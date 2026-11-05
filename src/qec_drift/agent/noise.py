"""Noise transforms on Stim circuits: the nominal surface-code memory and ways to perturb it.

Every transform returns a new circuit with the same detectors and observable, so a decoder built
from one circuit can decode shots from another.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import stim

P_NOMINAL = 0.003
Q_CROSSTALK = 0.005
NOISE_GATES = {"DEPOLARIZE1": 1, "DEPOLARIZE2": 2, "X_ERROR": 1, "Z_ERROR": 1}
READOUT = ("X_ERROR",)  # the flips before a measurement and after a reset
GATES = ("DEPOLARIZE2",)


def nominal(d: int, p: float = P_NOMINAL) -> stim.Circuit:
    return stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        distance=d,
        rounds=d,
        after_clifford_depolarization=p,
        before_round_data_depolarization=p,
        before_measure_flip_probability=p,
        after_reset_flip_probability=p,
    )


def coordinates(c: stim.Circuit) -> dict[int, tuple[float, ...]]:
    return {k: tuple(v) for k, v in c.get_final_qubit_coordinates().items()}


def data_qubits(c: stim.Circuit) -> list[int]:
    """Data qubits of a generated rotated code have odd coordinates; measure qubits even."""
    return sorted(q for q, xy in coordinates(c).items() if all(v % 2 == 1 for v in xy))


def measure_qubits(c: stim.Circuit) -> list[int]:
    return sorted(set(coordinates(c)) - set(data_qubits(c)))


def cx_pairs(c: stim.Circuit) -> list[tuple[int, int]]:
    """The distinct (control, target) pairs of the circuit's CX gates, in first-use order."""
    seen: dict[tuple[int, int], None] = {}
    for inst in c.flattened():
        if inst.name == "CX":
            t = [x.value for x in inst.targets_copy()]
            for i in range(0, len(t), 2):
                seen.setdefault((t[i], t[i + 1]), None)
    return list(seen)


def with_crosstalk(base: stim.Circuit, q: float = Q_CROSSTALK) -> stim.Circuit:
    """Add DEPOLARIZE2(q) on neighbouring data qubits after each round's data noise."""
    coords = coordinates(base)
    out = stim.Circuit()
    for inst in base.flattened():
        out.append(inst)
        if inst.name != "DEPOLARIZE1":
            continue
        targets = [t.value for t in inst.targets_copy()]
        if len(targets) < 2 or any(c % 2 != 1 for q_ in targets for c in coords[q_]):
            continue  # only the data-qubit layer
        at = {coords[t]: t for t in targets}
        for t in targets:
            x, y = coords[t]
            for dx, dy in ((2, 0), (0, 2)):
                if (x + dx, y + dy) in at:
                    out.append("DEPOLARIZE2", [t, at[(x + dx, y + dy)]], q)
    return out


def with_scaled_qubits(base: stim.Circuit, sigma: float, seed: int) -> stim.Circuit:
    """Scale every noise instruction by a per-qubit lognormal factor with mean 1."""
    f = np.random.default_rng(seed).lognormal(0, sigma, base.num_qubits)
    f /= f.mean()
    out = stim.Circuit()
    for inst in base.flattened():
        if inst.name not in NOISE_GATES:
            out.append(inst)
            continue
        arity, p = NOISE_GATES[inst.name], inst.gate_args_copy()[0]
        t = [x.value for x in inst.targets_copy()]
        for i in range(0, len(t), arity):
            group = t[i : i + arity]
            out.append(inst.name, group, min(0.5, p * float(np.prod(f[group]) ** (1 / arity))))
    return out


def with_scaled_gates(base: stim.Circuit, factors: dict[str, float]) -> stim.Circuit:
    """Scale the probability of the named noise instructions by their factor."""
    out = stim.Circuit()
    for inst in base.flattened():
        if inst.name not in factors:
            out.append(inst)
            continue
        p = inst.gate_args_copy()[0]
        out.append(
            inst.name, [x.value for x in inst.targets_copy()], min(0.5, p * factors[inst.name])
        )
    return out


def with_scaled_where(
    base: stim.Circuit,
    names: tuple[str, ...],
    factor: float,
    hit: Callable[[list[int]], bool],
) -> stim.Circuit:
    """Scale the named noise instructions by `factor` on the target groups that `hit` selects.

    A noise instruction on many targets is split into the groups that change and the groups
    that do not; both keep their place in the circuit.
    """
    out = stim.Circuit()
    for inst in base.flattened():
        if inst.name not in names:
            out.append(inst)
            continue
        arity, p = NOISE_GATES[inst.name], inst.gate_args_copy()[0]
        t = [x.value for x in inst.targets_copy()]
        groups = [t[i : i + arity] for i in range(0, len(t), arity)]
        same = [q for g in groups if not hit(g) for q in g]
        changed = [q for g in groups if hit(g) for q in g]
        if same:
            out.append(inst.name, same, p)
        if changed:
            out.append(inst.name, changed, min(0.5, p * factor))
    return out
