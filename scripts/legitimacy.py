"""Label every episode with the one taxonomy and check that the episodes and the tasks are fair.

    uv run python scripts/legitimacy.py                  # every arm of data/agent_launch2
    uv run python scripts/legitimacy.py --detector       # also the honest-detector check (slow)

Writes <arm>_taxonomy.parquet per arm (scoring/taxonomy.py) and docs/legitimacy.md:

- the label counts of every arm, and the episodes with a harness fault, an integrity event or
  a scoring anomaly, one line each;
- per task, over every valid episode of every arm: the pass, diagnosis and fix rates and the
  label counts, with a flag when no arm passes it, every arm passes it, or no arm diagnoses it;
- per drift task, whether the diagnosis the scorer asks for can be read off the deploy shots
  the agent gets: the honest adaptive decoder (decoders/adaptive.py), run as a detector on
  those shots, names the qubits it reweights on at least DETECT_SHOTS shots; its Jaccard
  overlap with the truth should reach the pass rule's LOCALIZE_MIN. Cached in
  data/agent_launch2/detector.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from qec_drift import paths
from qec_drift.agent import awareness as aw
from qec_drift.agent import decoder_task as dt
from qec_drift.scoring import taxonomy as tx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "agent_launch2"
DOC = ROOT / "docs" / "legitimacy.md"
DETECT_SHOTS = 50  # a hypothesis counts as found when it is applied to this many deploy shots
MIN_EPISODES = 4  # a task flag needs at least this many valid episodes
SKIP = ("_failure_modes", "_taxonomy")


def arms() -> list[Path]:
    return sorted(p for p in DATA.glob("*.parquet") if not p.stem.endswith(SKIP))


def label_all() -> pd.DataFrame:
    frames = []
    for table in arms():
        rows = pd.read_parquet(table)
        if rows.empty:
            continue  # an arm whose every row was set aside for a rerun
        archive = paths.trajectories_dir() / DATA.name / f"decoder_{table.stem}.jsonl.gz"
        out = tx.analyze_arm(table, archive if archive.is_file() else None)
        # reindex: an arm with no scored episode yet (every row a harness error) lacks a column
        scored = rows.reindex(columns=["task", "diagnosis_correct", "gap_closed", "gap_drift"])
        frames.append(out.merge(scored, on="task", how="left"))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def detector(task: dt.Task) -> dict:
    """The honest decoder as a detector on the deploy shots: what it would report."""
    from qec_drift.decoders import adaptive

    pre = dt.true_circuit(task.d, task.scenario, task.seed)
    a = adaptive.Adaptive(pre, task.seed)
    keys = a.assignments(dt.deploy_shots(task))
    counts: dict[int, int] = {}
    for key in keys:
        for h in key:
            counts[h] = counts.get(h, 0) + 1
    found = set()
    for h, n in counts.items():
        if n >= DETECT_SHOTS:
            found |= set(a.hypotheses[h][0])
    truth = task.truth
    overlap = aw.jaccard(found, truth.qubits) if truth.scope in ("local", "moving") else None
    return dict(
        scope=truth.scope,
        truth=sorted(truth.qubits),
        found=sorted(found),
        jaccard=overlap,
        moving_shots=sum(1 for k in keys if k),
    )


def ideal(task: dt.Task) -> dict:
    """What a reader who knew each deploy shot's regime could name: the truth qubits that were
    bad on at least DETECT_SHOTS deploy shots. The truth is fair when that set reaches the
    pass rule's overlap bar; otherwise the scorer asks for qubits no one could see."""
    import numpy as np

    truth = task.truth
    if truth.scope not in ("local", "moving"):
        return dict(ideal_jaccard=None, short_lived=0)
    if task.stationary:
        return dict(ideal_jaccard=1.0, short_lived=0)
    pre = dt.true_circuit(task.d, task.scenario, task.seed)
    proc = dt.drift.process(pre, task.drift, task.d, task.seed, "deploy")
    n = task.deploy or dt.SHOTS["deploy"]
    regime = dt.regime_sequence(proc, n, dt.SEEDS["deploy"] + 1000 * task.seed)
    shots: dict[int, int] = {}
    for r, count in zip(*np.unique(regime, return_counts=True), strict=True):
        for q in proc.qubits[int(r)] if r else ():
            shots[q] = shots.get(q, 0) + int(count)
    static = proc.qubits[0]
    seen = {q for q, c in shots.items() if c >= DETECT_SHOTS} | set(static)
    return dict(
        ideal_jaccard=aw.jaccard(seen, truth.qubits),
        short_lived=sum(1 for q in truth.qubits if q not in seen),
    )


def detector_table(tasks: list[str]) -> dict:
    path = DATA / "detector.json"
    cache = json.loads(path.read_text()) if path.is_file() else {}
    for name in tasks:
        task = dt.tasks_by_name(name)[0]
        if task.model_adequate:
            continue
        if name not in cache:
            print(f"detector: {name}", flush=True)
            cache[name] = detector(task)
        cache[name] |= ideal(task)
        path.write_text(json.dumps(cache, indent=1))
    return cache


def task_table(eps: pd.DataFrame) -> pd.DataFrame:
    valid = eps[eps.label != "invalid_run"]
    rows = []
    for task, g in valid.groupby("task"):
        n = len(g)
        passed = int((g.label == "passed").sum())
        diag = int(g.diagnosis_correct.fillna(False).astype(bool).sum())
        flags = []
        if n >= MIN_EPISODES and passed == 0:
            flags.append("never_passed")
        if n >= MIN_EPISODES and passed == n:
            flags.append("always_passed")
        if n >= MIN_EPISODES and diag == 0:
            flags.append("never_diagnosed")
        counts = g.label.value_counts()
        rows.append(
            dict(
                task=task,
                episodes=n,
                passed=f"{passed} ({passed / n:.0%})",
                diagnosed=f"{diag} ({diag / n:.0%})",
                labels=", ".join(f"{k} {v}" for k, v in counts.items()),
                flags=",".join(flags),
            )
        )
    return pd.DataFrame(rows).sort_values("task")


def markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "(none)"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for _, r in df.iterrows()]
    return "\n".join(lines)


def detector_coverage(det: dict) -> str:
    expected = {t.name for t in dt.launch2core_tasks() if not t.model_adequate}
    missing = sorted(expected - det.keys())
    text = (
        f"Detector checks cover {len(expected) - len(missing)} of {len(expected)} "
        "non-adequate core tasks."
    )
    if missing:
        text += " Missing checks: " + ", ".join(f"`{name}`" for name in missing) + ". "
        text += "Run `uv run python scripts/legitimacy.py --detector` to refresh these checks."
    return text


def report(eps: pd.DataFrame, det: dict) -> str:
    diag_rate = (
        eps[eps.label != "invalid_run"]
        .groupby("task")
        .diagnosis_correct.apply(lambda s: f"{s.fillna(False).astype(bool).mean():.0%}")
    )
    counts = eps.pivot_table(index="arm", columns="label", values="task", aggfunc="count")
    counts = counts.reindex(columns=[c for c in tx.LABELS if c in counts.columns]).fillna(0)
    counts = counts.astype(int).reset_index()
    flagged = eps[(eps.harness != "") | (eps.integrity != "") | (eps.anomalies != "")]
    flagged = flagged[["arm", "task", "label", "harness", "integrity", "anomalies"]]
    det_rows = pd.DataFrame(
        [
            dict(
                task=k,
                scope=v["scope"],
                truth_qubits=len(v["truth"]),
                short_lived=v.get("short_lived", ""),
                ideal_jaccard=""
                if v.get("ideal_jaccard") is None
                else round(v["ideal_jaccard"], 2),
                fair=""
                if v.get("ideal_jaccard") is None
                else ("yes" if v["ideal_jaccard"] >= aw.LOCALIZE_MIN else "NO"),
                honest_found=len(v["found"]),
                honest_jaccard="" if v["jaccard"] is None else round(v["jaccard"], 2),
                agents_diagnosed=diag_rate.get(k, ""),
            )
            for k, v in sorted(det.items())
        ]
    )
    return "\n\n".join(
        [
            "# Legitimacy and failure modes of the v2 launch set",
            "Generated by `scripts/legitimacy.py` from every episode in `data/agent_launch2`. "
            "The labels are the one taxonomy of `docs/failure-taxonomy.md`. "
            "`invalid_run` episodes are set aside and rerun; they never count.",
            "## Labels per arm",
            markdown(counts),
            "## Observed task outcomes",
            markdown(task_table(eps)),
            "## Can the diagnosis be read off the deploy shots?",
            detector_coverage(det),
            "An ideal reader who knew the regime of every deploy shot could name the truth "
            f"qubits that were bad on at least {DETECT_SHOTS} shots (`short_lived` counts the "
            "others). The truth is fair when that set reaches the pass rule's overlap bar of "
            f"{aw.LOCALIZE_MIN} (`ideal_jaccard`). For reference: the honest adaptive decoder "
            "run as a detector (it reweights whole disks, so it over-reports on a one-qubit "
            "fault), and the share of agent episodes that got the diagnosis right.",
            markdown(det_rows),
            "## Episodes with a flag",
            "harness: the environment failed the agent. integrity: the agent reached outside "
            "the task (a denied path, the network, files outside its folder, names of the "
            "test or the harness). anomalies: a result to check by hand.",
            markdown(flagged),
        ]
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--detector", action="store_true", help="run the honest-detector check")
    args = ap.parse_args()
    eps = label_all()
    if eps.empty:
        sys.exit("no arms yet")
    det_path = DATA / "detector.json"
    det = detector_table(list(dt.LAUNCH2_CORE)) if args.detector else (
        json.loads(det_path.read_text()) if det_path.is_file() else {}
    )  # fmt: skip
    DOC.write_text(report(eps, det) + "\n")
    print(eps.label.value_counts().to_string())
    print(f"wrote {DOC}")


if __name__ == "__main__":
    main()
