# NOTES: pulse_wrong_model (rebuilt after the independent review)

Finding numbers refer to the review (findings 1 to 18). Earlier notes are superseded.

## 2026-11-14: drive compression (the model's form can be wrong)

The rebuilt task below was solved by known methods (reference 0.996): refitting two numbers and
designing a robust pulse left nothing between the reference and the ceiling. The task's name
promises a wrong model, so the new family makes the design model's *form* wrong, not only its
numbers.

- New family: AM-AM drive compression, delivered amplitude a (1 - k a^2), k = 0.05 to 0.15
  (3 to 9 percent, 5 to 16 degrees, at the gate's 0.77 peak). Lazar et al. 2023
  (arXiv:2212.01077) report non-linear control lines putting 15 ns rotations several degrees
  off a linear model; the k range is our assumption around that.
- Families on changed instances: scale, freq, compress, scale + compress (4 each of 16). The
  old scale + freq family went; freq stays diagnosis-only.
- The Rabi sweep now runs to amplitude 1.0 (101 points). With the old 0 to 0.5 sweep, k was
  not identifiable (Cramer-Rao sigma 0.14, larger than k itself, since k a^2 <= k/4 there looks
  like a scale change). At 0 to 1.0 sigma_k is 0.012, so every drawn k is at least 4 sigma.
- Diagnosis gains an optional `compression` (default 0), graded like the others in units of
  its Cramer-Rao limit; D is now the product of three credits.
- Reference: joint fit of (s, delta, k, T2), 3 sigma test on each, robust GRAPE for the
  delivered pulse under the cap 1 - k, then per-sample predistortion solving |u|(1 - k|u|^2) =
  |v|. Runtime 5 to 6 min for 32 instances.
- New heuristic check: `heuristic_linear_model.py` is the previous reference (exact linear
  model, robust GRAPE). It is the honest standard recipe a strong agent would write.

Measured (public; mean +/- se over 2 secret seeds; run_all.py exit 0):

| solution | public | secret |
|---|---|---|
| trivial | 0.500 | 0.500 +/- 0.000 |
| reference | 0.991 | 0.990 +/- 0.002 |
| heuristic_linear_model | 0.843 | 0.851 +/- 0.004 |
| lazy_always_changed_robust | 0.355 | 0.364 +/- 0.003 |
| every other check | at or below 0.500 | at or below 0.500 |

On the public set the linear recipe keeps full marks on controls, scale and freq, and drops to
0.37 on compression instances (reference 0.94): it fits a biased scale and does not
predistort. So the headroom is now the skill the task names: noticing that the Rabi period
lengthens with amplitude and that the model's form, not its numbers, has to change. The
reference's remaining losses are diagnosis credits between 2 and 3 sigma.

Older notes below describe the rebuild and stay accurate except where this section updates them
(families, Rabi sweep, the "solved by known methods" verdict, runtime).

## What changed and why

- Isolation (finding 1). The solver used to run in a `multiprocessing` child that inherited the
  grader's import path, so `import harness` recovered every hidden parameter (review exploit
  pulse_import, 1.00). Now `eval/_isolate.py` (identical in all three envs) runs `python -I` in
  an empty temp dir with sys.path = [solution folder] + stdlib/site-packages, passes only
  `data`, strips the environment, and reads back JSON. `evaluate.py` re-execs once so a secret
  seed is not visible in /proc/<pid>/cmdline or environ.
- Output and seeds (findings 1, 15, 18). stdout is the score only; `--json` is gone, `--report
  PATH` writes the breakdown with truth for maintainers. Instances come from one master seed
  (`--seed N` or MISMATCH_SEED; public smoke test = master 0); instance i uses
  default_rng([master, 1, i]), kinds come from a shuffled list, all in order and deterministic.
- Scoring (finding 2). 32 instances, exactly half controls. A wrong `changed` scores 0. The
  rule for each instance (control / fix / diagnosis-only) is set from the true parameters.
  The report gives false-alarm and miss rates.
- Free credit (finding 2, brief item 6). Diagnosis credit is the product of the two parameter
  credits, so a fixed design guess earns 0 on any changed instance. Tolerances are stated in
  units of the per-instance Cramer-Rao limit (full within 2 sigma, zero at 4 sigma).
- Robust reference and metric floor (finding 7). Metric is L = log10(e_coherent + 1e-4).
  I chose an additive 1e-4 incoherent term over a T1 model: on hardware T1/T2 add an error that
  is, to first order, independent of the pulse shape, so a constant term has the same effect on
  the ranking as a Lindblad model at a fraction of the cost and with no extra parameter to
  mis-specify; 1e-4 is the order of Hyyppa 2024 (1.6e-4 at 7.9 ns). It is soft, so there is no
  threshold staircase. The oracle is now a perfect gate (L = -4), a true ceiling. The reference
  does a joint binomial maximum-likelihood fit of both traces with the exact models, a 3 sigma
  change test, and a 24-sample GRAPE pulse (exact gradients) that minimises the mean infidelity
  over s_est + k sigma_s, k = -2..2. Its pulses sit near 1e-8.5 coherent error across +-2 sigma.
- Alpha family replaced (finding 13). alpha is known and fixed (alpha ~ -E_C, geometry; the
  junction spread moves f01, Kreikebaum 2020). New family: qubit frequency drift of 10 to 80
  kHz, measured by a Ramsey trace. It brings real drift in. A 12 ns pi pulse cannot see it (the
  free virtual Z absorbs the phase; 80 kHz costs under 2e-6), so those instances are graded on
  diagnosis with a do-no-harm gate. Spectroscopy was dropped with alpha.
- Identifiability (coordinator input, Morales-Hashemi 2026). Both graded parameters are
  identifiable from the traces given: s from Rabi, delta from Ramsey (CRB 0.41 to 0.42 percent
  and 0.3 to 0.5 kHz). T2 is fitted but not graded. Nothing else is graded.
- Lazy battery in checks/ (expect.json): the review's leak (import), a stack-frame leak,
  const, malformed output, blind refit, blind robust, always-changed with fit and robust pulse.
  Checks use checks/_kit.py, written from TASK.md, not eval/.

Needless recalibration. A solver that always fits and returns a new pulse but says "no change"
scores exactly the trivial 0.500 with a robust pulse and slightly less with a DRAG refit (a noisy
refit can cost up to 0.4 decade on a control). I do not add a charge for returning a different
but equally good pulse on a control: the decision is already scored by `changed`, and the pulse
is judged on its physics only. Under the changed-gated rule that solver cannot gain anything.

## Measured (python 3.13, numpy 2.5, scipy 1.18, one process, machine shared with 2 workers)

Public = master seed 0. Secret = 5 master seeds drawn with `secrets`, mean +/- standard error
over seeds. 32 instances each.

| solution | public | secret |
|---|---|---|
| trivial | 0.500 | 0.500 +/- 0.000 |
| reference | 1.000 | 0.996 +/- 0.002 |
| sandbox starter | 0.500 | 0.500 +/- 0.000 |
| leak_import | 0.000 | 0.000 +/- 0.000 |
| leak_frames | 0.500 | 0.500 +/- 0.000 |
| lazy_const | 0.000 | 0.000 +/- 0.000 |
| lazy_malformed | 0.000 | 0.000 +/- 0.000 |
| lazy_blind_refit | 0.490 | 0.483 +/- 0.007 |
| lazy_blind_robust | 0.500 | 0.500 +/- 0.000 |
| lazy_always_changed_robust | 0.500 | 0.497 +/- 0.002 |

Every check is at or below trivial (rule: <= trivial + 0.05). Reference: no false alarms and no
misses on 192 instances; its losses are three diagnosis credits between 2 and 3 sigma (one scale,
two Ramsey frequency estimates). Per-instance standard error of the reference score on one
seed is below 0.01.

Runtime: trivial 6 to 7 s, reference 110 to 120 s for 32 instances (about 2 s per control, 4 to
7 s per changed instance including process start). Robust checks about 130 s.

## Honest assessment and remaining limits

- The task is solved by known methods: the reference scores 0.996. Once fix credit depends on
  a correct decision and the reference designs for its own error bar, nothing is left between
  it and the ceiling. I did not weaken it or retune the task. Harder honest variants would be
  continuous drift across several traces, a cost for taking more data, or decoherence-limited
  traces where the decision is close to the noise.
- The change decision is easy here: the smallest changes (2 percent scale, 10 kHz) are 5 and 20
  or more standard errors from design. The task tests whether an agent checks before reusing a
  design and designs for uncertainty, not a subtle hypothesis test.
- Exactly half of the instances are controls, so an always-changed solver with perfect physics
  ties trivial at 0.5. That is the intended floor, not headroom.
- The drive-scale and frequency ranges, T2*, shot counts, the ideal Ramsey rotations and the
  1e-4 term are assumptions (TASK.md). The 85 kHz anchor is the review's quote of Vibe
  Calibration; I did not re-read the paper.
- A solver that reads eval/ from disk can regenerate the public smoke-test set; scored runs
  must use a secret seed and a sandbox that hides eval/.

## 2026-11-18: hard tier (`--tier hard`)

Design. A 6 ns gate on a drive line twice as strong (fast gates: Hyyppa et al. 2024, arXiv
2402.17757, at 6.25 ns; Werninghaus et al. 2021, arXiv 2003.05952, at 4.16 ns). The unlisted
change: the line's transfer differs between f01 and f12, so the drive reaches the higher
transitions m times as strongly as the Duffing model says (cable and package ripple; Jerger et
al. 2019, arXiv 1706.05829; lambda = m sqrt 2 in Gambetta et al. 2011, arXiv 1011.1949). |log m|
in log 1.07 to log 1.15 (0.6 to 1.2 dB), either sign, an assumption. Rabi and Ramsey cannot see
it; a DRAG-check trace (the design pulse then its negative, repeated, then a pi/2 about y; after
Lucero et al. 2010, arXiv 1007.1690) amplifies the phase and leakage errors it causes. 12 of the
16 changed instances per set carry it, alone or with a scale or compression change. Secret seeds
are salted. No prediction was written down before these runs; the design was iterated on the
public set and on early held-out runs, and the numbers below come from one run of the frozen
design.

Measured (public set and 5 paper seeds, `experiments/results/summary_hard.md`): trivial 0.50,
reference 0.63 [0.55, 0.70], ceiling (`genie_drive12`, the reference told that m may differ from
1, never its size) 0.93 [0.86, 0.98]. Per family, reference then ceiling: m alone 0.00 then 1.00
(the reference sees no change), m with scale 0.09 then 1.00, m with compression 0.08 then 0.94,
listed families 0.95 to 1.00 for the reference and 0.80 to 0.98 for the ceiling, controls 0.97
then 0.89 (the ceiling's extra parameter costs it some false alarms). A linear-drive heuristic
scores 0.57. Lazy and leak checks: at most 0.50 (`leak_frames` and the blind refits equal
trivial), `lazy_always_other` 0.08; reference on swapped data 0.37.
