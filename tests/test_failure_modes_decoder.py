"""Decoder-family failure modes: one leaf per episode, fitted-model detection, the arm table."""

from __future__ import annotations

import gzip
import json
import re

import pandas as pd
import pytest

from qec_drift.agent import decoder_task as dt
from qec_drift.scoring import failure_modes_decoder as fm
from qec_drift.scoring.failure_modes_decoder import (
    DECODER_LEAVES,
    analyze_decoder,
    classify_decoder,
    is_fitted,
)


def _leaf(**kw) -> str:
    base = dict(has_decoder=True, scored=True, gap=0.5, fitted=False, correlated=False, ran=True)
    return classify_decoder(**(base | kw))[0]


@pytest.mark.parametrize(
    ("kw", "leaf"),
    [
        (dict(ran=False, has_decoder=False), "harness_error"),
        (dict(has_decoder=False), "no_decoder"),
        (dict(scored=False), "unscored"),
        (dict(gap=-0.1), "worse_than_plain"),
        (dict(), "nominal_plain"),
        (dict(correlated=True), "nominal_correlated"),
        (dict(fitted=True), "fitted_plain"),
        (dict(fitted=True, correlated=True), "fitted_correlated"),
    ],
)
def test_each_gate(kw, leaf):
    assert _leaf(**kw) == leaf


def test_every_input_lands_in_exactly_one_known_leaf():
    seen = set()
    for ran in (True, False):
        for has in (True, False):
            for scored in (True, False):
                for gap in (-1.0, 0.0, 0.9, float("nan")):
                    for fitted in (True, False):
                        for corr in (True, False):
                            leaf, gate = classify_decoder(
                                has_decoder=has,
                                scored=scored,
                                gap=gap,
                                fitted=fitted,
                                correlated=corr,
                                ran=ran,
                            )
                            assert leaf in DECODER_LEAVES and gate.startswith("D")
                            seen.add(leaf)
    assert seen == set(DECODER_LEAVES)


def test_fitted_detection_on_inlined_models_and_own_files():
    dem = str(dt.nominal(3).detector_error_model(decompose_errors=True))
    assert not is_fitted(f'_DEM = """{dem}"""\n', 3)
    perturbed = re.sub(
        r"error\(([0-9.eE+-]+)\)", lambda m: f"error({float(m.group(1)) * 1.5:.12g})", dem
    )
    assert is_fitted(f'_DEM = """{perturbed}"""\n', 3)
    assert not is_fitted("c = stim.Circuit(open('nominal.stim').read())\n", 3)
    assert is_fitted("w = np.load('pfit.npy')\n", 3)
    assert is_fitted("m = stim.DetectorErrorModel.from_file(os.path.join(_D, 'fitted.dem'))\n", 3)
    assert is_fitted("m = pymatching.Matching()\nm.add_edge(0, 1, weight=w)\n", 3)
    assert is_fitted("c = stim.Circuit()\nfor i in base: c.append(i)\n", 3)
    assert not is_fitted(
        "c = stim.Circuit.from_file('nominal.stim'); d = np.load('train.npz')\n", 3
    )
    own = "d2.append(stim.DemInstruction('error', [float(_P[k])], x.targets_copy()))\n"
    assert is_fitted(own, 3)


def test_analyze_decoder_writes_leaves_and_flags(tmp_path):
    work = tmp_path / "work" / "arm_x" / "d3-both"
    work.mkdir(parents=True)
    (work / "decoder.py").write_text("import pymatching\n")  # an old row with the source on disk
    rows = [
        dict(arm="arm_x", task="d3-both", d=3, outcome="no_submit", stop="turns", turns=24,
             gap_closed=float("nan"), decoder_src="", score_error="too big"),
        dict(arm="arm_x", task="d3-hetero", d=3, outcome="submitted", stop="submitted", turns=5,
             gap_closed=0.7, decoder_src="m = Matching(dem, enable_correlations=True)",
             score_error=""),
        dict(arm="arm_x", task="d3-none", d=3, outcome="error", stop="error", turns=0,
             gap_closed=float("nan"), decoder_src="", score_error="Throttled: gave up"),
        dict(arm="arm_x", task="d3-drift", d=3, outcome="submitted", stop="submitted", turns=9,
             gap_closed=0.8, gap_drift=0.55, diagnosis_correct=True, decoder_src="x = 1",
             score_error="", ref_stale_corr=0.01, ref_true_corr=0.005, ref_adaptive_corr=0.0055),
    ]  # fmt: skip
    parquet = tmp_path / "arm_x.parquet"
    pd.DataFrame(rows).to_parquet(parquet)
    traj = tmp_path / "decoder_arm_x.jsonl.gz"
    body = {"content": [{"type": "tool_use", "name": "run_python",
                         "input": {"code": "v = np.load('val.npz'); estimate = 1"}}]}  # fmt: skip
    with gzip.open(traj, "wt") as f:
        f.write(
            json.dumps({"task": "d3-hetero", "messages": [{"role": "assistant", "body": body}]})
        )
        f.write("\n")
    out = analyze_decoder(parquet, traj).set_index("task")
    assert out.loc["d3-both", "leaf"] == "unscored"
    assert out.loc["d3-hetero", "leaf"] == "nominal_correlated"
    assert out.loc["d3-none", "leaf"] == "harness_error" and out.loc["d3-none", "gate"] == "D0"
    assert out.loc["d3-both", "verdict"] == out.loc["d3-none", "verdict_rel"] == "no_score"
    assert out.loc["d3-hetero", "verdict"] == "passed"  # no diagnosis column: the fix decides
    # the drift row: the fix passes the absolute rule, not 0.75 of the honest 0.9 recovery
    assert out.loc["d3-drift", "verdict"] == "passed"
    assert out.loc["d3-drift", "verdict_rel"] == "missed_fix"
    assert out.loc["d3-hetero", "used_validation"] and out.loc["d3-hetero", "tried_fit"]
    assert out.loc["d3-both", "used_validation"] is None or pd.isna(
        out.loc["d3-both", "used_validation"]
    )
    assert (tmp_path / "arm_x_failure_modes.parquet").is_file()


def test_fitted_detection_on_edited_circuits_and_behaviour():
    circuit = "c = stim.Circuit('X_ERROR(0.003) 1 2\nX_ERROR(0.045) 12\nM 1')"
    assert fm.is_fitted(circuit, 5)
    assert not fm.is_fitted("c = stim.Circuit('X_ERROR(0.003) 1 2\nM 1')", 5)
    rewrite = "mm = re.match(r'(DEPOLARIZE1|DEPOLARIZE2|X_ERROR)\\(([\\d.e-]+)\\) (.*)', s)"
    assert fm.is_fitted(rewrite, 5)
    row = pd.Series({"agree_nominal_plain": 1.0, "agree_nominal_corr": 0.98, "decoder_src": ""})
    assert fm.by_behaviour(row) == (False, False)
    row = pd.Series({"agree_nominal_plain": 0.98, "agree_nominal_corr": 1.0, "decoder_src": ""})
    assert fm.by_behaviour(row) == (False, True)
    row = pd.Series({"agree_nominal_plain": 0.9, "agree_nominal_corr": 0.9,
                     "decoder_src": "m.decode_batch(det, enable_correlations=True)"})  # fmt: skip
    assert fm.by_behaviour(row) == (True, True)
    assert fm.by_behaviour(pd.Series({"agree_nominal_plain": float("nan")})) is None
    assert fm.by_behaviour(pd.Series({"gap_closed": 0.5})) is None


def test_fitted_detection_on_computed_models_and_own_modules():
    assert fm.is_fitted("m = stim.DetectorErrorModel(_DEM_NOM if k == 'n' else _DEM_DRIFT)", 5)
    assert fm.is_fitted("c = stim.Circuit('\\n'.join(out))", 5)
    assert not fm.is_fitted("c = stim.Circuit(open('nominal.stim').read())", 5)
    assert not fm.is_fitted("c = stim.Circuit.from_file(os.path.join(_HERE, 'nominal.stim'))", 5)
    assert fm.is_fitted("import numpy as np\nfrom mod import modify\n", 5)
    assert not fm.is_fitted("import numpy as np\nfrom scipy.sparse import csr_matrix\n", 5)
    nominal = sorted(fm.nominal_probabilities(5))
    assert not fm.is_fitted(f"stim.DetectorErrorModel('error({nominal[0]}) D0 D1')", 5)
    assert fm.is_fitted(f"stim.DetectorErrorModel('error({nominal[0]}) D0 D1 error(0.09) D2')", 5)
