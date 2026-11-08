from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from qec_drift.agent import attempts, transcripts
from qec_drift.scoring import failure_modes_decoder as fm
from qec_drift.scoring import taxonomy

SPEC = importlib.util.spec_from_file_location(
    "attempt_judge", Path(__file__).resolve().parents[1] / "scripts" / "judge_transcripts.py"
)
judge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(judge)


def interrupted_fixture(root: Path, legacy: bool) -> tuple[Path, Path]:
    data = root / "data" / "fixture_set"
    data.mkdir(parents=True)
    folder = root / "trajectories" / data.name
    folder.mkdir(parents=True)
    table, archive = data / "arm.parquet", folder / "decoder_arm.jsonl.gz"
    row = dict(
        arm="arm",
        task="t",
        d=3,
        outcome="submitted",
        stop="completed",
        turns=3,
        gap_closed=0.9,
        gap_drift=float("nan"),
        diagnosis_correct=True,
        decoder_bytes=42,
        decoder_src="m = Matching(dem, enable_correlations=True)",
        score_error="",
    )
    rec = dict(
        task="t",
        model="synthetic-model",
        trace_kind="codex_stream",
        report={"try": "committed-old"},
        decoder_src=row["decoder_src"],
        events=[{"type": "turn.completed"}],
    )
    with archive.open("ab") as trace:
        if legacy:
            trace.write(gzip.compress((json.dumps(rec) + "\n").encode()))
        else:
            row = attempts.append_attempt(trace, row, rec, "arm")
        attempts.write_table(table, [row])
        orphan = rec | {
            "report": {"try": "uncommitted-new"},
            "events": [
                {
                    "type": "item.completed",
                    "item": {"type": "command_execution", "command": "load('val.npz')"},
                },
                {"type": "turn.failed", "error": {"message": "usage limit"}},
            ],
        }
        attempts.append_attempt(trace, row, orphan, "arm")
    pd.DataFrame(
        [dict(arm="arm", task="t", attempt_id=row.get("attempt_id"), label="passed", gate="G1")]
    ).to_parquet(data / "arm_taxonomy.parquet")
    return table, archive


@pytest.mark.parametrize("legacy", [False, True])
def test_every_consumer_uses_committed_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy: bool
) -> None:
    table, archive = interrupted_fixture(tmp_path, legacy)
    monkeypatch.setattr(judge, "DATA", table.parent)
    monkeypatch.setattr(judge.paths, "trajectories_dir", lambda: tmp_path / "trajectories")
    monkeypatch.setattr(judge, "facts", lambda row: f"committed gap {row['gap_closed']}")
    work = judge.episodes()
    assert len(work) == 1
    assert "committed-old" in work[0][3] and "uncommitted-new" not in work[0][3]
    modes = fm.analyze_decoder(table, archive)
    assert not modes.iloc[0].used_validation
    labels = taxonomy.analyze_arm(table, archive)
    assert labels.iloc[0].label == "passed" and labels.iloc[0].transcript
    page = transcripts.render_archive(archive, table) / "t.md"
    text = page.read_text()
    assert "committed-old" in text and "uncommitted-new" not in text
    assert "`passed`" in text


def test_missing_match_is_reported_and_replaces_stale_rendered_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, archive = interrupted_fixture(tmp_path, False)
    page = transcripts.render_archive(archive, table) / "t.md"
    rows = pd.read_parquet(table)
    rows["attempt_id"] = "missing"
    attempts.write_table(table, rows.to_dict("records"))
    pd.DataFrame([dict(task="t", attempt_id="missing", label="passed", gate="G1")]).to_parquet(
        table.with_name("arm_taxonomy.parquet")
    )
    transcripts.render_archive(archive, table)
    assert "No archived transcript matches the scored attempt" in page.read_text()
    assert "committed-old" not in page.read_text() and "uncommitted-new" not in page.read_text()
    monkeypatch.setattr(judge, "DATA", table.parent)
    monkeypatch.setattr(judge, "OUT", table.parent / "judge")
    monkeypatch.setattr(judge.paths, "trajectories_dir", lambda: tmp_path / "trajectories")
    assert judge.episodes() == []
    assert "1 missing transcripts" in judge.report()
    labels = taxonomy.analyze_arm(table, archive)
    assert not labels.iloc[0].transcript


@pytest.mark.parametrize("identity", [None, "scored-attempt"])
def test_absent_decoder_never_uses_mutable_work_directory(
    tmp_path: Path, identity: str | None
) -> None:
    work = tmp_path / "work"
    (work / "t").mkdir(parents=True)
    (work / "t" / "decoder.py").write_text("m = Matching(dem, enable_correlations=True)")
    row = pd.Series(dict(task="t", attempt_id=identity, decoder_src="", decoder_bytes=0))
    assert fm._source(row, work) == ""


@pytest.mark.parametrize("source", [None, float("nan"), pd.NA])
def test_versioned_unknown_source_never_uses_mutable_work_directory(
    tmp_path: Path, source: object
) -> None:
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "decoder.py").write_text("uncommitted source")
    row = pd.Series(dict(task="t", attempt_id="identified", decoder_src=source))
    assert fm._source(row, tmp_path) == ""


def test_renderer_reads_score_snapshot_once_during_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, archive = interrupted_fixture(tmp_path, False)
    original = pd.read_parquet
    reads = []

    def replacing_read(path: Path, *args: object, **kwargs: object) -> pd.DataFrame:
        result = original(path, *args, **kwargs)
        if path == table:
            reads.append(True)
            newest = list(transcripts.records(archive))[-1]
            updated = result.assign(attempt_id=newest["attempt_id"], passed=False)
            attempts.write_table(table, updated.to_dict("records"))
        return result

    monkeypatch.setattr(pd, "read_parquet", replacing_read)
    page = transcripts.render_archive(archive, table) / "t.md"
    assert reads == [True]
    assert "committed-old" in page.read_text()
    assert "uncommitted-new" not in page.read_text()


@pytest.mark.parametrize("derived_id", [None, "stale-attempt"])
def test_stale_classifications_are_not_attached_to_current_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, derived_id: str | None
) -> None:
    table, archive = interrupted_fixture(tmp_path, False)
    stale = dict(task="t", attempt_id=derived_id, label="stale-label", gate="stale-gate")
    pd.DataFrame([stale]).to_parquet(table.with_name("arm_taxonomy.parquet"))
    pd.DataFrame([stale | dict(leaf="stale-leaf")]).to_parquet(
        table.with_name("arm_failure_modes.parquet")
    )
    page = transcripts.render_archive(archive, table) / "t.md"
    assert "committed-old" in page.read_text()
    assert "stale-" not in page.read_text()
    monkeypatch.setattr(judge, "DATA", table.parent)
    assert judge.valid_tables()[0][1].empty


def test_classifiers_preserve_attempt_identity(tmp_path: Path) -> None:
    table, archive = interrupted_fixture(tmp_path, False)
    identity = pd.read_parquet(table).iloc[0].attempt_id
    assert fm.analyze_decoder(table, archive).iloc[0].attempt_id == identity
    assert taxonomy.analyze_arm(table, archive).iloc[0].attempt_id == identity


def test_grid_waits_for_classification_of_current_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, _ = interrupted_fixture(tmp_path, False)
    spec = importlib.util.spec_from_file_location(
        "attempt_grid", SPEC.origin.replace("judge_transcripts.py", "grid_table.py")
    )
    grid = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grid)
    rows = pd.read_parquet(table).assign(passed=True, pass_rel=True)
    monkeypatch.setattr(grid, "scored", lambda _: rows.copy())
    monkeypatch.setattr(
        grid, "parse_arm", lambda name: ("test", "high", "codex") if name == "arm" else None
    )
    labels = table.with_name("arm_taxonomy.parquet")
    current = pd.read_parquet(labels)
    current.assign(attempt_id="older").to_parquet(labels)
    assert grid.cells(table.parent) == {}
    current.to_parquet(labels)
    assert grid.cells(table.parent) == {("test", "codex"): {"high": "100% / 100%"}}
