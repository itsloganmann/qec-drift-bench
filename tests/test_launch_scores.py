"""The launch score table on an arm with no scored episode yet: every row a harness error."""

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "launch_scores.py"
SPEC = importlib.util.spec_from_file_location("launch_scores", SCRIPT)
ls = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ls)


def test_unscored_arm_has_no_capability_rate(tmp_path: Path) -> None:
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
    assert row["tasks"] == 0
    assert row["absolute"] == "0 (n/a)"
    assert row["diagnosis"] == "n/a"


def test_interrupted_attempt_preserves_cost_without_lowering_pass_rate(tmp_path: Path) -> None:
    path = tmp_path / "test.parquet"
    pd.DataFrame(
        {
            "task": ["valid", "interrupted"],
            "adequate_truth": [True, True],
            "outcome": ["submitted", "error"],
            "provider_interrupted": [False, True],
            "passed": [True, False],
            "diagnosis_correct": [True, False],
            "report_scope": ["adequate", None],
            "seconds": [10, 20],
            "cost_usd": [1.0, 2.0],
        }
    ).to_parquet(path)
    row = ls.arm_row(path.stem, ls.scored(path))
    assert row["tasks"] == 1 and row["errors"] == 1
    assert row["absolute"] == "1 (100%)"
    assert row["relative"] == "1 (100%)"
    assert row["diagnosis"] == "100%"
    assert row["cost"] == 3.0
