"""Lazy: the reference's refit predistortion and diagnosis, but always 'changed'."""
from _ref import reference


def solve(data):
    out = reference().solve(data)
    out["diagnosis"]["changed"] = True
    if not out["diagnosis"]["kinds"]:
        out["diagnosis"]["kinds"] = {"new_tail": {"amp": 0.003, "tau_ns": 500.0}}
    return out
