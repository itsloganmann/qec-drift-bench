"""The Codex scaffold: a fake CLI streams JSONL and writes the files; the shared harness scores."""

from __future__ import annotations

import json
import stat

import pytest

from qec_drift.agent import decoder_run_cc as cc
from qec_drift.agent import decoder_run_codex as cx
from qec_drift.agent import decoder_task as dt
from tests.test_decoder_run_cc import DECODER


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(dt, "SHOTS", {"train": 3000, "val": 500, "deploy": 500, "test": 20000})


FAKE_AUTH = {
    "auth_mode": "chatgpt",
    "OPENAI_API_KEY": None,
    "tokens": {"id_token": "i", "access_token": "a", "refresh_token": "r", "account_id": "acc"},
    "last_refresh": "2026-11-02T00:00:00Z",
}


def fake_codex(tmp_path, report: dict | None):
    """A stand-in for `codex exec`: goes to the -C folder, writes the files, streams events."""
    events = [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "item_0", "type": "error", "message": "note"}},
        {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/bin/zsh -lc 'python -c \"print(1)\"'",
                "aggregated_output": "1\n",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": "ok"}},
        {"type": "turn.completed", "usage": {"input_tokens": 30, "output_tokens": 7}},
    ]
    script = tmp_path / "codex"
    body = '#!/bin/bash\nwhile [ $# -gt 1 ]; do if [ "$1" = -C ]; then cd "$2"; fi; shift; done\n'
    body += f"cat > decoder.py <<'PY'\n{DECODER}PY\n"
    if report is not None:
        body += f"cat > report.json <<'J'\n{json.dumps(report)}\nJ\n"
    body += "cat <<'STREAM'\n" + "\n".join(json.dumps(e) for e in events) + "\nSTREAM\n"
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_the_codex_scaffold_scores_through_the_shared_harness(small, tmp_path, monkeypatch):
    monkeypatch.setattr(cx, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(cx, "login", lambda: FAKE_AUTH)
    task = dt.Task(5, "none", "bq15")
    report = {
        "model_adequate": False,
        "confidence": 80,
        "scope": "local",
        "changed_qubits": sorted(task.truth.qubits),
        "mechanism": "all",
        "stationary": True,
    }
    monkeypatch.setattr(cx, "CODEX", fake_codex(tmp_path, report))
    row, traj = cc.run_episode(task, "gpt-test", "high", tmp_path / "work", 1.0, cx.BACKEND)
    assert row["outcome"] == "submitted" and row["turns"] == 1 and row["tokens_in"] == 30
    assert row["stop"] == "completed" and row["cost_usd"] == 0.0 and row["diagnosis_correct"]
    assert row["uses_correlations"] and row["agree_nominal_corr"] == 1.0
    assert traj["scaffold"] == "codex" and traj["trace_kind"] == "codex_stream"
    assert traj["effort"] == "high" and len(traj["events"]) == 6
    seen = traj["workdir"].rsplit("/", 1)[1]  # a random folder name, not the task's
    assert seen.startswith("ep-") and task.name not in traj["workdir"]
    episode = tmp_path / "cfg" / "episodes" / f"{cc.EPISODE_TAG}--{seen}"
    assert episode.is_dir() and not (episode / "auth.json").exists()
    cmd = cx.command(tmp_path, tmp_path / "cfg", "gpt-test", "high")
    assert cmd[0] == "sandbox-exec" and "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "computer_use" in cmd and 'model_reasoning_effort="high"' in cmd
    assert cmd[-1] == cc.prompt() and "--ignore-user-config" in cmd


def test_the_codex_state_dir_keeps_the_login_without_its_refresh_token(tmp_path):
    cx.prepare_config_dir(tmp_path / "cfg", FAKE_AUTH)
    saved = json.loads((tmp_path / "cfg" / "auth.json").read_text())
    assert saved["tokens"] == {
        "id_token": "i",
        "access_token": "a",
        "refresh_token": "",
        "account_id": "acc",
    }
    assert saved["auth_mode"] == "chatgpt"
    assert (tmp_path / "cfg" / "auth.json").stat().st_mode & 0o777 == 0o600
    env = cx.environment(tmp_path / "cfg")
    assert env["CODEX_HOME"] == str(tmp_path / "cfg") and env["ZDOTDIR"] == str(tmp_path / "cfg")
    assert "OPENAI_API_KEY" not in env and "CODEX_API_KEY" not in env
    prof = cx.command(tmp_path, tmp_path / "cfg", "m", None)[2]
    assert ".codex" in prof and prof.index("packages") > prof.index(".codex")  # install reopened
    assert "code_mode_host" not in cx.OFF and env["CODEX_CODE_MODE_HOST_PATH"].endswith("host")
    assert ".agents" in prof


def test_tool_calls_are_counted_per_line_and_capped(tmp_path):
    from qec_drift.agent import isolation

    assert cx.tool_starts('{"type":"item.started","item":{"type":"command_execution"}}') == 1
    assert cx.tool_starts('{"type":"item.completed","item":{"type":"command_execution"}}') == 0
    assert cx.tool_starts('{"type":"item.started","item":{"type":"reasoning"}}') == 0
    two = '{"type":"assistant","message":{"content":[{"type":"tool_use"},{"type":"tool_use"}]}}'
    assert cc.tool_starts(two) == 2 and cc.tool_starts('{"type":"user"}') == 0
    script = tmp_path / "chatty"
    body = "#!/bin/bash\nfor i in $(seq 1 50); do echo '" + two + "'; sleep 0.05; done\n"
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    login = tmp_path / "login"
    login.write_text("x")
    events, code = isolation.stream(
        [str(script)], tmp_path, {"PATH": "/usr/bin:/bin"}, login, lambda _: True,
        tools=cc.tool_starts, max_tools=10,
    )  # fmt: skip
    assert any("tool-call limit" in str(e.get("note")) for e in events) and code != 0
    assert (
        10 < sum(cc.tool_starts(json.dumps(e)) for e in events if e.get("type") == "assistant") < 50
    )


def test_the_benchmark_install_record_is_hidden_and_python_still_runs(tmp_path):
    import shlex
    import subprocess

    from qec_drift.agent import isolation

    own = isolation.own_install()
    assert any(p.name.endswith(".dist-info") for p in own) and any(p.suffix == ".pth" for p in own)
    work, cfg = tmp_path / "w", tmp_path / "c"
    work.mkdir()
    cfg.mkdir()
    prof = isolation.profile(work, cfg, cfg, cfg / "login.json")
    meta = next(p for p in own if p.name.endswith(".dist-info")) / "METADATA"
    py = shlex.quote(str(cc.paths.REPO_ROOT / ".venv" / "bin" / "python"))
    test = f"cat {shlex.quote(str(meta))}; {py} -c 'import stim, pymatching; print(\"ok\")'"
    r = subprocess.run(["sandbox-exec", "-p", prof, "/bin/zsh", "-c", test], cwd=work,
                       capture_output=True, text=True, timeout=120)  # fmt: skip
    assert "Operation not permitted" in r.stderr and "QEC-Drift" not in r.stdout
    assert r.stdout.strip().endswith("ok")


def test_a_refused_group_kill_at_the_cap_still_ends_the_episode(tmp_path, monkeypatch):
    from qec_drift.agent import isolation

    def refuse(pid, sig):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(isolation.os, "killpg", refuse)
    two = '{"type":"assistant","message":{"content":[{"type":"tool_use"},{"type":"tool_use"}]}}'
    script = tmp_path / "chatty"
    loop = "for i in $(seq 1 50); do echo '" + two + "'; sleep 0.05; done\n"
    script.write_text("#!/bin/bash\n" + loop)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    login = tmp_path / "login"
    login.write_text("x")
    events, code = isolation.stream(
        [str(script)], tmp_path, {"PATH": "/usr/bin:/bin"}, login, lambda _: True,
        tools=cc.tool_starts, max_tools=10,
    )  # fmt: skip
    assert any("tool-call limit" in str(e.get("note")) for e in events) and code != 0


def test_a_failed_turn_with_a_limit_message_is_a_throttle():
    refused = [
        {"type": "turn.started"},
        {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}},
    ]
    assert cx.summary(refused, 1) == dict(
        stop="failed", tokens_in=0, tokens_out=0, cost_usd=0.0, throttled=True
    )
    done = [{"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 2}}]
    assert cx.summary(done, 0)["stop"] == "completed" and not cx.summary(done, 0)["throttled"]
    assert cx.summary(done, 0)["tokens_out"] == 2
    assert cx.replied('{"type": "thread.started", "thread_id": "t"}')
    assert not cx.replied('{"type":"item.completed","item":{"type":"command_execution"}}')
    assert not cx.replied('{"type":"turn.started"}')


def test_transcripts_render_every_archive_shape(tmp_path):
    import gzip

    from qec_drift.agent import transcripts

    codex = dict(
        task="d5-none",
        model="gpt-test",
        effort="high",
        scaffold="codex",
        trace_kind="codex_stream",
        prompt="Do the task.",
        events=[
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Looking."}},
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "ls",
                    "aggregated_output": "a\nb",
                    "exit_code": 0,
                },
            },
            {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 2}},
        ],
        decoder_src="def decode(det):\n    return det[:, :1]\n",
        report={"model_adequate": True},
    )
    claude = dict(
        task="d5-none-s1",
        model="claude-test",
        effort=None,
        scaffold="claude-code",
        trace_kind="claude_code_stream",
        prompt="Do the task.",
        events=[
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "I will look."},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}},
                    ]
                },
            },
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "content": "x" * 5000}]},
            },
            {"type": "result", "subtype": "success", "total_cost_usd": 1.5},
        ],
        decoder_src="",
        report=None,
    )
    api = dict(
        task="d5-none-s2",
        model="claude-test",
        effort="high",
        trace_kind="api",
        messages=[
            {"role": "user", "content": "Do the task."},
            {
                "role": "assistant",
                "body": json.dumps(
                    {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "run_python",
                                "input": {"code": "print(1)"},
                            }
                        ]
                    }
                ),
            },
            {"role": "tool", "content": "1\n"},
        ],
        decoder_src="x = 1",
    )
    archive = tmp_path / "decoder_test_arm.jsonl.gz"
    with gzip.open(archive, "wt") as f:
        for rec in (codex, claude, api):
            f.write(json.dumps(rec) + "\n")
    folder = transcripts.render_archive(archive)
    assert folder == tmp_path / "test_arm" and (folder / "README.md").exists()
    text = (folder / "d5-none.md").read_text()
    assert "```sh\nls\n```" in text and "Result (exit 0)" in text and "def decode" in text
    assert "model_adequate" in text and "<details><summary>Prompt</summary>" in text
    text = (folder / "d5-none-s1.md").read_text()
    assert "ls -la" in text and "more characters cut" in text and "CLI cost estimate $1.50" in text
    text = (folder / "d5-none-s2.md").read_text()
    assert "print(1)" in text and "x = 1" in text
    # members written one by one, the last one cut short: the first two still render
    broken = tmp_path / "decoder_broken.jsonl.gz"
    members = [gzip.compress((json.dumps(r) + "\n").encode()) for r in (codex, claude, api)]
    broken.write_bytes(members[0] + members[1] + members[2][: len(members[2]) // 2])
    assert [r["task"] for r in transcripts.records(broken)] == ["d5-none", "d5-none-s1"]


def test_a_login_zsh_in_the_episode_environment_finds_the_venv_python(tmp_path):
    import subprocess

    from qec_drift.agent import isolation

    cfg = isolation.fresh_dir(tmp_path / "cfg")
    out = subprocess.run(
        ["/bin/zsh", "-lc", "command -v python3; python3 -c 'import stim, pymatching'"],
        env=isolation.environment(cfg),
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines()[0].startswith(str(isolation.paths.REPO_ROOT / ".venv"))


def test_a_thinking_cli_is_not_killed_and_a_silent_one_is(tmp_path, monkeypatch):
    from qec_drift.agent import isolation

    monkeypatch.setattr(isolation, "LOGIN_SECONDS", 0.5)
    login = tmp_path / "login"
    for name, body, killed in (
        ("thinking", 'echo \'{"type":"system"}\'; sleep 1.5; echo \'{"type":"result"}\'', False),
        ("silent", "sleep 3", True),
    ):
        if login.exists():
            login.chmod(0o600)  # the previous pass locked it
        login.write_text("x")
        script = tmp_path / name
        script.write_text("#!/bin/bash\n" + body + "\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        events, code = isolation.stream(
            [str(script)], tmp_path, {"PATH": "/usr/bin:/bin"}, login, lambda _: False
        )
        notes = [e.get("note") for e in events if e.get("type") == "harness"]
        assert (notes == ["the CLI did not start in time"]) is killed, (name, notes)
        assert login.stat().st_mode & 0o777 == 0  # locked either way


def test_a_here_document_works_in_the_sandboxed_episode_shell(tmp_path):
    import subprocess

    from qec_drift.agent import isolation

    work, cfg = tmp_path / "work", isolation.fresh_dir(tmp_path / "cfg")
    work.mkdir()
    login = cfg / "login"
    login.write_text("x")
    prof = isolation.profile(work, cfg, tmp_path / "cfg", login)
    out = subprocess.run(
        ["sandbox-exec", "-p", prof, "/bin/zsh", "-lc", "cat <<EOF\nheredoc ok\nEOF"],
        cwd=work,
        env=isolation.environment(cfg),
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.stdout.strip() == "heredoc ok", out.stderr
