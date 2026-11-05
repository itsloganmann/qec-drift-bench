"""Run the decoder tasks with Codex as the agent, on the ChatGPT subscription.

The third scaffold, next to decoder_run.py (the API) and decoder_run_cc.py (Claude Code). Each
episode starts one headless `codex exec` in the task folder with the same task text, under the
sandbox-exec profile and the allowlisted environment of agent/isolation.py, with CODEX_HOME at a
state directory of its own that holds the ChatGPT login (access token, no refresh token) and
no config, skills, plugins, hooks or MCP servers of this machine. Codex's own sandbox is off:
the outer one confines it, and two seatbelt profiles do not nest. Its browser, computer use,
apps, memories, plugins, skill search, hooks and web search are off; its code-mode host, the
helper that the shell of these models runs through, comes from the same install tree as the
binary. This machine's shared skills (~/.agents) are hidden with the rest of its agent
configuration; the five skills built into the CLI stay. The agent writes
decoder.py and report.json and stops; decoder_run_cc.run_episode scores decoder.py on the
hidden test shots as the other scaffolds do and archives the JSONL event stream as the
trajectory.

Differences from the Claude Code arms, reported with the arm: Codex's own system prompt, tools
(a shell, apply_patch) and loop; no cost ceiling (the CLI reports none), only the episode's
time limit.

Example:
    uv run python -m qec_drift.agent.decoder_run_codex --model gpt-6-astra --effort max \\
        --arm gpt_6_astra_max_codex --set launch2 --out data/agent_launch2
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from pathlib import Path

from qec_drift.agent import decoder_run_cc as cc
from qec_drift.agent import isolation

CODEX_PACKAGES = Path.home() / ".codex" / "packages"  # the CLI's own install, no secrets
CODEX = CODEX_PACKAGES / "standalone" / "current" / "bin" / "codex"  # not this machine's wrapper
AUTH = Path.home() / ".codex" / "auth.json"
CONFIG_DIR = Path.home() / ".qec-drift-codex"  # CODEX_HOME of every episode, nothing else
OFF = (  # features the model would otherwise get as tools or context
    "browser_use",
    "browser_use_external",
    "in_app_browser",
    "computer_use",
    "apps",
    "memories",
    "plugins",
    "skill_search",
    "hooks",
)
HOST = CODEX.parent / "codex-code-mode-host"  # the shell of these models runs through it
TOOL_ITEMS = ("command_execution", "file_change", "mcp_tool_call", "web_search")
REFRESH_MARGIN = 20 * 60
REFRESH_MODEL = "gpt-5.6-sol"


def _expires(token: str) -> float:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return float(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))


def login() -> dict:
    """The ChatGPT login as ~/.codex/auth.json holds it, refreshed first when the access
    token has less than REFRESH_MARGIN left: one short call of the real CLI outside the
    sandbox, with this machine's CODEX_HOME and no API key in its environment, renews the
    file, and it is read back."""
    data = json.loads(AUTH.read_text())
    if _expires(data["tokens"]["access_token"]) - time.time() < REFRESH_MARGIN:
        scratch = isolation.fresh_dir(CONFIG_DIR / "refresh")
        cmd = [str(CODEX), "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check"]
        cmd += ["-m", REFRESH_MODEL, "-c", 'model_reasoning_effort="low"', "Reply with ok."]
        subprocess.run(
            cmd,
            cwd=scratch,
            env=isolation.environment(scratch),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        data = json.loads(AUTH.read_text())
    return data


def login_file(where: Path) -> Path:
    return where / "auth.json"


def prepare_config_dir(where: Path, credential: dict | None = None) -> Path:
    """A CODEX_HOME for one episode: the login with its refresh token blanked (the CLI needs
    the field, and does not need a value while the access token lives), an empty config."""
    where = isolation.fresh_dir(where)
    data = login() if credential is None else credential
    tokens = {k: ("" if k == "refresh_token" else v) for k, v in data["tokens"].items()}
    copy = {
        "auth_mode": data.get("auth_mode", "chatgpt"),
        "OPENAI_API_KEY": None,
        "tokens": tokens,
        "last_refresh": data.get("last_refresh"),
    }
    target = login_file(where)
    target.write_text(json.dumps(copy))
    target.chmod(0o600)
    (where / "config.toml").write_text("")  # unread (--ignore-user-config); none of this machine
    return where


def environment(config_dir: Path) -> dict[str, str]:
    env = isolation.environment(config_dir)
    env["CODEX_HOME"] = str(config_dir)
    env["CODEX_CODE_MODE_HOST_PATH"] = str(HOST)
    return env


def command(workdir: Path, config_dir: Path, model: str, effort: str | None) -> list[str]:
    """The sandboxed `codex exec` command line of one episode."""
    cmd = [
        "sandbox-exec",
        "-p",
        isolation.profile(
            workdir, config_dir, CONFIG_DIR, login_file(config_dir), (CODEX_PACKAGES,)
        ),
        str(CODEX),
        "exec",
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        str(workdir),
        "-m",
        model,
        "-c",
        'web_search="disabled"',
    ]
    for feature in OFF:
        cmd += ["--disable", feature]
    if effort:
        cmd += ["-c", f'model_reasoning_effort="{effort}"']
    return cmd + [cc.prompt()]


def replied(line: str) -> bool:
    """The CLI's first event: Codex loads the login before it opens the thread, and the
    first item (the agent's first command) would come too late to lock against."""
    return '"type":"thread.started"' in line.replace(" ", "")


def run_cli(
    workdir: Path, model: str, effort: str | None, _max_usd: float, config_dir: Path
) -> tuple[list[dict], int]:
    """One headless Codex session in `workdir`. Returns the event stream and the exit code."""
    cmd = command(workdir, config_dir, model, effort)
    return isolation.stream(
        cmd, workdir, environment(config_dir), login_file(config_dir), replied, tools=tool_starts
    )


def tool_starts(line: str) -> int:
    """The tool calls one stream line starts: an item.started of a tool item."""
    compact = line.replace(" ", "")
    if '"type":"item.started"' not in compact:
        return 0
    return int(any(f'"type":"{kind}"' in compact for kind in TOOL_ITEMS))


def tool_calls(events: list[dict]) -> int:
    return sum(
        e.get("type") == "item.completed" and (e.get("item") or {}).get("type") in TOOL_ITEMS
        for e in events
    )


def summary(events: list[dict], code: int) -> dict:
    """How the episode ended: "completed" at a completed turn, "failed" at a failed one, the
    last turn's tokens, no cost (the subscription pays), and whether the subscription refused
    it (no completed turn and a limit message)."""
    usage: dict = {}
    stop = f"exit {code}"
    text = []
    for e in events:
        kind = e.get("type")
        if kind == "turn.completed":
            usage = e.get("usage") or {}
            stop = "completed"
        elif kind == "turn.failed":
            stop = "failed"
            text.append(str((e.get("error") or {}).get("message", "")))
        elif kind == "error":
            text.append(str(e.get("message", "")))
        elif kind in ("stderr", "harness"):
            text.append(str(e.get("text") or e.get("note") or ""))
    return dict(
        stop=stop,
        tokens_in=int(usage.get("input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
        cost_usd=0.0,
        throttled=stop != "completed" and bool(cc.LIMIT.search(" ".join(text))),
    )


def _check() -> None:
    if not CODEX.exists():
        sys.exit(f"no Codex CLI at {CODEX}")
    if not AUTH.is_file() or "tokens" not in json.loads(AUTH.read_text()):
        sys.exit(f"no ChatGPT login in {AUTH}; run `codex login` first")


def _prepare(task_name: str) -> Path:
    return prepare_config_dir(cc.episode_dir(CONFIG_DIR, task_name))


def _release(config_dir: Path) -> None:
    isolation.remove(login_file(config_dir))


BACKEND = cc.Backend(
    "codex", "codex_stream", _check, _prepare, run_cli, _release, tool_calls, summary
)


def main() -> None:
    cc.run_arm(cc.parse_args(__doc__), BACKEND)


if __name__ == "__main__":
    main()
