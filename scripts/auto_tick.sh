#!/bin/bash
# Refresh the grid's analysis every hour while the grids run, with no Claude session:
# relabel every arm, rebuild the legitimacy report, run the blinded judge on new episodes
# (it uses the ChatGPT quota), refresh the README table, commit and push what changed, then
# refresh the public snapshot (scripts/publish_snapshot.sh: no transcripts, secret scan first).
# Usage: scripts/auto_tick.sh   (run in the background; stop it with kill)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
log=data/agent_launch2/auto_tick.out
while true; do
  {
    echo "--- $(date '+%Y-%m-%d %H:%M %Z')"
    uv run python scripts/classify_arms.py | grep agent_launch2
    uv run python scripts/legitimacy.py | tail -1
    uv run python scripts/judge_transcripts.py --concurrency 2 | tail -1
    uv run python scripts/grid_table.py --readme README.md > /dev/null
    uv run python scripts/usage.py
    git add README.md docs trajectories data/usage_log.jsonl
    if ! git diff --cached --quiet; then
      git commit -q -m "docs: grid refresh $(date '+%Y-%m-%d %H:%M %Z')" && git push -q
    fi
    scripts/publish_snapshot.sh
  } >> "$log" 2>&1
  sleep 3600
done
