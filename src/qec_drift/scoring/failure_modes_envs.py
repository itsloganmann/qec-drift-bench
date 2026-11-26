"""Failure modes for the data-out tasks (envs/): one leaf per episode.

The gates are exclusive and exhaustive. Each episode takes the first that applies, on its paper
seed instances (envs_grade.py):
    E0 the episode never ran (a harness error, a refused subscription) -> harness_error
    E1 solution.py missing or still the starter                     -> no_solution
    E2 at least half of the answers invalid (shape, time, crash)    -> invalid_answer
    E3 "changed" on no instance                                     -> never_changed
    E4 "changed" on every instance                                  -> always_changed
    E5 more than SHARE of the controls called "changed"             -> false_alarms
    E6 more than SHARE of the changes called "unchanged"            -> misses
    E7 more than SHARE of the found changes with diagnosis < 0.5    -> diagnosis_short
    E8 more than SHARE of the graded fixes below PASS_GAP           -> fix_short
    E9 none of the above                                            -> sound

E3 and E4 are the guesses that the tasks' lazy checks (envs/<task>/checks/) show score at or
below the trivial floor. The leaf says how an episode fails; its pass_rate says how often.

Example:
    uv run python -m qec_drift.scoring.failure_modes_envs data/envs_hard/opus_5_5_cc.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from qec_drift.agent.awareness import PASS_GAP

SHARE = 0.25
LEAVES = (
    "harness_error", "no_solution", "invalid_answer", "never_changed", "always_changed",
    "false_alarms", "misses", "diagnosis_short", "fix_short", "sound",
)  # fmt: skip


def _share(mask: pd.Series) -> float:
    return float(mask.mean()) if len(mask) else 0.0


def leaf(episode: dict, rows: pd.DataFrame) -> str:
    """The first gate that applies to one episode, given its paper-seed instance rows."""
    if episode["outcome"] == "error":
        return "harness_error"
    if episode["outcome"] == "no_solution" or rows.empty:
        return "no_solution"
    if _share(rows["error"]) >= 0.5:
        return "invalid_answer"
    rows = rows[~rows["error"]]
    said = rows["said"].fillna(False).astype(bool)
    if not said.any():
        return "never_changed"
    if said.all():
        return "always_changed"
    changed = rows["truth_changed"].astype(bool)
    if _share(said[~changed]) > SHARE:
        return "false_alarms"
    if _share(~said[changed]) > SHARE:
        return "misses"
    found = rows[changed & said]
    if _share(found["diag"].dropna() < 0.5) > SHARE:
        return "diagnosis_short"
    if _share(found["fix"].dropna() < PASS_GAP) > SHARE:
        return "fix_short"
    return "sound"


def analyze_envs(table: Path) -> pd.DataFrame:
    """Write <arm>_failure_modes.parquet next to the arm table, one leaf per episode."""
    df = pd.read_parquet(table)
    inst_path = table.with_name(f"{table.stem}_instances.parquet")
    inst = pd.read_parquet(inst_path) if inst_path.exists() else pd.DataFrame()
    out = []
    for ep in df.to_dict("records"):
        rows = (
            inst[(inst["task"] == ep["env"]) & (inst["rollout"] == ep["rollout"])
                 & (inst["seed"] != "public")]
            if not inst.empty else inst
        )  # fmt: skip
        out.append(
            dict(
                task=ep["task"],
                env=ep["env"],
                rollout=ep["rollout"],
                model=ep["model"],
                leaf=leaf(ep, rows),
                pass_rate=ep.get("pass_rate"),
            )
        )
    res = pd.DataFrame(out)
    res.to_parquet(table.with_name(f"{table.stem}_failure_modes.parquet"), index=False)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("tables", nargs="+", type=Path)
    for table in ap.parse_args().tables:
        print(analyze_envs(table).to_string(index=False))


if __name__ == "__main__":
    main()
