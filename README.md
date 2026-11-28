# Quantum Agent Bench

Quantum Agent Bench tests whether AI agents can diagnose and repair drift in three simulated stages of a superconducting quantum computer. Explore the [interactive walkthrough](https://quantum-agent-bench.pages.dev/) or open the [Kaggle notebook](https://www.kaggle.com/code/loganmann24/quantum-agent-bench).

## Three environments

| Environment | What the agent sees | What it submits | How it is scored |
|---|---|---|---|
| [Control pulses](https://github.com/pkarakala/qec-drift-bench/blob/7c3804ca5e02063c8e378926e0d2830d945e7161/mismatch/pulse_wrong_model/TASK.md) | A nominal transmon model, a control pulse, and calibration traces | A drift diagnosis and a revised X-gate pulse | Gate error on the simulated device |
| [Error correction](https://github.com/pkarakala/qec-drift-bench/blob/7c3804ca5e02063c8e378926e0d2830d945e7161/mismatch/qec_drift_d3/TASK.md) | A Stim surface-code circuit and detector samples before and after a possible change | A diagnosis and a Stim detector error model for a fixed decoder | Diagnosis and logical error recovery on held-out shots |
| [Readout](https://github.com/pkarakala/qec-drift-bench/blob/7c3804ca5e02063c8e378926e0d2830d945e7161/mismatch/readout_drift/TASK.md) | Labeled calibration measurements and eight unlabeled IQ batches | A drift diagnosis and Gaussian discriminator parameters | State assignment error on held-out measurements |

The structured-output tasks follow the [public mismatch-track draft](https://github.com/pkarakala/qec-drift-bench/pull/1). The original error-correction track asks the agent to write a decoder. See the [scored Kaggle pilots](docs/kaggle-benchmarks-port.md) for results from all three structured tasks.

## Error-correction results

**Task pass rate (%).** Every scored cell uses the same 23 tasks selected during development. A task passes when the diagnosis is correct and the decoder meets the recovery thresholds on held-out measurements.

| Model | Low | Medium | High | Very high | Maximum | Ultra |
|---|---:|---:|---:|---:|---:|---:|
| GPT-5.6-Luna | 0.0% | 0.0% | 0.0% | 4.3% | 13.0% | N/A |
| GPT-5.6-Sol | 17.4% | 17.4% | 34.8% | 30.4% | 47.8% | 30.4% |
| GPT-5.6-Terra | 0.0% | 0.0% | 4.3% | 8.7% | 26.1% | 30.4% |
| GPT-6-Astra | 60.9% | 56.5% | 56.5% | 43.5% | 65.2% | 60.9% |

Columns show reasoning settings. Ultra enables automatic delegation. N/A marks an unsupported setting.

The replication is in progress. It covers the same 85 tasks for each of 23 supported configurations, for 1,955 evaluations. [Latest audited progress](data/audits/codex-replication-progress.json).

## Papers and analysis

- [Quantum Agent Bench paper](paper/workshop-20261111/Quantum_Agent_Bench.pdf) covers control pulses, error correction, and readout.
- [Original error-correction paper](paper/workshop-20261111/QEC_Drift_Workshop_Paper.pdf) documents the executable-decoder study.
- [LaTeX source and build instructions](paper/workshop-20261111/README.md).
- [Interactive failure taxonomy and trace analysis](docs/failure-analysis/README.md) and [failure-analysis plots](docs/failure-atlas-20261110/index.md).
- [Early replication results](docs/fresh-seed-results-20261110.md) and [literature review](paper/workshop-20261111/LITERATURE_AND_NOVELTY_AUDIT.md).

## Reproduce

```sh
uv sync --all-groups
uv run pytest -m "not slow"
```

[Benchmark instructions](docs/runbook.md). [Data-out tasks](envs/README.md): the same diagnose-and-fix question on other parts of the device, where the agent returns data instead of code. [Original benchmark specification](docs/benchmark-spec-2026-11-01.md). [Score data and metric definition](paper/workshop-20261111/evidence/model-pass-rates.json).

The public repository includes tasks, scoring, reference methods, aggregate results, and the paper. Public aggregates reproduce the figures. Full transcript replay requires private evidence.
