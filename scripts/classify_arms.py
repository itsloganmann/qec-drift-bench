"""Classify every arm's episodes into the failure taxonomy and render the transcripts.

    uv run python scripts/classify_arms.py            # every arm table under data/<set>/
    uv run python scripts/classify_arms.py --summary  # also a Markdown count table per arm

For each data/<set>/<arm>.parquet the adapter (scoring/failure_modes_decoder.py) writes
<arm>_failure_modes.parquet from the table and the arm's trajectory archive, then
agent/transcripts.py renders the archive with the leaf and the verdict on every page.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from qec_drift import paths
from qec_drift.agent import transcripts
from qec_drift.scoring import taxonomy
from qec_drift.scoring.failure_modes_decoder import analyze_decoder

SETS = ("agent_decoder", "agent_drift", "agent_hard", "agent_hard2", "agent_launch",
        "agent_launch2")  # fmt: skip


def archive_of(set_name: str, arm: str) -> Path:
    root = paths.trajectories_dir()
    folder = root if set_name == "agent_decoder" else root / set_name
    return folder / f"decoder_{arm}.jsonl.gz"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    counts = []
    for set_name in SETS:
        folder = paths.DATA / set_name
        if not folder.is_dir():
            continue
        for table in sorted(folder.glob("*.parquet")):
            if table.stem.endswith(("_failure_modes", "_taxonomy")):
                continue  # outputs of this script and of scripts/legitimacy.py
            if pd.read_parquet(table).empty:
                continue  # an arm whose every row was set aside for a rerun
            arm = table.stem
            archive = archive_of(set_name, arm)
            modes = analyze_decoder(table, archive if archive.is_file() else None)
            taxonomy.analyze_arm(table, archive if archive.is_file() else None)
            if archive.is_file():
                transcripts.render_archive(archive, table)
            leaves = modes.leaf.value_counts().to_dict()
            verdicts = modes.verdict_rel.value_counts().to_dict()
            counts.append(
                dict(set=set_name, arm=arm, n=len(modes), leaves=leaves, verdicts=verdicts)
            )
            print(f"{set_name}/{arm}: {len(modes)} episodes, leaves {leaves}, verdicts {verdicts}")
    if args.summary:
        rows = [
            dict(set=c["set"], arm=c["arm"], n=c["n"],
                 leaves=", ".join(f"{k} {v}" for k, v in sorted(c["leaves"].items())),
                 verdicts=", ".join(f"{k} {v}" for k, v in sorted(c["verdicts"].items())))
            for c in counts
        ]  # fmt: skip
        df = pd.DataFrame(rows)
        print("\n| set | arm | n | leaves | verdicts (relative rule) |\n|---|---|---|---|---|")
        for _, r in df.iterrows():
            print(f"| {r['set']} | {r['arm']} | {r['n']} | {r['leaves']} | {r['verdicts']} |")


if __name__ == "__main__":
    main()
