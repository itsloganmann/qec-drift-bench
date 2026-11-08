"""Run the decoder tasks with Claude Code as the agent, on the claude.ai subscription.

A second scaffold next to `decoder_run.py`. Each episode starts one headless `claude -p` process
in the task folder with Bash, Read, Write and Edit, the same task text, and no API key in its
environment, so it authenticates through the claude.ai login and bills the subscription. The
agent writes `decoder.py` and `report.json` (the same assessment fields as the API harness's
`submit`) and stops; the harness then scores `decoder.py` on the hidden test shots exactly as
the API harness does, and archives the CLI's event stream as the trajectory.

Differences from the API arms, reported with the arm: Claude Code's own system prompt, tools and
loop in a bare configuration (its own config directory: no hooks, plugins, MCP servers or
instruction files from this machine); a looser sandbox (agent/isolation.py: the CLI and its
shells run under a `sandbox-exec` profile that confines writes to the task folder and the
CLI's own state, hides the repository, secret stores and this machine's session archives, and
leaves the network open, because the CLI needs it); a cost ceiling instead of a tool-call
ceiling. The test labels never reach the folder either way. The episode loop, the row and the
arm driver here serve the Codex scaffold (decoder_run_codex.py) too, through a `Backend`.

Example:
    uv run python -m qec_drift.agent.decoder_run_cc --model claude-opus-5-5 --arm opus_cc \
        --set launch --tasks d5-none-dpatch30 --out data/agent_launch --max-usd 30
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from qec_drift import paths
from qec_drift.agent import attempts, isolation, transcripts
from qec_drift.agent import awareness as aw
from qec_drift.agent import decoder_run as dr
from qec_drift.agent import decoder_task as dt
from qec_drift.agent.provider_limits import LIMIT
from qec_drift.agent.provider_limits import interrupted as provider_interrupted
from qec_drift.scoring import taxonomy
from qec_drift.scoring.failure_modes_decoder import analyze_decoder

CLAUDE = Path.home() / ".local" / "bin" / "claude"
EPISODE_USD = 25.0  # the CLI's own estimate; the subscription pays, this only ends an episode
TOOLS = "Bash,Read,Write,Edit"
THROTTLE_WAIT = 15 * 60  # seconds between tries while the subscription is at its limit
THROTTLE_TRIES = 12
REPORT_NOTE = (
    "\n\nThere is no submit tool here. When decoder.py is ready, write report.json in the work "
    "folder with your assessment, with the keys model_adequate, confidence, scope, "
    "changed_qubits, mechanism, stationary, what_is_wrong and evidence (the same meanings as "
    "above), then stop. Whatever decoder.py exists when you stop is scored. You have about "
    "50 minutes of wall-clock time in all; when it runs out, whatever decoder.py and "
    "report.json exist are scored as they are."
)
LOGIN_LOST = re.compile(r"not logged in|failed to authenticate|oauth session expired|/login", re.I)
EXIT_LOGIN_LOST = 3  # the arm's exit code when the subscription login is gone: the grid stops
EXIT_THROTTLED = 4


def prompt() -> str:
    text = dr.prompt(awareness=True)
    old = "Use run_python to work and submit when decoder.py is ready."
    return text.replace(old, "Work in this folder with the shell and the file tools.") + REPORT_NOTE


CONFIG_DIR = Path.home() / ".qec-drift-claude"  # the CLI's own state for these runs, nothing else
EPISODE_TAG = str(os.getpid())  # the arm's name once run_arm sets it: two arms never share a folder
KEYCHAIN_SERVICE = "Claude Code-credentials"


REFRESH_MARGIN = 20 * 60  # seconds of token life left below which the login is refreshed first


def keychain_credential() -> dict:
    """The Claude Code login as the macOS Keychain holds it, refreshed when it is about to
    expire, or LoginLost when the refresh did not work (only a person can log in again).

    The copies the episodes get carry no refresh token, so the Keychain entry has to stay
    fresh. Only an interactive-style CLI call refreshes it: when the access token has less than
    REFRESH_MARGIN left, one short call of the real CLI, outside the sandbox and with the
    machine's own config, renews the entry, and the fresh token is read back.
    """
    credential = _read_keychain()
    if _life(credential) < REFRESH_MARGIN:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        cmd = [str(CLAUDE), "-p", "Reply with ok.", "--model", "claude-haiku-5-5", "--tools", ""]
        cmd += ["--no-session-persistence", "--strict-mcp-config", "--mcp-config"]
        cmd += ['{"mcpServers": {}}']
        subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120, check=False)
        credential = _read_keychain()
        if _life(credential) < REFRESH_MARGIN:
            raise LoginLost("the claude.ai login expired and could not be refreshed")
    return credential


def _life(credential: dict) -> float:
    """Seconds of access-token life left; none without a token."""
    oauth = credential.get("claudeAiOauth") or {}
    if not oauth.get("accessToken"):
        return 0.0
    return oauth.get("expiresAt", 0) / 1000 - time.time()


def _read_keychain() -> dict:
    raw = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(raw)


def prepare_config_dir(where: Path, credential: dict | None = None) -> Path:
    """A config directory for one episode, with only the claude.ai login and empty settings.

    With CLAUDE_CONFIG_DIR pointing here, none of this machine's hooks, plugins, MCP servers or
    instruction files load into the episode. The login is copied from the macOS Keychain: the
    claude.ai access token only, without the refresh token, so what is on disk expires within
    hours and cannot mint another. `run_cli` locks the file at the CLI's first reply, before
    the agent can run a command, because the agent's shells share the sandbox. Each episode
    gets a fresh directory of its own, with its own cache and temp, and the sandbox lets it
    write nowhere else under CONFIG_DIR, so no episode can plant a hook or a file for the next.
    """
    where = isolation.fresh_dir(where)
    credential = keychain_credential() if credential is None else credential
    login = {k: v for k, v in credential["claudeAiOauth"].items() if k != "refreshToken"}
    target = where / ".credentials.json"
    if target.exists():
        target.chmod(0o600)
    target.write_text(json.dumps({"claudeAiOauth": login}))
    target.chmod(0o600)
    (where / "settings.json").write_text('{"hooks": {}, "enabledPlugins": {}}\n')
    return where


def login_file(where: Path) -> Path:
    return where / ".credentials.json"


def lock_credential(where: Path) -> None:
    isolation.lock(login_file(where))


def remove_credential(where: Path) -> None:
    isolation.remove(login_file(where))


def environment(config_dir: Path) -> dict[str, str]:
    """The allowlisted environment of agent/isolation.py with the episode's own config directory.
    With no ANTHROPIC_API_KEY the CLI uses the claude.ai login in `config_dir`."""
    env = isolation.environment(config_dir)
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    env["CLAUDE_CODE_TMPDIR"] = str(config_dir / "tmp")  # the CLI's shell scratch tree too
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def profile(workdir: Path, config_dir: Path) -> str:
    """The sandbox-exec profile of agent/isolation.py for this episode."""
    return isolation.profile(workdir, config_dir, CONFIG_DIR, login_file(config_dir))


def run_cli(
    workdir: Path, model: str, effort: str | None, max_usd: float, config_dir: Path
) -> tuple[list[dict], int]:
    """One headless Claude Code session in `workdir`. Returns the event stream and the exit code."""
    cmd = [
        "sandbox-exec",
        "-p",
        profile(workdir, config_dir),
        str(CLAUDE),
        "-p",
        prompt(),
        "--model",
        model,
        "--tools",
        TOOLS,
        "--dangerously-skip-permissions",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers": {}}',
        "--max-budget-usd",
        str(max_usd),
    ]
    if effort:
        cmd += ["--effort", effort]
    return isolation.stream(
        cmd, workdir, environment(config_dir), login_file(config_dir), replied, tools=tool_starts
    )


def replied(line: str) -> bool:
    """The CLI's first reply: the token was read, and the agent's first shell command can only
    follow this reply, so the login is locked before the agent can act."""
    return '"type":"assistant"' in line.replace(" ", "")


def tool_starts(line: str) -> int:
    """The tool calls one stream line starts: the tool_use blocks of an assistant message."""
    compact = line.replace(" ", "")
    if '"type":"assistant"' not in compact:
        return 0
    return compact.count('"type":"tool_use"')


def tool_calls(events: list[dict]) -> int:
    n = 0
    for e in events:
        if e.get("type") == "assistant":
            for b in (e.get("message") or {}).get("content", []):
                n += b.get("type") == "tool_use"
    return n


def cli_result(events: list[dict]) -> dict:
    for e in reversed(events):
        if e.get("type") == "result":
            return e
    return {}


def summary(events: list[dict], code: int) -> dict:
    """How the episode ended: the stop reason, tokens, the CLI's cost estimate, and whether the
    subscription refused it (an error exit with a limit message)."""
    result = cli_result(events)
    usage = result.get("usage") or {}
    text = " ".join(
        str(e.get("result") or e.get("text") or e.get("note") or "")
        for e in events
        if e.get("type") in ("result", "stderr", "harness")
    )
    failed = bool(result.get("is_error") or code != 0)
    return dict(
        stop=result.get("terminal_reason", f"exit {code}"),
        tokens_in=int(usage.get("input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
        cost_usd=float(result.get("total_cost_usd") or 0.0),
        throttled=failed and bool(LIMIT.search(text)),
        login_lost=failed and bool(LOGIN_LOST.search(text)),
    )


class Throttled(Exception):
    """The subscription refused the episode before the agent did anything."""


class LoginLost(Exception):
    """The subscription login is gone and only a person can renew it: the arm must stop."""


@dataclass(frozen=True)
class Backend:
    """One CLI scaffold: how an episode's state is prepared, run, read and released."""

    name: str  # the trajectory's `scaffold`
    trace_kind: str
    check: Callable[[], None]  # fail before the first episode when the CLI or login is missing
    prepare: Callable[[str], Path]  # the task's state directory, with a copy of the login
    run: Callable[[Path, str, str | None, float, Path], tuple[list[dict], int]]
    release: Callable[[Path], None]  # take the login copy away
    turns: Callable[[list[dict]], int]
    summary: Callable[[list[dict], int], dict]


def _check() -> None:
    if not CLAUDE.exists():
        sys.exit(f"no Claude Code CLI at {CLAUDE}")
    try:
        keychain_credential()  # fail now, not in the first episode, when the login is missing
    except LoginLost as exc:
        print(f"login lost: {exc}", flush=True)
        sys.exit(EXIT_LOGIN_LOST)


def episode_dir(root: Path, task_name: str) -> Path:
    return root / "episodes" / f"{EPISODE_TAG}--{task_name}"


def _prepare(task_name: str) -> Path:
    return prepare_config_dir(episode_dir(CONFIG_DIR, task_name))


CLAUDE_CODE = Backend(
    "claude-code",
    "claude_code_stream",
    _check,
    _prepare,
    run_cli,
    remove_credential,
    tool_calls,
    summary,
)


def read_report(workdir: Path) -> dict | None:
    text = dr.read_regular_file(workdir / "report.json", limit=200_000)
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def run_episode(
    task: dt.Task,
    model: str,
    effort: str | None,
    root: Path,
    max_usd: float,
    backend: Backend = CLAUDE_CODE,
) -> tuple[dict, dict]:
    """One episode in a folder with a random name, moved to root/<task> once it is scored.

    The CLI shows the agent its working directory, and a task name says what is wrong
    (`d5-none-dwander30d30-s6`: a wandering fault); 2026-11-03, agents read it. So neither the
    task folder nor the CLI's state directory carries the task name while the agent runs.
    """
    workdir = (root / f"ep-{secrets.token_hex(6)}").resolve()
    final = (root / task.name).resolve()
    isolation.clear(final)  # an earlier attempt may have left read-only caches; fail before
    try:
        return _episode(task, model, effort, workdir, max_usd, backend)
    finally:
        if workdir.exists():
            workdir.rename(final)


def _episode(
    task: dt.Task,
    model: str,
    effort: str | None,
    workdir: Path,
    max_usd: float,
    backend: Backend,
) -> tuple[dict, dict]:
    dt.write_agent_files(task, workdir)
    test_det, test_obs, regime = dt.test_sample(task)
    refs = dt.task_references(task, test_det, test_obs, regime)
    config_dir = backend.prepare(workdir.name)
    started = time.monotonic()
    try:
        events, code = backend.run(workdir, model, effort, max_usd, config_dir)
    finally:
        backend.release(config_dir)
    seconds = time.monotonic() - started
    turns = backend.turns(events)
    ended = backend.summary(events, code)
    if ended.get("login_lost"):
        raise LoginLost(ended["stop"])
    if ended["throttled"] and turns == 0:
        raise Throttled(ended["stop"])
    interrupted = provider_interrupted(events)
    err, pred = (
        ("provider usage limit", None) if interrupted
        else dr.score_submission(workdir, task, test_det)
    )
    l_agent = dt.logical_error_rate(pred, test_obs) if pred is not None else float("nan")
    scored = pred is not None
    agree_plain = agree_corr = float("nan")
    if pred is not None:
        plain, corr = dt.nominal_predictions(task.d, test_det)
        agree_plain = float(np.mean(pred.reshape(-1) == np.asarray(plain, bool).reshape(-1)))
        agree_corr = float(np.mean(pred.reshape(-1) == np.asarray(corr, bool).reshape(-1)))
    given = read_report(workdir)
    report = aw.report_from(given) if given is not None else None
    verdict = aw.diagnosis(report or aw.report_from({}), task.truth)
    gap = dt.gap_closed(l_agent, refs) if scored else float("nan")
    drift_gap = dt.gap_drift(l_agent, refs) if scored else float("nan")
    verdict["passed"] = aw.passed(verdict["diagnosis_correct"], gap, drift_gap)
    src = dr.read_regular_file(workdir / "decoder.py")
    row = (
        dict(
            task=task.name,
            d=task.d,
            scenario=task.scenario,
            drift=task.drift,
            seed=task.seed,
            adequate_truth=task.model_adequate,
            reported=report is not None,
            awareness_brier=aw.brier(report, task.model_adequate) if report else float("nan"),
            outcome="error" if interrupted else ("submitted" if scored else "no_decoder"),
            provider_interrupted=interrupted,
            stop=ended["stop"],
            turns=turns,
            n_run_python=0,
            n_timeouts=0,
            tokens_in=ended["tokens_in"],
            tokens_out=ended["tokens_out"],
            l_agent=l_agent,
            gap_closed=gap,
            gap_drift=drift_gap,
            cost_usd=ended["cost_usd"],
            seconds=round(seconds),
            uses_correlations="enable_correlations" in src,
            agree_nominal_plain=agree_plain,
            agree_nominal_corr=agree_corr,
            auto_scored=not interrupted,
            score_error="" if scored else err,
            decoder_bytes=dr.decoder_size(workdir),
            decoder_src=src,
        )
        | (report or aw.report_from({}))
        | verdict
        | {f"ref_{k}": v for k, v in refs.items()}
    )
    trajectory = dict(
        task=task.name,
        model=model,
        effort=effort,
        scaffold=backend.name,
        trace_kind=backend.trace_kind,
        prompt=prompt(),
        events=events,
        decoder_src=src,
        report=given,
        workdir=str(workdir),  # the folder the agent saw; the rows live under root/<task>
    )
    return row, trajectory


def safe_episode(task: dt.Task, *args, backend: Backend = CLAUDE_CODE) -> tuple[dict, dict]:
    """One episode, tried again after a wait while the subscription is at its limit; any
    other failure lands in the table as an error row."""
    reason = "Throttled: gave up"
    for _ in range(THROTTLE_TRIES):
        try:
            return run_episode(task, *args, backend=backend)
        except Throttled as exc:
            print(f"{task.name}: {exc}; next try in {THROTTLE_WAIT} s", flush=True)
            time.sleep(THROTTLE_WAIT)
        except LoginLost:
            raise
        except Exception as exc:  # noqa: BLE001 - every failure must land in the table
            where = traceback.format_exc(limit=-3).strip().splitlines()[-6:]
            reason = (f"{type(exc).__name__}: {exc} | " + " / ".join(where))[:1500]
            break
    row = dict(
        task=task.name,
        d=task.d,
        scenario=task.scenario,
        drift=task.drift,
        seed=task.seed,
        adequate_truth=task.model_adequate,
        reported=False,
        awareness_brier=float("nan"),
        outcome="error",
        stop="error",
        turns=0,
        n_run_python=0,
        n_timeouts=0,
        tokens_in=0,
        tokens_out=0,
        l_agent=float("nan"),
        gap_closed=float("nan"),
        gap_drift=float("nan"),
        cost_usd=0.0,
        seconds=0,
        uses_correlations=False,
        agree_nominal_plain=float("nan"),
        agree_nominal_corr=float("nan"),
        auto_scored=False,
        score_error=reason,
        decoder_bytes=0,
        decoder_src="",
    ) | aw.report_from({})
    return row, dict(task=task.name, error=reason, trace_kind=backend.trace_kind, events=[])


def parse_args(description: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=description.split("\n", 1)[0])
    ap.add_argument("--model", required=True, help="a full model id, e.g. claude-opus-5-5")
    ap.add_argument("--effort", default=None)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--max-usd", type=float, default=EPISODE_USD, help="per episode, CLI estimate")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--set", default="launch", choices=sorted(dt.TASK_SETS))
    ap.add_argument(
        "--tasks",
        default="",
        help="comma list of task names from any set, or @<file> with one name per line: "
        "an episode can list every process's command line, so the grid passes a file",
    )
    ap.add_argument("--out", type=Path, default=paths.DATA / "agent_launch")
    ap.add_argument("--append", action="store_true", help="keep the arm's rows for other tasks")
    return ap.parse_args()


def run_arm(args: argparse.Namespace, backend: Backend = CLAUDE_CODE) -> None:
    global EPISODE_TAG
    EPISODE_TAG = args.arm
    backend.check()
    refs = args.out / "references.json"
    if refs.is_file():
        print(f"references cached for {dt.load_references(refs)} tasks", flush=True)
    names = args.tasks
    if names.startswith("@"):
        names = ",".join(Path(names[1:]).read_text().split())
    tasks = dt.tasks_by_name(names) if names else dt.TASK_SETS[args.set]()
    root = args.out / "work" / args.arm
    root.mkdir(parents=True, exist_ok=True)
    dr.warm_up_stim()
    traj_path = paths.trajectories_dir() / args.out.name / f"decoder_{args.arm}.jsonl.gz"
    traj_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    table = args.out / f"{args.arm}.parquet"
    if args.append and table.exists():
        rows = pd.read_parquet(table).to_dict("records")
    with (
        traj_path.open("ab") as trace,
        ThreadPoolExecutor(args.concurrency) as pool,
    ):
        for start in range(0, len(tasks), args.concurrency):
            batch = tasks[start : start + args.concurrency]
            try:
                done = list(
                    pool.map(
                        lambda t: safe_episode(
                            t, args.model, args.effort, root, args.max_usd, backend=backend
                        ),
                        batch,
                    )
                )
            except LoginLost as exc:
                print(f"login lost: {exc}; the arm stops here", flush=True)
                if rows:
                    attempts.write_table(table, rows)
                sys.exit(EXIT_LOGIN_LOST)
            for row, trajectory in done:
                saved = attempts.append_attempt(trace, row, trajectory, args.arm)
                rows = [r for r in rows if r["task"] != row["task"]] + [saved]
            attempts.write_table(table, rows)
            if any(row.get("provider_interrupted") for row, _ in done):
                report_arm(table, traj_path)
                sys.exit(EXIT_THROTTLED)
    df = pd.DataFrame(rows)
    cols = [
        "task",
        "outcome",
        "stop",
        "turns",
        "seconds",
        "gap_closed",
        "gap_drift",
        "report_scope",
        "localization",
        "diagnosis_correct",
        "passed",
        "cost_usd",
    ]
    print(df[[c for c in cols if c in df.columns]].round(3).to_string(index=False))
    print(
        f"{args.arm}: pass rate {df.passed.fillna(False).mean():.3f} ({int(df.passed.sum())} of "
        f"{len(df)}), diagnosis correct {df.diagnosis_correct.fillna(False).mean():.3f}, "
        f"CLI cost estimate ${df.cost_usd.sum():.2f} (subscription)"
    )
    report_arm(table, traj_path)


def report_arm(table: Path, traj_path: Path) -> None:
    try:
        analyze_decoder(table, traj_path)
        labels = taxonomy.analyze_arm(table, traj_path)  # before rendering: pages show the label
        print("failure modes:", labels.label.value_counts().to_dict())
        print("transcripts:", transcripts.render_archive(traj_path, table))
    except Exception as exc:  # noqa: BLE001 - the rows are saved; the adapter is a report
        print(f"failure-mode adapter failed: {exc}", flush=True)


def main() -> None:
    run_arm(parse_args(__doc__))


if __name__ == "__main__":
    main()
