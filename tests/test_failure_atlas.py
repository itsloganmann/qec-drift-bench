"""Landmark checks for missingness, score authority, and review identity."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from failure_atlas import aggregate, build, summarize  # noqa: E402
from failure_atlas_inputs import facts  # noqa: E402


def row(rid, label, key=None, diagnosis=True):
    return dict(
        run_id=rid,
        rule_label=label,
        review_key=key,
        protocol="identifier-masked-v2",
        diagnosis_correct=diagnosis,
        cohort="test",
        arm="model",
        family="fault",
        transcript_available=key is not None,
    )


def test_invalid_runs_and_unreviewed_runs_have_separate_denominators():
    rows = [
        row("a", "passed", "a"),
        row("b", "invalid_run", "b"),
        row("c", "under_adapted", "c"),
        row("d", "plain_matching", None),
    ]
    reviews = {"a": {"label": "passed"}, "b": {"label": "invalid_run"}}
    result = summarize(rows, reviews)
    assert result["recorded"] == 4
    assert result["valid"] == 3
    assert result["invalid"] == 1
    assert result["passes"] == 1
    assert result["available"] == 3
    assert result["reviewed"] == 2
    assert result["missing_reviews"] == 2
    assert sum(result["judge_labels"].values()) == 2


def test_judge_disagreement_never_changes_stored_pass():
    result = summarize([row("a", "passed", "a")], {"a": {"label": "plain_matching"}})
    assert result["passes"] == 1
    assert result["agreement"] == 0
    assert result["quadrants"] == {"diagnosis_1_fix_1": 1}


def test_historical_missing_diagnosis_is_not_scored_as_wrong():
    result = summarize([row("a", "passed", diagnosis=None)], {})
    assert result["diagnosis_measured"] == 0
    assert result["quadrants"] == {"diagnosis_unmeasured": 1}
    assert "Diagnosis was not required" in facts({"diagnosis_correct": None})


def test_stale_protocol_cannot_complete_an_exact_key():
    inventory = dict(rows=[row("a", "passed", "a")], source_hashes={})
    result = aggregate(inventory, [dict(key="a", label="passed", protocol="old")])
    assert result["overall"]["reviewed"] == 0
    assert result["status"] == "in_progress"


def test_duplicate_run_ids_are_rejected():
    with pytest.raises(ValueError, match="Duplicate run"):
        aggregate(dict(rows=[row("a", "passed"), row("a", "passed")]), [])


def test_public_aggregate_has_no_run_keys_or_judge_prose():
    inventory = dict(rows=[row("private candidate", "passed", "secretkey")], source_hashes={})
    value = aggregate(
        inventory,
        [
            dict(
                key="secretkey",
                protocol="identifier-masked-v2",
                label="passed",
                cause="private raw transcript",
            )
        ],
    )
    assert "secretkey" not in str(value)
    assert "private raw transcript" not in str(value)
    assert "private candidate" not in str(value)


def test_available_transcript_without_key_cannot_be_claimed_complete():
    value = row("a", "passed")
    value["transcript_available"] = True
    result = aggregate(dict(rows=[value], source_hashes={}), [])
    assert result["status"] == "in_progress"


def test_unresolved_binding_mismatch_stops_artifact_output(tmp_path, monkeypatch):
    import json

    import judge_transcripts

    monkeypatch.setattr(judge_transcripts, "judged", lambda: [])
    source = tmp_path / "private"
    source.mkdir()
    (source / "inventory.json").write_text(
        json.dumps(dict(rows=[row("a", "passed")], source_hashes={}))
    )
    (source / "binding-audit.json").write_text(json.dumps(dict(issues=["source mismatch"])))
    output = tmp_path / "public"
    with pytest.raises(ValueError, match="source-binding audit"):
        build(source, output)
    assert not output.exists()


def test_legacy_without_protocol_cannot_enter_judgment_hash(tmp_path, monkeypatch):
    import hashlib
    import json

    import judge_transcripts

    current = dict(key="current", protocol="identifier-masked-v2", label="passed")
    legacy = dict(key="old", label="passed")
    monkeypatch.setattr(judge_transcripts, "judged", lambda: [legacy, current])
    source = tmp_path / "private"
    source.mkdir()
    value = row("a", "passed", "current")
    value["cohort"] = "agent_launch2"
    (source / "inventory.json").write_text(json.dumps(dict(rows=[value], source_hashes={})))
    output = tmp_path / "public"
    build(source, output)
    result = json.loads((output / "failure-atlas.json").read_text())
    expected = hashlib.sha256(
        json.dumps([current], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert result["overall"]["reviewed"] == 1
    assert result["provenance"]["matching_judgments_sha256"] == expected


def test_judge_repair_claim_must_clear_each_measured_floor():
    rows = [
        row("valid nominal pass", "passed", "a") | dict(gap_closed=1, gap_drift=None),
        row("wrong pass", "under_adapted", "b") | dict(gap_closed=0.68, gap_drift=0.47),
        row("wrong diagnosis-only", "plain_matching", "c", diagnosis=False)
        | dict(gap_closed=0.53, gap_drift=0.47),
        row("acknowledged failure", "harmful_decoder", "d") | dict(gap_closed=-1, gap_drift=-2),
    ]
    reviews = {
        "a": dict(label="passed"),
        "b": dict(label="passed"),
        "c": dict(label="misdiagnosis"),
        "d": dict(label="harmful_decoder"),
    }
    result = summarize(rows, reviews)
    assert result["judge_repair_floor_contradictions"] == 2
    assert result["passes"] == 1
