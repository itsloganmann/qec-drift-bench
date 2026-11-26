# readout_drift: notes (version 3, after the independent review)

Version 2 is in git history. Finding numbers refer to the review (findings 1 to 18).

## What changed and why

- Isolation (finding 1). `solve` runs in a fresh process (`eval/_isolate.py`, same file in all
  three environments): `python -I`, empty temp folder, only the solution's folder plus stdlib and
  site-packages on `sys.path`, environment stripped (no `MISMATCH_SEED`), 120 s timeout enforced
  by the subprocess (finding 15). The solver gets only `data` and never the hidden test set.
- Data, not code (finding 1). The solver returns the discriminator as Gaussian components
  (mean, 2x2 covariance, weight, label), one list or one per experiment. The grader validates
  shapes and positive definiteness (invalid scores 0) and labels its own test points by maximum
  posterior. The test set is shuffled. The stale anchor is the calibration LDA written in the
  same form.
- Output and seeds (findings 1, 18). `evaluate.py` prints one number. `--json` is gone;
  `--report PATH` writes the breakdown with truth for maintainers. Scored instances come from
  `--seed N` or `MISMATCH_SEED`; evaluate.py re-execs itself with the seed on a pipe so it is not
  in `/proc/<pid>/cmdline` or `environ`. Without a seed the 30 public instances (seeds 3001 to
  3030, consecutive) are a reproducible smoke test.
- Scoring rule (findings 2, 11). 15 of 30 instances are controls. A wrong `changed` scores 0 for
  the instance, so fix credit is paid only with the right yes or no. Each instance's rule
  (control, fix, diagnosis only) is fixed at build time from a separate 400,000-shot sample of
  the true device (gap >= 0.003), never from the test sample. The oracle is now the exact Bayes
  rule of the true device including the T1 tail, so it is a real ceiling. The report gives the
  false-alarm and miss rates.
- Free credit (finding 2, brief item 6). Magnitude tolerances tightened (phase 4 to max(2.5 deg,
  10%), gain 0.06 to 0.04, shift 25% to 15%, noise 0.08 to 0.06). Sizes are graded against the
  full change including wander, which is what the shots identify.
- Leakage dropped (finding 9). With the physical level-2 resonator pull, f2/chi =
  -3 Delta / (Delta + 2 alpha) (Koch 2007, arXiv:cond-mat/0703002), Delta = -2.5 to -1.0 GHz and
  alpha = -0.34 to -0.2 GHz give f2/chi = -2.6 to -1.8: the |2> cloud sits beyond |1>, away from
  |0>, so it barely moves the 0/1 boundary (no fix to score). On 2000 devices from this task's
  prior the |2> to |1> distance is 1.0 / 1.6 / 2.8 sigma (10th / 50th / 90th percentile); with
  about 275 |1> shots the Fisher-limit standard error on the leak fraction L is 0.016 at the
  median, so L = 0.05 clears 3 standard errors in only half of the devices even with the |2>
  position known and no T1 tail. Measurement-induced transitions (Sank 2016, arXiv:1606.05721;
  Khezri 2022, arXiv:2212.05097) land in the same far-side clouds, so reframing does not help
  at these shot counts. A family that is not identifiable should not be graded (Morales-Hashemi
  et al., arXiv:2610.03545), so it is gone and the |2> level is not modelled.
- T1 family (finding 12). `t1_drop`: T1 falls by 3 to 10 times (Klimov 2018, arXiv:1809.01043).
  Measured: with Delta p_decay (rise in the chance that a |1> shot decays inside the window) of
  0.15 to 0.35, the reference found 3 of 12 in a few hundred unlabeled shots (log-likelihood
  gain about 4: decayed shots trade off against the unknown per-experiment population). With a
  rise >= 0.35 it found 7 of 10. So instances are redrawn until the rise is >= 0.35 and the floor
  is 0.25; this selects long windows and large factors (kept factors mostly 6 to 10). The fitted
  factor is only good to about 40%, so the `t1_drop` size is not graded; its kind is.
- Drift sizes (finding 12). No source supports the phase, gain, shift or noise ranges, so TASK.md
  calls them stress cases. Background wander below the floor stays on every instance.
- Time structure (review, "how they handle drift"). New family `phase_ramp`: the rotation grows
  linearly across the 8 ordered experiments, and every instance is scored per experiment (the
  solver may return 8 discriminators). Kept simple: one linear ramp, no other time dependence;
  the wander also includes a small ramp.
- Reference (findings 6, 9). Now the strongest method we know: maximum-likelihood fit of the
  stated device model (T1 tail and preparation error included) to the calibration, then to the
  unlabeled shots for every candidate model (none, 6 singles, pairs with the top 2), profiling
  the per-experiment populations by EM; penalised-likelihood model choice (8 log-likelihood
  units per family); families reported only above the floor; discriminator = the fitted
  model's Bayes rule with the T1 tail as 8 components. The penalty was chosen before any run
  and not tuned; development used seeds 777 and 778 only. No target band.
- Lazy battery (finding 2, brief item 8) in `checks/`, see `checks/expect.json`.
- Open question added to TASK.md; every uncited number marked as an assumption.

## Measured

Python 3.13, numpy 2.5.3, scipy 1.18.1, one process on a shared 4-core machine (load about 4).
Public = seeds 3001 to 3030; secret = 5 seeds drawn with `secrets` (788356457, 1107635184,
1123023411, 2075486682, 978180092). Wall time is the whole `evaluate.py` run (30 instances,
each with a fresh child process).

| solution | public | secret mean +/- se | max over seeds of (score - trivial) | wall s |
|---|---|---|---|---|
| eval/_trivial.py | 0.500 | 0.500 +/- 0.000 | 0 | 22 |
| eval/_reference.py | 0.946 | 0.922 +/- 0.019 | +0.486 | 114 |
| sandbox/solution.py (starter) | 0.500 | 0.500 +/- 0.000 | 0 | 23 |
| checks/lazy_blind_refit.py | 0.500 | 0.500 +/- 0.000 | 0 | 24 |
| checks/lazy_refit_changed.py | 0.344 | 0.346 +/- 0.003 | -0.148 | 24 |
| checks/lazy_const.py | 0.138 | 0.140 +/- 0.005 | -0.342 | 22 |
| checks/lazy_malformed.py | 0.000 | 0.000 +/- 0.000 | -0.500 | 22 |
| checks/leak_frames.py | 0.128 | 0.132 +/- 0.004 | -0.353 | 22 |
| checks/leak_import.py | 0.138 | 0.140 +/- 0.005 | -0.343 | 22 |
| checks/leak_position.py | 0.087 | 0.087 +/- 0.000 | -0.412 | 22 |

Every check is at or below trivial on every seed. The trivial score is 0.5 by construction (it
is right on the 15 controls and earns nothing elsewhere). Reference false-alarm rate 0 to 7%,
miss rate 0 to 20% across the six runs. Over the 180 reference instances the loss sits in
`t1_drop` alone (3.9 of 12 lost, 3 missed), near-floor `resonator_shift` (3.2 of 12) and
near-floor `phase_rotation` (2.8 of 12), then controls (2 false alarms of 90); compound drifts,
gain and ramps are close to solved. So headroom is in close calls at the floor and in T1, not
in the large stress-case drifts. No prediction was written down before this run.

## Remaining limits

- A solver that reads eval/ from disk can regenerate the public smoke-test set; scored runs must
  use a secret seed and a sandbox that hides eval/.
- The stated drift sizes for phase, gain, shift and noise are stress cases, not cited values.
- `t1_drop` is visible only for large drops with long windows; the selection is stated in TASK.md.
- The truth for near-floor instances includes wander, so a few sit just above the floor and
  are close calls for any method.
- Supported labels (2026-11-14). Before this fix, wander could push a near-floor drift below its
  own no-change floor while the instance stayed labelled "changed": 27 of 906 near-floor draws
  (3.0 percent; phase, SNR drop and shift near specs on seeds 3001 to 3302). Such a label asks
  the solver to contradict TASK.md's definition of no change, so no method could earn it.
  `draw_device` now redraws until every listed family is at or above its floor after wander
  (`supported()` in eval/harness.py), applying the same rule to the t1_drop decay rise.
- Instance order (2026-11-17). The order used to be the same for every seed: the 15 drift specs,
  then the 15 controls. The solver's process is fresh per instance, but /tmp persists, so a
  solver that counts its own calls knew which spec it was on. A re-audit probe that does no
  physics (stale calibration LDA plus the old order) scored 0.68 and 0.71 on two secret seeds.
  `instance_list` now shuffles the order per seed, as qec_drift_d3 and pulse_wrong_model already
  did, and the probe is kept as `checks/leak_order.py` (0.38 on seed 424242 after the fix).
  Per-instance scores do not depend on the order, so earlier scores stand; only the
  swapped-data ablation, which pairs each instance with the previous one, changes.

## 2026-11-18: hard tier (`--tier hard`)

Design. The readout chain's gain turns anisotropic (`iq_stretch`): the IQ plane is stretched by
sqrt(rho) along an axis and squeezed across it, on the signal and on the share of the noise that
passes that stage, as a phase-sensitive amplifier or an IQ demodulator imbalance would do (Caves
1982, doi:10.1103/PhysRevD.26.1817; Krantz et al. 2019, arXiv 1904.06560, Sec. V.E). rho is
log-uniform in 1.5 to 3 (a stress case; an assumption). It is not one of the six stated
families, so the solver reports kind "other", alone or next to a listed family that also
changed. 10 of the 15 changed instances per set carry it (6 alone); the rest are listed
families, several close to their floors. Secret seeds are salted. No prediction was written down
before these runs; the design was iterated on the public set and on early held-out runs, and the
numbers below come from one run of the frozen design.

Measured (public set and 5 paper seeds, `experiments/results/summary_hard.md`): trivial 0.50,
reference 0.74 [0.68, 0.80], ceiling (`genie_stretch`, the reference told that a stretch may
exist, never its size or axis) 0.92 [0.87, 0.96]. Per family, reference then ceiling: stretch
alone 0.28 then 0.84, two changes at once (4 of 5 with the stretch) 0.53 then 0.91, listed
families and controls the same for both (controls 0.97). Rubric: the reference loses most on
`fix_gap` (0.126) and on missing "other" in `kinds` (0.044). Lazy and leak checks: highest
`leak_order` 0.30, `lazy_always_other` 0.16; reference on swapped data 0.18.
