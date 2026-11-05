#!/bin/bash
# Keep the v2 grid going with no Claude session open. Every 10 minutes:
# - restart scripts/auto_tick.sh (the hourly refresh) if it is not running;
# - restart a scaffold's grid that is not running and has not finished ("exit 0" in its log);
# - run the Claude grid only from CLAUDE_FROM on and while the Claude week is below CLAUDE_MAX
#   percent: Logan keeps the last 10% for himself. Above it, the Claude grid and its episodes
#   are stopped (found by the scaffold's own command line, never by a model name); it starts
#   again after the weekly reset.
# Start it outside any session, so that closing Claude does not stop it:
#   scripts/supervise.sh --detach        (log: data/agent_launch2/supervise.out)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
LOG=data/agent_launch2/supervise.out
CLAUDE_FROM="2026-11-07 01:05"
CLAUDE_MAX=90

if [ "${1:-}" = --detach ]; then
  exec uv run python -c 'import subprocess, sys
subprocess.Popen(["scripts/supervise.sh"], stdin=subprocess.DEVNULL,
                 stdout=open(sys.argv[1], "a"), stderr=subprocess.STDOUT, start_new_session=True)' "$LOG"
fi

say() { echo "$(date '+%Y-%m-%d %H:%M') $*"; }
running() { pgrep -f "run_grid.py --backend $1" > /dev/null; }
finished() { [ "$(tail -1 "data/agent_launch2/grid_$1.out" 2> /dev/null)" = "exit 0" ]; }
start() {
  say "starting the $1 grid"
  (scripts/grid_v2.sh "$1"; echo "exit $?" >> "data/agent_launch2/grid_$1.out") > /dev/null 2>&1 &
}
killtree() {
  local child
  for child in $(pgrep -P "$1"); do killtree "$child"; done
  kill -9 "$1" 2> /dev/null
}
claude_week() { uv run python scripts/usage.py | sed -n 's/.*claude weekly all \([0-9]*\)%.*/\1/p'; }

from=$(date -j -f '%Y-%m-%d %H:%M' "$CLAUDE_FROM" +%s)
say "supervisor up (pid $$)"
tick=0
while true; do
  if ! pgrep -f auto_tick.sh > /dev/null; then
    say "starting auto_tick.sh"
    nohup scripts/auto_tick.sh > /dev/null 2>&1 &
  fi
  if ! running codex && ! finished codex; then start codex; fi
  if [ "$(date +%s)" -ge "$from" ] && [ $((tick % 3)) -eq 0 ] && ! finished claude; then
    week=$(claude_week)
    if [ -z "$week" ]; then
      say "Claude usage unreadable; Claude grid left as it is"
    elif [ "$week" -ge "$CLAUDE_MAX" ] && running claude; then
      say "Claude week at $week%: stopping the Claude grid"
      for pid in $(pgrep -f 'run_grid.py --backend claude'); do killtree "$pid"; done
    elif [ "$week" -lt "$CLAUDE_MAX" ] && ! running claude; then
      say "Claude week at $week%"
      start claude
    fi
  fi
  tick=$((tick + 1))
  sleep 600
done
