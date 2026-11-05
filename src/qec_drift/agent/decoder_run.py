"""Run one model as a decoder-building agent on the six tasks, and keep every trajectory.

The model gets two tools: `run_python(code)` (sandboxed, see agent/sandbox.py) and `submit()`.
The harness holds the test labels in memory; the test shots reach the sandbox only while the
submitted decoder is scored, and the labels never do.

Example:
    uv run python -m qec_drift.agent.decoder_run --model claude-opus-5-5 --effort medium \
        --arm opus_5_5_medium --max-usd 10
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qec_drift import paths
from qec_drift.agent import awareness as aw
from qec_drift.agent import decoder_task as dt
from qec_drift.agent import sandbox
from qec_drift.llm import pricing
from qec_drift.llm.anthropic_client import AnthropicClient, build_kwargs
from qec_drift.llm.types import Request
from qec_drift.scoring.failure_modes_decoder import analyze_decoder

MAX_TURNS = 40
EPISODE_USD = 4.0  # one episode stops once its estimated cost passes this
MAX_TOKENS = 16_000
RUN_TIMEOUT = 120
SCORE_TIMEOUT = 300
MAX_FAILED_SUBMITS = 3
MAX_NUDGES = 2
COUNTDOWN_FROM = 5  # tool results carry the calls left once this few remain
SYSTEM = "You are an expert in quantum error correction and numerical Python."
TOOLS = [
    {
        "name": "run_python",
        "description": "Run Python code in your work folder (numpy, scipy, stim, pymatching, "
        "torch; no network; 120 s limit). Each call starts a new Python process, so keep state "
        "in files; files you write there persist. Returns the output.",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "submit",
        "description": "Submit decoder.py for scoring on held-out shots. Ends the task on success.",
        "input_schema": {"type": "object", "properties": {}},
    },
]
REPORT_FIELDS = aw.REPORT_FIELDS
AWARENESS_PROMPT = aw.PROMPT
TEXT_LIMIT = aw.TEXT_LIMIT
report_from = aw.report_from
awareness_brier = aw.brier


def tools(awareness: bool) -> list[dict]:
    """The tool list; with awareness the submit call also carries the model assessment."""
    if not awareness:
        return TOOLS
    submit = TOOLS[1] | {"input_schema": {"type": "object", "properties": REPORT_FIELDS}}
    return [TOOLS[0], submit]


SCORER = """\
import importlib.util, sys
import numpy as np
spec = importlib.util.spec_from_file_location("decoder", "decoder.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
det = np.load(sys.argv[1])["det"]
np.save(sys.argv[2], np.asarray(mod.decode(det), dtype=bool).reshape(det.shape[0], -1))
"""


def prompt(awareness: bool = False) -> str:
    return _prompt() + (AWARENESS_PROMPT if awareness else "")


def _prompt() -> str:
    return (
        "A team runs a rotated surface-code memory experiment on real hardware and decodes it "
        "with minimum-weight perfect matching built from the circuit that they believe describes "
        "the hardware. The real noise may differ from that circuit in ways that nobody has "
        "characterized.\n\n"
        "Your work folder holds:\n"
        "- nominal.stim: the circuit that the team believes (Stim format, with detectors and "
        "one logical observable)\n"
        "- train.npz and val.npz: arrays `det` (shots by detectors, bool) and `obs` (shots by 1, "
        "bool), measured on the real hardware during calibration\n"
        "- deploy.npz: array `det` only, the most recent shots from the hardware, with no logical "
        "labels (the team could not run the calibration circuit again)\n\n"
        "Shots in every file, and the shots your decoder is scored on, are in the order they "
        "were taken.\n\n"
        "Write decoder.py that defines `decode(det)`, which takes a bool array of detection "
        "events (shots by detectors) and returns the predicted logical flips (bool, one per "
        "shot). The team scores it on held-out shots from the same hardware. A lower logical "
        "error rate is better. Decoding 300,000 shots must take under 300 s.\n\n"
        "Use run_python to work and submit when decoder.py is ready. You have at most "
        f"{MAX_TURNS} tool calls in all. When they run out, whatever decoder.py exists is scored "
        "as it is, and no decoder.py scores as a failure."
    )


def _blocks(msg: Any) -> list[dict]:
    return [b.model_dump(mode="json", exclude_none=True) for b in msg.content]


DECODER_LIMIT = 5_000_000  # a fitted d = 7 model inlined as text is about 300 KB


def read_regular_file(path: Path, limit: int = DECODER_LIMIT) -> str:
    """The text of a regular file inside the agent folder, or "" for a link or anything else.

    The agent's code can leave a link where the harness expects a file, so the harness never
    follows one.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return ""
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return ""
        return os.read(fd, limit).decode("utf-8", errors="replace")
    finally:
        os.close(fd)


def decoder_problem(workdir: Path, limit: int = DECODER_LIMIT) -> str:
    """Why decoder.py cannot be scored, or "" when it can. Never follows a link."""
    try:
        info = os.lstat(workdir / "decoder.py")
    except OSError:
        return "decoder.py is missing"
    if not stat.S_ISREG(info.st_mode):
        return "decoder.py is not a regular file"
    if info.st_size == 0:
        return "decoder.py is empty"
    if info.st_size > limit:
        return f"decoder.py is {info.st_size} bytes; the limit is {limit}"
    return ""


def decoder_size(workdir: Path) -> int:
    try:
        info = os.lstat(workdir / "decoder.py")
    except OSError:
        return 0
    return info.st_size if stat.S_ISREG(info.st_mode) else 0


def has_decoder(workdir: Path) -> bool:
    return not decoder_problem(workdir)


COPY_LIMIT = 500_000_000  # bytes per file copied into the scoring folder
PRED_LIMIT = 200_000_000  # bytes of predictions the harness will read


def copy_regular_tree(src: Path, dst: Path, limit: int = COPY_LIMIT) -> None:
    """Copy the regular files and folders under `src`; links and special files are skipped."""
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src, followlinks=False):
        rel = Path(root).relative_to(src)
        dirs[:] = [d for d in dirs if stat.S_ISDIR(os.lstat(Path(root) / d).st_mode)]
        for d in dirs:
            (dst / rel / d).mkdir(exist_ok=True)
        for name in files:
            path = Path(root) / name
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            except OSError:
                continue
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                    continue
                with os.fdopen(fd, "rb") as f, open(dst / rel / name, "wb") as g:
                    shutil.copyfileobj(f, g)
                fd = -1
            finally:
                if fd >= 0:
                    os.close(fd)


def load_regular_npy(path: Path, limit: int = PRED_LIMIT) -> np.ndarray | None:
    """np.load of a regular file only (never a link), or None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return None
        with os.fdopen(fd, "rb") as f:
            return np.load(f, allow_pickle=False)
    except Exception:
        return None


def score_submission(
    workdir: Path, task: dt.Task, test_det: np.ndarray
) -> tuple[str, np.ndarray | None]:
    """Run the submitted decoder on the test shots inside the sandbox.

    The decoder runs in a throwaway copy of the agent folder, and the test shots and the
    predictions live next to that copy in a folder that the harness makes now. Nothing is
    written into the agent folder, so a decoder that fails cannot leave the test shots behind
    for the agent's next turn.
    """
    problem = decoder_problem(workdir)
    if problem:
        return problem, None
    scratch = Path(tempfile.mkdtemp(prefix="score-")).resolve()
    try:
        work, test, pred_path = scratch / "work", scratch / "test.npz", scratch / "pred.npy"
        copy_regular_tree(workdir, work)
        np.savez_compressed(test, det=test_det)
        code, out = sandbox.run(
            ["-", str(test), str(pred_path)],
            work,
            SCORE_TIMEOUT,
            stdin=SCORER,
            read=[scratch],
            write=[scratch],
        )
        pred = load_regular_npy(pred_path) if code == 0 else None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if code != 0:
        return out, None
    if pred is None:
        return "decode produced no readable predictions file", None
    n = test_det.shape[0]
    if pred.ndim == 0 or pred.shape[0] != n or pred.size != n:
        return f"decode returned shape {pred.shape} for {n} shots with one observable", None
    return "", pred.reshape(n, 1).astype(bool)


def run_episode(
    client: Any,
    task: dt.Task,
    model: str,
    effort: str | None,
    root: Path,
    max_usd: float = EPISODE_USD,
    awareness: bool = False,
) -> tuple[dict, dict]:
    """One agent conversation. Returns the score row and the full trajectory.

    The episode ends on a scored submit, on the third failed submit, when the model stops
    calling tools (after at most two reminders), at MAX_TURNS, or once its estimated cost passes
    `max_usd`. On every exit without a scored submit the harness scores whatever decoder.py
    exists and records why when it cannot.
    """
    workdir = (root / task.name).resolve()
    shutil.rmtree(workdir, ignore_errors=True)
    dt.write_agent_files(task, workdir)
    test_det, test_obs, regime = dt.test_sample(task)
    refs = dt.task_references(task, test_det, test_obs, regime)
    text0, tool_list = prompt(awareness), tools(awareness)
    base = build_kwargs(
        Request(SYSTEM, text0, model, 0.0, MAX_TOKENS, effort, {"thinking": "summarized"})
    )
    messages: list[dict] = [{"role": "user", "content": text0}]
    trace: list[dict] = [{"role": "user", "content": text0}]
    report: dict | None = None  # the assessment from the last submit that carried one
    tokens_in = tokens_out = failed = nudges = n_run = n_timeouts = 0
    outcome, l_agent, turns, cost, stop, err = "no_submit", float("nan"), 0, 0.0, "turns", ""
    for turn in range(1, MAX_TURNS + 1):
        turns = turn
        started = time.monotonic()
        msg, body, request_id = client._create_with_body(
            base | {"messages": messages, "tools": tool_list}
        )
        tokens_in += int(msg.usage.input_tokens or 0)
        tokens_out += int(msg.usage.output_tokens or 0)
        cost = pricing.estimate_usd("anthropic", model, tokens_in, tokens_out) or 0.0
        trace.append({"role": "assistant", "body": body, "request_id": request_id,
                      "latency_s": round(time.monotonic() - started, 2)})  # fmt: skip
        messages.append({"role": "assistant", "content": list(msg.content)})
        calls = [b for b in msg.content if b.type == "tool_use"]
        if not calls:
            if nudges < MAX_NUDGES and has_decoder(workdir):
                nudges += 1  # the model stopped without submitting: remind it, at most twice
                reminder = "decoder.py is in the work folder. Call submit when you want it scored."
                messages.append({"role": "user", "content": reminder})
                trace.append({"role": "user", "content": reminder})
                continue
            stop = "ended_turn"
            break
        results, done = [], False
        for call in calls:
            if call.name == "run_python":
                n_run += 1
                code, out = sandbox.run(
                    ["-"], workdir, RUN_TIMEOUT, stdin=call.input.get("code", "")
                )
                n_timeouts += code == 124
                text = f"exit code {code}\n{out}"
            elif call.name == "submit":
                given = dict(call.input or {})
                if report is None or any(k in given for k in REPORT_FIELDS):
                    report = report_from(given)
                err, pred = score_submission(workdir, task, test_det)
                if pred is not None:
                    l_agent, outcome, done = (
                        dt.logical_error_rate(pred, test_obs),
                        "submitted",
                        True,
                    )
                    text, stop = "Submitted. The task is finished.", "submitted"
                else:
                    failed += 1
                    text = f"Submission failed: {err}"
                    done = failed >= MAX_FAILED_SUBMITS
                    if done:
                        outcome = stop = "failed_submit"
            else:
                text = f"unknown tool {call.name}"
            left = MAX_TURNS - turn
            if left <= COUNTDOWN_FROM and not done:
                text += f"\n[{left} tool call{'s' if left != 1 else ''} left before the task ends]"
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": text})
        messages.append({"role": "user", "content": results})
        trace.append({"role": "tool", "content": results})
        if done:
            break
        if cost >= max_usd:
            stop = "episode_budget"
            break
    if outcome == "no_submit":  # out of turns, budget or words: score what exists
        err, pred = score_submission(workdir, task, test_det)
        if pred is not None:
            l_agent, outcome = dt.logical_error_rate(pred, test_obs), "auto_scored"
    src = read_regular_file(workdir / "decoder.py")
    scored = l_agent == l_agent
    agree_plain = agree_corr = float("nan")
    if pred is not None:  # how much of the decoder is the nominal one, by behaviour
        plain, corr = dt.nominal_predictions(task.d, test_det)
        agree_plain = float(np.mean(pred.reshape(-1) == np.asarray(plain, bool).reshape(-1)))
        agree_corr = float(np.mean(pred.reshape(-1) == np.asarray(corr, bool).reshape(-1)))
    brier, verdict = None, {}
    if awareness:  # no submit call means no assessment: the Brier is undefined, not perfect
        brier = awareness_brier(report, task.model_adequate) if report else float("nan")
        verdict = aw.diagnosis(report or report_from({}), task.truth)
        gap = dt.gap_closed(l_agent, refs) if scored else float("nan")
        drift_gap = dt.gap_drift(l_agent, refs) if scored else float("nan")
        verdict["passed"] = aw.passed(verdict["diagnosis_correct"], gap, drift_gap)
    row = dict(task=task.name, d=task.d, scenario=task.scenario, drift=task.drift, seed=task.seed,
               adequate_truth=task.model_adequate, reported=report is not None,
               awareness_brier=brier, outcome=outcome, stop=stop,
               turns=turns, n_run_python=n_run, n_timeouts=n_timeouts, tokens_in=tokens_in,
               tokens_out=tokens_out, l_agent=l_agent,
               gap_closed=dt.gap_closed(l_agent, refs) if scored else float("nan"),
               gap_drift=dt.gap_drift(l_agent, refs) if scored else float("nan"),
               cost_usd=cost, uses_correlations="enable_correlations" in src,
               agree_nominal_plain=agree_plain, agree_nominal_corr=agree_corr,
               auto_scored=outcome == "auto_scored", score_error="" if scored else err,
               decoder_bytes=decoder_size(workdir), decoder_src=src,
               ) | (report or report_from({})) | verdict | {
                   f"ref_{k}": v for k, v in refs.items()}  # fmt: skip
    trajectory = dict(task=task.name, model=model, effort=effort, system=SYSTEM, tools=tool_list,
                      trace_kind="api_returned", messages=trace, decoder_src=src)  # fmt: skip
    return row, trajectory


def safe_episode(client: Any, task: dt.Task, *args: Any) -> tuple[dict, dict]:
    """run_episode, with any exception turned into an error row so the run goes on."""
    try:
        return run_episode(client, task, *args)
    except Exception as exc:  # noqa: BLE001 - every failure must land in the table
        reason = f"{type(exc).__name__}: {exc}"[:500]
        row = dict(task=task.name, d=task.d, scenario=task.scenario, drift=task.drift,
                   seed=task.seed, adequate_truth=task.model_adequate, reported=False,
                   awareness_brier=float("nan"), outcome="error", stop="error", turns=0,
                   n_run_python=0, n_timeouts=0, tokens_in=0, tokens_out=0,
                   l_agent=float("nan"), gap_closed=float("nan"), cost_usd=0.0,
                   uses_correlations=False, agree_nominal_plain=float("nan"),
                   agree_nominal_corr=float("nan"), auto_scored=False, score_error=reason,
                   decoder_bytes=0, decoder_src="") | report_from({})  # fmt: skip
        return row, dict(task=task.name, error=reason, trace_kind="api_returned", messages=[])


def warm_up_stim() -> None:
    """Run one stim sample to numpy in the main thread before any worker thread does.

    stim looks numpy's C API up on first use behind a C++ static-init guard. When several
    threads reach that first use together, one holds the GIL while it waits on the guard and
    the one inside the lookup waits for the GIL: a deadlock. The tier 2 Opus arm sat like that
    for 50 minutes on 2026-11-01 with no API call made. One sample here ends the race.
    """
    dt.sample(dt.nominal(3), 1, 0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--effort", default=None)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--max-usd-episode", type=float, default=EPISODE_USD)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--set", default="tier1", choices=sorted(dt.TASK_SETS))
    ap.add_argument("--tasks", default="", help="comma list of task names from any set")
    ap.add_argument("--awareness", action="store_true", help="ask for the model assessment")
    ap.add_argument("--out", type=Path, default=paths.DATA / "agent_decoder")
    args = ap.parse_args()
    tasks = dt.tasks_by_name(args.tasks) if args.tasks else dt.TASK_SETS[args.set]()
    if pricing.estimate_usd("anthropic", args.model, 1000, 1000) is None:
        sys.exit(f"no price for {args.model} in configs; the budget caps would never fire")
    client, root = AnthropicClient(), args.out / "work" / args.arm
    warm_up_stim()  # before the thread pool: see the function
    root.mkdir(parents=True, exist_ok=True)
    rows, spent = [], 0.0
    traj_path = paths.trajectories_dir() / args.out.name / f"decoder_{args.arm}.jsonl.gz"
    traj_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        gzip.open(traj_path, "wt", encoding="utf-8") as trace,
        ThreadPoolExecutor(args.concurrency) as pool,
    ):
        for start in range(0, len(tasks), args.concurrency):
            if spent >= args.max_usd:
                print(f"budget stop at ${spent:.2f}: {len(rows)} of {len(tasks)} tasks done")
                break
            batch = tasks[start : start + args.concurrency]
            for row, trajectory in pool.map(
                lambda t: safe_episode(
                    client, t, args.model, args.effort, root, args.max_usd_episode, args.awareness
                ),
                batch,
            ):
                rows.append(row | {"arm": args.arm})
                trace.write(json.dumps(trajectory, ensure_ascii=False) + "\n")
                trace.flush()
                spent += row["cost_usd"]
            pd.DataFrame(rows).to_parquet(args.out / f"{args.arm}.parquet")  # after every batch
    df = pd.DataFrame(rows)
    cols = ["task", "outcome", "stop", "turns", "gap_closed", "uses_correlations", "cost_usd"]
    if args.awareness:
        cols += [
            "adequate_truth",
            "report_adequate",
            "report_confidence",
            "awareness_brier",
            "gap_drift",
            "truth_scope",
            "report_scope",
            "localization",
            "diagnosis_correct",
            "passed",
        ]
    cols = [c for c in cols if c in df.columns]
    print(df[cols].round(3).to_string(index=False))
    print(f"{args.arm}: median gap closed {df.gap_closed.median():.3f}, ${spent:.2f}")
    if "passed" in df.columns:
        print(
            f"pass rate {df.passed.fillna(False).mean():.3f} ({int(df.passed.sum())} of "
            f"{len(df)}), diagnosis correct {df.diagnosis_correct.fillna(False).mean():.3f}"
        )
    modes = analyze_decoder(args.out / f"{args.arm}.parquet", traj_path)
    print("failure modes:", modes.leaf.value_counts().to_dict())


if __name__ == "__main__":
    main()
