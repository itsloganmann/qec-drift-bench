"""Reference for flux_distortion: model comparison over the listed drifts, then exact refit.

Method. The measured step through the nominal predistortion is modelled exactly (cascade of
first-order stages, as TASK.md states) with every nominal stage free inside its stated wander
(a Gaussian prior), and compared under four hypotheses: no drift, one stage changed (each
stage in turn, its prior removed), a new tail (multi-start over time constants), and the best
single change plus the other kind. Starts are found with the first-order (sum of exponentials)
approximation and refined with the exact model by weighted least squares
(scipy.optimize.least_squares). A hypothesis must beat the simpler one by PENALTY per extra free
parameter (a BIC-like rule, Schwarz 1978, doi:10.1214/aos/1176344136). The change call is made
on effect size: the fitted line's predicted stale test-program error against the floor. The
predistortion returned inverts the fitted stages. Trusts the stated model; never reports "other".
Licence: Apache-2.0.
"""
import numpy as np
from scipy.optimize import least_squares
from scipy.signal import lfilter

WANDER_AMP, WANDER_TAU = 0.03, 0.02       # stated in TASK.md
NEW_TAU, NEW_SEP = (20.0, 5000.0), 2.5   # a new tail sits 2.5x or more from every nominal tau
PENALTY = 12.0                            # chi^2 units per extra free parameter
N_STARTS = 12


class Line:
    def __init__(self, data):
        self.dt = 1.0 / data["sample_rate_gsps"]
        self.t, self.y, self.s = (np.asarray(data[k], float) for k in ("t_ns", "step", "sigma"))
        self.nom = [(float(s["amp"]), float(s["tau_ns"])) for s in data["nominal_stages"]]
        self.idx = np.round(self.t / self.dt).astype(int)
        n = self.idx[-1] + 2
        self.pre_step = self.predistort(np.ones(n), self.nom)
        self.floor = float(data["floor_mse"])

    def ba(self, amp, tau):
        lam = np.exp(-self.dt / tau)
        return np.array([1.0 + amp, -(lam + amp)]), np.array([1.0, -lam])

    def line(self, x, stages):
        for a, t in stages:
            b, den = self.ba(a, t)
            x = lfilter(b, den, x)
        return x

    def predistort(self, x, stages):
        for a, t in stages:
            b, den = self.ba(a, t)
            x = lfilter(den, b, x)
        return np.clip(x, -1.5, 1.5)

    def exact(self, stages):
        return self.line(self.pre_step, stages)[self.idx]

    def approx(self, stages):
        f = lambda st: sum(a * np.exp(-self.t / t) for a, t in st)  # noqa: E731
        return 1.0 + f(stages) - f(self.nom)

    def program_mse(self, true, stages):
        n = lambda ns: int(round(ns / self.dt))  # noqa: E731
        err = []
        for on, neg, idle in ((60, 0, 1000), (30, 30, 1000), (2000, 0, 3000)):
            w = np.concatenate([np.ones(n(on)), -np.ones(n(neg)), np.zeros(n(idle))])
            err.append(self.line(self.predistort(w, stages), true) - w)
        w = np.zeros(n(8 * 400 + 2000))
        for k in range(8):
            w[n(400 * k):n(400 * k + 60)] = 1.0
        err.append(self.line(self.predistort(w, stages), true) - w)
        return float(np.mean(np.concatenate(err) ** 2))

    # -------- fitting --------
    def fit(self, free, new, x0=None, exact=True):
        """free: index of the stage without prior (or None); new: whether a new tail exists.
        Parameters: per stage (amp, log tau), then the new tail's (amp, log tau)."""
        k = len(self.nom)
        p0 = np.array([v for a, t in self.nom for v in (a, np.log(t))])
        sd = np.array([v for a, _ in self.nom for v in (max(abs(a), 1e-4) * WANDER_AMP / 1.7,
                                                        WANDER_TAU / 1.7)])
        if x0 is None:
            x0 = p0.copy() if not new else np.concatenate([p0, [0.0, np.log(300.0)]])
        model = self.exact if exact else self.approx

        def unpack(x):
            st = [(x[2 * i], np.exp(x[2 * i + 1])) for i in range(k)]
            return st + ([(x[2 * k], np.exp(x[2 * k + 1]))] if new else [])

        def res(x):
            r = (model(unpack(x)) - self.y) / self.s
            pr = (x[:2 * k] - p0) / sd
            if free is not None:
                pr[2 * free:2 * free + 2] = 0.0
            return np.concatenate([r, pr])

        lo = np.full(x0.size, -np.inf)
        hi = np.full(x0.size, np.inf)
        lo[1::2], hi[1::2] = np.log(0.3), np.log(5e4)
        lo[0::2], hi[0::2] = -0.3, 0.3
        x0 = np.clip(x0, lo + 1e-9, hi - 1e-9)
        r = least_squares(res, x0, bounds=(lo, hi), x_scale="jac", max_nfev=200)
        return float(np.sum(r.fun ** 2)), r.x, unpack(r.x)

    def fit_new(self, free, base_x=None):
        """New tail with multi-start over its time constant (starts on the approximation)."""
        best = None
        far = lambda lt: min(abs(lt - np.log(t)) for _, t in self.nom) >= np.log(NEW_SEP)  # noqa: E731
        for lt in filter(far, np.linspace(np.log(NEW_TAU[0]), np.log(NEW_TAU[1]), 3 * N_STARTS)):
            for a0 in (-0.004, 0.004):
                p = base_x if base_x is not None else np.array(
                    [v for a, t in self.nom for v in (a, np.log(t))])
                c, x, _ = self.fit(free, True, np.concatenate([p[:2 * len(self.nom)], [a0, lt]]),
                                   exact=False)
                if far(x[-1]) and (best is None or c < best[0]):
                    best = (c, x)
        if best is None:
            return np.inf, None, None
        c, x, st = self.fit(free, True, best[1])
        return (c, x, st) if far(x[-1]) else (np.inf, None, None)


def hypotheses(L):
    """Fit every hypothesis; returns {name: (cost, x, stages)} and {name: extra parameters}."""
    k = len(L.nom)
    cands = {"none": L.fit(None, False)}
    for i in range(k):
        cands[f"tail{i}"] = L.fit(i, False)
    cands["new"] = L.fit_new(None)
    nparams = {"none": 0, "new": 2, **{f"tail{i}": 2 for i in range(k)}}
    single = min((n for n in cands if n != "none" and cands[n][1] is not None),
                 key=lambda n: cands[n][0] + PENALTY * nparams[n])
    if single == "new":
        for i in range(k):
            c, x, st = L.fit(i, True, cands["new"][1])
            cands[f"tail{i}+new"] = (c, x, st) if min(
                abs(x[-1] - np.log(t)) for _, t in L.nom) >= np.log(NEW_SEP) else (np.inf, x, st)
            nparams[f"tail{i}+new"] = 4
    else:
        cands[f"{single}+new"] = L.fit_new(int(single[4:]), cands[single][1])
        nparams[f"{single}+new"] = 4
    return cands, nparams


def best(cands, nparams, extra=0.0):
    """Name and penalised cost of the best hypothesis."""
    pick = min(cands, key=lambda n: cands[n][0] + PENALTY * nparams[n])
    return pick, cands[pick][0] + PENALTY * nparams[pick] + extra


def answer(L, pick, x, stages, changed=None):
    k = len(L.nom)
    if changed is None:
        changed = pick != "none" and L.program_mse(stages, L.nom) >= L.floor
    kinds = {}
    if changed:
        for part in pick.split("+"):
            if part.startswith("tail"):
                i = int(part[4:])
                kinds["tail_changed"] = {"stage": i, "amp": float(x[2 * i]),
                                         "tau_ns": float(np.exp(x[2 * i + 1]))}
            elif part == "new":
                kinds["new_tail"] = {"amp": float(x[2 * k]), "tau_ns": float(np.exp(x[2 * k + 1]))}
    return {"filters": [{"amp": float(a), "tau_ns": float(t)} for a, t in stages],
            "diagnosis": {"changed": bool(changed), "kinds": kinds}}


def solve(data):
    L = Line(data)
    cands, nparams = hypotheses(L)
    pick, _ = best(cands, nparams)
    _, x, stages = cands[pick]
    return answer(L, pick, x, stages)
