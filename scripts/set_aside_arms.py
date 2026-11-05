"""Set aside whole arms of the v2 grid after a defect that touched every episode.

    uv run python scripts/set_aside_arms.py name_leak     # every arm of data/agent_launch2

On 2026-11-03 the task folder an agent worked in was named after its task, and a task name
says what is wrong (`d5-none-dwander30d30-s6`: a wandering fault). Every episode until then
could read it, so every row is set aside and rerun in folders with random names.

For each arm, its table and the tables derived from it move to data/agent_launch2/<reason>/,
and its trajectory archive and rendered pages to trajectories/agent_launch2/<reason>/, kept for
the record. With no table left, scripts/run_grid.py runs the arm from the start; with no
archive left, the new archive holds only the new episodes.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "agent_launch2"
TRAJ = ROOT / "trajectories" / "agent_launch2"
DERIVED = ("_failure_modes", "_taxonomy")


def move(src: Path, folder: Path) -> None:
    if src.exists():
        folder.mkdir(parents=True, exist_ok=True)
        if (folder / src.name).exists():
            raise SystemExit(f"refusing: {folder / src.name} exists")
        shutil.move(src, folder / src.name)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("reason", help="folder name for the set-aside rows, e.g. name_leak")
    args = ap.parse_args()
    arms = sorted(p.stem for p in DATA.glob("*.parquet") if not p.stem.endswith(DERIVED))
    for arm in arms:
        for suffix in ("", *DERIVED):
            move(DATA / f"{arm}{suffix}.parquet", DATA / args.reason)
        move(TRAJ / f"decoder_{arm}.jsonl.gz", TRAJ / args.reason)
        move(TRAJ / arm, TRAJ / args.reason)
        print(f"{arm}: set aside")


if __name__ == "__main__":
    main()
