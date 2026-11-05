# Pass 1: LLM and agent benchmarks for quantum computing and QEC, 2023 to 2026

Survey notes compiled 2026-11-01. Every row had its arXiv abstract page or GitHub README fetched and
its title confirmed. Headline: no published, released benchmark has an LLM agent write a QEC
decoder that Stim grades under a controlled noise-model mismatch. Three items come close
(QIQCBench, an unmerged Frontier-Engineering decoder task, StabilizerBench) and each misses at
least one of: decoder code, stochastic noise, a mismatch axis, public release.

| Name | Year | Id or URL | What it measures | Task format | Grader | Models | Agent writes decoder or circuit, simulator grades? |
|---|---|---|---|---|---|---|---|
| Qiskit HumanEval | 2024 | 2406.14712 | 151 Qiskit function tasks | code gen | unit tests | unnamed | No |
| Qiskit HumanEval-hard | 2025 | 2508.20907 | 151 tasks, imports stripped | code gen | unit tests, hardware rewards | Qiskit Code Assistant, Qwen2.5-Coder | No |
| QCircuitBench (was QCircuitNet) | 2024 to 2025 | 2410.07961 | 25 algorithms, 3 suites, 120k points | code gen | validation functions | GPT-3.5, GPT-4, fine-tunes | No |
| QHackBench | 2025 | 2506.20008 | 49 PennyLane QHack challenges | code gen and repair agents | execution tests | unnamed | No |
| QuanBench | 2025 | 2510.16779 | 44 (117) tasks | code gen | Pass@k, process fidelity | unnamed | No |
| QCoder | 2025 | 2510.26101 | 67 contest problems, hardware constraints | code gen | simulator feedback; Claude judge in Arena | GPT-4o 19%, o3 78% | No |
| QuanBench+ | 2026 | 2604.08570 | 42 tasks across Qiskit, Cirq, PennyLane | code gen and repair | executable tests, KL | unnamed | No |
| Qiskit QuantumKatas | 2026 | 2605.27210 | 350 tasks, 26 categories, incl. bit-flip QEC katas | code gen | deterministic tests | 16 LLMs | No |
| QASM-Eval | 2026 | 2605.30358 | 1,200 OpenQASM3 tasks: feedback, timing, pulse | code completion | verifier | Llama-3 FT, GPT-5.6-Terra | No |
| QEncodeBench | 2026 | 2609.20319 | phase-oracle encoding | code gen or agent | adversarial verifier | unnamed | No |
| QTestBench | 2026 | 2610.13811 | quality of LLM-written tests, 18 tasks | code gen | checkers and mutants | 5 LLMs | No |
| QBugLM | 2026 | 2606.07314 | OpenQASM3 bug repair | agentic | simulation | Claude 4.6 Sonnet, Qwen3 Coder | No |
| quantum-api-drift | 2026 | 2607.04072 | 50 tasks, Qiskit version fidelity | code gen | execution per SDK version | 17 incl. Claude Opus 4.7 | No |
| Quantum Leap audit, QBE, Quantum Arena | 2026 | 2610.28678; github QSCSoftwareEcosystem/quantum-leaderboard | audit of 5 suites (530 tasks) plus 96 QBE | code gen | unit tests | 15 models | No |
| Agent-Q | 2025 | 2504.11109 | 14k QAOA and VQE circuits | code gen | expectation values | unnamed | No |
| QAgent | 2025 | 2508.20134 | 12 kernels, calibration under frequency drift | agent | Pass@1, fidelity | 5 LLMs | No |
| QUASAR | 2025 | 2510.00967 | QASM generation via agentic RL | code gen | simulator | 4B vs GPT-5 | No |
| QuantumBench | 2025 | 2511.00092 | about 800 MCQ, 9 areas | QA | exact match | unnamed | No |
| Quantum-Audit | 2026 | 2602.10092 | 2,700 questions | QA | accuracy | 26; Opus 4.5 84% | No |
| QC-Stark | 2026 | 2609.35581 | 11 tasks, incl. T11 syndrome-to-error identification | QA and code, auto-verified | execution | 10 models | No |
| CURIE (QECC task) | 2025 | 2503.13517 | 65 QEC papers to Error Correction Zoo YAML | extraction | ROUGE-L, LMScore | Gemini, Claude-3, GPT-4o | No |
| QuantumLLMInstruct | 2024 | 2412.20956 | 500k synthetic pairs | training data | LLM judge | n/a | No |
| QIQCBench and Quantum-Harbor | 2026 | 2609.17439 | 49 lab tasks; QEC: decoder calibration, logical memory, lattice-surgery CNOT on a simulated 114-qubit transmon grid with hidden correlated seam noise | agent with tools in a sandbox | hidden grader replays on fresh syndromes | 17 systems: GPT-5.6 sol, terra, luna; DeepSeek V4.1 Flash, V4 Pro, V4 Flash; GLM-5.3, 5.3 Flash, 5.2; Claude Opus 4.8, Haiku 4.5; Qwen3.8 Max, Flash; Hunyuan T3, T4; Kimi K3; Seed 2.1 Pro | Partial: submits decoder configurations, not code |
| QCTRL-BENCH | 2026 | 2605.26021 | 16 control tasks, open and noisy | LLM proposes analytic ansatz | fidelity simulation | unnamed | No (control protocol) |
| QMP-Bench | 2026 | 2604.00149 | 100 many-body tasks | agent | code plus physics verifiers | unnamed | No |
| Agents' Infinite Game in Quantum (UCSB) | 2026 | agents-infinite-game.org | 5 agent-generated environments: metrology, Hamiltonian simulation, flux iSWAP control | agent writes code, 28 qubits max | normalized figure of merit | one solver agent | No QEC yet |
| science-speedrun surface-code-decoding | 2026 | github sunnweiwei/science-speedrun; HF sunweiwei/ai4sci-surface-code-decoding | train a neural decoder on Sycamore data, 8xH100 for 48 h | agent writes training code (Harbor format) | held-out verifier; agent 0.7626, baseline 0.7557, reference 0.7615 | Codex, Claude Code, Antigravity | Yes, real data, not Stim |
| Frontier-Engineering PR 114 | 2026 | 2604.12290; github Einsia/Frontier-Engineering/pull/114 | 47 optimization tasks; the PR adds surface-code decode() graded by Stim and PyMatching with sealed noise strengths, separate interpreter, no stim or pymatching import, wall-clock budget | agent edits program | frozen verifier; score (log L_trivial - log L)/(log L_trivial - log L_mwpm) | Claude Opus 4.6, GPT-5.4, Gemini 3.1 on the main suite | Yes in the PR; PR open, unmerged |
| StabilizerBench | 2026 | 2604.21287 | 192 codes; preparation, optimization, flag-FT circuits | agent emits Stim circuits | Stim tableau; single-fault FT score | Claude Opus 4.6, GPT-5.2, Gemini 3 Pro | Yes for circuits; no decoders, no stochastic noise |
| OmniQEC | 2026 | 2607.25865 | qLDPC discovery; Stim circuit-level p = 0.005; BP+OSD | LLM writes code constructions | Stim plus BP-OSD LER | Claude Opus 4.8, GPT-5.5, DeepSeek-V4-Pro | Partial: codes, decoder fixed |
| BB code evolution (IBM) | 2026 | 2606.02418 | 465 codes via program mutation | program evolution | distance, MILP | unnamed | No simulator |
| Multi-agent qLDPC discovery | 2026 | 2608.08996 | balanced-product codes | multi-agent | BP-OSD code capacity | unnamed | Partial |
| SCE qLDPC discovery | 2026 | 2606.24808 | lifted-product codes | concept evolution | BP+OSD | GPT-5.4-mini and nano | Partial |
| QEC encodings for molecules | 2026 | 2606.25870 | fermion-to-qubit codes | program evolution | distance verifier | unnamed | Partial |
| Multi-agent QEC code gen (DAC 2025) | 2025 | 2504.14557 | one surface-code decoder agent example | agent | one qualitative example | StarCoder-3B | Weak yes, no metric |
| Securing QEC against AI advice | 2026 | 2609.19090 | accept or reject adviser updates under drift | single study | simulation | none | No |
| k-agents; Vibe Calibration | 2024; 2026 | 2412.07978; 2606.22376 | transmon calibration | agent | human parity | unnamed; fine-tuned | No |
| El Agente Cuantico | 2025 | 2512.18847 | surface-code memory via CUDA-Q QEC, Stim, PyMatching | agent | human rubric | unnamed | No (calls PyMatching) |
| Circuit discovery (Lukin group); AI-agent circuit optimization (Flammia) | 2026 | 2610.22367; 2610.31352 | Toffoli and qubit counts; encodings, layout, synthesis | LLM evolution; agent programs | exact verifier | unnamed | No |
| FTPrimitiveBench | 2026 | 2605.04049 | logical primitives under biased noise, no LLM | n/a | stabilizer simulation | none | No |

Non-LLM decoder references a new benchmark should match: decoder-bench (IISWC 2025), the
sim-to-real decoder study 2609.04557, the QEC Model Zoo and the CI-grounded baseline suite (NeurIPS
2026), the MaxResnick correlated-noise challenge.

## Gaps

1. Agent-written decoder code, Stim-graded, released: nobody has it.
2. Noise-model mismatch as a controlled axis: no agent benchmark varies the gap between the DEM
   shown to the agent and the sampling noise. QIQCBench hides seam noise as a trap in one task; PR
   114 seals only p.
3. Stochastic circuit-level noise in LLM QEC evals: StabilizerBench uses a deterministic single
   fault model; no logical error rate with intervals is reported for any agent output.
4. QEC task count is tiny: one task in QIQCBench, one in the speedrun, three in StabilizerBench.
5. Open release: QIQCBench and Quantum-Harbor are unreleased.
6. Evaluator integrity: the audit paper (2610.28678) and Gatekeepers (2606.18422) show harness bugs
   flip scores; only PR 114 isolates candidates.
7. qLDPC decoding: five code-discovery papers, zero decoder-writing tasks.
8. Physics-informed hardware agents: QCTRL-BENCH and the UCSB Infinite Game are the only
   benchmarks; no DRAG or GRAPE agent eval; no cat-qubit item.
9. Latency and throughput budgets for agent decoders: only PR 114 and the Resnick challenge.
10. No survey enumerates LLM-for-quantum benchmarks.

## Unconfirmed

QC-Bench (OpenReview hrDlJGrPqc, page blocked); ScientistsLastExam (no public repo); PennyCoder
2507.19562; PennySynth 2605.25572; BDD synthesis 2609.05327. "QuantumScribe" does not exist as a
quantum LLM project.
