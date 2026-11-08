from __future__ import annotations

import gzip
import json
from pathlib import Path

from qec_drift.agent.transcripts import records


def member(task: str) -> bytes:
    return gzip.compress((json.dumps(dict(task=task, events=[])) + "\n").encode(), mtime=0)


def test_magic_inside_valid_gzip_member_is_not_a_boundary(tmp_path: Path) -> None:
    raw = member("middle")
    extra = b"inside\x1f\x8b\x08member"
    # FEXTRA is a legal part of one member and can contain the gzip magic bytes.
    embedded = raw[:3] + b"\x04" + raw[4:10] + len(extra).to_bytes(2, "little") + extra + raw[10:]
    archive = tmp_path / "records.jsonl.gz"
    archive.write_bytes(member("first") + embedded + member("last"))
    expected = [json.loads(line) for line in gzip.decompress(archive.read_bytes()).splitlines()]
    assert list(records(archive)) == expected


def test_reader_recovers_after_bad_member_and_preserves_complete_truncated_line(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "records.jsonl.gz"
    archive.write_bytes(
        member("first") + b"junk\x1f\x8b\x08invalid" + member("second") + member("tail")[:-8]
    )
    assert [r["task"] for r in records(archive)] == ["first", "second", "tail"]


def test_reader_skips_invalid_json_and_does_not_invent_partial_record(tmp_path: Path) -> None:
    archive = tmp_path / "records.jsonl.gz"
    archive.write_bytes(gzip.compress(b'{"task":"ok"}\ninvalid\n{"task":', mtime=0)[:-8])
    assert list(records(archive)) == [dict(task="ok")]


def test_reader_recovers_past_truncated_header_waiting_for_extra_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "records.jsonl.gz"
    truncated = member("unused")[:3] + b"\x04" + member("unused")[4:10] + b"\xff\xff"
    archive.write_bytes(member("first") + truncated + member("last"))
    assert [r["task"] for r in records(archive)] == ["first", "last"]
