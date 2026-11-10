# Transcript judge

All **533 of 533** current development episodes have an exact-input review under `identifier-masked-v2`, using `gpt-6-astra` at medium effort. There are no missing current transcripts or pending current reviews.

This public report contains aggregate judgments. Per-episode narratives and concern evidence remain private. The original detailed report is preserved locally, and the saved judgments are unchanged.

[Broader failure-mode atlas](failure-atlas-20261110/index.md) covers historical decoder cohorts and the fresh-seed study separately. Its coverage table reports the status of the full finite audit.

Explicit model identifiers and arm paths were masked. Scaffold and tool syntax remain clues. Long rendered transcripts shorten outputs and keep their first and last sections. This is partial masking and model-assisted review, not independent human adjudication. The evaluator is also one of the model families evaluated.

687 saved judgments from older protocols are excluded. A current review must match both its exact input key and protocol.

## Agreement with the frozen rule labels

Rule and judge agree on 526/533 episodes (98.7%). Disagreements remain visible; agreement measures consistency rather than truth. Stored success scores are unchanged. Four judge labels claim sufficient repair despite drift recovery below the fixed 0.5 floor. The raw labels remain visible; this consistency check is not a full accuracy estimate.

| Label | Rule count | Judge count |
|---|---:|---:|
| Invalid harness run | 0 | 0 |
| Passed | 144 | 146 |
| Budget exhausted | 36 | 36 |
| No submission | 0 | 0 |
| Broken decoder | 0 | 0 |
| Harmful decoder | 72 | 72 |
| Diagnosis only | 11 | 13 |
| Nominal unchanged | 44 | 42 |
| Plain fitted matching | 117 | 116 |
| Under-adapted | 109 | 108 |

## Legitimacy flags

These flags are nonexclusive observations from the judge. They do not establish causality, unfairness, or cheating.

| Observation | Episodes |
|---|---:|
| Environment concern | 31 |
| Instruction concern | 0 |
| Integrity concern | 289 |
| Fairness: fair | 533 |
| Fairness: questionable | 0 |
| Fairness: unfair | 0 |

## Limits

The published atlas separates model outcomes, invalid harness runs, scorer messages and missing submissions. Fixed scoring timeouts remain failures. Sparse fresh coverage and historical task changes prevent a pooled model ranking.

The atlas JSON includes the frozen inventory, source, generator and current-judgment-set hashes. Raw transcripts, fresh candidate identities, and arbitrary judge prose are excluded from publication.
