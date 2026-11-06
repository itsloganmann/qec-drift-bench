"""Scan every blob in a git history for secrets before a push to a public repository.

The scan covers every version of every file (gzip members are decompressed) and looks for two
things: the common key formats, and the exact values of this machine's own secrets (the
secrets file, the Claude Code keychain item, the Codex auth file). It prints where a hit is,
never the value. The last line is ``hits: N``; a publish step pushes only on ``hits: 0``.

Usage: uv run python scripts/secret_scan.py <path to a git repository>
"""

import json
import re
import subprocess
import sys
import zlib
from pathlib import Path

PATTERNS = {
    "anthropic": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "openai": r"sk-(?:proj-)?[A-Za-z0-9_\-]{32,}",
    "github": r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}",
    "aws": r"AKIA[0-9A-Z]{16}",
    "slack": r"xox[abprs]-[A-Za-z0-9\-]{10,}",
    "google": r"AIza[0-9A-Za-z_\-]{35}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "jwt": r"eyJ[A-Za-z0-9_\-]{20,}\.eyJ[A-Za-z0-9_\-]{50,}\.[A-Za-z0-9_\-]{20,}",
    "token_field": (
        r"\"(?:refresh_token|access_token|accessToken|refreshToken|id_token)\""
        r"\s*:\s*\"[^\"]{20,}\""
    ),
}
COMPILED = {name: re.compile(pattern.encode()) for name, pattern in PATTERNS.items()}
ENV_LINE = re.compile(r"\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*['\"]?([^'\"#\s]{12,})")


def machine_secrets() -> set[bytes]:
    """Collect the exact secret values that live on this machine."""
    values: set[str] = set()
    env = Path.home() / ".claude" / "secrets.env"
    if env.is_file():
        for line in env.read_text().splitlines():
            m = ENV_LINE.match(line)
            if m:
                values.add(m.group(1))
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        oauth = json.loads(raw)["claudeAiOauth"]
        values |= {v for v in oauth.values() if isinstance(v, str) and len(v) > 20}
    except Exception:  # noqa: BLE001 - the keychain item is optional
        pass
    codex = Path.home() / ".codex" / "auth.json"
    if codex.is_file():
        _walk(json.loads(codex.read_text()), values)
    return {v.encode() for v in values if not v.startswith(("http", "/"))}


def _walk(node: object, values: set[str]) -> None:
    if isinstance(node, dict):
        for child in node.values():
            _walk(child, values)
    elif isinstance(node, str) and len(node) > 20 and not node.startswith("/"):
        values.add(node)


def git(repo: str, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", repo, *args], input=data, capture_output=True, check=True
    ).stdout


def gunzip_members(data: bytes) -> bytes:
    """Decompress every gzip member of a multi-member stream."""
    out: list[bytes] = []
    i = 0
    while i < len(data):
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            out.append(d.decompress(data[i:]))
        except zlib.error:
            break
        used = len(data) - i - len(d.unused_data)
        if used <= 0:
            break
        i += used
    return b"".join(out)


def blobs_in_history(repo: str) -> dict[str, str]:
    """Map every blob sha in the history to one path it had."""
    named: dict[str, str] = {}
    for line in git(repo, "rev-list", "--objects", "--all").decode().splitlines():
        sha, _, path = line.partition(" ")
        if path:
            named.setdefault(sha, path)
    kinds = git(repo, "cat-file", "--batch-check", data="\n".join(named).encode())
    blobs = {}
    for line in kinds.decode().splitlines():
        parts = line.split()
        if parts[1:2] == ["blob"]:
            blobs[parts[0]] = named[parts[0]]
    return blobs


def main() -> int:
    repo = sys.argv[1]
    values = machine_secrets()
    print(f"exact values to look for: {len(values)}")
    blobs = blobs_in_history(repo)
    print(f"blobs: {len(blobs)}")
    hits = 0
    for sha, path in blobs.items():
        data = git(repo, "cat-file", "blob", sha)
        if data[:2] == b"\x1f\x8b":
            data = gunzip_members(data)
        for name, pattern in COMPILED.items():
            m = pattern.search(data)
            if m:
                hits += 1
                ctx = data[max(0, m.start() - 60) : m.start()].decode("utf-8", "replace")
                ctx = ctx.replace("\n", " ")[-60:]
                print(f"PATTERN {name} in {path} ({sha[:8]}) after: ...{ctx}")
        for value in values:
            if value in data:
                hits += 1
                print(f"EXACT secret value in {path} ({sha[:8]})")
    print("hits:", hits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
