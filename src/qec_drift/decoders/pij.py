"""Refit a detector error model from unlabeled detection events: the pij method.

Spitz et al. 2018 (Adv. Quantum Technol. 1, 1800012) and the supplements of Google Quantum AI's
2021 and 2023 surface-code papers estimate the probability of each matching-graph edge from the
pairwise correlation of its two detectors,

    p_ij = 1/2 - 1/2 sqrt(1 - 4 (<x_i x_j> - <x_i><x_j>) / (1 - 2<x_i> - 2<x_j> + 4<x_i x_j>)),

and each boundary edge from the marginal once the pair edges are known,

    1 - 2<x_i> = (1 - 2 p_i) prod_j (1 - 2 p_ij).

The fit lifts to the nominal DEM: every error instruction is scaled by the ratio of the fitted
to the nominal probability of its first decomposed component, so hyperedges keep their structure
and correlated matching still works. The ratio is shrunk toward 1 with SHRINK pseudo-events, so
an edge seen a handful of times keeps its nominal probability and a small deploy batch does not
turn into noise. No labels are used, so a lab can run it on deploy data. This is the
expert-pipeline baseline for the drift tiers: what a known method gets.
"""

from __future__ import annotations

from collections import defaultdict
from math import prod, sqrt

import numpy as np
import pymatching
import stim

P_MIN, P_MAX = 1e-5, 0.45
SHRINK = 20.0  # pseudo-events that pull a fitted ratio toward the nominal 1
Key = tuple[int, ...]


def components(inst: stim.DemInstruction) -> list[Key]:
    """The detector sets of an error instruction's decomposed components, in order."""
    out: list[list[int]] = [[]]
    for t in inst.targets_copy():
        if t.is_separator():
            out.append([])
        elif t.is_relative_detector_id():
            out[-1].append(t.val)
    return [tuple(sorted(c)) for c in out if c]


def fitted_probabilities(
    dem: stim.DetectorErrorModel, det: np.ndarray
) -> tuple[dict[Key, float], dict[Key, float]]:
    """Edge probabilities (pairs and boundaries of the DEM) fitted to the detection events.

    Returns the fit and, per edge, the events it rests on: coincidences for a pair, detections
    for a boundary.
    """
    det = np.asarray(det, dtype=np.float32)
    n = det.shape[0]
    m = det.mean(0).astype(np.float64)
    c = (det.T @ det).astype(np.float64) / n
    keys = {k for inst in dem.flattened() if inst.type == "error" for k in components(inst)}
    pairs = sorted(k for k in keys if len(k) == 2)
    fit: dict[Key, float] = {}
    events: dict[Key, float] = {}
    for i, j in pairs:
        events[(i, j)] = c[i, j] * n
        num = c[i, j] - m[i] * m[j]
        den = 1 - 2 * m[i] - 2 * m[j] + 4 * c[i, j]
        x = 1 - 4 * num / den if den > 0 else 1.0
        p = 0.5 - 0.5 * sqrt(x) if x > 0 else 0.5
        fit[(i, j)] = float(np.clip(p, P_MIN, P_MAX))
    around: dict[int, list[float]] = defaultdict(list)
    for (i, j), p in fit.items():
        around[i].append(1 - 2 * p)
        around[j].append(1 - 2 * p)
    for (i,) in sorted(k for k in keys if len(k) == 1):
        events[(i,)] = m[i] * n
        p = 0.5 - (1 - 2 * m[i]) / (2 * prod(around[i]))
        fit[(i,)] = float(np.clip(p, P_MIN, P_MAX))
    return fit, events


def nominal_probabilities(dem: stim.DetectorErrorModel) -> dict[Key, float]:
    """The probability that each edge of the DEM flips, combined over every error that hits it."""
    keep: dict[Key, float] = defaultdict(lambda: 1.0)
    for inst in dem.flattened():
        if inst.type != "error":
            continue
        p = inst.args_copy()[0]
        for k in set(components(inst)):
            keep[k] *= 1 - p
    return {k: 1 - v for k, v in keep.items()}


def refit(
    dem: stim.DetectorErrorModel, det: np.ndarray, shrink: float = SHRINK
) -> stim.DetectorErrorModel:
    """The DEM with every error scaled to the fitted probability of its first component."""
    (fit, events), nominal = fitted_probabilities(dem, det), nominal_probabilities(dem)
    out = stim.DetectorErrorModel()
    for inst in dem.flattened():
        if inst.type != "error":
            out.append(inst)
            continue
        key = components(inst)[0]
        ratio = fit[key] / nominal[key] if nominal.get(key, 0) > 0 else 1.0
        ratio = (events[key] * ratio + shrink) / (events[key] + shrink)
        p = float(np.clip(inst.args_copy()[0] * ratio, P_MIN, P_MAX))
        out.append("error", [p], inst.targets_copy())
    return out


def decoders(dem: stim.DetectorErrorModel) -> tuple[pymatching.Matching, pymatching.Matching]:
    """Plain and correlated matching on a DEM."""
    return (
        pymatching.Matching.from_detector_error_model(dem),
        pymatching.Matching.from_detector_error_model(dem, enable_correlations=True),
    )
