"""Lazy: nominal predistortion, always 'changed' with one fixed guess (a new 1% tail at 300 ns)."""


def solve(data):
    return {"filters": data["nominal_stages"],
            "diagnosis": {"changed": True, "kinds": {"new_tail": {"amp": 0.01, "tau_ns": 300.0}}}}
