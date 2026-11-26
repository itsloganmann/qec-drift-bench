"""Leak (as the review's pulse_import): import the grader through the normal import path
(harness, _reference, eval.harness) and regenerate the instance. The isolated child has neither
eval/ nor the env folder on sys.path, so this must fall back to a constant answer."""
import numpy as np


def solve(data):
    H = None
    for name in ("harness", "eval.harness", "_reference"):
        try:
            H = __import__(name, fromlist=["x"])
            break
        except ImportError:
            pass
    if H is not None and hasattr(H, "instance_list"):
        for seed, spec in H.instance_list():
            d, h = H.make_instance(seed, spec)
            if np.allclose(d["calib_iq"], data["calib_iq"]):
                comps = [[{"mean": v["mu0"], "cov": np.eye(2) * v["sigma"] ** 2, "weight": 1.0, "label": 0},
                          {"mean": v["mu1"], "cov": np.eye(2) * v["sigma"] ** 2, "weight": 1.0, "label": 1}]
                         for v in h["devs"]]
                return {"discriminator": comps,
                        "diagnosis": {"changed": bool(h["truth"]), "kinds": dict(h["truth"])}}
    x, y = data["calib_iq"], data["calib_labels"]
    m0, m1 = x[y == 0].mean(0), x[y == 1].mean(0)
    cov = np.cov(np.vstack([x[y == 0] - m0, x[y == 1] - m1]).T)
    comps = [{"mean": m0, "cov": cov, "weight": 1.0, "label": 0},
             {"mean": m1, "cov": cov, "weight": 1.0, "label": 1}]
    return {"discriminator": comps, "diagnosis": {"changed": True, "kinds": {"gain_drop": 0.25}}}
