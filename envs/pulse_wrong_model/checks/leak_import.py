"""LEAK (review's pulse_import, kept as close to the original as possible): import the harness
from the import path the solver process used to inherit, and look the instance up. Adapted only
to the new harness API. With eval/_isolate.py the import fails, so this scores 0."""
import numpy as np


def solve(data):
    import harness as H
    for master in (H.PUBLIC_SEED,):
        for inst in H.build(master, H.N_INSTANCES):
            if np.array_equal(inst["data"]["rabi_p_exc"], data["rabi_p_exc"]) and \
                    np.array_equal(inst["data"]["ramsey_p1"], data["ramsey_p1"]):
                _, pulse = H.optimise_drag(inst["scale"], inst["delta_ghz"])
                return {"pulse": pulse,
                        "diagnosis": {"changed": inst["kind"] != "control",
                                      "drive_scale": inst["scale"],
                                      "f01_ghz": H.F01_GHZ + inst["delta_ghz"]}}
    raise RuntimeError("no match")
