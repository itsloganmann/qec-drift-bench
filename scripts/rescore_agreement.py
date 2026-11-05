"""Add the behavioural columns (agreement with the nominal decoders) to a finished run.

Reruns each stored decoder on the task's test shots in the sandbox, the way the harness scored
it, and writes `agree_nominal_plain` and `agree_nominal_corr` back into the parquet. The
logical error rate is recomputed and must match the recorded one.

Usage: uv run python scripts/rescore_agreement.py data/agent_hard/sonnet_5_5_high.parquet
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from qec_drift.agent import decoder_run as dr
from qec_drift.agent import decoder_task as dt


def main(parquet: Path) -> None:
    df = pd.read_parquet(parquet)
    arm = str(df["arm"].iloc[0])
    work = parquet.parent / "work" / arm
    plain_col, corr_col = [], []
    for _, row in df.iterrows():
        task = dt.tasks_by_name(str(row["task"]))[0]
        test_det, test_obs = dt.test_shots(task)
        err, pred = dr.score_submission(work / task.name, task, test_det)
        if pred is None:
            print(task.name, "no prediction:", err[:80], flush=True)
            plain_col.append(float("nan"))
            corr_col.append(float("nan"))
            continue
        l_agent = dt.logical_error_rate(pred, test_obs)
        plain, corr = dt.nominal_predictions(task.d, test_det)
        a = float(np.mean(pred.reshape(-1) == np.asarray(plain, bool).reshape(-1)))
        b = float(np.mean(pred.reshape(-1) == np.asarray(corr, bool).reshape(-1)))
        same = abs(l_agent - float(row["l_agent"])) < 1e-9
        print(f"{task.name:26s} agree plain {a:.4f} corr {b:.4f} L {l_agent:.5f}"
              f"{'' if same else '  (differs from the recorded ' + str(row['l_agent']) + ')'}",
              flush=True)  # fmt: skip
        plain_col.append(a)
        corr_col.append(b)
    df["agree_nominal_plain"] = plain_col
    df["agree_nominal_corr"] = corr_col
    df.to_parquet(parquet)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        main(Path(arg))
