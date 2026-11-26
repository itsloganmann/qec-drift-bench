"""Trivial baseline: trust the design model, say nothing changed. Licence: Apache-2.0."""
import numpy as np


def solve(data):
    return {"pulse": np.asarray(data["nominal_pulse"]),
            "diagnosis": {"changed": False, "drive_scale": data["drive_scale_design_ghz"],
                          "f01_ghz": data["f01_design_ghz"]}}
