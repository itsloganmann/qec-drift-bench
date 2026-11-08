from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "judge_transcripts.py"
SPEC = importlib.util.spec_from_file_location("judge_transcripts", SCRIPT)
judge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(judge)


def test_report_discloses_partial_coverage_and_identity_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(judge, "DATA", tmp_path)
    monkeypatch.setattr(
        judge, "episodes", lambda: [("arm", task, task, None, {}) for task in ("a", "b")]
    )
    monkeypatch.setattr(
        judge,
        "judged",
        lambda: [
            dict(
                arm="arm",
                task="a",
                key="a",
                label="passed",
                cause="passed",
                environment_problem=False,
                instruction_problem=False,
                integrity_problem=False,
                task_fair="fair",
            )
        ],
    )
    pd.DataFrame([dict(arm="arm", task="a", label="passed")]).to_parquet(
        tmp_path / "arm_taxonomy.parquet"
    )
    rendered = judge.report()
    assert "1 of 2 current episodes with archived transcripts" in rendered
    assert "paths can reveal model and effort" in rendered
    assert "not fully blinded" in rendered
    assert "blinded to the agent's model" not in rendered
