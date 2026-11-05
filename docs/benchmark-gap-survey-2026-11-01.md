# Benchmark gap survey, 2026-11-01

Question: is there a meaningful, unclaimed gap in evaluations of AI agents that ties to Pranav's
work (qubit-lab, cqec-ml-decoder, duquantum-cat-qubit, kernel-relay, compilers) and that could
carry a benchmark with release-card scope?

Method: three parallel literature passes on 2026-11-01 (quantum and QEC LLM benchmarks; physics
regime and science-agent benchmarks; decoder datasets and QEC-community evals), plus arXiv API,
GitHub, Semantic Scholar, OpenReview and Hugging Face searches. Every row below had its arXiv
abstract page or repository page fetched and its title confirmed. The eight load-bearing items were
read a second time by hand. Raw pass notes with the full tables are in `docs/survey-2026-11-01/`.

## Answer

The opening is real but narrower than "a QEC engineer benchmark". A broad quantum-lab agent
benchmark already exists (QIQCBench, 49 tasks, 17 systems, unreleased), and an agent that writes a
surface-code decoder graded by Stim exists as an unmerged pull request in a general engineering
benchmark. Nobody has the axis this project started from: the agent holds a model of the hardware
that is wrong in a controlled way, and the score covers both how much of the gap it closes and
whether it knows the model is wrong. Spec: `docs/benchmark-spec-2026-11-01.md`.

## Closest prior art (verified)

| Item | Date | Id | What it is | What it lacks for our claim |
| --- | --- | --- | --- | --- |
| QIQCBench and Quantum-Harbor, "Evaluating Verified Autonomy in Quantum Engineering" (Guo et al.: NUS, Unitary Foundation, Boston College, Georgia Tech, GaugeForge, UChicago, NTU) | 2026-09-15 | arXiv 2609.17439 | 49 expert-authored lab tasks across calibration and control, error correction and compilation, sensing and networking. Virtual lab with a hidden grader. 17 agentic systems (GPT-5.6 variants, Claude Opus 4.8, DeepSeek V4, GLM-5.3, Qwen3.8, Kimi K3, others). Pass rates 78% down to 3%. One decoder-calibration task on a simulated 114-qubit transmon grid, with correlated seam noise that the lab notebook does not mention. | The agent submits a decoder configuration, not code. Mismatch is one trap in one task, not an axis. No drift. No awareness score. Hidden parameters "stay out of all published material"; no release. |
| Frontier-Engineering PR 114, task_04_quantum_error_decoder (y-ji24, port of ScientistsLastExam) | 2026-10-09, open | github.com/Einsia/Frontier-Engineering/pull/114 | Agent writes `decode(problem, detection_events)` from a graphlike DEM. Stim samples, PyMatching anchors. Score per regime: (log L_trivial - log L_candidate) / (log L_trivial - log L_mwpm). Sealed regimes vary only p. Candidate runs in a separate interpreter, may not import stim or pymatching, has a wall-clock budget. | Mismatch is absent: the DEM shown is the sampling DEM. Ceiling is MWPM, not the best known decoder. Unmerged. |
| science-speedrun, surface-code-decoding (sunnweiwei) | 2026 | github.com/sunnweiwei/science-speedrun | Harbor-format long-running task: train a neural decoder on about 8 GB of Sycamore surface-code data, 8xH100 for 48 h, verifier replays on held-out data. Agent 0.7626, baseline 0.7557, reference 0.7615 (metric not named). | Real data only, GPU-scale budget, no mismatch axis, no awareness score, margins of under 1%. |
| StabilizerBench (Paz et al.) | 2026-04-23 | arXiv 2604.21287 | 192 stabilizer codes, three tasks (state preparation, optimization, flag fault tolerance), Gottesman-Knill verification, capability and quality scores, three frontier agents. Released. | Circuits, not decoders. No stochastic noise, no logical error rate. |
| A Sim-to-Real Study of Surface-Code Decoder Benchmarking (Manor et al.) | 2026-09-03 | arXiv 2609.04557 | Six decoders ranked on a four-step noise-model ladder against Willow data; rank agreement needs per-operation rates. Pipeline and per-shot results released. | No agent. No normalized gap-closed score. |
| Decoder Model Compatibility under Drifting and Correlated Noise (Hoyt et al.) | 2026-09-24 | arXiv 2609.29018 | Syndrome surprisal under a stationary DEM as a drift signal on IBM and Google data; postselection gains. | A decoding method, not an eval. Shows drift is live on hardware. |
| Estimating Detector Error Models on Google's Willow (Arms et al.) | 2025-12-11 | arXiv 2512.10814 | DEM parameters and structure learned from syndromes without a decoder; time series of DEMs tracks drift. | Method paper. The recipe an agent would reach for on tier 2 and 4. |
| QC-Stark (Gupta) | 2026-09-28 | arXiv 2609.35581 | 11 quantum tasks, 10 models, auto-verified. T11 "QEC decoding" asks the model to identify the error from a syndrome on repetition, Steane and surface codes. | Single-shot question, no agent, no decoder code, no simulator in the loop. |
| Agents' Infinite Game in Quantum (UCSB AI Lab and Quantum CoDesign Lab; Weng, Juneja, So; advisers Wang and Niu) | 2026 | agents-infinite-game.org | Agent-generated verifiable environments from open problems; five accepted (metrology, Hamiltonian simulation, iSWAP flux control); qiskit-aer, 28 qubits, 3 h; 673 reviewers invited. | No QEC and no decoders yet. Same campus and group as Pranav: coordinate, do not compete. |
| AdaExploreBench (Wang et al.) | 2026-10-19 | arXiv 2610.25950 | Hidden rules with unannounced drift; the agent must notice stale knowledge and re-explore; best model GPT-6 Sol 61.9% calibrated accuracy. | Abstract rule environments. No physics, no simulator truth, no held model. |
| SimulCost (Cao et al.) | 2026-03-11 | arXiv 2603.20253 | 4,947 cost-aware parameter-tuning tasks over 11 simulators; frontier success 45% to 81%. | Scores accuracy and cost only; no judgement about model validity. |
| OmniQEC (AI scientist) | 2026-07-28 | arXiv 2607.25865 | LLM orchestration discovers qLDPC codes, Stim and BP+OSD score them. | Codes, with a fixed decoder. |
| QAgent | 2025-08-26 | arXiv 2508.20134 | Multi-agent OpenQASM programming with calibration under hardware frequency drift. | Drift is a compilation nuisance, not the object; no QEC. |
| Securing QEC against misleading advice from AI agents (Ozguler) | 2026-09-16 | arXiv 2609.19090 | A gate that accepts an adviser's recovery update only under a drift bound; modeled adviser, no LLM. | Defence method, not an eval. Cite for the "adviser under drift" framing. |

Physics-regime pass, in one line: no benchmark anywhere scores whether an agent notices that its
physical model is invalid or stale with a simulator as truth. About twenty simulator-graded design
benchmarks exist since 2025 (photonics, fluids, FEA, PDEs, radiation transport, collider analyses)
and every one scores the artifact. The only design aimed at regime traps (PhysBreak) is a
one-commit repository with no paper.

## Public real-hardware QEC data (all CC BY 4.0, all public)

| Set | Record | Content | Use |
| --- | --- | --- | --- |
| Google Sycamore surface code (Nature 2023) | zenodo 6804040 | d = 3 and 5, X and Z, 50k shots per config, rounds 1 to 25; circuit DEM, pij DEMs, four decoders' predictions | Dev set only. AlphaQubit fine-tuned on it. |
| Google Willow below threshold | zenodo 13273331 | d = 3, 5, 7, 14 patches, 15 round counts, 112 GB | Dev set. Used by Lange et al. and the sim-to-real study. |
| Google color code | zenodo 14238944 | d = 3, 5 on Willow | Lightly used. Second-code split. |
| Google dynamic surface codes | zenodo 14238907 | d = 3, 5, dynamic circuits | Lightly used. Circuit-mismatch tests. |
| Google RL control of QEC | zenodo 17566522, 18896801 | d = 5 surface and color code; paper has injected-drift runs | Possible drift source; README not verified. |
| Google leakage (Nat. Phys. 2023) | zenodo 7302032 | Repetition d = 21, surface d = 3 with leakage; readout clouds | Leakage tier. |
| AWS concatenated cat qubits (Nature 2025) | zenodo 14257632 | Cat-qubit repetition d = 3, 5 | Biased-noise tier; raw syndromes unconfirmed. |
| Lange et al. IBM ibm_berlin plus pij DEMs | zenodo 23335425 | d = 3, 5 memory, stability, ZZ lattice-surgery merge; calibrated pij DEMs | Best non-Google set, new (Oct 2026). |
| Harper et al. IBM Marrakesh heavy-hex | zenodo 18993470 | Heavy-hex subsystem code d = 3 | Transfer tests. |
| Kunlun BB codes (Nat. Phys. 2025) | zenodo 17706106 | [[18,4,4]] and [[18,6,3]] | qLDPC option, non-standard format. |

No hidden real-data split exists anywhere. A private patch from a hardware lab is the only route
to one, and it is the concrete ask for the DeepMind conversation.

## Ranked gaps

1. Mismatch as a controlled axis with an awareness score. No agent benchmark varies the gap
   between the model the agent is shown and the noise that samples the data, and none scores
   whether the agent reports that its model is wrong. Closest: QIQCBench's one seam trap.
2. Agent-written decoder code, graded by logical error rate, released. PR 114 is the only
   instance and it is unmerged, p-only, MWPM-capped.
3. Drift with an agent on a physical system. Hoyt, Bhardwaj, Arms and the Google RL paper show
   drift is live; AdaExploreBench shows agents miss unannounced drift in abstract settings. Nobody
   joins the two.
4. A normalized "gap closed to the best known decoder" metric with floor and ceiling computed on
   the same shots, with paired shot-level tests and intervals. AlphaQubit reports fits, the
   sim-to-real study reports rank agreement, calibration papers report percent gains.
5. Head-to-head of calibration methods (pij, Chen 2022, Sivak priors, DEM estimation, ACES) on one
   dataset. None exists; a benchmark's reference ladder supplies it as a by-product.
6. Biased-noise and bosonic tasks for agents. No cat-qubit or XZZX item exists anywhere.
7. Evaluator integrity. The LLM-quantum audit (arXiv 2610.28678) and Gatekeepers (2606.18422)
   show harness bugs flip scores; our own pilot lost three episodes to a file-size cap.

## Novelty statement (as of 2026-11-01, 3 PM CST)

Checked: arXiv (API and listing searches on 16 query forms), Semantic Scholar (citations of
StabilizerBench; the search endpoint was rate limited), OpenReview public search, GitHub repository
and code search, Hugging Face datasets, Zenodo records, the Frontier-Engineering main branch and
pull requests, and the UCSB Infinite Game site and repository. Three parallel passes fetched and
confirmed about 150 abstract or record pages; the eight load-bearing items were read a second time.

Found nowhere: an agent benchmark in which the model shown to the agent is wrong in a controlled
way and the score covers both the physical result and the agent's judgement that the model is
wrong; a drift tier with an agent on a physical system; a normalized gap-closed score with a floor
and a best-known ceiling on the same shots; a hidden real-hardware split; any biased-noise or
bosonic agent task.

What cannot be checked from outside, and so limits the claim:

1. QIQCBench keeps its per-task parameters out of print. Its one decoder-calibration task hides
   correlated seam noise; nothing in the paper scores awareness or drift, but a follow-up could.
2. The UCSB Infinite Game site lists a "Quantum error correction: decoders and code design under
   realistic circuit-level noise" environment with status "in generation". This is Pranav's own
   group (Niu). It is the single largest overlap risk and also the natural partner: Pranav should
   raise our mismatch axis with them before we announce anything.
3. Frontier-Engineering PR 114 (open since 2026-10-09) may merge; it stays p-only and MWPM-capped.
4. Submissions under blind review (ICLR 2027, NeurIPS 2027 Datasets and Benchmarks) are not
   indexed. Repeat this pass two weeks before any release, as the related-work note already says
   for the paper.

## Saturation risk, stated before design

Our pilot: Sonnet 5.5 and Opus 5.5 close 0.90 to 0.99 of the gap when the mismatch fits inside a
detector error model (d = 5). Tier 1 is near saturation for frontier agents and cannot carry the
benchmark. Headroom must come from drift, noise outside the model class, real data and biased
noise, and from a ceiling at the best known decoder rather than correlated matching.

## Addendum, 2026-11-01 evening: the "debug a quantum chip" framing

A second search for "AI debugs a quantum chip" turned up four items that the morning survey
did not list. None scores what we score, but two of them own nearby words.

| item | what it is | overlap with us |
|---|---|---|
| Vibe Calibration, arXiv 2606.22376 (June 2026) | an LLM agent that calibrated 108 of 112 qubits on a superconducting processor in 4.7 hours; a demonstration, no task suite, no harness, no leaderboard | owns "AI calibrates a chip"; says nothing about a wrong noise model or a decoder |
| QCalEval, arXiv 2604.25884 (April 2026, NVIDIA and IQM, Fermilab report number) | 243 calibration plots, six question types, a VLM benchmark; NVIDIA Ising Calibration 1 released with it | plot reading, not a closed loop; no noise model, no drift, no decoder |
| Özgüler, arXiv 2609.19090 (September 2026) | a safety gate that accepts an AI-proposed QEC recovery update only when calibration uncertainty and a drift bound certify it; shows a surface-code case where a violated drift bound lets a harmful update through | the closest in spirit: AI advice on decoders under drift. It is a control analysis with simulated attacks, not an agent benchmark. Cite it: it is the reason a measured pass rate matters |
| QBugLM, arXiv 2606.07314 (June 2026) | an agentic benchmark for debugging quantum software | software bugs; owns "quantum debugging benchmark" as a phrase |

Consequence for the pitch: do not say "AI debugs a quantum chip" or "AI calibrates a chip";
both exist. Say the precise thing, which is still unclaimed: **the first benchmark that tests
whether an AI agent can tell when a quantum chip's noise model is wrong, say what broke, and
fix the error correction.** The novelty statement in the morning survey stands with that
wording. Sources: the arXiv abstracts fetched 2026-11-01.
