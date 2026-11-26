# Data-out tasks: results and retired tasks (2026-11-26)

Three earlier data-out tasks do not ship here: frontier agents pass each of them at 0.75 or more,
on both tiers. Only tasks below that bar count (scripts/select_tasks.py).

| task (hard tier) | part of the device | best known method | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 | decision |
|---|---|---|---|---|---|---|
| pulse_wrong_model | 6 ns X gate under a wrong drive model | 0.61 | 0.96 | 0.78 | 0.63 | retired |
| qec_drift_d3 | d = 3 surface code, weak faults and switching TLS | 0.67 | 0.75 | 0.80 | 0.65 | retired |
| readout_drift | dispersive readout, IQ shots in 8 batches | 0.65 | 0.76 | 0.58 | 0.42 | retired |

Each cell is the pass rate under `awareness.passed`, per instance, on 5 paper seeds, averaged
over 3 rollouts. On the standard tiers, Opus 5.5 passed 0.95 to 0.99 of the instances.

## How the runs were made

- Claude Code headless (`claude -p`, `acceptEdits`, file tools and `python` only, no web), on a
  subscription, 45 minutes per episode, 3 episodes at a time on one laptop. Not this
  repository's runner: `agent/envs_run.py` came after these runs.
- Opus 5.5 reached the 45-minute limit in all 9 of its episodes. Whatever `solution.py` held at
  that point was graded. In one QEC and one readout rollout it held only the starter, which
  scores at the floor. Both exclusions stand with those rollouts counted. Without them, Opus
  passes about 0.88 on both.
- The first two rounds ran beside processes left over from timed-out episodes, which slowed
  the laptop. That can only have lowered scores.
- A scan of all 27 transcripts found no reads of a grader, of hidden data or of the network. One
  Opus readout episode tried to list the folders above its own and read the git log; the run's
  tool permissions refused both. One Sonnet QEC episode wrote scratch files next to its own folder.
- No prediction was written before these runs (AGENTS.md rule 4). The prediction for the next
  task goes in its NOTES.md before its first agent run.

## What it means

The hard tiers add a change that TASK.md does not describe, and the strongest known method that
trusts the stated model passes about 0.6 of them. The best agents pass 0.76 to 0.96. But the
kit's dev_data held public instances with that change in them, so an agent could see examples
of it before the secret seeds. One Opus pulse solution (rollout 1) fits four extra parameters
and flags "other" when one of them explains the DRAG-check data much better; the unlisted
change is among them. These runs therefore measure "find a change seen in the dev data", not
"find a change never described". A re-run with every out-of-model instance left out of dev_data
is under way, and this note will carry its numbers.
