from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "legitimacy.py"
SPEC = importlib.util.spec_from_file_location("legitimacy", SCRIPT)
leg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(leg)


def test_core_expansion_reports_missing_detector_checks_until_regenerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, added, adequate = leg.dt.LAUNCH2_CORE[2], leg.dt.LAUNCH2_CORE[-1], leg.dt.LAUNCH2_CORE[0]
    assert not leg.dt.tasks_by_name(old)[0].model_adequate
    assert not leg.dt.tasks_by_name(added)[0].model_adequate
    assert leg.dt.tasks_by_name(adequate)[0].model_adequate
    record = dict(
        scope="local", truth=[1], found=[1], jaccard=1.0, ideal_jaccard=1.0, short_lived=0
    )
    cache = {old: record, "obsolete": record}
    eps = pd.DataFrame(
        [
            dict(
                arm="test",
                task=old,
                label="passed",
                diagnosis_correct=True,
                harness="",
                integrity="",
                anomalies="",
            )
        ]
    )
    monkeypatch.setattr(leg.dt, "LAUNCH2_CORE", (old, adequate))
    assert "Detector checks cover 1 of 1 non-adequate core tasks." in leg.report(eps, cache)

    monkeypatch.setattr(leg.dt, "LAUNCH2_CORE", (old, added, adequate))
    stale = leg.report(eps, cache)
    assert "Detector checks cover 1 of 2 non-adequate core tasks." in stale
    assert f"Missing checks: `{added}`" in stale
    assert "scripts/legitimacy.py --detector" in stale

    monkeypatch.setattr(leg, "DATA", tmp_path)
    (tmp_path / "detector.json").write_text(json.dumps(cache))
    calls = []

    def detector(task: leg.dt.Task) -> dict:
        calls.append(task.name)
        return dict(record)

    monkeypatch.setattr(leg, "detector", detector)
    monkeypatch.setattr(leg, "ideal", lambda _: dict(ideal_jaccard=1.0, short_lived=0))
    refreshed = leg.detector_table(list(leg.dt.LAUNCH2_CORE))
    assert calls == [added]
    rendered = leg.report(eps, refreshed)
    assert "Detector checks cover 2 of 2 non-adequate core tasks." in rendered
    assert "Missing checks:" not in rendered


def test_missing_detector_cache_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    task = leg.dt.LAUNCH2_CORE[2]
    monkeypatch.setattr(leg.dt, "LAUNCH2_CORE", (task,))
    eps = pd.DataFrame(
        [
            dict(
                arm="test",
                task=task,
                label="passed",
                diagnosis_correct=True,
                harness="",
                integrity="",
                anomalies="",
            )
        ]
    )
    report = leg.report(eps, {})
    assert "Detector checks cover 0 of 1 non-adequate core tasks." in report
    assert f"Missing checks: `{task}`" in report
