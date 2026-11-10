"""Freeze private transcript inputs for the finite failure-atlas review.

Outputs contain private transcripts. Keep them outside the published tree.
The current development cohort retains its existing v2 judge keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import judge_transcripts as judge
import pyarrow.parquet as pq

from qec_drift.agent import attempts, transcripts
from qec_drift.scoring import failure_modes_decoder as fm
from qec_drift.scoring import taxonomy as tx

ROOT = Path(__file__).resolve().parents[1]
COHORTS = (
    "agent_decoder",
    "agent_drift",
    "agent_hard",
    "agent_hard2",
    "agent_launch",
    "agent_trial",
)
EXTRA_PROTOCOL = "atlas-archive-fresh-v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def family(row: dict) -> str:
    drift = str(row.get("drift") or "")
    if "+" in drift:
        return "combined faults"
    for token, name in (
        ("gwander", "moving gates"),
        ("wander", "moving qubits"),
        ("patch", "spatial patch"),
        ("bq", "local qubit"),
        ("bg", "local gates"),
        ("meas", "measurement"),
        ("tls", "telegraph noise"),
    ):
        if token in drift:
            return name
    return "adequate nominal" if not drift and row.get("scenario") == "none" else "other mismatch"


def facts(row: dict) -> str:
    names = (
        "d",
        "scenario",
        "drift",
        "outcome",
        "stop",
        "turns",
        "seconds",
        "score_error",
        "reported",
        "report_adequate",
        "report_scope",
        "report_stationary",
        "report_qubits",
        "report_mechanism",
        "truth_scope",
        "truth_stationary",
        "truth_qubits",
        "truth_mechanism",
        "diagnosis_correct",
        "gap_closed",
        "gap_drift",
        "honest",
    )
    diagnosis_note = (
        "Diagnosis was not required in this earlier task. "
        "Treat it as satisfied for the joint rule, "
        "and do not infer a diagnosis failure from missing fields."
        if row.get("diagnosis_correct") is None
        else "Diagnosis was required and was measured for this task."
    )
    metric_note = (
        "A missing historical gap_drift or honest metric is not a failure. "
        "Apply drift recovery requirements only to measured metrics. "
        "If gap_drift is missing, repair uses gap_closed only. "
        "If honest is missing, omit the relative-to-honest condition."
    )
    return (
        "The archived task prompt governs required files, reports, and budgets. "
        "Do not impose the generic introduction's file list or report contract on an "
        "earlier pilot. Treat a missing file as an environment failure only if the "
        "archived task actually promised it.\n"
        + metric_note
        + "\n"
        + diagnosis_note
        + "\n"
        + "\n".join(f"{name}: {row.get(name)}" for name in names)
        + (
            "\nA good decoder requires gap_closed >= 0.5 and, for drift, gap_drift >= 0.5 "
            "and >= 0.75 * honest. Diagnosis requires correct scope, stationarity, and "
            "at least half the changed-qubit localization. The mechanism is diagnostic only."
        )
    )


def extra_payload(row: dict, rec: dict, arm: str) -> tuple[str, bool]:
    rendered = transcripts.render_record(dict(rec, model="the agent", effort=None))
    text = judge.mask_identifiers(rendered, rec, arm)
    truncated = len(text) > judge.HEAD + judge.TAIL
    if truncated:
        text = text[: judge.HEAD] + "\n[... middle cut ...]\n" + text[-judge.TAIL :]
    return "FACTS\n" + facts(row) + "\nTRANSCRIPT\n" + text, truncated


def extra_key(text: str) -> str:
    return hashlib.sha256((EXTRA_PROTOCOL + judge.key(text)).encode()).hexdigest()


def public_facts(row: dict, rec: dict, cohort: str, arm: str, rid: str) -> dict:
    f = tx.features(rec)
    return dict(
        run_id=rid,
        cohort=cohort,
        arm=arm,
        family=family(row),
        distance=row.get("d"),
        diagnosis_correct=row.get("diagnosis_correct"),
        reported=row.get("reported"),
        mechanism_correct=row.get("mechanism_correct"),
        localization=row.get("localization"),
        gap_closed=row.get("gap_closed"),
        gap_drift=row.get("gap_drift"),
        score_error=bool(row.get("score_error")),
        budget_hit=f.budget_hit,
        transcript_available=bool(rec),
    )


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def collect(output: Path, study: Path, current_inputs: Path | None = None) -> None:
    if output.exists():
        raise FileExistsError("Use a new output directory to preserve frozen inputs")
    output.mkdir(parents=True)
    rows, work, source_hashes = [], [], {}
    # Existing judgments are read by exact current key, never by arm/task alone.
    current = (
        judge.episodes()
        if current_inputs is None
        else [
            (r["arm"], r["task"], r["key"], r["payload"])
            for r in map(json.loads, current_inputs.read_text().splitlines())
            if r["cohort"] == "agent_launch2"
        ]
    )
    if current_inputs is not None:
        if any(
            r["protocol"] != judge.PROTOCOL
            for r in map(json.loads, current_inputs.read_text().splitlines())
            if r["cohort"] == "agent_launch2"
        ):
            raise ValueError("Saved current protocol differs from the current judge protocol")
        old = json.loads(current_inputs.with_name("inventory.json").read_text())
        for name, expected in old["source_hashes"].items():
            if name.startswith(("data/agent_launch2/", "trajectories/agent_launch2/")):
                if sha(ROOT / name) != expected:
                    raise ValueError("Frozen current inputs no longer match the source artifacts")
    for arm, task, key, text in current:
        if key != judge.key(text):
            raise ValueError("Saved current payload does not match current judge settings")
        work.append(
            dict(
                cohort="agent_launch2",
                arm=arm,
                task=task,
                key=key,
                protocol=judge.PROTOCOL,
                payload=text,
            )
        )
    indexed = {(r["arm"], r["task"]): r for r in work}
    cohorts = (*COHORTS, "agent_launch2")
    for cohort in cohorts:
        base = ROOT / "data" / cohort
        for table in sorted(base.glob("*.parquet")):
            if table.stem.endswith(("_taxonomy", "_failure_modes")):
                continue
            source_hashes[str(table.relative_to(ROOT))] = sha(table)
            scores = pq.read_table(table).to_pylist()
            archive = ROOT / "trajectories" / cohort / f"decoder_{table.stem}.jsonl.gz"
            if cohort == "agent_decoder" and not archive.exists():
                archive = ROOT / "trajectories" / f"decoder_{table.stem}.jsonl.gz"
            recs = attempts.select(transcripts.records(archive), scores) if archive.exists() else {}
            labels_path = table.with_name(table.stem + "_taxonomy.parquet")
            if labels_path.exists():
                source_hashes[str(labels_path.relative_to(ROOT))] = sha(labels_path)
            labels = (
                attempts.select(pq.read_table(labels_path).to_pylist(), scores)
                if labels_path.exists()
                else {}
            )
            for r in scores:
                task, arm = r["task"], table.stem
                rec = recs.get(task, {})
                rid = f"{cohort}-{len(rows) + 1:04}"
                label = labels.get(task, {}).get("label")
                if not label:
                    label = "nominal_unchanged" if r.get("agree_nominal_plain", 0) == 1 else None
                item = public_facts(r, rec, cohort, arm, rid) | dict(
                    rule_label=label,
                    fix_good=labels.get(task, {}).get("verdict_rel")
                    in ("passed", "missed_diagnosis"),
                )
                if cohort == "agent_launch2":
                    entry = indexed.get((arm, task))
                    if entry is None:
                        raise ValueError("Current score row has no frozen current review input")
                elif rec:
                    span = (r.get("ref_stale_corr") or 0) - (r.get("ref_true_corr") or 0)
                    known = r.get("ref_adaptive_corr")
                    known = r.get("ref_pij_corr") if known is None else known
                    r["honest"] = (
                        ((r.get("ref_stale_corr", 0) - known) / span)
                        if known is not None and span > 0
                        else None
                    )
                    text, cut = extra_payload(r, rec, arm)
                    entry = dict(
                        cohort=cohort,
                        arm=arm,
                        task=task,
                        key=extra_key(text),
                        protocol=EXTRA_PROTOCOL,
                        payload=text,
                        whole_view_cut=cut,
                    )
                    work.append(entry)
                else:
                    entry = None
                if entry:
                    item.update(review_key=entry["key"], protocol=entry["protocol"])
                    entry["run_id"] = rid
                rows.append(item)
            if archive.exists():
                source_hashes[str(archive.relative_to(ROOT))] = sha(archive)
    manifest = json.loads((study / "candidates.json").read_text())
    candidates = {r["id"]: r for r in manifest["candidates"]}
    state = json.loads((study / "models/results.json").read_text())
    source_hashes["fresh_model_results"] = sha(study / "models/results.json")
    for pair in state["pairs"]:
        if not pair["attempts"]:
            continue
        for attempt in pair["attempts"]:
            result = attempt["result"]
            directory = study / attempt["archive"]
            for name, expected in result["artifact_sha256"].items():
                if sha(directory / name) != expected:
                    raise ValueError("Fresh attempt artifact hash mismatch")
            launch = json.loads((directory / "launch.json").read_text())
            events = [json.loads(s) for s in (directory / "events.jsonl").read_text().splitlines()]
            score = result.get("score", {})
            workdir = Path(result["workdir"])
            source = workdir / "decoder.py"
            src = source.read_text() if source.exists() else ""
            candidate = candidates[pair["id"]]
            arm_spec = manifest["arms"][pair["arm_index"]]
            arm = "_".join(
                [
                    arm_spec["model"].replace("-", "_").replace(".", "_"),
                    arm_spec["effort"],
                    arm_spec["backend"],
                ]
            )
            r = candidate["task"] | score.get("parsed_report", {}) | score.get("diagnosis", {})
            r.update(
                outcome="submitted",
                stop=result["summary"]["stop"],
                turns=result["turns"],
                reported=score.get("reported"),
                seconds=result["seconds"],
                honest=score.get("honest"),
                score_error=score.get("error", ""),
                gap_closed=score.get("gap_closed"),
                gap_drift=score.get("gap_drift"),
            )
            rec = dict(
                task="fresh candidate",
                model=arm_spec["model"],
                scaffold="codex",
                trace_kind="codex_stream",
                prompt=launch["prompt"],
                events=events,
                decoder_src=src,
                report=score.get("report"),
            )
            rid = f"fresh-{len(rows) + 1:04}"
            valid = attempt["status"] == "valid"
            fitted = fm.is_fitted(src, r["d"]) if src else False
            leaf, _ = fm.classify_decoder(
                has_decoder=bool(src),
                scored=score.get("status") == "scored",
                gap=score.get("gap_closed") or 0,
                fitted=fitted,
                correlated="enable_correlations" in src,
                ran=valid,
            )
            verdict = (
                "passed"
                if score.get("passed_relative")
                else ("missed_fix" if r.get("diagnosis_correct") else "missed_both")
            )
            if not r.get("diagnosis_correct") and score.get("status") == "scored":
                gap = score.get("gap_closed")
                drift_gap = score.get("gap_drift")
                fixed = (
                    gap is not None
                    and gap >= 0.5
                    and (
                        drift_gap is None
                        or (drift_gap >= 0.5 and drift_gap >= 0.75 * (score.get("honest") or 0))
                    )
                )
                if fixed:
                    verdict = "missed_diagnosis"
            label, _ = tx.label(
                leaf,
                verdict,
                ran=valid,
                budget_hit=tx.features(rec).budget_hit or result["turns"] >= 40,
            )
            text, cut = extra_payload(r, rec, arm)
            k = extra_key(text)
            work.append(
                dict(
                    cohort="fresh",
                    arm=arm,
                    task=pair["id"],
                    key=k,
                    protocol=EXTRA_PROTOCOL,
                    payload=text,
                    run_id=rid,
                    whole_view_cut=cut,
                )
            )
            rows.append(
                public_facts(r, rec, "fresh", arm, rid)
                | dict(
                    rule_label=label,
                    fix_good=verdict in ("passed", "missed_diagnosis"),
                    review_key=k,
                    protocol=EXTRA_PROTOCOL,
                    rule_basis="later_source_snapshot_not_archive_bound",
                    decoder_snapshot_sha256=hashlib.sha256(src.encode()).hexdigest(),
                )
            )
    for name in ("scripts/judge_transcripts.py", "scripts/failure_atlas_inputs.py"):
        source_hashes[name] = sha(ROOT / name)
    (output / "inventory.json").write_text(
        json.dumps(clean(dict(rows=rows, source_hashes=source_hashes)), indent=2, allow_nan=False)
    )
    with (output / "inputs.jsonl").open("w") as f:
        for r in work:
            f.write(json.dumps(r, allow_nan=False) + "\n")
    print(json.dumps(dict(rows=len(rows), inputs=len(work), output=str(output))), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--current-inputs", type=Path)
    args = parser.parse_args()
    collect(args.output, args.study, args.current_inputs)
