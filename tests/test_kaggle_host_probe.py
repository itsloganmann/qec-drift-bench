from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kaggle"))
import kaggle_host_probe as probe


class DeliberatelyUnsafeLocalEnvironment:
    def run(self, command: list[str]) -> SimpleNamespace:
        result = subprocess.run(
            [sys.executable, *command[1:]],
            capture_output=True,
            text=True,
            timeout=15,
            env={"QEC_PROBE_PARENT_CANARY": os.environ["QEC_PROBE_PARENT_CANARY"]},
        )
        return SimpleNamespace(exit_code=result.returncode, stdout=result.stdout)


def test_unisolated_control_exposes_only_synthetic_canaries() -> None:
    previous = os.environ.get("QEC_PROBE_PARENT_CANARY")
    result = probe.run_probe(DeliberatelyUnsafeLocalEnvironment())
    assert result["status"] == "boundary_failed"
    assert {
        "private_label",
        "private_generator",
        "inherited_environment",
        "private_loopback_service",
    } <= set(result["leaked_canary_surfaces"])
    assert result["observations"]["private_process_environment"]["readable"] in (True, False, None)
    assert not result["scored_runs_authorized"]
    assert not result["resource_enforcement_verified"]
    assert os.environ.get("QEC_PROBE_PARENT_CANARY") == previous


def test_worker_failure_never_authorizes_scoring() -> None:
    environment = SimpleNamespace(run=lambda command: SimpleNamespace(exit_code=1, stdout=""))
    result = probe.run_probe(environment)
    assert result["status"] == "probe_failed"
    assert not result["scored_runs_authorized"]


def test_process_launch_failure_cleans_prior_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    servers = []
    original = probe.ThreadingHTTPServer

    def server(*args: Any, **kwargs: Any) -> probe.ThreadingHTTPServer:
        instance = original(*args, **kwargs)
        servers.append(instance)
        return instance

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("synthetic launch failure")

    monkeypatch.setenv("QEC_PROBE_PARENT_CANARY", "previous")
    monkeypatch.setattr(probe, "ThreadingHTTPServer", server)
    monkeypatch.setattr(probe.subprocess, "Popen", fail)
    with pytest.raises(OSError, match="synthetic launch"):
        probe.run_probe(None)
    assert os.environ["QEC_PROBE_PARENT_CANARY"] == "previous"
    assert servers[0].socket.fileno() == -1


def test_namespace_mismatch_never_opens_process(monkeypatch: pytest.MonkeyPatch) -> None:
    import kaggle_probe_worker as worker

    monkeypatch.setattr(worker, "pid_namespace", lambda: {"boot": "other", "namespace": "pid:[2]"})
    monkeypatch.setattr(worker.os, "open", lambda *a, **k: pytest.fail("process opened"))
    result = worker.process_probe(
        {"fake_process_identity": {"namespace": {"boot": "host", "namespace": "pid:[1]"}}}
    )
    assert result["readable"] is None
    assert result["status"] == "not_tested"


@pytest.mark.parametrize(
    "matching_identity,environment",
    [(False, b""), (True, b"OTHER=synthetic\0"), (True, b"QEC_PROBE_PARENT_CANARY=canary\0")],
)
def test_process_identity_checked_before_environment(
    monkeypatch: pytest.MonkeyPatch, matching_identity: bool, environment: bytes
) -> None:
    import kaggle_probe_worker as worker

    namespace = {"boot": "host", "namespace": "pid:[1]"}
    reads = []
    fields = ["S"] + ["0"] * 18 + ["12" if matching_identity else "13"]

    def read(fd: int, name: str) -> bytes:
        reads.append(name)
        return ("42 (fake) " + " ".join(fields)).encode() if name == "stat" else environment

    monkeypatch.setattr(worker, "pid_namespace", lambda: namespace)
    monkeypatch.setattr(worker.os, "open", lambda *a, **k: 10)
    monkeypatch.setattr(worker.os, "close", lambda fd: None)
    monkeypatch.setattr(worker, "read_relative", read)
    result = worker.process_probe(
        {
            "fake_process_identity": {"namespace": namespace, "start_ticks": "12", "pid": 42},
            "canary_sha256": hashlib.sha256(b"canary").hexdigest(),
        }
    )
    if not matching_identity:
        assert reads == ["stat"]
        assert result["readable"] is None
    else:
        assert reads == ["stat", "environ"]
        assert result["readable"] is True
        assert result["matches_canary"] == (b"QEC_PROBE_PARENT_CANARY=" in environment)
