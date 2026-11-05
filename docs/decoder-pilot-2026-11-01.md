# Decoder-agent pilot, 2026-11-01

Plan and predictions: `docs/archive/plan-decoder-agent.md`. Three Claude arms, six tasks each, one
episode per task. The harness that ran the pilot had a 24-turn cap and a 200 KB limit on
`decoder.py`. Both bound the result (see "Harness defects"). Cost $17.62 in all: Haiku 5.5
medium $0.28, Sonnet 5.5 high $5.84, Opus 5.5 medium $11.50 (cap $25).

## Result in short

1. **When Sonnet or Opus finished a task, it closed 0.90 to 0.99 of the gap.** Each fitted a
   detector error model from the training shots and turned on correlated matching. That is
   the hard step the plan asked about: a score above 0.7 needs the unmodelled noise learned
   from the shots. Three such episodes finished: Sonnet d5-hetero 0.930, Opus d5-hetero 0.895,
   Opus d5-crosstalk 0.992. A fourth, Sonnet d7-both, had a fitted correlated decoder on disk
   that the harness refused for its size. Scored after the run with the same test shots, it
   closes 0.806.
2. **Haiku stays under 0.25.** Its three submissions score 0.156, 0.104 and 0.000 (plain or
   lightly refitted matching, no correlations). The two decoders the harness refused score
   0.043 and 0.242 after the run.
3. **Completion, not technique, was the bottleneck.** 9 of the 12 Sonnet and Opus episodes
   hit the 24-turn cap while still fitting: 24 to 26 `run_python` calls each, 0 to 2
   timeouts, no submit, and a last output that is a fit in progress.
4. The run logs print "median gap closed 0.930" and "0.944". Those medians are over submitted
   episodes only (1 of 6 and 2 of 6). Do not quote them.

## Episodes

g is the gap closed on the 300,000 test shots. "post hoc" means the decoder on disk was scored
after the run with the same scorer and test shots (not a submission). Leaf is the failure-mode
leaf from `scoring/failure_modes_decoder.py`.

| Arm | Task | Outcome | Turns | g | Leaf | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| Haiku 5.5 medium | d5-hetero | no_submit | 24 | | no_decoder | $0.06 |
| | d5-crosstalk | submitted | 13 | 0.156 | fitted_plain | $0.02 |
| | d5-both | submitted | 12 | 0.104 | fitted_plain | $0.02 |
| | d7-hetero | submitted | 19 | 0.000 | nominal_plain | $0.05 |
| | d7-crosstalk | failed_submit | 22 | 0.043 post hoc | unscored (305 KB) | $0.06 |
| | d7-both | no_submit | 24 | 0.242 post hoc | unscored (315 KB) | $0.07 |
| Sonnet 5.5 high | d5-hetero | submitted | 18 | 0.930 | fitted_correlated | $0.60 |
| | d5-crosstalk | no_submit | 24 | | no_decoder | $1.09 |
| | d5-both | no_submit | 24 | | no_decoder | $1.17 |
| | d7-hetero | no_submit | 24 | | no_decoder | $0.97 |
| | d7-crosstalk | no_submit | 24 | | no_decoder | $1.14 |
| | d7-both | no_submit | 24 | 0.806 post hoc | unscored (298 KB) | $0.86 |
| Opus 5.5 medium | d5-hetero | submitted | 16 | 0.895 | fitted_correlated | $0.87 |
| | d5-crosstalk | submitted | 24 | 0.992 | fitted_correlated | $2.38 |
| | d5-both | no_submit | 24 | | no_decoder | $2.26 |
| | d7-hetero | no_submit | 24 | | no_decoder | $1.72 |
| | d7-crosstalk | no_submit | 24 | | no_decoder | $2.04 |
| | d7-both | no_submit | 24 | | no_decoder | $2.23 |

Flags: all 18 episodes read `val.npz`, and all 18 ran code with estimation words. Haiku
d5-both is a 31-line decoder that keeps the nominal model's structure and replaces every
error probability with its own fitted number, without correlations; the gain is 0.104.

## Predictions against results

Written in the plan before any episode.

1. Median g: Haiku below 0.25, yes (0.104). Sonnet 0.25 to 0.60, no: 0.930 on its one finished
   task and 0.806 on the refused one. Opus 0.40 to 0.80, no: 0.895 and 0.992.
2. Correlated matching in at least half of Opus submissions (2 of 2) and at most a quarter of
   Haiku's (0 of 3): yes.
3. No arm estimates the noise model from the training shots in more than a third of its
   episodes: wrong. All 18 episodes ran estimation code. Every Sonnet and Opus decoder that
   exists carries a fitted model (4 of 4); Haiku 2 of 5.
4. At least one arm submits a decoder worse than plain matching in 10% or more of its
   episodes: no. The lowest score is exactly 0.000 (Haiku d7-hetero submitted the nominal
   matcher after its refits did not beat it on validation).
5. Half or fewer of the episodes score on validation before submit: no, 18 of 18 did.

## Harness defects found

Fixed after the pilot in `src/qec_drift/agent/decoder_run.py`, with tests in
`tests/test_decoder_agent.py`.

1. A 200 KB cap on `decoder.py` with a wrong message ("missing, empty or not a regular file").
   A fitted d = 7 model inlined as text is about 300 KB. It cost Haiku d7-crosstalk (three
   refused submits), Haiku d7-both (two) and Sonnet d7-both (refused at the end-of-turns
   score). The limit is now 5 MB and the message names the size.
2. 24 turns ended 9 of 12 Sonnet and Opus episodes mid-fit. The cap is now 40 turns with a
   per-episode cost cap (`--max-usd-episode`, default $4) so the longer loop cannot run away.
3. The end-of-turns score ran only on the turn-cap exit and kept no reason. Every exit without
   a scored submit now scores what exists, and the row keeps `stop`, `score_error`,
   `n_run_python`, `n_timeouts` and `decoder_bytes`.
4. One to three turns per episode went to the discovery that `run_python` keeps no state
   between calls ("Not persistent state; rerun all together"). The tool description now says
   that each call starts a new process.
5. The family ran without a failure-mode adapter (AGENTS.md rule 11). The adapter and its
   leaves are in `docs/failure-taxonomy.md`; the runner calls it at the end.

## Reading against the go and no-go

The pilot as run does not settle the go and no-go: with 1 of 6 and 2 of 6 completions the arms
cannot be compared on median g. Three things are clear: the arms differ (Haiku under 0.25
against 0.80 to 0.99), at least three techniques appear (nominal plain, fitted plain, fitted
correlated), and on d = 5 the two strong arms are at or above the 0.85 saturation line.

Next, in order:

1. Rerun the 12 unfinished episodes on the fixed harness (same tasks, 40 turns, $4 per
   episode, about $25 in all). Predictions, written before the rerun: (i) Sonnet and Opus
   submit in at least 4 of their 5 and 4 tasks; (ii) their median g over all six tasks is 0.80
   or more, with d7-both the lowest; (iii) Haiku's median over six stays below 0.30 and at most
   one Haiku decoder uses correlations; (iv) no decoder scores below 0; (v) every Sonnet and
   Opus decoder carries a fitted model.
2. If (ii) holds, the task is saturated on noise that a detector error model can express, as
   the plan's flag says. The next family moves the noise outside the model. Candidate: drift.
   The training shots come from one noise level and the test shots from a later, shifted one.
   `decode(det)` receives all test shots at once, so a decoder can refit the model from the
   test detectors without labels; the oracle (g = 1) is correlated matching with the test-time
   true model. The question becomes whether the agent notices that its training-time fit is
   stale. Pranav's input is needed for a realistic drift model and for the leakage case, which
   Stim does not simulate natively.
3. If (ii) fails on d = 7 or on the 'both' tasks, keep this family and grow it: more seeds per
   task, Opus high, and the time per fit as a measured cost.

Anthropic spend to date is about $94 of the $200 month (earlier runs $73, the accept-or-escalate
pilot $3.19, this pilot $17.62).

## Reproduce

```bash
export ANTHROPIC_API_KEY=...   # only the API harness needs it
uv run python -m qec_drift.agent.decoder_task data/agent_decoder   # references.json
uv run python -m qec_drift.agent.decoder_run --model claude-opus-5-5 --effort medium \
    --arm opus_5_5_medium --max-usd 14 --max-usd-episode 4 --concurrency 3
uv run python -m qec_drift.scoring.failure_modes_decoder data/agent_decoder/opus_5_5_medium.parquet
```

Trajectories: `trajectories/decoder_<arm>.jsonl.gz`. Work folders with each agent's files and
its `decoder.py`: `data/agent_decoder/work/<arm>/<task>/`.

## Rerun of the 12 unfinished episodes, 2026-11-01 (fixed harness, 40 turns, $4 per episode)

Arms `haiku_5_5_medium_r2`, `sonnet_5_5_high_r2`, `opus_5_5_medium_r2`. The prompt did not yet
state the tool-call budget (added afterwards, for tier 2 on). Cost $24.73 in all.

| Arm | Task | Outcome | Stop | Turns | g | Leaf | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Haiku 5.5 medium | d5-hetero | submitted | submitted | 11 | 0.343 | fitted_plain | $0.02 |
| | d7-crosstalk | submitted | submitted | 12 | 0.260 | fitted_plain | $0.02 |
| | d7-both | submitted | submitted | 15 | 0.431 | fitted_plain | $0.03 |
| Sonnet 5.5 high | d5-crosstalk | no_submit | turns | 40 | | no_decoder | $2.86 |
| | d5-both | no_submit | turns | 40 | | no_decoder | $1.73 |
| | d7-hetero | submitted | submitted | 25 | 0.612 | fitted_correlated | $1.18 |
| | d7-crosstalk | no_submit | turns | 40 | | no_decoder | $1.78 |
| | d7-both | no_submit | turns | 40 | | no_decoder | $2.47 |
| Opus 5.5 medium | d5-both | no_submit | episode_budget | 37 | | no_decoder | $4.23 |
| | d7-hetero | submitted | submitted | 29 | 0.957 | fitted_correlated | $3.05 |
| | d7-crosstalk | no_submit | episode_budget | 32 | | no_decoder | $4.06 |
| | d7-both | submitted | submitted | 30 | 0.904 | fitted_correlated | $3.29 |

Haiku's d7-both decoder builds its matching graph by hand from a list of fitted probabilities
(`add_edge`), and its d7-crosstalk decoder rebuilds the circuit instruction by instruction with
its own noise; both are fitted models without correlations. Opus's two decoders are 351 and 362
bytes: they load a `fitted.dem` or `final.dem` from the work folder and turn on correlations, so
the fitted model lives in a file, not in the source. The adapter's fitted rule was widened for
both patterns after this run.

### Six tasks per arm, pilot and rerun together

Best delivered result per task; "none" means no decoder in either run.

| Arm | d5-hetero | d5-crosstalk | d5-both | d7-hetero | d7-crosstalk | d7-both | Delivered | Median g (none = 0) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Haiku 5.5 medium | 0.343 | 0.156 | 0.104 | 0.000 | 0.260 | 0.431 | 6 of 6 | 0.21 |
| Sonnet 5.5 high | 0.930 | none | none | 0.612 | none | 0.806 post hoc | 2 of 6 (3 with the post-hoc score) | 0.31 |
| Opus 5.5 medium | 0.895 | 0.992 | none | 0.957 | none | 0.904 | 4 of 6 | 0.90 |

### What the rerun changed

1. **Delivery within budget is the main failure for the strong arms, and it is not a harness
   limit.** Sonnet wrote no `decoder.py` in 40 turns on 4 of 5 tasks, with 1 or 2 timeouts each;
   its work folders hold fit2 through fit5, a 2.5 GB pickle, a neural attempt. Opus hit the $4 cap
   without a decoder on 2 of 4. Haiku delivered 6 of 6 and never reached 0.5.
2. **When Opus delivers, it is at the ceiling.** 0.90 to 0.99 on four tasks, every one a fitted
   model with correlated matching. d5-both and d7-crosstalk never got a decoder from Opus in
   either run (one pilot episode at 24 turns, one rerun at the $4 cap).
3. **Predictions for the rerun.** (i) Sonnet and Opus submit on at least 4 of 5 and 4: no, 1 of 5
   and 2 of 4. (ii) Median g over six tasks 0.80 or more with d7-both lowest: Opus 0.90 with the
   two misses as zero, and d7-both was not the lowest; Sonnet 0.31. (iii) Haiku median under 0.30
   and at most one Haiku decoder with correlations: yes, 0.21 and none. (iv) No decoder below 0:
   yes. (v) Every Sonnet and Opus decoder carries a fitted model: yes, 6 of 6.
4. **Reading against the go and no-go.** The arms differ, three techniques appear, and the best
   arm sits at the ceiling when it finishes, so tier 1 is saturated in skill for Opus and bounded
   by delivery for Sonnet. The benchmark keeps tier 1 as the floor tier, with two scores reported
   apart: g on delivered decoders, and the delivery rate. The agent was never told its budget in
   these runs; from tier 2 on the prompt states it and the last five tool results count down, so
   the delivery rate under a stated budget is the number to compare.

## Tier 2 design check before spending, 2026-11-01

The first tier 2 build scaled every noise probability by 1.8 at test time. Its references showed
the stale fit decoding as well as the true model (d7-none: stale 0.00814, true 0.00814; d5-both:
stale 0.03458, true 0.03475), because a uniform scale shifts every matching weight by the same
constant. Structural drifts measured at d = 5 with 100,000 shots (true over stale logical error
rate; a value of 1.00 means no gap): readout and reset flips 3x, 0.90 and 0.84 on the none and
hetero bases; 5x, 0.73 and 0.65; a fresh per-qubit draw, 0.75 and 0.82; crosstalk onset, 0.84 on
the none base and 1.00 on the hetero base (instruction grouping made it a no-op there); two-qubit
gate noise 2x, 1.01 and 1.00. Tier 2 uses "meas5" and "requbit". The same check showed that pure
drift is undetectable from calibration shots alone, so every task now ships `deploy.npz`.

