"""Hidden harness for pulse_wrong_model. Licence: Apache-2.0.

Simulated ground truth: a 4-level Duffing transmon whose drive-line scale and/or qubit
frequency may differ from the design values, or whose drive line has become non-linear
(AM-AM compression, Lazar 2023). Builds the solver's data (Rabi and Ramsey traces
with binomial shot noise), decides each instance's scoring rule from the true parameters, runs
the solution in an isolated process (eval/_isolate.py) and scores it.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np
from scipy.optimize import minimize

import rubric
from _isolate import run_solver

TWO_PI = 2.0 * np.pi

# ---------------- design (nominal) model ----------------
F01_GHZ = 5.0             # design qubit frequency; the drive and frame sit here
ALPHA_GHZ = -0.30         # anharmonicity alpha/2pi, known and not drifting (see TASK.md)
SCALE_DESIGN_GHZ = 0.10   # Rabi rate Omega/2pi per unit pulse amplitude
GATE_NS, DT_NS = 12.0, 0.5
N_SAMPLES = int(round(GATE_NS / DT_NS))
AMP_CAP = 1.0
LEVELS = 4
E_FLOOR = 1e-4            # incoherent error budget added to the coherent infidelity

# Rabi amplitude sweep: fixed 40 ns Gaussian (sigma 10 ns, shifted to zero at the edges)
RABI_NS = 40.0
RABI_AMPS = np.linspace(0.0, 1.0, 101)
RABI_SHOTS = 100
# Ramsey: two pi/2 pulses (ideal, rotation angle scales with s), frame offset 1 MHz
RAMSEY_DELAYS_NS = np.linspace(0.0, 10000.0, 201)
RAMSEY_OFFSET_GHZ = 0.001
RAMSEY_SHOTS = 100

# ---------------- instance generation ----------------
PUBLIC_SEED = 0
N_INSTANCES, N_QUICK = 32, 8
SCALE_REL_RANGE = (0.02, 0.06)       # drive-line transfer change (assumption)
FREQ_DRIFT_KHZ = (10.0, 80.0)        # qubit frequency drift magnitude (assumption)
T2_US_RANGE = (10.0, 30.0)           # Ramsey T2* (assumption)
# Drive compression: the delivered amplitude is a (1 - k a^2) for a requested amplitude a.
# k = 0.05 to 0.15 puts the 12 ns pi pulse 3 to 9 percent (5 to 16 degrees) off at its peak,
# the order of the "several degrees" at 15 ns in Lazar 2023 (range itself an assumption).
COMPRESS_RANGE = (0.05, 0.15)
FAMILIES = ("scale", "freq", "compress", "scale_compress")

# Hard tier: a 6 ns gate (fast gates: Hyyppa 2024, arXiv 2402.17757, at 6.25 ns; Werninghaus
# 2021, arXiv 2003.05952, at 4.16 ns) on a stronger drive line, and an effect outside the design
# model's form. The line's transfer differs between f01 and f12 = f01 + alpha (cable and package
# ripple; Jerger 2019, arXiv 1706.05829, measure such transfer functions with the qubit), so the
# drive reaches the 1-2 and 2-3 transitions m times as strongly as the Duffing matrix elements
# say (lambda = m sqrt 2 in the notation of Gambetta 2011, arXiv 1011.1949). m is not one of the
# listed parameters; a solver reports it as `other`. |log m| in log 1.07 to log 1.15 (0.6 to 1.2
# dB of ripple), either sign: an assumption. A DRAG-check trace (the design pulse followed by its
# negative, repeated, then an ideal pi/2 about y) is added; it cancels amplitude errors and
# amplifies phase and leakage errors, like the amplified-phase-error sequences of Lucero 2010
# (arXiv 1007.1690).
DRIVE12_RANGE = (1.07, 1.15)
CHECK_PAIRS = np.arange(1, 31)
CHECK_SHOTS = 200
TIERS = {
    "standard": dict(gate_ns=12.0, scale=0.10, families=FAMILIES, seed=0),
    "hard": dict(gate_ns=6.0, scale=0.20, seed=20261118,
                 families=("drive12",) * 6 + ("drive12_scale",) * 3 + ("drive12_compress",) * 3
                 + FAMILIES),
}
TIER = "standard"


def use_tier(name):
    """Set the module's design constants for a tier (one tier per process)."""
    global TIER, GATE_NS, N_SAMPLES, SCALE_DESIGN_GHZ, FAMILIES, _NOMINAL
    t = TIERS[name]
    TIER, GATE_NS, SCALE_DESIGN_GHZ = name, t["gate_ns"], t["scale"]
    N_SAMPLES, FAMILIES, _NOMINAL = int(round(GATE_NS / DT_NS)), t["families"], None

# ---------------- scoring ----------------
FIX_GAP_DEC = 0.3          # stale must be this many decades above the oracle to score fix
NOHARM_SLACK_DEC, NOHARM_ZERO_DEC = 0.1, 1.0
TOL_FULL_SIG, TOL_ZERO_SIG = 2.0, 4.0  # diagnosis credit in units of the Cramer-Rao limit
SOLVER_TIMEOUT_S = 120.0


# ---------------- physics ----------------
def _ops(d=LEVELS, m=1.0):
    """Drive operators; m scales the 1-2 and higher matrix elements (hard tier, see above)."""
    b = np.diag(np.sqrt(np.arange(1, d)), 1).astype(complex)
    b[1:, 2:] *= m
    return b + b.conj().T, 1j * (b.conj().T - b)


X_OP, Y_OP = _ops()
N_LEV = np.arange(LEVELS)


def hamiltonians(u, scale, delta, k=0.0, m=1.0):
    """H_k for requested samples u_k = I + iQ; delta = f01_true - f_drive (GHz); the line
    delivers u (1 - k |u|^2); m is the hard tier's 1-2 drive factor."""
    u = np.asarray(u, dtype=complex)
    u = u * (1.0 - k * np.abs(u) ** 2)
    h0 = np.diag(TWO_PI * (N_LEV * delta + 0.5 * N_LEV * (N_LEV - 1) * ALPHA_GHZ))
    c = 0.5 * TWO_PI * scale
    X, Y = (X_OP, Y_OP) if m == 1.0 else _ops(LEVELS, m)
    return h0 + c * (u.real[..., None, None] * X + u.imag[..., None, None] * Y)


def expmh(H, dt):
    """exp(-i H dt) for a stack of Hermitian matrices."""
    w, V = np.linalg.eigh(H)
    return (V * np.exp(-1j * dt * w)[..., None, :]) @ np.swapaxes(V.conj(), -1, -2)


def chain(P):
    """Ordered product P_{n-1} ... P_0 over the second-to-last stack axis (time)."""
    U = P[..., 0, :, :]
    for k in range(1, P.shape[-3]):
        U = P[..., k, :, :] @ U
    return U


def coherent_infid(u, scale, delta, k=0.0, m=1.0):
    """1 - F_avg on the 0-1 block (Pedersen 2007 Eq. 3), free virtual Z after the gate."""
    S = chain(expmh(hamiltonians(u, scale, delta, k, m), DT_NS))[:2, :2]
    F = (np.real(np.trace(S @ S.conj().T)) + (abs(S[0, 1]) + abs(S[1, 0])) ** 2) / 6.0
    return max(1.0 - F, 0.0)


def gate_L(u, scale, delta, k=0.0, m=1.0):
    return float(np.log10(coherent_infid(u, scale, delta, k, m) + E_FLOOR))


def gauss_env(T, dt):
    t = (np.arange(int(round(T / dt))) + 0.5) * dt
    sig, c = T / 4.0, T / 2.0
    e = np.exp(-((t - c) ** 2) / (2 * sig**2))
    return t, e - np.exp(-(c**2) / (2 * sig**2)), -(t - c) / sig**2 * e


def clip_pulse(u):
    u = np.asarray(u, dtype=complex)
    m = np.abs(u)
    return np.where(m > AMP_CAP, u * AMP_CAP / np.maximum(m, 1e-300), u)


def drag_pulse(p):
    A, beta, det = p
    t, g, dg = gauss_env(GATE_NS, DT_NS)
    return clip_pulse(A * (g + 1j * beta * dg) * np.exp(1j * det * t))


def optimise_drag(scale, delta):
    """The design team's optimiser: multi-start Nelder-Mead over (A, beta, det)."""
    f = lambda p: np.log10(coherent_infid(drag_pulse(p), scale, delta) + 1e-12)
    _, g, _ = gauss_env(GATE_NS, DT_NS)
    A0 = 0.5 / (scale * g.sum() * DT_NS)
    best = None
    for b0 in np.linspace(-0.4, 1.2, 5):
        for d0 in (-0.04, 0.0, 0.04, 0.08):
            r = minimize(f, [A0, b0, d0], method="Nelder-Mead",
                         options=dict(xatol=1e-9, fatol=1e-6, maxiter=4000))
            if best is None or r.fun < best.fun:
                best = r
    return np.asarray(best.x), drag_pulse(best.x)


_NOMINAL = None


def nominal():
    global _NOMINAL
    if _NOMINAL is None:
        _NOMINAL = optimise_drag(SCALE_DESIGN_GHZ, 0.0)
    return _NOMINAL


# ---------------- measured traces ----------------
def rabi_p(scale, delta, k=0.0, m=1.0):
    _, env, _ = gauss_env(RABI_NS, DT_NS)
    U = chain(expmh(hamiltonians(RABI_AMPS[:, None] * env[None, :], scale, delta, k, m), DT_NS))
    return np.clip(1.0 - np.abs(U[:, 0, 0]) ** 2, 0.0, 1.0)


Y90 = np.array([[1.0, -1.0], [1.0, 1.0]]) / np.sqrt(2.0)  # ideal pi/2 about y on the 0-1 block


def check_p(u, scale, delta, k=0.0, m=1.0):
    """1 - P(0) after n pairs (pulse, then the pulse negated), n = CHECK_PAIRS, from |0>,
    followed by an ideal pi/2 rotation about y (it makes the trace sensitive to the error's
    sign; leaked population stays where it is and counts as not 0)."""
    u = np.asarray(u, dtype=complex)
    pair = chain(expmh(hamiltonians(-u, scale, delta, k, m), DT_NS)) @ \
        chain(expmh(hamiltonians(u, scale, delta, k, m), DT_NS))
    psi, out = np.eye(LEVELS, dtype=complex)[:, 0], []
    for _ in range(int(CHECK_PAIRS.max())):
        psi = pair @ psi
        out.append(1.0 - abs((Y90 @ psi[:2])[0]) ** 2)
    return np.clip(np.array(out)[CHECK_PAIRS - 1], 0.0, 1.0)


def ramsey_p(scale, delta, t2_ns):
    th = 0.5 * np.pi * scale / SCALE_DESIGN_GHZ
    tau = RAMSEY_DELAYS_NS
    osc = np.exp(-tau / t2_ns) * np.cos(TWO_PI * (RAMSEY_OFFSET_GHZ + delta) * tau)
    return np.clip(0.5 * (1.0 - np.cos(th) ** 2 + np.sin(th) ** 2 * osc), 0.0, 1.0)


def crb(scale, delta, t2_ns, k=0.0, m=1.0):
    """Cramer-Rao standard deviations of (scale, delta, k) from both traces, T2 a nuisance
    (hard tier: m held at its true value)."""
    th = np.array([scale, delta, t2_ns, k])
    h = np.array([1e-6, 1e-7, 1.0, 1e-5])
    def traces(x):
        return rabi_p(x[0], x[1], x[3], m), ramsey_p(x[0], x[1], x[2])
    J = []
    for i in range(4):
        e = np.zeros(4); e[i] = h[i]
        (ra, rm), (rb, rn) = traces(th + e), traces(th - e)
        J.append(((ra - rb) / (2 * h[i]), (rm - rn) / (2 * h[i])))
    p_r, p_m = traces(th)
    w_r = RABI_SHOTS / np.maximum(p_r * (1 - p_r), 1e-4)
    w_m = RAMSEY_SHOTS / np.maximum(p_m * (1 - p_m), 1e-4)
    I = np.array([[np.sum(w_r * J[i][0] * J[j][0]) + np.sum(w_m * J[i][1] * J[j][1])
                   for j in range(4)] for i in range(4)])
    C = np.linalg.inv(I)
    return float(np.sqrt(C[0, 0])), float(np.sqrt(C[1, 1])), float(np.sqrt(C[3, 3]))


# ---------------- instances ----------------
def tier_salt() -> list[int]:
    """Extra seed words for the hard tier, so a secret seed draws unrelated instances per tier."""
    return [] if TIER == "standard" else [2]


def instance_kinds(master, n):
    """Exactly n//2 controls; the rest cycle through the families; order shuffled."""
    nf = len(FAMILIES)
    kinds = ["control"] * (n // 2) + [FAMILIES[i % nf] for i in range(n - n // 2)]
    np.random.default_rng([master, 0, *tier_salt()]).shuffle(kinds)
    return kinds


def instance_params(master, i, kind):
    rng = np.random.default_rng([master, 1, i, *tier_salt()])
    rs = rng.choice([-1, 1]) * rng.uniform(*SCALE_REL_RANGE)
    df = rng.choice([-1, 1]) * rng.uniform(*FREQ_DRIFT_KHZ) * 1e-6
    t2 = rng.uniform(*T2_US_RANGE) * 1e3
    kc = rng.uniform(*COMPRESS_RANGE)
    scale = SCALE_DESIGN_GHZ * (1 + rs) if "scale" in kind else SCALE_DESIGN_GHZ
    delta = df if kind == "freq" else 0.0
    k = kc if "compress" in kind else 0.0
    m = 1.0
    if TIER != "standard":  # drawn after the standard draws, so standard instances are unchanged
        mm = np.exp(rng.choice([-1, 1]) * rng.uniform(*np.log(DRIVE12_RANGE)))
        m = float(mm) if "drive12" in kind else 1.0
    return scale, delta, t2, k, m, rng


def make_data(scale, delta, t2, k, rng, m=1.0):
    nom_p, nom_u = nominal()
    _, env, _ = gauss_env(RABI_NS, DT_NS)
    data = {
        "f01_design_ghz": F01_GHZ, "alpha_ghz": ALPHA_GHZ,
        "drive_scale_design_ghz": SCALE_DESIGN_GHZ,
        "gate_time_ns": GATE_NS, "dt_ns": DT_NS, "n_samples": N_SAMPLES,
        "amp_cap": AMP_CAP, "levels_hint": LEVELS,
        "nominal_pulse": nom_u.copy(),
        "nominal_drag_params": {"A": float(nom_p[0]), "beta_ns": float(nom_p[1]),
                                "detuning_rad_per_ns": float(nom_p[2])},
        "rabi_amps": RABI_AMPS.copy(), "rabi_envelope": env, "rabi_dt_ns": DT_NS,
        "rabi_shots": RABI_SHOTS,
        "rabi_p_exc": rng.binomial(RABI_SHOTS, rabi_p(scale, delta, k, m)) / RABI_SHOTS,
        "ramsey_delays_ns": RAMSEY_DELAYS_NS.copy(), "ramsey_offset_ghz": RAMSEY_OFFSET_GHZ,
        "ramsey_shots": RAMSEY_SHOTS,
        "ramsey_p1": rng.binomial(RAMSEY_SHOTS, ramsey_p(scale, delta, t2)) / RAMSEY_SHOTS,
    }
    if TIER != "standard":
        data.update(tier=TIER, drag_check_pairs=CHECK_PAIRS.copy(), drag_check_shots=CHECK_SHOTS,
                    drag_check_p_exc=rng.binomial(CHECK_SHOTS, check_p(nom_u, scale, delta, k, m))
                    / CHECK_SHOTS)
    return data


def build(master, n):
    """Data plus the hidden truth and the scoring rule, decided from true parameters only."""
    _, nom_u = nominal()
    out = []
    for i, kind in enumerate(instance_kinds(master, n)):
        scale, delta, t2, k, m, rng = instance_params(master, i, kind)
        data = make_data(scale, delta, t2, k, rng, m)
        L_stale, L_oracle = gate_L(nom_u, scale, delta, k, m), float(np.log10(E_FLOOR))
        if kind == "control":
            rule = "control"
        else:
            rule = "fix" if L_stale - L_oracle >= FIX_GAP_DEC else "diagnosis"
        s_sig, d_sig, k_sig = crb(scale, delta, t2, k, m)
        out.append(dict(i=i, kind=kind, rule=rule, scale=scale, delta_ghz=delta, t2_ns=t2,
                        compression=k, drive12=m, L_stale=L_stale, L_oracle=L_oracle, sigma_scale=s_sig,
                        sigma_delta_ghz=d_sig, sigma_compression=k_sig, data=data))
    return out


# ---------------- scoring ----------------
def parse_output(out):
    pulse = np.asarray(out["pulse"], dtype=complex).reshape(-1)
    if pulse.shape != (N_SAMPLES,) or not np.all(np.isfinite(pulse)):
        raise ValueError("pulse must be finite complex, length %d" % N_SAMPLES)
    d = out["diagnosis"]
    if not isinstance(d["changed"], bool):
        raise ValueError("diagnosis.changed must be bool")
    s, f = float(d["drive_scale"]), float(d["f01_ghz"])
    k = float(d.get("compression", 0.0))
    if not (np.isfinite(s) and np.isfinite(f) and np.isfinite(k)):
        raise ValueError("non-finite diagnosis")
    other = d.get("other", False)
    if not isinstance(other, bool):
        raise ValueError("diagnosis.other must be bool")
    return clip_pulse(pulse), d["changed"], s, f, k, other


def sig_credit(err, sigma):
    return float(np.clip((TOL_ZERO_SIG - abs(err) / sigma) / (TOL_ZERO_SIG - TOL_FULL_SIG), 0, 1))


def score_one(inst, out):
    pulse, changed, s_est, f_est, k_est, other = parse_output(out)
    L_sol = gate_L(pulse, inst["scale"], inst["delta_ghz"], inst["compression"], inst["drive12"])
    excess = L_sol - inst["L_stale"]
    noharm = float(np.clip((NOHARM_ZERO_DEC - excess) / (NOHARM_ZERO_DEC - NOHARM_SLACK_DEC),
                           0, 1))
    cs = sig_credit(s_est - inst["scale"], inst["sigma_scale"])
    cf = sig_credit(f_est - F01_GHZ - inst["delta_ghz"], inst["sigma_delta_ghz"])
    ck = sig_credit(k_est - inst["compression"], inst["sigma_compression"])
    co = float(other == (inst["drive12"] != 1.0))  # hard tier: "outside the listed form"
    r = dict(changed=changed, L_sol=L_sol, scale_est=s_est, f01_est=f_est,
             compression_est=k_est, other=other, scale_credit=cs, f01_credit=cf,
             compression_credit=ck, other_credit=co, noharm=noharm)
    fix = noharm if inst["rule"] != "fix" else float(
        np.clip((inst["L_stale"] - L_sol) / (inst["L_stale"] - inst["L_oracle"]), 0, 1))
    checks = rubric.instance_checks(
        inst["rule"], changed == (inst["kind"] != "control"), fix, noharm,
        {"scale": cs, "f01": cf, "compression": ck, "other": co})
    right = checks["change_call"]["v"] == 1.0  # fix and diag are reported as 0 when it is wrong
    diag = checks["diagnosis"]["v"] if "diagnosis" in checks else 1.0
    r.update(fix=fix * right, diag=diag * right, score=rubric.total(checks), rubric=checks)
    return r


def evaluate(solution_path, master=PUBLIC_SEED, quick=False, tier="standard"):
    use_tier(tier)
    rows = []
    for inst in build(master, N_QUICK if quick else N_INSTANCES):
        ok, out, secs = run_solver(solution_path, inst["data"], SOLVER_TIMEOUT_S)
        row = {k: v for k, v in inst.items() if k != "data"}
        row["solve_s"] = round(secs, 2)
        try:
            if not ok:
                raise RuntimeError(out)
            row.update(score_one(inst, out))
        except Exception as e:  # noqa: BLE001
            row.update(error=str(e)[:300], fix=0.0, diag=0.0, score=0.0, rubric=rubric.invalid())
        rows.append(row)
    sc = np.array([r["score"] for r in rows])
    ctrl = [r for r in rows if r["kind"] == "control"]
    chg = [r for r in rows if r["kind"] != "control"]
    said = lambda r: r.get("changed") is True  # noqa: E731
    return {"score": float(sc.mean()), "score_se": float(sc.std(ddof=1) / np.sqrt(len(sc))),
            "master_seed": master, "tier": tier, "rubric": rubric.VERSION,
            "false_alarm_rate": float(np.mean([said(r) for r in ctrl])),
            "miss_rate": float(np.mean([not said(r) for r in chg])),
            "instances": rows}
