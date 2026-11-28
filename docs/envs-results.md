# Data-out tasks: agent results and the task selection (2026-11-26)

One data-out task ships here, `readout_drift` on the hard tier. It is the task where the best
frontier agent passes under 0.75 of the instances (scripts/select_tasks.py). Three more were
scored the same way and do not ship.

## The held-out pilot

| task (hard tier) | best known method | Opus 5.5 | Sonnet 5.5 | Opus 5.5 xhigh | Fable 5.2 xhigh | decision |
|---|---|---|---|---|---|---|
| readout_drift | 0.65 | 0.56 | 0.55 | 0.42 | 0.64 (1 rollout) | ships |
| pulse_wrong_model | 0.61 | 0.62 | 0.65 | 0.62 | 0.87 [0.82, 0.92] | not here |
| flux_distortion | 0.66 | 0.77 [0.73, 0.81] | 0.77 | not run | not run | not here |
| qec_drift_d3 | 0.67 | 0.78 [0.71, 0.84] | 0.46 | not run | not run | not here |

Each cell is the pass rate under `awareness.passed`, per instance, on the 5 paper seeds
(`envs/config.json`), averaged over the rollouts: 3 at default effort, 3 for Opus at xhigh, and
2 for Fable at xhigh unless the cell says otherwise. The brackets are a 95% bootstrap interval
for the best model on a task that misses the bar, with seeds resampled together with all of
their instances. "Best known method" is the task's `eval/_reference.py`, the strongest method we
know that trusts the model TASK.md states. The trivial answer ("nothing changed") scores 0.50
on every task.

- readout_drift: the best agent (Fable at xhigh, 0.64) is 1 point under the reference and 11
  under the bar. Fable has one rollout here, so this cell is the least certain one.
- pulse_wrong_model: at default effort the best agent passes 0.65. Fable at xhigh passes 0.87.
  It flags the unlisted change on 55% of the instances that hold only that change, where Opus
  and Sonnet flag none. The task is out.
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
- 3 rollouts per model and task at default effort, 24 episodes in all. Haiku 5.5 was not run
  in this pilot. A second batch ran Opus 5.5 and Fable 5.2 at xhigh effort on the same kits and
  sandbox. Evals were paused before every Fable rollout finished.
- These runs used the original benchmark's pilot driver, not this repository's
  `agent/envs_run.py`, which came after them. The readout kit is the same.
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

docs/envs-selection.md reads the pilot from data/envs_hard/pilot_heldout_2026-11-26.csv and
pilot_heldout_xhigh_2026-11-26.csv, one row per rollout. Each row is `awareness.passed` per
instance on the pilot's own grader reports, with the readers of `agent/envs_grade.py`.
Arms run with `envs_run` join that table.
