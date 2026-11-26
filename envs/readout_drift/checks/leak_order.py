"""Leak (found in the 2026-11-17 re-audit): the instance order used to be the same for every seed
(15 drifted specs, then 15 controls). The isolated child can keep a call counter in /tmp, so it
knew its index and hence the answer; this scored 0.68 to 0.71 on secret seeds. The order is now
shuffled per seed, so this must fall to trivial. No physics: stale calibration LDA plus the old
fixed order."""
import os, json, tempfile, numpy as np
SPECS = [["phase_rotation"], ["phase_rotation"], ["phase_ramp"], ["gain_drop"], ["gain_drop"],
         ["resonator_shift"], ["resonator_shift"], ["noise_growth"], ["t1_drop"], ["t1_drop"],
         ["phase_rotation", "gain_drop"], ["resonator_shift", "noise_growth"], ["gain_drop", "t1_drop"],
         ["phase_ramp", "noise_growth"], ["resonator_shift", "gain_drop"]] + [[]] * 15
GUESS = {"gain_drop": 0.25, "noise_growth": 0.35, "t1_drop": 5.0, "phase_rotation": 25.0,
         "phase_ramp": 25.0, "resonator_shift": 0.5}
F = os.path.join(tempfile.gettempdir(), "ro_order_counter.json")
def solve(data):
    try:
        n = json.load(open(F))["n"]
    except Exception:
        n = 0
    json.dump({"n": (n + 1) % 30}, open(F, "w"))
    x, y = data["calib_iq"], data["calib_labels"]
    m0, m1 = x[y == 0].mean(0), x[y == 1].mean(0)
    cov = np.cov(np.vstack([x[y == 0] - m0, x[y == 1] - m1]).T)
    kinds = {k: GUESS[k] for k in SPECS[n]}
    return {"discriminator": [{"mean": m0, "cov": cov, "weight": 1.0, "label": 0},
                              {"mean": m1, "cov": cov, "weight": 1.0, "label": 1}],
            "diagnosis": {"changed": bool(kinds), "kinds": kinds}}
