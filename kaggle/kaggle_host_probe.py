from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from contextlib import ExitStack
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from kaggle_probe_worker import process_identity


def restore_environment(previous: str | None) -> None:
    if previous is None:
        os.environ.pop("QEC_PROBE_PARENT_CANARY", None)
    else:
        os.environ["QEC_PROBE_PARENT_CANARY"] = previous


def stop_process(process: subprocess.Popen) -> None:
    try:
        process.kill()
    finally:
        process.wait(timeout=5)


def run_probe(environment: Any) -> dict:
    token = secrets.token_hex(32)
    canary = token.encode()
    previous = os.environ.get("QEC_PROBE_PARENT_CANARY")
    with ExitStack() as cleanup:
        cleanup.callback(restore_environment, previous)
        os.environ["QEC_PROBE_PARENT_CANARY"] = token
        directory = cleanup.enter_context(
            tempfile.TemporaryDirectory(prefix="qec-synthetic-private-")
        )
        private = Path(directory)
        (private / "labels-canary").write_bytes(canary)
        (private / "labels-canary").chmod(0o600)
        (private / "generator-canary.py").write_text("CANARY = " + repr(token) + "\n")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(canary)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cleanup.callback(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cleanup.callback(thread.join, timeout=5)
        cleanup.callback(server.shutdown)
        fake_process = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(60)"],
            env={"QEC_PROBE_PARENT_CANARY": token},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cleanup.callback(stop_process, fake_process)
        if fake_process.poll() is not None:
            raise RuntimeError("Synthetic process ended before probe")
        configuration = {
            "canary_sha256": hashlib.sha256(canary).hexdigest(),
            "private_file": str(private / "labels-canary"),
            "generator": str(private / "generator-canary.py"),
            "fake_process_identity": process_identity(fake_process.pid),
            "loopback_url": f"http://127.0.0.1:{server.server_port}/canary",
        }
        script = Path(__file__).with_name("kaggle_probe_worker.py").read_text()
        response = environment.run(["python3", "-c", script, json.dumps(configuration)])
        if response.exit_code != 0:
            return {
                "status": "probe_failed",
                "exit_code": response.exit_code,
                "scored_runs_authorized": False,
            }
        observations = json.loads(response.stdout)
        cases = [
            value for value in observations.values() if isinstance(value.get("readable"), bool)
        ]
        leaked = [name for name, value in observations.items() if value.get("matches_canary")]
        status = "no_canary_exposure_observed" if len(cases) == 5 else "probe_incomplete"
        return {
            "checked_utc": datetime.now(UTC).isoformat(),
            "environment_class": type(environment).__module__ + "." + type(environment).__name__,
            "status": "boundary_failed" if leaked else status,
            "scored_runs_authorized": False,
            "observations": observations,
            "leaked_canary_surfaces": leaked,
            "all_five_probes_observed": len(cases) == 5,
            "resource_enforcement_verified": False,
            "note": (
                "Synthetic canaries only. Interpret denials in the actual hosted environment. "
                "Resource enforcement and known-decoder parity remain separate gates."
            ),
        }


if __name__ == "__main__":
    from kaggle_benchmarks import envs

    result = run_probe(envs.current)
    print(json.dumps(result, indent=2, allow_nan=False))
