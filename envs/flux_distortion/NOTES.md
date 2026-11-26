# flux_distortion: notes (version 1, 2026-11-26)

The fourth environment, and the first built through the acceptance standard
(docs/STANDARD.md). Its acceptance card is in docs/acceptance.md.

## Why this task

Two-qubit gates on flux-tunable transmons need the flux pulse to arrive with its intended shape;
every lab with such qubits measures the line's step response and predistorts (Rol 2020, arXiv:
1907.04818; Hellings 2025, arXiv:2503.04610; Venkateswaran 2026, arXiv:2604.15895). It is the
calibration step just below the CZ gate, a layer the first three environments do not cover.

## Design choices

- Line model: a cascade of first-order stages, each a decaying exponential in the step response
  (Hellings 2025 Eq. 1 fits a sum of four exponentials; for percent-level tails a cascade and a
  sum differ at second order, and a cascade is what a stack of IIR inverses corrects exactly).
- The solver returns data: stages to invert and optional FIR taps. The grader applies them to a
  test program it holds and passes the result through the true line, so no solver code touches
  the truth or the test program.
- The change call is defined by effect size (stale test-program error against a floor of
  (5e-4)^2, the Hellings 2025 residual), with draw rules that leave a gap: changed instances at
  2 x floor or more, controls at 0.5 x floor or less. Every instance has wander, which the
  cryoscope can see (a 3% wander of a 3% tail is 1e-3 at short times, one sigma per point), so
  "something moved" is not the same as "changed".
- A new tail is drawn at least 2.5 times away from every nominal time constant, and TASK.md
  says so; nearer, a new tail and a changed stage explain the same data.
- Diagnosis tolerances are 2 to 4 Cramer-Rao sigma with every stage's amplitude and time
  constant free, so the wander is a nuisance parameter in the bound, as it is for the solver.
- Hard tier: part of the pulse arrives late, s(t) = 1 - r before a delay d and 1 after
  (impedance mismatch; named as a distortion source by Rol 2020 and Hellings 2025, sizes not
  given there, so r 0.5% to 2% and d 2 to 20 ns are assumptions). No stage can model it; the
  FIR filter can correct it.

## Measured (2026-11-26, cloud, one core per run)

Mean over the paper seeds (10 standard, 5 hard) with 95% intervals, public set in brackets
(experiments/results/summary.md and summary_hard.md).

| solution | standard | hard |
|---|---|---|
| trivial (stale predistortion, "no change") | 0.50 (0.50) | 0.50 (0.50) |
| reference | 0.96 [0.95, 0.97] (0.97) | 0.80 [0.75, 0.84] (0.76) |
| reference without the fix / without the diagnosis | 0.71 / 0.75 | n/a |
| genie_echo (told the echo's form; ceiling) | n/a | 0.96 [0.94, 0.98] (0.93) |
| best lazy or leak check on secret seeds | 0.50 | 0.50 |

The reference's remaining standard-tier losses are instances with both kinds, where it reports
only the changed stage. On the hard tier it never reports "other" and its stages cannot model
the echo. The genie profiles the echo size out of every fit in closed form; its own misses are
echo plus new tail (it reports a changed stage) and echoes shorter than 2.5 ns, which look like
the first stage. Every gate is in docs/acceptance.md.

## Limits

- Amplitude bands of the nominal stages and the drift ranges are assumptions: the cited papers
  fit such tails, but the values are in figures we could not read as text.
- The data is the reconstructed step response, not the raw cryoscope phases; reconstruction
  error is folded into the stated Gaussian noise.
- Not yet run by any agent; gate S1 (best agent passes under 75%) is pending.
