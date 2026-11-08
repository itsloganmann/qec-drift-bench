"""Scan every blob in a git history for secrets before a push to a public repository.

The scan covers every version of every file (gzip members are decompressed) and looks for two
things: the common key formats, and the exact values of this machine's own secrets (the
secrets file, the Claude Code keychain item, the Codex auth file). It prints where a hit is,
never file contents. The last line is ``hits: N``; a publish step pushes only on ``hits: 0``.
Complete credential token fields are collected from text or hex even if their envelope is
damaged, solely for exact matching. Authentication keeps its strict parser. A present but
unreadable Keychain item or an unexpected read failure stops the scan.

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
TOKEN_FIELD = re.compile(
    r'"(?:accessToken|refreshToken|access_token|refresh_token|id_token)"\s*:\s*'
)
KEYCHAIN_ITEM_NOT_FOUND = 44


def keychain_tokens(raw: str) -> set[str]:
    candidates = [raw]
    try:
        candidates.append(bytes.fromhex(raw.strip()).decode("utf-8", "replace"))
    except ValueError:
        pass
    values = set()
    decoder = json.JSONDecoder()
    for text in candidates:
        for match in TOKEN_FIELD.finditer(text):
            try:
                value, _ = decoder.raw_decode(text, match.end())
            except json.JSONDecodeError:
                continue
            if isinstance(value, str) and len(value) > 20:
                values.add(value)
    if not values:
        raise ValueError("No readable credential token fields in Claude Keychain")
    return values


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
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except FileNotFoundError:
        pass
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Could not inspect Claude Keychain") from None
    else:
        if result.returncode == 0:
            values |= keychain_tokens(result.stdout)
        elif result.returncode != KEYCHAIN_ITEM_NOT_FOUND or result.stdout.strip():
            raise RuntimeError("Could not inspect Claude Keychain")
    codex = Path.home() / ".codex" / "auth.json"
    if codex.is_file():
        _walk(json.loads(codex.read_text()), values)
    return {v.encode() for v in values if not v.startswith(("http", "/"))}


def _walk(node: object, values: set[str]) -> None:
    if isinstance(node, (dict, list)):
        for child in node.values() if isinstance(node, dict) else node:
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
                print(f"PATTERN {name} in {path} ({sha[:8]})")
        for value in values:
            if value in data:
                hits += 1
                print(f"EXACT secret value in {path} ({sha[:8]})")
    print("hits:", hits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
