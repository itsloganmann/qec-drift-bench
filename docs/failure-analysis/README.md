# Failure mode and trace analysis

[Open the interactive report](index.html). Download the HTML to use both views offline.

The taxonomy view links an expandable L1, L2 and L3 tree to the failure distribution. Filter by evaluation, configuration or task family. Joint pass rates come from the stored scoring rule. The label selector switches between the scoring rule and the saved trajectory review. Each failure has one primary label. One episode can miss multiple checks.

The trace view shows the chronology of recorded excerpts, the saved review and the measured verdict. The public report includes a development example and a moving-fault example from the replication. The private report includes every failed or externally interrupted attempt and reviewed disagreement covered by the saved evidence. The report retains the 704 historical decoder records. The fresh-seed view incorporates the 56 early replication results once.

Historical reviewer inputs sometimes shortened long outputs. Some recovered archives lack full checksums. Replication reviews cover archived Codex output without middle cuts. The report lists the number of budget stops with a possible uncaptured tail. A related excerpt is a literal match located with a search term. Use it to inspect the check. A causal claim requires a controlled comparison.

## Refresh from a verified snapshot

Run after the results and trajectory audit record the same snapshot.

    uv run python scripts/failure_report.py PRIVATE_EVIDENCE_DIR docs/failure-analysis/index.html
    uv run python scripts/failure_report.py PRIVATE_EVIDENCE_DIR PUBLIC_REPORT.html --private-output /absolute/path/to/PRIVATE_REPORT.html

The public report uses grouped counts and two approved examples. Keep the private report outside the repository.
