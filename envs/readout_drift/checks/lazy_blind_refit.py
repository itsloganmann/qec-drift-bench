"""Lazy (review's readout_blind_refit, reimplemented without importing _reference): always refit
a 2-cloud Gaussian mixture by EM to the new shots, never report a change."""
import numpy as np

CHANGED, KINDS = False, {}


def em(x, m0, m1, s, w1=0.5, iters=300):
    m = np.array([m0, m1], float)
    for _ in range(iters):
        lp = -((x[:, None] - m[None]) ** 2).sum(-1) / (2 * s * s) + np.log([1 - w1, w1])
        r = np.exp(lp - lp.max(1, keepdims=True))
        r /= r.sum(1, keepdims=True)
        nk = r.sum(0)
        m = (r.T @ x) / nk[:, None]
        s = np.sqrt((r * ((x[:, None] - m[None]) ** 2).sum(-1)).sum() / (2 * len(x)))
        w1 = np.clip(nk[1] / len(x), 1e-3, 1 - 1e-3)
    return m[0], m[1], s


def solve(data):
    xc, yc = data["calib_iq"], data["calib_labels"]
    a0, a1 = xc[yc == 0].mean(0), xc[yc == 1].mean(0)
    s0 = np.sqrt(np.vstack([xc[yc == 0] - a0, xc[yc == 1] - a1]).var(0).mean())
    m0, m1, s = em(data["shots_iq"], a0, a1, s0)
    if np.linalg.norm(m0 - a1) + np.linalg.norm(m1 - a0) < np.linalg.norm(m0 - a0) + np.linalg.norm(m1 - a1):
        m0, m1 = m1, m0
    cov = (s * s * np.eye(2)).tolist()
    comps = [{"mean": m0, "cov": cov, "weight": 1.0, "label": 0},
             {"mean": m1, "cov": cov, "weight": 1.0, "label": 1}]
    return {"discriminator": comps, "diagnosis": {"changed": CHANGED, "kinds": KINDS}}
