"""Physics kit for the grader checks: fits and pulse design written from TASK.md alone.
It does not import eval/ (a solver could not). Licence: Apache-2.0."""
import numpy as np
from scipy.optimize import minimize, minimize_scalar

TWO_PI = 2.0 * np.pi


def ops(d):
    b = np.diag(np.sqrt(np.arange(1, d)), 1).astype(complex)
    return b + b.conj().T, 1j * (b.conj().T - b)


def hams(data, u, s, delta):
    d = data["levels_hint"]
    X, Y = ops(d)
    n = np.arange(d)
    h0 = np.diag(TWO_PI * (n * delta + 0.5 * n * (n - 1) * data["alpha_ghz"]))
    u = np.asarray(u, dtype=complex)
    return h0 + 0.5 * TWO_PI * s * (u.real[..., None, None] * X + u.imag[..., None, None] * Y)


def props(H, dt):
    w, V = np.linalg.eigh(H)
    return (V * np.exp(-1j * dt * w)[..., None, :]) @ np.swapaxes(V.conj(), -1, -2), w, V


def rabi_model(data, s, delta=0.0):
    u = np.asarray(data["rabi_amps"])[:, None] * np.asarray(data["rabi_envelope"])[None, :]
    P = props(hams(data, u, s, delta), data["rabi_dt_ns"])[0]
    U = P[:, 0]
    for k in range(1, P.shape[1]):
        U = P[:, k] @ U
    return np.clip(1 - np.abs(U[:, 0, 0]) ** 2, 1e-9, 1 - 1e-9)


def ramsey_model(data, s, delta, t2):
    th = 0.5 * np.pi * s / data["drive_scale_design_ghz"]
    tau = np.asarray(data["ramsey_delays_ns"])
    osc = np.exp(-tau / t2) * np.cos(TWO_PI * (data["ramsey_offset_ghz"] + delta) * tau)
    return np.clip(0.5 * (1 - np.cos(th) ** 2 + np.sin(th) ** 2 * osc), 1e-9, 1 - 1e-9)


def nll(p, frac, n):
    k = frac * n
    return -float(np.sum(k * np.log(p) + (n - k) * np.log(1 - p)))


def estimate(data):
    """Return (s, sigma_s, delta). Rabi likelihood for s; Ramsey periodogram + likelihood for delta."""
    sd, nr = data["drive_scale_design_ghz"], data["rabi_shots"]
    pr = np.asarray(data["rabi_p_exc"])
    f = lambda s: nll(rabi_model(data, s), pr, nr)  # noqa: E731
    grid = sd * np.linspace(0.85, 1.15, 61)
    s0 = grid[np.argmin([f(s) for s in grid])]
    s = minimize_scalar(f, bounds=(s0 - 0.006 * sd, s0 + 0.006 * sd), method="bounded",
                        options=dict(xatol=1e-8)).x
    h = 1e-4 * sd
    curv = (f(s + h) - 2 * f(s) + f(s - h)) / h**2
    sig = 1 / np.sqrt(max(curv, 1e-30))
    tau, pm = np.asarray(data["ramsey_delays_ns"]), np.asarray(data["ramsey_p1"])
    fr = data["ramsey_offset_ghz"] + np.linspace(-3e-4, 3e-4, 3001)
    power = np.abs(np.exp(-1j * TWO_PI * fr[:, None] * tau[None, :]) @ (pm - pm.mean()))
    d0 = fr[np.argmax(power)] - data["ramsey_offset_ghz"]
    g = lambda x: nll(ramsey_model(data, s, x[0] * 1e-6, x[1] * 1e4), pm,  # noqa: E731
                      data["ramsey_shots"])
    r = minimize(g, [d0 * 1e6, 2.0], method="Nelder-Mead", options=dict(xatol=1e-6, fatol=1e-7))
    return float(s), float(sig), float(r.x[0] * 1e-6)


def infid(U):
    S = U[:2, :2]
    return 1 - (np.real(np.trace(S @ S.conj().T)) + (abs(S[0, 1]) + abs(S[1, 0])) ** 2) / 6


def gate_infid(data, u, s, delta):
    P = props(hams(data, u, s, delta), data["dt_ns"])[0]
    U = P[0]
    for k in range(1, len(P)):
        U = P[k] @ U
    return infid(U)


def drag_refit(data, s, delta):
    """Re-optimise the design DRAG family (A, beta, det) on the fitted model."""
    T, dt = data["gate_time_ns"], data["dt_ns"]
    t = (np.arange(int(round(T / dt))) + 0.5) * dt
    sig, c = T / 4, T / 2
    e = np.exp(-((t - c) ** 2) / (2 * sig**2))
    g, dg = e - np.exp(-(c**2) / (2 * sig**2)), -(t - c) / sig**2 * e
    pulse = lambda p: p[0] * (g + 1j * p[1] * dg) * np.exp(1j * p[2] * t)  # noqa: E731
    nd = data["nominal_drag_params"]
    x0 = [nd["A"] * data["drive_scale_design_ghz"] / s, nd["beta_ns"], nd["detuning_rad_per_ns"]]
    r = minimize(lambda p: np.log10(gate_infid(data, pulse(p), s, delta) + 1e-12), x0,
                 method="Nelder-Mead", options=dict(xatol=1e-9, fatol=1e-6, maxiter=4000))
    return pulse(r.x)


def _grad(data, u, scales, delta):
    """Mean infidelity over drive scales and its gradient (2, N) wrt Re u, Im u."""
    dt = data["dt_ns"]
    X, Y = ops(data["levels_hint"])
    sc = np.asarray(scales, dtype=float)
    H0 = hams(data, 0 * u, 0.0, delta)
    Hd = hams(data, u, 1.0, delta) - H0
    P, w, V = props(H0[None] + sc[:, None, None, None] * Hd[None], dt)
    ph = np.exp(-1j * dt * w)
    Vh = np.swapaxes(V.conj(), -1, -2)
    E, N, d = P.shape[0], P.shape[1], P.shape[-1]
    A = np.empty((E, N + 1, d, d), dtype=complex)
    A[:, 0] = np.eye(d)
    for k in range(N):
        A[:, k + 1] = P[:, k] @ A[:, k]
    S = A[:, N, :2, :2]
    a, b = np.abs(S[:, 0, 1]), np.abs(S[:, 1, 0])
    F = (np.sum(np.abs(S) ** 2, axis=(1, 2)) + (a + b) ** 2) / 6
    G = np.zeros((E, d, d), dtype=complex)
    G[:, :2, :2] = 2 * S
    G[:, 0, 1] += 2 * (a + b) * S[:, 0, 1] / np.maximum(a, 1e-300)
    G[:, 1, 0] += 2 * (a + b) * S[:, 1, 0] / np.maximum(b, 1e-300)
    G /= 6
    Bd = np.empty((E, N, d, d), dtype=complex)
    Bd[:, N - 1] = np.eye(d)
    for k in range(N - 1, 0, -1):
        Bd[:, k - 1] = np.swapaxes(P[:, k].conj(), -1, -2) @ Bd[:, k]
    Mt = Vh @ (Bd @ G[:, None] @ np.swapaxes(A[:, :N].conj(), -1, -2)) @ V
    dw = w[..., :, None] - w[..., None, :]
    same = np.abs(dw) < 1e-9
    Gam = np.where(same, -1j * dt * ph[..., :, None],
                   (ph[..., :, None] - ph[..., None, :]) / np.where(same, 1, dw))
    c = (0.5 * TWO_PI * sc)[:, None, None, None]
    gr = [-np.real(np.sum(Mt.conj() * Gam * (Vh @ (c * op) @ V), axis=(-1, -2))).mean(0)
          for op in (X, Y)]
    return float(np.mean(1 - F)), np.array(gr)


def robust(data, s, sig, delta, tries=8):
    """24 free samples in the amplitude disk, mean infidelity over s + k sig, k = -2..2."""
    N, cap = data["n_samples"], data["amp_cap"]
    ens = s + sig * np.arange(-2, 3)

    def cost(x):
        z = x[:N] + 1j * x[N:]
        q = 1 + np.abs(z) ** 2
        u = cap * z / np.sqrt(q)
        e, gr = _grad(data, u, ens, delta)
        dua = cap * (1 / np.sqrt(q) - z * z.real / q**1.5)
        dub = cap * (1j / np.sqrt(q) - z * z.imag / q**1.5)
        g = np.concatenate([gr[0] * dua.real + gr[1] * dua.imag,
                            gr[0] * dub.real + gr[1] * dub.imag])
        return np.log10(e + 1e-14), g / ((e + 1e-14) * np.log(10))

    u0 = np.asarray(data["nominal_pulse"]) * data["drive_scale_design_ghz"] / s
    u0 = u0 * min(1.0, 0.95 * cap / np.max(np.abs(u0)))
    z0 = u0 / np.sqrt(cap**2 - np.abs(u0) ** 2)
    rng = np.random.default_rng(1)
    best = None
    for _ in range(tries):
        x0 = np.concatenate([z0.real, z0.imag]) + 0.3 * rng.standard_normal(2 * N)
        r = minimize(cost, x0, jac=True, method="L-BFGS-B",
                     options=dict(maxiter=3000, ftol=1e-13, gtol=1e-10))
        if best is None or r.fun < best.fun:
            best = r
        if best.fun < -7.5:
            break
    z = best.x[:N] + 1j * best.x[N:]
    return cap * z / np.sqrt(1 + np.abs(z) ** 2)
