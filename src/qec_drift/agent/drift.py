"""Structural drift: what changes between the calibration shots and the deploy shots.

A drift kind is the `drift` field of a task. Global kinds change most of the device; local kinds
change one qubit or one gate, which a rate test over the whole batch barely sees, so the agent
has to find where the change is. Each kind also defines the truth that the agent's diagnosis is
scored against: a scope (none, local, global, moving), the changed qubits, a mechanism, and
whether the noise is stationary.

Stationary kinds:
- "meas{f}": readout and reset flips f times more likely on every qubit (global, readout)
- "requbit": a fresh per-qubit lognormal scale of every probability (global, all)
- "xt{q}": two-qubit depolarizing at q / 1000 between neighbouring data qubits (global, crosstalk)
- "bq{f}": every noise instruction on one qubit, f times (local, all)
- "br{f}": readout and reset flips on one measure qubit, f times (local, readout)
- "bg{f}": the two-qubit depolarizing after one CX pair, f times (local, gate)
- "line{f}": readout and reset flips on one column of measure qubits, f times (local, readout)
- "cp{a}": a / 10 of each data qubit's idle depolarizing moves into two-qubit depolarizing on
  neighbouring data pairs, marginals about unchanged (global, crosstalk)

Non-stationary kinds, where no single circuit describes the hardware and the task is a
`Process` of regimes that alternate with the base in stretches of about `dwell` shots (DWELL
by default; "wander30d60" sets 60):
- "tls{f}": one qubit switches between its base noise and f times more (local, all)
- "wander{f}": each bad stretch picks a new qubit out of WANDER candidates drawn per batch,
  so the deploy and the test batch have different bad qubits (moving, all)
- "patch{f}": each bad stretch picks a new disk of PATCH_RADIUS around one of WANDER centres,
  every qubit in it f times noisier (moving, all)
- "gwander{f}": each bad stretch picks a new CX pair out of WANDER candidates and makes its
  two-qubit depolarizing f times more likely: a coupler that fails at changing places
  (moving, gate)
- "ramp{f}": one qubit's noise climbs from its base to f times in RAMP_STEPS equal steps
  over the batch, in time order, like a defect that drifts into resonance (local, all; not
  stationary)

Kinds joined with "+" apply in order; at most one part may be non-stationary, and the
stationary parts change the base that its regimes alternate with ("bq15+wander30": a bad
qubit all the time, and a wandering one on top). The truth is the union of the parts; for a
moving kind the qubits are those that were bad in the deploy batch, which `truth` takes as
`present`, the regime indices that the batch used.

A local kind picks its target with a draw seeded by the family, the distance and the replicate
seed, not by f, so the rungs of a magnitude ladder differ only in how hard they hit. A per-shot
hot spot was built and dropped on 2026-11-01: no method can approach its per-shot oracle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import stim

from qec_drift.agent import noise

SIGMA = 1.0
DWELL = 200  # mean stretch length, in shots, of a telegraph state
WANDER = 12  # candidate bad qubits or centres of a wandering fault, per batch
PATCH_RADIUS = 2.5  # coordinate units; a disk holds a qubit and its nearest neighbours
RAMP_STEPS = 8  # levels above the base of a ramp, geometric from the base to f
NONSTATIONARY = ("tls", "wander", "patch", "gwander", "ramp")
MECHANISMS = ("none", "readout", "gate", "all", "crosstalk")
SCOPES = ("none", "local", "global", "moving")
FAMILIES = {  # family: (mechanism, scope)
    "meas": ("readout", "global"),
    "requbit": ("all", "global"),
    "xt": ("crosstalk", "global"),
    "bq": ("all", "local"),
    "br": ("readout", "local"),
    "bg": ("gate", "local"),
    "line": ("readout", "local"),
    "cp": ("crosstalk", "global"),
    "tls": ("all", "local"),
    "wander": ("all", "moving"),
    "patch": ("all", "moving"),
    "gwander": ("gate", "moving"),
    "ramp": ("all", "local"),
}
# The draw index of each family. Append only: a new family must not move the targets of the
# old ones, which the recorded runs depend on.
_ORDER = ("bg", "bq", "br", "cp", "line", "meas", "patch", "requbit", "tls", "wander", "xt",
          "gwander", "ramp")  # fmt: skip
_KIND = re.compile(
    r"^(meas|xt|bq|br|bg|line|cp|tls|wander|patch|gwander|ramp)(\d+(?:\.\d+)?)(?:d(\d+))?$"
)
PAIR_SHARE = 0.8 * 4  # marginal flip share of DEPOLARIZE2 (12 of 15) times pairs per inner qubit


@dataclass(frozen=True)
class Truth:
    scope: str
    qubits: frozenset[int]
    mechanism: str
    stationary: bool = True


@dataclass(frozen=True)
class Process:
    """The test-time hardware: regimes, their shares of the shots, and how shots are ordered.

    Regime 0 is the base. `dwell` None means one stationary regime; a number means the base
    alternates with one of the other regimes, drawn at random, in stretches of about that many
    consecutive shots. `order` "ramp" means the regimes follow each other once, in index
    order, in equal blocks of shots. `qubits[i]` is what regime i changes relative to the base.
    """

    circuits: tuple[stim.Circuit, ...]
    shares: tuple[float, ...]
    dwell: int | None = None
    qubits: tuple[frozenset[int], ...] = ()
    order: str = "telegraph"

    @property
    def stationary(self) -> bool:
        return len(self.circuits) == 1


NO_DRIFT = Truth("none", frozenset(), "none")


def parse(kind: str) -> tuple[str, float]:
    """The family and magnitude of one drift kind. Raises ValueError for an unknown kind."""
    if kind == "requbit":
        return kind, 0.0
    m = _KIND.match(kind)
    if not m:
        raise ValueError(f"unknown drift kind {kind!r}; families: {sorted(FAMILIES)}")
    if m.group(3) and m.group(1) not in NONSTATIONARY:
        raise ValueError(f"{kind!r}: only a non-stationary kind takes a dwell")
    return m.group(1), float(m.group(2))


def dwell_of(kind: str) -> int:
    """The mean stretch length of one non-stationary kind."""
    m = _KIND.match(kind)
    return int(m.group(3)) if m and m.group(3) else DWELL


def parts(kind: str) -> list[str]:
    """The kinds of a "+"-joined drift, each checked. "" is no drift."""
    out = [k for k in kind.split("+") if k] if kind else []
    for k in out:
        parse(k)
    if sum(parse(k)[0] in NONSTATIONARY for k in out) > 1:
        raise ValueError(f"{kind!r}: at most one part may be non-stationary")
    return out


def split_parts(kind: str) -> tuple[list[str], str | None]:
    """(stationary parts, the non-stationary part or None)."""
    moving = [k for k in parts(kind) if parse(k)[0] in NONSTATIONARY]
    return [k for k in parts(kind) if parse(k)[0] not in NONSTATIONARY], (
        moving[0] if moving else None
    )


def stationary(kind: str) -> bool:
    return split_parts(kind)[1] is None


def _rng(family: str, d: int, seed: int) -> np.random.Generator:
    return np.random.default_rng([_ORDER.index(family), d, seed])


def local_target(family: str, pre: stim.Circuit, d: int, seed: int) -> frozenset[int]:
    """The qubit (bq, br, tls), column (line) or CX pair (bg) that a local kind changes."""
    rng = _rng(family, d, seed)
    if family in ("bq", "tls", "ramp"):
        return frozenset([int(rng.choice(sorted(noise.coordinates(pre))))])
    if family == "br":
        return frozenset([int(rng.choice(noise.measure_qubits(pre)))])
    if family == "line":
        coords = noise.coordinates(pre)
        xs = [coords[q][0] for q in noise.measure_qubits(pre)]
        columns = sorted(x for x in set(xs) if xs.count(x) >= 3)  # not a two-qubit edge column
        x = columns[int(rng.integers(len(columns)))]
        return frozenset(q for q in noise.measure_qubits(pre) if coords[q][0] == x)
    pairs = noise.cx_pairs(pre)
    return frozenset(pairs[int(rng.integers(len(pairs)))])


def disk(pre: stim.Circuit, centre: int, radius: float = PATCH_RADIUS) -> frozenset[int]:
    coords = noise.coordinates(pre)
    cx, cy = coords[centre][:2]
    r2 = radius**2
    return frozenset(q for q, c in coords.items() if (c[0] - cx) ** 2 + (c[1] - cy) ** 2 <= r2)


def with_correlated_pairs(base: stim.Circuit, share: float) -> stim.Circuit:
    """Move `share` of each data qubit's idle depolarizing into neighbouring-pair depolarizing."""
    thinned = noise.with_scaled_where(
        base, ("DEPOLARIZE1",), 1 - share, lambda g: g[0] in set(noise.data_qubits(base))
    )
    p = next(
        i.gate_args_copy()[0]
        for i in base.flattened()
        if i.name == "DEPOLARIZE1" and i.targets_copy()[0].value in noise.data_qubits(base)
    )
    return noise.with_crosstalk(thinned, share * p / PAIR_SHARE)


def apply(pre: stim.Circuit, kind: str, d: int, seed: int = 0) -> stim.Circuit:
    """The test-time circuit of a stationary kind: the pre-drift circuit with its changes."""
    if not stationary(kind):
        raise ValueError(f"{kind!r} is not one circuit; use process()")
    out = pre
    for k in parts(kind):
        out = _apply_one(out, k, d, seed)
    return out


def _scaled(base: stim.Circuit, qubits: frozenset[int], f: float) -> stim.Circuit:
    return noise.with_scaled_where(
        base, tuple(noise.NOISE_GATES), f, lambda g: bool(qubits & set(g))
    )


def gate_scaled(base: stim.Circuit, pair: frozenset[int], f: float) -> stim.Circuit:
    """The two-qubit depolarizing after one CX pair, f times."""
    return noise.with_scaled_where(base, noise.GATES, f, lambda g: set(g) == pair)


def hot_regimes(
    base: stim.Circuit, kind: str, d: int, seed: int, split: str
) -> list[tuple[stim.Circuit, frozenset[int]]]:
    """The bad regimes of one non-stationary kind on a base circuit: (circuit, changed qubits)."""
    family, f = parse(kind)
    if family in ("tls", "ramp"):
        bad = local_target(family, base, d, seed)
        if family == "tls":
            return [(_scaled(base, bad, f), bad)]
        steps = range(1, RAMP_STEPS + 1)
        return [(_scaled(base, bad, f ** (k / RAMP_STEPS)), bad) for k in steps]
    rng = np.random.default_rng([_ORDER.index(family), d, seed, split == "deploy"])
    if family == "gwander":
        pairs = noise.cx_pairs(base)
        picks = [frozenset(pairs[int(i)]) for i in rng.choice(len(pairs), WANDER, replace=False)]
        return [(gate_scaled(base, pair, f), pair) for pair in picks]
    pool = sorted(noise.coordinates(base))
    picks = [int(q) for q in rng.choice(pool, size=WANDER, replace=False)]
    targets = [frozenset([q]) if family == "wander" else disk(base, q) for q in picks]
    return [(_scaled(base, t, f), t) for t in targets]


def process(pre: stim.Circuit, kind: str, d: int, seed: int = 0, split: str = "test") -> Process:
    """The test-time hardware for any kind. `split` picks the candidate draw of a moving kind."""
    static, moving = split_parts(kind)
    base = pre
    for k in static:
        base = _apply_one(base, k, d, seed)
    static_qubits = frozenset().union(*(_truth_one(pre, k, d, seed).qubits for k in static))
    if moving is None:
        return Process((base,), (1.0,), None, (static_qubits,))
    hot = hot_regimes(base, moving, d, seed, split)
    n = len(hot)
    ramp = parse(moving)[0] == "ramp"
    return Process(
        (base, *(c for c, _ in hot)),
        tuple([1 / (n + 1)] * (n + 1)) if ramp else (0.5, *([0.5 / n] * n)),
        None if ramp else dwell_of(moving),
        (static_qubits, *(q for _, q in hot)),
        "ramp" if ramp else "telegraph",
    )


def _apply_one(pre: stim.Circuit, kind: str, d: int, seed: int) -> stim.Circuit:
    family, f = parse(kind)
    if family == "meas":
        return noise.with_scaled_gates(pre, {"X_ERROR": f})
    if family == "requbit":
        return noise.with_scaled_qubits(pre, SIGMA, seed=900 + d + 100 * seed)
    if family == "xt":
        return noise.with_crosstalk(pre, f / 1000)
    if family == "cp":
        return with_correlated_pairs(pre, f / 10)
    target = local_target(family, pre, d, seed)
    if family == "bq":
        return _scaled(pre, target, f)
    if family in ("br", "line"):
        return noise.with_scaled_where(pre, noise.READOUT, f, lambda g: bool(target & set(g)))
    return noise.with_scaled_where(pre, noise.GATES, f, lambda g: set(g) == target)


def truth(
    pre: stim.Circuit,
    kind: str,
    d: int,
    seed: int = 0,
    present: set[int] | None = None,
    split: str = "deploy",
) -> Truth:
    """What a correct diagnosis says about this drift: the union of its parts.

    For a non-stationary part the qubits are those of the regimes in `present` (indices into
    the process of `split`; None means all of them).
    """
    static, moving = split_parts(kind)
    found = [_truth_one(pre, k, d, seed) for k in static]
    if moving is not None:
        proc = process(pre, kind, d, seed, split)
        used = range(1, len(proc.circuits)) if present is None else sorted(set(present) - {0})
        qubits = frozenset().union(*(proc.qubits[i] for i in used))
        mechanism, scope = FAMILIES[parse(moving)[0]]
        found.append(Truth(scope, qubits, mechanism, stationary=False))
    if not found:
        return NO_DRIFT
    if len(found) == 1:
        return found[0]
    scopes = {t.scope for t in found}
    scope = "moving" if "moving" in scopes else ("local" if scopes == {"local"} else "global")
    mechanisms = {t.mechanism for t in found}
    mechanism = mechanisms.pop() if len(mechanisms) == 1 else "all"
    return Truth(
        scope,
        frozenset().union(*(t.qubits for t in found)),
        mechanism,
        stationary=all(t.stationary for t in found),
    )


def _truth_one(pre: stim.Circuit, kind: str, d: int, seed: int) -> Truth:
    """The truth of one stationary part, or of a fixed telegraph qubit."""
    family, _ = parse(kind)
    mechanism, scope = FAMILIES[family]
    if family in ("tls", "ramp"):
        return Truth(scope, local_target(family, pre, d, seed), mechanism, stationary=False)
    if scope == "local":
        return Truth(scope, local_target(family, pre, d, seed), mechanism)
    if family in ("xt", "cp"):
        return Truth(scope, frozenset(noise.data_qubits(pre)), mechanism)
    return Truth(scope, frozenset(noise.coordinates(pre)), mechanism)
