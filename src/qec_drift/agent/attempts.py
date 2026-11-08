from __future__ import annotations

import gzip
import json
import math
import os
import tempfile
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import BinaryIO

import pandas as pd


def _identity(record: Mapping) -> str | None:
    value = record.get("attempt_id")
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, str) and value:
        return value
    raise ValueError("invalid attempt identity")


def is_legacy(record: Mapping) -> bool:
    try:
        return _identity(record) is None
    except ValueError:
        return False


def require_legacy(rows: pd.DataFrame) -> None:
    if not all(is_legacy(row) for row in rows.to_dict("records")):
        raise ValueError("This legacy maintenance script cannot modify identified attempts")


def select(records: Iterable[dict], rows: Iterable[Mapping]) -> dict[str, dict]:
    by_id, ambiguous = {}, set()
    for rec in records:
        try:
            identity = _identity(rec)
        except ValueError:
            continue
        task = rec.get("task")
        if not isinstance(task, str):
            continue
        key = task, identity
        if identity is not None and key in by_id and by_id[key] != rec:
            ambiguous.add(key)
        by_id[key] = rec
    selected = {}
    for row in rows:
        try:
            key = row["task"], _identity(row)
        except ValueError:
            continue
        if key in by_id and key not in ambiguous:
            selected[row["task"]] = by_id[key]
    return selected


def append_attempt(trace: BinaryIO, row: dict, trajectory: dict, arm: str) -> dict:
    if row["task"] != trajectory["task"]:
        raise ValueError("score and transcript tasks differ")
    identity = uuid.uuid4().hex
    record = trajectory | {"attempt_id": identity}
    trace.write(gzip.compress((json.dumps(record, ensure_ascii=False) + "\n").encode()))
    trace.flush()
    os.fsync(trace.fileno())
    return row | {"arm": arm, "attempt_id": identity}


def write_table(table: Path, rows: list[dict] | pd.DataFrame) -> None:
    with tempfile.NamedTemporaryFile(
        dir=table.parent, prefix=f".{table.stem}-", delete=False
    ) as tmp:
        path = Path(tmp.name)
        try:
            pd.DataFrame(rows).to_parquet(tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(path, table)
        finally:
            path.unlink(missing_ok=True)
