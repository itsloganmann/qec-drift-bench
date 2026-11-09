from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import study_statistics as stats  # noqa: E402


def candidates():
    return [
        {"id": "a", "family": "f1", "template_id": "t1"},
        {"id": "b", "family": "f1", "template_id": "t1"},
        {"id": "c", "family": "f1", "template_id": "t1"},
        {"id": "d", "family": "f2", "template_id": "t2"},
    ]


def test_hierarchy_preserves_sampled_cluster_sizes(monkeypatch):
    choices = iter([[0, 0], [0], [0, 1, 1], [0], [2, 2, 2]])

    class Draw:
        def choice(self, values, size):
            selected = np.asarray(next(choices))
            assert len(selected) == size
            assert set(selected) <= set(range(values) if isinstance(values, int) else values)
            return selected

    monkeypatch.setattr(stats.np.random, "default_rng", lambda seed: Draw())
    weights = stats.bootstrap_weights(candidates(), draws=1)
    np.testing.assert_array_equal(weights, [[1, 2, 3, 0]])
    assert weights.sum() == 6


def test_paired_identical_arms_have_zero_difference_interval():
    points = candidates()
    values = np.array([[1, 1], [0, 0], [1, 1], [0, 0]])
    weights = stats.bootstrap_weights(points, draws=100)
    result = stats.estimate(points, values[:, 0] - values[:, 1], weights)
    assert result["mean"] == 0
    assert result["interval"] == [0, 0]
    assert result["candidates"] == 4
    assert result["families"] == 2
    assert result["templates"] == 2


def test_pooled_mean_and_linear_percentiles_use_variable_draw_sizes():
    points = candidates()
    weights = np.array([[1, 2, 3, 0], [0, 0, 0, 2]])
    result = stats.estimate(points, np.array([1, 0, 0, 1]), weights)
    assert result["mean"] == 0.5
    assert result["interval"] == pytest.approx([0.1875, 0.9791666666666666])


def test_empty_sample_has_no_interval_and_weights_are_reproducible():
    assert stats.estimate([], np.array([]), np.empty((100, 0))) is None
    np.testing.assert_array_equal(
        stats.bootstrap_weights(candidates(), draws=30),
        stats.bootstrap_weights(candidates(), draws=30),
    )


def test_missing_results_widen_bounds_without_becoming_failures():
    result = stats.bounds(4, [True, False, None])
    assert result == {
        "denominator": 4,
        "observed": 2,
        "passes": 1,
        "failures": 1,
        "unresolved": 2,
        "lower": 0.25,
        "upper": 0.75,
    }
    assert stats.bounds(0, [])["lower"] is None
    with pytest.raises(ValueError):
        stats.bounds(1, [True, False])
    with pytest.raises(ValueError):
        stats.bounds(1, ["false"])
