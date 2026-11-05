"""Run many arms of one subscription scaffold over the gated tasks of a set, and resume.

Usage:
    uv run python scripts/run_grid.py --backend claude --set launch2 --out data/agent_launch2 \\
        --arms claude-fable-5-1:max,claude-haiku-4-5:low --concurrency 2

An arm is <model>:<effort>. Its name is the model without the vendor prefix, the effort and
the scaffold: fable_5_1_max_cc, gpt_6_astra_max_codex. A drift task passes the gate when the
oracle beats the stale fit by 20% and the honest adaptive decoder recovers at least half of
that loss; adequate tasks always pass. For each arm, the tasks without a valid row (no row,
or an error row) run with --append after a memory gate of MEMORY_FREE percent. Arms run in
the order given, one at a time; a second call resumes whatever is left.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
MODULES = {
    "claude": "qec_drift.agent.decoder_run_cc",
    "codex": "qec_drift.agent.decoder_run_codex",
}
SUFFIX = {"claude": "cc", "codex": "codex"}
MEMORY_FREE = 20
EXIT_LOGIN_LOST = 3  # decoder_run_cc.EXIT_LOGIN_LOST
MIN_TASKS = 10
VALID = ("submitted", "no_decoder")
TOOL_CALLS = 40  # isolation.TOOL_CALLS: an episode that went past it predates the cap


def gate(refs: dict[str, dict]) -> tuple[list[str], list[str]]:
    """The task names that pass, and one line per task saying why."""
    keep, lines = [], []
    for name, r in refs.items():
        if "stale_corr" not in r:
            keep.append(name)
            lines.append(f"{name:34s} adequate")
            continue
        ratio = r["true_corr"] / r["stale_corr"]
        span = r["stale_corr"] - r["true_corr"]
        known = r.get("adaptive_corr", r.get("pij_corr"))  # stationary faults: the refit
        honest = (r["stale_corr"] - known) / span if span > 0 else float("nan")
        ok = ratio <= 0.80 and honest >= 0.5
        why = "keep" if ok else ("drop: no gap" if ratio > 0.80 else "drop: no honest method")
        lines.append(f"{name:34s} true/stale {ratio:5.2f} honest {honest:5.2f} {why}")
        if ok:
            keep.append(name)
    return keep, lines


def arm_name(model: str, effort: str, backend: str) -> str:
    short = re.sub(r"[^a-z0-9]+", "_", re.sub(r"^claude-", "", model.lower())).strip("_")
    return f"{short}_{effort}_{SUFFIX[backend]}"


def pending(table: Path, tasks: list[str]) -> list[str]:
    """The tasks without a valid row: an episode in which the agent acted, or that completed."""
    if not table.exists():
        return list(tasks)
    df = pd.read_parquet(table)
    acted = (df.turns.fillna(0) > 0) | (df.stop == "completed")
    within = df.turns.fillna(0) <= TOOL_CALLS + 1  # the killing call itself may be counted
    done = set(df.loc[df.outcome.isin(VALID) & acted & within, "task"])
    return [t for t in tasks if t not in done]


def memory_free() -> int:
    out = subprocess.run(["memory_pressure", "-Q"], capture_output=True, text=True).stdout
    m = re.search(r"(\d+)%", out)
    return int(m.group(1)) if m else 100


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--backend", choices=sorted(MODULES), required=True)
    ap.add_argument("--set", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--arms", required=True, help="comma list of <model>:<effort>")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--tasks", default="", help="comma list: only these gated tasks")
    ap.add_argument("--core", action="store_true", help="only the LAUNCH2_CORE tasks")
    args = ap.parse_args()
    if args.core:  # the names stay off this process's command line, which episodes can read
        from qec_drift.agent.decoder_task import LAUNCH2_CORE

        args.tasks = ",".join(LAUNCH2_CORE)
    refs = json.loads((args.out / "references.json").read_text())
    keep, lines = gate(refs)
    print("\n".join(lines))
    if args.tasks:
        wanted = [t.strip() for t in args.tasks.split(",") if t.strip()]
        missing = [t for t in wanted if t not in keep]
        if missing:
            sys.exit(f"refusing: not gated or not referenced: {missing}")
        keep = wanted
    print(f"gate kept {len(keep)} of {len(refs)} tasks", flush=True)
    if len(keep) < MIN_TASKS:
        sys.exit(f"refusing: fewer than {MIN_TASKS} tasks survive the gate")
    for spec in args.arms.split(","):
        model, effort = spec.strip().split(":")
        name = arm_name(model, effort, args.backend)
        table = args.out / f"{name}.parquet"
        todo = pending(table, keep)
        if not todo:
            print(f"{name}: done", flush=True)
            continue
        while memory_free() < MEMORY_FREE:
            print(f"{name}: waiting, {memory_free()}% memory free", flush=True)
            time.sleep(300)
        cmd = ["uv", "run", "python", "-m", MODULES[args.backend]]
        cmd += ["--model", model, "--effort", effort, "--arm", name, "--set", args.set]
        todo_file = args.out / f"{name}.todo"  # under the repository: hidden from episodes
        todo_file.write_text("\n".join(todo) + "\n")
        cmd += ["--tasks", f"@{todo_file}", "--out", str(args.out)]
        cmd += ["--concurrency", str(args.concurrency)]
        if table.exists():
            cmd.append("--append")
        print(f"{name}: {len(todo)} tasks to run", flush=True)
        with (args.out / f"{name}.log").open("a") as log:
            run = subprocess.run(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT, check=False)
        left = pending(table, keep)
        print(f"{name}: finished, {len(left)} tasks without a valid row", flush=True)
        if run.returncode == EXIT_LOGIN_LOST:
            sys.exit("the subscription login is gone; log in again and rerun this command")


if __name__ == "__main__":
    main()
