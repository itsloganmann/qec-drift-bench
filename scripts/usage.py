"""Both subscriptions' usage, logged: how much of each weekly window the grid has used.

    uv run python scripts/usage.py            # print and append a line to data/usage_log.jsonl

Claude: the claude.ai usage endpoint with the Keychain login (weekly all models, weekly
Fable). Codex: the rate-limit headers of one tiny request to the ChatGPT backend with the
~/.codex login (primary window, used percent, reset). Nothing here touches the sandboxed
episodes; it reads the machine's own logins, as the scaffolds' refresh steps do.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "data" / "usage_log.jsonl"
CLAUDE_USAGE = "https://api.anthropic.com/api/oauth/usage"
CODEX_RESPONSES = "https://chatgpt.com/backend-api/codex/responses"
TEXT = {"type": "input_text", "text": "ok"}


def claude() -> dict:
    raw = subprocess.run(
        ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    token = json.loads(raw)["claudeAiOauth"]["accessToken"]
    out = subprocess.run(
        ["curl", "-s", "-m", "20", "-H", f"Authorization: Bearer {token}",
         "-H", "anthropic-beta: oauth-2025-04-20", CLAUDE_USAGE],
        capture_output=True,
        text=True,
    ).stdout  # fmt: skip
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
    head = subprocess.run(
        ["curl", "-s", "-m", "40", "-D", "-", "-o", "/dev/null", "-X", "POST", CODEX_RESPONSES,
         "-H", f"Authorization: Bearer {token}", "-H", f"chatgpt-account-id: {account}",
         "-H", "Content-Type: application/json", "-H", "OpenAI-Beta: responses=experimental",
         "-H", "originator: codex_cli_rs", "-H", "accept: text/event-stream", "-d", body],
        capture_output=True,
        text=True,
    ).stdout  # fmt: skip
    out = {}
    for line in head.splitlines():
        if line.lower().startswith("x-codex-") and ":" in line:
            key, value = line.split(":", 1)
            out[key.strip().lower().removeprefix("x-codex-")] = value.strip()
    keys = ("plan-type", "primary-used-percent", "primary-window-minutes",
            "primary-reset-after-seconds", "secondary-used-percent")  # fmt: skip
    return {k: out.get(k) for k in keys}


def main() -> None:
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "claude": claude(), "codex": codex()}
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")
    c, x = row["claude"], row["codex"]
    print(
        f"claude weekly all {c.get('weekly_all', {}).get('percent')}%, "
        f"weekly fable {c.get('weekly_scoped', {}).get('percent')}%; "
        f"codex {x.get('plan-type')} weekly {x.get('primary-used-percent')}%, "
        f"resets in {int(x.get('primary-reset-after-seconds') or 0) // 3600} h"
    )


if __name__ == "__main__":
    main()
