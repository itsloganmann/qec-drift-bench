"""Render the historical and current failure analysis from verified evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[1]
COHORTS = {
    "fresh": "Fresh-seed replication",
    "agent_launch2": "Development evaluation",
    "agent_launch": "Earlier evaluation",
    "agent_decoder": "Decoder pilot",
    "agent_drift": "Drift pilot",
    "agent_hard": "Hard-task pilot",
    "agent_hard2": "Hard-task follow-up",
    "agent_trial": "Single-task pilot",
}
FAMILIES = {
    "adequate": "Adequate nominal model",
    "meas": "Readout drift",
    "bq": "Local qubit drift",
    "tls": "Switching drift",
    "patch": "Spatial patch",
    "wander": "Moving qubit fault",
    "gwander": "Moving gate fault",
    "bg+wander": "Gate drift and moving fault",
    "bq+wander": "Qubit drift and moving fault",
}
EXCERPT_TERMS = {
    "execution": ("tool-call limit", "timed out after", "modulenotfounderror", "turn.failed"),
    "diagnosis": ("affected_qubits", "report_stationary", "jaccard", "stationary"),
    "repair": ("enable_correlations", "detector_error_model", "decode_batch", "gap_closed"),
    "external": ("modulenotfounderror", "turn.failed", "at capacity", "controller interrupted"),
}
PRIVATE_TEXT = re.compile(
    r"(?:credential|authorization|bearer\s|api[_ -]?key|[a-z0-9_-]*token[ =:]|/users/|\.env\b)",
    re.I,
)


def load(path: Path):
    return json.loads(path.read_bytes())


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def family_name(family: str) -> str:
    kind = family.removeprefix("none:")
    return FAMILIES.get(kind, kind.replace("_", " ").replace(":", " · "))


def legacy_configuration(arm: str) -> str:
    name = arm.removesuffix("_codex").removesuffix("_claude").removesuffix("_api")
    model, sep, effort = name.rpartition("_")
    if sep and effort in {"low", "medium", "high", "xhigh", "max", "ultra"}:
        return f"{model.replace('_', ' ')} · {effort}"
    return name.replace("_", " ")


def check(kind: str, title: str, result: str) -> dict:
    return {"kind": kind, "title": title, "result": result}


def metric(value, label: str) -> str:
    return f"{label} {value:.3f}." if value is not None else ""


def failed_checks(row: dict) -> list[dict]:
    if row["rule"] == "invalid_run":
        return [check("external", "External interruption or eligibility", row["status"])]
    if row["rule"] == "passed":
        if row["review"] in {"passed", "invalid_run"}:
            return []
        return [check("repair", "Review disagreement", "The frozen joint criterion passed.")]
    checks = []
    if row["diagnosis"] is False:
        detail = metric(row.get("localization"), "Localization overlap")
        checks.append(
            check("diagnosis", "Fault diagnosis", f"Diagnosis criterion failed. {detail}".strip())
        )
    if row["score_error"]:
        if row["rule"] == "out_of_budget":
            title = "Submit a scorable decoder within budget"
        else:
            title = "Submit a scorable decoder"
        checks.append(check("execution", title, "The episode finished without a scorable decoder."))
    elif row["repair_met"] is False:
        gap = metric(row.get("gap_closed"), "Nominal-gap recovery")
        drift = metric(row.get("gap_drift"), "Drift recovery")
        floor = metric(row.get("drift_floor"), "Required drift recovery")
        result = " ".join(text for text in (gap, drift, floor) if text)
        checks.append(
            check("repair", "Decoder recovery", result or "The saved repair criterion failed.")
        )
    if not checks:
        checks.append(
            check("repair", "Stored failure verdict", "No separate failed check was recorded.")
        )
    # Put the measured repair step first when the primary failure is about repair.
    if row["rule"] in {"plain_matching", "under_adapted", "nominal_unchanged", "harmful_decoder"}:
        checks.sort(key=lambda item: item["kind"] != "repair")
    return checks


def exact_excerpts(records, checks: list[dict]) -> dict:
    """Keep literal, chronological excerpts and mark automatic associations."""
    terms = {item["kind"]: EXCERPT_TERMS[item["kind"]] for item in checks}
    matches: dict[str, list] = {kind: [] for kind in terms}
    for number, role, text in records:
        if all(len(rows) >= 3 for rows in matches.values()):
            break
        for line in text.splitlines():
            if not line.strip():
                continue
            folded = line.lower()
            for kind, probes in terms.items():
                hits = matches[kind]
                if len(hits) >= 3:
                    continue
                for probe in probes:
                    position = folded.find(probe)
                    if position < 0:
                        continue
                    excerpt = line[max(0, position - 120) : position + len(probe) + 150].strip()
                    if not PRIVATE_TEXT.search(excerpt) and all(
                        hit["text"] != excerpt for hit in hits
                    ):
                        hits.append(
                            {
                                "position": number,
                                "role": role,
                                "text": excerpt,
                                "evidence": "Related recorded excerpt",
                            }
                        )
                    break
    return matches


def historical_rows(evidence: Path, include_traces: bool) -> list[dict]:
    origin = evidence / "atlas-20261110-contracts"
    frozen = load(origin / "inventory.json")["rows"]
    audit = load(origin / "private-run-audit.json")
    if len(frozen) != 760 or len(audit) != len(frozen):
        raise ValueError("Historical evidence does not cover all 760 original rows")
    if any(
        row != {k: v for k, v in saved.items() if k != "judgment"}
        for row, saved in zip(frozen, audit, strict=True)
    ):
        raise ValueError("Historical review rows differ from the frozen inventory")
    inputs_path = origin / "inputs.jsonl"
    result = []
    with inputs_path.open(encoding="utf-8") as inputs:
        indexed = {
            item["run_id"]: (number, item)
            for number, line in enumerate(inputs, 1)
            if (item := json.loads(line))["cohort"] != "fresh"
        }
    for item in audit:
        if item["cohort"] == "fresh":
            continue
        identity = item["run_id"]
        number, source = indexed.pop(identity)
        judgment = item["judgment"]
        if (source["key"], source["protocol"]) != (item["review_key"], item["protocol"]):
            raise ValueError(f"Historical review input does not match {identity}")
        if (judgment["key"], judgment["protocol"]) != (source["key"], source["protocol"]):
            raise ValueError(f"Historical judgment does not match {identity}")
        score_error = item["score_error"] or item["rule_label"] in {
            "no_submission",
            "broken_decoder",
            "out_of_budget",
        }
        row = {
            "id": identity,
            "cohort": item["cohort"],
            "family": family_name(item["family"]),
            "configuration": legacy_configuration(item["arm"]),
            "task": source["task"],
            "rule": item["rule_label"],
            "review": judgment["label"],
            "status": "Historical eligibility exclusion",
            "diagnosis": item["diagnosis_correct"],
            "repair_met": None if score_error else item["fix_good"],
            "score_error": score_error,
            "gap_closed": item["gap_closed"],
            "gap_drift": item["gap_drift"],
            "localization": item["localization"],
            "selected": True,
        }
        if include_traces:
            row["checks"] = failed_checks(row)
            if row["checks"]:
                _, _, rendered = source["payload"].partition("\nTRANSCRIPT\n")
                source_lines = (
                    (i, "Rendered transcript line", line)
                    for i, line in enumerate(rendered.splitlines(), 1)
                )
                row["trace"] = exact_excerpts(source_lines, row["checks"])
                row["cause"] = judgment["cause"]
                row["source_url"] = inputs_path.as_uri()
                row["source_note"] = (
                    f"Frozen historical review input, record {number}. "
                    "Long historical renderings can contain trimmed outputs."
                )
        result.append(row)
    if indexed or len(result) != 704:
        raise ValueError("Historical backfill omitted or duplicated a row")
    return result


def visible_records(events_path: Path):
    with events_path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            event = json.loads(line)
            kind = event.get("type")
            item = event.get("item") or {}
            item_kind = item.get("type")
            if kind == "item.completed" and item_kind == "agent_message":
                yield number, "Agent message", item.get("text") or ""
            elif kind == "item.completed" and item_kind == "command_execution":
                yield number, "Completed tool action", item.get("command") or ""
            elif kind in {"harness", "stderr", "turn.failed"}:
                yield number, "Execution record", event.get("note") or event.get("text") or line


def replication_rows(evidence: Path, include_traces: bool) -> tuple[list[dict], dict]:
    study = evidence / "fresh-seed-v1"
    raw = (study / "models/results.json").read_bytes()
    state = json.loads(raw)
    audit = load(evidence / "CODEX_CONTINUATION_AUDIT_20261111.json")
    manifest_bytes = (study / "candidates.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if (
        audit["model_results_sha256"] != digest(raw)
        or audit["completed_attempts_awaiting_review"] != 0
        or state["contract"]["candidate_manifest_sha256"] != digest(manifest_bytes)
    ):
        raise ValueError("The results, manifest and verified trajectory audit must match")
    capture_limits = {
        item["attempt_id"]: item["provenance_limit"]
        for item in audit.get("capture_limitations", [])
    }
    original = load(study / "models/original56-complete-trajectory-reviews-20261111.json")
    if not original["complete"] or len(original["records"]) != 56:
        raise ValueError("The original trajectory ledger is incomplete")
    early = {item["attempt_id"]: item for item in original["records"]}
    resumed = {item["attempt_id"]: item for item in audit["records"]}
    if early.keys() & resumed.keys():
        raise ValueError("Original and continued reviews overlap")
    candidates = {item["id"]: item for item in manifest["candidates"]}
    rows = []
    seen = set()
    for pair in state["pairs"]:
        arm = manifest["arms"][pair["arm_index"]]
        if arm["backend"] != "codex":
            continue
        candidate = candidates[pair["id"]]
        for attempt in pair["attempts"]:
            if attempt["status"] == "started":
                continue
            identity = attempt["id"]
            if identity in seen:
                raise ValueError("Duplicate attempt in the results")
            seen.add(identity)
            ref = early.get(identity) or attempt["trajectory_analysis"]
            expected = early.get(identity) or resumed[identity]
            if any(
                ref[key] != expected[key] for key in ("review_sha256", "rule_label", "review_label")
            ):
                raise ValueError(f"Review differs from the verified audit for {identity}")
            score = attempt["result"].get("score", {})
            selected = pair["status"] == "valid" and attempt is pair["attempts"][-1]
            if selected and (score["passed_relative"] is not (ref["rule_label"] == "passed")):
                raise ValueError(
                    f"Frozen success score disagrees with the rule label for {identity}"
                )
            measured = score.get("status") == "scored"
            diagnosis = score.get("diagnosis") or {}
            drift = score.get("gap_drift")
            floor = max(0.5, 0.75 * score["honest"]) if drift is not None else None
            row = {
                "id": identity,
                "cohort": "fresh",
                "family": family_name(candidate["family"]),
                "configuration": f"{arm['model']} · {arm['effort']}",
                "task": f"{candidate['template_id']} · draw {candidate['replicate']}",
                "rule": ref["rule_label"] if selected else "invalid_run",
                "review": ref["review_label"],
                "status": attempt["status"].replace("_", " ").capitalize(),
                "diagnosis": diagnosis.get("diagnosis_correct"),
                "score_error": not measured,
                "repair_met": (
                    score["gap_closed"] is not None
                    and score["gap_closed"] >= 0.5
                    and (floor is None or drift >= floor)
                )
                if measured
                else None,
                "gap_closed": score.get("gap_closed"),
                "gap_drift": drift,
                "drift_floor": floor,
                "localization": diagnosis.get("localization"),
                "selected": selected,
            }
            if include_traces:
                row["checks"] = failed_checks(row)
                if row["checks"]:
                    review_path = study / ref["review_path"]
                    review_raw = review_path.read_bytes()
                    if digest(review_raw) != ref["review_sha256"]:
                        raise ValueError(f"Archived review changed for {identity}")
                    review = json.loads(review_raw)
                    event_path = study / attempt["archive"] / "events.jsonl"
                    if (
                        digest(event_path.read_bytes())
                        != attempt["result"]["artifact_sha256"]["events.jsonl"]
                    ):
                        raise ValueError(f"Archived event stream changed for {identity}")
                    row["trace"] = exact_excerpts(visible_records(event_path), row["checks"])
                    row["cause"] = review["review"]["cause"]
                    row["source_url"] = event_path.as_uri()
                    row["source_note"] = (
                        "Normalized event stream. Excerpt positions refer to event lines."
                    )
                    if identity in capture_limits:
                        row["source_note"] += f" {capture_limits[identity]}"
            rows.append(row)
    if seen != early.keys() | resumed.keys():
        raise ValueError("Report coverage differs from the verified review ledgers")
    if not capture_limits.keys() <= seen:
        raise ValueError("Capture limits refer to attempts outside the verified review ledgers")
    if sum(row["selected"] for row in rows) != audit["completed_codex_episodes"]:
        raise ValueError("Report selected scores differ from the benchmark ledger")
    return rows, {
        "checked": audit["checked_utc"],
        "scored": audit["completed_codex_episodes"],
        "planned": 1955,
        "capture_limits": len(capture_limits),
    }


def counts_only(rows: list[dict]) -> list[dict]:
    fields = (
        "cohort",
        "family",
        "configuration",
        "rule",
        "review",
        "diagnosis",
        "repair_met",
        "score_error",
        "selected",
    )
    counts = Counter(tuple(row[field] for field in fields) for row in rows)
    return [dict(zip(fields, values, strict=True)) | {"n": n} for values, n in counts.items()]


def curated_case(path: Path, fresh: bool = False) -> dict:
    case = load(path)
    if fresh:
        return {
            "id": "moving-fault",
            "cohort": "fresh",
            "configuration": "Codex",
            "family": "Moving fault",
            "task": "Moving-fault diagnosis and repair",
            "rule": "plain_matching",
            "review": "plain_matching",
            "checks": [
                check(
                    "repair",
                    "Decoder recovery",
                    "Diagnosis passed. "
                    + metric(case["frozen_gap_closed"], "Nominal-gap recovery")
                    + " "
                    + metric(case["frozen_gap_drift"], "Drift recovery"),
                )
            ],
            "trace": {
                "repair": [
                    {
                        "role": "Agent message",
                        "text": case["visible_quote"],
                        "evidence": "Source-verified excerpt",
                    },
                    {
                        "role": "Submitted decoder",
                        "text": "\n".join(case["code_fragments"]),
                        "evidence": "Source-verified excerpt",
                    },
                ]
            },
            "cause": case["review_excerpt"],
            "source_note": "Quoted from an archived fresh-seed evaluation.",
        }
    return {
        "id": "validation-shape",
        "cohort": "agent_launch2",
        "configuration": "Development configuration",
        "family": "Decoder validation",
        "task": "Prediction and label shapes",
        "rule": "harmful_decoder",
        "review": case["review_label"],
        "checks": [
            check(
                "repair",
                "Decoder recovery",
                metric(case["frozen_gap_closed"], "Nominal-gap recovery"),
            )
        ],
        "trace": {
            "repair": [
                {
                    "role": "Completed tool action",
                    "text": "\n".join(case["code_fragments"]),
                    "evidence": "Source-verified excerpt",
                },
                {
                    "role": "Tool output",
                    "text": case["observed_stdout_prefix"],
                    "evidence": "Source-verified excerpt",
                },
            ]
        },
        "cause": case["review_excerpt"],
        "source_note": case["quotation_notes"],
    }


def render(template_dir: Path, output: Path, payload: dict, private: bool) -> None:
    template = (template_dir / "failure_report.html").read_text()
    script = (template_dir / "failure_report.js").read_text()
    safe_json = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).replace("<", "\\u003c")
    count = payload["snapshot"]["capture_limits"]
    attempts = "one budget-stopped attempt" if count == 1 else f"{count:,} budget-stopped attempts"
    capture_note = f" Output after the stop could not be verified for {attempts}." if count else ""
    html = (
        template.replace("__CAPTURE_NOTE__", capture_note)
        .replace("__REPORT_SCRIPT__", script)
        .replace("__REPORT_DATA__", safe_json)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only completed files. Private artifacts have the owner's read and write permissions.
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        tmp = Path(handle.name)
        try:
            handle.write(html)
            handle.close()
            tmp.chmod(0o600 if private else 0o644)
            tmp.replace(output)
        finally:
            tmp.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "evidence", type=Path, help="Private research-continuation evidence directory"
    )
    parser.add_argument("output", type=Path, help="Public aggregate report file")
    parser.add_argument(
        "--private-output", type=Path, help="Optional owner-only per-attempt report file"
    )
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    private = args.private_output
    if private and (
        private.resolve() == args.output.resolve() or private.resolve().is_relative_to(ROOT)
    ):
        parser.error(
            "Keep the private report outside the repository and apart from the public output"
        )
    rows = historical_rows(evidence, bool(private))
    live, snapshot = replication_rows(evidence, bool(private))
    rows.extend(live)
    paper = ROOT / "paper/workshop-20261111/evidence"
    payload = {
        "cohorts": COHORTS,
        "snapshot": snapshot,
        "groups": counts_only(rows),
        "codebook": load(paper / "hierarchical-taxonomy.json")["codebook"],
        "cases": [
            curated_case(paper / "trajectory-example.json"),
            curated_case(ROOT / "docs/failure-analysis/moving-fault-example.json", fresh=True),
        ],
        "private": False,
    }
    if private:
        cases = [row for row in rows if row["checks"]]
        render(Path(__file__).parent, private, payload | {"cases": cases, "private": True}, True)
    render(Path(__file__).parent, args.output, payload, False)
    print(
        json.dumps(
            {
                "historical_rows": len(rows) - len(live),
                "replication_attempts": len(live),
                "replication_scores": snapshot["scored"],
                "public_examples": len(payload["cases"]),
                "private_failed_or_interrupted_attempts": sum(
                    bool(row.get("checks")) for row in rows
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
