"""What the subscription scaffolds share: an allowlisted environment, a sandbox-exec profile,
a fresh state directory per episode, and a streaming runner with a deadline and a login lock.
(agent/sandbox.py is something else: the API harness's runner for the agent's code.)

Both scaffolds (decoder_run_cc.py for Claude Code, decoder_run_codex.py for Codex) start one
headless CLI process per episode in the task folder. The process and everything it spawns run
under a `sandbox-exec` profile that confines writes to the task folder and the episode's own
state directory, hides the repository, this machine's secret stores and the scaffold's other
episodes, and leaves the network open (the CLI needs its API, and a profile cannot filter by
host). The login the CLI needs is copied into the episode's state directory without its
refresh token and locked (mode 000, which the profile forbids the agent to undo) at the CLI's
first reply, before the agent can run a command.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from qec_drift import paths

EPISODE_SECONDS = 3600  # the prompt says "about 50 minutes"; the rest is the final scoring
TOOL_CALLS = 40  # the prompt's budget: the CLI is killed at the first call past it
LOGIN_SECONDS = 60  # the login file is readable at most this long after launch
KEEP_ENV = ("HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TERM")
SECRET_DIRS = (
    ".claude",
    ".claude.json",
    ".claude.json.backup",
    ".ssh",
    ".aws",
    ".gnupg",
    ".config/gh",
    ".codex",
    ".agents",  # skills every agent on this machine shares
    ".claude-mem",
    ".netrc",
    "Library/Keychains",
    ".qec-drift-claude",  # the scaffolds' state roots: the other episodes' logins
    ".qec-drift-codex",
)


def clear(path: Path) -> None:
    """Remove a tree, read-only parts included (a uv or pip cache is read-only), and fail
    when anything is left: a rerun must not start with the files of an earlier attempt."""

    def writable(func, target, _exc) -> None:
        Path(target).parent.chmod(0o700)
        if Path(target).exists() and not Path(target).is_symlink():
            Path(target).chmod(0o700)
        func(target)

    if path.exists() or path.is_symlink():
        shutil.rmtree(path, onexc=writable)
    if path.exists():
        raise RuntimeError(f"could not clear {path}")


def fresh_dir(where: Path) -> Path:
    """A new state directory for one episode, with its own cache and temp.

    It is also the episode's ZDOTDIR. A login zsh (Codex runs every command in one) reads
    /etc/zprofile, whose path_helper moves the system directories to the front of PATH, so
    `python3` became a system Python without stim and pymatching (2026-11-03: six Codex
    episodes lost to it). The `.zprofile` here runs after it and puts the venv first again.
    """
    clear(where)  # nothing from an earlier episode survives
    where.mkdir(mode=0o700, parents=True)
    (where / "cache").mkdir(mode=0o700)
    (where / "tmp").mkdir(mode=0o700)
    venv = paths.REPO_ROOT / ".venv" / "bin"
    (where / ".zprofile").write_text(f'export PATH="{venv}:$PATH"\n')
    return where


def environment(config_dir: Path) -> dict[str, str]:
    """The CLI's environment from an allowlist: no API keys, no other secrets.

    The project's venv comes first on PATH so the agent's `python` has stim, pymatching,
    numpy, scipy and torch. Caches and temp stay with the episode. ZDOTDIR points at the
    episode directory, so a login zsh (Codex spawns one for each command, and this machine's
    startup files would fill it with keys) reads no startup file of this machine.
    """
    env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
    venv = paths.REPO_ROOT / ".venv" / "bin"
    env["PATH"] = f"{venv}:{Path.home() / '.local' / 'bin'}:/opt/homebrew/bin:/usr/bin:/bin"
    env["XDG_CACHE_HOME"] = str(config_dir / "cache")
    env["npm_config_cache"] = str(config_dir / "cache" / "npm")
    env["TMPDIR"] = str(config_dir / "tmp")
    env["TMPPREFIX"] = str(config_dir / "tmp" / "zsh")  # zsh here-documents: not /tmp/zsh
    env["ZDOTDIR"] = str(config_dir)
    return env


def own_install() -> list[Path]:
    """The benchmark's own files in the shared venv: the editable-install `.pth` (the path of
    the hidden source) and the dist-info, whose METADATA holds a copy of the README with the
    pass rule and the fault families (2026-11-04: agents listed these files)."""
    site = paths.REPO_ROOT / ".venv" / "lib"
    return sorted(site.glob("python*/site-packages/qec_drift*"))


def _sub(path: Path | str) -> str:
    return f'(subpath "{Path(path).resolve()}")'


def profile(
    workdir: Path,
    config_dir: Path,
    state_root: Path,
    login: Path,
    allow_reads: tuple[Path, ...] = (),
) -> str:
    """A sandbox-exec profile for the CLI and everything it spawns.

    Writes only in the task folder, this episode's own state directory (its cache and temp
    included), the system's per-user temp tree, and /dev. No reads of the repository outside
    the task folder and the venv, so the agent cannot read the task generator or other tasks;
    no reads of this machine's secret stores, agent configurations or session archives; no
    reads of the scaffold's other episodes under `state_root`. Reads are otherwise allowed: a
    CLI needs the system, Homebrew and its own install, and a default-deny read policy broke
    it. The network stays open, because the CLI needs the API and a sandbox-exec profile
    cannot filter by host. The login file cannot be changed, unlinked or replaced from inside.
    `allow_reads` reopens parts of a hidden tree that hold no secrets (a CLI's own install).
    Both scaffolds' state roots are hidden; this episode's own directory is reopened. The
    ancestors of the task folder and of the state directory give up their metadata only (a
    stat, not a listing): a CLI canonicalizes its working and home paths at start.
    """
    home = Path.home()
    writes = [workdir, config_dir, "/private/var/folders", "/dev"]
    deny_reads = [home / d for d in SECRET_DIRS]
    deny_reads += own_install()  # the benchmark's own install record: its README and paths
    reopen = [f"(allow file-read* {_sub(p)})" for p in allow_reads]
    ancestors = {str(p) for q in (workdir, config_dir) for p in Path(q).resolve().parents}
    parents = " ".join(f'(literal "{p}")' for p in sorted(ancestors))
    return "\n".join(
        [
            "(version 1)",
            "(allow default)",
            "(deny file-write*)",
            f"(allow file-write* {' '.join(_sub(p) for p in writes)})",
            f"(deny file-read* {_sub(paths.REPO_ROOT)})",
            f"(allow file-read* {_sub(workdir)} {_sub(paths.REPO_ROOT / '.venv')})",
            f"(deny file-read* {' '.join(_sub(p) for p in deny_reads)})",
            *reopen,
            f"(deny file-read* file-write* {_sub(state_root)})",
            f"(allow file-read-metadata {parents})",
            f"(allow file-read* file-write* {_sub(config_dir)})",
            "(deny file-write-mode file-write-flags file-write-unlink file-write-data "
            f'file-write-create file-write-owner (literal "{login}"))',
        ]
    )


def lock(login: Path) -> None:
    """Take the login away from the agent while the CLI keeps running.

    The CLIs read the token once, keep it in memory when a later read fails, and log out
    when the file is missing, is not a file, or holds no token. So the file stays and its mode
    goes to 000, from outside the sandbox. Inside the sandbox the profile denies every change
    to that path (mode, flags, data, unlink, create), so the agent cannot restore it; the
    harness runs outside the sandbox and can. Done at the first reply and by the watchdog.
    """
    if login.is_file():
        login.chmod(0)


def remove(login: Path) -> None:
    if login.is_dir():
        login.rmdir()
    elif login.exists():
        login.chmod(0o600)
        login.unlink()


def kill(proc: subprocess.Popen) -> None:
    """SIGKILL the CLI's whole process group. macOS can refuse the group (EPERM) once its
    members are exiting; the CLI itself is then killed alone (2026-11-04: a GPT-6-Astra max
    episode at the tool-call limit became an error row instead of being scored)."""
    try:
        os.killpg(proc.pid, 9)
    except (PermissionError, ProcessLookupError):
        if proc.poll() is None:
            proc.kill()


def stream(
    cmd: list[str],
    workdir: Path,
    env: dict[str, str],
    login: Path,
    replied: Callable[[str], bool],
    seconds: int = EPISODE_SECONDS,
    tools: Callable[[str], int] = lambda line: 0,
    max_tools: int = TOOL_CALLS,
) -> tuple[list[dict], int]:
    """One CLI process to its end: its JSON events (one per stdout line) and its exit code.

    `replied(line)` says whether a stdout line is the model's first reply: the login is locked
    there, and after LOGIN_SECONDS at the latest. A CLI that has written nothing at all by then
    is killed; one that is alive but still thinking is not (2026-11-03: six Haiku 5.5 max
    episodes were killed at a minute of thinking before their first reply). The
    whole process group is killed at `seconds`, and at the first tool call past `max_tools`
    (`tools(line)` counts the calls a line starts), as the task text promises: whatever
    decoder.py exists then is scored. Stderr is drained on its own thread and lands as one
    "stderr" event.
    """
    events: list[dict] = []
    lines: list[str] = []
    err_chunks: list[str] = []
    started = threading.Event()
    alive = threading.Event()  # any stdout line: the CLI is up, whether or not it has replied
    proc = subprocess.Popen(
        cmd,
        cwd=workdir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    def drain_stderr() -> None:
        err_chunks.append(proc.stderr.read() if proc.stderr else "")

    def watchdog() -> None:
        started.wait(LOGIN_SECONDS)
        lock(login)
        if not alive.is_set() and proc.poll() is None:
            events.append({"type": "harness", "note": "the CLI did not start in time"})
            kill(proc)

    def deadline() -> None:
        try:
            proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            events.append({"type": "harness", "note": "episode time limit"})
            kill(proc)

    threads = [threading.Thread(target=f, daemon=True) for f in (drain_stderr, watchdog, deadline)]
    for t in threads:
        t.start()
    assert proc.stdout is not None
    calls = 0
    for line in proc.stdout:
        lines.append(line)
        alive.set()
        if not started.is_set() and replied(line):
            lock(login)  # the agent's first command can only follow the first reply
            started.set()
        calls += tools(line)
        if calls > max_tools and proc.poll() is None:
            events.append({"type": "harness", "note": f"tool-call limit ({max_tools})"})
            kill(proc)
    proc.wait()
    for t in threads:
        t.join(timeout=5)
    for line in lines:
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"type": "unparsed", "text": line[:2000]})
    err = "".join(err_chunks)
    if err.strip():
        events.append({"type": "stderr", "text": err[-4000:]})
    return events, proc.returncode
