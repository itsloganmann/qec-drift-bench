from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from qec_drift.agent import noise
from qec_drift.decoders import adaptive, visible, visible_state


def test_permutation_ties_and_obvious_departures() -> None:
    zero = np.zeros((256, 3), bool)
    assert visible.adequacy_p(zero, zero) == 1
    assert visible.adequacy_p(zero, ~zero) == 0.01
    assert visible.stationarity_p(zero) == 1
    switching = np.concatenate((zero, ~zero))
    assert visible.stationarity_p(switching) == 0.01
    assert visible.stationarity_p(switching) == visible.stationarity_p(switching)


def test_temporal_test_detects_order_not_only_marginal_change() -> None:
    x = np.repeat(np.array([False, True]), 256).reshape(-1, 1)
    shuffled = x[np.random.default_rng(13).permutation(len(x))]
    assert visible.stationarity_p(x) == 0.01
    assert visible.stationarity_p(shuffled) > 0.01
    np.testing.assert_array_equal(x.mean(0), shuffled.mean(0))


def test_incomplete_blocks_are_discarded_per_scale() -> None:
    x = np.zeros((128, 2), bool)
    np.testing.assert_equal(visible.temporal_statistic(np.vstack((x, [[1, 1]]))), 0)
    with pytest.raises(ValueError, match="four blocks"):
        visible.stationarity_p(x[:127])


@pytest.mark.parametrize("bad", [np.array([]), np.empty((0, 3)), [[2, 0]], [[np.nan, 0]]])
def test_invalid_events_are_rejected(bad) -> None:
    with pytest.raises(ValueError):
        visible.detectors(bad)


def test_insufficient_data_produces_no_default_report(tmp_path: Path) -> None:
    circuit = noise.nominal(3)
    circuit.to_file(tmp_path / "nominal.stim")
    np.savez(tmp_path / "deploy.npz", det=np.zeros((127, circuit.num_detectors), bool))
    assert visible.fit(tmp_path)["status"] == "unsupported"
    assert not (tmp_path / "report.json").exists()


def test_deploy_labels_are_rejected(tmp_path: Path) -> None:
    circuit = noise.nominal(3)
    circuit.to_file(tmp_path / "nominal.stim")
    np.savez(tmp_path / "deploy.npz", det=np.zeros((128, circuit.num_detectors)), obs=[0])
    with pytest.raises(ValueError, match="detector events only"):
        visible.fit(tmp_path)


def test_adaptive_roundtrip_keeps_bank_and_predictions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(adaptive, "RATE_SHOTS", 100)
    circuit = noise.nominal(3)
    circuit.to_file(tmp_path / "nominal.stim")
    bank = adaptive.Adaptive(circuit, 0)
    det = circuit.compile_detector_sampler(seed=37).sample(256)
    found, keys = visible.localize(bank, det)
    assert found <= set(circuit.get_final_qubit_coordinates())
    expected = bank.decode(det)
    visible_state.save_bank(bank, keys, tmp_path)
    loaded = visible_state.load_bank(tmp_path)
    assert loaded.hypotheses == bank.hypotheses
    np.testing.assert_array_equal(loaded.w_on, bank.w_on)
    np.testing.assert_array_equal(loaded.w_off, bank.w_off)
    assert loaded.assignments(det) == bank.assignments(det)
    np.testing.assert_array_equal(loaded.decode(det), expected)
    metadata = json.loads((tmp_path / "bank.json").read_text())
    assert len(metadata["hypotheses"]) == len(bank.hypotheses)


@pytest.fixture
def evaluator(monkeypatch):
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts/evaluate_visible_baseline.py"
    spec = importlib.util.spec_from_file_location("evaluate_visible_baseline_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_visible_fit_and_hidden_score_use_real_sandbox(evaluator, tmp_path: Path) -> None:
    import sys
    from dataclasses import asdict

    from qec_drift.agent import decoder_task as dt
    from qec_drift.agent import sandbox

    if sys.platform != "darwin":
        pytest.skip("The current local scorer uses macOS sandbox-exec")
    visible_dir, private = tmp_path / "opaque-visible", tmp_path / "private"
    visible_dir.mkdir()
    private.mkdir()
    circuit = noise.nominal(3)
    circuit.to_file(visible_dir / "nominal.stim")
    deploy = circuit.compile_detector_sampler(seed=0).sample(20_000)
    np.savez(visible_dir / "deploy.npz", det=deploy)
    det, obs = circuit.compile_detector_sampler(seed=5).sample(200, separate_observables=True)
    for split in ("train", "val"):
        np.savez(visible_dir / f"{split}.npz", det=det, obs=obs)
    np.savez(private / "test.npz", det=det, obs=obs)
    (private / "task.json").write_text(
        json.dumps(
            {
                "task": asdict(dt.Task(3, "none")),
                "truth": {"scope": "none", "qubits": [], "mechanism": "none", "stationary": True},
                "model_adequate": True,
            }
        )
    )
    (private / "references.json").write_text(json.dumps({"nominal": 0.3, "true_corr": 0.1}))
    work = tmp_path / "work"
    result = evaluator.evaluate(visible_dir, private, work, evaluator.ROOT / "src/qec_drift")
    assert result["status"] == "scored", result
    assert result["adequate_correct"] is True
    assert result["report"]["scope"] == "none"
    assert 0 <= result["logical_error_rate"] <= 1
    code, output = sandbox.run(
        ["-"], work, 10, stdin=f'open({str(private / "test.npz")!r}, "rb").read()'
    )
    assert code != 0 and "PermissionError" in output
    assert not (work / "test.npz").exists()


@pytest.mark.parametrize("nominal_rate,true_rate", [(0, 0), (0.1, 0.2), (None, None)])
def test_undefined_gap_is_checkpointed_as_failed(
    evaluator, tmp_path: Path, monkeypatch, nominal_rate, true_rate
) -> None:
    from dataclasses import asdict

    from qec_drift.agent import decoder_task as dt

    visible_dir, private = tmp_path / "visible", tmp_path / "private"
    visible_dir.mkdir()
    private.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    (work / "fit.json").write_text(json.dumps({"status": "ready"}))
    (work / "report.json").write_text(
        json.dumps({"model_adequate": True, "scope": "none", "stationary": True})
    )
    (private / "task.json").write_text(
        json.dumps(
            {
                "task": asdict(dt.Task(3, "none")),
                "truth": {"scope": "none", "qubits": [], "mechanism": "none", "stationary": True},
                "model_adequate": True,
            }
        )
    )
    np.savez(private / "test.npz", det=np.zeros((2, 24), bool), obs=np.zeros((2, 1), bool))
    (private / "references.json").write_text(
        json.dumps(
            {} if nominal_rate is None else {"nominal": nominal_rate, "true_corr": true_rate}
        )
    )
    monkeypatch.setattr(evaluator, "prepare_work", lambda *args: None)
    monkeypatch.setattr(evaluator.sandbox, "run", lambda *args, **kwargs: (0, ""))
    monkeypatch.setattr(
        evaluator.run, "score_submission", lambda *args: ("", np.zeros((2, 1), bool))
    )
    monkeypatch.setattr(
        dt.Task,
        "truth",
        property(lambda self: (_ for _ in ()).throw(AssertionError("Live truth must not be read"))),
    )
    row = evaluator.evaluate(visible_dir, private, work, tmp_path)
    evaluator.write_json(tmp_path / "checkpoint.json", {"rows": [row]})
    saved = json.loads((tmp_path / "checkpoint.json").read_text())["rows"][0]
    assert saved["gap_closed"] is None
    if nominal_rate is None:
        assert saved["reference_status"] == "undefined"
        assert saved["passed_absolute"] is saved["passed_relative"] is None
        assert saved["diagnosis"]["diagnosis_correct"] is True
        assert saved["logical_error_rate"] == 0
    else:
        assert saved["passed_absolute"] is saved["passed_relative"] is False


def test_resume_retains_failures_skips_completed_and_rejects_changed_runtime(
    evaluator, tmp_path: Path, monkeypatch
) -> None:
    export, output = tmp_path / "export", tmp_path / "output"
    (export / "scorer").mkdir(parents=True)
    (export / "scorer/manifest.json").write_text("{}")
    for identity in ("a", "b"):
        (export / "scorer" / identity).mkdir()
        (export / "scorer" / identity / "references.json").write_text("{}")
    output.mkdir()
    calls = []

    def evaluate(visible_dir, *args):
        calls.append(visible_dir.name)
        if visible_dir.name == "a":
            return {
                "id": "a",
                "status": "fit_timeout",
                "passed_absolute": False,
                "passed_relative": False,
            }
        raise RuntimeError("Synthetic failure")

    monkeypatch.setattr(evaluator, "evaluate", evaluate)
    manifest = {"tasks": [{"id": "a"}, {"id": "b"}]}
    evaluator.run_study(export, output, manifest)
    evaluator.run_study(export, output, manifest)
    state = json.loads((output / "results.json").read_text())
    assert calls == ["a", "b"]
    assert len(state["rows"]) == state["all_candidates_denominator"] == 2
    assert [row["status"] for row in state["rows"]] == ["fit_timeout", "exception"]
    assert all(row["passed_absolute"] is row["passed_relative"] is None for row in state["rows"])
    assert state["complete"] is True
    monkeypatch.setattr(evaluator.platform, "python_version", lambda: "changed")
    with pytest.raises(ValueError, match="runtime"):
        evaluator.run_study(export, output, manifest)
