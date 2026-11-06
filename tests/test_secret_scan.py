"""The secret scan that gates every push of the public snapshot."""

import gzip
import importlib.util
import subprocess
import sys
from pathlib import Path

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
