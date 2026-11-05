#!/bin/bash
# Hard drift tier: references with the pij baseline, a gap gate, then one Sonnet arm.
# Usage: run_hard.sh <repo> [max_usd]
set -euo pipefail
repo="$1"
cap="${2:-18}"
out="$repo/data/agent_hard2"
cd "$repo"
mkdir -p "$out"
free=$(memory_pressure -Q | awk '/percentage/ {print $NF}' | tr -d '%')
echo "memory free: ${free}%"
if [ "${free:-0}" -lt 20 ]; then echo "refusing: memory below 20% free"; exit 2; fi
if [ ! -s "$out/references.json" ]; then
  uv run python -m qec_drift.agent.decoder_task "$out" --set nonstationary --workers 3 \
    2>&1 | tee "$out/references.log"
fi
tasks=$(uv run python - "$out/references.json" <<'PY'
import json, sys
refs = json.load(open(sys.argv[1]))
keep = []
hdr = f"{'task':26s} {'true/stale':>10s} {'stale_g':>8s} {'pij_g':>6s} {'pijc_g':>7s} {'pijc_drift':>10s}"
print(hdr, file=sys.stderr)
for name, r in refs.items():
    top = r["nominal"] - r["true_corr"]
    g = lambda x: (r["nominal"] - x) / top if top > 0 else float("nan")
    if "stale_corr" not in r:
        keep.append(name)
        print(f"{name:26s} {'adequate':>10s} {'':>8s} {g(r['pij_plain']):6.2f} {g(r['pij_corr']):7.2f}", file=sys.stderr)
        continue
    ratio = r["true_corr"] / r["stale_corr"]
    span = r["stale_corr"] - r["true_corr"]
    dg = (r["stale_corr"] - r["pij_corr"]) / span if span > 0 else float("nan")
    ok = ratio <= 0.80
    print(f"{name:26s} {ratio:10.2f} {g(r['stale_corr']):8.2f} {g(r['pij_plain']):6.2f} {g(r['pij_corr']):7.2f} {dg:10.2f} {'keep' if ok else 'drop'}", file=sys.stderr)
    if ok:
        keep.append(name)
print(",".join(keep))
PY
)
n=$(echo "$tasks" | tr ',' '\n' | grep -c .)
echo "gate kept $n tasks: $tasks"
if [ "$n" -lt 10 ]; then echo "refusing: fewer than 10 tasks survive the gate"; exit 3; fi
uv run python -m qec_drift.agent.decoder_run --model claude-sonnet-5-5 --effort high \
  --arm sonnet_5_5_high --max-usd "$cap" --awareness --set nonstationary --tasks "$tasks" --out "$out" \
  2>&1 | tee "$out/sonnet_5_5_high.log" | tail -40
echo "done sonnet"
# Opus on two adequate tasks and the first six drift survivors.
opus=$(echo "$tasks" | tr ',' '\n' | awk '/-d/ {d[++nd]=$0; next} {a[++na]=$0} END {o=a[1]","a[2]; for (i=1;i<=6&&i<=nd;i++) o=o","d[i]; print o}')
free=$(memory_pressure -Q | awk '/percentage/ {print $NF}' | tr -d '%')
if [ "${free:-0}" -lt 20 ]; then echo "refusing opus: memory below 20% free"; exit 2; fi
uv run python -m qec_drift.agent.decoder_run --model claude-opus-5-5 --effort medium \
  --arm opus_5_5_medium --max-usd 14 --awareness --set nonstationary --tasks "$opus" --out "$out" \
  2>&1 | tee "$out/opus_5_5_medium.log" | tail -40
echo "done opus"
