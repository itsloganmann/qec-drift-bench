from __future__ import annotations

from collections import defaultdict

import numpy as np

DRAWS = 10_000
SEED = 20261108


def coverage(candidates: list[dict]) -> dict:
    families: dict[str, int] = defaultdict(int)
    templates: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        families[candidate["family"]] += 1
        templates[candidate["template_id"]] += 1
    return {
        "candidates": len(candidates),
        "families": len(families),
        "templates": len(templates),
        "by_family": dict(families),
        "by_template": dict(templates),
    }


def bootstrap_weights(candidates: list[dict], draws: int = DRAWS) -> np.ndarray:
    clusters: dict[str, dict[str, list[int]]] = {}
    for index, candidate in enumerate(candidates):
        clusters.setdefault(candidate["family"], {}).setdefault(
            candidate["template_id"], []
        ).append(index)
    families = [list(templates.values()) for templates in clusters.values()]
    weights = np.zeros((draws, len(candidates)), dtype=np.int32)
    rng = np.random.default_rng(SEED)
    for draw in range(draws):
        for family_index in rng.choice(len(families), size=len(families)):
            templates = families[family_index]
            for template_index in rng.choice(len(templates), size=len(templates)):
                members = templates[template_index]
                selected = rng.choice(members, size=len(members))
                np.add.at(weights[draw], selected, 1)
    return weights


def estimate(candidates: list[dict], values: np.ndarray, weights: np.ndarray) -> dict | None:
    if not candidates:
        return None
    if values.shape != (len(candidates),) or weights.shape[1] != len(candidates):
        raise ValueError("Statistic dimensions do not match the candidate set")
    if not np.isfinite(values).all() or np.any(weights.sum(axis=1) <= 0):
        raise ValueError("Invalid statistic or empty bootstrap draw")
    samples = (weights @ values) / weights.sum(axis=1)
    return coverage(candidates) | {
        "mean": float(np.mean(values)),
        "interval": np.quantile(samples, [0.025, 0.975], method="linear").tolist(),
    }


def bounds(denominator: int, values: list[bool | None]) -> dict:
    if denominator < len(values) or any(v is not None and type(v) is not bool for v in values):
        raise ValueError("Invalid binary outcomes or denominator")
    passes = sum(v is True for v in values)
    failures = sum(v is False for v in values)
    unresolved = denominator - passes - failures
    return {
        "denominator": denominator,
        "observed": passes + failures,
        "passes": passes,
        "failures": failures,
        "unresolved": unresolved,
        "lower": passes / denominator if denominator else None,
        "upper": (passes + unresolved) / denominator if denominator else None,
    }
