"""LAZY (review's pulse_blind_robust, reimplemented without eval/): always fit, always design the
robust 24-sample pulse around the fit, never report a change."""
import _kit as K


def solve(data):
    s, sig, delta = K.estimate(data)
    return {"pulse": K.robust(data, s, sig, delta),
            "diagnosis": {"changed": False, "drive_scale": data["drive_scale_design_ghz"],
                          "f01_ghz": data["f01_design_ghz"]}}
