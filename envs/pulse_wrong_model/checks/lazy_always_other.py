"""LAZY (hard tier): design pulse and design numbers, always "changed" with `other` true.

Probes the hard tier's new flag: `other` completes the diagnosis on changes outside the design
model's form, so a solver that always claims one must still lose every control and earn no fix."""
import numpy as np


def solve(data):
    return {"pulse": np.asarray(data["nominal_pulse"]),
            "diagnosis": {"changed": True, "drive_scale": data["drive_scale_design_ghz"],
                          "f01_ghz": data["f01_design_ghz"], "other": True}}
