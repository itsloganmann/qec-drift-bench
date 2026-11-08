from __future__ import annotations

import argparse
import dataclasses
import gzip
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from qec_drift.agent import decoder_run_cc as cc
from qec_drift.agent import decoder_run_codex as cx
from qec_drift.agent import decoder_task as dt
from qec_drift.agent import transcripts
from qec_drift.scoring import taxonomy as tx

LIMIT_MESSAGE = "You've hit your usage limit. Try again later."
CODEX_LIMIT = {"type": "turn.failed", "error": {"message": LIMIT_MESSAGE}}
CLAUDE_LIMIT = {"type": "result", "is_error": True, "result": LIMIT_MESSAGE}


@pytest.mark.parametrize("backend", [cc.CLAUDE_CODE, cx.BACKEND], ids=["claude", "codex"])
@pytest.mark.parametrize("has_decoder", [False, True])
def test_mid_episode_limit_is_saved_without_scoring(
    backend: cc.Backend, has_decoder: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = dt.Task(5, "none", "")
    terminal = CODEX_LIMIT if backend.name == "codex" else CLAUDE_LIMIT
    events = [terminal]
    released = []
    monkeypatch.setattr(dt, "write_agent_files", lambda _, p: p.mkdir(parents=True))
    monkeypatch.setattr(dt, "test_sample", lambda *_: (None, None, None))
    monkeypatch.setattr(dt, "task_references", lambda *_: {})

    def run(workdir: Path, *_: Any) -> tuple[list[dict], int]:
        if has_decoder:
            (workdir / "decoder.py").write_text("partial decoder")
        return events, 1

    def score(*_: Any) -> None:
        pytest.fail("A provider-interrupted attempt must not be scored")

    monkeypatch.setattr(cc.dr, "score_submission", score)
    fake = dataclasses.replace(
        backend,
        prepare=lambda _: tmp_path,
        release=released.append,
        run=run,
        turns=lambda _: 3,
    )
    row, rec = cc.safe_episode(task, "test", "high", tmp_path / "work", 1.0, backend=fake)
    assert row["outcome"] == "error" and row["provider_interrupted"]
    assert row["turns"] == 3 and not row["auto_scored"]
    assert not row["passed"]
    assert rec["events"] == events and released == [tmp_path]
    assert rec["decoder_src"] == ("partial decoder" if has_decoder else "")


@pytest.mark.parametrize("terminal", [CODEX_LIMIT, CLAUDE_LIMIT])
def test_legacy_interrupted_attempt_is_invalid_even_after_tool_calls(
    terminal: dict, tmp_path: Path
) -> None:
    table = tmp_path / "test_high_codex.parquet"
    row = dict(
        task="task",
        outcome="no_decoder",
        stop="failed",
        turns=3,
        passed=False,
        adequate_truth=True,
        gap_closed=float("nan"),
        gap_drift=float("nan"),
        diagnosis_correct=False,
        l_agent=float("nan"),
        decoder_src="",
    )
    pd.DataFrame([row]).to_parquet(table)
    archive = tmp_path / "decoder_test_high_codex.jsonl.gz"
    archive.write_bytes(
        gzip.compress((json.dumps({"task": "task", "events": [terminal]}) + "\n").encode())
    )
    labels = tx.analyze_arm(table, archive)
    assert labels.iloc[0].label == "invalid_run"
    assert "provider_limit" in labels.iloc[0].harness


@pytest.mark.parametrize(
    "events",
    [
        [CODEX_LIMIT, {"type": "turn.completed"}],
        [CLAUDE_LIMIT, {"type": "result", "is_error": False, "result": "done"}],
        [
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "aggregated_output": LIMIT_MESSAGE,
                },
            }
        ],
        [{"type": "harness", "note": "tool-call limit (40)"}],
        [{"type": "turn.failed", "error": {"message": "unrelated error"}}],
        [
            {"type": "error", "message": "429 Too Many Requests; reconnecting"},
            {"type": "turn.failed", "error": {"message": "Tool call budget exceeded"}},
        ],
    ],
)
def test_recovered_limits_tool_output_and_task_budget_are_not_provider_failures(
    events: list[dict],
) -> None:
    assert not tx.features({"events": events}).provider_interrupted


def test_standalone_provider_error_is_an_interruption() -> None:
    assert tx.features(
        {"events": [{"type": "error", "message": LIMIT_MESSAGE}]}
    ).provider_interrupted


def test_recovered_limit_before_unrelated_failure_is_scored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        {"type": "error", "message": "429 Too Many Requests; reconnecting"},
        {"type": "turn.failed", "error": {"message": "Tool call budget exceeded"}},
    ]
    monkeypatch.setattr(dt, "write_agent_files", lambda _, p: p.mkdir(parents=True))
    monkeypatch.setattr(dt, "test_sample", lambda *_: (None, None, None))
    monkeypatch.setattr(dt, "task_references", lambda *_: {})
    scored = []

    def score(*_: Any) -> tuple[str, None]:
        scored.append(True)
        return "no decoder", None

    monkeypatch.setattr(cc.dr, "score_submission", score)
    backend = dataclasses.replace(
        cx.BACKEND,
        prepare=lambda _: tmp_path,
        release=lambda _: None,
        run=lambda *_: (events, 1),
        turns=lambda _: 3,
    )
    row, _ = cc.safe_episode(
        dt.Task(5, "none", ""), "test", "high", tmp_path / "work", 1.0, backend=backend
    )
    assert scored == [True]
    assert row["outcome"] == "no_decoder" and not row["provider_interrupted"]


def test_arm_persists_interruption_and_stops_before_starting_more_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "data"
    out.mkdir()
    tasks = [SimpleNamespace(name="first"), SimpleNamespace(name="second")]
    row = dict(task="first", outcome="error", stop="failed", turns=3, provider_interrupted=True)
    rec = dict(task="first", events=[CODEX_LIMIT], decoder_src="partial")
    calls = []
    reports = []
    monkeypatch.setattr(dt, "tasks_by_name", lambda _: tasks)
    monkeypatch.setattr(cc.dr, "warm_up_stim", lambda: None)

    def episode(task: SimpleNamespace, *_args: Any, **_kwargs: Any) -> tuple[dict, dict]:
        calls.append(task.name)
        assert task.name == "first", "Do not start more tasks after a provider interruption"
        return row, rec

    monkeypatch.setattr(cc, "safe_episode", episode)

    def report(table: Path, archive: Path) -> None:
        assert pd.read_parquet(table).iloc[0].provider_interrupted
        assert list(transcripts.records(archive)) == [rec]
        reports.append(True)

    monkeypatch.setattr(cc, "report_arm", report, raising=False)
    backend = dataclasses.replace(cx.BACKEND, check=lambda: None)
    args = argparse.Namespace(
        out=out,
        arm="test",
        tasks="first,second",
        set="unused",
        append=False,
        concurrency=1,
        model="test",
        effort="high",
        max_usd=1,
    )
    with pytest.raises(SystemExit) as exc:
        cc.run_arm(args, backend)
    assert exc.value.code == cc.EXIT_THROTTLED
    assert calls == ["first"]
    assert reports == [True]
    saved = pd.read_parquet(out / "test.parquet")
    assert saved.iloc[0].provider_interrupted
    archive = cc.paths.trajectories_dir() / out.name / "decoder_test.jsonl.gz"
    assert list(transcripts.records(archive)) == [rec]


def test_grid_does_not_report_success_with_pending_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_grid.py"
    spec = importlib.util.spec_from_file_location("test_grid", script)
    grid = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grid)
    names = [f"task{i}" for i in range(grid.MIN_TASKS)]
    (tmp_path / "references.json").write_text(json.dumps({n: {} for n in names}))
    monkeypatch.setattr(grid, "memory_free", lambda: 100)
    monkeypatch.setattr(
        grid.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(
        grid.sys,
        "argv",
        [
            "run_grid.py",
            "--backend",
            "codex",
            "--set",
            "launch2core",
            "--out",
            str(tmp_path),
            "--arms",
            "test:high",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        grid.main()
    assert exc.value.code != 0
