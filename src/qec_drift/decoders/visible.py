from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import stim

from qec_drift.decoders import adaptive, pij
from qec_drift.decoders.visible_state import save_bank

NOMINAL_SHOTS = 20_000
PERMUTATIONS = 99
BLOCKS = (32, 128, 512)
MIN_DURATION = 50


def detectors(value: np.ndarray, width: int | None = None) -> np.ndarray:
    x = np.asarray(value)
    if x.ndim != 2 or not x.shape[0] or not x.shape[1]:
        raise ValueError("Expected a nonempty detector matrix")
    if width is not None and x.shape[1] != width:
        raise ValueError("Detector count does not match nominal circuit")
    if not np.isin(x, (0, 1)).all():
        raise ValueError("Detector values must be binary")
    return x.astype(bool, copy=False)


def adequacy_p(nominal: np.ndarray, deploy: np.ndarray) -> float:
    nominal, deploy = detectors(nominal), detectors(deploy)
    if nominal.shape[1] != deploy.shape[1]:
        raise ValueError("Detector counts differ")
    n, m = len(nominal), len(deploy)
    both = np.concatenate((nominal, deploy))
    total = both.sum(0, dtype=np.float64)
    p = np.clip(total / (n + m), 1e-4, 1 - 1e-4)
    denominator = np.sqrt(p * (1 - p) * (1 / n + 1 / m))

    def statistic(first: np.ndarray) -> float:
        count = first.sum(0, dtype=np.float64)
        return float(np.max(np.abs(count / n - (total - count) / m) / denominator))

    observed = statistic(nominal)
    rng = np.random.default_rng(1)
    exceed = sum(
        statistic(both[rng.permutation(n + m)[:n]]) >= observed for _ in range(PERMUTATIONS)
    )
    return (1 + exceed) / (1 + PERMUTATIONS)


def temporal_statistic(x: np.ndarray) -> float:
    values = []
    for size in BLOCKS:
        n = len(x) // size
        if n < 4:
            continue
        blocks = x[: n * size].reshape(n, size, x.shape[1]).mean(1)
        p = np.clip(blocks.mean(0), 1e-4, 1 - 1e-4)
        values.append(float(np.max(np.abs(blocks - blocks.mean(0)) / np.sqrt(p * (1 - p) / size))))
    if not values:
        raise ValueError("Stationarity requires at least four blocks of 32 shots")
    return max(values)


def stationarity_p(deploy: np.ndarray) -> float:
    x = detectors(deploy)
    observed = temporal_statistic(x)
    rng = np.random.default_rng(2)
    exceed = sum(
        temporal_statistic(x[rng.permutation(len(x))]) >= observed for _ in range(PERMUTATIONS)
    )
    return (1 + exceed) / (1 + PERMUTATIONS)


def localize(bank: adaptive.Adaptive, deploy: np.ndarray) -> tuple[set[int], list[tuple[int, ...]]]:
    keys = bank.assignments(deploy)
    counts = Counter(h for key in keys for h in key)
    found = set().union(*(bank.hypotheses[h][0] for h, n in counts.items() if n >= MIN_DURATION))
    allowed = set(bank.stale.get_final_qubit_coordinates())
    if any(not region <= allowed for region, _, _ in bank.hypotheses):
        raise ValueError("Hypothesis contains a qubit outside QUBIT_COORDS")
    return found, sorted(set(keys))


def fit(folder: Path) -> dict:
    nominal = stim.Circuit.from_file(folder / "nominal.stim")
    with np.load(folder / "deploy.npz", allow_pickle=False) as data:
        if set(data.files) != {"det"}:
            raise ValueError("Deploy input must contain detector events only")
        deploy = detectors(data["det"], nominal.num_detectors)
    if len(deploy) < 4 * min(BLOCKS):
        result = {"status": "unsupported", "reason": "Fewer than128deploy shots"}
        (folder / "fit.json").write_text(json.dumps(result) + "\n")
        return result
    simulated = nominal.compile_detector_sampler(seed=0).sample(NOMINAL_SHOTS)
    adequate_p = adequacy_p(simulated, deploy)
    time_p = stationarity_p(deploy)
    adequate, stationary = adequate_p > 0.01, time_p > 0.01
    found, keys, bank = set(), [], None
    if not adequate:
        bank = adaptive.Adaptive(nominal, seed=0)
        found, keys = localize(bank, deploy)
    scope = (
        "none"
        if adequate
        else (
            "global"
            if len(found) >= (len(nominal.get_final_qubit_coordinates()) + 1) // 2
            else "local"
        )
    )
    mode = {"none": "nominal", "global": "refit", "local": "adaptive"}[scope]
    report = {
        "model_adequate": adequate,
        "confidence": 50,
        "scope": scope,
        "changed_qubits": sorted(found),
        "mechanism": {"none": "none", "global": "readout", "local": "all"}[scope],
        "stationary": stationary,
        "what_is_wrong": "nothing" if adequate else "Detector statistics differ from nominal.",
        "evidence": f"Fixed permutation tests: adequacy p={adequate_p}; stationarity p={time_p}.",
    }
    if mode == "adaptive":
        save_bank(bank, keys, folder)
    else:
        dem = nominal.detector_error_model(decompose_errors=True)
        if mode == "refit":
            dem = pij.refit(dem, deploy)
        (folder / "model.dem").write_text(str(dem))
    result = {"status": "ready", "mode": mode, "adequacy_p": adequate_p, "stationarity_p": time_p}
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (folder / "fit.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
