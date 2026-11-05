"""Run model-written Python where it can read only the Python install, the virtual environment, its
own work folder and the paths a caller names; write only in its work folder and the paths a caller
names; and use no network. The environment is clean, so no API key reaches it.

macOS `sandbox-exec` does the locking with an allowlist profile (`deny default`). The harness
never writes into the work folder while the agent's code can run there: the code arrives on stdin
and the scorer's files live in a harness-owned folder that the agent's earlier code could not name.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from qec_drift import paths

OUTPUT_LIMIT = 5000
SYSTEM_READ = (
    "/usr/lib",
    "/usr/share",
    "/System",
    "/Library/Frameworks",
    "/private/var/db/dyld",
    "/private/etc/localtime",
    "/private/var/db/timezone",
    "/dev",
)


def _sub(path: Path | str) -> str:
    return f'(subpath "{Path(path).resolve() if str(path).startswith("/") else path}")'


def profile(workdir: Path, read: Sequence[Path] = (), write: Sequence[Path] = ()) -> str:
    base = Path(sys.base_prefix).resolve()
    venv = (paths.REPO_ROOT / ".venv").resolve()
    reads = [workdir, base, venv, *read, *SYSTEM_READ]
    writes = [workdir, "/dev", *write]
    return "\n".join(
        [
            "(version 1)",
            "(deny default)",
            f"(allow process-exec* {_sub(base)} {_sub(venv)})",
            "(allow process-fork)",
            "(allow signal (target self))",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow ipc-posix-shm)",
            "(allow ipc-posix-sem)",
            "(allow file-read-metadata)",
            '(allow file-read* (literal "/"))',  # Python lists the root at start-up
            f"(allow file-read* {' '.join(_sub(p) for p in reads)})",
            f"(allow file-write* {' '.join(_sub(p) for p in writes)})",
            "(deny network*)",
        ]
    )


def run(
    args: Sequence[str],
    workdir: Path,
    timeout: int,
    *,
    stdin: str | None = None,
    read: Sequence[Path] = (),
    write: Sequence[Path] = (),
) -> tuple[int, str]:
    """Run `python args` in the sandbox. Returns (exit code, the last OUTPUT_LIMIT chars).

    `stdin` is the program text when `args` is ["-"]. `read` and `write` name extra folders.
    The process gets its own session, and the whole session is killed when the call returns, so
    no child the code left behind can touch the work folder after the harness has read it.
    """
    workdir = Path(workdir).resolve()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(workdir), "OMP_NUM_THREADS": "2"}
    cmd = ["sandbox-exec", "-p", profile(workdir, read, write), sys.executable, *args]
    proc = subprocess.Popen(
        cmd,
        cwd=workdir,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(stdin, timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_session(proc.pid)
        out, _ = proc.communicate()
        out, code = (out or "") + f"\n[timed out after {timeout} s]", 124
    finally:
        _kill_session(proc.pid)
    return code, (out or "")[-OUTPUT_LIMIT:]


def _kill_session(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
