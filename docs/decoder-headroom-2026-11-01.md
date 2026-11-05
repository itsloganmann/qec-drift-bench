# Decoder headroom, 2026-11-01

Measured with Stim 1.16 and PyMatching 2.4 on rotated surface-code memories (d rounds), 200,000
shots per cell (40,000 for BP plus matching). Logical error rate per shot. Script:
`src/qec_drift/agent/decoder_task.py`. These numbers are from a scratch run; the harness
recomputes them for the six tasks.

## Plain matching against correlated matching (uniform depolarizing noise)

| d | p | plain | correlated | ratio |
| --- | --- | --- | --- | --- |
| 5 | 0.003 | 0.00348 | 0.00261 | 0.75 |
| 5 | 0.005 | 0.01374 | 0.01076 | 0.78 |
| 7 | 0.003 | 0.00142 | 0.00067 | 0.47 |
| 7 | 0.005 | 0.01008 | 0.00621 | 0.62 |

## Per-qubit noise the nominal model lacks (lognormal scale sigma = 1.0)

Matching with the true weights lowers the error by 12% to 17% against nominal weights
(d = 5: 0.83, d = 7: 0.85 to 0.88). Correlated matching with the true weights lowers it by
40% to 54%.

## Unmodelled crosstalk (DEPOLARIZE2 on neighbouring data qubits each round)

| d | p | q | oracle weights | oracle + correlated |
| --- | --- | --- | --- | --- |
| 5 | 0.003 | 0.002 | 0.93 | 0.69 |
| 5 | 0.003 | 0.005 | 0.85 | 0.65 |
| 7 | 0.003 | 0.002 | 0.81 | 0.46 |
| 7 | 0.003 | 0.005 | 0.70 | 0.43 |

Ratios are against plain matching on the nominal model.

## Above correlated matching

BP plus matching (beliefmatching) adds 3% to 9% on top of correlated matching on the same
circuits (d = 5 and 7, p = 0.003 and 0.005). Off-the-shelf decoders leave a small gap above
correlated matching under these noise models.

## Reading

The ladder has real steps: correlated matching (a documented option), then knowing the true
noise, then a small gain from BP. The largest single step is correlated matching. An agent
that sets one flag can reach about half of the gap, so the task must also test the harder
step: learning the unmodelled noise from shots.
