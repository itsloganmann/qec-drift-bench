"""Both subscriptions' usage, logged: how much of each weekly window the grid has used.

    uv run python scripts/usage.py            # print and append a line to data/usage_log.jsonl

Claude: the claude.ai usage endpoint with the Keychain login (weekly all models, weekly
Fable). Codex: the rate-limit headers of one tiny request to the ChatGPT backend with the
~/.codex login (primary window, used percent, reset). Nothing here touches the sandboxed
episodes; it reads the machine's own logins, as the scaffolds' refresh steps do.
Each provider is read independently. A failed read is logged by exception type, without its
message or credentials, and prints unknown usage. HTTP authorization headers go through stdin.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "data" / "usage_log.jsonl"
CLAUDE_USAGE = "https://api.anthropic.com/api/oauth/usage"
CODEX_RESPONSES = "https://chatgpt.com/backend-api/codex/responses"
TEXT = {"type": "input_text", "text": "ok"}


def request(
    url: str,
    headers: dict[str, str],
    seconds: int,
    body: str | None = None,
    headers_only: bool = False,
) -> tuple[int, str]:
    """Keep private headers off process arguments, without curlrc or redirect forwarding."""
    if any("\r" in value or "\n" in value for value in headers.values()):
        raise ValueError("invalid HTTP header")
    cmd = ["curl", "--disable", "-sS", "-m", str(seconds), "-H", "@-", "-w", "\n%{http_code}"]
    if headers_only:
        cmd += ["-D", "-", "-o", "/dev/null"]
    if body is not None:
        cmd += ["-d", body]
    cmd.append(url)
    output = subprocess.run(
        cmd,
        input="".join(f"{name}: {value}\n" for name, value in headers.items()),
        capture_output=True,
        text=True,
        timeout=seconds + 5,
        check=True,
    ).stdout
    text, status = output.rsplit("\n", 1)
    return int(status), text


def claude() -> dict:
    raw = subprocess.run(
        ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout
    token = json.loads(raw)["claudeAiOauth"]["accessToken"]
    status, out = request(
        CLAUDE_USAGE,
        {"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"},
        20,
    )
    if status != 200:
        raise RuntimeError(f"Claude usage HTTP {status}")
    data = json.loads(out)
    limits = {
        lim["kind"]: {"percent": lim["percent"], "resets_at": lim["resets_at"]}
        for lim in data.get("limits", [])
    }
    return limits


def codex() -> dict:
    auth = json.loads((Path.home() / ".codex" / "auth.json").read_text())
    token, account = auth["tokens"]["access_token"], auth["tokens"].get("account_id", "")
    body = json.dumps(
        {
            "model": "gpt-5.6-sol",
            "instructions": "Reply with ok.",
            "input": [{"type": "message", "role": "user", "content": [TEXT]}],
            "store": False,
            "stream": True,
            "reasoning": {"effort": "low", "summary": None},
            "tools": [],
            "include": [],
        }
    )  # fmt: skip
    status, head = request(
        CODEX_RESPONSES,
        {
            "Authorization": f"Bearer {token}",
            "chatgpt-account-id": account,
            "Content-Type": "application/json",
            "OpenAI-Beta": "responses=experimental",
            "originator": "codex_cli_rs",
            "accept": "text/event-stream",
        },
        40,
        body=body,
        headers_only=True,
    )
    if status not in (200, 429):
        raise RuntimeError(f"Codex usage HTTP {status}")
    out = {}
    for line in head.splitlines():
        if line.lower().startswith("x-codex-") and ":" in line:
            key, value = line.split(":", 1)
            out[key.strip().lower().removeprefix("x-codex-")] = value.strip()
    keys = ("plan-type", "primary-used-percent", "primary-window-minutes",
            "primary-reset-after-seconds", "secondary-used-percent")  # fmt: skip
    return {k: out.get(k) for k in keys}


def probe(read: Callable[[], dict]) -> dict:
    try:
        return read()
    except Exception as exc:  # noqa: BLE001 - one failed provider must not hide the other
        return {"error": type(exc).__name__}


def display(value: object) -> str:
    return "unknown" if value is None else str(value)


def main() -> None:
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "claude": probe(claude),
        "codex": probe(codex),
    }
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")
    c, x = row["claude"], row["codex"]
    try:
        reset = str(int(x.get("primary-reset-after-seconds")) // 3600)
    except (TypeError, ValueError):
        reset = "unknown"
    print(
        f"claude weekly all {display(c.get('weekly_all', {}).get('percent'))}%, "
        f"weekly fable {display(c.get('weekly_scoped', {}).get('percent'))}%; "
        f"codex {display(x.get('plan-type'))} weekly {display(x.get('primary-used-percent'))}%, "
        f"resets in {reset} h"
    )


if __name__ == "__main__":
    main()
