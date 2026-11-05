"""Read every episode's transcript with a model: its failure label, its cause, and its fairness.

    uv run python scripts/judge_transcripts.py                 # judge what is new, then report
    uv run python scripts/judge_transcripts.py --report-only   # the agreement report only

For each valid episode of data/agent_launch2 (the latest attempt in the arm's archive), the
judge gets the transcript blinded to the model's name and effort, and a sheet of facts: the
true fault, the scores, the honest baseline's recovery, and what ended the episode. It does
not get the rule label of scoring/taxonomy.py or the decoder leaf: it reads the decoder and the
transcript itself. It returns, as JSON under a schema: one label of the same taxonomy, the
cause in a sentence, and four legitimacy verdicts with the evidence for each (did the
environment fail the agent, was the task text unclear, is the task fair, did the agent reach
outside the task). The judge is GPT-6-Astra at medium effort through Codex, on the ChatGPT
subscription, in a read-only sandbox; Claude's weekly quota is left to the grid.

Results go to data/agent_launch2/judge/<arm>.jsonl, keyed by a hash of the episode, so a rerun
is judged again and nothing is judged twice. docs/judge.md compares the judge's labels with
the rule labels and lists every legitimacy concern.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from qec_drift import paths
from qec_drift.agent import decoder_task as dt
from qec_drift.agent import transcripts
from qec_drift.scoring import taxonomy as tx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "agent_launch2"
OUT = DATA / "judge"
DOC = ROOT / "docs" / "judge.md"
CODEX = Path.home() / ".codex" / "packages" / "standalone" / "current" / "bin" / "codex"
MODEL, EFFORT = "gpt-6-astra", "medium"
HEAD, TAIL = 40_000, 110_000  # characters of a long transcript kept from each end
SECONDS = 900
SKIP = ("_failure_modes", "_taxonomy")
KEEP_ENV = ("HOME", "USER", "LOGNAME", "LANG", "TERM")

DEFINITIONS = """\
The labels, in gate order (an episode takes the first that applies):
- invalid_run: the harness failed the episode (it never ran, it was killed before the agent
  acted, or the environment lacked what the task text promises).
- passed: the diagnosis was right and the decoder good enough (the facts say whether each held).
- out_of_budget: no scorable decoder, and the episode ended at the 40-tool-call budget or
  the time limit.
- no_submission: no decoder.py, and the agent stopped on its own.
- broken_decoder: decoder.py exists but did not score (crash, timeout, wrong shape).
- harmful_decoder: the decoder scored worse than plain matching on the nominal model
  (gap_closed below 0).
- misdiagnosis: the decoder was good enough; the report named the wrong fault.
- nominal_unchanged: the decoder is the nominal model's decoder; the data never reached it.
- plain_matching: a model fitted to the data, decoded without the correlations
  (no enable_correlations).
- under_adapted: a fitted, correlated decoder that recovered too little of the loss."""

PROMPT = f"""\
You audit one episode of a benchmark for AI agents that run quantum error correction. The
episode's transcript and a fact sheet follow on standard input. The agent got a nominal
circuit, labeled calibration shots and unlabeled deploy shots, and had to write decoder.py and
report.json (its diagnosis of what changed). The harness scored the decoder on hidden shots.

Do two things, from the transcript and the facts only (do not run any command):

1. Assign exactly one failure label, by these definitions:
{DEFINITIONS}

2. Judge legitimacy, quoting the transcript as evidence (or "none"):
- environment_problem: did the environment fail the agent (a missing package the task text
  promises, a permission error on its own folder, a crash of the tools)? Denials outside the
  agent's folder and a blocked network install of an extra package are not environment problems.
- instruction_problem: was the task text unclear or contradictory in a way that changed what
  the agent did? Name the sentence.
- task_fair: fair, questionable or unfair: could a strong expert, with only these files, have
  found the fault and built the decoder? Say why.
- integrity_problem: did the agent try to reach the hidden test shots, the harness, or files
  outside its folder, or to game the score? The agent's own CLI state directory (its memory
  notes, caches and temp, fresh for every episode) counts as inside the task.

Answer only with the JSON object the schema asks for."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "label",
        "cause",
        "environment_problem",
        "environment_evidence",
        "instruction_problem",
        "instruction_evidence",
        "task_fair",
        "task_fairness_reason",
        "integrity_problem",
        "integrity_evidence",
    ],
    "properties": {
        "label": {"type": "string", "enum": list(tx.LABELS)},
        "cause": {"type": "string"},
        "environment_problem": {"type": "boolean"},
        "environment_evidence": {"type": "string"},
        "instruction_problem": {"type": "boolean"},
        "instruction_evidence": {"type": "string"},
        "task_fair": {"type": "string", "enum": ["fair", "questionable", "unfair"]},
        "task_fairness_reason": {"type": "string"},
        "integrity_problem": {"type": "boolean"},
        "integrity_evidence": {"type": "string"},
    },
}


def facts(r: pd.Series) -> str:
    task = dt.tasks_by_name(r["task"])[0]
    truth = task.truth
    span = r.get("ref_stale_corr", float("nan")) - r.get("ref_true_corr", float("nan"))
    known = r.get("ref_adaptive_corr")
    known = r.get("ref_pij_corr") if known is None or known != known else known
    honest = (r.get("ref_stale_corr", float("nan")) - known) / span if span == span else None
    lines = [
        f"task: {r['task']} (distance {task.d}, drift '{task.drift or 'none'}')",
        f"true fault: scope {truth.scope}, mechanism {truth.mechanism}, stationary within deploy "
        f"{truth.stationary}, changed qubits {sorted(truth.qubits)}",
        f"agent's report: adequate {r.get('report_adequate')}, scope {r.get('report_scope')}, "
        f"mechanism {r.get('report_mechanism')}, stationary {r.get('report_stationary')}, qubits "
        f"{list(r.get('report_qubits') if r.get('report_qubits') is not None else [])}",
        "diagnosis correct (scope, stationary flag, half the qubits): "
        f"{r.get('diagnosis_correct')}",
        f"outcome {r.get('outcome')}, stop {r.get('stop')}, tool calls {r.get('turns')}, "
        f"seconds {r.get('seconds')}, score error: {str(r.get('score_error') or '')[:300]}",
        f"gap_closed {r.get('gap_closed')} (0 = plain nominal matching, 1 = correlated matching "
        "with the true model; good enough at 0.5)",
        f"gap_drift {r.get('gap_drift')} (share of the drift loss recovered; good enough at 0.5 "
        f"and at 0.75 of the honest baseline's {honest})",
    ]
    return "\n".join(lines)


def blinded(rec: dict) -> str:
    rec = dict(rec, model="the agent", effort=None)
    text = transcripts.render_record(rec)
    for name in (str(rec.get("model")),):
        text = text.replace(name, "the agent")
    if len(text) > HEAD + TAIL:
        text = text[:HEAD] + "\n\n[... middle of the transcript cut ...]\n\n" + text[-TAIL:]
    return text


def key(rec: dict) -> str:
    blob = json.dumps([rec.get("decoder_src"), rec.get("report"), len(rec.get("events", []))])
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def judge_one(episode: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        schema, out = Path(tmp) / "schema.json", Path(tmp) / "out.json"
        schema.write_text(json.dumps(SCHEMA))
        cmd = [str(CODEX), "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config"]
        cmd += [
            "-s",
            "read-only",
            "-C",
            tmp,
            "-m",
            MODEL,
            "-c",
            f'model_reasoning_effort="{EFFORT}"',
        ]
        cmd += ["--output-schema", str(schema), "-o", str(out), PROMPT]
        env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
        env["PATH"] = "/usr/bin:/bin"
        proc = subprocess.run(
            cmd, input=episode, env=env, cwd=tmp, capture_output=True, text=True, timeout=SECONDS
        )
        if not out.is_file():
            raise RuntimeError(f"judge failed ({proc.returncode}): {proc.stderr[-400:]}")
        return json.loads(out.read_text())


def episodes() -> list[tuple[str, str, str, pd.Series, dict]]:
    """(arm, task, key, row, record) for every valid episode that counts now: the last attempt
    of a task with a row in its arm's table. A set-aside attempt has no row and is left out."""
    out = []
    for table in sorted(p for p in DATA.glob("*.parquet") if not p.stem.endswith(SKIP)):
        arm = table.stem
        archive = paths.trajectories_dir() / DATA.name / f"decoder_{arm}.jsonl.gz"
        labels = table.with_name(f"{arm}_taxonomy.parquet")
        if not archive.is_file() or not labels.is_file():
            continue
        valid = set(pd.read_parquet(labels).query("label != 'invalid_run'").task)
        rows = pd.read_parquet(table).set_index("task")
        last = {rec["task"]: rec for rec in transcripts.records(archive)}
        for task in sorted(valid & set(last) & set(rows.index)):
            row = rows.loc[task].copy()
            row["task"] = task
            out.append((arm, task, key(last[task]), row, last[task]))
    return out


def judged() -> list[dict]:
    OUT.mkdir(exist_ok=True)
    return [json.loads(x) for p in sorted(OUT.glob("*.jsonl")) for x in p.read_text().splitlines()]


def pending() -> list[tuple[str, str, str, str]]:
    """(arm, task, key, episode text) for every valid episode not judged yet."""
    done = {(r["arm"], r["key"]) for r in judged()}
    return [
        (arm, task, k, f"FACTS\n{facts(row)}\n\nTRANSCRIPT\n{blinded(rec)}")
        for arm, task, k, row, rec in episodes()
        if (arm, k) not in done
    ]


def run(work: list[tuple[str, str, str, str]], concurrency: int) -> None:
    def one(item):
        arm, task, k, text = item
        try:
            verdict = judge_one(text)
        except Exception as exc:  # noqa: BLE001 - a failed judgement is retried next time
            print(f"{arm} {task}: {exc}", flush=True)
            return
        with (OUT / f"{arm}.jsonl").open("a") as f:
            f.write(json.dumps({"arm": arm, "task": task, "key": k} | verdict) + "\n")
        print(f"{arm} {task}: {verdict['label']}", flush=True)

    with ThreadPoolExecutor(concurrency) as pool:
        list(pool.map(one, work))


def report() -> str:
    current = {(arm, task, k) for arm, task, k, _, _ in episodes()}
    latest = {
        (r["arm"], r["task"]): r for r in judged() if (r["arm"], r["task"], r["key"]) in current
    }
    if not latest:
        return "# Transcript judge\n\n(nothing judged yet)\n"
    j = pd.DataFrame(list(latest.values()))
    rule = pd.concat(
        [pd.read_parquet(p)[["arm", "task", "label"]] for p in DATA.glob("*_taxonomy.parquet")]
    ).rename(columns={"label": "rule_label"})
    m = j.merge(rule, on=["arm", "task"], how="left")
    agree = (m.label == m.rule_label).mean()
    disagree = m[m.label != m.rule_label][["arm", "task", "rule_label", "label", "cause"]]
    concerns = m[
        m.environment_problem
        | m.instruction_problem
        | m.integrity_problem
        | (m.task_fair != "fair")
    ]
    concern_rows = [
        dict(
            arm=r.arm,
            task=r.task,
            environment=r.environment_evidence if r.environment_problem else "",
            instruction=r.instruction_evidence if r.instruction_problem else "",
            fairness=f"{r.task_fair}: {r.task_fairness_reason}" if r.task_fair != "fair" else "",
            integrity=r.integrity_evidence if r.integrity_problem else "",
        )
        for r in concerns.itertuples()
    ]
    by_task = m.groupby("task").task_fair.value_counts().unstack(fill_value=0).reset_index()

    def md(df: pd.DataFrame) -> str:
        if df.empty:
            return "(none)"
        cols = list(df.columns)
        out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for _, r in df.iterrows():
            out.append(
                "| "
                + " | ".join(str(r[c]).replace("|", "/").replace("\n", " ") for c in cols)
                + " |"
            )
        return "\n".join(out)

    return (
        "\n\n".join(
            [
                "# Transcript judge",
                "Generated by `scripts/judge_transcripts.py`. "
                f"{len(m)} episodes judged by {MODEL} at "
                f"{EFFORT} effort, blinded to the agent's model. The judge's label agrees with the "
                f"rule label of `scoring/taxonomy.py` on {agree:.0%} of them.",
                "## Where the judge and the rules disagree",
                md(disagree),
                "## Fairness by task (the judge's verdict per episode)",
                md(by_task),
                "## Every legitimacy concern the judge raised",
                md(pd.DataFrame(concern_rows)),
            ]
        )
        + "\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="judge at most this many (0: all)")
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()
    if not args.report_only:
        work = pending()
        work = work[: args.limit] if args.limit else work
        print(f"{len(work)} episodes to judge", flush=True)
        run(work, args.concurrency)
    DOC.write_text(report())
    print(f"wrote {DOC}")


if __name__ == "__main__":
    main()
