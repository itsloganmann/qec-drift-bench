from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def tick(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    folder = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(folder))
    spec = importlib.util.spec_from_file_location(
        "test_judge_tick_script", folder / "judge_tick.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.judge, "DOC", tmp_path / "report.md")
    monkeypatch.setattr(module.judge, "report", lambda: "current coverage\n")
    if hasattr(module, "time"):
        monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    return module


def state(primary: object = "81", secondary: object = "0", status: int = 200) -> dict:
    return {
        "primary-used-percent": primary,
        "secondary-used-percent": secondary,
        "http-status": status,
    }


@pytest.mark.parametrize(
    "data",
    [
        state("85"),
        state("100"),
        state(secondary="85"),
        state(None),
        state(secondary=None),
        state("nan"),
        state("inf"),
        state("-1"),
        state(True),
        state("bad"),
        state(status=429),
        {},
        {"error": "TimeoutExpired"},
    ],
)
def test_unknown_or_exhausted_quota_skips_work_but_refreshes_report(
    tick: ModuleType, monkeypatch: pytest.MonkeyPatch, data: dict
) -> None:
    monkeypatch.setattr(tick.usage, "codex", lambda: data)
    monkeypatch.setattr(tick.judge, "pending", lambda: pytest.fail("must not prepare model work"))
    monkeypatch.setattr(tick.judge, "run", lambda *a, **k: pytest.fail("must not launch a judge"))
    tick.main()
    assert tick.judge.DOC.read_text() == "current coverage\n"


def test_each_pair_gets_a_fresh_quota_check_and_stops_at_reserve(
    tick: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads, batches = [], []
    values = iter(["81", "81", "83", "85"])

    def probe() -> dict:
        value = next(values)
        reads.append(value)
        return state(value)

    monkeypatch.setattr(tick.usage, "codex", probe)
    monkeypatch.setattr(tick.judge, "pending", lambda: list(range(12)))
    monkeypatch.setattr(
        tick.judge, "run", lambda work, concurrency: batches.append((work, concurrency))
    )
    tick.main()
    assert reads == ["81", "81", "83", "85"]
    assert batches == [([0, 1], 2), ([2, 3], 2)]
    assert tick.judge.DOC.read_text() == "current coverage\n"


def test_safe_quota_still_limits_tick_to_eight_reviews(
    tick: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, batches = [], []
    monkeypatch.setattr(tick.usage, "codex", lambda: calls.append(True) or state("0", "0"))
    monkeypatch.setattr(tick.judge, "pending", lambda: list(range(12)))
    monkeypatch.setattr(tick.judge, "run", lambda work, concurrency: batches.extend(work))
    tick.main()
    assert batches == list(range(8)) and len(calls) == 5


def test_quota_change_during_preparation_prevents_first_launch(
    tick: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = iter(["84", "85"])
    monkeypatch.setattr(tick.usage, "codex", lambda: state(next(values)))
    monkeypatch.setattr(tick.judge, "pending", lambda: ["episode"])
    monkeypatch.setattr(
        tick.judge, "run", lambda *a: pytest.fail("quota changed during preparation")
    )
    tick.main()
    assert tick.judge.DOC.read_text() == "current coverage\n"


def test_probe_failure_does_not_leak_exception_message(
    tick: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def fail() -> dict:
        raise OSError("private credential must not be printed")

    monkeypatch.setattr(tick.usage, "codex", fail)
    tick.main()
    assert "private credential" not in capsys.readouterr().out


def test_transient_read_failure_retries_before_authorizing_work(
    tick: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def probe() -> dict:
        calls.append(True)
        if len(calls) == 1:
            raise TimeoutError("private transport details")
        return state("82", "0")

    monkeypatch.setattr(tick.usage, "codex", probe)
    assert tick.quota_available() is True
    assert len(calls) == 2


def test_transient_failures_stop_after_three_reads(
    tick: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def probe() -> dict:
        calls.append(True)
        raise TimeoutError("private transport details")

    monkeypatch.setattr(tick.usage, "codex", probe)
    assert tick.quota_available() is False
    assert len(calls) == 3


def test_known_reserve_during_retry_stops_without_more_reads(
    tick: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = iter([{"error": "CalledProcessError"}, state("85")])
    monkeypatch.setattr(tick.usage, "codex", lambda: next(values))
    assert tick.quota_available() is False
    with pytest.raises(StopIteration):
        next(values)
