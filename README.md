# QEC-Drift

This is a public snapshot of the benchmark: the tasks, the harness, the scoring, the fairness checks and the results. The per-episode transcripts are not in it, because some agents listed files on the machine that ran them; ask the author for access.

<!-- grid:start -->
## Live results

Pass rate under the relative rule / under the absolute rule (docs/launch2-grid-2026-11-02.md). Arms still running show their done count. Episodes labelled `invalid_run` (the harness failed them; docs/failure-taxonomy.md) are left out. Updated 2026-11-08 00:23 GMT.

### v2 launch set (40 tasks gated; the core is 23)

| model | low | medium | high | xhigh | max | ultra |
|---|---|---|---|---|---|---|
| GPT-5.6-Luna (Codex) | 0% / 0% (core) | 0% / 0% (core) | 0% / 5% (20/23) | 4% / 9% (core) | 13% / 13% (core) |  |
| GPT-5.6-Sol (Codex) | 17% / 17% (core) | 17% / 26% (core) | 35% / 35% (core) | 30% / 30% (core) | 48% / 48% (core) | 30% / 30% (core) |
| GPT-5.6-Terra (Codex) | 0% / 4% (core) | 0% / 0% (core) | 4% / 13% (core) | 9% / 17% (core) | 26% / 26% (core) | 30% / 35% (core) |
| GPT-6-Astra (Codex) | 61% / 65% (core) | 57% / 57% (core) | 57% / 61% (core) | 43% / 48% (core) | 65% / 70% (core) | 61% / 65% (core) |
| Opus 5.5 (Claude Code) |  |  |  |  | 100% / 100% (4/23) |  |

### v1 launch set (21 tasks)

| model | high | max |
|---|---|---|
| Fable 5.1 (Claude Code) |  | 0% / 0% (2/21) |
| GPT-6-Astra (Codex) |  | 67% / 67% (12/21) |
| Sonnet 5.5 (API) | 0% / 25% (12/21) |  |

<!-- grid:end -->

Can an AI agent tell when a quantum chip's noise model is wrong, say what broke, and fix the
error correction?

Every use of a quantum computer waits on fault tolerance, and the error-correction stack is run by
hand: characterize the noise, build the decoder, notice when the chip drifts, do it again. This
benchmark hands an agent the model a lab believes describes its chip, calibration data from before
a change, and fresh data from after it. The agent must diagnose the change and ship a decoder.
Ground truth is physical: Stim and PyMatching on the true noise, with the known methods from the
literature as the baseline on every task.

Status (2026-11-02): the stationary tiers are built and measured, and the launch set (moving
faults: a qubit that switches between good and bad every few hundred shots and moves across the
chip, patches, compounds, a faster switching rate, a small deploy batch) has its first numbers.
Through the Claude Code scaffold, Opus 5.5 passes 24% of launch tasks and Sonnet 5.5 10% under
the relative rule (the agent must recover most of what a competent adaptive decoder recovers);
48% and 14% under the absolute rule. Both models find the fault and fix it as if it were
stationary; an honest adaptive decoder recovers 67% to 97% of the loss on every task.
The claim, scores, tiers, predictions and kill
conditions: `docs/benchmark-spec-2026-11-01.md`. Results and design decisions in order:
`docs/decoder-pilot-2026-11-01.md`, `docs/drift-pilot-2026-11-01.md`. Why this gap and not
another: `docs/benchmark-gap-survey-2026-11-01.md`.

## A task

1. The agent gets `nominal.stim` (the surface-code circuit with the noise the team believes),
   `train.npz` and `val.npz` (labeled shots from the true noise, taken before any change),
   `deploy.npz` (recent detection events, no labels, in the order they were taken), Python with
   numpy, scipy, stim and pymatching, no network, no test labels, and 40 tool calls.
2. It writes `decoder.py` with `decode(det) -> obs_flips` and calls `submit` with its diagnosis:
   `model_adequate`, `confidence`, `scope` (none, local, global), `changed_qubits`, `mechanism`,
   `stationary`, `what_is_wrong`, `evidence`.
3. The harness scores the decoder on 300,000 hidden shots. `gap_closed` is the share of the gap
   from nominal matching to the oracle (correlated matching with the true, per-regime noise) that
   the decoder closes. `gap_drift` is the share of the stale calibration's loss it recovers. The
   diagnosis is correct when the scope and the stationary flag are right and, for a local fault,
   the reported qubits overlap the true ones. A task is **passed** when the diagnosis is correct,
   `gap_closed` is at least 0.5, and on a drift task `gap_drift` is at least 0.5.
4. Every API response is archived as returned (`trajectories/`), and every episode gets one
   failure-mode leaf (`docs/failure-taxonomy.md`).

## Task sets

| set | what changes | tasks |
|---|---|---|
| `tier1` | static mismatch inside the model class: per-qubit rates, crosstalk | 6 |
| `tier2` | readout flips 5x or a fresh per-qubit draw after calibration | 14 |
| `hard` | one qubit or one gate at 15x to 40x, combined faults, a 2,000-shot deploy batch | 30, gate keeps 17 |
| `nonstationary` | a qubit that switches between good and bad every 200 shots or so, fixed or wandering | 22, gate keeps 18 |

A launch script computes every task's references first and refuses to spend if a drift task's
true model is not at least 20% better than the stale fit. The known methods (`decoders/pij.py`,
the pairwise-correlation refit; the window method for telegraph noise) are reported per task, so
the pass rule is reachable by a method in the literature on every task that counts.

## Layout

- `src/qec_drift/agent/`: the harness. `decoder_task.py` (tasks, references, sampling),
  `drift.py` (what changes), `noise.py` (circuit transforms), `awareness.py` (the diagnosis
  report and the pass rule), `decoder_run.py` (the episode loop), `sandbox.py`.
- `src/qec_drift/decoders/`: baseline decoders (the pij refit).
- `src/qec_drift/scoring/`: the failure-mode adapter.
- `src/qec_drift/llm/`: the Anthropic client and pricing.
- `scripts/`: launch scripts with the spend gate, and the behavioural rescoring.
- `trajectories/` (not in this public snapshot): archived API responses per run; `trajectories/archive/` holds the runs of the
  project this benchmark grew out of. `docs/archive/` holds that project's notes.

## Setup and run

```bash
uv sync --all-groups
uv run pytest
export ANTHROPIC_API_KEY=...   # only the API harness needs it
scripts/run_hard.sh "$PWD" 24            # references, gate, Sonnet on the hard set
scripts/run_nonstationary.sh "$PWD" 18   # the same for the non-stationary set, then Opus
uv run python -m qec_drift.scoring.failure_modes_decoder data/agent_hard/sonnet_5_5_high.parquet
```

`docs/runbook.md` has every command. Commits carry no AI attribution; see `AGENTS.md`.
