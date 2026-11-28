"""Grading rubric for readout_drift: every instance's score as named, weighted checks.

One fixed rubric grades every instance, solver, seed and tier; harness.evaluate scores with it,
and each instance's report carries its checks. Every check is computed by script from the hidden
truth and the solver's answer (no LLM judge). A check is a gate (it must pass, value 1, or the
instance scores 0), weighted (it adds weight x value, value in [0, 1]) or a multiplier (it scales
the weighted sum). The weights are the ones TASK.md states. Licence: Apache-2.0.
"""

from __future__ import annotations

VERSION = "readout_drift/rubric-v1"
RULES = ("control", "fix", "diagnosis_only")
W_FIX, W_CHANGED, W_KIND, W_MAG = 0.6, 0.15, 0.15, 0.10

# id: (what failing it means, {rule: weight or role})
CHECKS = {
    "valid_answer": ("crashed, timed out, too many or invalid components, or ill-typed "
                     "diagnosis", dict.fromkeys(RULES, "gate")),
    "change_call": ("false alarm on a control, or a missed change (gate)",
                    dict.fromkeys(RULES, W_CHANGED)),
    "fix_gap": ("the discriminator does not close the error gap the change opened",
                {"fix": W_FIX}),
    "no_harm": ("the discriminator is worse than the stale one (0.2 percentage points free, none at 1.2)",
                {"control": W_FIX, "diagnosis_only": W_FIX}),
    "kinds": ("wrong set of changed families (Jaccard overlap; an unlisted change is \"other\")",
              dict.fromkeys(RULES, W_KIND)),
    "magnitudes": ("a graded family's size outside its tolerance", dict.fromkeys(RULES, W_MAG)),
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


def instance_checks(rule: str, call_right: bool, fix: float, kind: float, mag: float) -> dict:
    """fix is the gap closed on fix instances, else the no-harm credit (harness.run_instance)."""
    return {"valid_answer": check(1.0, gate=True),
            "change_call": check(call_right, W_CHANGED, gate=True),
            ("fix_gap" if rule == "fix" else "no_harm"): check(fix, W_FIX),
            "kinds": check(kind, W_KIND),
            "magnitudes": check(mag, W_MAG)}
