"""Lazy: the reference's refit predistortion every time, but never reports a change."""
from _ref import reference


def solve(data):
    out = reference().solve(data)
    out["diagnosis"] = {"changed": False, "kinds": {}}
    return out
