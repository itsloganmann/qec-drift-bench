# Failure taxonomy

A failure receives one primary label. The L1/L2/L3 hierarchy is mutually exclusive and collectively exhaustive (MECE) **after passes and external invalidations are separated**. Multiple defects can occur in one trajectory; the priority rule assigns a single primary leaf rather than double counting them.

## Read the hierarchy

| L1: failure area | L2: failure class | L3: primary failure mode | Review n | Frozen-rule n |
|---|---|---|---:|---:|
| Execution / delivery | Budget or early stop | Budget exhausted |36|36|
| Execution / delivery | Budget or early stop | No submission |0|0|
| Execution / delivery | Scoring execution | Broken decoder |0|0|
| Decoder repair | Regression | Harmful decoder |72|72|
| Decoder repair | Insufficient update | Nominal unchanged |42|44|
| Decoder repair | Insufficient update | Plain fitted matching |116|117|
| Decoder repair | Insufficient update | Under-adapted |108|109|
| Diagnosis / report | Report correctness | Misdiagnosis |13|11|
| **Total failures** | | | **387** | **389** |

Population: all 533 current development episodes with exact-input transcript judgments. The review assigns 146 passes and 0 external exclusions; the frozen rule has 144 passes. Other cohorts have different task contracts and are shown separately in the [atlas](failure-atlas-20261110/index.md) and paper appendix.

## Why a leaf applies

Apply the first applicable gate:

1. Separate external invalidations and joint passes.
2. If there is no scorable decoder: budget/deadline exhaustion first, then voluntary stop with no decoder, then a present but unscorable decoder.
3. If the measured repair is worse than nominal plain matching, label it harmful.
4. If repair passes but the fault report fails, label it misdiagnosis.
5. For remaining insufficient repairs, distinguish behaviorally nominal, fitted plain matching, and the remaining under-adapted category.

Nominal behavior uses at least 99.99% prediction agreement when recorded, with source inspection as a fallback. Decoder subtypes use implementation heuristics and can miss custom algorithms. The hierarchy partitions operational labels; it is not an independently validated causal theory.

## Evidence and limits

The review is score-aware and model-assisted. Four development labels contradict a measured repair floor; they remain raw, and they do not change frozen success scores. The 47 historical environment exclusions also remain recorded as a policy dispute. Current review coverage is 760/760 score-selected decoder episodes. The old hourly publisher and recurring launchers are stopped.

The [paper](../paper/workshop-20261111/QEC_Drift_Workshop_Paper.pdf) contains the hierarchy, distribution, and an exact visible tool-action excerpt with its quoted review label. The [codebook and counts](../paper/workshop-20261111/evidence/hierarchical-taxonomy.json) and [quote provenance](../paper/workshop-20261111/evidence/trajectory-example.json) are reproducible aggregate artifacts.

Implementation: [priority tree](../src/qec_drift/scoring/taxonomy.py), [decoder adapter](../src/qec_drift/scoring/failure_modes_decoder.py), [transcript evaluator](../scripts/judge_transcripts.py). The [atlas](failure-atlas-20261110/index.md) documents source linkage, damaged-archive recovery, provisional fresh subtypes, and exact-input coverage.
