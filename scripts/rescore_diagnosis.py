"""Recompute the diagnosis and pass columns of finished runs from their stored reports.

Usage: uv run python scripts/rescore_diagnosis.py data/agent_launch/opus_5_5_medium_cc.parquet ...
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from qec_drift.agent import attempts
from qec_drift.agent import awareness as aw
from qec_drift.agent import decoder_task as dt

REPORT = ("report_adequate", "report_confidence", "report_scope", "report_qubits",
          "report_mechanism", "report_stationary")  # fmt: skip


def main(parquet: Path) -> None:
    df = pd.read_parquet(parquet)
    attempts.require_legacy(df)
    out = []
    for _, row in df.iterrows():
        task = dt.tasks_by_name(str(row["task"]))[0]
        report = {k: row[k] for k in REPORT if k in row}
        qubits = report.get("report_qubits")
        report["report_qubits"] = [int(q) for q in (qubits if qubits is not None else [])]
        verdict = aw.diagnosis(report, task.truth)
        verdict["passed"] = aw.passed(
            verdict["diagnosis_correct"], float(row["gap_closed"]), float(row["gap_drift"])
        )
        out.append(verdict)
    for key in out[0]:
        df[key] = [v[key] for v in out]
    attempts.write_table(parquet, df)
    print(f"{parquet.name}: passed {int(df.passed.sum())} of {len(df)}, "
          f"diagnosis {df.diagnosis_correct.mean():.0%}")  # fmt: skip


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        main(Path(arg))
