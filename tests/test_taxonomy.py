"""The one failure taxonomy: every input lands in exactly one label; features read every format."""

from __future__ import annotations

import itertools

from qec_drift.scoring import taxonomy as tx
from qec_drift.scoring.failure_modes_decoder import DECODER_LEAVES

VERDICTS = ("passed", "missed_diagnosis", "missed_fix", "missed_both", "no_score")


def test_every_input_lands_in_exactly_one_label_and_every_label_is_reachable():
    seen = set()
    for leaf, verdict, ran, budget in itertools.product(
        DECODER_LEAVES, VERDICTS, (True, False), (True, False)
    ):
        lab, gate = tx.label(leaf, verdict, ran=ran, budget_hit=budget)
        assert lab in tx.LABELS and gate == f"G{tx.LABELS.index(lab)}"
        seen.add(lab)
    assert seen == set(tx.LABELS)


def test_the_gates_in_order():
    assert tx.label("fitted_correlated", "passed", ran=False, budget_hit=False)[0] == "invalid_run"
    assert tx.label("fitted_correlated", "passed", ran=True, budget_hit=True)[0] == "passed"
    assert tx.label("no_decoder", "no_score", ran=True, budget_hit=True)[0] == "out_of_budget"
    assert tx.label("no_decoder", "no_score", ran=True, budget_hit=False)[0] == "no_submission"
    assert tx.label("unscored", "no_score", ran=True, budget_hit=False)[0] == "broken_decoder"
    assert tx.label("worse_than_plain", "missed_both", ran=True, budget_hit=False)[0] == (
        "harmful_decoder"
    )
    assert tx.label("fitted_plain", "missed_diagnosis", ran=True, budget_hit=False)[0] == (
        "misdiagnosis"
    )
    assert tx.label("nominal_plain", "missed_fix", ran=True, budget_hit=False)[0] == (
        "nominal_unchanged"
    )
    assert tx.label("fitted_plain", "missed_both", ran=True, budget_hit=False)[0] == (
        "plain_matching"
    )
    assert tx.label("fitted_correlated", "missed_fix", ran=True, budget_hit=False)[0] == (
        "under_adapted"
    )


def test_features_read_claude_code_and_codex_records():
    cc = dict(
        events=[
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "cat ../x"}}
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [{"type": "tool_result", "content": "Operation not permitted"}]
                },
            },
            {"type": "harness", "note": "tool-call limit (40)"},
        ]
    )
    f = tx.features(cc)
    assert f.budget_hit and f.flags()["denied"] and f.flags()["outside"]
    assert not f.env_missing and not f.flags()["network"]
    codex = dict(
        events=[
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "python3 -m pip install --target vendor stim",
                    "aggregated_output": "No module named 'stim'",
                },
            }
        ]
    )
    f = tx.features(codex)
    assert f.env_missing and f.flags()["network"] and f.flags()["own_copy"] and not f.budget_hit
    inside = tx.features(
        {"events": [{"type": "item.completed", "item": {"type": "command_execution",
         "command": "cat /Users/x/work/a/t/report.json; python3 -c 'install numpy'"}}]}
    )  # fmt: skip
    assert not inside.env_missing and not inside.flags()["own_copy"]
    assert inside.flags()["outside"] and not inside.flags(("/Users/x/work/a/t",))["outside"]
    assert not tx.features({"events": [{"type": "item.completed", "item": {}}]}).env_missing


def test_clear_removes_read_only_caches(tmp_path):
    from qec_drift.agent import isolation

    cache = tmp_path / "w" / ".tmp" / "uv" / "wheel"
    cache.mkdir(parents=True)
    (cache / "x.whl").write_text("x")
    cache.chmod(0o555)
    cache.parent.chmod(0o555)
    isolation.clear(tmp_path / "w")
    assert not (tmp_path / "w").exists()


def test_pages_show_the_one_label_of_the_last_attempt(tmp_path):
    import gzip
    import json

    import pandas as pd

    from qec_drift.agent import transcripts

    archive = tmp_path / "decoder_x_max_cc.jsonl.gz"
    first = {"task": "t1", "model": "m", "events": [], "report": {"try": 1}}
    rerun = {"task": "t1", "model": "m", "events": [], "report": {"try": 2}}
    archive.write_bytes(
        b"".join(gzip.compress((json.dumps(r) + "\n").encode()) for r in (first, rerun))
    )
    table = tmp_path / "x_max_cc.parquet"
    pd.DataFrame([dict(task="t1", outcome="submitted", passed=False)]).to_parquet(table)
    modes = dict(task="t1", leaf="nominal_plain", gate="D4", verdict="missed_fix")
    pd.DataFrame([modes | dict(verdict_rel="missed_fix")]).to_parquet(
        tmp_path / "x_max_cc_failure_modes.parquet"
    )
    pd.DataFrame([dict(task="t1", label="nominal_unchanged", gate="G7")]).to_parquet(
        tmp_path / "x_max_cc_taxonomy.parquet"
    )
    folder = transcripts.render_archive(archive, table)
    page = (folder / "t1.md").read_text()
    assert "`nominal_unchanged` (G7), from the decoder leaf `nominal_plain`" in page
    assert '"try": 2' in page
    index = (folder / "README.md").read_text()
    assert index.count("[t1](t1.md)") == 1 and "nominal_unchanged" in index


def test_a_fetch_of_the_public_source_is_a_probe():
    rec = {"events": [{"type": "item.completed", "item": {"type": "command_execution",
           "command": "git clone https://github.com/itsloganmann/qec-drift-bench"}}]}  # fmt: skip
    assert tx.features(rec).flags()["probe"]
