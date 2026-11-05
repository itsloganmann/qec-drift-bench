#!/bin/bash
# Launch set: references with the oracle, the window method and the honest adaptive decoder,
# then two gates, then (only with --run) one Sonnet arm and one Opus arm on the survivors.
# Usage: run_launch.sh <repo> [--run] [sonnet_cap] [opus_cap]
set -euo pipefail
repo="$1"
run=0
if [ "${2:-}" = "--run" ]; then run=1; shift; fi
sonnet_cap="${2:-20}"
opus_cap="${3:-20}"
out="$repo/data/agent_launch"
cd "$repo"
mkdir -p "$out"
free=$(memory_pressure -Q | awk '/percentage/ {print $NF}' | tr -d '%')
echo "memory free: ${free}%"
if [ "${free:-0}" -lt 20 ]; then echo "refusing: memory below 20% free"; exit 2; fi
if [ ! -s "$out/references.json" ]; then
  uv run python -m qec_drift.agent.decoder_task "$out" --set launch --workers 3 \
    2>&1 | tee "$out/references.log"
fi
tasks=$(uv run python - "$out/references.json" <<'PY'
import json, sys
refs = json.load(open(sys.argv[1]))
keep = []
hdr = f"{'task':30s} {'true/stale':>10s} {'stale_g':>8s} {'pij_drift':>9s} {'window_drift':>12s} {'adaptive_drift':>14s}"
print(hdr, file=sys.stderr)
for name, r in refs.items():
    top = r["nominal"] - r["true_corr"]
    g = lambda x: (r["nominal"] - x) / top if top > 0 else float("nan")
    if "stale_corr" not in r:
        keep.append(name)
        print(f"{name:30s} {'adequate':>10s} {'':>8s} {'':>9s} {'':>12s} {g(r['pij_corr']):14.2f}  (pij g)", file=sys.stderr)
        continue
    span = r["stale_corr"] - r["true_corr"]
    dg = lambda x: (r["stale_corr"] - x) / span if span > 0 else float("nan")
    ratio = r["true_corr"] / r["stale_corr"]
    honest = dg(r["adaptive_corr"]) if "adaptive_corr" in r else float("nan")
    ok = ratio <= 0.80 and honest >= 0.5
    why = "keep" if ok else ("drop: no gap" if ratio > 0.80 else "drop: no honest method")
    print(f"{name:30s} {ratio:10.2f} {g(r['stale_corr']):8.2f} {dg(r['pij_corr']):9.2f} "
          f"{dg(r.get('window_corr', float('nan'))):12.2f} {honest:14.2f} {why}", file=sys.stderr)
    if ok:
        keep.append(name)
print(",".join(keep))
PY
)
n=$(echo "$tasks" | tr ',' '\n' | grep -c .)
echo "gate kept $n tasks: $tasks"
if [ "$n" -lt 10 ]; then echo "refusing: fewer than 10 tasks survive the gates"; exit 3; fi
if [ "$run" -ne 1 ]; then echo "references and gates only; pass --run to spend"; exit 0; fi
uv run python -m qec_drift.agent.decoder_run --model claude-sonnet-5-5 --effort high \
  --arm sonnet_5_5_high --max-usd "$sonnet_cap" --awareness --set launch --tasks "$tasks" --out "$out" \
  2>&1 | tee "$out/sonnet_5_5_high.log" | tail -40
echo "done sonnet"
free=$(memory_pressure -Q | awk '/percentage/ {print $NF}' | tr -d '%')
if [ "${free:-0}" -lt 20 ]; then echo "refusing opus: memory below 20% free"; exit 2; fi
uv run python -m qec_drift.agent.decoder_run --model claude-opus-5-5 --effort medium \
  --arm opus_5_5_medium --max-usd "$opus_cap" --awareness --set launch --tasks "$tasks" --out "$out" \
  2>&1 | tee "$out/opus_5_5_medium.log" | tail -40
echo "done opus"
