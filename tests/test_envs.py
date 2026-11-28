"""Data-out tasks: the kit hides the truth, a fake CLI edits solution.py, the harness saves it,
the task's own grader scores it, and the pass rule and failure modes read the report."""

from __future__ import annotations

import dataclasses
import json
import pickle

import pandas as pd
import pytest

from qec_drift.agent import decoder_run_cc as cc
from qec_drift.agent import envs_grade as eg
from qec_drift.agent import envs_kit as kit
from qec_drift.agent import envs_run as er
from qec_drift.agent import isolation
from qec_drift.scoring import failure_modes_envs as fm

TASK = "readout_drift"
SOLUTION = (kit.ENVS / TASK / "sandbox" / "solution.py").read_text() + "# edited by the agent\n"


@pytest.fixture(scope="module")
def kits(tmp_path_factory):
    return er.build_kits(tmp_path_factory.mktemp("envs"), [TASK])


def fake_backend(tmp_path, seen: dict) -> cc.Backend:
    def run(workdir, model, effort, max_usd, config_dir, task_prompt=None):
        seen["prompt"], seen["files"] = task_prompt, sorted(p.name for p in workdir.iterdir())
        (workdir / "solution.py").write_text(SOLUTION)
        (workdir / "NOTES_AGENT.md").write_text("nothing changed")
        return [{"type": "result", "terminal_reason": "completed"}], 0

    def prepare(name):
        d = tmp_path / "state" / name
        d.mkdir(parents=True)
        return d

    summary = dict(
        stop="completed", tokens_in=1, tokens_out=1, cost_usd=0.0, throttled=False,
        login_lost=False,
    )  # fmt: skip
    return cc.Backend(
        "fake", "fake_stream", lambda: None, prepare, run, lambda d: None, lambda ev: 2,
        lambda ev, code: summary,
    )  # fmt: skip


def test_kit_holds_hard_instances_and_no_truth(kits):
    d = kits[TASK]
    assert {p.name for p in d.iterdir()} == {
        "TASK.md", "solution.py", "dev_data", "check.py", "PROMPT.md",
    }  # fmt: skip
    data = pickle.loads(sorted((d / "dev_data").glob("*.pkl"))[0].read_bytes())
    assert data["tier"] == "hard"
    assert not {"truth", "answer", "seed", "rule", "family"} & set(data)
    assert "OVER LIMIT' if dt > 120" in (d / "check.py").read_text()
    text = er.prompt(d)
    assert "hard tier" in text and f"at most {isolation.TOOL_CALLS} tool calls" in text


def test_episode_saves_the_solution_and_a_row(tmp_path, monkeypatch, kits):
    monkeypatch.setattr(er, "solutions_dir", lambda: tmp_path / "solutions")
    monkeypatch.setattr(er, "build_kits", lambda root, envs: kits)
    seen: dict = {}
    argv = ["--model", "fake-model", "--arm", "fake_arm", "--rollouts", "1", "--envs", TASK]
    args = er.parse_args([*argv, "--out", str(tmp_path / "out")])
    df = er.run_arm(args, backend=fake_backend(tmp_path, seen))
    assert "hard tier" in seen["prompt"] and "dev_data" in seen["files"]
    row = df.iloc[0]
    assert (row.task, row.outcome, row.turns) == (f"envs-{TASK}-hard", "submitted", 2)
    saved = tmp_path / "solutions" / "fake_arm" / TASK / "r0"
    assert (saved / "solution.py").read_text() == SOLUTION
    assert json.loads((saved / "meta.json").read_text())["tier"] == "hard"
    assert pd.read_parquet(tmp_path / "out" / "fake_arm.parquet").attempt_id.notna().all()
    again = er.run_arm(args, backend=fake_backend(tmp_path, seen := {}))
    assert seen == {} and len(again) == 1  # a submitted rollout is not run twice
    monkeypatch.setattr(eg, "OUT", tmp_path / "graded")
    monkeypatch.setattr(eg, "seeds", lambda: [None, eg.CONFIG["paper_seeds"][0]])
    graded = eg.grade_arm(tmp_path / "out" / "fake_arm.parquet")
    assert graded.pass_rate.iloc[0] == pytest.approx(0.5)  # the starter: every control only
    assert len(list((tmp_path / "graded" / "reports" / TASK).iterdir())) == 1
    modes = pd.read_parquet(tmp_path / "out" / "fake_arm_failure_modes.parquet")
    assert modes.leaf.tolist() == ["never_changed"]


@pytest.mark.parametrize("task", sorted(kit.TASKS))
def test_hard_dev_data_leaves_out_every_out_of_model_instance(task):
    out_of_model = kit.TASKS[task][2]
    families = [fam for fam, _ in kit.instances(task, "hard")]
    kept = sum(not out_of_model(fam) for fam in families)
    assert 0 < kept < len(families)  # the hard tier has such instances, and they are dropped
    assert len(kit.public_data(task, "hard")) == kept


def test_the_pass_rule_is_awareness_passed_per_instance():
    base = dict(truth_changed=True, said=True, diag=0.5, fix=0.5)
    assert eg.passed(base)
    assert not eg.passed(dict(base, said=False))
    assert not eg.passed(dict(base, diag=0.4))
    assert not eg.passed(dict(base, fix=0.49))
    assert eg.passed(dict(truth_changed=False, said=False, diag=None, fix=None))
    assert not eg.passed(dict(truth_changed=False, said=None, diag=None, fix=None))


def test_the_starter_scores_the_floor_on_the_public_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(eg, "OUT", tmp_path)
    monkeypatch.setattr(eg, "seeds", lambda: [None])
    sol = tmp_path / "solution.py"
    sol.write_text(SOLUTION)
    rows = eg.instance_rows(TASK, sol, "starter")
    assert len(rows) == 30 and not any(r["error"] for r in rows)
    controls = [r for r in rows if not r["truth_changed"]]
    assert all(r["passed"] for r in controls) and not any(
        r["passed"] for r in rows if r["truth_changed"]
    )
    assert (tmp_path / "reports" / TASK / "starter" / "public.json").exists()


@pytest.mark.parametrize(
    ("outcome", "said", "truth", "error", "expected"),
    [
        ("error", [True], [True], [False], "harness_error"),
        ("submitted", [None, None], [True, False], [True, True], "invalid_answer"),
        ("submitted", [False, False], [True, False], [False, False], "never_changed"),
        ("submitted", [True, True], [True, False], [False, False], "always_changed"),
        ("submitted", [True, False, True, False], [True, True, False, False], [False] * 4,
         "false_alarms"),
    ],
)  # fmt: skip
def test_failure_mode_gates(outcome, said, truth, error, expected):
    rows = pd.DataFrame(
        dict(
            said=said,
            truth_changed=truth,
            error=error,
            diag=[1.0] * len(said),
            fix=[1.0] * len(said),
        )
    )
    assert fm.leaf(dict(outcome=outcome), rows) == expected


def test_every_task_has_a_kit_entry_and_a_report_reader():
    tasks = {p.name for p in kit.ENVS.iterdir() if (p / "evaluate.py").is_file()}
    assert tasks == set(kit.TASKS) == set(eg.READERS)


def test_a_rollout_without_a_solution_is_kept_not_rerun(tmp_path, monkeypatch, kits):
    monkeypatch.setattr(er, "solutions_dir", lambda: tmp_path / "solutions")
    monkeypatch.setattr(er, "build_kits", lambda root, envs: kits)
    base = fake_backend(tmp_path, {})
    idle = dataclasses.replace(base, run=lambda workdir, *a, **k: ([{"type": "result"}], 0))
    argv = ["--model", "m", "--arm", "idle", "--rollouts", "1", "--envs", TASK]
    args = er.parse_args([*argv, "--out", str(tmp_path / "out")])
    assert er.run_arm(args, backend=idle).outcome.tolist() == ["no_solution"]
    never = dataclasses.replace(base, run=lambda *a, **k: pytest.fail("a kept rollout ran again"))
    assert er.run_arm(args, backend=never).outcome.tolist() == ["no_solution"]
