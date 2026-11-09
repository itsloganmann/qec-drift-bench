from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import platform
import shutil
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import numpy as np

from qec_drift.agent import awareness as aw
from qec_drift.agent import decoder_run as run
from qec_drift.agent import decoder_task as dt
from qec_drift.agent import sandbox

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "agent/noise.py",
    "agent/drift.py",
    "decoders/adaptive.py",
    "decoders/pij.py",
    "decoders/visible.py",
    "decoders/visible_state.py",
)
FIT_SECONDS = 3600
FIT_CODE = "from pathlib import Path\nfrom qec_drift.decoders.visible import fit\nfit(Path.cwd())\n"
DECODER_CODE = (
    "from pathlib import Path\nfrom qec_drift.decoders.visible_state import Decoder\n"
    "_decoder = Decoder(Path(__file__).resolve().parent)\ndef decode(det):\n"
    "    return _decoder.decode(det)\n"
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def prepare_work(visible: Path, work: Path, source: Path) -> None:
    work.mkdir(parents=True, exist_ok=False)
    for name in ("nominal.stim", "train.npz", "val.npz", "deploy.npz"):
        shutil.copyfile(visible / name, work / name)
    package = work / "qec_drift"
    for directory in ("", "agent", "decoders"):
        folder = package / directory
        folder.mkdir(exist_ok=True)
        (folder / "__init__.py").write_text("")
    for relative in SOURCE_FILES:
        shutil.copyfile(source / relative, package / relative)
    (work / "decoder.py").write_text(DECODER_CODE)


def evaluate(visible: Path, private: Path, work: Path, source: Path) -> dict:
    refs = json.loads((private / "references.json").read_text())
    result = {
        "id": visible.name,
        "reference_status": "defined" if refs else "undefined",
        "passed_absolute": False if refs else None,
        "passed_relative": False if refs else None,
    }
    prepare_work(visible, work, source)
    start = time.monotonic()
    code, output = sandbox.run(["-"], work, FIT_SECONDS, stdin=FIT_CODE)
    result["fit_seconds"] = time.monotonic() - start
    if code != 0:
        return result | {"status": "fit_timeout" if code == 124 else "fit_error", "error": output}
    state = json.loads((work / "fit.json").read_text())
    result.update(fit=state)
    if state["status"] != "ready":
        return result | {"status": state["status"]}
    raw_report = json.loads((work / "report.json").read_text())
    parsed = aw.report_from(raw_report)
    task_data = json.loads((private / "task.json").read_text())
    task = dt.Task(**task_data["task"])
    truth = dt.drift.Truth(
        **(task_data["truth"] | {"qubits": frozenset(task_data["truth"]["qubits"])})
    )
    diagnosis = aw.diagnosis(parsed, truth)
    diagnosis = {
        k: None if isinstance(v, float) and np.isnan(v) else v for k, v in diagnosis.items()
    }
    result.update(
        report=raw_report,
        diagnosis=diagnosis,
        adequate_correct=parsed["report_adequate"] == task_data["model_adequate"],
    )
    with np.load(private / "test.npz", allow_pickle=False) as data:
        det, obs = data["det"], data["obs"]
    start = time.monotonic()
    error, pred = run.score_submission(work, task, det)
    result["scoring_seconds"] = time.monotonic() - start
    if error:
        return result | {"status": "score_error", "error": error}
    rate = dt.logical_error_rate(pred, obs)
    if not refs:
        return result | {
            "status": "scored",
            "logical_error_rate": rate,
            "gap_closed": None,
            "gap_drift": None,
            "honest": None,
        }
    gap = dt.gap_closed(rate, refs)
    drift_gap = dt.gap_drift(rate, refs)
    absolute = aw.passed(diagnosis["diagnosis_correct"], gap, drift_gap)
    relative = absolute
    honest = None
    if drift_gap == drift_gap:
        honest = (refs["stale_corr"] - refs.get("adaptive_corr", refs["pij_corr"])) / (
            refs["stale_corr"] - refs["true_corr"]
        )
        relative = absolute and drift_gap >= 0.75 * honest
    return result | {
        "status": "scored",
        "logical_error_rate": rate,
        "gap_closed": None if np.isnan(gap) else gap,
        "gap_drift": None if np.isnan(drift_gap) else drift_gap,
        "honest": honest,
        "passed_absolute": bool(absolute),
        "passed_relative": bool(relative),
    }


def validate_export(export: Path) -> dict:
    manifest = json.loads((export / "scorer/manifest.json").read_text())
    for entry in manifest["tasks"]:
        for side, files in entry["files"].items():
            for name, expected in files.items():
                path = export / side / entry["id"] / name
                if sha(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
                    raise ValueError(f"Export content changed: {entry['id']}/{name}")
    return manifest


def run_study(export: Path, output: Path, manifest: dict) -> None:
    source = output / "source"
    result_path = output / "results.json"
    hashes = {}
    for relative in SOURCE_FILES:
        origin = ROOT / "src/qec_drift" / relative
        target = source / relative
        if not result_path.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, target)
        hashes[relative] = sha(target)
    state = {
        "started_utc": datetime.now(UTC).isoformat(),
        "complete": False,
        "manifest_sha256": sha(export / "scorer/manifest.json"),
        "source_sha256": hashes,
        "runner_sha256": sha(Path(__file__)),
        "fit_timeout_seconds": FIT_SECONDS,
        "score_timeout_seconds": run.SCORE_TIMEOUT,
        "all_candidates_denominator": len(manifest["tasks"]),
        "versions": {name: version(name) for name in ("numpy", "stim", "pymatching", "scipy")},
        "runtime": {
            "python": platform.python_version(),
            "os": platform.platform(),
            "machine": platform.machine(),
            "scoring_omp_threads": 2,
        },
        "attempts": [],
        "rows": [],
    }
    for name, module in [
        ("awareness", aw),
        ("decoder_task", dt),
        ("decoder_run", run),
        ("sandbox", sandbox),
    ]:
        state["source_sha256"][name] = sha(Path(module.__file__))
    if result_path.exists():
        previous = json.loads(result_path.read_text())
        for field in (
            "manifest_sha256",
            "source_sha256",
            "runner_sha256",
            "versions",
            "runtime",
            "fit_timeout_seconds",
            "score_timeout_seconds",
            "all_candidates_denominator",
        ):
            if state[field] != previous[field]:
                raise ValueError(f"Cannot resume changed study: {field}")
        state = previous
    for attempt in state["attempts"]:
        if attempt["status"] == "started":
            attempt["status"] = "interrupted"
    completed = {row["id"] for row in state["rows"]}
    if len(completed) != len(state["rows"]) or not completed <= {
        e["id"] for e in manifest["tasks"]
    }:
        raise ValueError("Invalid saved candidate identities")
    write_json(result_path, state)
    for entry in manifest["tasks"]:
        opaque = entry["id"]
        if opaque in completed:
            continue
        if any(sha(source / key) != hashes[key] for key in SOURCE_FILES):
            raise RuntimeError("Frozen baseline source changed")
        work = output / "work" / uuid4().hex
        attempt = {
            "id": opaque,
            "work": str(work.relative_to(output)),
            "status": "started",
            "started_utc": datetime.now(UTC).isoformat(),
        }
        state["attempts"].append(attempt)
        write_json(result_path, state)
        try:
            row = evaluate(
                export / "visible" / opaque,
                export / "scorer" / opaque,
                work,
                source,
            )
        except Exception as exc:
            row = {
                "id": opaque,
                "status": "exception",
                "error": f"{type(exc).__name__}: {exc}",
                "passed_absolute": False,
                "passed_relative": False,
            }
        if not json.loads((export / "scorer" / opaque / "references.json").read_text()):
            row.update(reference_status="undefined", passed_absolute=None, passed_relative=None)
        attempt.update(status=row["status"], finished_utc=datetime.now(UTC).isoformat())
        state["rows"].append(row)
        write_json(result_path, state)
        print(json.dumps(row), flush=True)
    state["complete"] = True
    state["finished_utc"] = datetime.now(UTC).isoformat()
    write_json(result_path, state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("export", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = validate_export(args.export)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_study(args.export, args.output, manifest)


if __name__ == "__main__":
    main()
