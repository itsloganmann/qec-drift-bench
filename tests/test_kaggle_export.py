from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from qec_drift.agent import decoder_task as dt


@pytest.fixture
def exporter(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "kaggle_export_test", scripts / "export_kaggle_tasks.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(dt, "SHOTS", {"train": 19, "val": 7, "deploy": 11, "test": 23})
    return module


def references(path: Path, task: dt.Task) -> Path:
    rates = dict(
        nominal=0.1, nominal_corr=0.08, true=0.1, true_corr=0.04, pij_plain=0.07, pij_corr=0.05
    )
    if task.drift:
        rates["stale_corr"] = 0.1
    if not task.stationary:
        rates.update(adaptive_corr=0.06, window_corr=0.05)
    path.write_text(json.dumps({task.name: rates}))
    return path


@pytest.mark.parametrize("task", [dt.Task(5, "none"), dt.Task(5, "none", "wander30", 2)])
def test_visible_bundle_contains_only_promised_files_and_preserves_shot_order(
    exporter: ModuleType, tmp_path: Path, task: dt.Task
) -> None:
    refs = references(tmp_path / "refs.json", task)
    visible, scorer = tmp_path / "visible", tmp_path / "scorer"
    manifest = exporter.export([task], refs, visible, scorer)
    assert manifest == json.loads((scorer / "manifest.json").read_text())
    assert manifest["reference_rates_recomputed"] is False
    record = manifest["tasks"][0]
    opaque = record["id"]
    assert len(opaque) == 32 and task.name not in opaque
    assert {p.name for p in visible.iterdir()} == {opaque}
    episode = visible / opaque
    assert {p.name for p in episode.iterdir()} == {
        "nominal.stim",
        "train.npz",
        "val.npz",
        "deploy.npz",
    }
    expected = tmp_path / "expected"
    dt.write_agent_files(task, expected)
    for name, keys in [("train", {"det", "obs"}), ("val", {"det", "obs"}), ("deploy", {"det"})]:
        with np.load(episode / f"{name}.npz", allow_pickle=False) as actual:
            with np.load(expected / f"{name}.npz", allow_pickle=False) as want:
                assert set(actual.files) == keys
                for key in keys:
                    np.testing.assert_array_equal(actual[key], want[key])
    with np.load(scorer / opaque / "test.npz", allow_pickle=False) as hidden:
        assert set(hidden.files) == {"det", "obs", "regime"}
        for key, want in zip(("det", "obs", "regime"), dt.test_sample(task), strict=True):
            np.testing.assert_array_equal(hidden[key], want)
    private = json.loads((scorer / opaque / "task.json").read_text())
    assert private["name"] == task.name
    assert private["truth"]["stationary"] is task.stationary
    assert (
        json.loads((scorer / opaque / "references.json").read_text())
        == json.loads(refs.read_text())[task.name]
    )
    for side, root in [("visible", visible), ("scorer", scorer)]:
        for name, meta in record["files"][side].items():
            file = root / opaque / name
            assert meta == exporter.fingerprint(file)


@pytest.mark.parametrize(
    "fault", ["missing", "nan", "bool", "zero_stale", "no_gap", "no_known", "missing_adaptive"]
)
def test_bad_or_ungated_references_fail_before_creating_outputs(
    exporter: ModuleType, tmp_path: Path, fault: str
) -> None:
    task = dt.Task(5, "none", "wander30")
    refs = references(tmp_path / "refs.json", task)
    table = json.loads(refs.read_text())
    row = table[task.name]
    if fault == "missing":
        del row["true_corr"]
    elif fault == "missing_adaptive":
        del row["adaptive_corr"]
    else:
        key, value = {
            "nan": ("true_corr", float("nan")),
            "bool": ("true_corr", False),
            "zero_stale": ("stale_corr", 0),
            "no_gap": ("true_corr", 0.09),
            "no_known": ("adaptive_corr", 0.09),
        }[fault]
        row[key] = value
    refs.write_text(json.dumps(table))
    with pytest.raises(ValueError):
        exporter.export([task], refs, tmp_path / "visible", tmp_path / "scorer")
    assert not (tmp_path / "visible").exists() and not (tmp_path / "scorer").exists()


@pytest.mark.parametrize("case", ["same", "nested", "alias", "existing", "dangling"])
def test_output_roots_cannot_overlap_or_overwrite(
    exporter: ModuleType, tmp_path: Path, case: str
) -> None:
    task = dt.Task(5, "none")
    refs = references(tmp_path / "refs.json", task)
    visible, scorer = tmp_path / "visible", tmp_path / "scorer"
    if case == "same":
        scorer = visible
    elif case == "nested":
        scorer = visible / "scorer"
    elif case == "alias":
        scorer.symlink_to(visible, target_is_directory=True)
    elif case == "existing":
        visible.mkdir()
        (visible / "keep").write_text("previous export")
    else:
        visible.symlink_to(tmp_path / "missing", target_is_directory=True)
    with pytest.raises((ValueError, FileExistsError)):
        exporter.export([task], refs, visible, scorer)
    if case == "existing":
        assert (visible / "keep").read_text() == "previous export"


@pytest.mark.parametrize("reverse", [False, True])
def test_case_alias_cannot_nest_output_roots(
    exporter: ModuleType, tmp_path: Path, reverse: bool
) -> None:
    probe = tmp_path / "case_probe"
    probe.mkdir()
    if not (tmp_path / "CASE_PROBE").exists():
        pytest.skip("requires a case-insensitive filesystem")
    task = dt.Task(5, "none")
    refs = references(tmp_path / "refs.json", task)
    visible, scorer = tmp_path / "visible", tmp_path / "VISIBLE" / "scorer"
    if reverse:
        visible, scorer = scorer, visible
    with pytest.raises((ValueError, FileExistsError)):
        exporter.export([task], refs, visible, scorer)
    assert not visible.exists() and not scorer.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "extra",
        "deploy_labels",
        "symlink",
        "wrong_shape",
        "wrong_dtype",
        "test_failure",
        "circuit_comment",
    ],
)
def test_invalid_generated_artifact_removes_incomplete_export(
    exporter: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    task = dt.Task(5, "none")
    refs = references(tmp_path / "refs.json", task)
    original = dt.write_agent_files

    def corrupt(task: dt.Task, folder: Path) -> None:
        original(task, folder)
        if fault == "extra":
            (folder / "truth.json").write_text('{"canary":"hidden"}')
        elif fault == "symlink":
            (folder / "nominal.stim").unlink()
            (folder / "nominal.stim").symlink_to(refs)
        elif fault == "deploy_labels":
            np.savez_compressed(
                folder / "deploy.npz", det=dt.deploy_shots(task), obs=np.ones((11, 1), bool)
            )
        elif fault == "wrong_shape":
            np.savez_compressed(folder / "deploy.npz", det=np.zeros((11, 1), bool))
        elif fault == "wrong_dtype":
            np.savez_compressed(folder / "deploy.npz", det=dt.deploy_shots(task).astype(int))
        elif fault == "circuit_comment":
            with (folder / "nominal.stim").open("a") as stream:
                stream.write("\n# task identity canary\n")

    monkeypatch.setattr(dt, "write_agent_files", corrupt)
    if fault == "test_failure":
        monkeypatch.setattr(
            dt, "test_sample", lambda task: (_ for _ in ()).throw(RuntimeError("failed"))
        )
    with pytest.raises((ValueError, RuntimeError)):
        exporter.export([task], refs, tmp_path / "visible", tmp_path / "scorer")
    assert not (tmp_path / "visible").exists() and not (tmp_path / "scorer").exists()


def test_empty_or_duplicate_task_selection_fails(exporter: ModuleType, tmp_path: Path) -> None:
    task = dt.Task(5, "none")
    refs = references(tmp_path / "refs.json", task)
    for tasks in ([], [task, task]):
        with pytest.raises(ValueError):
            exporter.export(tasks, refs, tmp_path / "visible", tmp_path / "scorer")
