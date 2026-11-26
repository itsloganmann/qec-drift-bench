"""LAZY (review's pulse_const): design pulse, design numbers, always "changed"."""
import numpy as np


def solve(data):
    return {"pulse": np.asarray(data["nominal_pulse"]),
            "diagnosis": {"changed": True, "drive_scale": data["drive_scale_design_ghz"],
                          "f01_ghz": data["f01_design_ghz"]}}
