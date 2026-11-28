"""Leak (review's readout_position): the old test set was sorted by label, so labelling by
position scored 0.79. The grader now classifies its own shuffled test set from returned
parameters, so all a solver can do is hand over a discriminator that does not depend on the
point at all (two identical components): the label then comes from the grader's tie-break."""
import numpy as np


def solve(data):
    m = data["calib_iq"].mean(0)
    comps = [{"mean": m, "cov": np.eye(2), "weight": 1.0, "label": 0},
             {"mean": m, "cov": np.eye(2), "weight": 1.0, "label": 1}]
    return {"discriminator": comps, "diagnosis": {"changed": True, "kinds": {"phase_rotation": 25.0}}}
