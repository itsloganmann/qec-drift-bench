"""Read the frozen fresh-seed study; never launch or change an experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from itertools import combinations
from pathlib import Path

import numpy as np
import study_statistics as stats

PASS_METRICS = ("passed_absolute", "passed_relative")
METRICS = (*PASS_METRICS, "adequate_correct", "diagnosis_correct", "mechanism_correct")
WARNING = "Availability selection can bias complete-case comparisons. No unmatched arm ranking."


def identities(rows: list[dict]) -> list[str]:
    result = [row["id"] for row in rows]
    if len(set(result)) != len(result):
        raise ValueError("Duplicate candidate identities")
    return result


def validate_design(frozen: dict, entries: list[dict]) -> None:
    ids = identities(frozen["candidates"])
    if set(identities(entries)) != set(ids):
        raise ValueError("Reference candidates do not match the design")
    if any(type(entry["gate"]["eligible"]) is not bool for entry in entries):
        raise ValueError("Invalid eligibility flag")
    schedule = [(p["id"], p["arm_index"]) for p in frozen["schedule"]]
    expected = {(identity, i) for identity in ids for i in range(len(frozen["arms"]))}
    if len(schedule) != len(expected) or set(schedule) != expected:
        raise ValueError("Frozen schedule does not cover every arm and candidate exactly once")
    families = {}
    for candidate in frozen["candidates"]:
        previous = families.setdefault(candidate["template_id"], candidate["family"])
        if previous != candidate["family"]:
            raise ValueError("Template belongs to multiple families")


def model_rows(frozen: dict, entries: list[dict], models: dict | None) -> tuple[list, list]:
    eligible = {e["id"] for e in entries if e["gate"]["eligible"]}
    if models is None:
        models = {
            "pairs": [
                p
                | {
                    "status": "pending" if p["id"] in eligible else "ineligible",
                    "attempts": [],
                }
                for p in frozen["schedule"]
            ]
        }
    pairs = models["pairs"]
    if [(p["id"], p["arm_index"]) for p in pairs] != [
        (p["id"], p["arm_index"]) for p in frozen["schedule"]
    ]:
        raise ValueError("Model state differs from the frozen schedule")
    scores = [{} for _ in frozen["arms"]]
    groups = [[] for _ in frozen["arms"]]
    for pair in pairs:
        attempts = pair["attempts"]
        if (pair["status"] == "ineligible") != (pair["id"] not in eligible):
            raise ValueError("Model eligibility differs from the frozen gate")
        if pair["status"] == "ineligible":
            if attempts:
                raise ValueError("Ineligible candidate has model attempts")
            continue
        if len(attempts) > 2 or sum(a["status"] == "valid" for a in attempts) > 1:
            raise ValueError("Model attempt limit or finality violated")
        if len(attempts) == 2 and attempts[0]["status"] not in {
            "provider_interrupted",
            "preaction_environment_error",
        }:
            raise ValueError("Model retry follows a non-retryable attempt")
        groups[pair["arm_index"]].append(pair)
        if pair["status"] != "valid":
            if any(a["status"] == "valid" for a in attempts):
                raise ValueError("Valid attempt is not reflected in pair status")
            continue
        if not attempts or attempts[-1]["status"] != "valid":
            raise ValueError("Valid pair lacks a valid final attempt")
        result = attempts[-1].get("result", {})
        score = result.get("score")
        if result.get("attempt_status") != "valid" or not isinstance(score, dict):
            raise ValueError("Valid attempt lacks its score")
        if any(type(score.get(metric)) is not bool for metric in PASS_METRICS):
            raise ValueError("Eligible model result lacks defined binary pass scores")
        scores[pair["arm_index"]][pair["id"]] = score
    return scores, groups


def metric_value(score: dict, metric: str) -> bool | None:
    value = (
        score.get("diagnosis", {}).get(metric)
        if metric in {"diagnosis_correct", "mechanism_correct"}
        else score.get(metric)
    )
    if value is not None and type(value) is not bool:
        raise ValueError("Metric is not boolean or undefined")
    return value


def analyze(
    frozen: dict, entries: list[dict], models: dict | None = None, baseline: dict | None = None
) -> dict:
    validate_design(frozen, entries)
    candidates = frozen["candidates"]
    by_id = {c["id"]: c for c in candidates}
    eligible_ids = {e["id"] for e in entries if e["gate"]["eligible"]}
    eligible = [c for c in candidates if c["id"] in eligible_ids]
    scores, groups = model_rows(frozen, entries, models)

    @lru_cache(maxsize=8)
    def weights(ids: tuple[str, ...]) -> np.ndarray:
        return stats.bootstrap_weights([by_id[i] for i in ids], draws=stats.DRAWS)

    def estimate(points: list[dict], values: list[float]) -> dict | None:
        if not points:
            return None
        return stats.estimate(
            points, np.asarray(values, dtype=float), weights(tuple(identities(points)))
        )

    def summary(points: list[dict], rows: dict[str, dict]) -> dict:
        metrics = {}
        for metric in METRICS:
            values = {c["id"]: metric_value(rows.get(c["id"], {}), metric) for c in points}
            observed = [c for c in points if values[c["id"]] is not None]
            metrics[metric] = {"bounds": stats.bounds(len(points), list(values.values()))}
            if metric in PASS_METRICS:
                metrics[metric]["estimate"] = estimate(
                    observed, [float(values[c["id"]]) for c in observed]
                )
                metrics[metric]["availability_selection_warning"] = len(observed) < len(points)
        selected = [rows[c["id"]] for c in points if c["id"] in rows]
        return stats.coverage(points) | {
            "completed_candidates": len(selected),
            "undefined_reference_candidates": sum(
                row.get("reference_status") == "undefined" for row in selected
            ),
            "reports_present": sum(
                row.get("reported", row.get("report") is not None) is True for row in selected
            ),
            "score_status_counts": dict(Counter(row.get("status", "unknown") for row in selected)),
            "scoring_timeouts": sum(
                row.get("status") == "score_error"
                and "[timed out after 300 s]" in row.get("error", "")
                and row.get("scoring_seconds", 0) >= 300
                for row in selected
            ),
            "metrics": metrics,
        }

    arm_reports = []
    for index, arm in enumerate(frozen["arms"]):
        pairs = groups[index]
        arm_reports.append(
            summary(eligible, scores[index])
            | {
                "arm_index": index,
                "arm": arm,
                "valid_episodes": len(scores[index]),
                "pair_status_counts": dict(Counter(p["status"] for p in pairs)),
                "attempt_status_counts": dict(
                    Counter(a["status"] for p in pairs for a in p["attempts"])
                ),
                "pairs_with_provider_interruption": sum(
                    any(a["status"] == "provider_interrupted" for a in p["attempts"]) for p in pairs
                ),
            }
        )

    baseline_rows = {} if baseline is None else {row["id"]: row for row in baseline["rows"]}
    if baseline is not None:
        if not set(identities(baseline["rows"])) <= by_id.keys():
            raise ValueError("Foreign baseline candidate")
        if baseline.get("complete") and len(baseline_rows) != len(candidates):
            raise ValueError("Complete baseline lacks candidates")
        for row in baseline_rows.values():
            if row.get("reference_status") == "undefined":
                if any(row.get(metric) is not None for metric in PASS_METRICS):
                    raise ValueError("Undefined references have a defined baseline pass score")
            elif any(type(row.get(metric)) is not bool for metric in PASS_METRICS):
                raise ValueError("Defined reference lacks a binary baseline pass score")

    comparisons = []
    compared = [(i, rows) for i, rows in enumerate(scores)]
    if baseline is not None:
        compared.append(("fixed_baseline", baseline_rows))
    for (left, left_rows), (right, right_rows) in combinations(compared, 2):
        metrics = {}
        for metric in PASS_METRICS:
            common = [
                c
                for c in eligible
                if all(
                    metric_value(rows.get(c["id"], {}), metric) is not None
                    for rows in (left_rows, right_rows)
                )
            ]
            difference = [
                float(metric_value(left_rows[c["id"]], metric))
                - float(metric_value(right_rows[c["id"]], metric))
                for c in common
            ]
            result = estimate(common, difference)
            if result is not None:
                result.update(
                    eligible_denominator=len(eligible),
                    coverage_fraction=len(common) / len(eligible),
                    availability_selection_warning=len(common) != len(eligible),
                )
            metrics[metric] = result
        comparisons.append(
            {"left": left, "right": right, "direction": "left_minus_right", "metrics": metrics}
        )
    return {
        "gates": stats.coverage(candidates)
        | {
            "eligible": len(eligible),
            "rejected": len(candidates) - len(eligible),
            "reasons": dict(Counter(e["gate"]["reason"] for e in entries)),
        },
        "arms": arm_reports,
        "model_execution": {
            "eligible_pairs": len(eligible) * len(frozen["arms"]),
            "valid_pairs": sum(len(rows) for rows in scores),
            "unresolved_pairs": len(eligible) * len(frozen["arms"])
            - sum(len(rows) for rows in scores),
        },
        "baseline_all_candidates": summary(candidates, baseline_rows),
        "baseline_eligible": summary(eligible, baseline_rows),
        "comparisons": comparisons,
        "inference": {
            "numpy_version": np.__version__,
            "draws": stats.DRAWS,
            "seed": stats.SEED,
            "quantile_method": "linear",
            "statistic": "pooled candidate mean; comparisons use paired differences",
            "resampling": "families, templates within family, replicates within template",
            "cluster_size": "Each sampled cluster retains its original member count.",
            "warning": WARNING,
            "population": "Within-family fresh-seed replication of selected development templates.",
            "limits": "Few families; descriptive intervals; no model-sampling variance estimate.",
        },
    }


def load_inputs(study: Path, baseline_path: Path | None) -> tuple[dict, dict]:
    provenance = {}

    def read(relative: str, path: Path | None = None) -> dict:
        path = path or study / relative
        raw = path.read_bytes()
        provenance[relative] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    frozen = read("candidates.json")
    references = read("reference-results.json")
    manifest = read("scorer/manifest.json")
    if len(frozen["candidates"]) != 92 or len(frozen["arms"]) != 58:
        raise ValueError("Expected the frozen 92-candidate, 58-arm study")
    design = stats.coverage(frozen["candidates"])
    if (
        design["families"] != 9
        or design["templates"] != 23
        or set(design["by_template"].values()) != {4}
    ):
        raise ValueError("Expected nine families and four draws from each of 23 templates")
    if references.get("complete") is not True:
        raise ValueError("All reference gates must finish before analysis")
    for source in (references, manifest):
        if source["candidate_manifest_sha256"] != provenance["candidates.json"]:
            raise ValueError("Candidate manifest hash changed")
    if manifest["reference_results_sha256"] != provenance["reference-results.json"]:
        raise ValueError("Reference results hash changed")
    entries = references["rows"]
    validate_design(frozen, entries)
    indexed = {entry["id"]: entry for entry in entries}
    if manifest["tasks"] != [indexed[c["id"]] for c in frozen["candidates"]]:
        raise ValueError("Scorer manifest differs from the frozen gate results")
    models = read("models/results.json") if (study / "models/results.json").exists() else None
    if models is not None:
        for contract_key, filename in [
            ("candidate_manifest_sha256", "candidates.json"),
            ("scorer_manifest_sha256", "scorer/manifest.json"),
        ]:
            if models["contract"][contract_key] != provenance[filename]:
                raise ValueError("Model contract belongs to another study")
    baseline = read("baseline_results", baseline_path) if baseline_path is not None else None
    if baseline is not None and baseline["manifest_sha256"] != provenance["scorer/manifest.json"]:
        raise ValueError("Baseline belongs to another study")
    return {
        "frozen": frozen,
        "entries": entries,
        "models": models,
        "baseline": baseline,
    }, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    inputs, provenance = load_inputs(args.study, args.baseline)
    report = analyze(**inputs)
    report.update(created_utc=datetime.now(UTC).isoformat(), input_sha256=provenance)
    report["analysis_source_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__), Path(stats.__file__))
    }
    with args.output.open("x") as handle:
        handle.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(args.output), "gates": report["gates"]}))


if __name__ == "__main__":
    main()
