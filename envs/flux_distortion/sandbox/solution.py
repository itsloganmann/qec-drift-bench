"""Starter solution for flux_distortion. Edit freely; keep the solve(data) -> dict interface.
As shipped it behaves like the trivial baseline: it keeps the nominal predistortion."""


def solve(data):
    stages = data["nominal_stages"]  # [{"amp": A, "tau_ns": tau}, ...] the stack now inverts

    # TODO: compare data["step"] (measured through the current predistortion, noise
    #       data["sigma"]) with a flat step and decide whether the line drifted (TASK.md).
    # TODO: return the stages of the line as it is now; the grader inverts them.
    return {"filters": stages, "fir": [1.0],
            "diagnosis": {"changed": False, "kinds": {}}}
