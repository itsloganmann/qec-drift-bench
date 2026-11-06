#!/bin/bash
# Keep the v2 grid going with no Claude session open. Every 10 minutes:
# - restart scripts/auto_tick.sh (the hourly refresh) if it is not running.
# Every 30 minutes, read both subscriptions' usage (scripts/usage.py) and gate the grids:
# - the Codex grid runs while the Codex week is below CODEX_MAX percent (100: the window reads
#   exhausted, and every episode then ends in "Throttled: gave up");
# - the Claude grid runs from CLAUDE_FROM on and while the Claude week is below CLAUDE_MAX
#   percent: Logan keeps the last 10% for himself.
# Above its cap, a grid and its episodes are stopped (found by the scaffold's own command line,
# never by a model name) and start again after the weekly reset. A grid that has finished
# ("exit 0" in its log) is left alone.
# Start it outside any session, so that closing Claude does not stop it:
#   scripts/supervise.sh --detach        (log: data/agent_launch2/supervise.out)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
LOG=data/agent_launch2/supervise.out
CLAUDE_FROM="2026-11-07 01:05"
CLAUDE_MAX=90
CODEX_MAX=100

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
stop_grid() {
  local pid
  for pid in $(pgrep -f "run_grid.py --backend $1"); do killtree "$pid"; done
}
# gate <scaffold> <week percent, or empty when unreadable> <cap>
gate() {
  if finished "$1"; then return; fi
  if [ -z "$2" ]; then
    say "$1 usage unreadable; $1 grid left as it is"
  elif [ "$2" -ge "$3" ] && running "$1"; then
    say "$1 week at $2%: stopping the $1 grid"
    stop_grid "$1"
  elif [ "$2" -lt "$3" ] && ! running "$1"; then
    say "$1 week at $2%"
    start "$1"
  fi
}

from=$(date -j -f '%Y-%m-%d %H:%M' "$CLAUDE_FROM" +%s)
say "supervisor up (pid $$)"
tick=0
while true; do
  if ! pgrep -f auto_tick.sh > /dev/null; then
    say "starting auto_tick.sh"
    nohup scripts/auto_tick.sh > /dev/null 2>&1 &
  fi
  if [ $((tick % 3)) -eq 0 ]; then
    usage=$(uv run python scripts/usage.py)
    gate codex "$(sed -n 's/.*codex [a-z]* weekly \([0-9]*\)%.*/\1/p' <<< "$usage")" "$CODEX_MAX"
    if [ "$(date +%s)" -ge "$from" ]; then
      gate claude "$(sed -n 's/.*claude weekly all \([0-9]*\)%.*/\1/p' <<< "$usage")" "$CLAUDE_MAX"
    fi
  fi
  tick=$((tick + 1))
  sleep 600
done
