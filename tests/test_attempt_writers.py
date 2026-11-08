from __future__ import annotations

import argparse
import dataclasses
import gzip
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from qec_drift.agent import attempts, transcripts
from qec_drift.agent import decoder_run as api
from qec_drift.agent import decoder_run_cc as cc
from qec_drift.agent import decoder_task as dt


@pytest.mark.parametrize("driver", ["api", "cli", "cli_append"])
def test_driver_commit_failure_preserves_previous_score_and_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver: str
) -> None:
    out = tmp_path / "data"
    out.mkdir()
    archive_root = tmp_path / "trajectories"
    folder = archive_root / out.name
    folder.mkdir(parents=True)
    archive = folder / "decoder_arm.jsonl.gz"
    old = {"task": "t", "try": "old"}
    archive.write_bytes(gzip.compress((json.dumps(old) + "\n").encode()))
    prefix = archive.read_bytes()
    table = out / "arm.parquet"
    attempts.write_table(table, [{"task": "t", "outcome": "submitted"}])
    before = table.read_bytes()
    monkeypatch.setattr(cc.paths, "trajectories_dir", lambda: archive_root)
    monkeypatch.setattr(dt, "tasks_by_name", lambda _: [SimpleNamespace(name="t")])
    monkeypatch.setattr(api, "warm_up_stim", lambda: None)
    row = dict(task="t", outcome="error", cost_usd=0.0)
    new = {"task": "t", "try": "new"}
    monkeypatch.setattr(api, "safe_episode", lambda *_args, **_kwargs: (row, new))
    monkeypatch.setattr(cc, "safe_episode", lambda *_args, **_kwargs: (row, new))

    def failed_commit(*_args: object) -> None:
        assert len(list(transcripts.records(archive))) == 2
        raise OSError("injected commit failure")

    monkeypatch.setattr(attempts, "write_table", failed_commit)
    with pytest.raises(OSError, match="injected commit failure"):
        if driver == "api":
            monkeypatch.setattr(api.pricing, "estimate_usd", lambda *_args: 1.0)
            monkeypatch.setattr(api, "AnthropicClient", object)
            monkeypatch.setattr(
                sys,
                "argv",
                [
                    "decoder-run",
                    "--model",
                    "test",
                    "--arm",
                    "arm",
                    "--max-usd",
                    "1",
                    "--tasks",
                    "t",
                    "--out",
                    str(out),
                    "--concurrency",
                    "1",
                ],
            )
            api.main()
        else:
            args = argparse.Namespace(
                out=out,
                arm="arm",
                tasks="t",
                set="unused",
                append=driver == "cli_append",
                concurrency=1,
                model="test",
                effort="high",
                max_usd=1,
            )
            cc.run_arm(args, dataclasses.replace(cc.CLAUDE_CODE, check=lambda: None))
    assert table.read_bytes() == before
    assert archive.read_bytes().startswith(prefix)
    assert transcripts.matching_records(archive, pd.read_parquet(table))["t"] == old
    assert list(transcripts.records(archive))[-1]["attempt_id"]
    assert "attempt_id" not in row and "attempt_id" not in new
