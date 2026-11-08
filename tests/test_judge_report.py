from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "judge_transcripts.py"
SPEC = importlib.util.spec_from_file_location("judge_transcripts", SCRIPT)
judge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(judge)


@pytest.mark.parametrize("current_review", [False, True])
def test_report_separates_current_legacy_and_missing_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, current_review: bool
) -> None:
    monkeypatch.setattr(judge, "DATA", tmp_path)
    rows = pd.DataFrame([dict(task=t, rule_label="passed") for t in ("a", "b", "missing")])
    rows = rows.set_index("task", drop=False)
    monkeypatch.setattr(judge, "valid_tables", lambda: [(tmp_path / "arm.parquet", rows)])
    monkeypatch.setattr(judge, "episodes", lambda _: [("arm", t, t, "payload") for t in ("a", "b")])
    verdict = dict(
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
    saved = [verdict]  # A matching old key must not be reused under the current protocol.
    if current_review:
        saved.append(verdict | dict(protocol=judge.PROTOCOL))
    monkeypatch.setattr(judge, "judged", lambda: saved)
    pd.DataFrame([dict(arm="arm", task="a", label="passed")]).to_parquet(
        tmp_path / "arm_taxonomy.parquet"
    )
    rendered = judge.report()
    assert f"{int(current_review)} of 2 current episodes with archived transcripts" in rendered
    assert "3 valid scored rows; 1 missing transcripts" in rendered
    assert f"{2 - int(current_review)} awaiting current review" in rendered
    assert "1 saved judgments use older protocols and are excluded" in rendered
    assert "`arm` / `missing`" in rendered
    assert "not complete blinding" in rendered
    assert "blinded to the agent's model" not in rendered
    if current_review:
        assert "on 100% of the current judgments" in rendered
    else:
        assert "No judgments under the current protocol yet" in rendered
        assert "100%" not in rendered
