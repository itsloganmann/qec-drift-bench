# Frozen fresh-seed analysis

This command implements the analysis specified before the existing 92 candidates were
generated. It reads results and creates a new report. It does not launch episodes, change
gates, select seeds, or tune the baseline. A prepared analysis command is not a completed study.

```sh
uv run python scripts/fresh_seed_analysis.py \
  .cache/research-continuation/fresh-seed-v1 \
  .cache/research-continuation/fresh-seed-analysis.json \
  --baseline .cache/research-continuation/visible-baseline-fresh-v1/results.json
```

All 92 reference results must be complete. The reader verifies the candidate, reference,
and scorer-manifest hashes, the frozen schedule, and any model or baseline study bindings.
The output records input and analysis-source hashes. Use a new output path for each snapshot.
The fixed baseline is reported over all 92 candidates and separately over eligible candidates.
Rejected candidates and undefined reference scores stay visible. Undefined values are not
recorded as capability failures. Model results use only eligible candidates.

Each arm reports valid episodes, attempt and pair statuses, provider interruptions, reports
present, diagnosis scores, scoring timeouts, and both pass rules. A replacement valid attempt
does not erase the earlier provider interruption. Parsed diagnosis scores may include defaults
from missing reports; the report count distinguishes submitted answers from those defaults.
A scoring timeout requires the runner's 300-second timeout marker and elapsed scoring time
of at least 300 seconds. Other scoring failures remain failures without that timeout label.

For each metric with N eligible candidates, S successes and U unresolved outcomes, the bounds
are S/N and (S+U)/N. They are completeness bounds, not confidence intervals. Observed rates
and intervals state their actual denominator. Each model pair and each model versus baseline
comparison uses only common eligible cases with defined scores. Differences are left minus
right. Empty paired sets have no estimate. Incomplete comparisons carry an availability warning;
the command does not rank arms on unmatched sets.

The fixed uncertainty procedure uses 10,000 draws with NumPy default_rng seed 20261108. It
samples observed fault families uniformly, then observed templates within each sampled family,
then eligible seed replicates within each sampled template. Each sampled cluster retains its
original member count, so the total number of rows may vary between draws. The statistic is
the pooled candidate mean or paired difference, not an average of cluster averages. All arms
with the same observed candidate set use the same draw weights. Intervals use the 2.5th and
97.5th percentiles with linear interpolation. Family and template coverage accompany estimates.

This is within-family seed replication of selected development templates. With few families,
the intervals are descriptive rather than precise population guarantees. One episode per pair
does not measure repeated model-sampling variance. Baseline-only results do not establish a
model ranking, and missing provider results do not become successes or failures.
