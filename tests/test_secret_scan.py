"""The secret scan that gates every push of the public snapshot."""

import gzip
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("secret_scan", ROOT / "scripts" / "secret_scan.py")
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)

SECRET = b"TOPSECRETVALUE1234567890"


def _repo(tmp_path: Path, files: dict[str, bytes]) -> str:
    repo = tmp_path / "repo"
    repo.mkdir()
    for name, data in files.items():
        (repo / name).write_bytes(data)
    git = [
        "git",
        "-C",
        str(repo),
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "-c",
        "commit.gpgsign=false",
    ]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "fixture"], check=True)
    return str(repo)


def _run(repo: str, monkeypatch, capsys) -> str:
    monkeypatch.setattr(scan, "machine_secrets", lambda: {SECRET})
    monkeypatch.setattr(sys, "argv", ["secret_scan.py", repo])
    assert scan.main() == 0
    return capsys.readouterr().out


def test_scan_reports_a_key_format_and_an_exact_value(tmp_path, monkeypatch, capsys):
    # The second gzip member holds the exact value: the scan must read every member.
    archive = gzip.compress(b'{"row": 1}\n') + gzip.compress(b'{"body": "' + SECRET + b'"}\n')
    repo = _repo(
        tmp_path,
        {
            "a.txt": b"key = sk-ant-" + b"A" * 20 + b"\n",
            "b.jsonl.gz": archive,
            "clean.md": b"# nothing here\n",
        },
    )
    out = _run(repo, monkeypatch, capsys)
    assert "PATTERN anthropic in a.txt" in out
    assert "EXACT secret value in b.jsonl.gz" in out
    assert SECRET.decode() not in out
    assert out.rstrip().endswith("hits: 2")


def test_clean_history_has_no_hits(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, {"README.md": b"# clean\n", "x.jsonl.gz": gzip.compress(b"{}\n")})
    out = _run(repo, monkeypatch, capsys)
    assert out.rstrip().endswith("hits: 0")


@pytest.mark.parametrize("encoding", ["json", "hex", "damaged", "damaged_hex"])
def test_token_fields_are_collected_without_trusting_credential_envelope(encoding: str) -> None:
    access = "opaque-access-" + "a" * 24
    refresh = "opaque-refresh-" + "b" * 24
    raw = json.dumps({"claudeAiOauth": {"accessToken": access, "refreshToken": refresh}})
    if encoding.startswith("damaged"):
        raw = "\x01" + raw[1:] + " trailing bytes"
    if encoding.endswith("hex"):
        raw = raw.encode().hex()
    assert scan.keychain_tokens(raw) == {access, refresh}


def test_complete_fields_survive_a_truncated_envelope_and_decode_json_escapes() -> None:
    token = 'opaque-quoted-"-' + "a" * 24
    field = json.dumps({"accessToken": token})[:-1]
    assert scan.keychain_tokens(field) == {token}


@pytest.mark.parametrize("raw", ["", "not readable", "7b62726f6b656e", '{"accessToken": null}'])
def test_present_but_unreadable_keychain_cannot_produce_a_clean_scan(raw: str) -> None:
    with pytest.raises(ValueError, match="No readable credential token fields"):
        scan.keychain_tokens(raw)


@pytest.mark.parametrize("code", [0, 44, 1])
def test_keychain_read_distinguishes_missing_item_from_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    token = "opaque-keychain-" + "k" * 24
    raw = json.dumps({"accessToken": token}).encode().hex()
    monkeypatch.setattr(scan.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        scan.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], code, raw if code == 0 else "", "private stderr must not appear"
        ),
    )
    if code == 1:
        with pytest.raises(RuntimeError, match="Could not inspect Claude Keychain") as error:
            scan.machine_secrets()
        assert "private stderr" not in str(error.value)
    else:
        assert scan.machine_secrets() == ({token.encode()} if code == 0 else set())


def test_timed_out_keychain_read_cannot_silently_skip_exact_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scan.Path, "home", lambda: tmp_path)

    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("security", 10, output="private output")

    monkeypatch.setattr(scan.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="Could not inspect Claude Keychain") as error:
        scan.machine_secrets()
    assert "private output" not in str(error.value)


def test_scan_does_not_print_a_secret_before_a_pattern_match(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, {"a.txt": SECRET + b" sk-ant-" + b"A" * 20})
    out = _run(repo, monkeypatch, capsys)
    assert SECRET.decode() not in out
    assert "PATTERN anthropic" in out and out.rstrip().endswith("hits: 2")


def test_malformed_keychain_exact_value_is_found_in_real_git_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _repo(tmp_path, {"a.txt": SECRET})
    raw = ("\x01" + json.dumps({"accessToken": SECRET.decode()}) + " trailing").encode().hex()
    original = subprocess.run

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if args[0] == "security":
            return subprocess.CompletedProcess(args, 0, raw)
        return original(args, **kwargs)

    monkeypatch.setattr(scan.subprocess, "run", run)
    monkeypatch.setattr(scan.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["secret_scan.py", repo])
    assert scan.main() == 0
    out = capsys.readouterr().out
    assert "EXACT secret value in a.txt" in out
    assert SECRET.decode() not in out and out.rstrip().endswith("hits: 1")
