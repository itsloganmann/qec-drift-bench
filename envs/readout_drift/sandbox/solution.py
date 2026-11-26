"""Starter solution for readout_drift. Edit freely; keep the solve(data) -> dict interface.
As shipped it behaves like the trivial baseline: it trusts the calibration."""
import numpy as np


def solve(data):
    x, y = data["calib_iq"], data["calib_labels"]
    m0, m1 = x[y == 0].mean(0), x[y == 1].mean(0)
    cov = np.cov(np.vstack([x[y == 0] - m0, x[y == 1] - m1]).T)

    # TODO: look at data["shots_iq"] (unlabeled, post-drift, batch index in data["shots_batch"])
    #       and decide whether the readout changed, which families and by how much (TASK.md).
    # TODO: refit the discriminator; you may return one list of components per batch.
    discriminator = [{"mean": m0, "cov": cov, "weight": 1.0, "label": 0},
                     {"mean": m1, "cov": cov, "weight": 1.0, "label": 1}]
    return {"discriminator": discriminator, "diagnosis": {"changed": False, "kinds": {}}}
