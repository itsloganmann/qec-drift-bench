from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "usage", Path(__file__).resolve().parents[1] / "scripts" / "usage.py"
)
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)


@pytest.mark.parametrize("failed", ["claude", "codex"])
def test_provider_failure_preserves_other_usage_and_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture, failed: str
) -> None:
    log = tmp_path / "usage.jsonl"
    log.write_text('{"previous": true}\n')
    monkeypatch.setattr(usage, "LOG", log)
    called = []

    def claude() -> dict:
        called.append("claude")
        if failed == "claude":
            raise ValueError("secret must not appear")
        return {"weekly_all": {"percent": 91}, "weekly_scoped": {"percent": 80}}

    def codex() -> dict:
        called.append("codex")
        if failed == "codex":
            raise OSError("secret must not appear")
        return {"plan-type": "prolite", "primary-used-percent": "72"}

    monkeypatch.setattr(usage, "claude", claude)
    monkeypatch.setattr(usage, "codex", codex)
    usage.main()
    lines = log.read_text().splitlines()
    assert json.loads(lines[0]) == {"previous": True}
    row = json.loads(lines[1])
    output = capsys.readouterr()
    assert called == ["claude", "codex"]
    assert row[failed]["error"] == ("ValueError" if failed == "claude" else "OSError")
    assert "secret must not appear" not in log.read_text() + output.out + output.err
    assert "resets in unknown h" in output.out
    if failed == "claude":
        assert row["codex"]["primary-used-percent"] == "72"
        assert re.search(r"codex [a-z]* weekly ([0-9]*)%", output.out).group(1) == "72"
        assert not re.search(r"claude weekly all ([0-9]*)%", output.out)
    else:
        assert row["claude"]["weekly_all"]["percent"] == 91
        assert re.search(r"claude weekly all ([0-9]*)%", output.out).group(1) == "91"
        assert not re.search(r"codex [a-z]* weekly ([0-9]*)%", output.out)


def test_claude_token_is_sent_on_stdin_not_process_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "test-claude-token"

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if args[0] == "security":
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "claudeAiOauth": {
                            "accessToken": token,
                        }
                    }
                ),
            )
        assert token not in " ".join(args)
        assert args[:2] == ["curl", "--disable"]
        assert "Authorization: Bearer " + token in kwargs["input"]
        assert "--location" not in args and "-L" not in args
        assert kwargs["check"] is True
        body = {"limits": [{"kind": "weekly_all", "percent": 100, "resets_at": "later"}]}
        return subprocess.CompletedProcess(args, 0, json.dumps(body) + "\n200")

    monkeypatch.setattr(usage.subprocess, "run", run)
    assert usage.claude() == {"weekly_all": {"percent": 100, "resets_at": "later"}}


@pytest.mark.parametrize("status", [200, 429, 401])
def test_codex_status_and_private_headers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: int
) -> None:
    auth = tmp_path / ".codex" / "auth.json"
    auth.parent.mkdir()
    auth.write_text(
        json.dumps({"tokens": {"access_token": "test-codex-token", "account_id": "acct"}})
    )
    monkeypatch.setattr(usage.Path, "home", lambda: tmp_path)

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        assert "test-codex-token" not in " ".join(args)
        assert "chatgpt-account-id: acct" in kwargs["input"]
        assert "Authorization: Bearer test-codex-token" in kwargs["input"]
        return subprocess.CompletedProcess(
            args, 0, "X-Codex-Primary-Used-Percent: 100\r\n\n" + str(status)
        )

    monkeypatch.setattr(usage.subprocess, "run", run)
    if status == 401:
        with pytest.raises(RuntimeError):
            usage.codex()
    else:
        assert usage.codex()["primary-used-percent"] == "100"
        assert usage.codex()["http-status"] == status


def test_malformed_credential_is_not_salvaged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(args[0])
        return subprocess.CompletedProcess(args, 0, 'damaged {"claudeAiOauth":{"accessToken":"x"}}')

    monkeypatch.setattr(usage.subprocess, "run", run)
    with pytest.raises(json.JSONDecodeError):
        usage.claude()
    assert calls == ["security"]


@pytest.mark.parametrize("headers_only", [False, True])
def test_real_curl_stdin_transport_and_no_redirect_or_user_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, headers_only: bool
) -> None:
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append((self.path, dict(self.headers), self.rfile.read(2)))
            self.send_response(302)
            self.send_header("Location", "/must-not-follow")
            self.send_header("Content-Length", "9")
            self.end_headers()
            self.wfile.write(b"test-body")

        def log_message(self, format: str, *args: object) -> None:
            pass

    (tmp_path / ".curlrc").write_text('header = "X-Unwanted: yes"\nlocation\n')
    monkeypatch.setenv("CURL_HOME", str(tmp_path))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, response = usage.request(
            f"http://127.0.0.1:{server.server_port}/probe",
            {"Authorization": "Bearer test-secret", "Content-Type": "application/json"},
            5,
            body="{}",
            headers_only=headers_only,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert status == 302
    assert len(received) == 1
    path, headers, body = received[0]
    assert path == "/probe" and body == b"{}"
    assert headers["Authorization"] == "Bearer test-secret"
    assert "X-Unwanted" not in headers
    if headers_only:
        assert "Location: /must-not-follow" in response and "test-body" not in response
    else:
        assert response == "test-body"


@pytest.mark.parametrize("bad_value", ["token\rInjected: yes", "token\nInjected: yes"])
def test_header_injection_fails_before_transport(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("transport must not start for an invalid header")

    monkeypatch.setattr(usage.subprocess, "run", unexpected)
    with pytest.raises(ValueError):
        usage.request("https://example.invalid", {"Authorization": bad_value}, 1)


def test_claude_rejects_http_error_even_with_plausible_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        usage.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, '{"claudeAiOauth":{"accessToken":"test-token"}}'
        ),
    )
    monkeypatch.setattr(usage, "request", lambda *a, **k: (401, '{"limits":[]}'))
    with pytest.raises(RuntimeError):
        usage.claude()


@pytest.mark.parametrize(
    "reset,expected", [(None, "unknown"), ("bad", "unknown"), ("0", "0"), ("7200", "2")]
)
def test_zero_usage_and_reset_formatting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    reset: str | None,
    expected: str,
) -> None:
    monkeypatch.setattr(usage, "LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(usage, "claude", lambda: {"weekly_all": {"percent": 0}})
    monkeypatch.setattr(
        usage,
        "codex",
        lambda: {
            "plan-type": "prolite",
            "primary-used-percent": "0",
            "primary-reset-after-seconds": reset,
        },
    )
    usage.main()
    output = capsys.readouterr().out
    assert "claude weekly all 0%" in output and "codex prolite weekly 0%" in output
    assert f"resets in {expected} h" in output
