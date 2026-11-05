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

## Budget notes

A Sonnet 5.5 high episode costs $0.2 to $2.2; an Opus 5.5 medium episode $0.6 to $1.9. Every arm
takes `--max-usd` and `--max-usd-episode`; the episode cap stops a conversation once its
estimated cost passes it, and the run stops before the next batch once the arm cap is passed.
