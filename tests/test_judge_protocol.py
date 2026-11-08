from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "judge_transcripts.py"
SPEC = importlib.util.spec_from_file_location("judge_transcripts", SCRIPT)
judge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(judge)


def record(scaffold: str = "codex") -> tuple[str, dict]:
    model = "gpt-5.6-luna" if scaffold == "codex" else "claude-opus-5-5"
    arm = "gpt_5_6_luna_high_codex" if scaffold == "codex" else "opus_5_5_max_cc"
    work = f"/repo/work/{arm}/ep-random"
    command = f"cat {work}/nominal.stim /outside/private.txt; echo {model}"
    output = f"{work}/nominal.stim: ok; /outside/private.txt: Permission denied ({arm})"
    if scaffold == "codex":
        events = [
            dict(
                type="item.completed",
                item=dict(
                    type="command_execution", command=command, aggregated_output=output, exit_code=0
                ),
            )
        ]
    else:
        events = [
            dict(
                type="assistant",
                message=dict(
                    content=[dict(type="tool_use", name="Bash", input=dict(command=command))]
                ),
            ),
            dict(type="user", message=dict(content=[dict(type="tool_result", content=output)])),
        ]
    return arm, dict(
        task="task-a",
        model=model,
        effort="high",
        scaffold=scaffold,
        trace_kind="codex_stream" if scaffold == "codex" else "claude_stream",
        workdir=work,
        events=events,
        decoder_src=f"# {model} {arm}",
        report={"evidence": f"{model} {arm}"},
    )


@pytest.mark.parametrize("scaffold", ["codex", "claude"])
def test_masks_identifiers_everywhere_and_preserves_path_evidence(
    monkeypatch: pytest.MonkeyPatch, scaffold: str
) -> None:
    arm, rec = record(scaffold)
    before = copy.deepcopy(rec)
    monkeypatch.setattr(judge, "facts", lambda _: f"score error in /repo/work/{arm}/decoder.py")
    text = judge.payload(pd.Series({}), rec, arm)
    assert rec == before
    assert arm not in text and rec["model"] not in text
    assert "/repo/work/agent/ep-random/nominal.stim" in text
    assert "/outside/private.txt: Permission denied" in text
    assert "score error in /repo/work/agent/decoder.py" in text
    assert "## Decoder shipped" in text and "## Report" in text


def test_payload_key_changes_with_visible_event_or_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    arm, rec = record()
    monkeypatch.setattr(judge, "facts", lambda row: str(row["score"]))
    row = pd.Series(dict(score=0.2))
    original = judge.key(judge.payload(row, rec, arm))
    edited = copy.deepcopy(rec)
    edited["events"][0]["item"]["command"] += "; cat test.npz"
    assert len(edited["events"]) == len(rec["events"])
    assert judge.key(judge.payload(row, edited, arm)) != original
    assert judge.key(judge.payload(pd.Series(dict(score=0.3)), rec, arm)) != original


@pytest.mark.parametrize("setting", ["PROMPT", "SCHEMA", "MODEL", "EFFORT", "PROTOCOL"])
def test_key_covers_judge_configuration(monkeypatch: pytest.MonkeyPatch, setting: str) -> None:
    first = judge.key("same submitted input")
    value = {"new": True} if setting == "SCHEMA" else "changed"
    monkeypatch.setattr(judge, setting, value)
    assert judge.key("same submitted input") != first


def test_cache_identity_includes_task_and_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    work = [("arm", "task-a", "same", "payload-a"), ("arm", "task-b", "same", "payload-b")]
    monkeypatch.setattr(judge, "episodes", lambda: work)
    done = [dict(arm="arm", task="task-a", key="same", protocol=judge.PROTOCOL)]
    monkeypatch.setattr(judge, "judged", lambda: done)
    assert judge.pending() == [work[1]]
    done[0].pop("protocol")
    assert judge.pending() == work


def test_pending_and_run_use_latest_archive_and_exact_task_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gzip
    import json

    data, trajectories = tmp_path / "data", tmp_path / "trajectories"
    data.mkdir()
    (trajectories / data.name).mkdir(parents=True)
    arm, first = record()
    last = copy.deepcopy(first)
    last["events"][0]["item"]["command"] = "echo latest-attempt"
    other = dict(last, task="task-b")
    invalid = dict(last, task="invalid")
    archive = trajectories / data.name / f"decoder_{arm}.jsonl.gz"
    archive.write_bytes(
        b"".join(
            gzip.compress((json.dumps(r) + "\n").encode()) for r in [first, last, other, invalid]
        )
    )
    pd.DataFrame([dict(task=r["task"]) for r in [last, other, invalid]]).to_parquet(
        data / f"{arm}.parquet"
    )
    pd.DataFrame(
        [
            dict(task=r["task"], label="invalid_run" if r is invalid else "passed")
            for r in [last, other, invalid]
        ]
    ).to_parquet(data / f"{arm}_taxonomy.parquet")
    monkeypatch.setattr(judge, "DATA", data)
    monkeypatch.setattr(judge, "OUT", data / "judge")
    monkeypatch.setattr(judge.paths, "trajectories_dir", lambda: trajectories)
    monkeypatch.setattr(judge, "facts", lambda row: f"facts for {row['task']}")
    work = judge.pending()
    assert len(work) == 2
    assert len({item[2] for item in work}) == 2
    assert all("echo latest-attempt" in item[3] for item in work)
    seen = []

    def evaluate(text: str) -> dict:
        seen.append(text)
        return dict(label="passed")

    monkeypatch.setattr(judge, "judge_one", evaluate)
    judge.run(work[:1], concurrency=1)
    assert seen == [work[0][3]]
    assert judge.pending() == work[1:]
    stored = judge.judged()[0]
    assert stored["protocol"] == judge.PROTOCOL and stored["key"] == judge.key(seen[0])


def test_facts_reuses_task_truth_without_caching_row_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    calls = []

    def task(name: str) -> list:
        calls.append(name)
        truth = SimpleNamespace(scope="none", mechanism="none", stationary=True, qubits=set())
        return [SimpleNamespace(d=5, drift="", truth=truth)]

    judge.task_facts.cache_clear()
    monkeypatch.setattr(judge.dt, "tasks_by_name", task)
    row = pd.Series(dict(task="same-task", gap_closed=0.2))
    assert "gap_closed 0.2" in judge.facts(row)
    row["gap_closed"] = 0.4
    assert "gap_closed 0.4" in judge.facts(row)
    assert calls == ["same-task"]
    judge.task_facts.cache_clear()
