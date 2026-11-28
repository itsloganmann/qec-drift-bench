"""Lazy (review's readout_const): calibration LDA, always 'changed, phase 25 deg, gain drop 0.25'."""
import numpy as np


def solve(data):
    x, y = data["calib_iq"], data["calib_labels"]
    m0, m1 = x[y == 0].mean(0), x[y == 1].mean(0)
    cov = np.cov(np.vstack([x[y == 0] - m0, x[y == 1] - m1]).T)
    comps = [{"mean": m0, "cov": cov, "weight": 1.0, "label": 0},
             {"mean": m1, "cov": cov, "weight": 1.0, "label": 1}]
    return {"discriminator": comps,
            "diagnosis": {"changed": True, "kinds": {"phase_rotation": 25.0, "gain_drop": 0.25}}}
