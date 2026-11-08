from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from qec_drift.agent import attempts, transcripts


def test_committed_attempt_survives_archive_append_before_table_commit(tmp_path: Path) -> None:
    table, archive = tmp_path / "arm.parquet", tmp_path / "decoder_arm.jsonl.gz"
    row, rec = {"task": "t", "outcome": "submitted"}, {"task": "t", "report": {"try": 1}}
    with archive.open("ab") as trace:
        first = attempts.append_attempt(trace, row, rec, "arm")
        attempts.write_table(table, [first])
        second = attempts.append_attempt(trace, row, rec | {"report": {"try": 2}}, "arm")
    assert "attempt_id" not in row and "attempt_id" not in rec
    assert first["attempt_id"] != second["attempt_id"]
    assert transcripts.matching_records(archive, pd.read_parquet(table))["t"]["report"] == {
        "try": 1
    }
    attempts.write_table(table, [second])
    assert transcripts.matching_records(archive, pd.read_parquet(table))["t"]["report"] == {
        "try": 2
    }
    assert len(list(transcripts.records(archive))) == 2


def test_failed_table_write_preserves_previous_bytes_and_removes_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = tmp_path / "arm.parquet"
    attempts.write_table(table, [{"task": "old"}])
    before = table.read_bytes()

    def fail(self: pd.DataFrame, target: object) -> None:
        target.write(b"incomplete parquet")
        raise OSError("injected disk failure")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail)
    with pytest.raises(OSError):
        attempts.write_table(table, [{"task": "new"}])
    assert table.read_bytes() == before
    assert list(tmp_path.iterdir()) == [table]


def test_legacy_row_cannot_select_versioned_orphan(tmp_path: Path) -> None:
    archive = tmp_path / "decoder_arm.jsonl.gz"
    legacy = {"task": "t", "report": {"try": "old"}}
    archive.write_bytes(gzip.compress((json.dumps(legacy) + "\n").encode()))
    prefix = archive.read_bytes()
    with archive.open("ab") as trace:
        attempts.append_attempt(
            trace, {"task": "t"}, {"task": "t", "report": {"try": "new"}}, "arm"
        )
    for value in (None, float("nan"), pd.NA):
        selected = transcripts.matching_records(
            archive, pd.DataFrame([{"task": "t", "attempt_id": value}])
        )
        assert selected == {"t": legacy}
    assert archive.read_bytes().startswith(prefix)


@pytest.mark.parametrize("value", ["missing", "", 1, [], {}])
def test_invalid_or_unmatched_identity_never_falls_back(value: object) -> None:
    recs = [{"task": "t"}, {"task": "t", "attempt_id": "known"}]
    assert attempts.select(recs, [{"task": "t", "attempt_id": value}]) == {}


def test_duplicate_id_with_different_content_is_ambiguous() -> None:
    a = {"task": "t", "attempt_id": "same", "report": 1}
    b = a | {"report": 2}
    rows = [{"task": "t", "attempt_id": "same"}]
    assert attempts.select([a, dict(a)], rows) == {"t": a}
    assert attempts.select([a, b, a], rows) == {}


def test_selection_includes_task_and_ignores_malformed_record_ids() -> None:
    a = {"task": "t", "attempt_id": "a"}
    b = {"task": "other", "attempt_id": "a"}
    bad = {"task": "t", "attempt_id": []}
    assert attempts.select([a, b, bad], [a]) == {"t": a}


def test_missing_archive_has_no_match(tmp_path: Path) -> None:
    assert (
        transcripts.matching_records(tmp_path / "missing.gz", pd.DataFrame([{"task": "t"}])) == {}
    )


def test_task_mismatch_cannot_append_an_attempt(tmp_path: Path) -> None:
    archive = tmp_path / "archive.gz"
    with archive.open("ab") as trace, pytest.raises(ValueError):
        attempts.append_attempt(trace, {"task": "a"}, {"task": "b"}, "arm")
    assert archive.read_bytes() == b""


def test_process_exit_after_archive_append_keeps_previous_committed_pair(tmp_path: Path) -> None:
    table, archive = tmp_path / "arm.parquet", tmp_path / "decoder_arm.jsonl.gz"
    with archive.open("ab") as trace:
        first = attempts.append_attempt(trace, {"task": "t"}, {"task": "t", "try": 1}, "arm")
    attempts.write_table(table, [first])
    before = table.read_bytes()
    env = dict(os.environ, ATTEMPT_TEST_ROOT=str(tmp_path))
    child = subprocess.run(
        [sys.executable, "-"],
        input="""import os
from pathlib import Path
from qec_drift.agent import attempts
root = Path(os.environ["ATTEMPT_TEST_ROOT"])
with (root / "decoder_arm.jsonl.gz").open("ab") as trace:
    attempts.append_attempt(trace, {"task": "t"}, {"task": "t", "try": 2}, "arm")
    os._exit(23)
""",
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
    )
    assert child.returncode == 23, child.stderr
    assert table.read_bytes() == before
    assert len(list(transcripts.records(archive))) == 2
    assert transcripts.matching_records(archive, pd.read_parquet(table))["t"]["try"] == 1
