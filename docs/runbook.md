# Runbook

Every stage as a command. Python runs through `uv run`. API keys come from the environment
(`export ANTHROPIC_API_KEY=...   # only the API harness needs it`).

## 1. References for a task set (CPU)

```bash
uv run python -m qec_drift.agent.decoder_task data/agent_hard --set hard --workers 4
```

Writes `references.json` with, per task, the logical error rate of nominal matching (plain and
correlated), the oracle (plain and correlated, per regime when the noise is not stationary),
the stale correlated fit, the pij refit on the deploy shots, and the window method on telegraph
tasks. Sets: `tier1`, `tier2`, `hard`, `nonstationary`. About 2 to 4 minutes per task at d = 5
with 300,000 test shots.

## 2. One arm (API)

```bash
uv run python -m qec_drift.agent.decoder_run --model claude-sonnet-5-5 --effort high \
    --arm sonnet_5_5_high --max-usd 24 --max-usd-episode 4 --set hard --awareness \
    --tasks d5-none,d5-none-dbq30-s1 --out data/agent_hard
```

`--awareness` adds the diagnosis fields to `submit` and the Brier, diagnosis and pass columns to
the table. `--tasks` takes names from any set. The parquet is written after every batch of
three episodes; the trajectories go to `trajectories/<out>/decoder_<arm>.jsonl.gz`. The run
ends with the failure-mode adapter.

## 3. The launch scripts (references, gate, arms)

```bash
scripts/run_hard.sh "$PWD" 24             # hard set: references, gate, Sonnet
scripts/run_hard_opus.sh "$PWD" 28        # Opus on eight hard tasks, after Sonnet
scripts/run_nonstationary.sh "$PWD" 18    # non-stationary set: references, gate, Sonnet, Opus
```

Each script checks free memory, computes the references, prints the gate table (true over stale
ratio, stale g, pij g, the baseline's drift gap) and refuses to spend if fewer than 10 tasks
survive. The gate keeps a drift task when its true model is at least 20% better than the stale
fit.

## 4. Failure modes and behavioural rescoring

```bash
uv run python -m qec_drift.scoring.failure_modes_decoder data/agent_hard/sonnet_5_5_high.parquet
uv run python scripts/rescore_agreement.py data/agent_hard/sonnet_5_5_high.parquet
```

The adapter writes `<arm>_failure_modes.parquet` with one leaf per episode (`no_decoder`,
`unscored`, `worse_than_plain`, `nominal_plain`, `nominal_correlated`, `fitted_plain`,
`fitted_correlated`). The rescoring script reruns stored decoders on the test shots and adds the
agreement columns to runs made before the harness recorded them.

## 5. Tests

```bash
uv run pytest
uv run ruff check src tests scripts
```

The suite runs scripted episodes through the real sandbox with small shot counts; no API key is
needed.

## 6. Data-out tasks (envs/)

```bash
uv run python -m qec_drift.agent.envs_grade --references        # trivial and reference
uv run python -m qec_drift.agent.envs_run --backend claude-code --model claude-opus-5-5 \
    --arm opus_5_5_cc --rollouts 3                                # episodes, on a subscription
uv run python -m qec_drift.agent.envs_grade data/envs_hard/opus_5_5_cc.parquet
```

`envs_run` builds each task's kit (`agent/envs_kit.py`), runs one episode per task and rollout
on the Claude Code or Codex scaffold, and saves each `solution.py` under
`data/envs_hard/solutions/`. `envs_grade` runs each task's own `evaluate.py` on the public seed
and the paper seeds (`envs/config.json`), applies the pass rule per instance, writes the pass
rate and native score into the arm table, and ends with the failure modes
(`scoring/failure_modes_envs.py`). Grading runs agent code through the task's
`eval/_isolate.py`, not under `sandbox-exec`, so grade in a container or a throwaway VM. About
2 minutes per seed per solution on one core.

Before a task counts, and after any change to it:

```bash
uv run python scripts/envs_legitimacy.py     # lazy, leak and data-ablation checks
uv run python scripts/select_tasks.py        # keep a task if the best agent passes under 75%
```

They write [envs-legitimacy.md](envs-legitimacy.md) and [envs-selection.md](envs-selection.md).
Retired tasks are in [envs-results.md](envs-results.md).

## Budget notes

A Sonnet 5.5 high episode costs $0.2 to $2.2; an Opus 5.5 medium episode $0.6 to $1.9. Every arm
takes `--max-usd` and `--max-usd-episode`; the episode cap stops a conversation once its
estimated cost passes it, and the run stops before the next batch once the arm cap is passed.
