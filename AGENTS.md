# Agent rules for QEC-Drift (Python package `qec_drift`)

These rules bind every human and agent contribution.

1. Ground truth is a simulation or a measurement, never a formula from memory. A task's
   references come from Stim and PyMatching on the true noise; a physics claim in the docs cites
   a paper and a locator.
2. Never spend on a task without a gap. The launch scripts compute every reference first and
   refuse to run an arm if a drift task's true model is not at least 20% better than the stale
   fit. Do not lower the gate to make a run go; drop the task.
3. Every task that counts has a known-method baseline (`pij_corr`, `window_corr`) reported next
   to the oracle, so the pass rule is reachable by a method in the literature. A task where no
   known method passes is reported apart, never counted in the headline.
4. Write predictions before a run and read them after. Every results note carries both.
5. Every model run keeps its trajectory and gets a failure-mode analysis. The harness archives
   the exact API response under `trajectories/<output folder>/decoder_<arm>.jsonl.gz` and ends
   with `scoring.failure_modes_decoder.analyze_decoder`. The adapter reads behaviour first
   (`agree_nominal_plain`, `agree_nominal_corr`) and source second.
6. The agent never sees test labels. Scoring runs in a throwaway copy of the agent folder inside
   the sandbox; the harness never follows a link the agent left.
7. Every source file stays under 600 physical lines. Split before you reach the cap.
8. Prose uses short plain sentences. No em dashes. No emoji. Simplified Technical English.
9. Commits carry no AI co-author or "generated with" lines. Attribute humans only.
10. Python runs through `uv run`. Do not `pip install` into the environment.
11. Secrets stay in the environment. Never write an API key or token into the repo or a log.
12. Test the behaviour you change, and run the tests that touch it before you call it done.
