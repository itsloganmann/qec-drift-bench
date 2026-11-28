# Data-out tasks

The decoder tasks ask the agent for code: it ships `decoder.py`, and the scorer runs that code
on hidden shots. A data-out task asks for data instead. The agent writes
`solve(data) -> dict`, which returns numbers such as a predistortion filter, and the task's own
grader applies those numbers to hidden test data. The agent's code never runs next to the
hidden data. This is one answer to point 1 of
[docs/kaggle-benchmarks-port.md](../docs/kaggle-benchmarks-port.md).

The same question runs through every task: is the model of the device still right? If not,
what changed, and what is the fix? Each answer holds `diagnosis.changed` and the fix, so the
QEC-Drift pass rule (`agent/awareness.py`) applies to each instance
(`agent/envs_grade.py`).

| task | part of the device | what the agent gets | what it returns | instances per seed |
|---|---|---|---|---|
| `readout_drift` | dispersive readout | labelled calibration shots, then a few hundred unlabelled IQ shots in 8 batches | a discriminator (one per batch if you like), the diagnosis | 30 (15 controls) |

Only the hard tier is here. On the standard tiers, Claude Opus 5.5 passed 95% or more of the
instances. A task stays only if the best agent passes under 75% of its hard instances
([docs/envs-results.md](../docs/envs-results.md)).

On the hard tier, the kit's dev data leaves out every instance whose change lies outside the
model TASK.md states (`agent/envs_kit.py`). The scored seeds still hold them. An agent must
notice a broken model without having seen an example of it.

## Layout of a task

```
<task>/
  TASK.md              what the agent reads: story, data, interface, scoring, limits, sources
  evaluate.py          scores a solution and prints one number; --report writes the breakdown
  eval/harness.py      hidden device, truth, baselines, scoring
  eval/rubric.py       the rubric: named, weighted checks, each a script over truth and answer
  eval/_isolate.py     runs solve() in a fresh `python -I` process in an empty temp folder
  eval/_trivial.py     trusts the nominal model and says "no change" (the 0.50 floor)
  eval/_reference.py   the strongest known method that trusts the stated model
  sandbox/solution.py  the starter, which behaves like trivial
  checks/              lazy and leak solutions, listed in checks/expect.json
  NOTES.md             predictions written before measuring, then the measurements
```

## Rules every task keeps

- `data` holds only what a lab engineer would have. No truth, no seed, no rule.
- About half of the instances are controls. A false alarm on a control scores 0, so a constant
  answer cannot beat doing nothing.
- fix = the gap closed between the stale model and the true model on the hidden test data,
  clipped to [0, 1]. Only diagnosis fields that the data can identify are graded.
- The seed reaches the grader on a pipe, never in argv or the environment.
- A hard tier can change the device in a way TASK.md does not describe. The answer for that is
  the kind `"other"`. Only noticing it is graded.
- Every TASK.md ends with a canary line, so a leak into training data can be found.
- Files under 600 lines, numpy and scipy only, the reference's full evaluation under 10 minutes
  on one core.

## Checks before a task counts

- `scripts/envs_legitimacy.py`: every lazy and leak solution in `checks/` scores at most
  trivial + 0.05, the reference on swapped data falls to that bar, and the reference beats it.
- `scripts/select_tasks.py`: the best agent model passes under 75% of the instances, averaged
  over its rollouts. A task at or above that bar leaves (docs/envs-results.md).

## Run it

See [docs/runbook.md](../docs/runbook.md), section 6. Seeds are in [config.json](config.json).
The paper seeds are public, so they are a reproduction set, not a held-out split.

Licence: task text CC BY 4.0, code Apache-2.0.
