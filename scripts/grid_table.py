"""The live results table: models by effort levels, pass rates per cell, into the README.

    uv run python scripts/grid_table.py                      # print the table
    uv run python scripts/grid_table.py --readme README.md   # also replace the README block

Each cell is the relative pass rate (the headline: diagnosis right, half the gap closed, and
at least 0.75 of what the honest adaptive decoder recovers) over the absolute pass rate
(without the honest-decoder bar), from scripts/launch_scores.py. An arm still running shows
how many of the set's tasks it has done. Arms are the parquet files of a launch folder, named
<model>_<effort>_<cc|codex>.parquet by scripts/run_grid.py (cc: Claude Code on the claude.ai
subscription; codex: Codex on the ChatGPT subscription; no suffix: the API harness).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from launch_scores import scored  # noqa: E402
from run_grid import TOOL_CALLS, VALID, gate  # noqa: E402

from qec_drift.agent import attempts  # noqa: E402
from qec_drift.agent.decoder_task import LAUNCH2_CORE  # noqa: E402

EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
SCAFFOLDS = {"cc": "Claude Code", "codex": "Codex", "": "API"}
START = "<!-- grid:start -->"
END = "<!-- grid:end -->"
SETS = (  # folder, title
    ("data/agent_launch2", "v2 launch set"),
    ("data/agent_launch", "v1 launch set"),
)


def model_name(slug: str) -> str:
    """fable_5_1 -> Fable 5.1; gpt_5_6_sol -> GPT-5.6-Sol; opus_4_8 -> Opus 4.8."""
    parts = slug.split("_")
    if parts[0] == "gpt":
        out, digits = [], []
        for p in parts[1:]:
            if p.isdigit():
                digits.append(p)
            else:
                if digits:
                    out.append(".".join(digits))
                    digits = []
                out.append(p.capitalize())
        if digits:
            out.append(".".join(digits))
        return "GPT-" + "-".join(out)
    words = [p for p in parts if not p.isdigit()]
    digits = [p for p in parts if p.isdigit()]
    return " ".join(w.capitalize() for w in words) + (" " + ".".join(digits) if digits else "")


def parse_arm(stem: str) -> tuple[str, str, str] | None:
    """(model slug, effort, scaffold key) from an arm's file name, or None."""
    m = re.fullmatch(r"(.+?)_(low|medium|high|xhigh|max|ultra)(?:_(cc|codex))?", stem)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3) or ""


def set_size(folder: Path) -> int | None:
    refs = folder / "references.json"
    if not refs.is_file():
        return None
    return len(gate(json.loads(refs.read_text()))[0])


def cells(folder: Path) -> dict[tuple[str, str], dict[str, str]]:
    """(model, scaffold) -> effort -> cell text, for every arm parquet in the folder."""
    total = set_size(folder)
    out: dict[tuple[str, str], dict[str, str]] = {}
    for path in sorted(folder.glob("*.parquet")):
        if path.name.endswith("_failure_modes.parquet"):
            continue
        arm = parse_arm(path.stem)
        if arm is None:
            continue
        model, effort, scaffold = arm
        df = scored(path)
        acted = (df.turns.fillna(0) > 0) | (df.stop == "completed")
        df = df[df.outcome.isin(VALID) & acted & (df.turns.fillna(0) <= TOOL_CALLS + 1)]
        labels = path.with_name(f"{path.stem}_taxonomy.parquet")
        if labels.is_file():
            matched = attempts.select(
                pd.read_parquet(labels).to_dict("records"), df.to_dict("records")
            )
            valid = {task for task, row in matched.items() if row["label"] != "invalid_run"}
            df = df[df.task.isin(valid)]
        if df.empty:
            continue  # only rows that scripts/run_grid.py will rerun
        n = len(df)
        text = f"{df.pass_rel.mean():.0%} / {df.passed.mean():.0%}"
        core = len(LAUNCH2_CORE) if folder.name == "agent_launch2" else None
        if core and n == core and total and total > core:
            text += " (core)"  # the LAUNCH2_CORE tasks every arm runs first
        elif core and n < core:
            text += f" ({n}/{core})"
        elif total is not None and n < total:
            text += f" ({n}/{total})"
        out.setdefault((model, scaffold), {})[effort] = text
    return out


def table(folder: Path, title: str) -> str:
    rows = cells(folder)
    if not rows:
        note = "(no valid episodes yet; rows set aside for a fairness fix are in the fairness log)"
        return f"### {title}\n\n{note}" if folder.is_dir() else ""
    efforts = [e for e in EFFORTS if any(e in r for r in rows.values())]
    total = set_size(folder)
    head = f"### {title}" + (
        f" ({total} tasks gated; the core is {len(LAUNCH2_CORE)})"
        if total and folder.name == "agent_launch2"
        else f" ({total} tasks)"
        if total
        else ""
    )
    lines = [head, "", "| model | " + " | ".join(efforts) + " |", "|---|" + "---|" * len(efforts)]
    for (model, scaffold), by_effort in sorted(rows.items()):
        name = f"{model_name(model)} ({SCAFFOLDS[scaffold]})"
        lines.append(f"| {name} | " + " | ".join(by_effort.get(e, "") for e in efforts) + " |")
    return "\n".join(lines)


def block(root: Path) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M %Z")
    parts = [
        START,
        "## Live results",
        "",
        "Pass rate under the relative rule / under the absolute rule "
        "(docs/launch2-grid-2026-11-02.md). Arms still running show their done count. "
        "Episodes labelled `invalid_run` (the harness failed them; docs/failure-taxonomy.md) "
        "are left out. "
        "Updated " + stamp + ".",
        "",
    ]
    for folder, title in SETS:
        t = table(root / folder, title)
        if t:
            parts += [t, ""]
    parts.append(END)
    return "\n".join(parts)


def write_readme(readme: Path, text: str) -> None:
    old = readme.read_text()
    if START in old and END in old:
        new = old[: old.index(START)] + text + old[old.index(END) + len(END) :]
    else:
        title_end = old.index("\n", old.index("# ")) + 1
        new = old[:title_end] + "\n" + text + "\n" + old[title_end:]
    readme.write_text(new)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--readme", type=Path, default=None, help="README to update in place")
    args = ap.parse_args()
    text = block(args.root)
    print(text)
    if args.readme:
        write_readme(args.readme, text)


if __name__ == "__main__":
    main()
