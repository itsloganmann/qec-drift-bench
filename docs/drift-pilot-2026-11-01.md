# Tier 2 drift pilot and the hard tier (2026-11-01)

Spec: `docs/benchmark-spec-2026-11-01.md`. Harness: `docs/decoder-pilot-2026-11-01.md` (tier 1,
harness defects, the tier 2 design check). Data: `data/agent_drift/` (Sonnet and Opus on the
14-task pilot set) and `data/agent_hard/` (the hard set). Trajectories: `trajectories/`.

## Pilot result, Sonnet 5.5 high, 14 tasks, $12.08

The gate passed: on every drift task the true model beats the stale fit by 14% to 44% in
logical error rate (`data/agent_drift/references.log`). Sonnet submitted on 14 of 14.

| group | tasks | median g | g range | reported adequate | Brier |
|---|---|---|---|---|---|
| adequate (none, no drift) | 4 | 0.50 | 0.00 to 1.00 | 4 of 4 | 0.04 to 0.08 |
| drift (meas5, requbit) | 8 | 0.72 | 0.32 to 1.00 | 0 of 8 | 0.001 to 0.006 |
| static hetero replicate | 2 | 0.82 | 0.53 to 1.10 | 0 of 2 | 0.005 to 0.010 |

Failure modes (adapter): fitted_plain 7, nominal_correlated 4, nominal_plain 2,
fitted_correlated 1. On the two adequate d = 7 tasks Sonnet shipped plain nominal matching
(g = 0): the correlated gain was left on the table. On 7 of 14 tasks it refit a model from
`deploy.npz` but decoded with plain matching.

**Awareness is saturated at this drift size.** Every call was right, at 92% to 97% confidence on
the drift tasks: AUROC 1.0. That trips the awareness half of the spec's kill condition (AUROC
above 0.90) while the decoding half (median g above 0.80) does not. The cause is the magnitude:
readout flips at 5x and a fresh per-qubit draw move most detection rates by a factor of 2 to 5,
and `deploy.npz` against `train.npz` shows it in one comparison.

The Opus arm on the pilot set never made an API call: its three episode threads deadlocked in
stim's first numpy conversion (fixed in `decoder_run.warm_up_stim`). It was not relaunched on the
pilot set, which the Sonnet result already shows to be too easy; the remaining budget goes to
Opus on the hard set.

## The hard tier: what changed and why

Model release cards quote pass rates where the frontier sits between 20% and 60%. The pilot
numbers are too high and the awareness number is binary. Three changes (commit after this note):

1. **Local faults on a magnitude ladder** (`agent/drift.py`). One qubit with every error source
   at 3x or 6x ("bq"), one measure qubit with readout flips at 5x or 10x ("br"), one CX pair with
   gate noise at 5x or 10x ("bg"), plus a small global readout drift ("meas2") and crosstalk
   onset ("xt3"). A rate test over the whole batch barely moves for a local fault; the agent has
   to find where the change is. The rungs of a family share the fault position, so they differ
   only in magnitude. 30 candidate tasks, 25 at d = 5 and 5 at d = 7, 5 of them adequate
   (`decoder_task.hard_tasks`). The launch script drops any rung whose true model is not at least
   20% better than the stale fit, so the ladder keeps the lowest magnitude that still leaves a
   decoding gap to measure.
2. **A diagnosis, not a flag** (`agent/awareness.py`). The submit call now carries `scope` (none,
   local, global), `changed_qubits` and `mechanism` (readout, gate, all, crosstalk, none). The
   diagnosis is correct when the scope matches and, for a local fault, the reported qubits
   overlap the true ones with Jaccard at least 0.5. The Brier score stays as the calibration
   number; mechanism accuracy is reported but not gated.
3. **A pass rule.** A task is passed when the diagnosis is correct and the decoder closes at
   least half of the gap to the oracle ceiling (`PASS_GAP = 0.5`). The headline number is the
   pass rate, which is what a card can quote next to its other benchmarks. g and the Brier stay
   as sub-scores.

An expert-pipeline baseline makes the pass rule fair: `decoders/pij.py` refits the nominal DEM
from the unlabeled deploy shots with the pairwise-correlation method (Spitz et al. 2018; the
Google 2021 and 2023 supplements) and decodes with correlated matching. Its g is reported for
every task as `pij_corr`. A task where the known method cannot pass is kept but flagged; a
frontier agent that knows the literature can reach it, and one that does not cannot.

## What the first hard grid showed, and the second grid

The first grid (ladder 3x and 6x on one qubit, 5x and 10x on one measure qubit's readout, 5x
and 10x on one CX pair, readout 2x, crosstalk onset) was scored before any spend. Almost every
rung failed the gate: the true model was within 1% to 11% of the stale fit
(`data/agent_hard/references_grid1.json`). A fault that small is hard to see and does not
matter for decoding, which makes it a detection test, not a decoding task. A second sweep at
d = 5 with 100,000 test shots (true over stale logical error rate; the known method's g in
brackets):

| kind | seed 0 | seed 1 | reading |
|---|---|---|---|
| one qubit, all noise 15x (`bq15`) | 0.86 (1.02) | 0.76 (1.01) | a gap, seed dependent |
| one qubit, all noise 30x (`bq30`) | 0.76 (1.03) | 0.58 (0.88) | a clear gap |
| one measure qubit, readout 20x / 40x (`br`) | 0.94 / 0.91 | 0.95 / 0.95 | no gap even at 40x |
| one CX pair, gate noise 20x / 40x (`bg`) | 0.82 / 0.64 | 0.96 / 0.92 | a gap when the pair sits on a short logical path |
| a readout column 3x / 5x (`line`) | 0.97 / 0.91 | 0.98 / 0.95 | no gap |
| correlated pairs, 50% / 80% of idle noise (`cp`) | 0.96 / 0.93 | 1.01 / 0.94 | no gap |
| readout 3x everywhere (`meas3`) | 0.90 | 0.86 | a small gap |
| fresh per-qubit draw (`requbit`) | 0.75 | 0.91 | a gap, seed dependent |

Two facts follow. Matching is robust to readout and to correlated-pair mismatch at these rates:
the weights move, the matchings do not. And on every task with a gap, the known method (pij
refit on the deploy shots, then correlated matching) closes it, so a pass rule can demand it.
Most of the plain gap on a drift task is the correlated-matching gain, not the drift:
`stale_g` runs 0.3 to 0.9. The harness therefore also reports `gap_drift`, the share of the
stale fit's loss that the agent recovers (0 is a perfect pre-drift fit with correlations, 1 is
the test-time model), and the pass rule has three parts: diagnosis correct, g at least 0.5,
and on a drift task `gap_drift` at least 0.5.

The second grid (`decoder_task.hard_tasks`, 30 tasks): 5 adequate; `bq15` and `bq30` at three
seeds; `bq30` with a 2,000-shot deploy batch, where a full refit overfits and the baseline's
shrinkage (20 pseudo-events toward the nominal ratio) is what keeps it honest; `bg40`;
`requbit`; `meas5` and `meas3`; two combined kinds that hide a subtle fault behind an obvious
one (`bq15+line5`, `bq30+meas3`); the hetero base with `meas5` and `requbit`; and `bq30` and
`requbit` at d = 7. The gate (true model at least 20% better than the stale fit) picks the
final set.

## The gate on the second grid (300,000 test shots, 20,000 deploy shots unless `-n2000`)

| task | true / stale | stale g | pij plain g | pij corr g | pij corr drift gap | gate |
|---|---|---|---|---|---|---|
| d5-none | adequate | | -0.00 | 1.06 | | kept |
| d5-none-s1 | adequate | | 0.06 | 1.09 | | kept |
| d5-none-s2 | adequate | | 0.04 | 1.13 | | kept |
| d7-none | adequate | | 0.07 | 0.97 | | kept |
| d7-none-s1 | adequate | | -0.01 | 1.02 | | kept |
| d5-none-dbq15 | 0.88 | 0.77 | 0.43 | 1.04 | 1.20 | dropped |
| d5-none-dbq15-s1 | 0.73 | 0.46 | 0.56 | 0.98 | 0.97 | kept |
| d5-none-dbq15-s2 | 0.93 | 0.84 | 0.26 | 1.02 | 1.13 | dropped |
| d5-none-dbq30 | 0.80 | 0.68 | 0.52 | 1.04 | 1.13 | dropped |
| d5-none-dbq30-s1 | 0.60 | 0.28 | 0.70 | 0.90 | 0.86 | kept |
| d5-none-dbq30-s2 | 0.85 | 0.75 | 0.42 | 0.99 | 0.95 | dropped |
| d5-none-dbq30-n2000 | 0.80 | 0.68 | 0.54 | 1.02 | 1.05 | dropped |
| d5-none-dbq30-s1-n2000 | 0.60 | 0.28 | 0.67 | 0.88 | 0.83 | kept |
| d5-none-dbq30-s2-n2000 | 0.85 | 0.75 | 0.35 | 1.01 | 1.04 | dropped |
| d5-none-dbg40 | 0.66 | 0.44 | 0.58 | 0.97 | 0.94 | kept |
| d5-none-dbg40-s1 | 0.96 | 0.94 | 0.27 | 0.96 | 0.34 | dropped |
| d5-none-dbg40-s2 | 0.95 | 0.91 | 0.33 | 0.99 | 0.87 | dropped |
| d5-none-drequbit | 0.81 | 0.63 | 0.37 | 0.96 | 0.89 | dropped |
| d5-none-drequbit-s1 | 0.94 | 0.88 | 0.24 | 0.99 | 0.88 | dropped |
| d5-none-drequbit-s2 | 0.71 | 0.56 | 0.57 | 0.97 | 0.93 | kept |
| d5-none-dmeas5 | 0.78 | 0.21 | 0.55 | 0.86 | 0.83 | kept |
| d5-none-dmeas3 | 0.87 | 0.53 | 0.30 | 0.97 | 0.93 | dropped |
| d5-none-dbq15+line5 | 0.80 | 0.65 | 0.52 | 1.05 | 1.14 | dropped |
| d5-none-dbq15+line5-s1 | 0.71 | 0.39 | 0.54 | 0.92 | 0.87 | kept |
| d5-none-dbq30+meas3 | 0.72 | 0.39 | 0.66 | 0.99 | 0.98 | kept |
| d5-hetero-dmeas5 | 0.68 | 0.69 | 0.83 | 0.92 | 0.74 | kept |
| d5-hetero-drequbit | 0.86 | 0.89 | 0.66 | 0.99 | 0.94 | dropped |
| d7-none-dbq30 | 0.44 | 0.55 | 0.65 | 0.97 | 0.94 | kept |
| d7-none-dbq30-s1 | 0.39 | 0.50 | 0.69 | 0.98 | 0.96 | kept |
| d7-none-drequbit | 0.67 | 0.78 | 0.51 | 1.06 | 1.27 | kept |

17 tasks kept: 5 adequate and 12 drift. The one-qubit faults keep one seed in three at
15x and 30x: the gap depends on where the qubit sits. The known method recovers 0.83 to 1.27
of the drift loss on every kept task, the 2,000-shot task included (0.83), so the pass rule
is reachable by a method in the literature on every task that counts.

## Predictions for the hard set, written before the run

Revised for the second grid, still before any episode ran on it:

1. Sonnet 5.5 high pass rate between 20% and 45% over the surviving tasks.
2. Diagnosis correct on fewer than half of the local tasks (the combined kinds and the gate
   faults carry the misses); on at least 4 of the 5 adequate tasks.
3. Awareness Brier stays near 0 on the single-fault tasks (a 30x fault is visible); the
   difficulty sits in the diagnosis and in `gap_drift`, not in the flag.
4. `pij_corr` recovers at least half the drift loss on at least 80% of the surviving drift
   tasks, the 2,000-shot tasks included.
5. Sonnet median `gap_drift` on the surviving drift tasks between 0.2 and 0.6, and under 0.3
   on the 2,000-shot tasks.

If prediction 1 holds, the hard set becomes tier 2 and the pilot kinds move to a warm-up split.
If the pass rate is above 60%, the next knobs are two faults per task everywhere and a
500-shot deploy batch; both are in the task grammar and need no harness change.

## Hard set result (2026-11-01 evening): Sonnet 29%, Opus 88%

Both arms ran on the 17 kept tasks (Opus on 8 of them). Every episode submitted.

| arm | tasks | pass rate | diagnosis correct | median g | median `gap_drift` (drift tasks) | cost |
|---|---|---|---|---|---|---|
| Sonnet 5.5 high | 17 | 5 of 17 (29%) | 17 of 17 | 0.63 | 0.39 | $9.91 |
| Opus 5.5 medium | 8 | 7 of 8 (88%) | 8 of 8 | 1.00 | 0.99 | $9.31 |

Prediction 1 (Sonnet 20% to 45%) held. Prediction 2 did not: the diagnosis was perfect in
both arms, scope and qubits alike, at 15x to 30x the fault location is plain in the detector
rates. Prediction 5 held (Sonnet median `gap_drift` 0.39). The whole difference between the
arms is the fix, not the diagnosis:

- Sonnet found the qubit and scaled its noise in the text of `nominal.stim`, then shipped
  plain matching on 11 of 12 drift tasks (`fitted_plain` after the adapter fix below). It
  recovers 0.2 to 0.6 of the drift loss and loses the rest to the missing correlations. On
  three of the five adequate tasks it shipped plain nominal matching (g = 0).
- Opus did the same localisation, kept correlated matching, and on the 2,000-shot task wrote a
  per-shot mixture classifier (a likelihood ratio over the affected detectors with an EM prior)
  that decodes each shot with its regime's model. That is the textbook method for a qubit that
  switches state, written unprompted. It missed only d7-dbq30, where it shipped plain matching
  after 11 turns.

Two fixes came out of reading the decoders. The failure-mode adapter had called every one of
these decoders "nominal": it read probabilities only out of inlined DEMs, not out of edited
circuit text, rebuilt models or helper modules. It now also records behaviour: the share of
test predictions identical to nominal plain and nominal correlated matching, which the harness
computes for every scored episode (`agree_nominal_plain`, `agree_nominal_corr`) and which the
adapter prefers over source reading. `scripts/rescore_agreement.py` added those columns to the
finished runs; the leaves above are the behavioural ones.

**Reading.** The hard set puts Sonnet in the band and leaves Opus at the ceiling of everything
stationary. The next tier has to be noise that one circuit cannot describe.

## Nonstationary noise: what was measured (d = 5, 100,000 shots, oracle over stale fit)

| kind | seed 0 | seed 1 | stationary refit recovers | known per-shot method recovers |
|---|---|---|---|---|
| telegraph qubit 15x, 50% duty, 200-shot stretches (`tls15`) | 0.98 | 0.96 | | |
| telegraph 30x (`tls30`) | 0.89 | 0.91 | 0.37 / -0.12 | 0.88 / 0.66 (window) |
| telegraph 50x (`tls50`) | 0.85 | 0.82 | 0.52 / 0.45 | 0.93 / 0.76 |
| telegraph 80x (`tls80`) | 0.83 | 0.75 | 0.48 / 0.46 | 0.85 / 0.83 |
| telegraph 30x at d = 7 | 0.74 | 0.88 | 0.81 / 0.92 | 0.98 / 0.67 |
| hot spot 15x, one qubit for 2 rounds, new spot every shot (`hot15`) | 0.91 | 0.90 | -0.35 / 0.26 | |
| hot spot 30x (`hot30`) | 0.76 | 0.75 | -0.03 / -0.02 | see the threshold sweep |
| hot spot 50x (`hot50`) | 0.63 | 0.69 | 0.00 / 0.07 | |
| hot spot 30x at d = 7 | 0.91 | 0.75 | 0.22 / -0.19 | |

The window method for telegraph noise (a per-shot likelihood ratio on the detectors the two
regimes differ on, averaged over 50 shots each side in time, then the chosen regime's
correlated matcher) recovers 0.67 to 0.98 of the loss. A stationary refit recovers about half:
a blended model is wrong in both states.

**The per-shot hot spot was dropped.** A stationary refit recovers nothing of it, which looked
like the hard task wanted, but the per-shot method cannot recover it either: scoring every
(qubit, two-round window) by the shot's own detection events picks the right one in 16% of
shots at 50x and 9% at 30x, and every decision threshold between "assign always" and "never"
decodes worse than the stale fit (threshold sweep, 60,000 shots, `tasks/b56sp2564` in the
session log). Two rounds of one qubit leave too few events to locate, so no method approaches
the per-shot oracle and the pass rule would be unreachable. The physics agrees: defects switch
over milliseconds, not between shots.

**The wandering telegraph replaces it** (`wander{f}`): a bad stretch of about 200 shots picks a
new random qubit out of 12 candidates drawn per batch, base stretches in between. Measured at
d = 5 with 100,000 shots:

| kind | oracle / stale, seeds 0 and 1 | stationary refit recovers | window method recovers |
|---|---|---|---|
| `wander50` | 0.52, 0.50 | 0.01, 0.05 | 0.97, 0.95 |
| `wander80` | 0.42, 0.43 | -0.09, -0.05 | 0.98, 0.96 |

Half the shots are lost to a moving fault, a stationary fit cannot see it, and pooling 100
consecutive shots locates it almost perfectly. The nonstationary set
(`decoder_task.nonstationary_tasks`, 22 tasks): 3 adequate, 9 fixed telegraph, 10 wandering;
the gate picks the survivors. The prompt now tells the agent that shots are in the order they
were taken, and the report has a `stationary` field that the diagnosis scores.

Predictions for the nonstationary set, before any episode: Sonnet pass rate 10% to 30%; Opus
30% to 60%; the diagnosis field that fails first is `stationary`, on the fixed telegraph tasks
for Sonnet; the wandering tasks are where Opus fails, because a stationary mixture over one
qubit does not fit twelve; Opus writes a per-shot classifier on at least half of the fixed
telegraph tasks and uses the shot order on fewer than half of all tasks.

## Non-stationary set, Sonnet 5.5 high (2026-11-01, night)

The gate kept 18 of 22 tasks (3 adequate, 6 fixed telegraph, 9 wandering). Sonnet ran 15 of
them before the $18 cap stopped it; every episode submitted.

| group | tasks | passed | diagnosis correct | median `gap_drift` | leaves |
|---|---|---|---|---|---|
| adequate | 3 | 1 | 3 of 3 | | nominal_plain 2, nominal_correlated 1 |
| fixed telegraph (`tls`) | 5 | 2 | 4 of 5 | 0.15 | fitted_plain 4, worse_than_plain 1 |
| wandering (`wander`) | 7 | 0 | 0 of 7 | -0.14 | fitted_plain 6, worse_than_plain 1 |

Pass rate 3 of 15 (20%), inside the predicted 10% to 30%. What the rows say:

- **It sees that the noise moves.** `stationary` was right on 12 of 12 drift tasks and the
  Brier stayed near zero. Prediction 2 (the `stationary` flag fails first) was wrong.
- **It cannot see that the fault moves.** Every wandering task was reported as `local`: Sonnet
  finds one bad qubit in the batch statistics and stops. Scope is where the diagnosis fails, 7
  of 7 times, as prediction 2 said it would for the wandering tasks.
- **No decoder uses the order of the shots.** None of the fifteen decoders pools consecutive
  shots or looks for a change point; two mention a window or a cumulative sum in passing. Every
  fix is a stationary refit with plain matching, which is why `gap_drift` sits at 0.15 on the
  fixed telegraph tasks and below zero on the wandering ones. Two decoders were worse than
  nominal matching (one at 14 times the nominal error rate), both a blended model of a bad
  qubit applied to every shot.
- **The baselines behave as designed.** The window method recovers 0.95 to 0.98 of the drift
  loss on all twelve tasks; the stationary pij refit recovers 0.65 to 0.86 on the fixed
  telegraph tasks and -0.07 to 0.08 on the wandering ones.

Opus runs on eight of the same tasks next; its rows go below when they land.

## Non-stationary set, Opus 5.5 medium (eight tasks, $11.94)

| task | gap closed | `gap_drift` | diagnosis | passed | decoder |
|---|---|---|---|---|---|
| d5-none-s3 | 0.00 | | right | no | nominal plain |
| d5-none-s4 | 1.00 | | right | yes | nominal correlated |
| d5-none-dtls80 | 1.00 | 1.00 | right | yes | fitted, correlated |
| d5-none-dtls80-s2 | 0.80 | 0.77 | right | yes | fitted, plain |
| d5-none-dtls50 | 0.73 | 0.64 | right | yes | fitted, plain |
| d5-none-dtls50-s2 | 1.00 | 1.00 | right | yes | fitted, correlated |
| d7-none-dtls30-s1 | 0.46 | -0.60 | right | no | fitted, plain |
| d5-none-dwander30 | 0.62 | 0.38 | scope wrong (local) | no | fitted, plain, Viterbi over the shot order; stopped at the $4 cap after 31 turns |

Pass rate 5 of 8 (62%), just above the predicted 30% to 60%, but the eight tasks were the first
six drift survivors plus two adequate ones, which made the sample telegraph-heavy: six fixed
telegraph tasks and one wandering one. On the fixed telegraph tasks Opus is at or near the
oracle on four of six, and it named the switching qubit every time. On the one wandering task
it did what no Sonnet episode did, a cumulative-sum change-point pass and a Viterbi decode over
the shot order, and still called the fault local and ran out of budget. One wandering task is
not a measurement; an Opus arm on the wandering survivors alone is the next run.

## Where the benchmark stands at the end of 2026-11-01

| set | Sonnet 5.5 high | Opus 5.5 medium |
|---|---|---|
| hard (stationary faults) | 5 of 17 (29%) | 7 of 8 (88%) |
| non-stationary, telegraph and wandering | 3 of 15 (20%) | 5 of 8 (62%), telegraph-heavy sample |

Both arms diagnose a stationary fault every time; the stationary tier is a test of the fix. Both
arms see that noise moves; the wandering tier is a test of whether the agent uses the order of
the shots, which Sonnet never did and Opus did once. The known method recovers 95% to 98% of the
wandering loss, so the headroom is real and reachable.

## Opus on wandering faults alone (four tasks, $9.52): 0 of 4

| task | gap closed | `gap_drift` | reported scope | decoder |
|---|---|---|---|---|
| d5-none-dwander50 | 0.76 | 0.64 | local | fitted, plain |
| d5-none-dwander50-s1 | 0.07 | -0.42 | global | fitted, plain, a cumulative-sum pass |
| d5-none-dwander80 | 0.83 | 0.79 | local | fitted, plain |
| d7-none-dwander30 | 0.38 | -0.99 | local | fitted, plain, a cumulative-sum pass |

Opus understood the fault in words every time. Its own report on the first task: single qubits
"take turns going into bursts lasting 100 to 600 shots", every error source "about 50 times
stronger", and between bursts "the device matches nominal.stim". It listed ten of the twelve
bad qubits. Then it shipped a stationary refit with plain matching on all four. At 50x and 80x
that blended model still recovers 0.64 and 0.79 of the loss, because a qubit that bad is better
over-weighted all the time than never; at 30x on d = 7 it is worse than the stale fit.

Two consequences for the scoring. First, the report schema had no word for what Opus saw: the
scope choices were none, local and global, and it picked local three times. The schema now has
`moving`, and a moving diagnosis is scored on the qubits that were bad in the deploy batch. The
four episodes above cannot be rescored under it; they are reported as run. Second, the pass
rule needs an honest ceiling. The window method is told the regimes. `decoders/adaptive.py` is
told nothing: it tests every qubit and every disk of neighbours at five factors against the
stale model over a sliding window of the time series and reweights the winner. It recovers
0.86 of the wandering loss at 30x and 0.97 of a moving patch, 0.64 on a bad qubit with a
wandering one on top, reaches the oracle on a fixed telegraph qubit, and leaves an adequate
batch alone (30,000-shot checks). The launch gate requires it to
recover at least half of the drift loss on every task that counts, so the pass rule is
reachable by a method that knows only what the agent knows.

Spend on 2026-11-01: about $100 across the hard, non-stationary and wandering runs, on top of
about $90 before the pivot. The launch set's agent runs wait for the budget.

## The launch set and its two gates (300,000 test shots)

| task | oracle / stale | stale g | pij refit recovers | window method recovers | honest adaptive recovers |
|---|---|---|---|---|---|
| d5-none-s5 | adequate | | | | pij g 1.09 |
| d5-none-s6 | adequate | | | | pij g 1.02 |
| d7-none-s3 | adequate | | | | pij g 0.98 |
| d5-none-dwander30 | 0.61 | 0.37 | 0.11 | 0.97 | 0.94 |
| d5-none-dwander30-s1 | 0.63 | 0.44 | -0.14 | 0.97 | 0.94 |
| d5-none-dwander30-s2 | 0.69 | 0.51 | -0.03 | 0.97 | 0.95 |
| d5-none-dwander50 | 0.47 | 0.27 | 0.12 | 0.98 | 0.97 |
| d5-none-dwander50-s1 | 0.51 | 0.34 | -0.21 | 0.96 | 0.94 |
| d5-none-dwander50-s2 | 0.57 | 0.36 | -0.04 | 0.96 | 0.93 |
| d5-none-dwander30d60 | 0.61 | 0.37 | 0.11 | 0.84 | 0.84 |
| d5-none-dwander30d60-s1 | 0.65 | 0.45 | -0.06 | 0.82 | 0.79 |
| d5-none-dwander30-n5000 | 0.61 | 0.37 | -0.01 | 0.97 | 0.94 |
| d5-none-dwander30-s1-n5000 | 0.63 | 0.44 | 0.07 | 0.97 | 0.94 |
| d5-none-dpatch30 | 0.47 | 0.10 | 0.15 | 0.96 | 0.95 |
| d5-none-dpatch30-s1 | 0.44 | 0.04 | 0.32 | 0.97 | 0.95 |
| d5-none-dbq15+wander30 | 0.59 | 0.41 | 0.19 | 0.98 | 0.72 |
| d5-none-dbq15+wander30-s1 | 0.53 | 0.32 | 0.29 | 0.97 | 0.68 |
| d5-none-dmeas2+wander30 | 0.54 | 0.25 | 0.23 | 0.97 | 0.86 |
| d5-none-dbq15+meas2+wander30 | 0.56 | 0.27 | 0.30 | 0.98 | 0.67 |
| d7-none-dwander30 | 0.55 | 0.62 | 0.02 | 0.97 | 0.96 |
| d7-none-dpatch30 | 0.51 | 0.41 | -0.26 | 0.97 | 0.95 |

All 21 tasks kept. On every drift task the oracle beats the stale fit by 31% to 56%; a
stationary refit of the deploy batch recovers between -0.26 and 0.32 of that loss; the window
method, which is told the regimes, recovers 0.82 to 0.98; the honest adaptive decoder, told
nothing but the stale model and the shot order, recovers 0.67 to 0.97. The compounds are where
the honest method loses the most (0.67 to 0.72): a static bad qubit under a wandering one. Both
arms run on all 21, capped at $20 each.

Predictions, before any episode: Sonnet 0% to 10%; Opus 10% to 30%, with its passes on the
50x tasks where a stationary over-weighting still recovers half the loss; neither arm passes a
compound or a patch task; the `moving` scope is reported on at least half of Opus's episodes
now that the schema has it, and on fewer than a quarter of Sonnet's.

## Launch set, Sonnet 5.5 high, first 12 of 21 tasks (2026-11-01, late): credits ran out

The Anthropic credit balance was exhausted after the twelfth episode; the next three failed
before the first call with "credit balance is too low", and the arms were stopped. The nine
unrun tasks: `d5-none-dwander30-s1-n5000`, both `patch30`, the four compounds, and both d = 7
tasks. Opus has not run on the launch set.

| task | gap closed | `gap_drift` | honest method recovers | scope | overlap | passed (absolute) | passed (relative) |
|---|---|---|---|---|---|---|---|
| d5-none-s5, s6, d7-none-s3 | 0.00 | | | none | | no (plain nominal matching) | no |
| d5-none-dwander30 | 0.65 | 0.45 | 0.94 | moving | 1.00 | no | no |
| d5-none-dwander30-s1 | 0.16 | -0.51 | 0.94 | moving | 1.00 | no | no |
| d5-none-dwander30-s2 | 0.26 | -0.51 | 0.95 | moving | 0.92 | no | no |
| d5-none-dwander50 | 0.79 | 0.71 | 0.97 | moving | 0.92 | yes | no |
| d5-none-dwander50-s1 | 0.73 | 0.59 | 0.94 | moving | 1.00 | yes | no |
| d5-none-dwander50-s2 | 0.73 | 0.58 | 0.93 | moving | 1.00 | yes | no |
| d5-none-dwander30d60 | 0.14 | -0.37 | 0.84 | moving | 1.00 | no | no |
| d5-none-dwander30d60-s1 | 0.48 | 0.06 | 0.79 | moving | 1.00 | no | no |
| d5-none-dwander30-n5000 | 0.62 | 0.40 | 0.94 | moving | 0.62 | no | no |

Three findings, on $8.86:

1. **The schema was the diagnosis problem.** With `moving` available, Sonnet reports it on 9 of
   9 wandering tasks and lists the bad qubits with Jaccard 0.92 to 1.00 (0.62 on the 5,000-shot
   batch, where it saw fewer of them). Diagnosis is 100% again. The prediction that Sonnet
   would report `moving` on fewer than a quarter of its episodes was wrong.
2. **The fix is still a stationary refit.** Every decoder over-weights the bad qubits all the
   time. At 50x that recovers 0.58 to 0.71 of the loss, because a qubit that bad is better
   over-weighted than ignored; at 30x it recovers nothing or less than nothing. Three passes,
   all at 50x, all by this route.
3. **The pass rule needs the honest method as its bar.** An absolute `gap_drift` of 0.5 lets a
   stationary over-weighting pass a 50x task on which the honest adaptive method recovers
   0.93 to 0.97. Scored as "at least three quarters of what the honest method recovers on this
   task", the pass rate is 0 of 12. That is the rule the launch set should ship with: the
   headline then reads "the agent recovers most of what a competent adaptive decoder recovers",
   which is the claim a card can carry. The absolute rule stays as a sub-score.

Under the relative rule the launch set stands at Sonnet 0 of 12, Opus not run. The remaining
nine Sonnet tasks and the Opus arm run when credits are back:

```bash
scripts/run_launch.sh "$PWD" --run 12 20   # reruns every survivor; or pass --tasks with the nine names
```


## Launch set, Opus 5.5 medium through Claude Code, all 21 tasks (2026-11-02, 02:40 to 05:10)

The arm ran on the claude.ai subscription through the Claude Code scaffold
(`decoder_run_cc.py`: one headless CLI per task, Bash and file tools, the same task text, a
report.json instead of a submit tool, the harness's own scoring). CLI cost estimate $17.22,
billed to the subscription. Two scoring rules are reported: **absolute**, the three-part rule
with `gap_drift` at least 0.5; **relative**, the same with `gap_drift` at least three quarters
of what the honest adaptive decoder recovers on that task. A moving fault reported as `local`
with the stationary flag false and the right qubits counts as diagnosed (rule added this night;
Opus did exactly that on every 50x task).

**Opus via Claude Code: 10 of 21 (48%) absolute, 5 of 21 (24%) relative, diagnosis 86%.**

| family | tasks | absolute passes | relative passes | median `gap_drift` | median overlap |
|---|---|---|---|---|---|
| wandering qubit 30x | 4 | 0 | 0 | 0.01 | 0.96 |
| wandering qubit 50x | 3 | 3 | 0 | 0.59 | 1.00 |
| faster switching (dwell 60) | 2 | 0 | 0 | 0.30 | 0.96 |
| 5,000-shot deploy batch | 2 | 0 | 0 | 0.32 | 0.67 |
| moving patch | 3 | 3 | 2 | 0.85 | 1.00 |
| compound | 4 | 2 | 1 | 0.55 | 0.57 |

| task | tool calls | gap closed | `gap_drift` | honest method | scope | overlap | absolute | relative |
|---|---|---|---|---|---|---|---|---|
| d5-none-s5 | 16 | 1.00 |  |  | none |  | yes | yes |
| d5-none-s6 | 17 | 1.00 |  |  | none |  | yes | yes |
| d7-none-s3 | 13 | 0.00 |  |  | none |  | no | no |
| d5-none-dwander30 | 24 | 0.16 | -0.34 | 0.94 | local | 0.37 | no | no |
| d5-none-dwander30-s1 | 33 | 0.64 | 0.36 | 0.94 | moving | 1.00 | no | no |
| d5-none-dwander30-s2 | 26 | 0.60 | 0.20 | 0.95 | moving | 0.92 | no | no |
| d5-none-dwander50 | 25 | 0.79 | 0.71 | 0.97 | local | 1.00 | yes | no |
| d5-none-dwander50-s1 | 20 | 0.73 | 0.59 | 0.94 | local | 1.00 | yes | no |
| d5-none-dwander50-s2 | 20 | 0.73 | 0.58 | 0.93 | local | 1.00 | yes | no |
| d5-none-dwander30d60 | 23 | 0.57 | 0.32 | 0.84 | local | 0.92 | no | no |
| d5-none-dwander30d60-s1 | 25 | 0.61 | 0.28 | 0.79 | local | 1.00 | no | no |
| d5-none-dwander30-n5000 | 24 | 0.59 | 0.35 | 0.94 | moving | 0.62 | no | no |
| d5-none-dwander30-s1-n5000 | 24 | 0.61 | 0.30 | 0.94 | moving | 0.71 | no | no |
| d5-none-dpatch30 | 33 | 0.87 | 0.85 | 0.95 | local | 1.00 | yes | yes |
| d5-none-dpatch30-s1 | 23 | 0.88 | 0.88 | 0.95 | local | 1.00 | yes | yes |
| d5-none-dbq15+wander30 | 26 | 0.71 | 0.51 | 0.72 | local | 0.92 | yes | no |
| d5-none-dbq15+wander30-s1 | 22 | 0.73 | 0.60 | 0.68 | local | 1.00 | yes | yes |
| d5-none-dmeas2+wander30 | 26 | 0.75 | 0.67 | 0.86 | global | 0.22 | no | no |
| d5-none-dbq15+meas2+wander30 | 26 | 0.54 | 0.37 | 0.67 | global | 0.22 | no | no |
| d7-none-dwander30 | 21 | 0.55 | -0.17 | 0.96 | local | 1.00 | no | no |
| d7-none-dpatch30 | 28 | 0.76 | 0.60 | 0.95 | moving | 1.00 | yes | no |

Reading. Opus finds the switching qubits almost every time (overlap 0.92 to 1.00 on 16 of 18
drift tasks; the two misses are the compounds under a global readout drift, where it reported
the readout drift and 22% of the qubits). It still fixes with a stationary model. That
recovers 58% to 71% at 50x and 85% to 88% on a moving patch, where a region that bad is
better over-weighted all the time, and 20% to 36% at 30x, where the honest adaptive method
recovers 94%. On the 30x tasks, the faster switching and the small deploy batch it never
reaches half. The relative rule, which asks for most of what a competent adaptive decoder
gets, is the one that separates "noticed and over-weighted" from "fixed": 24% for the frontier
model, with the passes on the patches and one compound.

Through Claude Code, Opus used 13 to 33 tool calls and 1.5 to 15 minutes per task, close to
the API harness's 40-call budget; the scaffold loads none of this machine's configuration and
runs under the sandbox described in `decoder_run_cc.py`.


## Launch set, Sonnet 5.5 high through Claude Code, all 21 tasks (2026-11-02, 05:10 to 08:15)

**Sonnet via Claude Code: 3 of 21 (14%) absolute, 2 of 21 (10%) relative, diagnosis 71%.**
CLI cost estimate $11.03 on the subscription. Leaves: fitted_plain 17, nominal_plain 2,
nominal_correlated 1, unscored 1 (a decoder that raised at import).

| task | tool calls | gap closed | `gap_drift` | honest method | scope | overlap | absolute | relative |
|---|---|---|---|---|---|---|---|---|
| d5-none-s5 | 25 | 1.00 |  |  | none |  | yes | yes |
| d5-none-s6 | 25 | 0.00 |  |  | none |  | no | no |
| d7-none-s3 | 14 | 0.00 |  |  | none |  | no | no |
| d5-none-dwander30 | 30 | 0.03 | -0.55 | 0.94 | moving | 0.59 | no | no |
| d5-none-dwander30-s1 | 30 | 0.67 | 0.40 | 0.94 | moving | 1.00 | no | no |
| d5-none-dwander30-s2 | 35 | 0.62 | 0.22 | 0.95 | moving | 0.67 | no | no |
| d5-none-dwander50 | 25 | 0.13 | -0.18 | 0.97 | local | 0.50 | no | no |
| d5-none-dwander50-s1 | 26 | 0.59 | 0.39 | 0.94 | moving | 1.00 | no | no |
| d5-none-dwander50-s2 | 35 | 0.70 | 0.53 | 0.93 | moving | 0.92 | yes | no |
| d5-none-dwander30d60 | 26 | 0.59 | 0.35 | 0.84 | moving | 0.52 | no | no |
| d5-none-dwander30d60-s1 | 33 | 0.54 | 0.17 | 0.79 | moving | 1.00 | no | no |
| d5-none-dwander30-n5000 | 31 | 0.27 | -0.16 | 0.94 | moving | 0.62 | no | no |
| d5-none-dwander30-s1-n5000 | 25 |  |  | 0.94 | moving | 0.44 | no | no |
| d5-none-dpatch30 | 29 | 0.88 | 0.86 | 0.95 | local | 0.98 | yes | yes |
| d5-none-dpatch30-s1 | 52 | 0.49 | 0.47 | 0.95 | local | 0.68 | no | no |
| d5-none-dbq15+wander30 | 40 | 0.42 | 0.01 | 0.72 | moving | 0.38 | no | no |
| d5-none-dbq15+wander30-s1 | 26 | 0.35 | 0.04 | 0.68 | moving | 0.28 | no | no |
| d5-none-dmeas2+wander30 | 23 | 0.38 | 0.18 | 0.86 | local | 0.20 | no | no |
| d5-none-dbq15+meas2+wander30 | 50 | 0.75 | 0.65 | 0.67 | moving | 0.22 | no | no |
| d7-none-dwander30 | 34 | 0.52 | -0.26 | 0.96 | local | 0.92 | no | no |
| d7-none-dpatch30 | 35 | 0.49 | 0.14 | 0.95 | local | 0.42 | no | no |

Sonnet reports `moving` on 12 of 18 drift tasks and names the qubits on the single-fault ones
(overlap 0.5 to 1.0), loses them on the compounds (0.2 to 0.4), and fixes with a stationary
refit and plain matching on 17 of 21 tasks. Median `gap_drift` by family: 0.17 on the 30x
wandering tasks, 0.39 at 50x, 0.47 on the patches, 0.11 on the compounds, below zero on the
5,000-shot batch. Its two relative passes are an adequate task with correlated matching and
one moving patch at 0.86.

## The launch set at the end of the first night

| arm | absolute rule | relative rule | diagnosis | cost |
|---|---|---|---|---|
| Opus 5.5 medium, Claude Code scaffold | 10 of 21 (48%) | 5 of 21 (24%) | 86% | $17 est., subscription |
| Sonnet 5.5 high, Claude Code scaffold | 3 of 21 (14%) | 2 of 21 (10%) | 71% | $11 est., subscription |
| Sonnet 5.5 high, API scaffold (12 of 21, credits ran out) | 3 of 12 | 0 of 12 | 100% | $8.86 |

The honest adaptive decoder, told nothing but the stale model and the shot order, recovers 0.67
to 0.97 of the loss on every one of these tasks. Both frontier models find the fault and fix it
as if it were stationary. The relative rule is the headline: 24% and 10%.
