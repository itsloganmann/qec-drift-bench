"""Decoder-gap harness: the noise builders, the references, the sandbox and a scripted episode."""

from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from qec_drift.agent import decoder_run as dr
from qec_drift.agent import decoder_task as dt
from qec_drift.agent import sandbox


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(dt, "SHOTS", {"train": 3000, "val": 500, "deploy": 500, "test": 20000})


def test_crosstalk_adds_pair_noise_the_nominal_circuit_lacks():
    base = dt.nominal(3)
    more = dt.with_crosstalk(base)

    def count(c):
        return sum(
            i.name == "DEPOLARIZE2" and i.gate_args_copy() == [dt.Q_CROSSTALK]
            for i in c.flattened()
        )

    assert count(base) == 0 and count(more) > 0
    assert more.num_detectors == base.num_detectors and more.num_observables == 1


def test_scaled_qubits_keep_the_mean_noise_and_the_structure():
    base = dt.nominal(3)
    scaled = dt.with_scaled_qubits(base, 1.0, seed=1)
    assert scaled.num_detectors == base.num_detectors
    assert str(scaled) != str(base)
    ps = [i.gate_args_copy()[0] for i in scaled.flattened() if i.name == "X_ERROR"]
    assert 0 < np.mean(ps) < 0.01 and max(ps) <= 0.5


def test_references_are_ordered_and_the_gap_is_zero_to_one(small):
    task = dt.Task(5, "both")
    det, obs = dt.test_shots(task)
    refs = dt.references(5, "both", det, obs)
    assert refs["true_corr"] < refs["nominal"]
    assert dt.gap_closed(refs["nominal"], refs) == pytest.approx(0.0)
    assert dt.gap_closed(refs["true_corr"], refs) == pytest.approx(1.0)
    assert dt.gap_closed(2 * refs["nominal"], refs) < 0


def test_sandbox_blocks_network_secrets_and_outside_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")
    (tmp_path / "t.py").write_text(
        "import os, socket\n"
        "def t(name, f):\n"
        "    try:\n        f(); print(name, 'ALLOWED')\n"
        "    except Exception as e:\n        print(name, 'blocked')\n"
        "t('net', lambda: socket.create_connection(('1.1.1.1', 53), timeout=2))\n"
        "t('secrets', lambda: open(os.path.expanduser('~/../logan/.claude/secrets.env')).read())\n"
        "t('outside', lambda: open('/Users/Shared/escape.txt', 'w').write('x'))\n"
        "t('inside', lambda: open('ok.txt', 'w').write('x'))\n"
        "print('key' , os.environ.get('ANTHROPIC_API_KEY'))\n"
    )
    code, out = sandbox.run(["t.py"], tmp_path, 60)
    assert "net blocked" in out and "outside blocked" in out and "inside ALLOWED" in out
    assert "secrets ALLOWED" not in out and "key None" in out


def test_sandbox_times_out(tmp_path):
    (tmp_path / "t.py").write_text("import time\ntime.sleep(30)\n")
    code, out = sandbox.run(["t.py"], tmp_path, 2)
    assert code == 124 and "timed out" in out


class _Block(SimpleNamespace):
    def model_dump(self, **_):
        return dict(vars(self))


class _Scripted:
    """First turn writes a plain-matching decoder, second turn submits."""

    DECODER = (
        "import numpy as np, pymatching, stim\n"
        "c = stim.Circuit(open('nominal.stim').read())\n"
        "dem = c.detector_error_model(decompose_errors=True)\n"
        "m = pymatching.Matching.from_detector_error_model(dem)\n"
        "def decode(det):\n    return m.decode_batch(det)\n"
    )

    def __init__(self):
        self.turn = 0

    def _create_with_body(self, kwargs):
        self.turn += 1
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        if self.turn == 1:
            code = f"open('decoder.py','w').write({self.DECODER!r})\nprint('written')"
            blocks = [_Block(type="tool_use", id="a", name="run_python", input={"code": code})]
        else:
            blocks = [_Block(type="tool_use", id="b", name="submit", input={})]
        return SimpleNamespace(content=blocks, usage=usage, stop_reason="tool_use"), "{}", "req_x"


def test_a_scripted_episode_scores_plain_matching_near_zero(small, tmp_path):
    row, traj = dr.run_episode(
        _Scripted(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path
    )
    assert row["outcome"] == "submitted" and row["turns"] == 2
    assert abs(row["gap_closed"]) < 0.25 and not row["uses_correlations"]
    assert row["agree_nominal_plain"] == 1.0 and row["agree_nominal_corr"] < 1.0
    assert [m["role"] for m in traj["messages"]] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    assert "written" in traj["messages"][2]["content"][0]["content"]
    assert not (tmp_path / "d5-both" / ".score").exists()


def test_a_relative_work_folder_still_scores(small, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    row, _ = dr.run_episode(
        _Scripted(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", Path("rel")
    )
    assert row["outcome"] == "submitted"


class _StopsEarly(_Scripted):
    """Writes the decoder, then ends its turn without submitting; submits after the reminder."""

    def _create_with_body(self, kwargs):
        self.turn += 1
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        if self.turn == 1:
            code = f"open('decoder.py','w').write({self.DECODER!r})"
            blocks = [_Block(type="tool_use", id="a", name="run_python", input={"code": code})]
        elif self.turn == 2:
            blocks = [_Block(type="text", text="done")]
        else:
            blocks = [_Block(type="tool_use", id="b", name="submit", input={})]
        return SimpleNamespace(content=blocks, usage=usage, stop_reason="end_turn"), "{}", "req_y"


def test_a_model_that_stops_without_submitting_gets_a_reminder(small, tmp_path):
    row, traj = dr.run_episode(
        _StopsEarly(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path
    )
    assert row["outcome"] == "submitted" and row["turns"] == 3
    assert any("Call submit" in str(m["content"]) for m in traj["messages"] if m["role"] == "user")


def test_test_labels_never_reach_the_work_folder(small, tmp_path):
    dr.run_episode(_Scripted(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path)
    files = {p.name for p in (tmp_path / "d5-both").iterdir()}
    assert files >= {"nominal.stim", "train.npz", "val.npz", "deploy.npz", "decoder.py"}
    assert "test.npz" not in files
    assert "obs" not in np.load(tmp_path / "d5-both" / "deploy.npz").files
    assert socket  # imported so a reader sees the sandbox test is about the network


def test_sandbox_reads_only_what_it_is_given(tmp_path):
    work, outside = tmp_path / "work", tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("hunter2")
    (work / "mine.txt").write_text("ok")
    program = (
        "import os\n"
        f"for name in ({str(outside / 'secret.txt')!r}, 'mine.txt',\n"
        "             os.path.expanduser('~/.zshenv')):\n"
        "    try:\n        print(name[-12:], 'READ', open(name).read()[:7])\n"
        "    except OSError:\n        print(name[-12:], 'blocked')\n"
    )
    code, out = sandbox.run(["-"], work, 30, stdin=program)
    assert "secret.txt blocked" in out and "mine.txt READ ok" in out and ".zshenv blocked" in out
    code, out = sandbox.run(["-"], work, 30, stdin=program, read=[outside])
    assert "secret.txt READ hunter2" in out


def test_sandbox_runs_the_numeric_stack_and_a_pool(tmp_path):
    program = (
        "import numpy, scipy.optimize, stim, pymatching, multiprocessing as mp\n"
        "with mp.get_context('fork').Pool(2) as pool:\n    print('pool', pool.map(abs, [-1, -2]))\n"
    )
    code, out = sandbox.run(["-"], tmp_path, 120, stdin=program)
    assert code == 0 and "pool [1, 2]" in out


class _Attacker(_Scripted):
    """Leaves links where the harness reads and writes, then writes a real decoder and submits."""

    victim_file: Path
    victim_dir: Path
    secret_link: bool = False

    def _create_with_body(self, kwargs):
        self.turn += 1
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        if self.turn == 1:
            code = (
                "import os\n"
                f"names = ['snippet_0.py', 'pred.npy'] + (['decoder.py'] * {self.secret_link})\n"
                "for name in names:\n"
                f"    os.symlink({str(self.victim_file)!r}, name)\n"
                f"os.symlink({str(self.victim_dir)!r}, '.score')\n"
            )
            if not self.secret_link:
                code += f"open('decoder.py','w').write({self.DECODER!r})\n"
            blocks = [_Block(type="tool_use", id="a", name="run_python", input={"code": code})]
        else:
            blocks = [_Block(type="tool_use", id="b", name="submit", input={})]
        return SimpleNamespace(content=blocks, usage=usage, stop_reason="tool_use"), "{}", "req_z"


def test_links_left_by_the_agent_do_not_make_the_harness_write_elsewhere(small, tmp_path):
    victim_dir = tmp_path / "victim"
    victim_dir.mkdir()
    victim = victim_dir / "precious.txt"
    victim.write_text("keep me")
    agent = _Attacker()
    agent.victim_file, agent.victim_dir = victim, victim_dir
    row, _ = dr.run_episode(agent, dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path / "w")
    assert row["outcome"] == "submitted"
    assert victim.read_text() == "keep me"
    assert [p.name for p in victim_dir.iterdir()] == ["precious.txt"]


def test_a_decoder_that_is_a_link_to_a_secret_is_not_read_or_stored(small, tmp_path):
    secret_dir = tmp_path / "s"
    secret_dir.mkdir()
    secret = secret_dir / "secret.txt"
    secret.write_text("TOP-SECRET-VALUE")
    agent = _Attacker()
    agent.victim_file, agent.victim_dir, agent.secret_link = secret, secret_dir, True
    row, traj = dr.run_episode(
        agent, dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path / "w"
    )
    assert row["decoder_src"] == "" and "TOP-SECRET-VALUE" not in str(row) + str(traj)
    assert row["outcome"] != "submitted"
    assert dr.read_regular_file(secret) == "TOP-SECRET-VALUE"  # a regular file still reads


class _BigDecoder(_Scripted):
    """Writes a decoder that inlines about 300 KB of text, as the fitted d = 7 models do."""

    DECODER = _Scripted.DECODER + "# " + "x" * 300_000 + "\n"


def test_a_300_kb_decoder_is_scored(small, tmp_path):
    row, _ = dr.run_episode(
        _BigDecoder(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path
    )
    assert row["outcome"] == "submitted" and row["stop"] == "submitted"
    assert row["decoder_bytes"] > 300_000 and row["score_error"] == ""


def test_decoder_problem_names_the_reason(tmp_path):
    assert dr.decoder_problem(tmp_path) == "decoder.py is missing"
    (tmp_path / "decoder.py").write_text("")
    assert dr.decoder_problem(tmp_path) == "decoder.py is empty"
    (tmp_path / "decoder.py").write_text("x" * 20)
    assert dr.decoder_problem(tmp_path, limit=10) == "decoder.py is 20 bytes; the limit is 10"
    assert dr.decoder_problem(tmp_path) == ""


class _NeverSubmits(_Scripted):
    """Writes the decoder, then only talks, through both reminders."""

    def _create_with_body(self, kwargs):
        self.turn += 1
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        if self.turn == 1:
            code = f"open('decoder.py','w').write({self.DECODER!r})"
            blocks = [_Block(type="tool_use", id="a", name="run_python", input={"code": code})]
        else:
            blocks = [_Block(type="text", text="done")]
        return SimpleNamespace(content=blocks, usage=usage, stop_reason="end_turn"), "{}", "req_z"


def test_a_model_that_only_talks_is_auto_scored(small, tmp_path):
    row, _ = dr.run_episode(
        _NeverSubmits(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path
    )
    assert row["outcome"] == "auto_scored" and row["stop"] == "ended_turn"
    assert row["turns"] == 4 and abs(row["gap_closed"]) < 0.25
    assert row["n_run_python"] == 1 and row["n_timeouts"] == 0


def test_an_episode_budget_stops_the_loop_and_scores_what_exists(small, tmp_path, monkeypatch):
    monkeypatch.setattr(dr.pricing, "estimate_usd", lambda *a, **k: 9.0)
    row, _ = dr.run_episode(
        _Scripted(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path, max_usd=1.0
    )
    assert row["stop"] == "episode_budget" and row["turns"] == 1
    assert row["outcome"] == "auto_scored" and row["cost_usd"] == 9.0


class _Reporter(_Scripted):
    """Submits with a model assessment: not adequate, confidence 80."""

    def _create_with_body(self, kwargs):
        msg, body, rid = super()._create_with_body(kwargs)
        for b in msg.content:
            if b.name == "submit":
                b.input = {"model_adequate": False, "confidence": 80, "what_is_wrong": "crosstalk",
                           "evidence": "pair correlations"}  # fmt: skip
        return msg, body, rid


def test_tools_add_the_assessment_only_with_awareness():
    assert dr.tools(False)[1]["input_schema"]["properties"] == {}
    assert set(dr.tools(True)[1]["input_schema"]["properties"]) == set(dr.REPORT_FIELDS)
    assert "model_adequate" in dr.prompt(True) and "model_adequate" not in dr.prompt(False)


def test_the_assessment_is_recorded_and_scored(small, tmp_path):
    row, traj = dr.run_episode(
        _Reporter(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path, awareness=True
    )
    assert row["outcome"] == "submitted" and row["adequate_truth"] is False
    assert row["report_adequate"] is False and row["report_confidence"] == 80
    assert row["report_text"] == "crosstalk"
    assert row["awareness_brier"] == pytest.approx(0.04)  # p(adequate) = 0.2 against truth 0
    assert "model_adequate" in traj["tools"][1]["input_schema"]["properties"]


def test_a_missing_assessment_counts_as_adequate_at_100(small, tmp_path):
    row, _ = dr.run_episode(
        _Scripted(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path, awareness=True
    )
    assert row["report_adequate"] is True and row["report_confidence"] == 100
    assert row["awareness_brier"] == pytest.approx(1.0)
    row, _ = dr.run_episode(_Scripted(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path)
    assert row["awareness_brier"] is None  # tier 1 runs are unchanged


def test_report_from_clamps_and_defaults():
    r = dr.report_from({"model_adequate": True, "confidence": "250"})
    assert r["report_adequate"] is True and r["report_confidence"] == 100
    assert dr.report_from({"confidence": "x"})["report_confidence"] == 100
    assert (
        dr.awareness_brier(dr.report_from({"model_adequate": True, "confidence": 100}), True) == 0
    )


def test_drift_tasks_have_a_stale_reference_and_an_adequate_negative(small):
    drift = dt.Task(3, "hetero", "meas5")
    det, obs = dt.test_shots(drift)
    refs = dt.task_references(drift, det, obs)
    assert set(refs) >= {"nominal", "true_corr", "stale_corr"}
    assert refs["true_corr"] <= refs["nominal"] and not drift.model_adequate
    assert drift.name == "d3-hetero-dmeas5"
    assert dt.Task(3, "none", "requbit").name == "d3-none-drequbit"
    with pytest.raises(ValueError, match="unknown drift kind"):
        dt.with_drift(dt.nominal(3), "nope", 3)
    adequate = dt.Task(3, "none")
    assert adequate.model_adequate and "stale_corr" not in dt.task_references(adequate, det, obs)
    a, b = dt.test_shots(dt.Task(3, "none")), dt.test_shots(dt.Task(3, "none", "", 1))
    assert not np.array_equal(a[0], b[0])  # a replicate seed changes the shots
    names = [t.name for t in dt.tier2_tasks()]
    assert (
        len(names) == len(set(names)) == 14 and sum(t.model_adequate for t in dt.tier2_tasks()) == 4
    )
    assert dt.tasks_by_name("d5-both,d7-none-dmeas5")[1] == dt.Task(7, "none", "meas5")


def test_sandbox_kills_children_the_code_left_behind(tmp_path):
    (tmp_path / "t.py").write_text(
        "import subprocess, sys\n"
        'child = \'import time; time.sleep(2); open("late.txt", "w").write("x")\'\n'
        "subprocess.Popen([sys.executable, '-c', child], stdout=subprocess.DEVNULL,"
        " stderr=subprocess.DEVNULL)\n"
        "print('parent done')\n"
    )
    code, out = sandbox.run(["t.py"], tmp_path, 30)
    assert code == 0 and "parent done" in out
    import time

    time.sleep(3)
    assert not (tmp_path / "late.txt").exists()


def test_no_submit_leaves_the_brier_undefined_and_a_retry_keeps_the_report(small, tmp_path):
    row, _ = dr.run_episode(
        _NeverSubmits(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path, awareness=True
    )
    assert row["reported"] is False and row["awareness_brier"] != row["awareness_brier"]
    first = dr.report_from({"model_adequate": False, "confidence": 70})
    assert first["report_adequate"] is False and first["report_confidence"] == 70
    assert (
        dr.report_from({"model_adequate": "false", "confidence": 99.6})["report_confidence"] == 100
    )
    assert dr.report_from({"model_adequate": "false"})["report_adequate"] is False
    assert (
        dr.report_from({"model_adequate": "maybe", "confidence": 1e999})["report_confidence"] == 100
    )
    assert dr.report_from({"confidence": 0.9})["report_confidence"] == 1
    assert len(dr.report_from({"evidence": "x" * 5000})["report_evidence"]) == dr.TEXT_LIMIT


class _BadShape(_Scripted):
    DECODER = (
        "import numpy as np\ndef decode(det):\n    return np.zeros((det.shape[0], 2), dtype=bool)\n"
    )


def test_a_decoder_with_the_wrong_shape_is_a_failed_submit_not_a_crash(small, tmp_path):
    row, _ = dr.run_episode(_BadShape(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path)
    assert (
        row["outcome"] in ("failed_submit", "no_submit", "auto_scored")
        or row["outcome"] == "submitted"
    )
    assert row["outcome"] != "submitted" and "shape" in row["score_error"]


class _Leaker(_Scripted):
    """Its decoder copies the test shots into the work folder, then fails on purpose."""

    DECODER = (
        "import shutil, sys, os\n"
        "here = os.path.dirname(os.path.abspath(__file__))\n"
        "def decode(det):\n"
        "    shutil.copy(sys.argv[1], os.path.join(here, 'stolen.npz'))\n"
        "    raise RuntimeError('boom')\n"
    )


def test_a_failing_decoder_cannot_leave_the_test_shots_in_the_work_folder(small, tmp_path):
    row, _ = dr.run_episode(_Leaker(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path)
    assert row["outcome"] != "submitted"
    assert not (tmp_path / "d5-both" / "stolen.npz").exists()


def test_safe_episode_turns_an_exception_into_an_error_row(small, tmp_path):
    class _Boom:
        def _create_with_body(self, kwargs):
            raise RuntimeError("api down")

    row, traj = dr.safe_episode(_Boom(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path)
    assert row["outcome"] == "error" and "api down" in row["score_error"]
    assert traj["messages"] == [] and row["cost_usd"] == 0.0


def test_tasks_by_name_dedupes_and_names_unknowns():
    assert dt.tasks_by_name("d5-both, d5-both") == [dt.Task(5, "both")]
    with pytest.raises(ValueError, match="unknown task names"):
        dt.tasks_by_name("d5-nope")


class _Busy(_Scripted):
    """Runs a trivial command every turn and never submits."""

    def _create_with_body(self, kwargs):
        self.turn += 1
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        blocks = [_Block(type="tool_use", id=f"r{self.turn}", name="run_python",
                         input={"code": "print(1)"})]  # fmt: skip
        return SimpleNamespace(content=blocks, usage=usage, stop_reason="tool_use"), "{}", "req_b"


def test_the_prompt_states_the_budget_and_the_last_calls_count_down(small, tmp_path, monkeypatch):
    assert f"at most {dr.MAX_TURNS} tool calls" in dr.prompt()
    monkeypatch.setattr(dr, "MAX_TURNS", 3)
    row, traj = dr.run_episode(_Busy(), dt.Task(5, "both"), "claude-haiku-5-5", "medium", tmp_path)
    notes = [m["content"][0]["content"] for m in traj["messages"] if m["role"] == "tool"]
    assert [("left before the task ends" in n) for n in notes] == [True, True, True]
    assert "2 tool calls left" in notes[0] and "1 tool call left" in notes[1]
    assert row["stop"] == "turns" and row["outcome"] == "no_submit"
