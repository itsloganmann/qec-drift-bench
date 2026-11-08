"""Export local Kaggle fixtures into separate visible and scorer-only directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import uuid
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

import numpy as np
import stim
from run_grid import gate

from qec_drift.agent import decoder_task as dt
from qec_drift.agent import drift, noise

VISIBLE = {"nominal.stim", "train.npz", "val.npz", "deploy.npz"}


def fingerprint(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": digest}


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def checked_references(tasks: list[dt.Task], raw: bytes) -> dict:
    table = json.loads(raw)
    if not isinstance(table, dict):
        raise ValueError("references must be a task-to-rates mapping")
    selected = {}
    for task in tasks:
        refs = table.get(task.name)
        required = {"nominal", "nominal_corr", "true", "true_corr", "pij_plain", "pij_corr"}
        if task.drift:
            required.add("stale_corr")
        if not task.stationary:
            required |= {"adaptive_corr", "window_corr"}
        if not isinstance(refs, dict) or not required <= refs.keys():
            raise ValueError(f"missing reference rates for {task.name}")
        if any(
            type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
            for v in refs.values()
        ):
            raise ValueError(f"invalid reference rate for {task.name}")
        if bool(task.drift) != ("stale_corr" in refs) or (task.drift and refs["stale_corr"] <= 0):
            raise ValueError(f"invalid stale reference for {task.name}")
        selected[task.name] = refs
    keep, reasons = gate(selected)
    if set(keep) != set(selected):
        raise ValueError("task gate failed:\n" + "\n".join(reasons))
    return selected


def checked_arrays(path: Path, shapes: dict[str, tuple[int, ...]]) -> None:
    with np.load(path, allow_pickle=False) as data:
        if set(data.files) != set(shapes):
            raise ValueError(f"unexpected fields in {path.name}")
        for name, shape in shapes.items():
            array = data[name]
            valid_type = array.dtype.kind in "iu" if name == "regime" else array.dtype == bool
            if array.shape != shape or not valid_type:
                raise ValueError(f"invalid array {path.name}:{name}")
            if name == "regime" and np.any(array < 0):
                raise ValueError("negative test regime")


def check_visible(task: dt.Task, folder: Path) -> int:
    if {p.name for p in folder.iterdir()} != VISIBLE:
        raise ValueError("visible bundle contains unexpected files")
    if any(p.is_symlink() or not p.is_file() for p in folder.iterdir()):
        raise ValueError("visible bundle requires regular files")
    circuit = stim.Circuit.from_file(folder / "nominal.stim")
    if (folder / "nominal.stim").read_text() != str(
        dt.nominal(task.d)
    ) or circuit.num_observables != 1:
        raise ValueError("visible circuit must be the nominal circuit")
    for split in ("train", "val", "deploy"):
        shots = (task.deploy or dt.SHOTS["deploy"]) if split == "deploy" else dt.SHOTS[split]
        shapes = {"det": (shots, circuit.num_detectors)}
        if split != "deploy":
            shapes["obs"] = (shots, 1)
        checked_arrays(folder / f"{split}.npz", shapes)
    return circuit.num_detectors


def export(tasks: list[dt.Task], references: Path, visible: Path, scorer: Path) -> dict:
    names = [task.name for task in tasks]
    if not names or len(set(names)) != len(names):
        raise ValueError("select at least one task, without duplicates")
    for root in (visible, scorer):
        if root.exists() or root.is_symlink():
            raise FileExistsError(f"output already exists: {root}")
    visible, scorer = visible.resolve(), scorer.resolve()
    if visible == scorer or visible in scorer.parents or scorer in visible.parents:
        raise ValueError("visible and scorer roots must be separate, non-nested directories")
    raw = references.read_bytes()
    refs = checked_references(tasks, raw)
    manifest = {
        "schema_version": 1,
        "kind": "local_development_fixture",
        "reference_rates_recomputed": False,
        "references_sha256": hashlib.sha256(raw).hexdigest(),
        "versions": {name: version(name) for name in ("numpy", "stim", "pymatching")},
        "generator_sha256": {
            module.__name__: fingerprint(Path(module.__file__))["sha256"]
            for module in (dt, drift, noise)
        },
        "shots": dict(dt.SHOTS),
        "seeds": dict(dt.SEEDS),
        "tasks": [],
    }
    created, created_parents = [], []
    try:
        for root in (visible, scorer):
            missing, parent = [], root.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir(mode=0o700)
                created_parents.append(parent)
            root.mkdir(mode=0o700)
            created.append(root)
        if any(visible.samefile(p) for p in (scorer, *scorer.parents)) or any(
            scorer.samefile(p) for p in visible.parents
        ):
            raise ValueError("output directories overlap on this filesystem")
        for task in tasks:
            identity = uuid.uuid4().hex
            agent_dir, private_dir = visible / identity, scorer / identity
            agent_dir.mkdir(mode=0o700)
            private_dir.mkdir(mode=0o700)
            dt.write_agent_files(task, agent_dir)
            detectors = check_visible(task, agent_dir)
            det, obs, regime = dt.test_sample(task)
            test = private_dir / "test.npz"
            np.savez_compressed(test, det=det, obs=obs, regime=regime)
            checked_arrays(
                test,
                {
                    "det": (dt.SHOTS["test"], detectors),
                    "obs": (dt.SHOTS["test"], 1),
                    "regime": (dt.SHOTS["test"],),
                },
            )
            truth = asdict(task.truth)
            truth["qubits"] = sorted(truth["qubits"])
            write_json(
                private_dir / "task.json",
                {
                    "name": task.name,
                    "task": asdict(task),
                    "truth": truth,
                    "model_adequate": task.model_adequate,
                },
            )
            write_json(private_dir / "references.json", refs[task.name])
            manifest["tasks"].append(
                {
                    "id": identity,
                    "files": {
                        side: {p.name: fingerprint(p) for p in sorted(root.iterdir())}
                        for side, root in (("visible", agent_dir), ("scorer", private_dir))
                    },
                }
            )
            print(f"exported {len(manifest['tasks'])}/{len(tasks)}", flush=True)
        write_json(scorer / "manifest.json", manifest)
    except BaseException:
        for root in reversed(created):
            if root.exists():
                shutil.rmtree(root)
        for parent in reversed(created_parents):
            if parent.exists():
                parent.rmdir()
        raise
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--visible-out", type=Path, required=True)
    parser.add_argument("--scorer-out", type=Path, required=True)
    parser.add_argument("--set", choices=sorted(dt.TASK_SETS), default="launch2core")
    args = parser.parse_args()
    export(dt.TASK_SETS[args.set](), args.references, args.visible_out, args.scorer_out)


if __name__ == "__main__":
    main()
