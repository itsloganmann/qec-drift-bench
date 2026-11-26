"""Reference solution for pulse_wrong_model: the strongest method we know. Licence: Apache-2.0.

1. Joint maximum-likelihood fit of both traces with the exact models TASK.md states
   (4-level Rabi simulation with drive compression, Ramsey formula): parameters drive scale
   s, frequency drift delta, compression kc, Ramsey T2 (nuisance). Binomial likelihood.
   Standard errors from the Fisher information.
2. A parameter has changed if it is more than 3 standard errors from design.
3. If anything changed: design a robust 24-sample delivered pulse v (GRAPE with exact
   gradients) that minimises the mean infidelity over s_est + k sigma_s, k = -2..2, at
   delta_est, with |v| <= 1 - kc; then predistort each sample, solving |u| (1 - kc |u|^2) = |v|.
   Otherwise keep the design pulse. Four optimiser restarts (fixed, so the answer is the same
   on any machine).
Uses only `data` and TASK.md. No access to the harness.
"""
import numpy as np
from scipy.optimize import minimize, minimize_scalar

TWO_PI = 2.0 * np.pi
NSIG = 3.0
ROBUST_K = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
RESTARTS = 4    # the robust ensemble error stalls near 1e-5.5, 50x under the 1e-4 floor


class Model:
    def __init__(self, data):
        self.d = data
        n = data["levels_hint"]
        b = np.diag(np.sqrt(np.arange(1, n)), 1).astype(complex)
        self.X, self.Y = b + b.conj().T, 1j * (b.conj().T - b)
        self.n = np.arange(n)
        self.alpha = data["alpha_ghz"]

    def H(self, u, s, delta, kc=0.0):
        n = self.n
        h0 = np.diag(TWO_PI * (n * delta + 0.5 * n * (n - 1) * self.alpha))
        u = np.asarray(u, dtype=complex)
        u = u * (1.0 - kc * np.abs(u) ** 2)
        return h0 + 0.5 * TWO_PI * s * (u.real[..., None, None] * self.X
                                        + u.imag[..., None, None] * self.Y)

    def rabi(self, s, delta, kc=0.0):
        d = self.d
        u = np.asarray(d["rabi_amps"])[:, None] * np.asarray(d["rabi_envelope"])[None, :]
        w, V = np.linalg.eigh(self.H(u, s, delta, kc))
        P = (V * np.exp(-1j * d["rabi_dt_ns"] * w)[..., None, :]) @ np.swapaxes(V.conj(), -1, -2)
        psi = np.zeros((P.shape[0], P.shape[-1]), dtype=complex)
        psi[:, 0] = 1.0
        for k in range(P.shape[1]):
            psi = np.einsum("aij,aj->ai", P[:, k], psi)
        return np.clip(1.0 - np.abs(psi[:, 0]) ** 2, 0.0, 1.0)

    def ramsey(self, s, delta, t2):
        d = self.d
        th = 0.5 * np.pi * s / d["drive_scale_design_ghz"]
        tau = np.asarray(d["ramsey_delays_ns"])
        osc = np.exp(-tau / t2) * np.cos(TWO_PI * (d["ramsey_offset_ghz"] + delta) * tau)
        return np.clip(0.5 * (1.0 - np.cos(th) ** 2 + np.sin(th) ** 2 * osc), 0.0, 1.0)


def nll(p, k, n):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -float(np.sum(k * np.log(p) + (n - k) * np.log(1 - p)))


def fit(M):
    d = M.d
    s_d = d["drive_scale_design_ghz"]
    kr = np.asarray(d["rabi_p_exc"]) * d["rabi_shots"]
    km = np.asarray(d["ramsey_p1"]) * d["ramsey_shots"]
    nr, nm = d["rabi_shots"], d["ramsey_shots"]
    # delta: periodogram peak of the Ramsey trace, refined on a fine grid
    tau = np.asarray(d["ramsey_delays_ns"])
    y = np.asarray(d["ramsey_p1"]) - np.mean(d["ramsey_p1"])
    fr = d["ramsey_offset_ghz"] + np.linspace(-3e-4, 3e-4, 3001)
    power = np.abs(np.exp(-1j * TWO_PI * fr[:, None] * tau[None, :]) @ y)
    delta0 = fr[np.argmax(power)] - d["ramsey_offset_ghz"]
    # (s, kc): grid of the Rabi likelihood (compression lengthens the Rabi period at high
    # amplitude, so s and kc separate), then refine
    rabi_nll = lambda s, kc: nll(M.rabi(s, delta0, kc), kr, nr)  # noqa: E731
    best = (np.inf, s_d, 0.0)
    for kc in np.linspace(-0.05, 0.25, 13):
        for s in s_d * np.linspace(0.85, 1.15, 21):
            v = rabi_nll(s, kc)
            if v < best[0]:
                best = (v, s, kc)
    r = minimize(lambda x: rabi_nll(x[0] * s_d, x[1] * 0.01), [best[1] / s_d, best[2] / 0.01],
                 method="Nelder-Mead",
                 options=dict(xatol=1e-7, fatol=1e-6, maxiter=2000,
                              initial_simplex=[[best[1] / s_d, best[2] / 0.01],
                                               [best[1] / s_d + 0.005, best[2] / 0.01],
                                               [best[1] / s_d, best[2] / 0.01 + 0.5]]))
    s0, k0 = r.x[0] * s_d, r.x[1] * 0.01
    t2s = np.linspace(3000.0, 80000.0, 40)
    t20 = t2s[np.argmin([nll(M.ramsey(s0, delta0, t), km, nm) for t in t2s])]
    # joint refinement in scaled coordinates
    x0 = np.array([s0 / s_d, delta0 * 1e6, t20 / 1e4, k0 / 0.01])
    f = lambda x: (nll(M.rabi(x[0] * s_d, x[1] * 1e-6, x[3] * 0.01), kr, nr)  # noqa: E731
                   + nll(M.ramsey(x[0] * s_d, x[1] * 1e-6, x[2] * 1e4), km, nm))
    simplex = x0 + np.vstack([np.zeros(4), np.diag([0.003, 0.3, 0.2, 0.3])])
    r = minimize(f, x0, method="Nelder-Mead",
                 options=dict(xatol=1e-7, fatol=1e-6, initial_simplex=simplex, maxiter=4000))
    return r.x[0] * s_d, r.x[1] * 1e-6, r.x[2] * 1e4, r.x[3] * 0.01


def fisher_sigmas(M, s, delta, t2, kc):
    """Standard errors of (s, delta, kc) from the Fisher information, T2 a nuisance."""
    d = M.d
    th, h = np.array([s, delta, t2, kc]), np.array([1e-6, 1e-7, 1.0, 1e-5])
    tr = lambda x: (M.rabi(x[0], x[1], x[3]), M.ramsey(x[0], x[1], x[2]))  # noqa: E731
    J = []
    for i in range(4):
        e = np.zeros(4)
        e[i] = h[i]
        (a, b), (c, e2) = tr(th + e), tr(th - e)
        J.append(((a - c) / (2 * h[i]), (b - e2) / (2 * h[i])))
    pr, pm = tr(th)
    wr = d["rabi_shots"] / np.maximum(pr * (1 - pr), 1e-4)
    wm = d["ramsey_shots"] / np.maximum(pm * (1 - pm), 1e-4)
    I = np.array([[np.sum(wr * J[i][0] * J[j][0]) + np.sum(wm * J[i][1] * J[j][1])
                   for j in range(4)] for i in range(4)])
    C = np.linalg.inv(I)
    return float(np.sqrt(C[0, 0])), float(np.sqrt(C[1, 1])), float(np.sqrt(C[3, 3]))


def predistort(v, kc):
    """Requested samples u with |u| (1 - kc |u|^2) = |v|, same phase (smallest root)."""
    a = np.abs(v)
    if kc <= 0:
        return np.asarray(v, dtype=complex)
    u = a.copy()
    for _ in range(60):  # Newton on g(x) = x - kc x^3 - a, monotone on [0, 1/sqrt(3 kc)]
        u = u - (u - kc * u**3 - a) / (1 - 3 * kc * u**2)
    return u * np.exp(1j * np.angle(v))


# ---------------- robust pulse: GRAPE with exact gradients ----------------
def infid_and_grad(M, u, scales, delta, dt):
    """Mean coherent 1 - F (TASK.md metric) over drive scales, and its gradient wrt Re u, Im u."""
    scales = np.asarray(scales, dtype=float)
    H = M.H(u[None, :], 1.0, delta) - M.H(0 * u[None, :], 1.0, delta)  # drive part at s = 1
    H = M.H(0 * u, 0.0, delta)[None] + scales[:, None, None, None] * H
    w, V = np.linalg.eigh(H)                                     # (E, N, d), (E, N, d, d)
    ph = np.exp(-1j * dt * w)
    Vh = np.swapaxes(V.conj(), -1, -2)
    P = (V * ph[..., None, :]) @ Vh
    E, N, d = P.shape[0], P.shape[1], P.shape[-1]
    A = np.empty((E, N + 1, d, d), dtype=complex)
    A[:, 0] = np.eye(d)
    for k in range(N):
        A[:, k + 1] = P[:, k] @ A[:, k]
    S = A[:, N, :2, :2]
    a, b = np.abs(S[:, 0, 1]), np.abs(S[:, 1, 0])
    F = (np.sum(np.abs(S) ** 2, axis=(1, 2)) + (a + b) ** 2) / 6.0
    G = np.zeros((E, d, d), dtype=complex)
    G[:, :2, :2] = 2 * S
    G[:, 0, 1] += 2 * (a + b) * S[:, 0, 1] / np.maximum(a, 1e-300)
    G[:, 1, 0] += 2 * (a + b) * S[:, 1, 0] / np.maximum(b, 1e-300)
    G /= 6.0
    Bd = np.empty((E, N, d, d), dtype=complex)                   # B_k^dag = (P_N-1..P_k+1)^dag
    Bd[:, N - 1] = np.eye(d)
    for k in range(N - 1, 0, -1):
        Bd[:, k - 1] = np.swapaxes(P[:, k].conj(), -1, -2) @ Bd[:, k]
    Mk = Bd @ G[:, None] @ np.swapaxes(A[:, :N].conj(), -1, -2)
    Mt = Vh @ Mk @ V
    dw = w[..., :, None] - w[..., None, :]
    same = np.abs(dw) < 1e-9
    Gam = np.where(same, -1j * dt * ph[..., :, None],
                   (ph[..., :, None] - ph[..., None, :]) / np.where(same, 1.0, dw))
    c = (0.5 * TWO_PI * scales)[:, None, None, None]
    gx = -np.real(np.sum(Mt.conj() * Gam * (Vh @ (c * M.X) @ V), axis=(-1, -2)))
    gy = -np.real(np.sum(Mt.conj() * Gam * (Vh @ (c * M.Y) @ V), axis=(-1, -2)))
    return float(np.mean(np.maximum(1 - F, 0))), gx.mean(0), gy.mean(0)


def robust_pulse(M, u0, s, sig_s, delta, restarts=RESTARTS, cap=None):
    """Minimise log10 of the ensemble-mean infidelity. Samples are mapped smoothly into the
    amplitude disk, u = cap z / sqrt(1 + |z|^2); a fixed number of restarts from u0 plus noise
    (stopping early below 1e-7.5), so the answer does not depend on the machine's speed."""
    d = M.d
    dt, N = d["dt_ns"], d["n_samples"]
    cap = d["amp_cap"] if cap is None else cap
    ens = s * (1.0 + ROBUST_K * sig_s / s)

    def to_u(x):
        z = x[:N] + 1j * x[N:]
        q = 1.0 + np.abs(z) ** 2
        return z, q, cap * z / np.sqrt(q)

    def cost(x):
        z, q, u = to_u(x)
        e, gx, gy = infid_and_grad(M, u, ens, delta, dt)
        dua = cap * (1.0 / np.sqrt(q) - z * z.real / q**1.5)
        dub = cap * (1j / np.sqrt(q) - z * z.imag / q**1.5)
        g = np.concatenate([gx * dua.real + gy * dua.imag, gx * dub.real + gy * dub.imag])
        return np.log10(e + 1e-14), g / ((e + 1e-14) * np.log(10))

    u0 = np.asarray(u0) * np.minimum(1.0, 0.95 * cap / np.max(np.abs(u0)))
    z0 = u0 / np.sqrt(cap**2 - np.abs(u0) ** 2)
    x0 = np.concatenate([z0.real, z0.imag])
    best = (np.inf, x0)
    rng = np.random.default_rng(0)
    for _ in range(restarts):
        r = minimize(cost, x0 + 0.3 * rng.standard_normal(2 * N), jac=True, method="L-BFGS-B",
                     options=dict(maxiter=3000, ftol=1e-13, gtol=1e-10))
        if r.fun < best[0]:
            best = (r.fun, r.x)
        if best[0] < -7.5:
            break
    return to_u(best[1])[2]


def solve(data):
    M = Model(data)
    s_d, f01 = data["drive_scale_design_ghz"], data["f01_design_ghz"]
    s, delta, t2, kc = fit(M)
    sig_s, sig_d, sig_k = fisher_sigmas(M, s, delta, t2, kc)
    s_ch = abs(s - s_d) > NSIG * sig_s
    d_ch = abs(delta) > NSIG * sig_d
    k_ch = abs(kc) > NSIG * sig_k
    if not (s_ch or d_ch or k_ch):
        return {"pulse": np.asarray(data["nominal_pulse"]),
                "diagnosis": {"changed": False, "drive_scale": s_d, "f01_ghz": f01,
                              "compression": 0.0}}
    s_use = s if s_ch else s_d
    d_use = delta if d_ch else 0.0
    k_use = kc if k_ch else 0.0
    u0 = np.asarray(data["nominal_pulse"]) * s_d / s_use
    v = robust_pulse(M, u0, s_use, sig_s, d_use, cap=data["amp_cap"] * (1 - max(k_use, 0.0)))
    return {"pulse": predistort(v, k_use),
            "diagnosis": {"changed": True, "drive_scale": float(s_use),
                          "f01_ghz": float(f01 + d_use), "compression": float(k_use)}}
