"""Grade data-out solutions with each task's own grader, and apply the QEC-Drift pass rule.

Each task in envs/ grades a solution with `evaluate.py --report`: it runs `solve(data)` in a
fresh `python -I` process in an empty temporary folder (eval/_isolate.py), with a timeout and
JSON out, and applies the returned data to the hidden test data. The seed reaches the grader on
a pipe, never in argv or the environment. This module runs that grader on the public seed and
the paper seeds (envs/config.json), reads the per-instance report, and applies the same rule as
`awareness.passed`, per instance:

- the "changed" answer is right;
- on a changed instance, at least half of the diagnosis credit;
- where a fix is graded, at least PASS_GAP of the gap to the best-known fix closed.

An episode's pass rate is the mean over the paper seeds' instances. Agent code runs in
_isolate.py, not under sandbox-exec, so grade agent solutions in a container or a throwaway VM.

Example:
    uv run python -m qec_drift.agent.envs_grade --references
    uv run python -m qec_drift.agent.envs_grade data/envs_hard/opus_5_5_cc.parquet
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from qec_drift import paths
from qec_drift.agent.awareness import PASS_GAP
from qec_drift.agent.envs_kit import ENVS, TASKS
from qec_drift.scoring.failure_modes_envs import analyze_envs

CONFIG = json.loads((ENVS / "config.json").read_text())
OUT = paths.DATA / "envs_hard"
BASELINES = {"trivial": "eval/_trivial.py", "reference": "eval/_reference.py"}
PINS = {k: "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}


def seeds() -> list[int | None]:
    """None (the public smoke-test set) and the paper seeds."""
    return [None, *CONFIG["paper_seeds"]]


def seed_tag(seed: int | None) -> str:
    return "public" if seed is None else str(seed)


def report(task: str, solution: Path, seed: int | None, dest: Path, ablate: bool = False) -> dict:
    """The task grader's per-instance report for one seed, cached at `dest`."""
    if dest.exists():
        return json.loads(dest.read_text())
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    cmd = [sys.executable, "evaluate.py", "--solution", str(solution.resolve()), "--report"]
    cmd += [str(part.resolve()), "--tier", CONFIG["tier"]]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    env = dict(os.environ, **PINS, MISMATCH_ABLATE="1" if ablate else "0")
    res = subprocess.run(cmd, cwd=ENVS / task, capture_output=True, text=True, env=env)
    if res.returncode != 0 or not part.exists():
        raise RuntimeError(f"{task} {solution} {seed_tag(seed)}: {res.stderr[-800:]}")
    part.rename(dest)
    return json.loads(dest.read_text())


def _readout(rep: dict) -> Iterator[dict]:
    for r in rep["instances"]:
        changed = bool(r["truth"])
        right = r.get("changed") == changed
        # the report's diagnosis credit: 0.15 for the kind, 0.10 for the magnitude
        diag = right * (0.15 * r["kind"] + 0.10 * r["magnitude"]) / 0.25 if "kind" in r else None
        yield dict(
            truth_changed=changed,
            said=r.get("changed"),
            fix=r.get("fix"),
            diag=diag,
            score=r["score"],
            error="error" in r,
        )


# task -> its report's instances as (truth_changed, said, fix, diag, score, error)
READERS: dict[str, Callable[[dict], Iterator[dict]]] = {"readout_drift": _readout}


def passed(row: dict) -> bool:
    """`awareness.passed` on one instance: the diagnosis is right and the fix closes PASS_GAP."""
    right = row["said"] is not None and bool(row["said"]) == row["truth_changed"]
    diag_ok = right and (not row["truth_changed"] or row["diag"] is None or row["diag"] >= 0.5)
    return diag_ok and (row["fix"] is None or row["fix"] >= PASS_GAP)


def reports(
    task: str, solution: Path, label: str, which: list[int | None], ablate: bool = False
) -> dict[str, dict]:
    """The reports of `solution` on the seeds `which`, one grader process per seed at a time."""

    def one(seed: int | None) -> dict:
        dest = OUT / "reports" / task / label / f"{seed_tag(seed)}.json"
        return report(task, solution, seed, dest, ablate)

    with ThreadPoolExecutor(min(len(which), os.cpu_count() or 1)) as pool:
        return dict(zip(map(seed_tag, which), pool.map(one, which), strict=True))


def instance_rows(task: str, solution: Path, label: str, ablate: bool = False) -> list[dict]:
    """One row per graded instance of `solution`, over the public and paper seeds."""
    out = []
    for tag, rep in reports(task, solution, label, seeds(), ablate).items():
        for i, row in enumerate(READERS[task](rep)):
            out.append(
                dict(task=task, label=label, seed=tag, instance=i, **row, passed=passed(row))
            )
    return out


def pass_rate(rows: list[dict]) -> dict:
    """Pass rate and native score over the paper seeds (the public seed is a smoke test)."""
    paper = [r for r in rows if r["seed"] != "public"]
    n = len(paper)
    return dict(
        pass_rate=sum(r["passed"] for r in paper) / n if n else None,
        score=sum(r["score"] for r in paper) / n if n else None,
        instances=n,
    )


def references() -> dict:
    """Trivial floor and best-known method per task; writes data/envs_hard/references.json."""
    refs = {}
    for task in TASKS:
        refs[task] = {
            name: pass_rate(instance_rows(task, ENVS / task / rel, name))
            for name, rel in BASELINES.items()
        }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "references.json").write_text(
        json.dumps(dict(config=CONFIG["version"], tier=CONFIG["tier"], tasks=refs), indent=1) + "\n"
    )
    return refs


def grade_arm(table: Path) -> pd.DataFrame:
    """Grade every episode of an arm table (envs_run.py), write its pass rate and native score
    back into the table, write <arm>_instances.parquet, and end with the failure modes
    (scoring/failure_modes_envs.py), as every decoder arm does."""
    df = pd.read_parquet(table)
    every, rates = [], []
    for ep in df.to_dict("records"):
        if ep["outcome"] == "error" or not ep.get("solution_path"):
            rates.append(dict(pass_rate=None, score=None, instances=0))
            continue
        solution = paths.REPO_ROOT / ep["solution_path"]
        # reports are cached by name: the arm, the rollout and the solution's own hash, so a
        # rerun rollout or another arm with the same model never reads a stale report
        digest = hashlib.sha256(solution.read_bytes()).hexdigest()[:12]
        label = f"{table.stem}__r{ep['rollout']}__{digest}"
        rows = instance_rows(ep["env"], solution, label)
        every += [dict(r, arm=table.stem, rollout=ep["rollout"]) for r in rows]
        rates.append(pass_rate(rows))
    df = df.assign(**pd.DataFrame(rates, index=df.index))
    df.to_parquet(table, index=False)
    pd.DataFrame(every).to_parquet(table.with_name(f"{table.stem}_instances.parquet"), index=False)
    analyze_envs(table)
    return df


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("tables", nargs="*", type=Path, help="arm tables from envs_run.py")
    ap.add_argument("--references", action="store_true", help="grade trivial and reference")
    a = ap.parse_args(argv)
    if a.references:
        print(json.dumps(references(), indent=1))
    for table in a.tables:
        df = grade_arm(table)
        print(df[["env", "rollout", "outcome", "pass_rate", "score"]].to_string(index=False))


if __name__ == "__main__":
    main()
