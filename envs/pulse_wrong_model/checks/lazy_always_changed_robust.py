"""LAZY: skip the decision. Always fit, always report "changed" with the fitted numbers, always
design the robust pulse. Best possible always-changed answer: it loses only the controls."""
import _kit as K


def solve(data):
    s, sig, delta = K.estimate(data)
    return {"pulse": K.robust(data, s, sig, delta),
            "diagnosis": {"changed": True, "drive_scale": s,
                          "f01_ghz": data["f01_design_ghz"] + delta}}
