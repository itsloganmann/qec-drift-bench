"""Reference solution for readout_drift: full-likelihood drift-model fit with model selection.

1. Calibration: maximum-likelihood fit of the labeled shots to the stated device model
   (two isotropic clouds, the T1 decay tail along the segment, symmetric preparation error).
2. New shots: for every candidate model (no change, each family, pairs of families) maximise
   the likelihood of the unlabeled shots over the drift parameters, profiling out the unknown
   |1> population of each of the 8 batches by EM. Centres move as the stated drift model says,
   starting from the fitted calibration centres; the resonator response uses the nominal model.
3. Pick the model by penalised likelihood; report the families whose fitted size is above the
   no-change floor. The discriminator is the Bayes rule of the fitted model for each batch,
   with the T1 tail written as 8 Gaussian components along the segment.
"""
from itertools import combinations

import numpy as np
from scipy.optimize import minimize

FAMS = ("phase_rotation", "phase_ramp", "gain_drop", "resonator_shift", "noise_growth", "t1_drop")
PAR = {"phase_rotation": "phi", "phase_ramp": "ramp", "gain_drop": "lg",
       "resonator_shift": "dk", "noise_growth": "ls", "t1_drop": "lf"}
STARTS = {"phi": [-20.0, 0.0, 20.0], "ramp": [-20.0, 0.0, 20.0], "lg": [np.log(0.75), 0.0],
          "dk": [-0.25, 0.0, 0.25], "ls": [0.0, np.log(1.3)], "lf": [0.0, np.log(3.0), np.log(10.0)]}
NEUTRAL = {"phi": 0.0, "ramp": 0.0, "lg": 0.0, "dk": 0.0, "ls": 0.0, "lf": 0.0}
PENALTY = 8.0      # log-likelihood a family must add to enter the model
N_SEG = 8          # Gaussian components for the T1 tail in the returned discriminator
U, WU = np.polynomial.legendre.leggauss(16)
U, WU = (U + 1) / 2, WU / 2


def gauss(x, m, s):
    return np.exp(-((x - m) ** 2).sum(-1) / (2 * s * s)) / (2 * np.pi * s * s)


def dens(x, m0, m1, s, r):
    """Densities of a |0> shot and of a |1> shot (with decay inside the window) at points x.
    m0, m1 may be per-point arrays (n, 2); s is a scalar."""
    f0 = gauss(x, m0, s)
    f1 = np.exp(-r) * gauss(x, m1, s)
    for u, w in zip(U, WU):
        f1 = f1 + w * r * np.exp(-r * u) * gauss(x, u * m1 + (1 - u) * m0, s)
    return f0, f1


def fit_calibration(x, y, nom):
    m0, m1 = x[y == 0].mean(0), x[y == 1].mean(0)
    s0 = np.sqrt(np.vstack([x[y == 0] - m0, x[y == 1] - m1]).var(0).mean())
    r0 = nom["T_int_us"] / nom["T1_us"]

    def nll(v):
        a, b, s, r, pt = v[:2], v[2:4], np.exp(v[4]), np.exp(v[5]), 1 / (1 + np.exp(-v[6]))
        f0, f1 = dens(x, a, b, s, r)
        lik = np.where(y == 0, (1 - pt) * f0 + pt * f1, (1 - pt) * f1 + pt * f0)
        prior = 0.5 * ((v[5] - np.log(r0)) / 0.15) ** 2  # nominal T1 is good to about 15%
        return -np.log(lik + 1e-300).sum() + prior

    v0 = np.r_[m0, m1, np.log(s0), np.log(r0), np.log(nom["p_thermal"] / (1 - nom["p_thermal"]))]
    v = minimize(nll, v0, method="L-BFGS-B").x
    return v[:2], v[2:4], np.exp(v[4]), np.exp(v[5]), 1 / (1 + np.exp(-v[6]))


def response(nom, f_s):
    k2 = nom["kappa_MHz"] / 2.0
    z = nom["amplitude"] * np.exp(1j * nom["theta0_rad"]) * k2 / (k2 + 1j * (f_s - nom["drive_offset_MHz"]))
    return np.array([z.real, z.imag])


class Model:
    def __init__(self, data):
        nom = self.nom = data["nominal"]
        self.f = nom["gain_noise_fraction"]
        self.nb = int(data["n_batches"])
        self.c0, self.c1, self.sc, self.rc, self.pt = fit_calibration(data["calib_iq"], data["calib_labels"], nom)
        self.x, self.b = data["shots_iq"], data["shots_batch"]
        self.base = response(nom, nom["chi_MHz"]), response(nom, -nom["chi_MHz"])
        self.w = np.full(self.nb, 0.5)
        self.single = {}

    def device(self, phi=0.0, ramp=0.0, lg=0.0, dk=0.0, ls=0.0, lf=0.0):
        """Per-batch centres (nb, 2) x 2, width and decay rate for drift parameters."""
        g, d = np.exp(lg), dk * self.nom["kappa_MHz"]
        a0 = self.c0 + response(self.nom, self.nom["chi_MHz"] + d) - self.base[0]
        a1 = self.c1 + response(self.nom, -self.nom["chi_MHz"] + d) - self.base[1]
        ang = np.radians(phi + ramp * (np.arange(self.nb) + 1) / self.nb)
        c, s = np.cos(ang), np.sin(ang)
        rot = lambda a: g * np.stack([c * a[0] - s * a[1], s * a[0] + c * a[1]], 1)  # noqa: E731
        sig = self.sc * np.sqrt(self.f * g * g + 1 - self.f) * np.exp(ls)
        return rot(a0), rot(a1), sig, self.rc * np.exp(lf)

    def loglik(self, **par):
        m0, m1, s, r = self.device(**par)
        f0, f1 = dens(self.x, m0[self.b], m1[self.b], s, r)
        A, B = (1 - self.pt) * f0 + self.pt * f1, (1 - self.pt) * f1 + self.pt * f0
        w = self.w
        for _ in range(15):  # EM for the |1> population of each batch (warm start)
            wb = w[self.b]
            resp = wb * B / (A + wb * (B - A) + 1e-300)
            w = np.clip(np.bincount(self.b, resp, self.nb) / np.bincount(self.b, minlength=self.nb), 1e-3, 1 - 1e-3)
        self.w = w
        wb = w[self.b]
        return float(np.log(A + wb * (B - A) + 1e-300).sum())

    def fit(self, fams):
        names = [PAR[f] for f in fams]
        if not names:
            return self.loglik(), {}
        if len(names) == 1:
            x0s = [(v,) for v in STARTS[names[0]]]
        else:  # pairs start from the single-family optima
            a, b = (self.single[n] for n in names)
            x0s = [(a, b), (a, NEUTRAL[names[1]]), (NEUTRAL[names[0]], b)]
        best = None
        for x0 in x0s:
            r = minimize(lambda v: -self.loglik(**dict(zip(names, v))), x0, method="Nelder-Mead",
                         options={"xatol": 1e-4, "fatol": 1e-3, "maxiter": 600})
            if best is None or r.fun < best.fun:
                best = r
        if len(names) == 1:
            self.single[names[0]] = float(best.x[0])
        return -best.fun, dict(zip(names, best.x))


def magnitudes(par, f, kappa):
    out = {}
    for fam, key in PAR.items():
        if key not in par:
            continue
        v = par[key]
        g = np.exp(v)
        out[fam] = float({"phi": v, "ramp": v, "lg": 1 - g / np.sqrt(f * g * g + 1 - f),
                          "dk": v * kappa, "ls": g - 1, "lf": g}[key])
    return out


def above_floor(fam, m, floor, kappa, rc):
    if fam == "t1_drop":  # floor is on the rise of the in-window decay probability
        return np.exp(-rc) - np.exp(-rc * m) >= floor["t1_drop_decay_increase"]
    lim = {"resonator_shift": floor["resonator_shift_kappa"] * kappa}.get(fam, floor.get(fam))
    return abs(m) > lim


def components(m0, m1, s, r):
    cov = (s * s * np.eye(2)).tolist()
    comps = [{"mean": m0.tolist(), "cov": cov, "weight": 1.0, "label": 0},
             {"mean": m1.tolist(), "cov": cov, "weight": float(np.exp(-r)), "label": 1}]
    for k in range(N_SEG):
        u = (k + 0.5) / N_SEG
        w = float(np.exp(-r * k / N_SEG) - np.exp(-r * (k + 1) / N_SEG))
        comps.append({"mean": (u * m1 + (1 - u) * m0).tolist(), "cov": cov, "weight": max(w, 1e-12), "label": 1})
    return comps


def solve(data):
    M = Model(data)
    kappa = M.nom["kappa_MHz"]
    fits = {(): M.fit(())}
    for fam in FAMS:
        fits[(fam,)] = M.fit((fam,))
    top = sorted(FAMS, key=lambda fm: -fits[(fm,)][0])[:2]
    for pr in combinations(FAMS, 2):
        if pr[0] in top or pr[1] in top:
            fits[pr] = M.fit(pr)
    best = max(fits, key=lambda k: fits[k][0] - PENALTY * len(k))
    ll, par = fits[best]
    mags = magnitudes(par, M.f, kappa)
    kinds = {k: v for k, v in mags.items() if above_floor(k, v, data["no_change_floor"], kappa, M.rc)}
    m0, m1, s, r = M.device(**par)
    disc = [components(m0[b], m1[b], s, r) for b in range(M.nb)]
    return {"discriminator": disc,
            "diagnosis": {"changed": bool(kinds), "kinds": kinds,
                          "model": list(best), "loglik_gain": round(ll - fits[()][0], 1)}}
