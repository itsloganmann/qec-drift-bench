"""The agent's model assessment: the fields it submits, how they are parsed, and how they score.

Two scores. The Brier score is the squared error of the reported probability that the nominal
model is adequate. The diagnosis is correct when the reported scope (none, local, global) is the
true one and, for a local change, the reported qubits overlap the true ones (Jaccard at least
LOCALIZE_MIN). A task is passed when the diagnosis is correct, the decoder closes at least
PASS_GAP of the gap to the best-known ceiling, and on a drift task it also recovers at least
PASS_GAP of the loss that the stale fit leaves: the agent must know what is wrong and fix it.
"""

from __future__ import annotations

import math
from typing import Any

from qec_drift.agent import drift

TEXT_LIMIT = 2000
QUBIT_LIMIT = 1000  # reported qubit indices kept
PASS_GAP = 0.5
LOCALIZE_MIN = 0.5
REPORT_FIELDS = {
    "model_adequate": {
        "type": "boolean",
        "description": "Does nominal.stim describe the hardware as it is now, deploy.npz included?",
    },
    "confidence": {"type": "integer", "description": "0 to 100, in your model_adequate answer"},
    "scope": {
        "type": "string",
        "enum": list(drift.SCOPES),
        "description": "Where the hardware differs from nominal.stim: none, local (one or a few "
        "qubits or one gate, the same ones all the time), global (most of the device), or moving "
        "(the bad location changes over time; list every qubit that was bad in deploy.npz)",
    },
    "changed_qubits": {
        "type": "array",
        "items": {"type": "integer"},
        "description": "For a local scope: the qubit indices (QUBIT_COORDS in nominal.stim) "
        "whose noise changed; for a gate, both qubits",
    },
    "mechanism": {
        "type": "string",
        "enum": list(drift.MECHANISMS),
        "description": "What changed on those qubits: readout (measurement and reset flips), "
        "gate (two-qubit gate noise), all (every error source), crosstalk (new correlated "
        "errors between neighbouring data qubits), or none",
    },
    "stationary": {
        "type": "boolean",
        "description": "Is the noise the same for every shot in deploy.npz (true), or does it "
        "change over time or from shot to shot (false)?",
    },
    "what_is_wrong": {"type": "string", "description": "One sentence, or 'nothing'"},
    "evidence": {"type": "string", "description": "What in the data supports it"},
}
PROMPT = (
    "\n\nThe team also needs your assessment of their model. In the submit call give "
    "model_adequate (does nominal.stim describe the hardware as it is now, the shots in "
    "deploy.npz included), confidence (0 to 100), scope (none, local, global or moving), "
    "changed_qubits "
    "(for a local or moving scope, the qubit indices from nominal.stim whose noise changed; "
    "for a moving fault, every qubit that was bad in deploy.npz), mechanism "
    "(readout, gate, all, crosstalk or none), stationary (within deploy.npz, is the noise the "
    "same for every shot, or does it change over time or from shot to shot within that batch; "
    "a change between the calibration files and deploy.npz alone does not make it "
    "non-stationary), what_is_wrong (one sentence, or "
    "'nothing') and evidence (what in the data supports it). A submit without the assessment "
    "counts as adequate at confidence 100 with scope none and stationary noise."
)


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def _as_confidence(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        x = float(value)
    except ValueError:
        return None
    if not math.isfinite(x) or not 0 <= x <= 100:
        return None
    return round(x)


def _as_choice(value: Any, choices: tuple[str, ...]) -> str:
    text = value.strip().lower() if isinstance(value, str) else ""
    return text if text in choices else ""


def _as_qubits(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[int] = []
    for v in value[:QUBIT_LIMIT]:
        if isinstance(v, bool):
            continue
        if isinstance(v, int) or (isinstance(v, str) and v.strip().lstrip("-").isdigit()):
            out.append(int(v))
        elif isinstance(v, float) and v.is_integer():
            out.append(int(v))
    return sorted(set(out))


def report_from(inp: dict) -> dict:
    """The agent's model assessment from a submit call.

    A missing or malformed field takes the documented default: adequate at confidence 100 with
    scope none. A missing scope on an inadequate report is "" and scores as wrong. Text is cut
    at TEXT_LIMIT characters.
    """
    adequate = _as_bool(inp.get("model_adequate"))
    confidence = _as_confidence(inp.get("confidence"))
    report_adequate = True if adequate is None else adequate
    scope = _as_choice(inp.get("scope"), drift.SCOPES)
    if adequate is None and "scope" not in inp:
        scope = "none"
    return dict(
        report_adequate=report_adequate,
        report_confidence=100 if confidence is None else confidence,
        report_scope=scope,
        report_qubits=_as_qubits(inp.get("changed_qubits")),
        report_mechanism=_as_choice(inp.get("mechanism"), drift.MECHANISMS),
        report_stationary=_as_bool(inp.get("stationary")) is not False,
        report_text=str(inp.get("what_is_wrong") or "")[:TEXT_LIMIT],
        report_evidence=str(inp.get("evidence") or "")[:TEXT_LIMIT],
    )


def brier(report: dict, adequate: bool) -> float:
    """Squared error of the reported probability that the model is adequate."""
    c = report["report_confidence"] / 100
    p = c if report["report_adequate"] else 1 - c
    return (p - float(adequate)) ** 2


def jaccard(a: set[int] | frozenset[int], b: set[int] | frozenset[int]) -> float:
    return len(a & b) / len(a | b) if a | b else float("nan")


def diagnosis(report: dict, truth: drift.Truth) -> dict:
    """How the reported diagnosis compares with the truth of the task."""
    overlap = float("nan")
    if truth.scope in ("local", "moving"):
        overlap = jaccard(set(report["report_qubits"]), truth.qubits)
    time_ok = report.get("report_stationary", True) == truth.stationary
    scope_ok = report["report_scope"] == truth.scope
    if truth.scope == "moving" and report["report_scope"] == "local" and time_ok:
        scope_ok = True  # "these qubits, and the noise changes over time" names a moving fault
    local_ok = truth.scope not in ("local", "moving") or overlap >= LOCALIZE_MIN
    return dict(
        truth_scope=truth.scope,
        truth_qubits=sorted(truth.qubits) if truth.scope in ("local", "moving") else [],
        truth_mechanism=truth.mechanism,
        truth_stationary=truth.stationary,
        localization=overlap,
        mechanism_correct=report["report_mechanism"] == truth.mechanism,
        diagnosis_correct=scope_ok and local_ok and time_ok,
    )


def passed(diagnosis_correct: bool, gap_closed: float, gap_drift: float = float("nan")) -> bool:
    """Diagnosis right, half the plain gap closed, and half the drift loss recovered (if any)."""
    ok = bool(diagnosis_correct) and gap_closed == gap_closed and gap_closed >= PASS_GAP
    if gap_drift == gap_drift:  # defined only on drift tasks
        ok = ok and gap_drift >= PASS_GAP
    return ok
