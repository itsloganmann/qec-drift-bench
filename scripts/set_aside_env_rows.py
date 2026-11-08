"""Set aside the Codex episodes hurt by the PATH defect fixed in agent/isolation.py on 2026-11-03.

An episode counts when its agent saw stim, pymatching or numpy missing, or installed its own
copy of one of them (a library the environment lacks, such as ldpc, does not count). Its row
moves from data/agent_launch2/<arm>.parquet to data/agent_launch2/env_defect/<arm>.parquet,
kept for the record, so scripts/run_grid.py reruns that task on the fixed environment. The
archive keeps every attempt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from qec_drift.agent import attempts
from qec_drift.agent.transcripts import matching_records

ROOT = Path(__file__).resolve().parents[1]
MISSING = re.compile(r"No module named '(stim|pymatching|numpy)'")
VENDOR = re.compile(r"(install|--target)[^\n]*\b(stim|pymatching|numpy)\b")  # not ldpc and the like


def hurt(rec: dict) -> bool:
    for e in rec.get("events", []):
        item = e.get("item") or {}
        if item.get("type") != "command_execution":
            continue
        if MISSING.search(item.get("aggregated_output") or "") or VENDOR.search(
            item.get("command") or ""
        ):
            return True
    return False


def main() -> None:
    out = ROOT / "data" / "agent_launch2"
    aside = out / "env_defect"
    aside.mkdir(exist_ok=True)
    for archive in sorted(
        (ROOT / "trajectories" / "agent_launch2").glob("decoder_*_codex.jsonl.gz")
    ):
        arm = archive.name.removeprefix("decoder_").removesuffix(".jsonl.gz")
        table = out / f"{arm}.parquet"
        if not table.is_file():
            continue
        df = pd.read_parquet(table)
        last = matching_records(archive, df)
        bad = sorted(t for t, rec in last.items() if hurt(rec))
        moved = df[df.task.isin(bad)]
        if moved.empty:
            print(f"{arm}: none")
            continue
        old = aside / f"{arm}.parquet"
        kept = pd.concat([pd.read_parquet(old), moved]) if old.is_file() else moved
        attempts.write_table(old, kept)
        attempts.write_table(table, df[~df.task.isin(bad)])
        print(f"{arm}: set aside {json.dumps(bad)}")


if __name__ == "__main__":
    main()
