# QEC-Drift

This is a public snapshot of the benchmark: the tasks, the harness, the scoring, the fairness checks and the results. The per-episode transcripts are not in it, because some agents listed files on the machine that ran them; ask the author for access.

A benchmark for AI models that must identify a quantum noise fault and build a working error-correction decoder.

## Results

**Task pass rate (%).** Every scored cell uses the same 23 evaluation tasks. Passing requires both a correct fault diagnosis and a decoder that meets the fixed recovery thresholds.

| Model | Low | Medium | High | Very high | Maximum | Ultra |
|---|---:|---:|---:|---:|---:|---:|
| GPT-5.6-Luna | 0.0% | 0.0% | 0.0% | 4.3% | 13.0% | Not run |
| GPT-5.6-Sol | 17.4% | 17.4% | 34.8% | 30.4% | 47.8% | 30.4% |
| GPT-5.6-Terra | 0.0% | 0.0% | 4.3% | 8.7% | 26.1% | 30.4% |
| GPT-6-Astra | 60.9% | 56.5% | 56.5% | 43.5% | 65.2% | 60.9% |

Columns are the model's reasoning settings. “Not run” means the evaluation was not completed, not a 0% score. Incomplete model evaluations are documented in the paper appendix. These tasks were selected during development, so the percentages describe performance on this task set.

## Paper and analysis

- [Paper PDF: four main pages, plus references and appendix](paper/workshop-20261111/QEC_Drift_Workshop_Paper.pdf), by Logan Mann and Pranav Reddy, University of California, Santa Barbara.
- [LaTeX source and build instructions](paper/workshop-20261111/README.md).
- [L1/L2/L3 failure taxonomy](docs/failure-taxonomy.md) and [failure-analysis plots](docs/failure-atlas-20261110/index.md).
- [Fresh-seed evaluation](docs/fresh-seed-results-20261110.md) and [literature/novelty checks](paper/workshop-20261111/LITERATURE_AND_NOVELTY_AUDIT.md).

## Reproduce

```sh
uv sync --all-groups
uv run pytest -m "not slow"
```

[Benchmark instructions](docs/runbook.md). [Task specification](docs/benchmark-spec-2026-11-01.md). [Score data and metric definition](paper/workshop-20261111/evidence/model-pass-rates.json).

The public repository includes tasks, scoring, reference methods, aggregate results, and the paper. Private trajectories and scorer fixtures are excluded. Public aggregates reproduce the figures; full transcript replay requires the private evidence.
