"""Hidden flux line, ground truth, baselines and scoring for flux_distortion.

A flux-tunable transmon's flux line distorts every pulse: its step response is a cascade of
first-order stages, each adding a decaying exponential (Rol 2020, arXiv:1907.04818; Hellings
2025, arXiv:2503.04610, Eq. 1). The control stack predistorts each pulse with the inverse of the
stages it was calibrated with (the nominal model). Since then the line may have drifted. The
solver sees the step response measured through the current predistortion (cryoscope at short
times, spectroscopy at long times) and returns a new predistortion: exponential stages to invert
and an optional FIR filter, plus a diagnosis. The grader applies that predistortion to a hidden
test program, passes it through the true line and scores the flux error. The solver runs in a
separate process (eval/_isolate.py) and never sees the truth. Licence: Apache-2.0.
"""
import numpy as np
from scipy.signal import lfilter

import rubric
from _isolate import run_solver

# ---------------- line model ----------------
FS_GHZ = 2.4                      # AWG sample rate (2.4 GS/s in all three cited setups)
DT_NS = 1.0 / FS_GHZ
N_STAGES = 4                      # nominal stages (Hellings 2025 fit N = 4)
# Nominal stage time constants (ns), one per band, log-uniform; tau in [1 ns, 10 us] as in
# Venkateswaran 2026 (arXiv:2604.15895, Table 1). Amplitude bands: assumption (percent-level
# tails; Rol 2020 reconstruct to 0.1%, so these are well above the measurement floor).
TAU_BANDS = ((3.0, 15.0), (30.0, 150.0), (300.0, 1500.0), (3000.0, 10000.0))
AMP_BANDS = ((0.005, 0.03), (0.003, 0.02), (0.002, 0.01), (0.001, 0.005))
WANDER_AMP, WANDER_TAU = 0.03, 0.02   # relative wander on every instance (assumption)
# Drift families. tail_changed: one stage's amplitude moves by a factor exp(+-[0.25, 0.7]) and
# its time constant by exp(+-[0.1, 0.4]) (a component's value moved, assumption). new_tail: a
# new stage, |A| 0.15% to 1%, tau 20 ns to 5 us log-uniform, at least 2.5x from every nominal tau
# (assumption; nearer taus are not identifiable from a changed stage).
TAIL_AMP_LOG, TAIL_TAU_LOG = (0.25, 0.7), (0.1, 0.4)
NEW_AMP, NEW_TAU, NEW_SEP = (0.0015, 0.01), (20.0, 5000.0), 2.5
# Hard tier: part of the pulse arrives late (an impedance mismatch; Rol 2020 and Hellings 2025
# name reflections as a source but give no size). s(t) = 1 - r before the delay d, 1 after.
# r 0.5% to 2%, d 2 to 20 ns: assumption. Not an exponential stage: the solver reports "other".
ECHO_R, ECHO_D_NS = (0.005, 0.02), (2.0, 20.0)
KINDS = ("tail_changed", "new_tail")
UNLISTED = "other"

# ---------------- measurement ----------------
# Cryoscope: every 1 ns from 1 to 200 ns, sigma 1e-3 (Rol 2020: within ~0.1%). Spectroscopy:
# 60 log-spaced times 200 ns to 20 us, sigma 5e-4 (Hellings 2025: relative flux error ~5e-4).
T_SHORT = np.arange(1.0, 201.0)
T_LONG = np.geomspace(210.0, 20000.0, 60)
T_MEAS = np.concatenate([T_SHORT, T_LONG])
SIGMA = np.concatenate([np.full(T_SHORT.size, 1e-3), np.full(T_LONG.size, 5e-4)])
N_STEP = int(np.ceil(T_MEAS[-1] / DT_NS)) + 2
IDX_MEAS = np.round(T_MEAS / DT_NS).astype(int)

# ---------------- test program and scoring ----------------
# Hidden test program (described in TASK.md): unit-amplitude flux pulses the processor plays.
def _program():
    n = lambda ns: int(round(ns / DT_NS))  # noqa: E731
    parts = []
    for on, neg, idle in ((60, 0, 1000), (30, 30, 1000), (2000, 0, 3000)):
        parts.append(np.concatenate([np.ones(n(on)), -np.ones(n(neg)), np.zeros(n(idle))]))
    train = np.zeros(n(8 * 400 + 2000))
    for k in range(8):
        train[n(400 * k):n(400 * k + 60)] = 1.0
    parts.append(train)
    return parts


PROGRAM = _program()
AMP_CAP = 1.5                     # AWG range: predistorted samples are clipped here
FLOOR = (5e-4) ** 2               # mean squared error of the Hellings 2025 residual (~5e-4)
CHANGE_MIN, CONTROL_MAX = 2.0 * FLOOR, 0.5 * FLOOR  # draw rules (TASK.md)
NOHARM_FREE, NOHARM_ZERO = 0.25 * FLOOR, 1.0 * FLOOR
TOL_FULL_SIG, TOL_ZERO_SIG = 2.0, 4.0
MAX_STAGES, MAX_FIR = 8, 128
TIME_LIMIT_S = 120.0
N_INSTANCES, QUICK = 32, 8
TIERS = {"standard": dict(salt=[], public=0,
                          families=("tail_changed", "new_tail", "both")),
         "hard": dict(salt=[2], public=20261126,
                      families=("echo",) * 6 + ("echo_tail",) * 3 + ("echo_new",) * 3
                      + ("tail_changed", "new_tail", "both", "new_tail"))}


def stage_ba(amp, tau_ns):
    """First-order stage with step response 1 + amp exp(-t / tau): H = 1 + amp (1 - z^-1) /
    (1 - lam z^-1), lam = exp(-dt / tau). Returns (b, a)."""
    lam = np.exp(-DT_NS / tau_ns)
    return np.array([1.0 + amp, -(lam + amp)]), np.array([1.0, -lam])


def apply_line(x, stages, echo=None):
    """Pass samples x through the cascade of stages [(amp, tau_ns), ...] and an optional echo
    (r, d_ns): y = (1 - r) x + r x delayed by d."""
    y = np.asarray(x, float)
    for amp, tau in stages:
        b, a = stage_ba(amp, tau)
        y = lfilter(b, a, y)
    if echo is not None:
        r, d = echo
        k = int(round(d / DT_NS))
        y = (1.0 - r) * y + r * np.concatenate([np.zeros(k), y[:-k]])
    return y


def predistort(x, stages, fir=None):
    """The control stack's predistortion: the inverse of every stage, then the FIR."""
    y = np.asarray(x, float)
    for amp, tau in stages:
        b, a = stage_ba(amp, tau)
        y = lfilter(a, b, y)
    if fir is not None:
        y = lfilter(np.asarray(fir, float), [1.0], y)
    return np.clip(y, -AMP_CAP, AMP_CAP)


def measured_step(true_stages, echo, nominal_stages):
    """Step response of (true line o nominal predistortion) at the measurement times."""
    return apply_line(predistort(np.ones(N_STEP), nominal_stages), true_stages, echo)[IDX_MEAS]


def program_mse(true_stages, echo, stages, fir=None):
    """Mean squared flux error of the test program with the given predistortion."""
    err = [apply_line(predistort(w, stages, fir), true_stages, echo) - w for w in PROGRAM]
    return float(np.mean(np.concatenate(err) ** 2))


# ---------------- instances ----------------
def _logu(rng, lo, hi):
    return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))


def draw_nominal(rng):
    return [(float(rng.choice([-1, 1]) * rng.uniform(*a)), _logu(rng, *t))
            for a, t in zip(AMP_BANDS, TAU_BANDS)]


def draw_truth(rng, nominal, family):
    """True stages (with wander), changed stage index, new tail, echo; None if redraw."""
    true = [(a * (1 + rng.uniform(-WANDER_AMP, WANDER_AMP)),
             t * (1 + rng.uniform(-WANDER_TAU, WANDER_TAU))) for a, t in nominal]
    stage, new, echo = None, None, None
    if family in ("tail_changed", "both", "echo_tail"):
        stage = int(rng.integers(N_STAGES))
        a, t = true[stage]
        fa = np.exp(rng.choice([-1, 1]) * rng.uniform(*TAIL_AMP_LOG))
        ft = np.exp(rng.choice([-1, 1]) * rng.uniform(*TAIL_TAU_LOG))
        true[stage] = (a * fa, t * ft)
    if family in ("new_tail", "both", "echo_new"):
        tau = _logu(rng, *NEW_TAU)
        if min(max(tau / t, t / tau) for _, t in nominal) < NEW_SEP:
            return None
        new = (float(rng.choice([-1, 1]) * rng.uniform(*NEW_AMP)), tau)
    if family.startswith("echo"):
        echo = (float(rng.choice([-1, 1]) * rng.uniform(*ECHO_R)), rng.uniform(*ECHO_D_NS))
    return true + ([new] if new else []), stage, new, echo


def fisher_sigmas(stages, echo, nominal):
    """Cramer-Rao standard deviations of every stage's (amp, tau) from the measured step, all
    stages free (wander makes them nuisance parameters); the echo is held at its truth."""
    theta = np.array([v for s in stages for v in (s[0], np.log(s[1]))])
    def f(th):
        st = [(th[2 * i], np.exp(th[2 * i + 1])) for i in range(len(stages))]
        return measured_step(st, echo, nominal) / SIGMA
    J = []
    for i in range(theta.size):
        h = 1e-5 if i % 2 == 0 else 1e-3
        e = np.zeros_like(theta)
        e[i] = h
        J.append((f(theta + e) - f(theta - e)) / (2 * h))
    J = np.array(J)
    C = np.linalg.pinv(J @ J.T)
    sd = np.sqrt(np.maximum(np.diag(C), 0))
    return [(float(sd[2 * i]), float(sd[2 * i + 1])) for i in range(len(stages))]


def build(seed, i, family):
    """One instance: data for the solver, hidden truth, anchors and the scoring rule."""
    rng = np.random.default_rng([seed, i])
    nominal = draw_nominal(rng)
    for _ in range(200):
        drawn = draw_truth(rng, nominal, "control" if family == "control" else family)
        if drawn is None:
            continue
        true, stage, new, echo = drawn
        m_stale = program_mse(true, echo, nominal)
        if (family == "control") == (m_stale <= CONTROL_MAX) and \
                (family == "control" or m_stale >= CHANGE_MIN):
            break
    else:
        raise RuntimeError(f"no draw for {family} (seed {seed}, instance {i})")
    meas = measured_step(true, echo, nominal) + rng.normal(0.0, SIGMA)
    kinds = {k for k, on in (("tail_changed", stage is not None), ("new_tail", new is not None),
                             (UNLISTED, echo is not None)) if on}
    sig = fisher_sigmas(true, echo, nominal)
    data = {"nominal_stages": [{"amp": a, "tau_ns": t} for a, t in nominal],
            "sample_rate_gsps": FS_GHZ, "t_ns": T_MEAS.copy(), "step": meas,
            "sigma": SIGMA.copy(), "kinds": list(KINDS), "floor_mse": FLOOR,
            "max_stages": MAX_STAGES, "max_fir_taps": MAX_FIR}
    return dict(family=family, rule="control" if family == "control" else "fix",
                truth=dict(stages=true, changed_stage=stage, new_tail=new, echo=echo,
                           kinds=sorted(kinds), sigmas=sig),
                m_stale=m_stale, m_oracle=0.0, data=data)


def instance_list(seed=None, quick=False, tier="standard"):
    t = TIERS[tier]
    fams = ["control"] * (N_INSTANCES // 2) + [t["families"][k % len(t["families"])]
                                               for k in range(N_INSTANCES // 2)]
    master = t["public"] if seed is None else int(seed)
    rng = np.random.default_rng([master, 999_999, *t["salt"]])
    rng.shuffle(fams)
    seeds = rng.integers(0, 2**31, N_INSTANCES)
    out = [(int(s), k, f) for k, (s, f) in enumerate(zip(seeds, fams))]
    if quick:
        ctrl = [o for o in out if o[2] == "control"][:QUICK // 2]
        return ctrl + [o for o in out if o[2] != "control"][:QUICK // 2]
    return out


# ---------------- scoring ----------------
def parse_answer(out):
    stages = [(float(s["amp"]), float(s["tau_ns"])) for s in out["filters"]]
    if not 0 < len(stages) <= MAX_STAGES or not all(
            np.isfinite(a) and abs(a) < 0.5 and np.isfinite(t) and 0.2 <= t <= 1e5
            for a, t in stages):
        raise ValueError("filters: 1 to 8 stages, |amp| < 0.5, tau_ns in [0.2, 1e5]")
    fir = out.get("fir")
    if fir is not None:
        fir = np.asarray(fir, float).reshape(-1)
        if not 1 <= fir.size <= MAX_FIR or not np.all(np.isfinite(fir)):
            raise ValueError("fir: 1 to 128 finite taps")
    d = out["diagnosis"]
    if not isinstance(d["changed"], bool) or not isinstance(d.get("kinds", {}), dict):
        raise ValueError("diagnosis.changed must be bool and diagnosis.kinds a dict")
    kinds = d.get("kinds", {})
    if not set(kinds) <= {*KINDS, UNLISTED}:
        raise ValueError(f"unknown kind in {sorted(kinds)}")
    return stages, fir, d["changed"], kinds


def sig_credit(err, sigma):
    return float(np.clip((TOL_ZERO_SIG - abs(err) / max(sigma, 1e-12))
                         / (TOL_ZERO_SIG - TOL_FULL_SIG), 0, 1))


def param_credit(truth, kinds):
    """Mean over the true listed kinds of the product of their parameter credits."""
    parts, sig = [], truth["sigmas"]
    if truth["changed_stage"] is not None:
        k = truth["changed_stage"]
        rep = kinds.get("tail_changed") or {}
        a, t = truth["stages"][k]
        ok = rep.get("stage") == k
        parts.append(ok * sig_credit(float(rep.get("amp", np.inf)) - a, sig[k][0]) *
                     sig_credit(np.log(max(float(rep.get("tau_ns", 1e-9)), 1e-9)) - np.log(t),
                                sig[k][1]))
    if truth["new_tail"] is not None:
        a, t = truth["new_tail"]
        rep = kinds.get("new_tail") or {}
        parts.append(sig_credit(float(rep.get("amp", np.inf)) - a, sig[N_STAGES][0]) *
                     sig_credit(np.log(max(float(rep.get("tau_ns", 1e-9)), 1e-9)) - np.log(t),
                                sig[N_STAGES][1]))
    return float(np.mean(parts)) if parts else 1.0


def run_instance(solution_path, seed, i, family, tier):
    inst = build(seed, i, family)
    data = dict(inst.pop("data"), tier=tier)
    ok, out, secs = run_solver(solution_path, data, TIME_LIMIT_S)
    tr = inst["truth"]
    rec = dict(seed=seed, **inst, solve_s=round(secs, 2))
    try:
        if not ok:
            raise RuntimeError(out)
        stages, fir, changed, kinds = parse_answer(out)
    except Exception as exc:  # noqa: BLE001
        rec.update(error=f"{type(exc).__name__}: {exc}"[:300], changed=None, fix=0.0,
                   score=0.0, rubric=rubric.invalid())
        return rec
    m_sol = program_mse(tr["stages"], tr["echo"], stages, fir)
    if inst["rule"] == "fix":
        fix = float(np.clip((inst["m_stale"] - m_sol) / (inst["m_stale"] - inst["m_oracle"]),
                            0, 1))
    else:
        fix = float(np.clip((NOHARM_ZERO - (m_sol - inst["m_stale"]))
                            / (NOHARM_ZERO - NOHARM_FREE), 0, 1))
    true_k, rep_k = set(tr["kinds"]), set(kinds)
    kind = len(true_k & rep_k) / len(true_k | rep_k) if true_k | rep_k else 1.0
    # With no listed kind true (an unlisted change alone), params equals the kinds credit.
    par = (param_credit(tr, kinds) if set(tr["kinds"]) & set(KINDS) else kind) \
        if inst["rule"] == "fix" else 1.0
    checks = rubric.instance_checks(inst["rule"], changed == (inst["rule"] == "fix"), fix,
                                    kind, par)
    rec.update(m_sol=m_sol, changed=changed, reported=kinds, fix=fix, kind=kind, params=par,
               score=rubric.total(checks), rubric=checks)
    return rec


def evaluate(solution_path, quick=False, seed=None, tier="standard"):
    recs = [run_instance(solution_path, s, i, f, tier)
            for s, i, f in instance_list(seed, quick, tier)]
    ctrl = [r for r in recs if r["rule"] == "control"]
    drift = [r for r in recs if r["rule"] != "control"]
    summary = dict(score=float(np.mean([r["score"] for r in recs])),
                   false_alarm_rate=float(np.mean([r["changed"] is not False for r in ctrl])),
                   miss_rate=float(np.mean([r["changed"] is not True for r in drift])),
                   n_fix=len(drift), n_control=len(ctrl),
                   errors=sum("error" in r for r in recs), tier=tier, rubric=rubric.VERSION)
    return {"score": summary["score"], "summary": summary, "instances": recs}


if __name__ == "__main__":
    import sys
    print(f"{evaluate(sys.argv[1] if len(sys.argv) > 1 else '../sandbox/solution.py')['score']:.4f}")
