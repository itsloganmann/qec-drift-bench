"""Grading rubric for pulse_wrong_model: every instance's score as named, weighted checks.

One fixed rubric grades every instance, solver, seed and tier; harness.evaluate scores with it,
and each instance's report carries its checks. Every check is computed by script from the hidden
truth and the solver's answer (no LLM judge). A check is a gate (it must pass, value 1, or the
instance scores 0), weighted (it adds weight x value, value in [0, 1]), a multiplier (it scales
the weighted sum) or a part (reported only; the diagnosis check is the product of its parts).
The weights are the ones TASK.md states. Licence: Apache-2.0.
"""

from __future__ import annotations

VERSION = "pulse_wrong_model/rubric-v1"
RULES = ("control", "fix", "diagnosis")
W_FIX, W_DIAG = 0.6, 0.4
PARTS = ("scale", "f01", "compression", "other")

# id: (what failing it means, {rule: weight or role})
_PART = {"fix": "part", "diagnosis": "part"}
CHECKS = {
    "valid_answer": ("crashed, timed out, wrong pulse length, over the amplitude cap, or "
                     "ill-typed diagnosis", dict.fromkeys(RULES, "gate")),
    "change_call": ("false alarm on a control, or a missed change (gate)",
                    {"control": W_DIAG, "fix": "gate", "diagnosis": "gate"}),
    "fix_gap": ("the pulse does not close the infidelity gap (in decades) the change opened",
                {"fix": W_FIX}),
    "no_harm": ("the pulse is worse than the design pulse (0.1 decade free, none at 1)",
                {"control": W_FIX, "diagnosis": "multiplier"}),
    "diagnosis": ("product of the four parts below", {"fix": W_DIAG, "diagnosis": 1.0}),
    "diag_scale": ("drive scale off by more than 2 Cramer-Rao sigma (none at 4)", _PART),
    "diag_f01": ("qubit frequency off by more than 2 sigma (none at 4)", _PART),
    "diag_compression": ("compression off by more than 2 sigma (none at 4)", _PART),
    "diag_other": ("wrong `other` flag (hard tier: an effect outside the model's form; "
                   "always right in the standard tier)", _PART),
}


def check(value: float, weight: float = 0.0, gate: bool = False, mult: bool = False,
          part: bool = False) -> dict:
    out = {"v": float(value), "w": float(weight)}
    for k, on in (("gate", gate), ("mult", mult), ("part", part)):
        if on:
            out[k] = True
    return out


def total(checks: dict) -> float:
    """0 if a gate fails; else the weighted sum times every multiplier."""
    if any(c.get("gate") and c["v"] < 1 for c in checks.values()):
        return 0.0
    s = sum(c["w"] * c["v"] for c in checks.values())
    for c in checks.values():
        if c.get("mult"):
            s *= c["v"]
    return float(s)


def invalid() -> dict:
    return {"valid_answer": check(0.0, gate=True)}


def instance_checks(rule: str, call_right: bool, fix: float, noharm: float,
                    parts: dict) -> dict:
    """parts: {name: credit} for PARTS (harness.score_one); fix is used on fix instances."""
    c = {"valid_answer": check(1.0, gate=True),
         "change_call": check(call_right, W_DIAG if rule == "control" else 0.0, gate=True)}
    if rule == "control":
        c["no_harm"] = check(noharm, W_FIX)
        return c
    d = 1.0
    for p in PARTS:
        d *= parts[p]
        c[f"diag_{p}"] = check(parts[p], part=True)
    if rule == "fix":
        c["fix_gap"] = check(fix, W_FIX)
        c["diagnosis"] = check(d, W_DIAG)
    else:
        c["diagnosis"] = check(d, 1.0)
        c["no_harm"] = check(noharm, mult=True)
    return c
