"""Failure modes for the decoder-agent family: one leaf per episode (docs/failure-taxonomy.md).

The gates are exclusive and exhaustive. Each episode takes the first that applies:
    D0 the episode never ran (a harness error, a refused subscription) -> harness_error
    D1 no decoder.py at the end                 -> no_decoder
    D2 decoder.py exists but was never scored   -> unscored (the row's score_error says why)
    D3 gap closed below 0                       -> worse_than_plain
    D4 what the decoder carries:
       nominal model, plain matching            -> nominal_plain
       nominal model, correlated matching       -> nominal_correlated
       a fitted model, plain matching           -> fitted_plain
       a fitted model, correlated matching      -> fitted_correlated

"Fitted" means the source holds a detector error model whose probabilities are not the nominal
circuit's, builds error instructions, a matching graph or a circuit with its own numbers, or
names a data file that the harness did not give it (a saved `fitted.dem`, for example). Flags,
true in any leaf:
`used_validation` and `tried_fit` are word matches on the code the agent ran, not meaning.

Each episode also gets a verdict under the absolute pass rule (`verdict`) and under the relative
rule (`verdict_rel`): passed, missed_diagnosis, missed_fix, missed_both, or no_score for the
leaves of D0 to D2. The leaf says what was shipped; the verdict says what it was worth.

Example:
    uv run python -m qec_drift.scoring.failure_modes_decoder \\
        data/agent_decoder/opus_5_5_medium.parquet
"""

from __future__ import annotations

import argparse
import json
import re
from functools import cache
from pathlib import Path

import pandas as pd

from qec_drift import paths
from qec_drift.agent import attempts
from qec_drift.agent import awareness as aw
from qec_drift.agent import decoder_task as dt
from qec_drift.agent.transcripts import matching_records, records

RELATIVE = 0.75  # of the honest adaptive decoder's recovery, the relative rule's bar
NO_SCORE = ("harness_error", "no_decoder", "unscored")
DECODER_LEAVES = (
    "harness_error", "no_decoder", "unscored", "worse_than_plain",
    "nominal_plain", "nominal_correlated", "fitted_plain", "fitted_correlated",
)  # fmt: skip
GIVEN_FILES = ("nominal.stim", "train.npz", "val.npz")
NOMINAL_SHARE = 0.9  # fewer known probabilities than this share means a fitted model
ERROR_P = re.compile(r"\berror\(([0-9][0-9.eE+-]*)\)")
# Any file name the source mentions with a data extension; one the harness did not give is a fit.
FILE_NAMES = re.compile(
    r"""['"]([\w./-]+\.(?:dem|stim|npy|npz|pkl|pickle|pt|pth|json|txt|csv|bin|h5|safetensors))['"]"""
)
OWN_ERRORS = re.compile(
    r"""DemInstruction\(\s*['"]error['"]|\.append\(\s*['"]error['"]"""
    r"""|\.add_edge\(|\.add_boundary_edge\(|stim\.Circuit\(\)"""
)
# Noise instructions written with a probability: an inlined or rebuilt circuit.
NOISE_P = re.compile(r"\b(?:X_ERROR|Z_ERROR|DEPOLARIZE[12])\(([0-9][0-9.eE+-]*)\)")
# A regex over noise lines of nominal.stim: the circuit is rewritten before the DEM is built.
EDITS_NOISE = re.compile(r"re\.\w+\([^\n]*(?:X_ERROR|Z_ERROR|DEPOLARIZE)")
AGREE = 0.9999  # share of identical test predictions that counts as the same decoder
REL_TOL = 1e-9  # a DEM probability this close to a nominal one is nominal (print rounding)
# A model built from computed text, not from a literal or from nominal.stim.
BUILT_MODEL = re.compile(r"stim\.(?:DetectorErrorModel|Circuit)\(([^\n]{0,120})")
IMPORTS = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
LIBRARIES = frozenset(
    "numpy np stim pymatching scipy torch sinter numba os sys re json pathlib math collections "
    "functools itertools typing time warnings gzip pickle io struct dataclasses random ctypes "
    "multiprocessing concurrent threading importlib __future__ copy operator heapq bisect "
    "array string textwrap contextlib abc enum statistics decimal fractions shutil tempfile "
    "glob fnmatch logging traceback inspect types weakref zlib hashlib base64 csv sqlite3 "
    "datetime calendar pprint reprlib numbers cmath".split()
)
FIT_WORDS = re.compile(
    r"estimat|calibrat|reweight|re-weight|\bp_?ij\b|two.point|pairwise|corrcoef|\bfit", re.I
)


@cache
def nominal_probabilities(d: int) -> frozenset[float]:
    dem = dt.nominal(d).detector_error_model(decompose_errors=True)
    return frozenset(float(i.args_copy()[0]) for i in dem.flattened() if i.type == "error")


def is_fitted(src: str, d: int) -> bool:
    """True when the decoder's model is not the nominal one: an inlined model or circuit with
    other probabilities, a model, graph or circuit built from its own numbers, a rewrite of the
    nominal circuit's noise lines, or files of its own."""
    probs = [float(x) for x in ERROR_P.findall(src)]
    if probs:  # an inlined DEM: fitted when any probability is not a nominal one
        known = sorted(nominal_probabilities(d))
        return any(not _near(p, known) for p in probs)
    noise = [round(float(x), 10) for x in NOISE_P.findall(src)]
    if noise and any(p != round(dt.P_NOMINAL, 10) for p in noise):
        return True  # a hand-edited circuit differs from nominal in a few lines, not most
    if OWN_ERRORS.search(src) or EDITS_NOISE.search(src) or own_module(src):
        return True
    if any(built_from_computed_text(arg) for arg in BUILT_MODEL.findall(src)):
        return True
    return any(Path(name).name not in GIVEN_FILES for name in FILE_NAMES.findall(src))


def _near(p: float, known: list[float]) -> bool:
    return any(abs(p - k) <= REL_TOL * max(k, 1e-12) for k in known)


def built_from_computed_text(arg: str) -> bool:
    """The argument text of a stim model constructor builds a model of the agent's own: it is
    not a string literal, not empty, and does not read nominal.stim."""
    arg = arg.lstrip()
    if not arg or arg[0] == ")" or "nominal.stim" in arg:
        return False
    if arg[0] not in "'\"":
        return True
    if arg.startswith(arg[0] * 3):
        return False  # a triple-quoted literal
    close = arg.find(arg[0], 1)
    if close < 0:
        return False  # a long literal that runs past the captured text
    after = arg[close + 1 :].lstrip()
    return bool(after) and after[0] not in "),"  # "'\n'.join(lines)": computed text


def own_module(src: str) -> bool:
    """The decoder imports a module that is not a library: code of the agent's own."""
    for a, b in IMPORTS.findall(src):
        top = (a or b).split(".")[0]
        if top not in LIBRARIES:
            return True
    return False


def by_behaviour(r: pd.Series) -> tuple[bool, bool] | None:
    """(fitted, correlated) from the share of test predictions identical to the nominal
    decoders, when the harness recorded it. None for older rows."""
    plain, corr = r.get("agree_nominal_plain"), r.get("agree_nominal_corr")
    if plain is None or corr is None or plain != plain or corr != corr:
        return None
    if plain >= AGREE:
        return False, False
    if corr >= AGREE:
        return False, True
    return True, "enable_correlations" in str(r.get("decoder_src") or "")


def classify_decoder(
    *,
    has_decoder: bool,
    scored: bool,
    gap: float,
    fitted: bool,
    correlated: bool,
    ran: bool = True,
) -> tuple[str, str]:
    """(leaf, gate) for one episode."""
    if not ran:
        return "harness_error", "D0"
    if not has_decoder:
        return "no_decoder", "D1"
    if not scored:
        return "unscored", "D2"
    if gap < 0:
        return "worse_than_plain", "D3"
    model = "fitted" if fitted else "nominal"
    return f"{model}_{'correlated' if correlated else 'plain'}", "D4"


def agent_code(trajectory: Path | None, rows: pd.DataFrame | None = None) -> dict[str, str]:
    """Task -> all code the agent ran, from the archived trajectory. Empty when there is none."""
    if trajectory is None or not Path(trajectory).is_file():
        return {}
    out = {}
    selected = (
        records(Path(trajectory)) if rows is None else matching_records(trajectory, rows).values()
    )
    for rec in selected:
        chunks = []
        for m in rec.get("messages", []):  # the API harness: run_python calls
            body = m.get("body") if m.get("role") == "assistant" else None
            body = json.loads(body) if isinstance(body, str) else (body or {})
            for b in body.get("content", []):
                if b.get("type") == "tool_use" and b.get("name") == "run_python":
                    chunks.append(str(b.get("input", {}).get("code", "")))
        for e in rec.get("events", []):  # Claude Code tool calls; Codex shell commands
            item = e.get("item") or {}
            if e.get("type") == "item.completed" and item.get("type") == "command_execution":
                chunks.append(str(item.get("command") or ""))
            if e.get("type") != "assistant":
                continue
            for b in (e.get("message") or {}).get("content", []):
                if b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    text = inp.get("command") or inp.get("content") or inp.get("new_string")
                    chunks.append(str(text or ""))
        out[rec["task"]] = "\n".join(chunks)
    return out


def _source(row: pd.Series, work: Path) -> str:
    stored = row.get("decoder_src")
    src = stored if isinstance(stored, str) else ""
    if src or not attempts.is_legacy(row) or _number(row, "decoder_bytes") == 0:
        return src
    path = work / str(row["task"]) / "decoder.py"  # rows from before the size limit was raised
    return path.read_text(errors="replace") if path.is_file() else ""


def _number(r: pd.Series, key: str) -> float:
    value = r.get(key)
    try:
        return float(value) if value is not None else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def verdicts(r: pd.Series, leaf: str) -> tuple[str, str]:
    """(verdict under the absolute rule, under the relative rule) for one scored episode."""
    if leaf in NO_SCORE:
        return "no_score", "no_score"
    diag = r.get("diagnosis_correct")
    diag = True if diag is None or diag != diag else bool(diag)  # tier 1 had no diagnosis
    gap, drift = _number(r, "gap_closed"), _number(r, "gap_drift")
    fix_abs = gap >= aw.PASS_GAP and (drift != drift or drift >= aw.PASS_GAP)
    span = _number(r, "ref_stale_corr") - _number(r, "ref_true_corr")
    known = _number(r, "ref_adaptive_corr")
    known = _number(r, "ref_pij_corr") if known != known else known  # stationary: the refit
    honest = (_number(r, "ref_stale_corr") - known) / span
    fix_rel = fix_abs and (drift != drift or honest != honest or drift >= RELATIVE * honest)

    def name(fix: bool) -> str:
        if diag and fix:
            return "passed"
        if fix:
            return "missed_diagnosis"
        return "missed_fix" if diag else "missed_both"

    return name(fix_abs), name(fix_rel)


def classify_arm(df: pd.DataFrame, work: Path, code: dict[str, str]) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        src = _source(r, work)
        gap = float(r["gap_closed"])
        exists = bool(src) or int(r.get("decoder_bytes") or 0) > 0
        seen = by_behaviour(r)
        fitted, correlated = seen or (
            bool(src) and is_fitted(src, int(r["d"])),
            "enable_correlations" in src,
        )
        leaf, gate = classify_decoder(
            has_decoder=exists, scored=gap == gap, gap=gap, fitted=fitted, correlated=correlated,
            ran=r.get("outcome") != "error",
        )  # fmt: skip
        verdict, verdict_rel = verdicts(r, leaf)
        ran = code.get(str(r["task"]))
        rows.append(dict(
            arm=r.get("arm"), task=r["task"], attempt_id=r.get("attempt_id"),
            outcome=r["outcome"], stop=r.get("stop"),
            turns=r["turns"], gap_closed=gap, leaf=leaf, gate=gate,
            verdict=verdict, verdict_rel=verdict_rel,
            score_error=r.get("score_error"),
            used_validation=None if ran is None else "val.npz" in ran,
            tried_fit=None if ran is None else bool(FIT_WORDS.search(ran)),
        ))  # fmt: skip
    return pd.DataFrame(rows)


def analyze_decoder(parquet: Path, trajectory: Path | None = None) -> pd.DataFrame:
    """Classify one arm's episodes and write `<arm>_failure_modes.parquet` next to the parquet."""
    parquet = Path(parquet)
    df = pd.read_parquet(parquet)
    arm = str(df["arm"].iloc[0]) if "arm" in df and len(df) else parquet.stem
    if trajectory is None:
        trajectory = paths.trajectories_dir() / f"decoder_{arm}.jsonl.gz"
    out = classify_arm(df, parquet.parent / "work" / arm, agent_code(trajectory, df))
    attempts.write_table(
        parquet.with_name(f"{parquet.stem}_failure_modes.parquet"), out.to_dict("records")
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("parquets", type=Path, nargs="+")
    args = ap.parse_args()
    cols = [
        "task",
        "outcome",
        "stop",
        "turns",
        "gap_closed",
        "leaf",
        "verdict_rel",
        "used_validation",
        "tried_fit",
    ]
    for parquet in args.parquets:
        out = analyze_decoder(parquet)
        print(f"== {parquet.stem}\n{out[cols].round(3).to_string(index=False)}\n")


if __name__ == "__main__":
    main()
