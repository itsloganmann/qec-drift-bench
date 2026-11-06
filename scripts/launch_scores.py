"""Pass rates of the arms of a launch set under both rules, per arm and as one grid table.

    uv run python scripts/launch_scores.py data/agent_launch2              # every arm there
    uv run python scripts/launch_scores.py data/agent_launch/opus_5_5_medium_cc.parquet --tasks

Absolute rule: diagnosis correct, gap_closed >= 0.5 and, on a drift task, gap_drift >= 0.5.
Relative rule (the headline): also gap_drift >= 0.75 of what the honest adaptive decoder
recovers on that task. Error rows (no episode) count as failures and are reported apart.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

RELATIVE = 0.75
COLUMNS = [
    "task",
    "turns",
    "gap_closed",
    "gap_drift",
    "honest",
    "report_scope",
    "localization",
    "diagnosis_correct",
    "passed",
    "pass_rel",
    "cost_usd",
]


def scored(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    for col in (
        "ref_stale_corr",
        "ref_true_corr",
        "ref_adaptive_corr",
        "ref_pij_corr",
        "gap_drift",
        "passed",
        "diagnosis_correct",
    ):
        if col not in df.columns:  # only adequate tasks so far, or no scored episode yet
            df[col] = float("nan")
    span = df.ref_stale_corr - df.ref_true_corr
    known = df.ref_adaptive_corr.fillna(df.ref_pij_corr)  # stationary faults: the refit
    df["honest"] = (df.ref_stale_corr - known) / span
    df["passed"] = df.passed.fillna(False).astype(bool)
    no_drift = df.gap_drift != df.gap_drift
    df["pass_rel"] = df.passed & (no_drift | (df.gap_drift >= RELATIVE * df.honest))
    return df


def arm_row(name: str, df: pd.DataFrame) -> dict:
    drift = df[~df.adequate_truth]
    return dict(
        arm=name,
        tasks=len(df),
        errors=int((df.outcome == "error").sum()),
        absolute=f"{int(df.passed.sum())} ({df.passed.mean():.0%})",
        relative=f"{int(df.pass_rel.sum())} ({df.pass_rel.mean():.0%})",
        diagnosis=f"{df.diagnosis_correct.fillna(False).mean():.0%}",
        median_gap_drift=round(float(drift.gap_drift.median()), 2) if len(drift) else float("nan"),
        moving_said=int((drift.report_scope == "moving").sum()),
        seconds=int(df.seconds.median()) if "seconds" in df else 0,
        cost=round(float(df.cost_usd.sum()), 2),
        _rel=float(df.pass_rel.mean()),
        _abs=float(df.passed.mean()),
    )


def markdown(table: pd.DataFrame) -> str:
    cols = list(table.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for _, r in table.iterrows()]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("paths", nargs="+", type=Path, help="arm parquet files or folders of them")
    ap.add_argument("--tasks", action="store_true", help="print every task of every arm")
    args = ap.parse_args()
    files: list[Path] = []
    for p in args.paths:
        if p.is_dir():
            files += sorted(
                q for q in p.glob("*.parquet") if not q.name.endswith("_failure_modes.parquet")
            )
        else:
            files.append(p)
    pd.set_option("display.width", 220)
    rows = []
    for path in files:
        df = scored(path)
        if args.tasks:
            print(f"== {path}")
            print(df[[c for c in COLUMNS if c in df.columns]].round(2).to_string(index=False))
        rows.append(arm_row(path.stem, df))
    table = pd.DataFrame(rows).sort_values(["_rel", "_abs"], ascending=False)
    print(markdown(table.drop(columns=["_rel", "_abs"])))


if __name__ == "__main__":
    main()
