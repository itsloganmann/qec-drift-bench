"""The hard drift tier: local faults, the diagnosis report, the pij baseline, and the pass rule."""

from __future__ import annotations

import json

import numpy as np
import pytest

from qec_drift.agent import awareness as aw
from qec_drift.agent import decoder_run as dr
from qec_drift.agent import decoder_task as dt
from qec_drift.agent import drift, noise
from qec_drift.decoders import pij
from tests.test_decoder_agent import _Scripted


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(dt, "SHOTS", {"train": 3000, "val": 500, "deploy": 500, "test": 20000})


def _noise_groups(c):
    """(name, probability, targets) per target group of every noise instruction."""
    out = []
    for inst in c.flattened():
        if inst.name in noise.NOISE_GATES:
            arity, p = noise.NOISE_GATES[inst.name], inst.gate_args_copy()[0]
            t = [x.value for x in inst.targets_copy()]
            out += [(inst.name, p, tuple(t[i : i + arity])) for i in range(0, len(t), arity)]
    return out


def test_a_bad_qubit_changes_only_the_noise_that_touches_it():
    base = noise.nominal(3)
    bad = drift.truth(base, "bq3", 3, 0).qubits
    changed = _noise_groups(drift.apply(base, "bq3", 3, 0))
    assert len(changed) == len(_noise_groups(base))
    for _, p, targets in changed:
        assert (p > noise.P_NOMINAL * 1.5) == bool(bad & set(targets))
        assert p == pytest.approx(noise.P_NOMINAL * (3 if bad & set(targets) else 1))


def test_a_bad_gate_changes_one_cx_pair_and_a_bad_readout_one_measure_qubit():
    base = noise.nominal(3)
    pair = drift.truth(base, "bg5", 3, 0).qubits
    pairs = {tuple(sorted(p)) for p in noise.cx_pairs(base)}
    assert len(pair) == 2 and tuple(sorted(pair)) in pairs
    hot = [(n, t) for n, p, t in _noise_groups(drift.apply(base, "bg5", 3, 0)) if p > 0.004]
    assert hot and all(n == "DEPOLARIZE2" and set(t) == pair for n, t in hot)
    q = drift.truth(base, "br5", 3, 0).qubits
    assert len(q) == 1 and q <= set(noise.measure_qubits(base))
    hot = [(n, t) for n, p, t in _noise_groups(drift.apply(base, "br5", 3, 0)) if p > 0.004]
    assert hot and all(n == "X_ERROR" and set(t) == q for n, t in hot)


def test_ladder_rungs_share_a_target_and_seeds_move_it():
    base = noise.nominal(5)
    assert drift.truth(base, "bq3", 5, 0).qubits == drift.truth(base, "bq6", 5, 0).qubits
    assert len({drift.truth(base, "bq3", 5, s).qubits for s in range(6)}) >= 3


def test_global_kinds_and_the_grammar():
    base = noise.nominal(3)
    assert drift.truth(base, "meas2", 3, 0) == drift.Truth(
        "global", frozenset(noise.coordinates(base)), "readout"
    )
    assert drift.truth(base, "xt3", 3, 0).qubits == frozenset(noise.data_qubits(base))
    assert drift.truth(base, "requbit", 3, 0).mechanism == "all"
    assert drift.truth(base, "", 3, 0) == drift.NO_DRIFT
    assert drift.parse("meas5") == ("meas", 5.0) and drift.parse("bq2.5") == ("bq", 2.5)
    for bad in ("meas", "zz3", "bq", "5bq"):
        with pytest.raises(ValueError):
            drift.parse(bad)


def test_report_from_parses_the_diagnosis_fields():
    r = aw.report_from(
        {
            "model_adequate": False,
            "confidence": 90,
            "scope": "Local",
            "changed_qubits": [7, "7", 3.0, True, "x", -1, 2.5],
            "mechanism": "GATE",
        }  # fmt: skip
    )
    assert r["report_scope"] == "local" and r["report_qubits"] == [-1, 3, 7]
    assert r["report_mechanism"] == "gate"
    assert aw.report_from({})["report_scope"] == "none"
    missing = aw.report_from({"model_adequate": False, "confidence": 70})
    assert missing["report_scope"] == "" and missing["report_qubits"] == []
    junk = aw.report_from({"scope": "everywhere", "changed_qubits": "5", "mechanism": 3})
    assert junk["report_scope"] == "" and junk["report_qubits"] == []
    assert junk["report_mechanism"] == ""


def test_diagnosis_needs_the_scope_and_half_the_qubits():
    local = drift.Truth("local", frozenset({5}), "all")
    say = lambda scope, qubits: aw.report_from(  # noqa: E731
        {"model_adequate": False, "scope": scope, "changed_qubits": qubits, "mechanism": "all"}
    )
    assert aw.diagnosis(say("local", [5, 6]), local)["diagnosis_correct"]
    assert aw.diagnosis(say("local", [5, 6]), local)["localization"] == pytest.approx(0.5)
    assert not aw.diagnosis(say("local", [6]), local)["diagnosis_correct"]
    assert not aw.diagnosis(say("local", [5, 6, 7]), local)["diagnosis_correct"]
    assert not aw.diagnosis(say("global", [5]), local)["diagnosis_correct"]
    wide = drift.Truth("global", frozenset(range(40)), "readout")
    verdict = aw.diagnosis(say("global", []), wide)
    assert verdict["diagnosis_correct"] and not verdict["mechanism_correct"]
    assert verdict["localization"] != verdict["localization"]
    assert aw.diagnosis(aw.report_from({}), drift.NO_DRIFT)["diagnosis_correct"]
    assert not aw.diagnosis(say("local", []), drift.NO_DRIFT)["diagnosis_correct"]


def test_pass_needs_a_correct_diagnosis_and_half_the_gap():
    assert aw.passed(True, 0.5) and aw.passed(True, 1.2)
    assert not aw.passed(True, 0.49) and not aw.passed(False, 1.0)
    assert not aw.passed(True, float("nan"))


def test_pij_refit_recovers_the_nominal_model_and_sees_readout_drift():
    c = noise.nominal(3)
    dem = c.detector_error_model(decompose_errors=True)
    nominal = pij.nominal_probabilities(dem)
    det, _ = dt.sample(c, 50_000, 1)
    fit, events = pij.fitted_probabilities(dem, det)
    ratios = np.array([fit[k] / nominal[k] for k in nominal])
    assert 0.85 < np.median(ratios) < 1.2 and min(events.values()) >= 0
    det5, _ = dt.sample(drift.apply(c, "meas5", 3, 0), 50_000, 2)
    fit5, _ = pij.fitted_probabilities(dem, det5)
    assert max(fit5[k] / nominal[k] for k in nominal) > 2.5
    refit = pij.refit(dem, det5)
    assert refit.num_errors == dem.num_errors and refit.num_detectors == dem.num_detectors
    plain, corr = pij.decoders(refit)
    assert plain.num_detectors == corr.num_detectors == dem.num_detectors


def test_hard_tasks_are_named_and_resolvable():
    tasks = dt.hard_tasks()
    names = [t.name for t in tasks]
    assert len(names) == len(set(names)) == 30
    assert sum(t.model_adequate for t in tasks) == 5
    assert "d5-none-dbq30-s2-n2000" in names and "d5-none-dbq15+line5-s1" in names
    assert [t.name for t in dt.tasks_by_name("d5-none-dbg40, d5-hetero-dmeas5")] == [
        "d5-none-dbg40",
        "d5-hetero-dmeas5",
    ]
    assert dt.Task(5, "none", "bq3", deploy=5000).name == "d5-none-dbq3-n5000"
    assert dt.Task(5, "none", "bq3").truth.scope == "local"


def test_references_include_the_pij_baseline(small):
    task = dt.Task(5, "none", "br10")
    det, obs = dt.test_shots(task)
    refs = dt.task_references(task, det, obs)
    assert {"stale_corr", "pij_plain", "pij_corr"} <= set(refs)
    assert 0 <= refs["pij_corr"] <= 1 and refs["true_corr"] <= refs["nominal"]


class _Diagnoser(_Scripted):
    """Submits with a local diagnosis naming the given qubits."""

    def __init__(self, qubits):
        super().__init__()
        self.qubits = qubits

    def _create_with_body(self, kwargs):
        msg, body, rid = super()._create_with_body(kwargs)
        for b in msg.content:
            if b.name == "submit":
                b.input = {"model_adequate": False, "confidence": 90, "scope": "local",
                           "changed_qubits": self.qubits, "mechanism": "all"}  # fmt: skip
        return msg, body, rid


def test_an_episode_scores_the_diagnosis_and_the_pass(small, tmp_path):
    task = dt.Task(5, "none", "bq6")
    right = sorted(task.truth.qubits)
    row, _ = dr.run_episode(
        _Diagnoser(right), task, "claude-haiku-5-5", "medium", tmp_path, awareness=True
    )
    assert row["truth_scope"] == "local" and row["truth_qubits"] == right
    assert row["diagnosis_correct"] and row["localization"] == 1.0
    assert row["passed"] == (row["gap_closed"] >= aw.PASS_GAP)
    row, _ = dr.run_episode(
        _Diagnoser([right[0] + 1000]), task, "claude-haiku-5-5", "medium", tmp_path, awareness=True
    )
    assert not row["diagnosis_correct"] and row["passed"] is False


def test_shrinkage_keeps_a_rarely_seen_edge_at_nominal():
    c = noise.nominal(3)
    dem = c.detector_error_model(decompose_errors=True)
    det, _ = dt.sample(drift.apply(c, "meas5", 3, 0), 300, 2)  # too few shots to trust a fit
    before = [i.args_copy()[0] for i in dem.flattened() if i.type == "error"]
    shrunk = [i.args_copy()[0] for i in pij.refit(dem, det).flattened() if i.type == "error"]
    raw = [i.args_copy()[0] for i in pij.refit(dem, det, 0.0).flattened() if i.type == "error"]
    move = lambda ps: np.median(np.abs(np.log(np.array(ps) / np.array(before))))  # noqa: E731
    assert move(shrunk) < move(raw)


def test_combined_kinds_apply_in_order_and_join_their_truth():
    base = noise.nominal(5)
    both = drift.truth(base, "bq15+line5", 5, 0)
    one, line = drift.truth(base, "bq15", 5, 0), drift.truth(base, "line5", 5, 0)
    assert both == drift.Truth("local", one.qubits | line.qubits, "all")
    assert drift.truth(base, "bq30+meas3", 5, 0).scope == "global"
    assert drift.truth(base, "br5+line5", 5, 0).mechanism == "readout"
    hot = {t for n, p, t in _noise_groups(drift.apply(base, "bq15+line5", 5, 0)) if p > 0.004}
    assert any(set(t) & one.qubits for t in hot) and any(set(t) & line.qubits for t in hot)
    assert drift.parts("") == [] and drift.parts("bq15+line5") == ["bq15", "line5"]
    with pytest.raises(ValueError):
        drift.parts("bq15+zz")


def test_the_drift_gap_isolates_the_stale_fit_and_gates_the_pass():
    refs = {"nominal": 0.010, "true_corr": 0.004, "stale_corr": 0.006}
    assert dt.gap_drift(0.006, refs) == pytest.approx(0.0)
    assert dt.gap_drift(0.004, refs) == pytest.approx(1.0)
    assert dt.gap_drift(0.005, refs) == pytest.approx(0.5)
    assert dt.gap_drift(0.005, {"nominal": 0.01, "true_corr": 0.004}) != 0  # NaN without drift
    assert aw.passed(True, 0.9, 0.5) and not aw.passed(True, 0.9, 0.49)
    assert aw.passed(True, 0.9, float("nan")) and not aw.passed(True, 0.4, 1.0)


def test_processes_sample_in_time_order_with_a_regime_per_shot():
    base = noise.nominal(3)
    tls = drift.process(base, "tls15", 3, 0)
    assert not tls.stationary and tls.dwell == drift.DWELL and len(tls.circuits) == 2
    det, obs, regime = dt.sample_process(tls, 4000, 5)
    assert det.shape == (4000, base.num_detectors) and obs.shape == (4000, 1)
    assert 0.3 < regime.mean() < 0.7
    switches = int(np.sum(regime[1:] != regime[:-1]))
    assert 5 < switches < 60  # stretches of about DWELL shots, not a shuffle
    wander = drift.process(base, "wander15", 3, 0)
    assert len(wander.circuits) == drift.WANDER + 1 and wander.dwell == drift.DWELL
    _, _, regime = dt.sample_process(wander, 6000, 5)
    assert len(set(regime.tolist())) > 4 and 0.3 < np.mean(regime == 0) < 0.7
    change = regime[:-1] != regime[1:]
    assert np.all(regime[1:][change] * regime[:-1][change] == 0)  # base between bad stretches
    other = drift.process(base, "wander15", 3, 0, split="deploy")
    assert [str(c) for c in other.circuits] != [str(c) for c in wander.circuits]
    assert drift.process(base, "bq15", 3, 0).stationary
    with pytest.raises(ValueError):
        drift.apply(base, "tls15", 3, 0)
    with pytest.raises(ValueError):
        drift.parts("tls15+wander15")
    assert drift.parts("tls15+bq15") == ["tls15", "bq15"]  # one moving part may join static ones


def test_nonstationary_truth_and_the_stationary_flag_in_the_diagnosis():
    base = noise.nominal(3)
    t = drift.truth(base, "tls15", 3, 0)
    assert t.scope == "local" and len(t.qubits) == 1 and not t.stationary
    moving = drift.truth(base, "wander15", 3, 0)
    assert moving.scope == "moving" and len(moving.qubits) == drift.WANDER
    assert moving.mechanism == "all" and not moving.stationary
    assert drift.truth(base, "bq15", 3, 0).stationary is True
    say = lambda flag: aw.report_from(  # noqa: E731
        {
            "model_adequate": False,
            "scope": "local",
            "changed_qubits": sorted(t.qubits),
            "mechanism": "all",
            "stationary": flag,
        }  # fmt: skip
    )
    assert aw.diagnosis(say(False), t)["diagnosis_correct"]
    assert not aw.diagnosis(say(True), t)["diagnosis_correct"]
    assert aw.report_from({})["report_stationary"] is True
    assert not aw.diagnosis(aw.report_from({"scope": "local"}), t)["diagnosis_correct"]
    assert aw.diagnosis(aw.report_from({}), drift.NO_DRIFT)["diagnosis_correct"]


def test_references_of_a_telegraph_task_hold_the_oracle_and_the_window_method(small):
    task = dt.Task(5, "none", "tls30")
    assert not task.stationary and "stationary" in dr.prompt(True)
    det, obs, regime = dt.test_sample(task)
    refs = dt.task_references(task, det, obs, regime)
    assert {"true_corr", "stale_corr", "window_corr", "pij_corr"} <= set(refs)
    assert refs["true_corr"] <= refs["stale_corr"] * 1.2  # 20,000 shots: noise, not a gap
    with pytest.raises(ValueError):
        dt.task_references(task, det, obs)


def test_the_nonstationary_set_is_named_and_mixed():
    tasks = dt.nonstationary_tasks()
    names = [t.name for t in tasks]
    assert len(names) == len(set(names)) == 22 and sum(t.model_adequate for t in tasks) == 3
    assert sum(not t.stationary for t in tasks) == 19
    assert dt.tasks_by_name("d5-none-dwander50-s2, d7-none-dtls30")[1].d == 7


def test_dwell_suffix_patches_and_compound_processes():
    base = noise.nominal(5)
    assert drift.parse("wander30d60") == ("wander", 30.0) and drift.dwell_of("wander30d60") == 60
    assert drift.dwell_of("wander30") == drift.DWELL and drift.dwell_of("bq15") == drift.DWELL
    with pytest.raises(ValueError):
        drift.parse("bq15d60")
    with pytest.raises(ValueError):
        drift.parts("tls30+wander30")
    fast = drift.process(base, "wander30d60", 5, 0)
    assert fast.dwell == 60 and len(fast.circuits) == drift.WANDER + 1
    patch = drift.process(base, "patch30", 5, 0)
    assert all(3 <= len(q) <= 9 for q in patch.qubits[1:])
    assert all(len(drift.disk(base, q)) >= 3 for q in noise.coordinates(base))
    both = drift.process(base, "bq15+wander30", 5, 0)
    static = drift.truth(base, "bq15", 5, 0).qubits
    assert both.qubits[0] == static and len(both.circuits) == drift.WANDER + 1
    hot = {t for n, p, t in _noise_groups(both.circuits[0]) if p > 0.004}
    assert hot and all(set(t) & static for t in hot)  # the base carries the static fault


def test_moving_truth_is_the_qubits_bad_in_the_deploy_batch():
    base = noise.nominal(5)
    full = drift.truth(base, "wander30", 5, 0)
    assert full.scope == "moving" and len(full.qubits) == drift.WANDER and not full.stationary
    part = drift.truth(base, "wander30", 5, 0, present={0, 1, 2})
    assert len(part.qubits) == 2 and part.qubits < full.qubits
    task = dt.Task(5, "none", "wander30", deploy=1000)
    assert task.truth.scope == "moving" and 1 <= len(task.truth.qubits) <= drift.WANDER
    both = drift.truth(base, "bq15+meas2+wander30", 5, 0)
    assert both.scope == "moving" and both.mechanism == "all" and not both.stationary
    say = aw.report_from(
        {
            "model_adequate": False,
            "scope": "moving",
            "changed_qubits": sorted(full.qubits)[:7],
            "mechanism": "all",
            "stationary": False,
        }  # fmt: skip
    )
    assert aw.diagnosis(say, full)["diagnosis_correct"]
    say["report_qubits"] = sorted(full.qubits)[:3]
    assert not aw.diagnosis(say, full)["diagnosis_correct"]
    say["report_qubits"] = sorted(full.qubits)[:7]
    say["report_scope"] = "local"  # the right qubits and "not stationary" name a moving fault
    assert aw.diagnosis(say, full)["diagnosis_correct"]
    say["report_stationary"] = True
    assert not aw.diagnosis(say, full)["diagnosis_correct"]


def test_launch_set_is_moving_faults_and_negatives():
    tasks = dt.launch_tasks()
    names = [t.name for t in tasks]
    assert len(names) == len(set(names)) == 21 and sum(t.model_adequate for t in tasks) == 3
    assert all(t.model_adequate or not t.stationary for t in tasks)
    assert "d5-none-dbq15+meas2+wander30" in names and "d5-none-dwander30-s1-n5000" in names


def test_new_families_keep_the_old_draws_and_add_gate_and_ramp_processes():
    base = noise.nominal(5)
    # Draws recorded before the gwander and ramp families existed: the v1 tasks must not move.
    assert sorted(drift.local_target("bq", base, 5, 0)) == [47]
    assert sorted(drift.local_target("tls", base, 5, 1)) == [5]
    assert sorted(drift.local_target("bg", base, 5, 0)) == [38, 39]
    deploy = [sorted(q) for _, q in drift.hot_regimes(base, "wander30", 5, 0, "deploy")]
    assert deploy[:4] == [[47], [26], [17], [31]]
    gw = drift.process(base, "gwander60", 5, 0)
    assert len(gw.circuits) == drift.WANDER + 1 and gw.order == "telegraph"
    assert gw.dwell == drift.DWELL and len(set(gw.qubits[1:])) == drift.WANDER
    pairs = {frozenset(p) for p in noise.cx_pairs(base)}
    assert all(q in pairs for q in gw.qubits[1:])
    hot = [(n, t) for n, p, t in _noise_groups(gw.circuits[1]) if p > 0.004]
    assert hot and all(n == "DEPOLARIZE2" and frozenset(t) == gw.qubits[1] for n, t in hot)
    truth = drift.truth(base, "gwander60", 5, 0)
    assert truth.scope == "moving" and truth.mechanism == "gate" and not truth.stationary
    ramp = drift.process(base, "ramp30", 5, 0)
    assert ramp.order == "ramp" and ramp.dwell is None
    assert len(ramp.circuits) == drift.RAMP_STEPS + 1 and len(set(ramp.qubits[1:])) == 1
    regime = dt.regime_sequence(ramp, 900, 3)
    assert regime[0] == 0 and regime[-1] == drift.RAMP_STEPS and np.all(np.diff(regime) >= 0)
    assert np.bincount(regime).tolist() == [100] * (drift.RAMP_STEPS + 1)
    bad = ramp.qubits[1]
    levels = [max(p for n, p, t in _noise_groups(c) if set(t) & bad) for c in ramp.circuits]
    assert levels == sorted(levels) and levels[-1] > 10 * levels[0]
    truth = drift.truth(base, "ramp30", 5, 0)
    assert truth.scope == "local" and truth.mechanism == "all" and not truth.stationary
    assert truth.qubits == bad and dt.Task(5, "none", "ramp30", 0, deploy=900).truth == truth
    assert drift.truth(base, "bg40+gwander60", 5, 0).mechanism == "gate"
    with pytest.raises(ValueError):
        drift.parts("ramp30+gwander60")


def test_launch2_pool_is_one_task_per_scenario_with_negatives():
    tasks = dt.launch2_tasks()
    names = [t.name for t in tasks]
    assert len(names) == len(set(names)) and sum(t.model_adequate for t in tasks) == 4
    assert all(t.model_adequate or not t.stationary for t in tasks)
    scenarios = [(t.d, t.scenario, t.drift, t.deploy) for t in tasks if t.drift]
    assert len(scenarios) == len(set(scenarios))  # no two drift tasks differ only in the seed
    families = {drift.parse(part)[0] for t in tasks for part in drift.parts(t.drift)}
    assert {"tls", "ramp", "wander", "patch", "gwander", "bq", "bg"} <= families
    assert {t.d for t in tasks} == {5, 7, 9} and any(t.scenario == "hetero" for t in tasks)
    assert dt.tasks_by_name("d9-none-dpatch30,d5-none-dramp40-s2-n5000")[1].deploy == 5000
    more = [t.name for t in dt.launch2b_tasks()]
    assert len(more) == 8 and not set(more) & set(names) and "d7-none-dgwander100" in more
    core = [t.name for t in dt.launch2core_tasks()]
    assert len(core) == 23 and len(set(core)) == 23
    assert sum(t.stationary and not t.model_adequate for t in dt.launch2core_tasks()) == 2
    assert sum(t.model_adequate for t in dt.launch2core_tasks()) == 2


def test_task_references_prefer_the_cached_table(tmp_path, monkeypatch):
    monkeypatch.setattr(dt, "_REFERENCES", {})
    path = tmp_path / "references.json"
    path.write_text(json.dumps({"d5-none-s5": {"nominal": 1.0, "true_corr": 0.5}}))
    assert dt.load_references(path) == 1
    assert dt.task_references(dt.Task(5, "none", "", 5), None, None) == {
        "nominal": 1.0,
        "true_corr": 0.5,
    }


def test_the_honest_adaptive_decoder_also_tries_single_gates():
    from qec_drift.decoders import adaptive

    stale = noise.nominal(3)
    a = adaptive.Adaptive(stale, 0)
    kinds = {kind for _, _, kind in a.hypotheses}
    assert kinds == {"all", "gate"}
    gate = next(h for h, (_, _, kind) in enumerate(a.hypotheses) if kind == "gate")
    assert a.matcher((gate,)).num_detectors == stale.num_detectors
