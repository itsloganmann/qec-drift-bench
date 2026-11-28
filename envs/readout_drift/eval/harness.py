"""Hidden device, ground truth, baselines and scoring for readout_drift.

Single-shot dispersive readout of a transmon. Integrated IQ points of |0> and |1> form
Gaussian clouds at the steady-state resonator responses (Blais 2021, arXiv:2005.12667;
Gambetta 2006, arXiv:cond-mat/0602322). |1> shots may decay (T1) inside the integration window
and land on the segment between the centres. After calibration the device may drift; the new
shots come in 8 ordered batches and a phase may ramp across them. The solver runs in a separate
process (eval/_isolate.py), sees only `data`, and returns a discriminator as Gaussian components
per batch; the grader classifies its own shuffled hidden test set.
"""
import json

import numpy as np

import rubric
from _isolate import run_solver

KINDS = ("phase_rotation", "phase_ramp", "gain_drop", "resonator_shift", "noise_growth",
         "t1_drop")
# Main magnitude ranges (resonator_shift in units of kappa; t1_drop is T1_before / T1_after,
# drawn log-uniform). All but t1_drop are stress cases (see TASK.md).
RANGES = {"phase_rotation": (10.0, 40.0), "phase_ramp": (10.0, 40.0), "gain_drop": (0.15, 0.35),
          "resonator_shift": (0.15, 0.40), "noise_growth": (0.20, 0.50), "t1_drop": (3.0, 10.0)}
NEAR = {"phase_rotation": (6.0, 8.0), "gain_drop": (0.10, 0.13), "resonator_shift": (0.10, 0.13)}
SIGNED = ("phase_rotation", "phase_ramp", "resonator_shift")
# Composition of the scored set: 15 controls and 15 drifted instances ("near" = just above floor).
DRIFT_SPECS = [
    [("phase_rotation", "main")], [("phase_rotation", "near")], [("phase_ramp", "main")],
    [("gain_drop", "main")], [("gain_drop", "near")], [("resonator_shift", "main")],
    [("resonator_shift", "near")], [("noise_growth", "main")], [("t1_drop", "main")],
    [("t1_drop", "main")], [("phase_rotation", "main"), ("gain_drop", "main")],
    [("resonator_shift", "main"), ("noise_growth", "main")],
    [("gain_drop", "main"), ("t1_drop", "main")], [("phase_ramp", "main"), ("noise_growth", "main")],
    [("resonator_shift", "main"), ("gain_drop", "main")],
]
SPECS = DRIFT_SPECS + [[]] * 15
PUBLIC_SEEDS = list(range(3001, 3001 + len(SPECS)))
# Hard tier: the readout chain's gain turns anisotropic (`iq_stretch`, not one of the six stated
# families; the solver must report it as kind "other"). The IQ plane is stretched by sqrt(rho)
# along an axis at angle psi and squeezed by 1/sqrt(rho) across it, applied to the signal and to
# the share of the noise that passes the stage (gain_noise_fraction), as a phase-sensitive
# (degenerate) parametric amplifier or an IQ demodulator imbalance would do (Caves 1982,
# doi:10.1103/PhysRevD.26.1817; parametric amplifiers in Krantz 2019 Sec. V.E). Size rho is a stress case (assumption).
STRETCH_RANGE = (1.5, 3.0)
HARD_DRIFT_SPECS = [[("iq_stretch", "main")]] * 6 + [
    [("iq_stretch", "main"), ("phase_rotation", "main")],
    [("iq_stretch", "main"), ("phase_rotation", "main")],
    [("iq_stretch", "main"), ("t1_drop", "main")], [("iq_stretch", "main"), ("gain_drop", "main")],
    [("t1_drop", "main")], [("phase_rotation", "near")], [("resonator_shift", "near")],
    [("gain_drop", "near")], [("phase_ramp", "main"), ("noise_growth", "main")]]
TIERS = {"standard": {"specs": SPECS, "public": PUBLIC_SEEDS},
         "hard": {"specs": HARD_DRIFT_SPECS + [[]] * 15,
                  "public": list(range(4001, 4001 + len(HARD_DRIFT_SPECS) + 15))}}
UNLISTED = "other"  # the kind a solver reports for a change outside the six families
QUICK_IDX = (0, 3, 5, 8, 15, 16, 17, 18)

N_CAL_PER_STATE = 2000
N_BATCHES = 8
N_NEW_RANGE = (300, 800)
N_TEST_PER_BATCH_STATE = 6250          # 100,000 test shots in all
N_TEST_PER_BATCH_STATE_QUICK = 1500
N_RULE_PER_BATCH_STATE = 25_000        # separate sample that fixes each instance's rule
GAIN_NOISE_FRACTION = 0.8
TIME_LIMIT_S = 120.0
MAX_COMPONENTS = 16                    # per batch
# Background wander on every instance (max |value|): phase step deg, phase ramp deg at the last
# batch, gain and noise fractions, shift / kappa, T1 fraction. All below the floor.
NUIS = {"phase": 2.0, "ramp": 2.0, "gain": 0.05, "noise": 0.03, "shift": 0.03, "t1": 0.10}
NO_CHANGE_FLOOR = {"phase_rotation": 5.0, "phase_ramp": 5.0, "gain_drop": 0.08,
                   "resonator_shift_kappa": 0.08, "noise_growth": 0.10,
                   "t1_drop_decay_increase": 0.25}
T1_MIN_DECAY_INCREASE = 0.35           # t1_drop instances are redrawn until this holds

NOHARM_TOL, NOHARM_SPAN = 0.002, 0.010
GAP_MIN = 0.003  # true stale - oracle error gap that makes an instance scored on fix
MAG_TOL = {  # absolute, relative (larger wins)
    "phase_rotation": (2.5, 0.10), "phase_ramp": (3.0, 0.15), "gain_drop": (0.04, 0.0),
    "resonator_shift": (0.06, 0.15), "noise_growth": (0.06, 0.0)}
_GL_U, _GL_W = np.polynomial.legendre.leggauss(32)
_GL_U, _GL_W = (_GL_U + 1) / 2, _GL_W / 2


# ----------------------------------------------------------------------------- device
def response(p, f_s):
    """Steady-state response A e^{i theta0} (kappa/2) / (kappa/2 + i (f_s - f_d)) as (I, Q)."""
    k2 = p["kappa_MHz"] / 2.0
    z = p["amplitude"] * np.exp(1j * p["theta0_rad"]) * k2 / (k2 + 1j * (f_s - p["drive_offset_MHz"]))
    return np.array([z.real, z.imag])


def gain_from_drop(drop, f=GAIN_NOISE_FRACTION):
    r = 1.0 - drop  # solves g / sqrt(f g^2 + 1 - f) = r
    return np.sqrt(r * r * (1 - f) / (1 - r * r * f))


def decay_prob(dev):
    return 1.0 - np.exp(-dev["T_int_us"] / dev["T1_us"])


def batch_devices(p, delta, phi, ramp, g, s, t1f, rho=1.0, psi=0.0):
    """One device per batch: shift delta MHz, rotation phi + ramp (b+1)/8 deg, gain g, noise s,
    and (hard tier) an anisotropic stretch rho along angle psi. With a stretch, "cov" holds the
    full noise covariance; otherwise noise is isotropic with standard deviation "sigma"."""
    m0, m1 = response(p, p["chi_MHz"] + delta), response(p, -p["chi_MHz"] + delta)
    f = GAIN_NOISE_FRACTION
    sigma = p["sigma"] * np.sqrt(f * g * g + 1 - f) * s
    c, si = np.cos(psi), np.sin(psi)
    Rp = np.array([[c, -si], [si, c]])
    T = Rp @ np.diag([np.sqrt(rho), 1 / np.sqrt(rho)]) @ Rp.T
    cov = (p["sigma"] * s) ** 2 * (f * g * g * T @ T.T + (1 - f) * np.eye(2))
    devs = []
    for b in range(N_BATCHES):
        a = np.radians(phi + ramp * (b + 1) / N_BATCHES)
        R = g * np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        d = dict(p, mu0=T @ R @ m0, mu1=T @ R @ m1, sigma=sigma, T1_us=p["T1_us"] / t1f)
        if rho != 1.0:
            d["cov"] = cov
        devs.append(d)
    return devs


def draw_base(rng):
    kappa = rng.uniform(2.0, 6.0)
    chi = 0.5 * kappa * rng.uniform(0.8, 1.2)
    p = dict(kappa_MHz=kappa, chi_MHz=chi, drive_offset_MHz=rng.choice([-1.0, 1.0]) * rng.uniform(0.3, 0.6) * chi,
             amplitude=1.0, theta0_rad=rng.uniform(0, 2 * np.pi), T_int_us=rng.uniform(0.5, 2.0),
             T1_us=rng.uniform(20.0, 100.0), p_thermal=rng.uniform(0.005, 0.02),
             gain_noise_fraction=GAIN_NOISE_FRACTION)
    p["mu0"], p["mu1"] = response(p, chi), response(p, -chi)
    p["sigma"] = float(np.linalg.norm(p["mu1"] - p["mu0"]) / rng.uniform(3.5, 5.5))
    return p


def draw_device(seed, spec):
    """Draw until every drifted family's graded size (wander included) is at or above its
    no-change floor, so no instance labelled "changed" sits inside the stated no-change band."""
    rng = np.random.default_rng(seed)
    while True:
        out = _draw_once(rng, spec)
        if supported(*out[:3]):
            return out


def supported(p, devs, truth):
    fl = NO_CHANGE_FLOOR
    size = {"phase_rotation": abs(truth.get("phase_rotation", 0.0)) / fl["phase_rotation"],
            "phase_ramp": abs(truth.get("phase_ramp", 0.0)) / fl["phase_ramp"],
            "gain_drop": truth.get("gain_drop", 0.0) / fl["gain_drop"],
            "resonator_shift": abs(truth.get("resonator_shift", 0.0)) / p["kappa_MHz"]
            / fl["resonator_shift_kappa"],
            "noise_growth": truth.get("noise_growth", 0.0) / fl["noise_growth"],
            "t1_drop": (decay_prob(devs[0]) - decay_prob(p)) / fl["t1_drop_decay_increase"],
            "other": 1.0}  # iq_stretch, drawn at 1.5x or more
    return all(size[k] >= 1.0 for k in truth)


def _draw_once(rng, spec):
    while True:  # t1_drop: redraw until the drop raises the in-window decay probability enough
        p = draw_base(rng)
        truth, dr = {}, dict(delta=0.0, phi=0.0, ramp=0.0, g=1.0, s=1.0, t1f=1.0)
        for kind, size in spec:
            if kind == "iq_stretch":
                dr["rho"] = float(np.exp(rng.uniform(*np.log(STRETCH_RANGE))))
                dr["psi"] = float(rng.uniform(0, np.pi))
                truth[UNLISTED] = dr["rho"]
                continue
            lo, hi = (NEAR if size == "near" else RANGES)[kind]
            if kind == "t1_drop":
                mag = float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
            else:
                mag = rng.uniform(lo, hi) * (rng.choice([-1.0, 1.0]) if kind in SIGNED else 1.0)
            key = {"phase_rotation": "phi", "phase_ramp": "ramp", "gain_drop": "g",
                   "resonator_shift": "delta", "noise_growth": "s", "t1_drop": "t1f"}[kind]
            dr[key] = (gain_from_drop(mag) if key == "g" else mag * p["kappa_MHz"] if key == "delta"
                       else 1.0 + mag if key == "s" else mag)
            truth[kind] = float(dr[key] if key == "delta" else mag)
        if "t1_drop" not in truth:
            break
        q = dict(p, T1_us=p["T1_us"] / dr["t1f"])
        if decay_prob(q) - decay_prob(p) >= T1_MIN_DECAY_INCREASE:
            break
    dr["phi"] += rng.uniform(-NUIS["phase"], NUIS["phase"])
    dr["ramp"] += rng.uniform(-NUIS["ramp"], NUIS["ramp"])
    dr["g"] *= rng.uniform(1 - NUIS["gain"], 1 + NUIS["gain"])
    dr["s"] *= rng.uniform(1 - NUIS["noise"], 1 + NUIS["noise"])
    dr["delta"] += rng.uniform(-NUIS["shift"], NUIS["shift"]) * p["kappa_MHz"]
    dr["t1f"] *= rng.uniform(1 - NUIS["t1"], 1 + NUIS["t1"])
    devs = batch_devices(p, **dr)
    f, g = GAIN_NOISE_FRACTION, dr["g"]
    total = {"phase_rotation": dr["phi"], "phase_ramp": dr["ramp"], "resonator_shift": dr["delta"],
             "gain_drop": 1 - g / np.sqrt(f * g * g + 1 - f), "noise_growth": dr["s"] - 1,
             "t1_drop": dr["t1f"]}
    total[UNLISTED] = dr.get("rho", 1.0)
    truth = {k: float(total[k]) for k in truth}  # graded sizes include the background wander
    e = lambda rel: 1.0 + rng.uniform(-rel, rel)  # noqa: E731
    nominal = dict(kappa_MHz=p["kappa_MHz"] * e(0.05), chi_MHz=p["chi_MHz"] * e(0.05),
                   drive_offset_MHz=p["drive_offset_MHz"] + rng.uniform(-0.03, 0.03) * p["kappa_MHz"],
                   amplitude=e(0.03), theta0_rad=p["theta0_rad"] + rng.uniform(-0.03, 0.03),
                   T_int_us=p["T_int_us"], T1_us=p["T1_us"] * e(0.15),
                   p_thermal=p["p_thermal"] * e(0.3), gain_noise_fraction=GAIN_NOISE_FRACTION)
    return p, devs, truth, rng, nominal


def sample_shots(rng, devs, prep, batch):
    """Integrated IQ points for prepared states `prep` taken in batches `batch` (device per batch)."""
    prep, batch = np.asarray(prep), np.asarray(batch)
    n = prep.size
    actual = prep.copy()
    flip = rng.random(n) < devs[0]["p_thermal"]  # thermal population: preparation error
    actual[flip] = 1 - actual[flip]
    T = devs[0]["T_int_us"]
    T1 = np.array([d["T1_us"] for d in devs])[batch]
    frac = np.where(actual == 1, np.minimum(rng.exponential(T1) / T, 1.0), 0.0)
    mu0 = np.array([d["mu0"] for d in devs])[batch]
    mu1 = np.array([d["mu1"] for d in devs])[batch]
    sig = np.array([d["sigma"] for d in devs])[batch]
    pts = frac[:, None] * mu1 + (1 - frac)[:, None] * mu0
    noise = rng.standard_normal((n, 2))
    if "cov" not in devs[0]:
        return pts + sig[:, None] * noise
    L = np.linalg.cholesky(devs[0]["cov"])  # the stretch is the same in every batch
    return pts + noise @ L.T


# ----------------------------------------------------------------------------- discriminators
def lda_components(x, y):
    """Calibration LDA written as two Gaussians with a shared covariance (the stale anchor)."""
    m0, m1 = x[y == 0].mean(0), x[y == 1].mean(0)
    cov = np.cov(np.vstack([x[y == 0] - m0, x[y == 1] - m1]).T)
    return [dict(mean=m0, cov=cov, weight=1.0, label=0), dict(mean=m1, cov=cov, weight=1.0, label=1)]


def check_components(comps):
    """Validate one batch's component list; return arrays or raise ValueError."""
    if not isinstance(comps, list) or not 1 <= len(comps) <= MAX_COMPONENTS:
        raise ValueError(f"need 1 to {MAX_COMPONENTS} components per batch")
    out = []
    for c in comps:
        if not isinstance(c, dict):
            raise ValueError("component must be a dict")
        mean = np.asarray(c["mean"], dtype=float)
        cov = np.asarray(c["cov"], dtype=float)
        w, lab = float(c["weight"]), c["label"]
        if mean.shape != (2,) or cov.shape != (2, 2) or lab not in (0, 1) or isinstance(lab, bool):
            raise ValueError("mean (2,), cov (2, 2), label 0 or 1")
        if not (np.all(np.isfinite(mean)) and np.all(np.isfinite(cov)) and np.isfinite(w) and w > 0):
            raise ValueError("non-finite value or weight <= 0")
        if abs(cov[0, 1] - cov[1, 0]) > 1e-9 * np.abs(cov).max() or np.linalg.eigvalsh(cov).min() <= 0:
            raise ValueError("cov must be symmetric positive definite")
        out.append((mean, cov, w, int(lab)))
    return out


def classify(comps, pts):
    """Max-posterior label; weights are normalised within each label, labels get equal priors."""
    ll = {0: [], 1: []}
    tot = {lab: sum(w for _, _, w, l2 in comps if l2 == lab) for lab in (0, 1)}
    for mean, cov, w, lab in comps:
        d = pts - mean
        sol = np.linalg.solve(cov, d.T).T
        ll[lab].append(np.log(w / tot[lab]) - 0.5 * (d * sol).sum(1) - 0.5 * np.log(np.linalg.det(cov)))
    lab = [np.logaddexp.reduce(np.array(ll[k]), axis=0) if ll[k] else np.full(len(pts), -np.inf)
           for k in (0, 1)]
    return (lab[1] > lab[0]).astype(int)


def classify_batches(per_batch, x, b):
    out = np.empty(len(x), dtype=int)
    for k in range(N_BATCHES):
        m = b == k
        out[m] = classify(per_batch[k], x[m])
    return out


def oracle_labels(devs, x, b):
    """Exact equal-prior Bayes rule for the true device, T1 tail included (thermal flips are
    symmetric and do not move it). This is the best any discriminator can do."""
    out = np.empty(len(x), dtype=int)
    for k, d in enumerate(devs):
        m = b == k
        xs, s2 = x[m], d["sigma"] ** 2
        if "cov" in d:  # whiten: the Bayes rule is invariant under the linear map
            W = np.linalg.inv(np.linalg.cholesky(d["cov"]))
            xs, s2 = xs @ W.T, 1.0
            d = dict(d, mu0=W @ d["mu0"], mu1=W @ d["mu1"])
        g = lambda c: np.exp(-((xs - c) ** 2).sum(1) / (2 * s2))  # noqa: E731
        r = d["T_int_us"] / d["T1_us"]
        f1 = np.exp(-r) * g(d["mu1"])
        for u, w in zip(_GL_U, _GL_W):
            f1 += w * r * np.exp(-r * u) * g(u * d["mu1"] + (1 - u) * d["mu0"])
        out[m] = (f1 > g(d["mu0"])).astype(int)
    return out


def balanced_set(rng, devs, per):
    y = np.tile(np.repeat([0, 1], per), N_BATCHES)
    b = np.repeat(np.arange(N_BATCHES), 2 * per)
    perm = rng.permutation(y.size)
    y, b = y[perm], b[perm]
    return sample_shots(rng, devs, y, b), y, b


def make_instance(seed, spec, quick=False, tier="standard"):
    p, devs, truth, rng, nominal = draw_device(seed, spec)
    y_cal = np.repeat([0, 1], N_CAL_PER_STATE)
    x_cal = sample_shots(rng, [p], y_cal, np.zeros(y_cal.size, dtype=int))
    per = int(rng.integers(N_NEW_RANGE[0], N_NEW_RANGE[1] + 1)) // N_BATCHES
    pops = rng.uniform(0.2, 0.8, N_BATCHES)
    y_new = (rng.random((N_BATCHES, per)) < pops[:, None]).astype(int).ravel()
    batch = np.repeat(np.arange(N_BATCHES), per)
    x_new = sample_shots(rng, devs, y_new, batch)
    stale = check_components(lda_components(x_cal, y_cal))
    # Scoring rule, fixed at build time from a separate large sample (never the test sample).
    xr, yr, br = balanced_set(np.random.default_rng([seed, 11]), devs, N_RULE_PER_BATCH_STATE)
    rule_gap = float((classify(stale, xr) != yr).mean() - (oracle_labels(devs, xr, br) != yr).mean())
    rule = "control" if not truth else ("fix" if rule_gap >= GAP_MIN else "diagnosis_only")
    nt = N_TEST_PER_BATCH_STATE_QUICK if quick else N_TEST_PER_BATCH_STATE
    x_test, y_test, b_test = balanced_set(np.random.default_rng([seed, 7]), devs, nt)
    data = {"nominal": nominal, "calib_iq": x_cal, "calib_labels": y_cal,
            "shots_iq": x_new, "shots_batch": batch, "n_batches": N_BATCHES,
            "kinds": list(KINDS), "no_change_floor": dict(NO_CHANGE_FLOOR)}
    if tier != "standard":
        data["tier"] = tier
    hidden = dict(truth=truth, devs=devs, stale=stale, rule=rule, rule_gap=rule_gap,
                  x_test=x_test, y_test=y_test, b_test=b_test)
    return data, hidden


# ----------------------------------------------------------------------------- scoring
def parse_output(out):
    """Return (per-batch component lists, changed, kinds) or raise ValueError."""
    if not isinstance(out, dict):
        raise ValueError("return a dict")
    disc = out["discriminator"]
    if isinstance(disc, list) and disc and isinstance(disc[0], list):
        if len(disc) != N_BATCHES:
            raise ValueError(f"per-batch discriminator needs {N_BATCHES} lists")
        per = [check_components(c) for c in disc]
    else:
        per = [check_components(disc)] * N_BATCHES
    diag = out["diagnosis"]
    changed = diag["changed"]
    if not isinstance(changed, bool):
        raise ValueError("diagnosis.changed must be true or false")
    kinds = diag.get("kinds", {}) if changed else {}
    if not isinstance(kinds, dict):
        raise ValueError("diagnosis.kinds must be a dict")
    return per, changed, {str(k): v for k, v in kinds.items()}


def mag_ok(kind, m, true):
    try:
        m = float(m)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(m):
        return False
    a, rel = MAG_TOL[kind]
    if kind in SIGNED and np.sign(m) != np.sign(true):
        return False
    return abs(m - true) <= max(a, rel * abs(true))


def run_instance(solution_path, seed, spec, quick=False, tier="standard"):
    data, h = make_instance(seed, spec, quick, tier)
    x, y, b, truth = h["x_test"], h["y_test"], h["b_test"], h["truth"]
    m_stale = float((classify(h["stale"], x) != y).mean())
    m_orac = float((oracle_labels(h["devs"], x, b) != y).mean())
    rec = dict(seed=int(seed), truth={k: round(v, 4) for k, v in truth.items()}, rule=h["rule"],
               rule_gap=h["rule_gap"], n_shots=len(data["shots_iq"]), m_stale=m_stale,
               m_oracle=m_orac)
    ok, out, rt = run_solver(solution_path, data, TIME_LIMIT_S)
    rec["runtime_s"] = rt
    try:
        if not ok:
            raise ValueError(out)
        per, changed, kinds = parse_output(out)
        m_sol = float((classify_batches(per, x, b) != y).mean())
    except Exception as exc:  # noqa: BLE001
        rec.update(error=f"{type(exc).__name__}: {exc}"[:300], changed=None, fix=0.0, score=0.0,
                   rubric=rubric.invalid())
        return rec
    if h["rule"] == "fix":
        gap = max(m_stale - m_orac, 0.5 * h["rule_gap"])
        fix = float(np.clip((m_stale - m_sol) / gap, 0, 1))
    else:
        fix = float(np.clip(1 - (m_sol - m_stale - NOHARM_TOL) / NOHARM_SPAN, 0, 1))
    t, r = set(truth), set(kinds)
    kind = 1.0 if not (t | r) else len(t & r) / len(t | r)
    graded = t - {"t1_drop", UNLISTED}  # t1_drop size not identifiable; "other" kind only
    mag = kind if not graded else sum(mag_ok(k, kinds[k], truth[k]) for k in graded & r) / len(graded)
    checks = rubric.instance_checks(h["rule"], changed == bool(truth), fix, kind, mag)
    rec.update(m_sol=m_sol, changed=changed, reported=json.loads(json.dumps(kinds, default=str)),
               fix=fix, kind=kind, magnitude=mag, score=rubric.total(checks), rubric=checks)
    return rec


def instance_list(seed=None, quick=False, tier="standard"):
    specs = TIERS[tier]["specs"]
    salt = [] if tier == "standard" else [2]  # hard-tier devices are independent of standard
    seeds = TIERS[tier]["public"] if seed is None else \
        [int(s) for s in np.random.default_rng([int(seed), *salt]).integers(0, 2**31, len(specs))]
    pairs = list(zip(seeds, specs))
    if quick:
        return [pairs[i] for i in QUICK_IDX]
    # Shuffle the order per seed (as qec and pulse do): a fixed order (15 drifts, then 15
    # controls) let a solver that counts its own calls read the answers off the position.
    order = np.random.default_rng([0 if seed is None else int(seed), 999_999, *salt]).permutation(len(pairs))
    return [pairs[i] for i in order]


def evaluate(solution_path, quick=False, seed=None, tier="standard"):
    recs = [run_instance(solution_path, s, k, quick, tier)
            for s, k in instance_list(seed, quick, tier)]
    ctrl = [r for r in recs if r["rule"] == "control"]
    drift = [r for r in recs if r["rule"] != "control"]
    summary = dict(score=float(np.mean([r["score"] for r in recs])),
                   false_alarm_rate=float(np.mean([r["changed"] is not False for r in ctrl])) if ctrl else None,
                   miss_rate=float(np.mean([r["changed"] is not True for r in drift])) if drift else None,
                   n_fix=sum(r["rule"] == "fix" for r in recs),
                   n_diagnosis_only=sum(r["rule"] == "diagnosis_only" for r in recs),
                   n_control=len(ctrl), errors=sum("error" in r for r in recs))
    summary.update(tier=tier, rubric=rubric.VERSION)
    return {"score": summary["score"], "summary": summary, "instances": recs}
