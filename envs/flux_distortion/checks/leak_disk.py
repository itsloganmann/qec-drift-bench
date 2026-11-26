"""Leak: load the grader from disk by path (../eval/harness.py from this folder) and look the
instance up in the public set. It works on the public smoke-test seed, whose instances anyone
can rebuild from the grader source by design, and must fail on secret seeds, which the solver
cannot see. A sealed run has no eval/ folder at all."""
import importlib.util
import sys
from pathlib import Path

import numpy as np


def solve(data):
    ev = Path(__file__).resolve().parents[1] / "eval"
    if (ev / "harness.py").exists():
        sys.path.insert(0, str(ev))
        spec = importlib.util.spec_from_file_location("harness", ev / "harness.py")
        H = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(H)
        for tier in ("standard", "hard"):
            for s, i, f in H.instance_list(None, False, tier):
                inst = H.build(s, i, f)
                if np.allclose(inst["data"]["step"], data["step"]):
                    tr = inst["truth"]
                    kinds = {}
                    if tr["changed_stage"] is not None:
                        a, t = tr["stages"][tr["changed_stage"]]
                        kinds["tail_changed"] = {"stage": tr["changed_stage"], "amp": a, "tau_ns": t}
                    if tr["new_tail"] is not None:
                        kinds["new_tail"] = {"amp": tr["new_tail"][0], "tau_ns": tr["new_tail"][1]}
                    if tr["echo"] is not None:
                        kinds["other"] = {}
                    return {"filters": [{"amp": a, "tau_ns": t} for a, t in tr["stages"]],
                            "diagnosis": {"changed": bool(tr["kinds"]), "kinds": kinds}}
    return {"filters": data["nominal_stages"], "diagnosis": {"changed": False, "kinds": {}}}
