"""Grading rubric for flux_distortion: every instance's score as named, weighted checks.

One fixed rubric grades every instance, solver, seed and tier; harness.run_instance scores with
it, and each instance's report carries its checks. Every check is computed by script from the
hidden truth and the solver's answer (no LLM judge). A check is a gate (it must pass, value 1,
or the instance scores 0), weighted (it adds weight x value, value in [0, 1]) or a multiplier
(it scales the weighted sum). The weights are the ones TASK.md states. Licence: Apache-2.0.
"""

from __future__ import annotations

VERSION = "flux_distortion/rubric-v1"
RULES = ("control", "fix")
W_CALL_CONTROL, W_NOHARM = 0.4, 0.6
W_FIX, W_KIND, W_PARAM = 0.5, 0.25, 0.25

# id: (what failing it means, {rule: weight or role})
CHECKS = {
    "valid_answer": ("crashed, timed out, too many stages or taps, an amplitude or time "
                     "constant out of range, or an ill-typed diagnosis",
                     dict.fromkeys(RULES, "gate")),
    "change_call": ("false alarm on a control, or a missed change (gate)",
                    {"control": W_CALL_CONTROL, "fix": "gate"}),
    "fix_gap": ("the predistortion does not remove the test-program flux error the change "
                "opened", {"fix": W_FIX}),
    "no_harm": ("the predistortion makes the test-program error worse than the stale one "
                "(a quarter of the floor free, none at one floor)", {"control": W_NOHARM}),
    "kinds": ("wrong set of changed kinds (Jaccard overlap; an unlisted change is \"other\")",
              {"fix": W_KIND}),
    "params": ("a changed stage or new tail's amplitude or time constant off by more than 2 "
               "Cramer-Rao sigma (none at 4), or the wrong stage", {"fix": W_PARAM}),
}


def check(value: float, weight: float = 0.0, gate: bool = False, mult: bool = False) -> dict:
    out = {"v": float(value), "w": float(weight)}
    for k, on in (("gate", gate), ("mult", mult)):
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


def instance_checks(rule: str, call_right: bool, fix: float, kind: float, par: float) -> dict:
    """fix is the error removed on fix instances, else the no-harm credit."""
    c = {"valid_answer": check(1.0, gate=True),
         "change_call": check(call_right, W_CALL_CONTROL if rule == "control" else 0.0,
                              gate=True)}
    if rule == "control":
        c["no_harm"] = check(fix, W_NOHARM)
    else:
        c.update(fix_gap=check(fix, W_FIX), kinds=check(kind, W_KIND),
                 params=check(par, W_PARAM))
    return c
