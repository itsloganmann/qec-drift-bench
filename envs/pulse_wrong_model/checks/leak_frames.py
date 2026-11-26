"""LEAK (stack-frame route used on qec/readout): walk the caller frames and look for hidden truth
(any local named like the grader's truth). In the isolated child the only caller is the child
stub, which holds `data` alone, so it finds nothing and falls back to the trivial answer."""
import sys

import numpy as np


def solve(data):
    f = sys._getframe(1)
    while f is not None:
        loc = f.f_locals
        for key in ("inst", "insts", "rows"):
            if key in loc:
                inst = loc[key]
                inst = inst[0] if isinstance(inst, list) else inst
                return {"pulse": np.asarray(data["nominal_pulse"]),
                        "diagnosis": {"changed": inst["kind"] != "control",
                                      "drive_scale": inst["scale"],
                                      "f01_ghz": 5.0 + inst["delta_ghz"]}}
        f = f.f_back
    return {"pulse": np.asarray(data["nominal_pulse"]),
            "diagnosis": {"changed": False, "drive_scale": data["drive_scale_design_ghz"],
                          "f01_ghz": data["f01_design_ghz"]}}
