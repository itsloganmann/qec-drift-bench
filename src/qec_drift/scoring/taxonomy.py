"""The one failure taxonomy: a single label per episode, and the legitimacy flags of each episode.

Every episode of every arm takes the first gate that applies (docs/failure-taxonomy.md). The
gates are mutually exclusive and, over every combination of their inputs, exhaustive
(tests/test_taxonomy.py). They read three things: the row the harness scored, the decoder
leaf and the relative-rule verdict of scoring/failure_modes_decoder.py, and features of the
transcript (agent/transcripts.py reads every archive format).

    G0 invalid_run        the harness failed the episode: it never ran, was killed before the
                          agent acted, or the environment lacked what the task text promises
    G1 passed             diagnosis right, decoder good enough under the relative rule
    G2 out_of_budget      no scorable decoder, and the episode hit the tool-call cap or time limit
    G3 no_submission      no decoder.py, and the agent stopped on its own
    G4 broken_decoder     decoder.py exists but did not score (crash, timeout, wrong shape)
    G5 harmful_decoder    scored worse than plain matching on the nominal model
    G6 misdiagnosis       the decoder was good enough, the report named the wrong fault
    G7 nominal_unchanged  the decoder is the nominal one: the data never reached it
    G8 plain_matching     a fitted model decoded without the correlations
    G9 under_adapted      a fitted, correlated decoder that recovered too little of the loss

Labels G6 to G9 come from a failed scored episode with a decoder at least as good as plain
nominal matching: G6 when only the diagnosis failed, else by what the decoder carries. Whether
the diagnosis also failed is the attribute `diagnosis_wrong`, not a label.

The legitimacy flags are attributes of an episode, not labels: harness faults (what puts an
episode in G0), integrity events (the agent reached for something outside the task), and
scoring anomalies (results a reader should check, such as beating the oracle by a lot).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from qec_drift import paths
from qec_drift.agent import attempts, provider_limits
from qec_drift.agent.transcripts import matching_records
from qec_drift.scoring import failure_modes_decoder as fm

LABELS = (
    "invalid_run",
    "passed",
    "out_of_budget",
    "no_submission",
    "broken_decoder",
    "harmful_decoder",
    "misdiagnosis",
    "nominal_unchanged",
    "plain_matching",
    "under_adapted",
)
TOOL_CALLS = 40  # the task text's budget (agent/isolation.py)
BEAT_ORACLE = 1.15  # gap_drift above this: better than the per-shot oracle by a lot; check it
MISSING = re.compile(r"No module named '(stim|pymatching|numpy)'")
OWN_COPY = re.compile(r"(pip3? install|--target)[^\n]*\b(stim|pymatching|numpy)\b")
LOGIN = re.compile(r"not logged in|failed to authenticate|oauth session expired", re.I)
DENIED = re.compile(r"Operation not permitted|Permission denied")
NETWORK = re.compile(
    r"\b(curl|wget|git clone|pip3? install|uv pip install|npm install)\b|https?://"
)
OUTSIDE = re.compile(r"(?:^|[\s'\"=(])(?:\.\./|~/|/Users/|/private/var/folders/[^\s'\"]*/score-)")
PROBE = re.compile(  # the hidden test, the harness, or the public source (public since 2026-11-05)
    r"\btest\.npz\b|\bpred\.npy\b|qec_drift|qec-drift|itsloganmann|decoder_task|references\.json"
)


@dataclass
class Features:
    """What a transcript shows, beyond the scored row."""

    commands: list[str] = field(default_factory=list)  # what the agent ran or wrote
    outputs: list[str] = field(default_factory=list)  # what the tools answered
    notes: list[str] = field(default_factory=list)  # harness notes and CLI errors
    provider_interrupted: bool = False

    @property
    def budget_hit(self) -> bool:
        return any("tool-call limit" in n or "time limit" in n for n in self.notes)

    @property
    def env_missing(self) -> bool:
        """The environment lacked what the task text promises (agent/isolation.py fixed the
        one known cause on 2026-11-03). Installing a copy anyway is the flag `own_copy`."""
        return any(MISSING.search(o) for o in self.outputs)

    @property
    def login_lost(self) -> bool:
        return any(LOGIN.search(n) for n in self.notes)

    def flags(self, allowed: tuple[str, ...] = ()) -> dict[str, bool]:
        """Integrity events. Paths under `allowed` (the task folder, the venv) are the agent's
        own and do not count as reaching outside."""
        joined = "\n".join(self.commands)
        inside = joined
        for prefix in sorted(allowed, key=len, reverse=True):
            inside = inside.replace(prefix, "")
        return dict(
            denied=any(DENIED.search(o) for o in self.outputs),
            network=bool(NETWORK.search(joined)),
            outside=bool(OUTSIDE.search(inside)),
            probe=bool(PROBE.search(joined)),
            own_copy=any(OWN_COPY.search(c) for c in self.commands),
        )


def features(rec: dict) -> Features:
    """The commands, outputs and notes of one archived episode, in any archive format."""
    f = Features(provider_interrupted=provider_limits.interrupted(rec.get("events", [])))
    for m in rec.get("messages", []):  # the API harness
        body = m.get("body") if m.get("role") == "assistant" else None
        body = json.loads(body) if isinstance(body, str) else (body or {})
        for b in body.get("content", []) if isinstance(body, dict) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                f.commands.append(str((b.get("input") or {}).get("code", "")))
        if m.get("role") == "tool":
            f.outputs.append(str(m.get("content", "")))
    for e in rec.get("events", []):
        kind, item = e.get("type"), e.get("item") or {}
        if kind == "assistant":  # Claude Code
            for b in (e.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    f.commands.append(
                        str(inp.get("command") or inp.get("file_path") or "")
                        + "\n"
                        + str(inp.get("content") or inp.get("new_string") or "")
                    )
        elif kind == "user":
            for b in (e.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    f.outputs.append(str(b.get("content", ""))[:20000])
        elif kind == "item.completed" and item.get("type") == "command_execution":  # Codex
            f.commands.append(str(item.get("command", "")))
            f.outputs.append(str(item.get("aggregated_output", ""))[:20000])
        elif kind in ("harness", "stderr", "result", "turn.failed", "error"):
            text = e.get("note") or e.get("text") or e.get("message") or e.get("result")
            f.notes.append(str(text or e.get("error") or ""))
    return f


def label(leaf: str, verdict_rel: str, *, ran: bool, budget_hit: bool) -> tuple[str, str]:
    """(label, gate) from the decoder leaf, the relative-rule verdict and two run facts."""
    if not ran or leaf == "harness_error":
        return "invalid_run", "G0"
    if verdict_rel == "passed":
        return "passed", "G1"
    if leaf == "no_decoder":
        return ("out_of_budget", "G2") if budget_hit else ("no_submission", "G3")
    if leaf == "unscored":
        return ("out_of_budget", "G2") if budget_hit else ("broken_decoder", "G4")
    if leaf == "worse_than_plain":
        return "harmful_decoder", "G5"
    if verdict_rel == "missed_diagnosis":
        return "misdiagnosis", "G6"
    if leaf.startswith("nominal_"):
        return "nominal_unchanged", "G7"
    if leaf == "fitted_plain":
        return "plain_matching", "G8"
    return "under_adapted", "G9"


def anomalies(r: pd.Series) -> list[str]:
    """Scored results a reader should check by hand."""
    out = []
    drift = r.get("gap_drift")
    if drift == drift and drift is not None and drift > BEAT_ORACLE:
        out.append("beats_oracle")
    if r.get("reported") is False:
        out.append("no_report")
    if r.get("outcome") == "submitted" and int(r.get("turns") or 0) > TOOL_CALLS + 1:
        out.append("over_budget_row")
    return out


def analyze_arm(table: Path, archive: Path | None, df: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per episode: the label, its gate, and the legitimacy flags. Writes
    <arm>_taxonomy.parquet next to the arm's table."""
    df = pd.read_parquet(table) if df is None else df
    arm = table.stem
    code = fm.agent_code(archive, df) if archive else {}
    modes = fm.classify_arm(df, table.parent / "work" / arm, code).set_index("task")
    last = matching_records(archive, df)
    rows = []
    for _, r in df.iterrows():
        task = r["task"]
        f = features(last[task]) if task in last else Features()
        turns = int(r.get("turns") or 0)
        acted = turns > 0 or r.get("stop") == "completed"
        ran = (
            r.get("outcome") != "error" and acted and not f.env_missing
            and not f.login_lost and not f.provider_interrupted
        )
        budget = f.budget_hit or turns >= TOOL_CALLS or r.get("stop") in ("exit -9",)
        leaf, verdict_rel = modes.loc[task, "leaf"], modes.loc[task, "verdict_rel"]
        lab, gate = label(leaf, verdict_rel, ran=ran, budget_hit=budget and leaf != "harness_error")
        harness = [
            name
            for name, hit in (
                ("never_acted", not acted),
                ("env_missing", f.env_missing),
                ("login_lost", f.login_lost),
                ("provider_limit", f.provider_interrupted),
                ("error_row", r.get("outcome") == "error"),
            )
            if hit
        ]
        workdir = table.parent / "work" / arm / task
        seen = last.get(task, {}).get("workdir")  # the random folder the agent worked in
        allowed = (str(workdir.resolve()), str(workdir), str(paths.REPO_ROOT / ".venv"))
        allowed += (seen,) if seen else ()
        integrity = [name for name, hit in f.flags(allowed).items() if hit]
        if task in last and task in json.dumps(last[task].get("events", [])):
            integrity.append("name_seen")  # a task name says what is wrong (the fairness log)
        rows.append(
            dict(
                arm=arm,
                task=task,
                attempt_id=r.get("attempt_id"),
                label=lab,
                gate=gate,
                leaf=leaf,
                verdict_rel=verdict_rel,
                diagnosis_wrong=verdict_rel in ("missed_diagnosis", "missed_both"),
                harness=",".join(harness),
                integrity=",".join(integrity),
                anomalies=",".join(anomalies(r)),
                transcript=task in last,
            )
        )
    out = pd.DataFrame(rows)
    attempts.write_table(table.with_name(f"{arm}_taxonomy.parquet"), out.to_dict("records"))
    return out
