"""The Claude Code scaffold: a fake CLI writes the decoder and the report; the harness scores."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from qec_drift.agent import decoder_run_cc as cc
from qec_drift.agent import decoder_task as dt
from qec_drift.scoring import failure_modes_decoder as fm


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(dt, "SHOTS", {"train": 3000, "val": 500, "deploy": 500, "test": 20000})


DECODER = (
    "import numpy as np, pymatching, stim\n"
    "c = stim.Circuit(open('nominal.stim').read())\n"
    "dem = c.detector_error_model(decompose_errors=True)\n"
    "m = pymatching.Matching.from_detector_error_model(dem, enable_correlations=True)\n"
    "def decode(det):\n    return m.decode_batch(det, enable_correlations=True)\n"
)


def fake_cli(tmp_path, report: dict | None):
    """A stand-in for `claude -p`: emits a stream, writes decoder.py and maybe report.json."""
    lines = [
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {"file_path": "decoder.py", "content": "x = 1"},
                        },
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "python -c 'print(1)'"},
                        },
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "terminal_reason": "completed",
                "total_cost_usd": 0.42,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        ),
    ]
    script = tmp_path / "claude"
    body = "#!/bin/bash\n" + f"cat > decoder.py <<'PY'\n{DECODER}PY\n"
    body += 'pwd > seen.txt; env >> seen.txt; echo "$@" >> seen.txt\n'  # what the agent sees
    if report is not None:
        body += f"cat > report.json <<'J'\n{json.dumps(report)}\nJ\n"
    body += "cat <<'STREAM'\n" + "\n".join(lines) + "\nSTREAM\n"
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


FAKE_LOGIN = {"claudeAiOauth": {"accessToken": "x", "refreshToken": "r"}, "mcpOAuth": {}}


def test_the_cc_scaffold_scores_the_decoder_and_the_report(small, tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(cc, "keychain_credential", lambda: FAKE_LOGIN)
    task = dt.Task(5, "none", "bq15")
    report = {
        "model_adequate": False,
        "confidence": 85,
        "scope": "local",
        "changed_qubits": sorted(task.truth.qubits),
        "mechanism": "all",
        "stationary": True,
    }
    monkeypatch.setattr(cc, "CLAUDE", fake_cli(tmp_path, report))
    row, traj = cc.run_episode(task, "claude-test", None, tmp_path / "work", 1.0)
    assert row["outcome"] == "submitted" and row["turns"] == 2 and row["cost_usd"] == 0.42
    assert row["stop"] == "completed" and row["uses_correlations"]
    assert row["diagnosis_correct"] and row["localization"] == 1.0
    assert row["agree_nominal_corr"] == 1.0 and 0 <= row["gap_closed"] <= 1.1
    assert traj["trace_kind"] == "claude_code_stream" and len(traj["events"]) == 3
    seen = Path(traj["workdir"])  # a random folder: the task name says what is wrong
    final = tmp_path / "work" / task.name
    assert seen.name.startswith("ep-") and not seen.exists() and (final / "decoder.py").is_file()
    assert task.name not in (final / "seen.txt").read_text()  # not in the path, env or args
    episode_dir = tmp_path / "cfg" / "episodes" / f"{cc.EPISODE_TAG}--{seen.name}"
    assert episode_dir.is_dir()  # tagged with the arm (the pid outside run_arm)
    env = cc.environment(episode_dir)
    assert "ANTHROPIC_API_KEY" not in env and env["CLAUDE_CONFIG_DIR"] == str(episode_dir)
    assert env["PATH"].startswith(str(cc.paths.REPO_ROOT / ".venv" / "bin"))
    prof = cc.profile(tmp_path, episode_dir)
    assert ".claude" in prof and "deny file-read*" in prof and str(tmp_path) in prof
    assert "/private/tmp/claude-" not in prof  # the CLI's scratch tree lives in the episode dir
    assert ".qec-drift-codex" in prof and ".qec-drift-claude" in prof  # both state roots hidden
    assert f'(literal "{episode_dir.parent.resolve()}")' in prof.split("file-read-metadata")[1]
    assert f'(literal "{tmp_path.resolve().parent}")' in prof.split("file-read-metadata")[1]
    assert env["CLAUDE_CODE_TMPDIR"] == str(episode_dir / "tmp")
    assert not (episode_dir / ".credentials.json").exists()  # removed after the episode
    assert "report.json" in cc.prompt() and "run_python" not in cc.prompt()


def test_a_missing_report_counts_as_adequate_and_the_adapter_reads_the_stream(
    small, tmp_path, monkeypatch
):
    task = dt.Task(5, "none", "")
    monkeypatch.setattr(cc, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(cc, "keychain_credential", lambda: FAKE_LOGIN)
    monkeypatch.setattr(cc, "CLAUDE", fake_cli(tmp_path, None))
    row, traj = cc.run_episode(task, "claude-test", None, tmp_path / "work", 1.0)
    assert row["reported"] is False and row["report_adequate"] is True
    assert (
        row["diagnosis_correct"] and row["passed"]
    )  # correlated nominal matching on an adequate task
    import gzip

    path = tmp_path / "t.jsonl.gz"
    with gzip.open(path, "wt") as f:
        f.write(json.dumps(traj) + "\n")
    code = fm.agent_code(path)
    assert "python -c" in code[task.name] and "x = 1" in code[task.name]


def test_the_config_dir_keeps_only_the_claude_ai_access_token(tmp_path):
    cc.prepare_config_dir(tmp_path / "cfg", FAKE_LOGIN)
    saved = json.loads((tmp_path / "cfg" / ".credentials.json").read_text())
    assert saved == {"claudeAiOauth": {"accessToken": "x"}}  # no refresh token, no MCP logins
    assert (tmp_path / "cfg" / ".credentials.json").stat().st_mode & 0o777 == 0o600
    assert json.loads((tmp_path / "cfg" / "settings.json").read_text()) == {
        "hooks": {},
        "enabledPlugins": {},
    }
    cc.lock_credential(tmp_path / "cfg")
    assert (tmp_path / "cfg" / ".credentials.json").stat().st_mode & 0o777 == 0
    assert "file-write-mode" in cc.profile(tmp_path, tmp_path / "cfg")
    cc.remove_credential(tmp_path / "cfg")
    assert not (tmp_path / "cfg" / ".credentials.json").exists()


def test_a_limit_message_with_no_tool_calls_is_a_throttle_and_the_episode_is_tried_again(
    small, tmp_path, monkeypatch
):
    monkeypatch.setattr(cc, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(cc, "keychain_credential", lambda: FAKE_LOGIN)
    monkeypatch.setattr(cc, "THROTTLE_WAIT", 0)
    good = fake_cli(tmp_path, None)
    refused = {
        "type": "result",
        "subtype": "error_during_execution",
        "is_error": True,
        "result": "Usage limit reached. Resets at 3pm.",
    }
    assert cc.summary([refused], 1)["throttled"]
    assert not cc.summary([refused | {"is_error": False}], 0)["throttled"]
    flag = tmp_path / "refused-once"
    script = tmp_path / "claude-limit"
    script.write_text(
        "#!/bin/bash\n"
        f"if [ ! -e '{flag}' ]; then touch '{flag}'; echo '{json.dumps(refused)}'; exit 1; fi\n"
        f"exec '{good}'\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(cc, "CLAUDE", script)
    task = dt.Task(5, "none", "")
    row, traj = cc.safe_episode(task, "claude-test", None, tmp_path / "work", 1.0)
    assert flag.exists() and row["outcome"] == "submitted" and row["turns"] == 2
    assert len(traj["events"]) == 3  # the refused attempt is not the trajectory
