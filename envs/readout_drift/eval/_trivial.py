"""Trivial baseline: trust the calibration (LDA on the labeled shots), report no change."""
import numpy as np


def solve(data):
    x, y = data["calib_iq"], data["calib_labels"]
    m0, m1 = x[y == 0].mean(0), x[y == 1].mean(0)
    cov = np.cov(np.vstack([x[y == 0] - m0, x[y == 1] - m1]).T)
    comps = [{"mean": m0, "cov": cov, "weight": 1.0, "label": 0},
             {"mean": m1, "cov": cov, "weight": 1.0, "label": 1}]
    return {"discriminator": comps, "diagnosis": {"changed": False, "kinds": {}}}
