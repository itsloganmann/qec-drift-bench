# Pass 2: physics regime awareness and simulator-graded science-agent benchmarks

Survey notes compiled 2026-11-01. Every row had its arXiv abstract page or official page fetched.
Headline: no existing benchmark scores an agent that holds an approximate physical model, with a
simulator as ground truth, on whether it notices the model is invalid or stale. The two halves exist
apart. Regime awareness appears only as an error-analysis note (TPBench) or a one-commit hackathon
repository (PhysBreak). Simulator-graded agent benchmarks are common (about 20 since 2025), and all
score the artifact. Escalation and staleness are scored in QA, tool-use and enterprise settings,
never in physics.

| Name | Year | Id | Domain | Measures | Grader | Regime awareness scored? | Agent artifact scored by a simulator? |
|---|---|---|---|---|---|---|---|
| TPBench | 2025 | 2502.15815 | HEP, cosmology | 57 theory problems | numeric tests plus GPT-4o | No; Sec. 4.3 notes expansions used outside validity | No |
| PhysReason | 2025 | 2502.12054 | physics | 1,200 problems | PSAS auto | No | No |
| UGPhysics | 2025 | 2502.00334 | undergraduate physics | 5,520 problems | rule plus model | No | No |
| PHYBench | 2025 | 2504.16074 | physics | 500 problems | EED score | No | No |
| PhysicsEval | 2025 | 2508.00079 | textbook physics | 19,609 problems | reference solutions | No | No |
| PHYSICS | 2025 | 2503.21821 | PhD-qualifying physics | 1,034 problems | LLM protocol | No | No |
| PhySense | 2025 | 2505.24823 | physics | 380 principle-first problems | answer match | No | No |
| ABench-Physics | 2025 | 2507.04766 | graduate and Olympiad | 400 static plus 100 parameter-varied | tolerance | No | No |
| CMPhysBench | 2025 | 2508.18124 | condensed matter | 520 calculations | SEED | No | No |
| PRL-Bench | 2026 | 2604.15411 | frontier physics | tasks from 100 PRL papers | verifiable checks | No | No |
| CURIE | 2025 | 2503.13517 | six sciences | 580 long-context problems | mixed | No | No |
| SciCode | 2024 | 2407.13168 | 16 subfields | 338 research coding subproblems | unit tests | No | Code vs tests |
| PhysBreak | 2026 | github ashifirahman9999-lab/physbreak | mechanics, EM, QM wells | accuracy vs distance from the textbook regime | SciPy simulation | By design (textbook_trap class); flag not scored | No |
| Parallel Physical Worlds | 2026 | 2607.00276 | counterfactual mechanics | reasoning under altered laws | dual LLM judge | Partial | No |
| Know-Act Gap / FaultyScience | 2026 | 2603.22619 | cross-science | answer-despite-flaw rate | GPT-5 judge | Partial (textual faults) | No |
| AbstentionBench | 2025 | 2506.09038 | general | abstain on unanswerable or outdated | auto | Partial, no physics | No |
| Lu et al. position | 2025 | 2506.06214 | theoretical physics | names "approximation judgment" as a gap | n/a | Named, not measured | No |
| ScienceAgentBench | 2024 | 2410.05080 | four disciplines | 102 paper tasks | execution metrics | No | Program, not simulation |
| MLE-bench | 2024 | 2410.07095 | ML engineering | 75 Kaggle competitions | leaderboard | No | No |
| PaperBench | 2025 | 2504.01848 | ML replication | 20 papers | rubric plus judge | No | No |
| AstaBench | 2025 | 2510.21652 | science suite | 2,400 problems, cost tracked | mixed | No | No |
| CORE-Bench | 2024 | 2409.11363 | reproducibility | 270 tasks | answer checks | No | No |
| DiscoveryWorld | 2024 | 2406.06769 | text simulation | 120 discovery tasks | completion | No | Environment, no artifact |
| PhysGym | 2025 | 2507.15550 | physics discovery | query a simulator, propose a law | hypothesis accuracy | No | Law vs simulation |
| NewtonBench | 2025 | 2510.07172 | 12 physics domains | 324 tasks with altered laws | law accuracy | Partial (altered, fixed per task) | Law vs hidden simulation |
| DiscoverPhysics | 2026 | 2605.26087 | altered N-body worlds | 22 worlds | held-out MSE plus rubric | Partial | Yes |
| LLM-SRBench | 2025 | 2504.10415 | four sciences | 239 equation-discovery tasks | symbolic accuracy | No | Equation vs data |
| FEABench | 2025 | 2504.06260 | multiphysics FEA | drive COMSOL | executability plus answer | No | Yes |
| CFDLLMBench | 2025 | 2509.20374 | CFD | OpenFOAM cases | executability, accuracy, convergence | No | Yes |
| PDEAgent-Bench | 2026 | 2605.09636 | PDE solvers | 645 instances | staged | No | Yes |
| SimulCost | 2026 | 2603.20253 | fluids, solids, plasma; 11 simulators | 4,947 cost-aware tuning tasks; frontier 45% to 81% | accuracy threshold plus analytic cost | No (false positives named, not scored) | Yes |
| MooseBench | 2026 | 2605.09360 | multiphysics | runs but wrong physics | intent fidelity vs PDE truth | No | Structural |
| PhysCodeBench | 2026 | 2604.23580 | 3D scene physics | 1,200 tasks | engine run, conservation residuals | No | Yes |
| PHITSBench | 2026 | 2607.09789 | radiation transport | 282 tasks | execution plus result match | No | Yes |
| Collider-Bench | 2026 | 2605.13950 | LHC analyses | reproduce yields | histogram metrics | No | Yes |
| gwBenchmarks | 2026 | 2605.11269 | gravitational waves | 8 precision tasks | external framework | No | Yes |
| QMP-Bench / PhysVEC | 2026 | 2604.00149 | quantum many-body | 100 research tasks | reproduction accuracy | No | Yes |
| Judge Agent | 2026 | 2603.25780 | 12 computational domains | silent failure rate 42% to 1.5% | well-posedness, convergence, bounds | Partial (numerical) | Yes |
| HALO-Bench | 2026 | 2608.28877 | nanophotonics | 52 design tasks | EM simulation | No | Yes |
| EngDesign | 2025 | 2509.16204 | nine engineering disciplines | design briefs | simulation-driven | No | Yes |
| Vortex100 | 2026 | 2608.20688 | integrated photonics | multi-objective | full-wave EM | No | Yes |
| When2Tool | 2026 | 2605.09252 | 18 environments | tool necessity | accuracy plus call count | No | No |
| EcoAgent-Bench | 2026 | 2608.05519 | QA sets | escalate, save, tier, stop under budget | accuracy plus economic consistency | No | No |
| AdaExploreBench | 2026 | 2610.25950 | hidden-rule environments | adaptation under implicit rule drift; GPT-6 Sol 61.9% | calibrated accuracy | Partial (stale knowledge, no physics) | No |
| EnvProbe | 2026 | 2606.31422 | controlled environments | belief calibration by probing | terminal state | Partial | No |
| ChurnBench | 2026 | 2609.11515 | enterprise data | freshness vs reasoning errors | ledger truth | Data staleness only | No |

Other confirmed rows of the pass (not repeated here): PhysicsEval, SciBench, LAB-Bench, EXP-Bench,
SUPER, ResearchBench, SciReplicate-Bench, DiscoveryBench, MechHypoBench, FEM-Bench, CompMat-Bench,
PCFBench, EngiAI, EngiBench (both), MetaTool, When2Call, Model-Adaptive Tool Necessity, KAPRO,
CostBench, healthcare escalation audit, Bayesian self-escalation, cost-aware stopping,
ReliabilityBench, Gaia2, ProEvolve, EnterpriseArena, robust adaptation, RobustBench-TC, SIMMER,
FaultyMath, Soohak.

## Gaps

1. Regime awareness is never a scored outcome with simulator ground truth.
2. Flawed-premise detection exists only with textual faults and LLM graders.
3. No benchmark gives the agent a cheap approximate model plus an expensive oracle and scores the
   escalation decision in physics.
4. Staleness detection is never tested on a physical system.
5. Simulator-graded design benchmarks score the artifact, not the model.
6. Error taxonomies do not separate "model invalid and unnoticed" from "arithmetic wrong".
7. Counterfactual worlds dominate; real validity boundaries are absent.

## Closest prior art

PhysBreak (same regime-shift idea, single-shot QA, no agent, no paper); SimulCost (simulator in
the loop with cost, but the agent tunes the oracle itself); AdaExploreBench (scores noticing stale
knowledge under unannounced drift, abstract rules only).

## Unconfirmed

PDE-Agents 2606.07850, PhysMent 2609.13152, SkillPCF 2605.29421, BilliardPhys-Bench 2605.30900,
AlloBench 2607.23332, Agent Drift 2601.04170, DRIFT-BENCH 2602.02455.
