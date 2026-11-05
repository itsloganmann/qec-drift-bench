#!/bin/bash
# Opus on eight of the hard tasks the gate kept, after the Sonnet arm has finished.
# Usage: run_hard_opus.sh <repo> [max_usd]
set -euo pipefail
repo="$1"
cap="${2:-28}"
out="$repo/data/agent_hard"
cd "$repo"
while pgrep -f "decoder_run --model claude-sonnet-5-5 .* --out data/agent_hard" >/dev/null; do
  sleep 30
done
free=$(memory_pressure -Q | awk '/percentage/ {print $NF}' | tr -d '%')
echo "memory free: ${free}%"
if [ "${free:-0}" -lt 20 ]; then echo "refusing: memory below 20% free"; exit 2; fi
tasks="d5-none,d7-none,d5-none-dbq30-s1,d5-none-dbq30-s1-n2000,d5-none-dbg40"
tasks="$tasks,d5-none-dbq15+line5-s1,d5-hetero-dmeas5,d7-none-dbq30"
uv run python -m qec_drift.agent.decoder_run --model claude-opus-5-5 --effort medium \
  --arm opus_5_5_medium --max-usd "$cap" --awareness --set hard --tasks "$tasks" --out "$out" \
  2>&1 | tee "$out/opus_5_5_medium.log" | tail -40
echo "done"
