"""Review a frozen finite atlas inventory through the subscription-backed judge.

Shares the existing finite-judge lock, admits two reviews at a time, and stops
at the existing quota gate. Each input receives at most two attempts per launch.
"""

from __future__ import annotations

import argparse
import fcntl
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import judge_transcripts as judge
from failure_atlas_inputs import EXTRA_PROTOCOL, extra_key
from judge_tick import CONCURRENCY, quota_available


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []


def review(directory: Path) -> None:
    lock_path = judge.ROOT / ".cache/research-continuation/finish-judges.lock"
    print("Waiting for the single finite-review lock", flush=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        inputs = read_jsonl(directory / "inputs.jsonl")
        for item in inputs:
            expected = (
                judge.key(item["payload"])
                if item["protocol"] == judge.PROTOCOL
                else (extra_key(item["payload"]) if item["protocol"] == EXTRA_PROTOCOL else None)
            )
            if item["key"] != expected:
                raise ValueError("Input identity differs from current judge settings")
        output = directory / "reviews.jsonl"
        existing = judge.judged() + read_jsonl(output)
        keys = {
            r["key"]
            for r in existing
            if r.get("protocol") in {judge.PROTOCOL, "atlas-archive-fresh-v1"}
        }
        pending = [r for r in inputs if r["key"] not in keys]
        state = dict(
            started_utc=datetime.now(UTC).isoformat(),
            total=len(inputs),
            initial_pending=len(pending),
            completed=0,
            errors=0,
            status="running",
        )

        def save():
            path = directory / "review-state.json"
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(state, indent=2))
            temp.replace(path)
            print(json.dumps(state), flush=True)

        def one(item):
            try:
                value = judge.judge_one(item["payload"])
                if (
                    set(value) != set(judge.SCHEMA["required"])
                    or value["label"] not in judge.tx.LABELS
                ):
                    raise ValueError("Judge response does not match the frozen schema")
                return value | {k: item[k] for k in ("key", "protocol", "cohort", "run_id")}
            except Exception as exc:  # one bounded retry, no unbounded retry loop
                return {"error": type(exc).__name__, "run_id": item["run_id"]}

        save()
        for index in range(0, len(pending), CONCURRENCY):
            if not quota_available():
                state["status"] = "quota_blocked"
                break
            batch = pending[index : index + CONCURRENCY]
            with ThreadPoolExecutor(CONCURRENCY) as pool:
                results = list(pool.map(one, batch))
            for item, result in zip(batch, results, strict=True):
                if "error" in result and quota_available():
                    result = one(item)
                if "error" in result:
                    state["errors"] += 1
                    with (directory / "review-errors.jsonl").open("a") as file:
                        file.write(json.dumps(result) + "\n")
                else:
                    with output.open("a") as file:
                        file.write(json.dumps(result) + "\n")
                    state["completed"] += 1
            save()
        else:
            state["status"] = "complete" if not state["errors"] else "finished_with_errors"
        state["finished_utc"] = datetime.now(UTC).isoformat()
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    review(parser.parse_args().directory)
