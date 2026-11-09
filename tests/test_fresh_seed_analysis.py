from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fresh_seed_analysis as analysis  # noqa: E402


@pytest.fixture
def inputs(monkeypatch):
    monkeypatch.setattr(analysis.stats, "DRAWS", 50)
    candidates = [
        {"id": "a", "family": "one", "template_id": "t1"},
        {"id": "b", "family": "one", "template_id": "t1"},
        {"id": "c", "family": "two", "template_id": "t2"},
    ]
    arms = [{"backend": "codex", "model": "m", "effort": effort} for effort in ("low", "high")]
    schedule = [{"id": c["id"], "arm_index": i} for c in candidates for i in range(2)]
    frozen = {"candidates": candidates, "arms": arms, "schedule": schedule}
    entries = [
        {"id": c["id"], "gate": {"eligible": c["id"] != "c", "reason": "test"}} for c in candidates
    ]
    return frozen, entries


def pair(identity, arm, passed, prior_interruption=False):
    result = {
        "attempt_status": "valid",
        "score": {
            "passed_absolute": passed,
            "passed_relative": passed,
            "status": "scored",
            "adequate_correct": True,
            "diagnosis": {"diagnosis_correct": passed},
        },
    }
    attempts = [{"status": "provider_interrupted"}] if prior_interruption else []
    attempts.append({"status": "valid", "result": result})
    return {"id": identity, "arm_index": arm, "status": "valid", "attempts": attempts}


def state(frozen, results):
    by_key = {(p["id"], p["arm_index"]): p for p in results}
    return {
        "pairs": [
            by_key.get(
                (p["id"], p["arm_index"]),
                p
                | {
                    "status": "ineligible" if p["id"] == "c" else "pending",
                    "attempts": [],
                },
            )
            for p in frozen["schedule"]
        ]
    }


def test_no_models_has_full_missing_bounds_and_no_comparative_estimate(inputs):
    frozen, entries = inputs
    report = analysis.analyze(frozen, entries)
    assert report["gates"]["candidates"] == 3
    assert report["gates"]["eligible"] == 2
    arm = report["arms"][0]
    assert arm["valid_episodes"] == 0
    assert arm["metrics"]["passed_absolute"]["bounds"]["unresolved"] == 2
    assert arm["metrics"]["passed_absolute"]["bounds"]["upper"] == 1
    assert arm["metrics"]["passed_absolute"]["estimate"] is None
    assert report["comparisons"][0]["metrics"]["passed_absolute"] is None


def test_partial_matching_retains_interruptions_and_uses_common_cases(inputs):
    frozen, entries = inputs
    models = state(frozen, [pair("a", 0, True, True), pair("b", 0, False), pair("a", 1, True)])
    report = analysis.analyze(frozen, entries, models)
    arm = report["arms"][0]
    assert arm["valid_episodes"] == 2
    assert arm["attempt_status_counts"] == {"provider_interrupted": 1, "valid": 2}
    assert report["arms"][1]["metrics"]["passed_absolute"]["bounds"]["lower"] == 0.5
    matched = report["comparisons"][0]["metrics"]["passed_absolute"]
    assert matched["candidates"] == 1
    assert matched["mean"] == 0
    assert matched["interval"] == [0, 0]
    assert matched["coverage_fraction"] == 0.5
    assert matched["availability_selection_warning"]


def test_timeout_is_a_valid_failure_and_not_an_unresolved_result(inputs):
    frozen, entries = inputs
    p = pair("a", 0, False)
    p["attempts"][-1]["result"]["score"].update(
        status="score_error", error="[timed out after 300 s]", scoring_seconds=300.1
    )
    report = analysis.analyze(frozen, entries, state(frozen, [p]))
    arm = report["arms"][0]
    assert arm["scoring_timeouts"] == 1
    assert arm["metrics"]["passed_absolute"]["bounds"]["failures"] == 1
    assert arm["metrics"]["passed_absolute"]["bounds"]["unresolved"] == 1


def test_baseline_retains_rejected_and_undefined_cases(inputs):
    frozen, entries = inputs
    baseline = {
        "rows": [
            {
                "id": "a",
                "passed_absolute": False,
                "passed_relative": False,
                "status": "fit_timeout",
            },
            {"id": "b", "passed_absolute": True, "passed_relative": True, "status": "scored"},
            {
                "id": "c",
                "passed_absolute": None,
                "passed_relative": None,
                "reference_status": "undefined",
                "status": "score_error",
            },
        ]
    }
    report = analysis.analyze(frozen, entries, baseline=baseline)
    result = report["baseline_all_candidates"]
    assert result["completed_candidates"] == 3
    assert result["undefined_reference_candidates"] == 1
    assert result["metrics"]["passed_absolute"]["bounds"]["denominator"] == 3
    assert result["metrics"]["passed_absolute"]["bounds"]["unresolved"] == 1
    assert result["metrics"]["passed_absolute"]["bounds"]["failures"] == 1
    assert report["baseline_eligible"]["metrics"]["passed_absolute"]["bounds"]["denominator"] == 2


@pytest.mark.parametrize("corruption", ["duplicate", "missing_score", "wrong_gate", "foreign"])
def test_corrupt_model_state_is_rejected(inputs, corruption):
    frozen, entries = inputs
    models = state(frozen, [pair("a", 0, True)])
    if corruption == "duplicate":
        models["pairs"][1] = copy.deepcopy(models["pairs"][0])
    elif corruption == "missing_score":
        del models["pairs"][0]["attempts"][-1]["result"]["score"]
    elif corruption == "wrong_gate":
        models["pairs"][-1]["status"] = "pending"
    else:
        models["pairs"][0]["id"] = "foreign"
    with pytest.raises(ValueError):
        analysis.analyze(frozen, entries, models)


def test_baseline_duplicate_is_rejected(inputs):
    frozen, entries = inputs
    with pytest.raises(ValueError):
        analysis.analyze(frozen, entries, baseline={"rows": [{"id": "a"}, {"id": "a"}]})


@pytest.mark.parametrize("identity", ["a", "c"])
def test_defined_baseline_failure_cannot_become_missing_data(inputs, identity):
    frozen, entries = inputs
    row = {
        "id": identity,
        "status": "fit_timeout",
        "reference_status": "defined",
        "passed_absolute": None,
        "passed_relative": None,
    }
    with pytest.raises(ValueError, match="baseline pass"):
        analysis.analyze(frozen, entries, baseline={"rows": [row]})


@pytest.mark.parametrize("prior", ["model_unavailable", "harness_cleanup_unresolved"])
def test_second_attempt_requires_permitted_interruption(inputs, prior):
    frozen, entries = inputs
    p = pair("a", 0, True, True)
    p["attempts"][0]["status"] = prior
    with pytest.raises(ValueError, match="retry"):
        analysis.analyze(frozen, entries, state(frozen, [p]))


def test_timeout_text_without_elapsed_deadline_is_not_counted(inputs):
    frozen, entries = inputs
    p = pair("a", 0, False)
    p["attempts"][-1]["result"]["score"].update(
        status="score_error", error="[timed out after 300 s]", scoring_seconds=0.1
    )
    report = analysis.analyze(frozen, entries, state(frozen, [p]))
    assert report["arms"][0]["scoring_timeouts"] == 0


@pytest.fixture
def exported_study(tmp_path):
    def save(name, data):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    candidates = [
        {"id": str(i), "template_id": str(i // 4), "family": str((i // 4) % 9)} for i in range(92)
    ]
    frozen = {
        "candidates": candidates,
        "arms": [{} for _ in range(58)],
        "schedule": [{"id": c["id"], "arm_index": i} for c in candidates for i in range(58)],
    }
    candidate_hash = save("candidates.json", frozen)
    entries = [{"id": c["id"], "gate": {"eligible": True, "reason": "test"}} for c in candidates]
    refs = {"candidate_manifest_sha256": candidate_hash, "complete": True, "rows": entries}
    reference_hash = save("reference-results.json", refs)
    manifest = {
        "candidate_manifest_sha256": candidate_hash,
        "reference_results_sha256": reference_hash,
        "tasks": entries,
    }
    save("scorer/manifest.json", manifest)
    return tmp_path, save, refs, manifest


def test_loader_records_input_hashes_and_accepts_no_model_calls(exported_study):
    root, _, _, _ = exported_study
    inputs, provenance = analysis.load_inputs(root, None)
    assert inputs["models"] is None
    assert len(inputs["entries"]) == 92
    assert set(provenance) == {"candidates.json", "reference-results.json", "scorer/manifest.json"}


@pytest.mark.parametrize(
    "corruption", ["partial", "candidate_hash", "reference_hash", "model_hash", "baseline_hash"]
)
def test_loader_rejects_partial_or_mixed_studies(exported_study, corruption):
    root, save, refs, manifest = exported_study
    baseline = None
    if corruption == "partial":
        refs["complete"] = False
        save("reference-results.json", refs)
    elif corruption == "candidate_hash":
        manifest["candidate_manifest_sha256"] = "wrong"
        save("scorer/manifest.json", manifest)
    elif corruption == "reference_hash":
        manifest["reference_results_sha256"] = "wrong"
        save("scorer/manifest.json", manifest)
    elif corruption == "model_hash":
        save("models/results.json", {"contract": {"candidate_manifest_sha256": "wrong"}})
    else:
        baseline = root / "baseline.json"
        save("baseline.json", {"manifest_sha256": "wrong"})
    with pytest.raises(ValueError):
        analysis.load_inputs(root, baseline)
