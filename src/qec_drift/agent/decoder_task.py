"""Decoder-gap tasks: a nominal circuit, hidden true noise, shots, and reference decoders.

The agent sees the nominal circuit and shots from the true noise. The score is the gap closed
(docs/plan-decoder-agent.md): 0 is plain matching on the nominal model, 1 is correlated matching
with the true noise model.

Tier 2 (docs/benchmark-spec-2026-11-01.md) adds drift and adequate-model tasks. A task with a
`drift` kind (agent/drift.py) samples its train and validation shots from the pre-drift true
circuit and its test shots from a structurally changed circuit. The agent also gets `deploy.npz`,
detection events without labels from the test-time circuit, so drift is detectable before
submit. The ceiling is correlated matching with the test-time model; `stale_corr` (correlated
matching with the pre-drift model) shows what a perfect training-time fit is worth, and
`pij_corr` shows what the known refit method (decoders/pij.py) gets from the deploy shots. A
task with scenario "none" and no drift has an adequate nominal model: the awareness negative
class.

The "hard" set uses local faults (one qubit, one gate) on a magnitude ladder, where a rate test
over the whole batch barely moves and the agent has to say where the change is.

Example:
    uv run python -m qec_drift.agent.decoder_task data/agent_decoder --set hard
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymatching
import stim

from qec_drift.agent import drift
from qec_drift.agent.noise import (  # noqa: F401 - re-exported for callers and tests
    NOISE_GATES,
    P_NOMINAL,
    Q_CROSSTALK,
    nominal,
    with_crosstalk,
    with_scaled_gates,
    with_scaled_qubits,
)
from qec_drift.decoders import adaptive, pij

SIGMA = drift.SIGMA
DISTANCES = (5, 7)
SCENARIOS = ("hetero", "crosstalk", "both")
DRIFTS = ("meas5", "requbit")  # the tier 2 pilot kinds; agent/drift.py has the grammar
SHOTS = {"train": 100_000, "val": 20_000, "deploy": 20_000, "test": 300_000}
SEEDS = {"train": 11, "val": 12, "test": 13, "deploy": 14}


def with_drift(pre: stim.Circuit, kind: str, d: int, seed: int = 0) -> stim.Circuit:
    """The test-time circuit: the pre-drift circuit with one structural change."""
    return drift.apply(pre, kind, d, seed)


def true_circuit(d: int, scenario: str, seed: int = 0) -> stim.Circuit:
    """The pre-drift true circuit. Scenario "none" is the nominal circuit (an adequate model)."""
    c = nominal(d)
    if scenario in ("crosstalk", "both"):
        c = with_crosstalk(c)
    if scenario in ("hetero", "both"):
        c = with_scaled_qubits(c, SIGMA, seed=7 + d + 100 * seed)
    return c


def sample(circuit: stim.Circuit, shots: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    return circuit.compile_detector_sampler(seed=seed).sample(shots, separate_observables=True)


def _telegraph(rng: np.random.Generator, shots: int, k: int, dwell: int) -> np.ndarray:
    """Regime per shot: the base regime 0 alternating with a random other one, each stretch a
    geometric length of mean dwell."""
    out = np.empty(shots, dtype=np.int16)
    i, base = 0, bool(rng.integers(2))
    while i < shots:
        n = int(rng.geometric(1 / dwell))
        out[i : i + n] = 0 if base else int(rng.integers(1, k))
        i, base = i + n, not base
    return out


def regime_sequence(proc: drift.Process, shots: int, seed: int) -> np.ndarray:
    """The regime of each shot, in time order, for this process and seed."""
    if proc.stationary:
        return np.zeros(shots, dtype=np.int16)
    if proc.order == "ramp":
        return (np.arange(shots) * len(proc.circuits) // shots).astype(np.int16)
    rng = np.random.default_rng(seed)
    if proc.dwell is None:
        return rng.choice(len(proc.circuits), size=shots, p=proc.shares).astype(np.int16)
    return _telegraph(rng, shots, len(proc.circuits), proc.dwell)


def sample_process(
    proc: drift.Process, shots: int, seed: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Shots from a process in time order: detection events, observables, regime per shot."""
    regime = regime_sequence(proc, shots, seed)
    if proc.stationary:
        det, obs = sample(proc.circuits[0], shots, seed)
        return det, obs, regime
    first = proc.circuits[0]
    det = np.zeros((shots, first.num_detectors), dtype=bool)
    obs = np.zeros((shots, first.num_observables), dtype=bool)
    for r, circuit in enumerate(proc.circuits):
        idx = np.flatnonzero(regime == r)
        if idx.size:
            det[idx], obs[idx] = sample(circuit, int(idx.size), seed + 7919 * (r + 1))
    return det, obs, regime


def logical_error_rate(pred: np.ndarray, obs: np.ndarray) -> float:
    pred = np.asarray(pred, dtype=bool).reshape(obs.shape)
    return float(np.mean(np.any(pred != obs, axis=1)))


def _rates(dem: stim.DetectorErrorModel, det: np.ndarray, obs: np.ndarray) -> tuple[float, float]:
    plain, corr = pij.decoders(dem)
    return (
        logical_error_rate(plain.decode_batch(det), obs),
        logical_error_rate(corr.decode_batch(det, enable_correlations=True), obs),
    )


def _oracle_rates(
    proc: drift.Process, det: np.ndarray, obs: np.ndarray, regime: np.ndarray
) -> tuple[float, float]:
    """Plain and correlated matching where every shot is decoded with its own regime's model."""
    plain_pred, corr_pred = np.zeros(obs.shape, bool), np.zeros(obs.shape, bool)
    for r, circuit in enumerate(proc.circuits):
        idx = np.flatnonzero(regime == r)
        if not idx.size:
            continue
        plain, corr = pij.decoders(circuit.detector_error_model(decompose_errors=True))
        plain_pred[idx] = np.asarray(plain.decode_batch(det[idx]), bool).reshape(idx.size, -1)
        corr_pred[idx] = np.asarray(
            corr.decode_batch(det[idx], enable_correlations=True), bool
        ).reshape(idx.size, -1)
    return logical_error_rate(plain_pred, obs), logical_error_rate(corr_pred, obs)


WINDOW = 50  # shots pooled on each side when a telegraph state is read off the time series


def window_rate(proc: drift.Process, det: np.ndarray, obs: np.ndarray, seed: int) -> float:
    """The known method for telegraph noise: per shot, the likelihood ratio of each other
    regime against the base on the detectors they differ on, averaged over a window of
    consecutive shots, then correlated matching with the regime that wins (the base when none
    does). The regimes are given; what the agent must also do is find them."""
    rates = [
        np.clip(sample(c, 20_000, seed + 31 * i)[0].mean(0), 1e-4, 0.5)
        for i, c in enumerate(proc.circuits)
    ]
    x = det.astype(np.float32)
    kernel = np.ones(2 * WINDOW + 1) / (2 * WINDOW + 1)
    scores = []
    for r in rates[1:]:
        sel = np.abs(np.log(r / rates[0])) > 0.3
        on, off = np.log(r / rates[0]) * sel, np.log((1 - r) / (1 - rates[0])) * sel
        scores.append(np.convolve(x @ on + (1 - x) @ off, kernel, mode="same"))
    llr = np.array(scores).T  # shots by other regimes
    best = llr.argmax(1)
    guess = np.where(llr[np.arange(len(best)), best] > 0, best + 1, 0).astype(np.int16)
    return _oracle_rates(proc, det, obs, guess)[1]


def references(
    d: int,
    scenario: str,
    det: np.ndarray,
    obs: np.ndarray,
    drift_kind: str = "",
    seed: int = 0,
    deploy: np.ndarray | None = None,
    regime: np.ndarray | None = None,
) -> dict[str, float]:
    """Logical error rate of the reference decoders on the given (test) shots.

    `true` and `true_corr` use the test-time model, per regime when the process is not
    stationary (an oracle that knows each shot's regime). With drift, `stale_corr` is
    correlated matching with the pre-drift model: the best a training-time fit can do. With
    deploy shots, `pij_plain` and `pij_corr` use the nominal DEM refit to them
    (decoders/pij.py). Non-stationary tasks add `window_corr` (the window method given the
    regimes) and `adaptive_corr` (decoders/adaptive.py, given nothing but the stale model and
    the time series: the honest known method, which the launch gate holds the pass rule to).
    """
    pre = true_circuit(d, scenario, seed)
    proc = drift.process(pre, drift_kind, d, seed)
    nominal_dem = nominal(d).detector_error_model(decompose_errors=True)
    out = {}
    out["nominal"], out["nominal_corr"] = _rates(nominal_dem, det, obs)
    if proc.stationary:
        true_dem = proc.circuits[0].detector_error_model(decompose_errors=True)
        out["true"], out["true_corr"] = _rates(true_dem, det, obs)
    else:
        if regime is None:
            raise ValueError("a non-stationary task needs the regime of every shot")
        out["true"], out["true_corr"] = _oracle_rates(proc, det, obs, regime)
        out["window_corr"] = window_rate(proc, det, obs, seed)
        out["adaptive_corr"] = logical_error_rate(adaptive.Adaptive(pre, seed).decode(det), obs)
    if drift_kind:
        dem = pre.detector_error_model(decompose_errors=True)
        corr = pymatching.Matching.from_detector_error_model(dem, enable_correlations=True)
        out["stale_corr"] = logical_error_rate(
            corr.decode_batch(det, enable_correlations=True), obs
        )
    if deploy is not None:
        out["pij_plain"], out["pij_corr"] = _rates(pij.refit(nominal_dem, deploy), det, obs)
    return out


def nominal_predictions(d: int, det: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Plain and correlated nominal matching on the shots: what an unchanged decoder predicts."""
    plain, corr = pij.decoders(nominal(d).detector_error_model(decompose_errors=True))
    return plain.decode_batch(det), corr.decode_batch(det, enable_correlations=True)


def gap_closed(l_agent: float, refs: dict[str, float]) -> float:
    top = refs["nominal"] - refs["true_corr"]
    return (refs["nominal"] - l_agent) / top if top > 0 else float("nan")


def gap_drift(l_agent: float, refs: dict[str, float]) -> float:
    """The share of the drift loss recovered: 0 is the stale correlated fit, 1 the test-time model.

    NaN without drift. Most of the plain gap is the correlated-matching gain; this isolates what
    noticing the drift was worth.
    """
    if "stale_corr" not in refs:
        return float("nan")
    top = refs["stale_corr"] - refs["true_corr"]
    return (refs["stale_corr"] - l_agent) / top if top > 0 else float("nan")


@dataclass(frozen=True)
class Task:
    d: int
    scenario: str
    drift: str = ""  # test-time structural change (agent/drift.py); "" means no drift
    seed: int = 0  # replicate seed: per-qubit scales, local fault positions, every shot sample
    deploy: int | None = None  # unlabeled test-time shots the agent gets; None: SHOTS["deploy"]

    @property
    def name(self) -> str:
        tail = (f"-d{self.drift}" if self.drift else "") + (f"-s{self.seed}" if self.seed else "")
        tail += f"-n{self.deploy}" if self.deploy else ""
        return f"d{self.d}-{self.scenario}{tail}"

    @property
    def model_adequate(self) -> bool:
        """True when the nominal circuit is the true noise: the awareness negative class."""
        return self.scenario == "none" and not self.drift

    @property
    def stationary(self) -> bool:
        return drift.stationary(self.drift)

    @property
    def truth(self) -> drift.Truth:
        """What a correct diagnosis of this task says, about the deploy batch the agent saw."""
        pre = true_circuit(self.d, self.scenario, self.seed)
        present = None
        if not self.stationary:
            proc = drift.process(pre, self.drift, self.d, self.seed, "deploy")
            n = self.deploy or SHOTS["deploy"]
            present = set(regime_sequence(proc, n, SEEDS["deploy"] + 1000 * self.seed).tolist())
        return drift.truth(pre, self.drift, self.d, self.seed, present)


def all_tasks() -> list[Task]:
    return [Task(d, s) for d in DISTANCES for s in SCENARIOS]


def tier2_tasks() -> list[Task]:
    """The tier 2 pilot set: 4 adequate-model tasks, 8 drift tasks, 2 static replicates."""
    out = [Task(d, "none", "", seed) for d in DISTANCES for seed in (0, 1)]
    out += [
        Task(d, base, kind) for d in DISTANCES for base in ("none", "hetero") for kind in DRIFTS
    ]
    out += [Task(d, "hetero", "", 1) for d in DISTANCES]
    return out


def hard_tasks() -> list[Task]:
    """Faults that matter for decoding and need a diagnosis, plus adequate-model negatives.

    Measured at d = 5 before this set was fixed (docs/drift-pilot-2026-11-01.md): readout faults
    and correlated-pair substitution leave matching almost unchanged even at 40x, single-qubit
    faults at 15x to 30x and gate faults at 40x do not. The launch script drops any task whose
    true model is not at least 20% better than the stale fit. Combined kinds hide a subtle fault
    behind an obvious one; `deploy=2000` makes a full refit overfit.
    """
    out = [Task(5, "none", "", s) for s in (0, 1, 2)] + [Task(7, "none", "", s) for s in (0, 1)]
    out += [Task(5, "none", k, s) for k in ("bq15", "bq30") for s in (0, 1, 2)]
    out += [Task(5, "none", "bq30", s, deploy=2000) for s in (0, 1, 2)]
    out += [Task(5, "none", "bg40", s) for s in (0, 1, 2)]
    out += [Task(5, "none", "requbit", s) for s in (0, 1, 2)]
    out += [Task(5, "none", k) for k in ("meas5", "meas3")]
    out += [Task(5, "none", "bq15+line5", s) for s in (0, 1)]
    out += [Task(5, "none", "bq30+meas3"), Task(5, "hetero", "meas5"), Task(5, "hetero", "requbit")]
    out += [Task(7, "none", "bq30", s) for s in (0, 1)] + [Task(7, "none", "requbit")]
    return out


def nonstationary_tasks() -> list[Task]:
    """Noise that changes within the batch: fixed and wandering telegraph qubits, plus negatives.

    Measured at d = 5 with 100,000 shots before the set was fixed: a telegraph qubit at 50x
    leaves a 15% to 18% gap between the oracle and the stale fit, at 80x 17% to 25%; a
    wandering one at 50x leaves 48% to 50%, at 80x 57% to 58%. The stationary refit recovers
    about half of a fixed telegraph loss and none of a wandering one; the window method 0.67 to
    0.98. The gate drops what falls under 20%.
    """
    out = [Task(5, "none", "", 3), Task(5, "none", "", 4), Task(7, "none", "", 2)]
    out += [Task(5, "none", k, s) for k in ("tls80", "tls50") for s in (0, 1, 2)]
    out += [Task(7, "none", "tls30", s) for s in (0, 1, 2)]
    out += [Task(5, "none", k, s) for k in ("wander30", "wander50", "wander80") for s in (0, 1, 2)]
    out += [Task(7, "none", "wander30", 0)]
    return out


def launch2_tasks() -> list[Task]:
    """The second launch pool: one task per physical scenario, no seed replicates.

    Each drift task is a different story about a superconducting chip, in the grammar of
    agent/drift.py: a two-level-system defect on one qubit that switches (tls30) or drifts
    into resonance over the batch (ramp20, ramp30, ramp40); defects on several qubits, one
    bad at a time (wander20, wander30, wander50d60, wander30d30), also seen through a short
    deploy batch (-n5000, -n2000); high-energy impacts that hit a region (patch20, patch30,
    patch50d40); a coupler whose two-qubit gate fails at changing places (gwander60,
    gwander60d60); a permanently bad qubit or coupler under a wandering fault (bq15+wander30,
    bg40+wander30); a chip whose qubits already differ from the model (hetero) under drift;
    and the main faults again at distance 7 and 9. Four adequate negatives.

    The gate in scripts/run_grid.py keeps a drift task when the oracle beats the stale fit by
    20% and the honest adaptive decoder recovers at least half of that loss.
    """
    out = [Task(5, "none", "", 5), Task(5, "none", "", 6), Task(7, "none", "", 3), Task(9, "none")]
    d5 = [
        ("tls30", 0, None), ("ramp30", 0, None), ("ramp20", 1, None), ("ramp40", 2, 5000),
        ("wander30", 1, None), ("wander20", 3, None), ("wander50d60", 2, None),
        ("wander30d30", 6, None), ("wander30", 4, 5000), ("wander30", 5, 2000),
        ("patch30", 0, None), ("patch20", 2, None), ("patch50d40", 1, None),
        ("gwander60", 0, None), ("gwander60d60", 1, None),
        ("bq15+wander30", 2, None), ("bg40+wander30", 3, None),
    ]  # fmt: skip
    out += [Task(5, "none", k, s, deploy=n) for k, s, n in d5]
    hetero = (("wander30", 0), ("patch30", 1), ("ramp30", 0))
    out += [Task(5, "hetero", k, s) for k, s in hetero]
    d7 = (("tls30", 0), ("ramp30", 0), ("wander30", 1), ("patch30", 2), ("gwander60", 0))
    out += [Task(7, "none", k, s) for k, s in d7]
    out += [Task(9, "none", "wander30"), Task(9, "none", "patch30")]
    return out


def launch2b_tasks() -> list[Task]:
    """The supplement to the launch2 pool, after a probe of the gate's gap condition: the
    single-defect stories at the magnitudes and places where the fault costs the stale decoder
    at least 20% (a 30x defect on an edge qubit costs it 6%; a ramp spends most of the batch
    below 10x). The same stories as launch2, at d5 and d7, and the coupler at 100x."""
    out = [Task(5, "none", "ramp80"), Task(5, "none", "tls30", 2), Task(5, "none", "gwander100")]
    out += [Task(5, "none", "gwander100d60", 1), Task(5, "hetero", "ramp80")]
    out += [Task(7, "none", k) for k in ("ramp100", "tls50", "gwander100")]
    return out


def launch2c_tasks() -> list[Task]:
    """Faster-moving faults for the hard rung (2026-11-04): GPT-6-Astra max passed 11 of the 13
    core tasks and failed only the fault that moves every 30 shots and the coupler that moves
    every 60. The same stories with shorter dwells, at d5 and d7, and a bad qubit under a fast
    wandering fault. At d5 the gate dropped a dwell of 15 or 20 shots (the honest decoder
    recovers 0.27 and 0.44 of the loss: too fast to follow) and kept the dwell of 30."""
    out = [Task(5, "none", "wander30d15", 7), Task(5, "none", "gwander100d30", 2)]
    out += [Task(5, "none", "patch50d20", 3), Task(5, "none", "bq15+wander30d30", 4)]
    out += [Task(7, "none", "wander30d30", 2), Task(7, "none", "gwander100d60", 1)]
    return out


def launch2d_tasks() -> list[Task]:
    """Candidates for a second hard rung (2026-11-04): on the 18-task core GPT-6-Astra max still
    passed 15, failing two single-qubit defects that hop every 30 or 60 shots. The same family,
    chosen by dwell and honest headroom, not by any model's results: a dwell of 40 at 30x, of 30
    at 50x and of 60 at 80x."""
    return [Task(5, "none", "wander30d40", 8), Task(5, "none", "wander50d30", 9),
            Task(5, "none", "wander80d60", 10)]  # fmt: skip


LAUNCH2_CORE = (
    "d5-none-s6",
    "d9-none",
    "d5-none-dbq30-s1",  # easy rung: one qubit 30x noisier, stationary
    "d5-none-dmeas5",  # easy rung: readout 5x worse on every qubit, stationary
    "d5-none-dtls30-s2",
    "d5-none-dpatch30",
    "d5-none-dwander30d30-s6",
    "d5-none-dgwander100d60-s1",
    "d5-none-dwander30-s5-n2000",
    "d5-none-dbg40+wander30-s3",
    "d7-none-dwander30-s1",
    "d5-none-dpatch50d40-s1",
    "d7-none-dgwander100",  # hard rung: a coupler that fails at changing places, distance 7
    # the hard rung added 2026-11-04, when GPT-6-Astra max passed 11 of the 13 tasks above:
    "d5-none-dgwander60d60-s1",  # a weaker coupler fault that moves every 60 shots
    "d5-none-dwander50d60-s2",  # a 50x defect that moves every 60 shots
    "d5-none-dbq15+wander30-s2",  # a permanently bad qubit under a wandering fault
    "d5-none-dgwander100d30-s2",  # the coupler fault moving every 30 shots
    "d5-none-dbq15+wander30d30-s4",  # a bad qubit under a fault moving every 30 shots
    # the second hard rung, 2026-11-04: GPT-6-Astra max still passed 15 of the 18; one defect
    # family (a qubit that hops every 30 to 60 shots), chosen by dwell and honest headroom:
    "d5-none-dwander30d40-s8",  # 30x, a new qubit every 40 shots
    "d5-none-dwander50d30-s9",  # 50x, every 30 shots
    "d5-none-dwander80d60-s10",  # 80x, every 60 shots
    "d7-none-dwander30d30-s2",  # 30x every 30 shots, distance 7
    "d7-none-dgwander100d60-s1",  # the coupler fault every 60 shots, distance 7
)


def launch2core_tasks() -> list[Task]:
    """The twenty-three tasks every arm runs first, a ladder so that no arm scores 0 or 100:
    two negatives, two stationary faults (the easy rung), eight moving faults, and eleven hard
    ones: a coupler fault at distance 7, five fast-moving or compound faults, and five qubits or
    couplers that hop every 30 to 60 shots. Arms extend to the rest of the gated pool while the
    subscriptions' weekly quotas allow."""
    pool = {t.name: t for t in launch2_tasks() + launch2b_tasks() + launch2c_tasks()}
    pool |= {t.name: t for t in launch2d_tasks()}
    pool |= {t.name: t for t in hard_tasks()}
    return [pool[name] for name in LAUNCH2_CORE]


def launch_tasks() -> list[Task]:
    """The launch set: moving faults only, with compounds, a faster dwell, a small deploy batch
    and regional patches; three adequate negatives. Fixed telegraph and stationary faults are
    the warm-up split, not the headline.

    The gate keeps a task when the oracle beats the stale fit by 20% and the honest adaptive
    decoder (no regime knowledge) recovers at least half of that loss.
    """
    out = [Task(5, "none", "", 5), Task(5, "none", "", 6), Task(7, "none", "", 3)]
    out += [Task(5, "none", k, s) for k in ("wander30", "wander50") for s in (0, 1, 2)]
    out += [Task(5, "none", "wander30d60", s) for s in (0, 1)]
    out += [Task(5, "none", "wander30", s, deploy=5000) for s in (0, 1)]
    out += [Task(5, "none", "patch30", s) for s in (0, 1)]
    out += [Task(5, "none", "bq15+wander30", s) for s in (0, 1)]
    out += [Task(5, "none", "meas2+wander30"), Task(5, "none", "bq15+meas2+wander30")]
    out += [Task(7, "none", "wander30"), Task(7, "none", "patch30")]
    return out


TASK_SETS = {
    "tier1": all_tasks,
    "tier2": tier2_tasks,
    "hard": hard_tasks,
    "nonstationary": nonstationary_tasks,
    "launch": launch_tasks,
    "launch2": launch2_tasks,
    "launch2b": launch2b_tasks,
    "launch2c": launch2c_tasks,
    "launch2d": launch2d_tasks,
    "launch2core": launch2core_tasks,
}


def tasks_by_name(names: str) -> list[Task]:
    """Tasks from a comma list of names, looked up over every set."""
    known = {t.name: t for f in TASK_SETS.values() for t in f()}
    wanted = list(dict.fromkeys(n.strip() for n in names.split(",") if n.strip()))
    unknown = [n for n in wanted if n not in known]
    if unknown:
        raise ValueError(f"unknown task names {unknown}; known: {sorted(known)}")
    return [known[n] for n in wanted]


def test_process(task: Task, split: str = "test") -> drift.Process:
    pre = true_circuit(task.d, task.scenario, task.seed)
    return drift.process(pre, task.drift, task.d, task.seed, split)


def test_circuit(task: Task) -> stim.Circuit:
    """The test-time circuit of a stationary task."""
    pre = true_circuit(task.d, task.scenario, task.seed)
    return drift.apply(pre, task.drift, task.d, task.seed)


def deploy_shots(task: Task) -> np.ndarray:
    """Detection events from the test-time hardware, no labels, in time order: deploy.npz."""
    n = task.deploy or SHOTS["deploy"]
    return sample_process(test_process(task, "deploy"), n, SEEDS["deploy"] + 1000 * task.seed)[0]


def write_agent_files(task: Task, folder: Path) -> None:
    """The files the agent may read: the nominal circuit, calibration shots, deploy shots."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "nominal.stim").write_text(str(nominal(task.d)))
    circuit = true_circuit(task.d, task.scenario, task.seed)  # pre-drift: validation is stale
    for split in ("train", "val"):
        det, obs = sample(circuit, SHOTS[split], SEEDS[split] + 1000 * task.seed)
        np.savez_compressed(folder / f"{split}.npz", det=det, obs=obs)
    np.savez_compressed(folder / "deploy.npz", det=deploy_shots(task))


def test_sample(task: Task) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Test shots in time order with the regime of each: detection events, labels, regime."""
    return sample_process(test_process(task), SHOTS["test"], SEEDS["test"] + 1000 * task.seed)


def test_shots(task: Task) -> tuple[np.ndarray, np.ndarray]:
    det, obs, _ = test_sample(task)
    return det, obs


_REFERENCES: dict[str, dict[str, float]] = {}  # task name: rates, from a references.json


def load_references(path: Path) -> int:
    """Cache the reference rates of a references.json; task_references then skips the
    recomputation (the honest adaptive baseline takes minutes at distance 7 and more at 9)."""
    _REFERENCES.update(json.loads(Path(path).read_text()))
    return len(_REFERENCES)


def task_references(
    task: Task, det: np.ndarray, obs: np.ndarray, regime: np.ndarray | None = None
) -> dict[str, float]:
    if task.name in _REFERENCES:
        return dict(_REFERENCES[task.name])
    return references(
        task.d, task.scenario, det, obs, task.drift, task.seed, deploy_shots(task), regime
    )


def reference_row(task: Task) -> tuple[str, dict[str, float]]:
    det, obs, regime = test_sample(task)
    return task.name, task_references(task, det, obs, regime)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--set", default="tier1", choices=sorted(TASK_SETS))
    ap.add_argument("--workers", type=int, default=1, help="tasks scored at the same time")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / "references.json"
    table = json.loads(out.read_text()) if out.is_file() else {}  # grows across runs and sets
    with ProcessPoolExecutor(args.workers) as pool:
        for name, refs in pool.map(reference_row, TASK_SETS[args.set]()):
            table[name] = refs
            print(name, {k: round(v, 5) for k, v in refs.items()}, flush=True)
            out.write_text(json.dumps(table, indent=2))  # after every task: a cut run loses nothing


if __name__ == "__main__":
    main()
