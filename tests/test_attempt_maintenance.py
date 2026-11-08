from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from qec_drift.agent import attempts, transcripts


def script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"attempt_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("commit_defect", [False, True])
def test_set_aside_uses_only_committed_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_defect: bool
) -> None:
    module = script("set_aside_env_rows")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    data, traces = tmp_path / "data" / "agent_launch2", tmp_path / "trajectories" / "agent_launch2"
    data.mkdir(parents=True)
    traces.mkdir(parents=True)
    table, archive = data / "arm_codex.parquet", traces / "decoder_arm_codex.jsonl.gz"
    row = dict(task="t", outcome="submitted", turns=1, stop="completed")
    rec = dict(task="t", events=[])
    with archive.open("ab") as stream:
        healthy = attempts.append_attempt(stream, row, rec, "arm_codex")
        attempts.write_table(table, [healthy])
        bad = rec | {
            "events": [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "aggregated_output": "No module named 'stim'",
                    },
                }
            ]
        }
        defect = attempts.append_attempt(stream, row, bad, "arm_codex")
    if commit_defect:
        attempts.write_table(table, [defect])
    archive_before = archive.read_bytes()
    module.main()
    saved = pd.read_parquet(table)
    if commit_defect:
        assert saved.empty and "task" in saved.columns
        backup = pd.read_parquet(data / "env_defect" / table.name)
        assert backup.iloc[0].attempt_id == defect["attempt_id"]
    else:
        assert saved.iloc[0].attempt_id == healthy["attempt_id"]
        assert not (data / "env_defect" / table.name).exists()
    assert archive.read_bytes() == archive_before
    assert len(list(transcripts.records(archive))) == 2


@pytest.mark.parametrize("name", ["rescore_agreement", "rescore_diagnosis"])
def test_legacy_rescoring_refuses_identified_rows_before_doing_work(
    tmp_path: Path, name: str
) -> None:
    table = tmp_path / "arm.parquet"
    attempts.write_table(table, [{"task": "t", "attempt_id": "committed"}])
    before = table.read_bytes()
    with pytest.raises(ValueError, match="cannot modify identified attempts"):
        script(name).main(table)
    assert table.read_bytes() == before
