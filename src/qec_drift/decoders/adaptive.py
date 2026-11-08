"""A benchmark-specific adaptive reference decoder for offline batches.

The reference builder supplies the pre-drift circuit and task seed. The seed controls
simulation of hypothesis detector rates. Actual fault locations, per-shot regime labels and
test observables are not inputs. Hypotheses cover every qubit, neighbour disk and CX pair at
the factors in MENU. Each shot uses WINDOW earlier and later shots, so decoding is not causal.
The likelihood test selects up to MAX_HOT hypotheses with disjoint detector support, then
uses correlated matching with those regions scaled.

DGR (Wang et al., arXiv:2311.16214v3, Section IV) is related work: it updates graph weights
from decoded-edge and edge-pair statistics. This implementation instead uses simulated fault
hypotheses and a centred-window likelihood test. It is a custom reference, not a reproduction
of DGR or an optimal decoder. The launch gate requires measured recovery of at least half
the drift loss. Full diagnosis reachability requires separate evidence.
"""

from __future__ import annotations

import numpy as np
import pymatching
import stim

from qec_drift.agent import noise
from qec_drift.agent.drift import disk as drift_disk
from qec_drift.agent.drift import gate_scaled

WINDOW = 50  # shots pooled on each side of a shot for its decision
CHUNK = 20_000  # shots scored at a time
MENU = (5.0, 10.0, 20.0, 40.0, 80.0)  # scale factors tried for a hot qubit
RATE_SHOTS = 4000  # shots sampled to learn each configuration's detector rates
MAX_HOT = 2  # regions reweighted at once for one shot
MIN_TOUCH = 0.3  # a detector counts for a hypothesis when it moves its log rate this much


def _rates(circuit: stim.Circuit, seed: int) -> np.ndarray:
    det, _ = circuit.compile_detector_sampler(seed=seed).sample(
        RATE_SHOTS, separate_observables=True
    )
    return np.clip(det.mean(0), 1e-4, 0.5)


def _scaled(base: stim.Circuit, qubits: frozenset[int], f: float, kind: str) -> stim.Circuit:
    """Every noise instruction that touches the region ("all"), or the two-qubit depolarizing
    of the one CX pair that the region is ("gate"), f times."""
    if kind == "gate":
        return gate_scaled(base, qubits, f)
    return noise.with_scaled_where(
        base, tuple(noise.NOISE_GATES), f, lambda g: bool(qubits & set(g))
    )


class Adaptive:
    """Built once per stale circuit; `decode` runs over shots in time order."""

    def __init__(self, stale: stim.Circuit, seed: int = 0):
        self.stale = stale
        self.base = _rates(stale, seed)
        qubits = sorted(noise.coordinates(stale))
        regions = [(frozenset([q]), "all") for q in qubits]
        regions += [(drift_disk(stale, q), "all") for q in qubits]
        regions += [(frozenset(p), "gate") for p in noise.cx_pairs(stale)]
        self.hypotheses: list[tuple[frozenset[int], float, str]] = []
        self.support: list[np.ndarray] = []  # the detectors each hypothesis speaks for
        on, off = [], []
        for i, (region, kind) in enumerate(regions):
            for f in MENU:
                r = _rates(_scaled(stale, region, f, kind), seed + 1 + i)
                sel = np.abs(np.log(r / self.base)) > MIN_TOUCH
                if not sel.any():
                    continue
                self.hypotheses.append((region, f, kind))
                self.support.append(sel)
                on.append(np.where(sel, np.log(r / self.base), 0.0))
                off.append(np.where(sel, np.log((1 - r) / (1 - self.base)), 0.0))
        self.w_on, self.w_off = np.array(on).T, np.array(off).T  # detectors by hypotheses
        self.margin = np.log(len(self.hypotheses))  # a flat prior over the hypotheses
        self._matchers: dict[tuple, pymatching.Matching] = {}

    def assignments(self, det: np.ndarray) -> list[tuple[int, ...]]:
        """Per shot, the hypotheses to apply: the likeliest region and factor against the stale
        model over a centred window of shots, and a second one if it also beats the prior and
        speaks for detectors the first does not touch. Empty when the stale model wins."""
        n = det.shape[0]
        cs = np.cumsum(np.vstack([np.zeros((1, det.shape[1]), np.float32), det]), axis=0)
        idx = np.arange(n)
        lo, hi = np.clip(idx - WINDOW, 0, n), np.clip(idx + WINDOW + 1, 0, n)
        out: list[tuple[int, ...]] = []
        for a in range(0, n, CHUNK):
            b = min(n, a + CHUNK)
            width = (hi[a:b] - lo[a:b])[:, None]
            rate = (cs[hi[a:b]] - cs[lo[a:b]]) / width
            llr = (rate @ self.w_on + (1 - rate) @ self.w_off) * width  # summed over the window
            order = np.argsort(llr, axis=1)[:, ::-1]
            for row in range(b - a):
                chosen: list[int] = []
                covered = np.zeros(det.shape[1], dtype=bool)
                for h in order[row, : 8 * MAX_HOT]:
                    if llr[row, h] <= self.margin or len(chosen) == MAX_HOT:
                        break
                    if (self.support[h] & covered).any():
                        continue  # it explains detectors the first hypothesis already does
                    chosen.append(int(h))
                    covered |= self.support[h]
                out.append(tuple(sorted(chosen)))
        return out

    def matcher(self, key: tuple[int, ...]) -> pymatching.Matching:
        if key not in self._matchers:
            circuit = self.stale
            for h in key:
                region, f, kind = self.hypotheses[h]
                circuit = _scaled(circuit, region, f, kind)
            self._matchers[key] = pymatching.Matching.from_detector_error_model(
                circuit.detector_error_model(decompose_errors=True), enable_correlations=True
            )
        return self._matchers[key]

    def decode(self, det: np.ndarray) -> np.ndarray:
        keys = self.assignments(det)
        pred = np.zeros((det.shape[0], self.stale.num_observables), dtype=bool)
        groups: dict[tuple, list[int]] = {}
        for i, k in enumerate(keys):
            groups.setdefault(k, []).append(i)
        for k, rows in groups.items():
            idx = np.array(rows)
            pred[idx] = np.asarray(
                self.matcher(k).decode_batch(det[idx], enable_correlations=True), bool
            ).reshape(idx.size, -1)
        return pred
