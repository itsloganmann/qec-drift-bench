from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import platform
import resource
import sys
import urllib.request
from collections.abc import Callable


def pid_namespace() -> dict | None:
    try:
        return {
            "boot": pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "namespace": os.readlink("/proc/self/ns/pid"),
        }
    except OSError:
        return None


def start_ticks(stat: bytes) -> str:
    return stat.rsplit(b")", 1)[1].split()[19].decode("ascii")


def process_identity(pid: int) -> dict | None:
    namespace = pid_namespace()
    if namespace is None:
        return None
    try:
        ticks = start_ticks(pathlib.Path(f"/proc/{pid}/stat").read_bytes())
        return {"namespace": namespace, "pid": pid, "start_ticks": ticks}
    except (OSError, IndexError, UnicodeError):
        return None


def read_relative(directory_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    with os.fdopen(fd, "rb") as handle:
        return handle.read()


def process_probe(configuration: dict) -> dict:
    identity = configuration.get("fake_process_identity")
    untested = {"readable": None, "status": "not_tested"}
    if not identity or identity["namespace"] != pid_namespace():
        return untested | {"reason": "shared_pid_namespace_unverified"}
    directory_fd = None
    try:
        directory_fd = os.open(
            f"/proc/{identity['pid']}", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        if start_ticks(read_relative(directory_fd, "stat")) != identity["start_ticks"]:
            return untested | {"reason": "owned_process_identity_changed"}
        # The verified proc directory prevents PID reuse from redirecting the environment read.
        entries = read_relative(directory_fd, "environ").split(b"\0")
        value = next(
            (x.split(b"=", 1)[1] for x in entries if x.startswith(b"QEC_PROBE_PARENT_CANARY=")),
            b"",
        )
        return {
            "readable": True,
            "matches_canary": hashlib.sha256(value).hexdigest() == configuration["canary_sha256"],
        }
    except (OSError, IndexError, UnicodeError) as error:
        return {"readable": False, "error_type": type(error).__name__}
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def run_probes(configuration: dict) -> dict:
    result = {}

    def check(name: str, read: Callable[[], bytes | str]) -> None:
        try:
            value = read()
            if isinstance(value, str):
                value = value.encode()
            result[name] = {
                "readable": True,
                "matches_canary": hashlib.sha256(value).hexdigest()
                == configuration["canary_sha256"],
            }
        except Exception as error:
            result[name] = {"readable": False, "error_type": type(error).__name__}

    check("private_label", lambda: pathlib.Path(configuration["private_file"]).read_bytes())
    check("inherited_environment", lambda: os.environ["QEC_PROBE_PARENT_CANARY"])

    def import_canary() -> str:
        spec = importlib.util.spec_from_file_location("probe_generator", configuration["generator"])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.CANARY

    check("private_generator", import_canary)
    result["private_process_environment"] = process_probe(configuration)
    check(
        "private_loopback_service",
        lambda: urllib.request.urlopen(configuration["loopback_url"], timeout=2).read(),
    )
    limits = {}
    for name in ("memory.max", "cpu.max", "pids.max"):
        try:
            limits[name] = pathlib.Path("/sys/fs/cgroup/" + name).read_text().strip()
        except OSError:
            limits[name] = None
    result["resources"] = {
        "platform": platform.platform(),
        "uid": os.getuid(),
        "cpu_count": os.cpu_count(),
        "cgroup": limits,
        "rlimit_cpu": list(resource.getrlimit(resource.RLIMIT_CPU)),
        "rlimit_as": list(resource.getrlimit(resource.RLIMIT_AS)),
    }
    return result


if __name__ == "__main__":
    print(json.dumps(run_probes(json.loads(sys.argv[1]))))
