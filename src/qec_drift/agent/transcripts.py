"""Readable transcripts of the archived trajectories: one Markdown file per episode.

A trajectory archive (trajectories/<set>/decoder_<arm>.jsonl.gz) holds one JSON record per
episode in one of three shapes: the API harness (`messages`: the model's turns with run_python
calls and their results), Claude Code (`events`: the CLI's stream of assistant blocks, tool
results and the final result) and Codex (`events`: items of agent messages, commands with their
output, file changes). `render_archive` writes trajectories/<set>/<arm>/<task>.md for each
record and an index README.md for the arm, with the episode's score when the arm's table in
data/<set>/<arm>.parquet is there. Long tool output is cut; the shipped decoder and the report
are complete.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from qec_drift import paths
from qec_drift.agent import attempts

RESULT_CHARS = 3000  # of each tool result or command output
CODE_CHARS = 20000  # of a file the agent wrote
TEXT_CHARS = 12000  # of one assistant message
SCORE_COLUMNS = ("outcome", "passed", "gap_closed", "gap_drift", "diagnosis_correct", "turns")
MODE_COLUMNS = ("leaf", "gate", "verdict", "verdict_rel")  # from <arm>_failure_modes.parquet
LABEL_COLUMNS = ("label", "gate")  # from <arm>_taxonomy.parquet: the one label and its gate


def _cut(text: str, limit: int) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... ({len(text) - limit} more characters cut)"


def _fence(text: str, lang: str = "") -> str:
    fence = "````" if "```" in text else "```"
    return f"{fence}{lang}\n{text.rstrip()}\n{fence}"


def _tool_use(name: str, inp: dict) -> list[str]:
    """One tool call of the API or Claude Code harness as Markdown lines."""
    if name == "run_python":
        return ["**run_python**", _fence(_cut(inp.get("code", ""), CODE_CHARS), "python")]
    if name == "Bash":
        return ["**Bash**", _fence(_cut(inp.get("command", ""), CODE_CHARS), "sh")]
    if name in ("Write", "Edit"):
        head = f"**{name}** `{inp.get('file_path', '')}`"
        body = inp.get("content") if name == "Write" else inp.get("new_string", "")
        lines = [head, _fence(_cut(body or "", CODE_CHARS))]
        if name == "Edit":
            lines.insert(1, "replacing:\n" + _fence(_cut(inp.get("old_string", ""), CODE_CHARS)))
        return lines
    if name == "Read":
        return [f"**Read** `{inp.get('file_path', '')}`"]
    return [f"**{name}**", _fence(_cut(json.dumps(inp, indent=1), CODE_CHARS), "json")]


def _blocks(content, out: list[str]) -> None:
    """Assistant content blocks (API and Claude Code share the shape)."""
    if isinstance(content, str):
        out.append(_cut(content, TEXT_CHARS))
        return
    for b in content or []:
        if not isinstance(b, dict):
            continue
        kind = b.get("type")
        if kind == "text" and b.get("text"):
            out.append(_cut(b["text"], TEXT_CHARS))
        elif kind == "thinking":
            out.append(f"*(thinking, {len(b.get('thinking') or '')} characters)*")
        elif kind == "tool_use":
            out += _tool_use(b.get("name", "?"), b.get("input") or {})


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict):
            parts.append(str(b.get("text") or b.get("content") or ""))
        else:
            parts.append(str(b))
    return "\n".join(parts)


def _api(rec: dict) -> list[str]:
    out: list[str] = []
    for m in rec.get("messages", []):
        role = m.get("role")
        if role == "assistant":
            body = m.get("body")
            body = json.loads(body) if isinstance(body, str) else (body or {})
            out.append("### Agent")
            _blocks(body.get("content"), out)
        elif role == "tool":
            out.append("Result:")
            out.append(_fence(_cut(_result_text(m.get("content")), RESULT_CHARS)))
        elif role == "user" and out:  # the first user turn is the prompt, shown above
            out.append("### User")
            out.append(_cut(_result_text(m.get("content")), TEXT_CHARS))
    return out


def _claude_code(rec: dict) -> list[str]:
    out: list[str] = []
    for e in rec.get("events", []):
        kind = e.get("type")
        if kind == "assistant":
            out.append("### Agent")
            _blocks((e.get("message") or {}).get("content"), out)
        elif kind == "user":
            for b in (e.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out.append("Result:")
                    out.append(_fence(_cut(_result_text(b.get("content")), RESULT_CHARS)))
        elif kind == "result":
            cost = e.get("total_cost_usd")
            out.append(
                f"*Session ended: {e.get('subtype') or e.get('terminal_reason') or '?'}"
                + (f", CLI cost estimate ${cost:.2f}" if cost else "")
                + "*"
            )
        elif kind == "harness":
            out.append(f"*Harness: {e.get('note')}*")
        elif kind == "rate_limit_event":
            out.append("*(rate limit event)*")
    return out


def _codex(rec: dict) -> list[str]:
    out: list[str] = []
    for e in rec.get("events", []):
        kind = e.get("type")
        item = e.get("item") or {}
        if kind != "item.completed":
            if kind == "turn.completed":
                usage = e.get("usage") or {}
                out.append(
                    f"*Turn ended: {usage.get('input_tokens', 0)} input tokens, "
                    f"{usage.get('output_tokens', 0)} output tokens*"
                )
            elif kind == "turn.failed":
                out.append(f"*Turn failed: {(e.get('error') or {}).get('message', '')}*")
            elif kind == "harness":
                out.append(f"*Harness: {e.get('note')}*")
            continue
        what = item.get("type")
        if what == "agent_message":
            out += ["### Agent", _cut(item.get("text", ""), TEXT_CHARS)]
        elif what == "reasoning":
            out.append(f"*(reasoning, {len(item.get('text') or '')} characters)*")
        elif what == "command_execution":
            out += ["**Command**", _fence(_cut(item.get("command", ""), CODE_CHARS), "sh")]
            out.append(f"Result (exit {item.get('exit_code')}):")
            out.append(_fence(_cut(item.get("aggregated_output", ""), RESULT_CHARS)))
        elif what == "file_change":
            files = ", ".join(f"`{c.get('path')}`" for c in item.get("changes") or [])
            out.append(f"**File change** {files}")
        elif what == "error":
            out.append(f"*CLI notice: {_cut(item.get('message', ''), 300)}*")
    return out


def render_record(rec: dict, score: dict | None = None) -> str:
    """The Markdown transcript of one episode record."""
    scaffold = rec.get("scaffold") or ("api" if "messages" in rec else "?")
    head = f"# {rec.get('task', '?')}: {rec.get('model', '?')}"
    if rec.get("effort"):
        head += f" at {rec['effort']} effort"
    lines = [head, "", f"Scaffold: {scaffold}."]
    if score:
        bits = [f"{k} {score[k]}" for k in SCORE_COLUMNS if k in score]
        lines.append("Score: " + ", ".join(bits) + ".")
        if "label" in score:
            lines.append(
                f"Failure mode (docs/failure-taxonomy.md): `{score['label']}` ({score['gate']}), "
                f"from the decoder leaf `{score.get('leaf', '?')}` and the verdict "
                f"{score.get('verdict_rel', '?')} (relative rule; "
                f"{score.get('verdict', '?')} under the absolute rule)."
            )
        elif "leaf" in score:
            lines.append(
                f"Failure mode (docs/failure-taxonomy.md): `{score['leaf']}` at gate "
                f"{score.get('gate', '?')}; verdict {score.get('verdict', '?')} (absolute rule), "
                f"{score.get('verdict_rel', '?')} (relative rule)."
            )
    if rec.get("error"):
        lines.append(f"Harness error: {rec['error']}")
    prompt = rec.get("prompt")
    if not prompt and rec.get("messages"):
        first = rec["messages"][0]
        prompt = _result_text(first.get("content")) if first.get("role") == "user" else ""
    if prompt:
        lines += ["", "<details><summary>Prompt</summary>", "", _cut(prompt, TEXT_CHARS)]
        lines += ["", "</details>"]
    lines += ["", "## Transcript", ""]
    if "messages" in rec:
        body = _api(rec)
    elif rec.get("trace_kind") == "codex_stream":
        body = _codex(rec)
    else:
        body = _claude_code(rec)
    lines += [line for part in body for line in (part, "")]
    if rec.get("decoder_src"):
        code = _fence(_cut(rec["decoder_src"], CODE_CHARS), "python")
        lines += ["## Decoder shipped", "", code, ""]
    if rec.get("report") is not None:
        lines += ["## Report", "", _fence(json.dumps(rec["report"], indent=1), "json"), ""]
    return "\n".join(lines)


def _scores(parquet: Path, df: pd.DataFrame) -> dict[str, dict]:
    """Task -> score fields from the arm's table, and the failure mode from its modes table."""
    cols = [c for c in SCORE_COLUMNS if c in df.columns]
    out = {}
    for _, row in df.iterrows():
        out[row["task"]] = {
            c: (round(row[c], 3) if isinstance(row[c], float) else row[c]) for c in cols
        }
    modes = parquet.with_name(f"{parquet.stem}_failure_modes.parquet")
    if modes.is_file():
        selected = attempts.select(pd.read_parquet(modes).to_dict("records"), df.to_dict("records"))
        for task, row in selected.items():
            out[task].update({c: row[c] for c in MODE_COLUMNS if c in row})
    labels = parquet.with_name(f"{parquet.stem}_taxonomy.parquet")
    if labels.is_file():
        selected = attempts.select(
            pd.read_parquet(labels).to_dict("records"), df.to_dict("records")
        )
        for task, row in selected.items():
            out[task].update({c: row[c] for c in LABEL_COLUMNS if c in row})
    return out


def records(archive: Path) -> Iterator[dict]:
    """Read concatenated gzip members using their actual decompressor boundaries.

    Complete JSON lines in a truncated final member are retained. After an invalid member,
    scan for another header; header bytes inside a valid member never split that member.
    """
    raw = archive.read_bytes()
    offset = 0
    while (start := raw.find(b"\x1f\x8b\x08", offset)) != -1:
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            text = d.decompress(raw[start:]).decode("utf-8", "replace")
        except zlib.error:
            offset = start + 1
            continue
        offset = len(raw) - len(d.unused_data) if d.eof else start + 1
        for line in text.splitlines():
            if line.startswith("{"):
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def matching_records(archive: Path | None, rows: pd.DataFrame) -> dict[str, dict]:
    if archive is None or not archive.is_file():
        return {}
    return attempts.select(records(archive), rows.to_dict("records"))


def render_archive(archive: Path, scores_parquet: Path | None = None) -> Path:
    """Write <set>/<arm>/<task>.md for every record of the archive and the arm's index."""
    arm = archive.name.removesuffix(".jsonl.gz").removeprefix("decoder_")
    folder = archive.parent / arm
    folder.mkdir(exist_ok=True)
    rows = (
        pd.read_parquet(scores_parquet)
        if scores_parquet and scores_parquet.is_file()
        else pd.DataFrame()
    )
    scores = _scores(scores_parquet, rows) if not rows.empty else {}
    index = [f"# {arm}", "", f"Rendered from `{archive.name}`.", ""]
    if scores:
        cols = "task | outcome | passed | gap_closed | gap_drift | diagnosis"
        index += [f"| {cols} | failure mode | verdict |"]
        index += ["|---|---|---|---|---|---|---|---|"]
    last = {rec.get("task", "unknown"): rec for rec in records(archive)}  # a rerun replaces
    if not rows.empty:
        matched = matching_records(archive, rows)
        for task in rows.task:
            last[task] = matched.get(task) or {
                "task": task,
                "error": "No archived transcript matches the scored attempt.",
            }
    for task, rec in last.items():
        score = scores.get(task)
        (folder / f"{task}.md").write_text(render_record(rec, score))
        if scores:
            s = score or {}
            index.append(
                f"| [{task}]({task}.md) | {s.get('outcome', '')} | {s.get('passed', '')} | "
                f"{s.get('gap_closed', '')} | {s.get('gap_drift', '')} | "
                f"{s.get('diagnosis_correct', '')} | {s.get('label', s.get('leaf', ''))} | "
                f"{s.get('verdict_rel', '')} |"
            )
        else:
            index.append(f"- [{task}]({task}.md)")
    (folder / "README.md").write_text("\n".join(index) + "\n")
    return folder


def render_all(root: Path | None = None) -> list[Path]:
    """Every archive under the trajectories folder (the paper-era archive/ excluded)."""
    root = root or paths.trajectories_dir()
    done = []
    for archive in sorted(root.rglob("*.jsonl.gz")):
        if "archive" in archive.relative_to(root).parts:
            continue
        set_name = archive.parent.name if archive.parent != root else "agent_decoder"
        arm = archive.name.removesuffix(".jsonl.gz").removeprefix("decoder_")
        done.append(render_archive(archive, paths.DATA / set_name / f"{arm}.parquet"))
    return done
