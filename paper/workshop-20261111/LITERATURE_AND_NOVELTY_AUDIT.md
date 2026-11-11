# Literature and novelty audit

Search and verification date: 11 November 2026. This is a targeted novelty check for the completed QEC-Drift decoder audit, not a systematic review of all quantum computing or agent research. The older approximation-validity project in the repository is a different study; its unverified literature notes were not imported as evidence.

## Verification standard

The bibliography contains 20 real papers. Nineteen were checked against their official arXiv records, actual downloaded paper PDFs, and DataCite DOI records. Five journal records were additionally checked through Crossref, including the one paper accessed directly through its journal PDF. Titles, the cited author names, publication or preprint years, and DOI/URL destinations were checked. Publisher metadata governs the journal entries; preprint entries deliberately identify themselves as arXiv rather than inventing a publication venue.

The first page of the RL-control preprint uses a collective institutional byline. Its individual authors were verified in the full paper and the Nature/Crossref record. The Spitz journal title includes “in a Time-Dependent Environment”; this is the verified journal title, although the arXiv metadata uses a shorter title. The AlphaQubit 2 citation uses the initial preprint year, 2025, while the retrieved PDF is the revised March 2026 version. These are version differences, not different papers.

The online SSI environment is a verified project artifact, not a paper. It is identified as such in a footnote and does not occupy a bibliography entry. Third-party search snippets were used for discovery only. No uncertain or unverified paper remains in the bibliography. Verification details are in `evidence/reference-verification.json`, `evidence/arxiv-metadata.json`, and the five `evidence/crossref-*.json` records. Downloaded third-party PDFs are retained locally for checking and excluded from the distributable source bundle.

## Search record

The searches covered four neighborhoods: adaptive/learned QEC decoding, quantum coding-agent evaluations, general scientific-agent evaluations, and trajectory/judge reliability. Queries included:

- `large language model agents quantum error correction decoding benchmark noise drift diagnosis repair`
- `quantum error correction decoder noise drift calibration correlation adaptive decoding`
- `LLM agent quantum error correction benchmark AlphaQubit QECBench`
- `DGR Decoders Tackling Noise Drift and Correlated Noise arxiv`
- `surface code decoding SSI index agent benchmark scientific research`
- `LLM benchmark quantum error correction diagnose noise decoder agent benchmark 2026`
- `quantum computing agent benchmark decoder drift`
- `quantum coding benchmark QCoder Qiskit code LLM QuantumBench 2025 2026`
- `Why Do Multi-Agent LLM Systems Fail arxiv`
- `science agents benchmark Scientist-Bench ScienceAgentBench PaperBench SciCode`
- Exact-title and identifier searches for each retained reference, followed by official-record and PDF checks.

Sources were screened for a concrete overlap with the paper's task, evaluation method, or failure analysis. Primary abstracts and relevant method descriptions support the scope distinctions below. Search absence cannot establish priority, and the paper makes no universal “first” claim. New papers after the search date may narrow the contribution further.

## Source-by-source overlap and claim support

| Key | Verified primary source | What overlaps | Defensible distinction or use in this paper | Locator |
|---|---|---|---|---|
| `spitz` | Spitz et al., 2018, [DOI](https://doi.org/10.1002/qute.201800012) | Infers matching weights from syndrome data in a changing environment. | Prior art for adaptive noise estimation. QEC-Drift does not introduce adaptive decoding. | Abstract and adaptive-weight method. |
| `dgr` | Wang et al., 2023 preprint, [arXiv:2311.16214](https://arxiv.org/abs/2311.16214) | Reweights decoding graphs for drift and correlated errors. | Prior method, not an implemented baseline reproduction in this audit. | Abstract; alignment and correlation reweighting sections. |
| `alpha` | Bausch et al., 2024, [DOI](https://doi.org/10.1038/s41586-024-08148-8) | Learns surface-code decoding with a recurrent transformer. | Establishes learned decoding; no superiority claim is made against it. | Abstract and decoder architecture. |
| `alpha2` | Senior et al., 2025 preprint, [arXiv:2512.07737](https://arxiv.org/abs/2512.07737) | Scalable, real-time learned topological-code decoding. | Relevant performance context; QEC-Drift does not test latency on a physical processor. | Abstract; revised PDF first page. |
| `rl` | Sivak et al., 2026, [DOI](https://doi.org/10.1038/s41586-026-10759-2) | Uses QEC detection signals to steer physical controls against drift. | Experimental autonomous adaptation predates this paper. Our agents write software in simulation. | Abstract and injected-drift experiment. |
| `stim` | Gidney, 2021, [DOI](https://doi.org/10.22331/q-2021-07-06-497) | Stabilizer-circuit simulation. | Simulator dependency and scope of ground truth. | Abstract and simulator description. |
| `sparse` | Higgott and Gidney, 2025, [DOI](https://doi.org/10.22331/q-2025-01-20-1600) | Efficient minimum-weight matching. | Decoding infrastructure, not evidence that our custom adaptive reference is literature-equivalent. | Abstract and implementation. |
| `stabilizer` | Paz et al., 2026, [arXiv:2604.21287](https://arxiv.org/abs/2604.21287) | Agent-assisted QEC circuit synthesis with verification. | QEC agents and simulator verification are prior art. Our output is a deployment decoder plus explicit noise diagnosis. | Abstract; task definitions. |
| `qcoder` | Mikuriya et al., 2025, [arXiv:2510.26101](https://arxiv.org/abs/2510.26101) | Quantum code generation with simulator feedback. | Prior quantum programming evaluation; not a new category invented by QEC-Drift. | Abstract; benchmark formulation. |
| `quanbench` | Slim et al., 2026, [arXiv:2604.08570](https://arxiv.org/abs/2604.08570) | Quantum code generation across multiple frameworks. | Related programming benchmark rather than a planted physical drift-and-diagnosis contract. | Abstract; aligned task design. |
| `apidrift` | Rasyidi and Faiz, 2026, [arXiv:2607.04072](https://arxiv.org/abs/2607.04072) | Quantum code failure and documentation-guided repair under SDK changes. | Software API drift differs from the physical noise drift in this study. | Abstract; version-fidelity protocol. |
| `quantumaudit` | Seefried et al., 2026, [arXiv:2610.28678](https://arxiv.org/abs/2610.28678) | Quantum-code benchmark and evaluator defects; output validity and uncertainty. | Closest evaluation-audit precedent. This paper cannot claim to discover evaluator failure in quantum coding. | Abstract; evaluator audits. |
| `scicode` | Tian et al., 2024, [arXiv:2407.13168](https://arxiv.org/abs/2407.13168) | Scientist-curated research coding. | Prior broad scientific coding evaluation; ours separates planted-fault diagnosis from executable recovery in one domain. | Abstract; benchmark construction. |
| `scienceagent` | Chen et al., 2024 preprint, [arXiv:2410.05080](https://arxiv.org/abs/2410.05080) | Data-driven scientific tasks completed by language agents. | Prior scientific workflow evaluation; no broad “first scientific-agent benchmark” claim is warranted. | Abstract; task extraction and grading. |
| `mle` | Chan et al., 2024 preprint, [arXiv:2410.07095](https://arxiv.org/abs/2410.07095) | Kaggle-derived machine-learning engineering competitions. | Relevant to the intended Kaggle readership and artifact-based evaluation, not an executed Kaggle run here. | Abstract; competition/evaluation setup. |
| `paperbench` | Starace et al., 2025, [arXiv:2504.01848](https://arxiv.org/abs/2504.01848) | Agents replicate research, with explicit grading. | Research-workflow precedent. A generated paper alone is not evidence of a completed experiment. | Abstract; task and grading descriptions. |
| `scigym` | Shen et al., 2026, [arXiv:2602.12984](https://arxiv.org/abs/2602.12984) | Multistep scientific tool use. | Broad tool-use evaluation precedes this domain-specific audit. | Abstract; environment and evaluation suite. |
| `sciarena` | Liu et al., 2026, [arXiv:2606.12736](https://arxiv.org/abs/2606.12736) | Scientific agent challenges across scales. | Broad scientific-agent research context, not a baseline result compared numerically here. | Abstract; benchmark scope. |
| `mast` | Cemri et al., 2025, [arXiv:2503.13657](https://arxiv.org/abs/2503.13657) | Empirical trajectory taxonomy, including expert annotation. | Failure taxonomies are established. Our priority tree is decoder-specific and lacks independently established human agreement. | Abstract; taxonomy and annotation method. |
| `judge` | Zheng et al., 2023, [arXiv:2306.05685](https://arxiv.org/abs/2306.05685) | LLM judging, agreement, and biases. | Supports treating automated agreement as fallible. The four QEC-Drift contradictions come from our own consistency audit. | Abstract; limitations of model judges. |

Separate verified project artifact: [OpenSSI surface-code environment](https://openssi.dev/ssi-index/environments/surface-code-decoding/), “The task”, “What the agent develops”, and “How it is judged”. It already evaluates an agent developing a surface-code decoder from experimental data. Our paper therefore does not claim the first agent-written QEC decoder.

## Claim boundary

The supported contribution combines: (1) nominal-to-deployment noise shift; (2) explicit scope, temporal behavior, and localization diagnosis; (3) an executable decoder graded on hidden simulated observables; (4) separate diagnosis and recovery measurements with a joint threshold; and (5) a score-linked audit retaining exclusions and judge contradictions. The literature search supports positioning this combination as a specific benchmark/audit contribution. It does not prove global novelty, a new physical decoding method, broad frontier-model rankings, causal failure mechanisms, unseen-family generalization, or workshop acceptance.
