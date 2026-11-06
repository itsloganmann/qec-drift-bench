"""The launch score table on an arm with no scored episode yet: every row a harness error."""

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "launch_scores.py"
SPEC = importlib.util.spec_from_file_location("launch_scores", SCRIPT)
ls = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ls)


def test_unscored_arm_counts_every_row_as_a_failure(tmp_path):
    # Error rows carry no passed, diagnosis_correct or ref_* column: the scorer never ran.
    rows = pd.DataFrame(
        {
            "task": ["d5-none-s6", "d9-none"],
            "adequate_truth": [False, True],
            "outcome": ["error", "error"],
            "stop": [None, None],
            "turns": [0, 0],
            "gap_closed": [float("nan")] * 2,
            "gap_drift": [float("nan")] * 2,
            "report_scope": [None, None],
            "seconds": [1800, 1700],
            "cost_usd": [0.0, 0.0],
        }
    )
    path = tmp_path / "gpt_6_astra_medium_codex.parquet"
    rows.to_parquet(path)
    df = ls.scored(path)
    assert not df.passed.any()
    assert not df.pass_rel.any()
    row = ls.arm_row(path.stem, df)
    assert row["errors"] == 2
    assert row["absolute"] == "0 (0%)"
    assert row["diagnosis"] == "0%"
