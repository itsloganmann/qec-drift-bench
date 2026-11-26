"""LAZY (review's pulse_blind_refit, reimplemented without eval/): always fit both traces and
re-optimise the design DRAG family on the fitted model, never report a change."""
import _kit as K


def solve(data):
    s, _, delta = K.estimate(data)
    return {"pulse": K.drag_refit(data, s, delta),
            "diagnosis": {"changed": False, "drive_scale": data["drive_scale_design_ghz"],
                          "f01_ghz": data["f01_design_ghz"]}}
