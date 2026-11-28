"""The 75% selection rule and the legitimacy report for the data-out tasks, on made-up rows."""

from __future__ import annotations

import importlib.util

import pandas as pd

from qec_drift import paths


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, paths.REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sel = _script("select_tasks")
leg = _script("envs_legitimacy")
REFS = {"t": {"reference": {"pass_rate": 0.6, "score": 0.7}, "trivial": {}}}


def arm(tmp_path, name, model, rates, outcome="submitted"):
    df = pd.DataFrame(
        dict(env="t", model=model, rollout=range(len(rates)), outcome=outcome, pass_rate=rates,
             score=rates)
    )  # fmt: skip
    path = tmp_path / f"{name}.parquet"
    df.to_parquet(path)
    return path


def test_the_best_model_decides_and_rollouts_are_averaged(tmp_path):
    rates = sel.model_rates(
        [arm(tmp_path, "a", "big", [0.9, 0.7, 0.5]), arm(tmp_path, "b", "small", [0.8, 0.8])]
    )
    assert dict(zip(rates.model, rates.pass_rate.round(3), strict=True)) == {
        "big": 0.7,
        "small": 0.8,
    }
    d = sel.decide("t", rates, REFS, 0.75)
    assert (d["status"], d["best"]) == ("excluded", "small")
    assert sel.decide("t", rates, REFS, 0.85)["status"] == "included"


def test_error_rows_do_not_count_and_a_task_without_runs_is_pending(tmp_path):
    rates = sel.model_rates([arm(tmp_path, "a", "big", [1.0, 1.0], outcome="error")])
    assert rates.empty
    assert sel.decide("t", rates, REFS, 0.75)["status"] == "pending"
    assert sel.decide("t", rates, REFS, 0.5)["status"] == "excluded"  # reference above the bar


def test_the_selection_table_names_every_model(tmp_path):
    rates = sel.model_rates([arm(tmp_path, "a", "big", [0.5])])
    text = sel.markdown([sel.decide("t", rates, REFS, 0.75)], rates, REFS, 0.75)
    assert "| t | included | 0.60 / 0.70 | 0.50 / 0.50 |" in text


def test_a_failed_check_is_marked_in_the_report():
    rows = [
        dict(check="lazy_const.py", kind="lazy", why="w", score=0.6, bar=0.55, ok=False),
        dict(check="reference", kind="room", why="w", score=0.8, bar=0.55, ok=True),
    ]
    text = leg.markdown({"t": rows})
    assert "| lazy_const.py | lazy | 0.600 | 0.550 | FAIL | w |" in text
    assert "| reference | room | 0.800 | 0.550 | pass | w |" in text


def test_a_csv_arm_table_counts_like_a_parquet_one(tmp_path):
    path = tmp_path / "pilot.csv"
    pd.read_parquet(arm(tmp_path, "a", "big", [0.6, 0.7])).to_csv(path, index=False)
    rates = sel.model_rates([path])
    assert rates.pass_rate.round(3).tolist() == [0.65]
    assert sel.decide("t", rates, REFS, 0.75)["best_pass"] == 0.65
