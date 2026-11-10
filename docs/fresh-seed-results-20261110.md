# Fresh-seed within-family replication, November 10, 2026

The fixed visible-only baseline passed 27 of 92 fresh candidates under both joint pass
rules. Seven candidates failed the frozen eligibility gate. Among the 85 eligible
candidates, 26 passed. The hierarchical 95% descriptive interval was 0.116 to 0.615
for all candidates and 0.118 to 0.676 for eligible candidates.

This study changed locations and shot seeds within 23 selected development templates
across nine fault families. It measures within-family replication, not generalization to
unseen families. The visible baseline implementation was frozen at commit
`58091afb2bfd1e4afcc66ebdd136953d646bbcec`. The fresh protocol, candidate manifest,
gates, deadlines, and predictions were frozen separately before evaluation.

## Visible baseline

| Population | Candidates | Scored | Score errors | Absolute passes | Relative passes | Pass rate | Hierarchical interval |
|---|---:|---:|---:|---:|---:|---:|---:|
| All fresh candidates | 92 | 74 | 18 | 27 | 27 | 29.3% | 11.6% to 61.5% |
| Eligible candidates | 85 | 68 | 17 | 26 | 26 | 30.6% | 11.8% to 67.6% |

All 18 score errors in the full baseline reached the fixed 300-second scoring deadline
and count as failures. Adequacy was correct on 92/92 candidates, but full diagnosis was
correct on 41/92 and mechanism was correct on 36/92. The baseline therefore detected
that the nominal model was inadequate much more reliably than it identified the full
fault.

The fresh seeds changed gate eligibility as predicted. Seven candidates from four of
the 23 templates were rejected: four had no decoding gap and three had no known method
that met the recovery gate.

## Prediction readout

Both longer-dwell groups had higher localization than dwell 30. The dwell-40 mean was
slightly above dwell 60, while its median was lower. Dwell is mixed with other template
attributes, so this comparison is descriptive and confounded. The table includes every
localized baseline row whose drift string has an explicit trailing dwell.

| Trailing dwell | Rows | Mean localization | Median localization |
|---|---:|---:|---:|
| 30 | 20 | 0.409 | 0.334 |
| 40 | 8 | 0.649 | 0.632 |
| 60 | 20 | 0.630 | 0.717 |

Localization over-reporting was clear. In 80 localized cases, the baseline predicted
more qubits than truth in 71, the same number in six, and fewer in three. It predicted
27.875 qubits on average against 15.913 true qubits, with 12.063 false-positive qubits
on average.

The larger-decoder timeout prediction was also supported. All 16 distance-7 candidates
timed out during scoring, compared with two of 72 distance-5 candidates and none of four
distance-9 candidates. Distance alone is not a runtime model because the templates and
decoder paths also differ.

## Model episodes

The frozen schedule contains 5,336 arm and candidate pairs, of which 4,930 are eligible.
The run completed 56 valid Codex episodes across 22 arms. Fifty-three returned scores,
three returned score errors, 14 passed the absolute rule, and 13 passed the relative
rule. Score errors count as failures.

Coverage stopped at the credential-lifetime safety gate. The latest Codex usage reading
was 63%, below the 85% quota threshold, but the access credential had less than the
required 61 minutes remaining for a bounded episode. Claude usage probes returned
`JSONDecodeError`, so no Claude episode was admitted. Missing Claude episodes are
omissions, not capability failures.

Only 38 comparisons had any matched candidates. Nineteen had one matched candidate,
eight had two, seven had three, three had four, and one had six. The largest comparison
therefore covered 6/85 eligible candidates. Availability selection and unequal coverage
make these comparisons unsuitable for arm or model ranking.

## Interpretation and evidence

The baseline shows modest joint success with broad uncertainty, perfect adequacy
classification, and weak full diagnosis. The preregistered over-reporting and
larger-decoder timeout predictions were supported. The dwell prediction had directional
but confounded support. The model sample is
credential-censored, sparse, and unmatched, so it supports execution counts only.

The intervals resample families, templates within families, and replicates within
templates for 10,000 draws with the frozen seed. There are few families, and one episode
per arm and candidate does not estimate model-sampling variance. All timeouts and score
errors remain failures.

[Machine-readable aggregate results](../data/audits/fresh-seed-closeout-20261110.json)
contain the counts, intervals, prediction readout, stop reason, comparison denominators,
and input hashes. Candidate manifests, scorer fixtures, schedules, model trajectories,
and per-candidate outcomes remain private.
