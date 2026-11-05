# Pass 3: real-hardware QEC datasets, decoder benchmarks, calibration methods

Survey notes compiled 2026-11-01. Every record page or abstract page was fetched. Headline: nine
public real-hardware QEC datasets exist, all CC BY 4.0 and all fully public; the two largest have
been used to fine-tune neural decoders, so none is a hidden test set as is. The decoder benchmark
literature is simulation-only except one 2026 sim-to-real study on Willow data. Calibration has a
mature method family (pij, RL priors, DEM estimation, syndrome correlations) and no shared
benchmark. No paper evaluates an AI agent that writes a decoder.

## Datasets

| Name | Year | Record | Code and distances | Shots and rounds | DEM or calibration | Hidden test set? |
|---|---|---|---|---|---|---|
| Google Sycamore surface code (Nature 2023) | 2022 | zenodo 6804040 | surface d = 3 (4 sites), d = 5 (1 site), X and Z; repetition d = 25 subsampled | 50k shots per config, rounds 1 to 25 (about 6.5M shots) | circuit DEM, pij DEMs, four decoders' predictions | No. AlphaQubit fine-tuned on it. Dev set. |
| Google Willow below threshold | 2024 | zenodo 13273331 | 105Q surface d = 3, 5, 7 (14 patches); 72Q d = 3, 5; 72Q repetition d = 29 | 50k shots per config, 15 round counts, 420 configs; 112.5 GB | third-party pij DEMs (zenodo 23335425) | No. Used by Lange et al. and the sim-to-real study. |
| Google color code | 2024 | zenodo 14238944 | color d = 3, 5 on Willow | 738 MB | not stated | Lightly used. Second-code split. |
| Google dynamic surface codes | 2024 | zenodo 14238907 | surface d = 3, 5, dynamic circuits | 2.1 GB | not stated | Lightly used. Circuit-mismatch tests. |
| Google RL control of QEC | 2025, v2 2026 | zenodo 17566522, 18896801 | surface d = 5 (2026) and color code (2025) | 7.8 GB; paper has injected-drift runs | not stated | Possible drift source; README unverified. |
| Google leakage (Nat. Phys. 2023) | 2022 | zenodo 7302032 | repetition d = 21, surface d = 3 with leakage | 10.1 GB | readout clouds, detection probabilities | Leakage tier. |
| AWS concatenated cat qubits (Nature 2025) | 2024 | zenodo 14257632 | cat-qubit repetition d = 3, 5 | 145 MB | not stated | Biased-noise tier; raw syndromes unconfirmed. |
| Lange et al. IBM ibm_berlin plus Google pij DEMs | 2026 | zenodo 23335425 | surface d = 3, 5 memory, stability, ZZ lattice-surgery merge | 200 MB | detection events, logical flips, calibrated pij DEMs | Best non-Google set, Oct 2026. |
| Harper et al. IBM Marrakesh heavy-hex | 2026 | zenodo 18993470 | heavy-hex subsystem code d = 3 | 1.1 GB | PyMatching from averaged calibration | Transfer tests. |
| Kunlun BB code experiment (Nat. Phys. 2025) | 2025 | zenodo 17706106; github ZhideLu/Exp_BivariateBicycleCode | [[18,4,4]] and [[18,6,3]] | repo folders | component error rates, readout matrix | qLDPC option, non-standard format. |

Not public or unconfirmed: ETH Krinner d = 3 (on request), Quantinuum Helios color code (no data
statement found), Microsoft and Quantinuum 2404.02280, IBM Sundaresan 2023, Google 2021, Harvard
Bluvstein 2023, Zuchongzhi 3.2, Quantinuum H2 qutrit toric. Alice and Bob, IonQ, QuEra: no syndrome
data found.

## Decoder benchmarks and calibration methods

| Name | Year | Id | What it does | AI agent or LLM? |
|---|---|---|---|---|
| Stim; Sinter; PyMatching 2 | 2021 to 2023 | 2103.02202; Stim glue; 2303.15933 | simulator, Monte Carlo harness, MWPM | No |
| Tesseract | 2025 | 2503.10988 | A* most-likely-error decoder | No |
| decoder-bench (IISWC 2025) | 2025 | github satvikmaurya/decoder-bench | simulated HDF5 syndrome sets: surface, BB, color, lattice surgery | No |
| FTPrimitiveBench | 2026 | 2605.04049 | logical primitives under biased and non-uniform noise | No |
| Sim-to-Real decoder benchmarking | 2026 | 2609.04557 | rank agreement between four noise models and Willow data; PyMatching, BeliefMatching, BP+OSD, BP+LSD, Tesseract, NVIDIA Ising | No |
| Real-time QEC system stack | 2026 | 2605.30765 | real-time readiness, tail latency | No |
| AlphaQubit | 2024 | Nature 635, 834 | even/odd cross-validation on Sycamore; pretrain on pij and SI1000, fine-tune; LER-per-round fit | ML decoder |
| AlphaQubit 2 | 2025 | 2512.07737 | real-time under 1 us, surface d = 11, color d = 9 | ML decoder |
| Modular GNN-RNN decoder (Lange et al.) | 2026 | 2610.03869 | fine-tune on IBM and Google data; memory, stability, ZZ merge | ML decoder |
| Cascade | 2026 | 2604.08358 | CNN decoder on the Gross code | ML decoder |
| Fowler et al. error-model extraction | 2014 | 1405.1454 | origin of pij estimation | No |
| Spitz et al. adaptive weights | 2018 | 1712.02360 | data-driven weights under time-dependent noise | No |
| Chen et al. calibrated decoders | 2022 | 2110.04285 | calibration from correlated events up to size 4 | No |
| Sivak et al. decoder priors | 2024 | 2406.02700 | RL-inspired priors; beats pij by 16% (repetition) and 3.3% (surface) on Sycamore | RL, no LLM |
| Darmawan | 2024 | 2403.08706 | fidelity loss under mis-specified noise, TN decoder | No |
| Hockings et al. noise-aware decoding | 2025 | 2502.21044 | ACES-calibrated priors | No |
| Remm et al. syndrome correlations | 2025 | 2502.17722 | Y, hook, multi-qubit, leakage errors on d = 3 | No |
| Blume-Kohout and Young | 2025 | 2504.14643 | DEM event probability estimation from syndromes | No |
| Bhardwaj et al. drifting noise | 2025 | 2511.09491 | sliding-window drift estimation | No |
| Arms et al. DEM estimation on Willow | 2025 | 2512.10814 | DEM parameters and structure from syndromes, time series tracks drift | No |
| Takou et al. | 2026 | 2606.11496 | DEM estimation on Willow and ibm_miami, 5% to 10% gain | No |
| Hoyt et al. model compatibility | 2026 | 2609.29018 | surprisal-weighted postselection under drift on IBM and Google data | No |
| Google RL control of QEC | 2025, Nature 2026 | 2511.08493 | RL tunes device control from detection events, 3.5x stability under injected drift | RL agent on hardware |
| Lee et al. heavy-hex compass code | 2026 | 2604.14296 | ACES plus soft info plus leakage detection, 38% gain at d = 5 | No |
| Unitary Foundation QEC Challenge | 2026 | github unitaryfoundation/qldpc-challenge | code leaderboard, agent-friendly, Pareto by n, k, d | agents submit codes |

## Gaps

1. No benchmark asks an agent to write decoder code.
2. No hidden real-hardware test set exists.
3. No normalized "gap closed to the best known decoder" score with floor and ceiling on the same
   shots.
4. No public drift-labeled dataset (the Google RL-control archive may hold injected-drift runs).
5. No public hardware set with soft readout or leakage flags.
6. Calibration methods are each evaluated by their own group on different data.
7. Non-Google hardware is thin.
8. Shot-level paired statistical protocols appear only in a hobby repository.
