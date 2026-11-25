# QEC-Drift

This is a public snapshot of the benchmark: the tasks, the harness, the scoring, the fairness checks and the results. The per-episode transcripts are not in it, because some agents listed files on the machine that ran them; ask the author for access.

The agent gets a baseline quantum circuit in Stim format and simulated error-detection measurements, then diagnoses any noise change and writes a decoder to predict logical errors on unseen measurements.

Stim simulates the noisy quantum circuits. PyMatching provides the matching algorithm for the reference decoders. [Stim](https://github.com/quantumlib/Stim) and [PyMatching](https://pymatching.readthedocs.io/en/stable/).

## Results

**Task pass rate (%).** Every scored cell uses the same 23 tasks selected during development. A task passes when the diagnosis is correct and the decoder meets the recovery thresholds on held-out measurements.

| Model | Low | Medium | High | Very high | Maximum | Ultra |
|---|---:|---:|---:|---:|---:|---:|
| GPT-5.6-Luna | 0.0% | 0.0% | 0.0% | 4.3% | 13.0% | N/A |
| GPT-5.6-Sol | 17.4% | 17.4% | 34.8% | 30.4% | 47.8% | 30.4% |
| GPT-5.6-Terra | 0.0% | 0.0% | 4.3% | 8.7% | 26.1% | 30.4% |
| GPT-6-Astra | 60.9% | 56.5% | 56.5% | 43.5% | 65.2% | 60.9% |

Columns show reasoning settings. Ultra enables automatic delegation. N/A marks an unsupported setting.

The replication is in progress. It covers the same 85 tasks for each of 23 supported configurations, for 1,955 evaluations. [Latest audited progress](data/audits/codex-replication-progress.json).

## Paper and analysis

- [Paper PDF: four main pages, plus references and appendix](paper/workshop-20261111/QEC_Drift_Workshop_Paper.pdf), by Logan Mann and Pranav Reddy, University of California, Santa Barbara.
- [LaTeX source and build instructions](paper/workshop-20261111/README.md).
- [Interactive failure taxonomy and trace analysis](docs/failure-analysis/README.md) and [failure-analysis plots](docs/failure-atlas-20261110/index.md).
- [Early replication results](docs/fresh-seed-results-20261110.md) and [literature review](paper/workshop-20261111/LITERATURE_AND_NOVELTY_AUDIT.md).

## Reproduce

```sh
uv sync --all-groups
uv run pytest -m "not slow"
```

[Benchmark instructions](docs/runbook.md). [Original benchmark specification](docs/benchmark-spec-2026-11-01.md). [Score data and metric definition](paper/workshop-20261111/evidence/model-pass-rates.json).

The public repository includes tasks, scoring, reference methods, aggregate results, and the paper. Public aggregates reproduce the figures. Full transcript replay requires private evidence.
