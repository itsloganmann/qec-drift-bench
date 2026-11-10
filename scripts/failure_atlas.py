"""Build a privacy-preserving failure atlas from frozen transcript-review inputs.

uv run python scripts/failure_atlas.py PRIVATE_DIRECTORY OUTPUT_DIRECTORY
No model call is made here. Only aggregate cells are published, never transcripts,
fresh candidate identifiers, seeds, run-level fresh scores, or local paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import judge_transcripts as judge
from failure_atlas_review import read_jsonl

LABELS = list(judge.tx.LABELS)
NAMES = {
    "invalid_run": "Rule-excluded run",
    "passed": "Passed",
    "out_of_budget": "Budget exhausted",
    "no_submission": "No submission",
    "broken_decoder": "Broken decoder",
    "harmful_decoder": "Harmful decoder",
    "misdiagnosis": "Diagnosis only",
    "nominal_unchanged": "Nominal unchanged",
    "plain_matching": "Plain fitted matching",
    "under_adapted": "Under-adapted",
}
EXPLANATIONS = {
    "invalid_run": [
        "External failure invalidated the run.",
        "Repair the environment or provider gate and rerun.",
    ],
    "passed": [
        "Diagnosis and repair both cleared the relative rule.",
        "Test replication on a held-out task family.",
    ],
    "out_of_budget": [
        "No scorable decoder at the tool or time deadline.",
        "Keep a working decoder early and bound expensive searches.",
    ],
    "no_submission": [
        "The agent stopped without a decoder.",
        "Check required deliverables before stopping.",
    ],
    "broken_decoder": [
        "The decoder crashed, timed out, or returned an invalid result.",
        "Validate the decode interface and runtime on held-out calibration data.",
    ],
    "harmful_decoder": [
        "The submitted decoder scored below nominal plain matching.",
        "Retain a validated fallback and reject damaging fits.",
    ],
    "misdiagnosis": [
        "The repair was sufficient but the diagnosis failed.",
        "Validate scope, time variation, and changed-qubit localization.",
    ],
    "nominal_unchanged": [
        "The decoder stayed behaviorally nominal or used nominal source.",
        "Verify deployment evidence changes the actual decoding model.",
    ],
    "plain_matching": [
        "A fitted model omitted correlations and fell short.",
        "Test whether correlated or time-conditioned decoding improves held-out loss.",
    ],
    "under_adapted": [
        "A fitted correlated decoder recovered too little loss.",
        "Measure regime tracking, calibration, and temporal adaptation separately.",
    ],
}

CASE_NOTES = [
    {
        "name": "A validation shape error can send the agent in the wrong direction",
        "observation": "A development trace compared an (N, 1) prediction array with an (N,) "
        "label array. Broadcasting made the comparison an N by N matrix. The agent then "
        "replaced nominal matching with an ensemble that scored worse than nominal matching.",
        "check": "Normalize prediction and label shapes before using validation loss "
        "to select a decoder.",
    },
    {
        "name": "The inferred regime can be routed to the wrong decoder",
        "observation": "One archived decoder returned argmax class indices as locations, "
        "then compared those indices directly with physical qubit IDs. Its correlated decoder "
        "closed some nominal gap but failed the drift-recovery requirement.",
        "check": "Map classifier indices back to physical IDs and test the dispatch path.",
    },
    {
        "name": "A working repair can still have a failed diagnosis",
        "observation": "A reviewed development episode named all 49 circuit qubits when "
        "21 were actually changed. Its decoder cleared the repair thresholds, while the "
        "over-broad report failed localization.",
        "check": "Evaluate localization precision and recall separately from decoder performance.",
    },
    {
        "name": "Exploration can consume the submission budget",
        "observation": "Several reviewed traces used all 40 tool calls on probes and "
        "debugging before writing decoder.py. These are budget failures, even when some "
        "intermediate analyses found useful evidence.",
        "check": "Write and test a valid fallback decoder before expensive exploration.",
    },
]


def summarize(rows: list[dict], reviews: dict[str, dict]) -> dict:
    """Counts preserve missing judgments and exclude invalid runs from capability rates."""
    labels = Counter(r.get("rule_label") or "unclassified" for r in rows)
    valid = [r for r in rows if r.get("rule_label") not in (None, "invalid_run")]
    current = [(r, reviews[r["review_key"]]) for r in rows if r.get("review_key") in reviews]
    paired = [(r, j) for r, j in current if r.get("rule_label") is not None]
    confusion = Counter((r["rule_label"], j["label"]) for r, j in paired)
    quadrants = Counter()
    for row in valid:
        if row.get("score_error") or row["rule_label"] in (
            "out_of_budget",
            "no_submission",
            "broken_decoder",
        ):
            quadrants["unscored"] += 1
        elif row.get("diagnosis_correct") is None:
            quadrants["diagnosis_unmeasured"] += 1
        else:
            good_fix = row["rule_label"] in ("passed", "misdiagnosis")
            quadrants[f"diagnosis_{int(bool(row['diagnosis_correct']))}_fix_{int(good_fix)}"] += 1
    concerns = {
        key: sum(bool(j.get(key)) for _, j in current)
        for key in ("environment_problem", "instruction_problem", "integrity_problem")
    }
    below_floor = sum(
        j["label"] in ("passed", "misdiagnosis")
        and any(r.get(key) is not None and r[key] < 0.5 for key in ("gap_closed", "gap_drift"))
        for r, j in current
    )
    wrong_diagnosis = sum(
        j["label"] == "passed" and r.get("diagnosis_correct") is False for r, j in current
    )
    return dict(
        recorded=len(rows),
        valid=len(valid),
        invalid=labels.get("invalid_run", 0),
        unclassified=labels.get("unclassified", 0),
        available=sum(bool(r.get("transcript_available")) for r in rows),
        reviewed=len(current),
        missing_reviews=len(rows) - len(current),
        passes=labels.get("passed", 0),
        labels=dict(labels),
        judge_labels=dict(Counter(j["label"] for _, j in current)),
        paired=len(paired),
        agreement=sum(r["rule_label"] == j["label"] for r, j in paired),
        confusion=[dict(rule=a, judge=b, count=n) for (a, b), n in sorted(confusion.items())],
        quadrants=dict(quadrants),
        unscored_valid=quadrants.get("unscored", 0),
        score_error_rows=sum(r.get("score_error") is True for r in valid),
        transcript_budget_notes=sum(r.get("budget_hit") is True for r in valid),
        concerns=concerns,
        judge_repair_floor_contradictions=below_floor,
        judge_pass_diagnosis_contradictions=wrong_diagnosis,
        fairness=dict(Counter(j.get("task_fair", "unknown") for _, j in current)),
        diagnosis_correct=sum(r.get("diagnosis_correct") is True for r in valid),
        diagnosis_measured=sum(r.get("diagnosis_correct") is not None for r in valid),
    )


def matching_reviews(rows: list[dict], saved: list[dict]) -> dict[str, dict]:
    """Require key membership before comparing optional protocol fields."""
    wanted = {r["review_key"]: r["protocol"] for r in rows if r.get("review_key")}
    return {
        r["key"]: r
        for r in saved
        if r.get("key") in wanted and r.get("protocol") == wanted[r["key"]]
    }


def aggregate(inventory: dict, saved: list[dict]) -> dict:
    rows = inventory["rows"]
    if len({r["run_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate run identity")
    identity = {r["review_key"]: r["protocol"] for r in rows if r.get("review_key")}
    reviews = matching_reviews(rows, saved)
    if any(r["label"] not in LABELS for r in reviews.values()):
        raise ValueError("Unknown judgment label")
    cohorts = defaultdict(list)
    for row in rows:
        cohorts[row["cohort"]].append(row)
    output = {}
    for name, members in cohorts.items():
        models, families = defaultdict(list), defaultdict(list)
        for row in members:
            models[row["arm"]].append(row)
            families[row["family"]].append(row)
        output[name] = summarize(members, reviews) | dict(
            models={k: summarize(v, reviews) for k, v in sorted(models.items())},
            families={k: summarize(v, reviews) for k, v in sorted(families.items())},
        )
    # A small set of development-only examples is kept in the private audit. Public
    # charts use counts only; arbitrary judge prose can contain unrelated local data.
    return dict(
        created_utc=datetime.now(UTC).isoformat(),
        status="complete"
        if all(not r.get("transcript_available") or r.get("review_key") in reviews for r in rows)
        else "in_progress",
        overall=summarize(rows, reviews),
        cohorts=output,
        names=NAMES,
        explanations=EXPLANATIONS,
        case_notes=CASE_NOTES,
        evaluator=dict(
            model=judge.MODEL,
            effort=judge.EFFORT,
            protocols=sorted(set(identity.values())),
            independence=(
                "Model-assisted judgments; partial identifier masking, not independent human "
                "ground truth."
            ),
        ),
        coverage_note=(
            "Every recorded decoder score row is inventoried. Current score-linked attempts "
            "are reviewed; superseded attempts are archived, not separate benchmark "
            "observations. Missing archives remain explicit."
        ),
        transcript_note=(
            "Rendered views shorten long messages and tool outputs. Long views keep the first "
            "40,000 and last 110,000 characters. This is review of every available run, not "
            "exhaustive reading of every raw byte or hidden reasoning."
        ),
        archive_note=(
            "Two damaged historical gzip archives supply 27 selected records recovered "
            "before compression errors. Their stored decoder and report fields were checked "
            "against the score rows, but those recovered records are not checksum verified."
        ),
        historical_gate_note=(
            "The earlier launch cohort has 47 frozen env_missing exclusions. All 47 traces "
            "contain a required-module import error. The original gate excludes these runs "
            "even when an agent later recovers or submits a scorable decoder. The transcript "
            "judge assigned non-invalid labels to all 47. This historical eligibility dispute "
            "is retained; neither the original exclusions nor the raw judgments are overwritten."
        ),
        fresh_source_note=(
            "Fresh score and event hashes are verified. Failed fresh decoder subtypes use a "
            "later work-folder source snapshot which was not bound into the original attempt "
            "hashes. They are provisional; stored success scores remain authoritative."
        ),
        comparison_note=(
            "Historical cohorts, development, and fresh seeds have different task sets. Fresh "
            "arm coverage is availability selected and sparse. Charts are descriptive and do "
            "not establish a model ranking or causal explanation."
        ),
        pilot_note=(
            "The earlier numerical-answer pilot has 64 model episodes and a different "
            "task/output contract. It is excluded from the decoder taxonomy; its 96-row "
            "episode table is a task fixture, not 96 additional model runs."
        ),
        provenance=dict(
            source_hashes=inventory["source_hashes"],
            inventory_sha256=hashlib.sha256(
                json.dumps(inventory, sort_keys=True).encode()
            ).hexdigest(),
        ),
    )


def markdown(data: dict) -> str:
    overall = data["overall"]
    dev = data["cohorts"]["agent_launch2"]
    lines = [
        "# QEC-Drift failure mode atlas",
        "",
        f"Snapshot: {data['created_utc']}. Status: **{data['status']}**.",
        "",
        f"The audit inventories {overall['recorded']} decoder runs and "
        f"{overall['available']} available score-linked transcripts. "
        f"{overall['reviewed']} have current exact-input judgments. "
        f"The frozen rule includes {overall['valid']} runs and excludes {overall['invalid']}.",
        f"Among valid runs, {overall['unscored_valid']} have no scored decoder and "
        f"{overall['score_error_rows']} carry a scorer or missing-submission message. "
        "These are overlapping counts. Fixed scoring timeouts remain failures; provider "
        "or environment invalidations are excluded from capability rates.",
        "",
        "[Interactive atlas Page]"
        "(https://chatgpt.com/space/page_22edfbe3fcf881918fdacb641af85579). "
        "[Download aggregate JSON](failure-atlas.json). The self-contained `index.html` "
        "also works as a local interactive artifact.",
        "",
        "## Where development runs fail",
        "",
        f"The current development set has {dev['passes']}/{dev['valid']} relative joint passes. "
        "A pass requires both the diagnosis and the decoder to clear the stored rule. "
        "The largest rule failure groups are fitted plain matching and insufficient adaptation. "
        "Transcript judgments are shown separately and never rewrite the stored success rates.",
        f"A deterministic check found {dev['judge_repair_floor_contradictions']} development "
        "judge labels claiming sufficient repair despite a measured gap or drift recovery "
        "below the required 0.5 floor. Unknown historical metrics are exempt. "
        "The raw labels are preserved, and this check does not estimate full judge accuracy.",
        "",
        "![Development failure mix](plots/development-failure-mix.png)",
        "",
        "![Fault family success and diagnosis](plots/development-fault-families.png)",
        "",
        "![Failure mix by arm](plots/development-arm-matrix.png)",
        "",
        "## Coverage by cohort",
        "",
        "| Cohort | Recorded | Valid | Invalid | Available transcripts | Current judgments |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, value in data["cohorts"].items():
        lines.append(
            f"| {name} | {value['recorded']} | {value['valid']} | {value['invalid']} | "
            f"{value['available']} | {value['reviewed']} |"
        )
    lines += [
        "",
        "## Why the labels apply",
        "",
        "| Label | Evidence described by the gate | Suggested next check |",
        "|---|---|---|",
    ]
    for key, value in data["explanations"].items():
        lines.append(f"| {data['names'][key]} | {value[0]} | {value[1]} |")
    lines += ["", "## Measurement limits", ""]
    lines += [
        "These development examples were checked against frozen transcript inputs. "
        "They illustrate observed mechanisms; their prevalence and causal effect "
        "were not estimated.",
        "",
    ]
    for note in CASE_NOTES:
        lines += [f"**{note['name']}.** {note['observation']} Suggested check: {note['check']}", ""]
    lines += [
        data[key] + "\n"
        for key in (
            "coverage_note",
            "transcript_note",
            "archive_note",
            "historical_gate_note",
            "binding_note",
            "comparison_note",
            "fresh_source_note",
            "pilot_note",
        )
    ]
    lines += [
        data["evaluator"]["independence"],
        "",
        "The earlier research closeout ended at documented provider and hosted-execution "
        "gates. This atlas does not imply that unrun planned grid cells were completed. "
        "No new model ranking or causal claim follows from this descriptive audit.",
        "",
        "## Reproduce",
        "",
        "```sh",
        "uv run python scripts/failure_atlas.py PRIVATE_FROZEN_INPUTS OUTPUT_DIRECTORY",
        "uv run --with matplotlib python scripts/failure_atlas_plots.py "
        "OUTPUT_DIRECTORY/failure-atlas.json OUTPUT_DIRECTORY/plots",
        "```",
        "",
        "Private inputs contain the transcript evidence and exact judgment keys. "
        "Public aggregates omit raw transcripts and fresh candidate identities. "
        "The aggregate JSON records input hashes. Figures are also exported as SVG.",
        "",
    ]
    return "\n".join(lines)


def build(directory: Path, output: Path) -> None:
    inventory = json.loads((directory / "inventory.json").read_text())
    saved = judge.judged() + read_jsonl(directory / "reviews.jsonl")
    data = aggregate(inventory, saved)
    identity = matching_reviews(inventory["rows"], saved)
    canonical_reviews = [identity[key] for key in sorted(identity)]
    data["provenance"]["matching_judgments_sha256"] = hashlib.sha256(
        json.dumps(canonical_reviews, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    data["provenance"]["generator_sha256"] = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("failure_atlas.py", "failure_atlas_template.html", "failure_atlas_plots.py")
    }
    binding_path = directory / "binding-audit.json"
    if binding_path.exists():
        binding = json.loads(binding_path.read_text())
        if binding["issues"]:
            raise ValueError("The source-binding audit has unresolved mismatches")
        data["provenance"]["binding_audit_sha256"] = hashlib.sha256(
            binding_path.read_bytes()
        ).hexdigest()
        data["provenance"]["binding_summary"] = binding["summary"]
        counts = binding["summary"]
        data["binding_note"] = (
            f"The {counts['legacy_untagged']} historical rows lack attempt IDs and use "
            "the last matching untagged record. "
            f"All {counts['decoder_source_matches']} archived decoder sources matched the "
            f"score rows; {counts['reports_compared']} archived report objects also matched. "
            "This does not remove ambiguity between historical reruns with identical outputs."
        )
    else:
        data["binding_note"] = "A separate source-binding audit was not supplied for this build."
    output.mkdir(parents=True, exist_ok=True)
    (output / "failure-atlas.json").write_text(json.dumps(data, indent=2, allow_nan=False))
    template = Path(__file__).with_name("failure_atlas_template.html").read_text()
    safe_json = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    (output / "index.html").write_text(template.replace("__ATLAS_DATA__", safe_json))
    (output / "index.md").write_text(markdown(data))
    joined = [r | {"judgment": identity.get(r.get("review_key"))} for r in inventory["rows"]]
    (directory / "private-run-audit.json").write_text(json.dumps(joined, indent=2, allow_nan=False))
    print(
        json.dumps(
            {
                k: data["overall"][k]
                for k in ("recorded", "available", "reviewed", "valid", "invalid")
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.directory, args.output)
