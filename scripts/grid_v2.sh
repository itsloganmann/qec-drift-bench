#!/bin/bash
# Run (or resume) one scaffold's grid on the v2 core. Usage: grid_v2.sh claude|codex
# Arms run in order; run_grid.py skips finished arms and reruns error and over-budget rows.
# The Fable 5.1 arms come first, but Fable has its own weekly limit: with SKIP_FABLE=1 (set by
# scripts/supervise.sh while that week is used up) the Claude grid runs without them and exits
# with SKIPPED, so the supervisor does not count the grid as finished and runs them after the reset.
set -euo pipefail
backend="$1"
conc=2
SKIPPED=75
[ "$backend" = codex ] && conc=4  # 2026-11-05: as many OpenAI arms as possible by the email
cd "$(dirname "$0")/.."
if [ "$backend" = claude ]; then
  arms="claude-fable-5-1:max,claude-opus-5-5:max,claude-sonnet-5-5:max,claude-haiku-5-5:max,claude-opus-4-8:max,claude-sonnet-4-6:max,claude-haiku-4-5:max"
  for e in low medium high xhigh; do arms+=",claude-haiku-4-5:$e,claude-haiku-5-5:$e"; done
  for e in low medium high xhigh; do arms+=",claude-fable-5-1:$e"; done
  for e in low medium high xhigh; do arms+=",claude-sonnet-5-5:$e,claude-sonnet-4-6:$e"; done
  for e in low medium high xhigh; do arms+=",claude-opus-5-5:$e,claude-opus-4-8:$e"; done
  if [ "${SKIP_FABLE:-0}" = 1 ]; then
    arms=$(tr , '\n' <<< "$arms" | grep -v '^claude-fable-' | paste -sd , -)
  fi
else
  arms="gpt-6-astra:max,gpt-5.6-luna:low,gpt-5.6-sol:max,gpt-5.6-terra:max,gpt-5.6-luna:max"
  arms+=",gpt-6-astra:ultra,gpt-5.6-sol:ultra,gpt-5.6-terra:ultra"
  for e in xhigh high medium; do arms+=",gpt-6-astra:$e,gpt-5.6-sol:$e,gpt-5.6-terra:$e,gpt-5.6-luna:$e"; done
  arms+=",gpt-6-astra:low,gpt-5.6-sol:low,gpt-5.6-terra:low"
fi
uv run python scripts/run_grid.py --backend "$backend" --set launch2core --out data/agent_launch2 \
  --core --arms "$arms" --concurrency "$conc" >> "data/agent_launch2/grid_$backend.out" 2>&1
if [ "$backend" = claude ] && [ "${SKIP_FABLE:-0}" = 1 ]; then
  exit "$SKIPPED"  # the Fable arms are still to run
fi
