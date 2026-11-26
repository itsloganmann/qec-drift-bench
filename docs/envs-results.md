# Data-out tasks: agent results and the task selection (2026-11-26)

Two data-out tasks ship here, `readout_drift` and `pulse_wrong_model`, both on the hard tier.
They are the tasks where the best frontier agent passes under 0.75 of the instances
(scripts/select_tasks.py). Two more were scored the same way and do not ship.

## The held-out pilot

| task (hard tier) | part of the device | best known method | Opus 5.5 | Sonnet 5.5 | decision |
|---|---|---|---|---|---|
| readout_drift | dispersive readout, IQ shots in 8 batches | 0.65 | 0.56 [0.48, 0.63] | 0.55 | ships |
| pulse_wrong_model | 6 ns X gate under a wrong drive model | 0.61 | 0.62 | 0.65 [0.60, 0.69] | ships |
| flux_distortion | flux line of a tunable transmon | 0.66 | 0.77 [0.73, 0.81] | 0.77 | not here |
| qec_drift_d3 | d = 3 surface code, weak faults and switching TLS | 0.67 | 0.78 [0.71, 0.84] | 0.46 | not here |

Each cell is the pass rate under `awareness.passed`, per instance, on the 5 paper seeds
(`envs/config.json`), averaged over 3 rollouts. The brackets are a 95% bootstrap interval for
the best model on each task, with seeds resampled together with all of their instances. "Best
known method" is the task's `eval/_reference.py`, the strongest method we know that trusts the model TASK.md
states. The trivial answer ("nothing changed") scores 0.50 on every task.

- readout_drift: the best agent is 9 points under the reference and 19 under the bar.
- pulse_wrong_model: the best agent (Sonnet, 0.65) is 4 points over the reference and 10 under
  the bar. Opus matches the reference.
- flux_distortion: both models pass 0.77. The interval spans the bar, so the task stays out.
  A solver that tests the fit and refits a general filter (no example of the unlisted change)
  passes 0.84, so the task has room, but an agent already reaches the bar.
- qec_drift_d3: Opus passes 0.78, and its interval spans the bar. It also overlaps this
  repository's own d = 3 tasks, so it is not offered here in any case.

## What "held out" means

The hard tier adds a change to the device that TASK.md does not describe. The answer for it is
`diagnosis["other"] = true`. In this pilot, the kit's `dev_data/` left out every public instance
with such a change (`agent/envs_kit.py`, `public_data`). The scored seeds still hold them. An
agent has to notice that the stated model is broken without having seen an example of the
break. Each hard TASK.md says this in its "Hard tier" section, and the kit's PROMPT.md says it
again.

An earlier pilot did not hold them out, and its numbers mean something else:

| task (hard tier) | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|
| pulse_wrong_model | 0.96 | 0.78 | 0.63 |
| readout_drift | 0.76 | 0.63 | 0.42 |

The QEC runs of that pilot are being regraded under its new rubric, so they are left out. With
examples in the dev data, finished agents matched the "told the form" ceiling on the
unlisted change. One Opus pulse solution fitted four extra parameters and flagged "other" when
one of them explained the DRAG-check data much better; the unlisted change was among them. That
pilot measured "find a change seen in the dev data". The held-out pilot measures "find a change
never described". Holding the examples out moved Opus on pulse from 0.96 to 0.62 and on readout
from 0.76 to 0.56.

## How the runs were made

- Claude Code headless (`claude -p`, `acceptEdits`, file tools plus `python`, `ls`, `head` and
  `wc`, no web, no subagents), on a subscription, in a cloud container. A private mount
  namespace hid the task's grader and its source from the agent. Agent
  commands ran as a separate user with no network.
- 45 minutes per episode. No held-out episode reached it: the longest took 27 minutes.
- 3 rollouts per model and task, 24 episodes in all. Haiku 5.5 was not run in this pilot.
- These runs used the original benchmark's pilot driver, not this repository's
  `agent/envs_run.py`, which came after them. The kit is the same, with one difference: the pulse
  dev data came from the standard tier's public seed (0) built on the hard tier, while
  `envs_kit.py` uses the hard tier's own public seed, as `evaluate.py --tier hard` does.
- No prediction was written down before these runs (AGENTS.md rule 4). The tasks' designs were
  iterated on the public set before the paper seeds were scored. The prediction for the next
  run goes in each task's NOTES.md before it starts.

## Reproduce

```bash
uv run python -m qec_drift.agent.envs_grade --references          # best known method, trivial
uv run python scripts/envs_legitimacy.py                          # lazy, leak, ablation checks
uv run python -m qec_drift.agent.envs_run --backend claude-code --model claude-opus-5-5 \
    --arm opus_5_5_cc --rollouts 3
uv run python -m qec_drift.agent.envs_grade data/envs_hard/opus_5_5_cc.parquet
uv run python scripts/select_tasks.py                             # docs/envs-selection.md
```

docs/envs-selection.md reads the pilot from data/envs_hard/pilot_heldout_2026-11-26.csv, one row
per rollout. Each row is `awareness.passed` per instance on the pilot's own grader reports, with
the readers of `agent/envs_grade.py`. Arms run with `envs_run` join that table.
