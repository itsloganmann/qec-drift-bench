# Visible-only diagnosis baseline v1

This is a fixed custom baseline for the 23 selected development tasks and a later fresh-seed study within the same task families. It is not a reproduction of DGR or evidence of transfer to unseen fault families. Development observations informed the design. No development result was used to tune this implementation after freezing.

The fit receives only the nominal circuit, labeled train and validation shots, and unlabeled deploy shots in an opaque folder. Version 1 uses the nominal circuit and deploy detector events. Private task names, seeds, planted sites, regimes and hidden observables are not inputs. The fit runs in the existing no-network file sandbox for at most 3600 seconds. The decoder runs through the unchanged scorer with its 300-second deadline. Every candidate remains in the denominator, including unsupported inputs, timeouts and exceptions.

## Fixed diagnosis

Adequacy compares deploy detector means with 20,000 nominal simulated shots using seed 0. The statistic is the maximum absolute difference divided by sqrt(p*(1-p)*(1/n+1/m)), where p is the pooled detector rate clipped to [0.0001,0.9999]. Calibrate with 99 whole-shot label permutations from a new RNG with seed 1 for each bundle. The p-value is (1+number of null statistics at least as large as observed)/100. Reject adequacy at p<=0.01. This tests these detector statistics, not all possible physical departures.

Stationarity uses non-overlapping blocks of 32, 128 and 512 shots. A scale needs at least four blocks. Discard its incomplete final block. For each scale, compute its pooled detector mean p from that same complete prefix and the maximum absolute block-rate deviation divided by sqrt(clip(p)*(1-clip(p))/block_size). The test statistic is the maximum over all eligible scales, blocks and detectors. Calibrate the entire statistic with 99 whole-shot order permutations using a new RNG with seed 2, identical truncation and inclusive ties. Report nonstationary at p<=0.01. With fewer than 128 shots, return unsupported without a report. This test detects order dependence, not every hidden IID mixture of shotwise regimes.

For an inadequate model, build the existing Adaptive bank with simulation seed 0. Union qubits in hypotheses assigned to at least 50 deploy shots. Preserve the complete bank, including hypotheses not selected during deploy. Reject qubit indices outside the nominal circuit's QUBIT_COORDS set Q. Report global if the union includes at least ceil(len(Q)/2) qubits, otherwise local. An empty union stays local and can fail. An adequate model reports scope none. Local with stationary=false uses the existing scorer's moving/local equivalence. This version preserves the known localization over-reporting limitation.

Report mechanism none for adequate, all for local and readout for global. The global mechanism is a limited prior for the current template inventory. Mechanism remains a separate score. Confidence is fixed at 50; permutation p-values are not posterior confidence.

## Decoder and artifact format

Adequate uses nominal correlated matching. Global uses pairwise-refit correlated matching fitted on deploy. Local uses Adaptive with seed 0. All hidden decoding uses only detector inputs.

Local fitted state has format `visible-adaptive-v1`: JSON metadata for all hypotheses and the likelihood margin; numeric/boolean NPZ arrays for base rates, likelihood weights and support masks; and text DEMs only for keys encountered during visible deploy. No pickle is used. Decoder loading reconstructs the whole bank and those warm matchers inside the scoring deadline. Unseen hidden keys construct their matcher inside that deadline. No hidden detector or observable enters fitting or warmup. Other modes serialize their fitted DEM as text.

The runner freezes source hashes, export hashes, Python and dependency versions, OS/architecture and limits before its first case. It grades against hash-verified exported truth. Each case and interrupted attempt is saved. Resume requires the same source, inputs, runtime and limits; completed failures are retained. Historical model score tables are not changed.

For fresh candidates with undefined reference rates, keep available diagnosis and decoder observations and report null joint scores. Keep these candidates in the inventory. Defined but degenerate gaps still fail under the existing rule. This reporting fix does not change the frozen method or completed development results.

## Predictions before evaluation

The adequacy test should have limited false positives on adequate IID tasks. Sustained switching should be easier for the time-order test than IID mixtures. Localization should still over-report on some tasks, causing joint failures. Adaptive decoding may exceed 300 seconds on larger circuits. No minimum pass count is assumed, and no timeout is excused as an environment failure.

Run with `uv run python scripts/evaluate_visible_baseline.py EXPORT OUTPUT`. Keep OUTPUT private because it contains scorer results and provenance. The exported development fixtures do not become held-out merely by rerunning them. A fresh-seed study must freeze its candidate population and model grid separately before model calls.

## Completed development run

The frozen run finished all 23 cases on November 8. Four passed both joint rules. Adequacy was correct on 23/23, stationarity on 22/23, and full diagnosis on 6/23. Four d=7 decoders hit the fixed 300-second scoring timeout and remain failures. See the [November 9 audit](development-audit-20261109.md) for the prediction readout, all-case evidence, and reference sensitivity analysis.
