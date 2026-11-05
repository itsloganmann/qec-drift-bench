# Benchmark spec, draft 0 (2026-11-01)

Working name: shift-qec (Logan and Pranav to rename). Survey and gap ranking:
`docs/benchmark-gap-survey-2026-11-01.md`.

## The claim in one sentence

An agent that acts on physical hardware holds a model of that hardware. We give it a model that is
wrong in a controlled way and measure two things on every task: how much of the gap to the best
known method it closes, and whether it knows the model is wrong.

Why this and not "a QEC engineer benchmark": QIQCBench (arXiv 2609.17439) already claims the broad
lab-agent space with 49 tasks and 17 systems, unreleased. Nobody scores model-mismatch awareness
with a physical ground truth, in QEC or in any other physics domain. That axis is the paper's
original question ("does the model know when the textbook approximation breaks") moved onto the
agent's own model of the device, where Stim and hardware data give an exact answer.

## What the agent gets and returns

Gets: a nominal model (a Stim circuit or detector error model), measured shots from the true noise
(train and validation), Python with numpy, scipy, stim, pymatching, torch, a sandbox with no network
and no test labels, a wall-clock budget, and a `submit` tool.

Returns: `decoder.py` with `decode(det) -> obs_flips` (or the tier's artifact), plus a structured
report: `model_adequate` (true or false), `confidence` (0 to 100), `what_is_wrong` (free text),
`evidence` (free text). The report is required; a missing report scores as "adequate, 100".

## Scores

- **g, gap closed.** g = (log L_floor - log L_agent) / (log L_floor - log L_ceiling) on the hidden
  test shots. Floor is matching on the nominal model. Ceiling is the best known method for the
  tier on the same shots (see tiers). Reported unclipped; the composite uses the clip to [0, 1].
  L_trivial (never flip) is also reported, as in Frontier-Engineering PR 114.
- **a, awareness.** Brier score of `model_adequate` with `confidence` against the hidden truth,
  and AUROC over a tier's tasks. Half of each tier's tasks have an adequate nominal model, so
  blanket "wrong" scores no better than blanket "right". `what_is_wrong` is matched to the planted
  defect by a rubric (word match first, LLM judge second, sampled by hand before any rate is quoted).
- **Diagnosis and pass rate (hard tier, 2026-11-01).** The submit call also carries `scope` (none,
  local, global), `changed_qubits` and `mechanism`. A diagnosis is correct when the scope matches
  and a local fault's reported qubits overlap the true ones (Jaccard at least 0.5). A task is
  passed when the diagnosis is correct, g is at least 0.5, and on a drift task `gap_drift` (the
  share of the stale fit's loss recovered) is at least 0.5. The pass rate is the headline
  number; g, the Brier score and mechanism accuracy are sub-scores. `pij_corr`, the known refit
  method on the deploy shots (`decoders/pij.py`), is reported per task as the expert-pipeline
  reference. See `docs/drift-pilot-2026-11-01.md`.
- **Stale-validation trap.** A fixed share of tasks give validation shots from the nominal or
  pre-drift regime. The score on those tasks is reported apart, with the agent's own reported
  validation number next to the true test number. The pilot showed 18 of 18 episodes trusted
  validation; this is where that becomes a measured failure.
- Composite per tier: median g over tasks (clipped) and the tier AUROC. Composite over the
  benchmark: mean of tier composites, with tier 1 weighted at half because it is near saturation.
- Every number carries a Wilson 95% interval over shots and is paired on identical shots across
  decoders. Three seeds per task; report the median and the spread.

## Tiers (mismatch classes)

| Tier | Mismatch | Floor | Ceiling | Awareness truth | Status |
| --- | --- | --- | --- | --- | --- |
| 1 Static, inside the model class | per-qubit rates, crosstalk, both | nominal matching | correlated matching with the true DEM, and BP plus matching where it is better | nominal is wrong in every task; adequate tasks use the nominal noise | Built. Pilot 2026-11-01. Near saturation for Sonnet and Opus at d = 5. |
| 2 Drift | calibration shots from one noise structure, test shots after a structural change: readout and reset flips 5x ("meas5") or a fresh per-qubit draw ("requbit"); the agent also gets `deploy.npz`, recent shots without labels; later: slow drift within the batch, bursts, crosstalk onset | nominal matching (floor); `stale_corr`, correlated matching with the pre-drift true model, is reported as what a perfect training-time fit is worth | correlated matching with the test-time true DEM | the fit is stale, and `deploy.npz` shows it | Built 2026-11-01 (`decoder_task.tier2_tasks`: 4 adequate-model tasks, 8 drift tasks, 2 static replicates). A uniform 1.8x scale was built first and rejected: it shifts every matching weight by one constant, so the stale fit decoded as well as the true model (measured, `docs/decoder-pilot-2026-11-01.md`). The launch script refuses to spend if any drift task's true model is not at least 10% better than the stale fit. Pilot result (Sonnet): median g 0.72, awareness AUROC 1.0, too easy. Hard set (`hard_tasks`, local 15x to 30x faults, combined faults, a diagnosis and a three-part pass rule): Sonnet 29%, Opus 88% pass. |
| 3 Outside the model class | leakage (heralded or hidden), soft readout clouds on top of Stim outcomes, non-Markovian bursts, coherent rotations on d = 3 via Dynamiqs | nominal matching | best published method per defect (leakage-aware matching, soft-information matching, Tesseract or BP+OSD where published) | the DEM class cannot express the noise | Design with Pranav. Stim cannot sample leakage or coherent errors on its own. |
| 2b Non-stationary (built 2026-11-01 evening) | a telegraph qubit (nominal or 30x to 80x in stretches of about 200 shots) and a wandering one (each stretch a new qubit out of 12); shots in time order; `stationary` field in the report | nominal matching; `stale_corr` | an oracle that knows each shot's regime; `window_corr`, the known method given the regimes, recovers 0.67 to 0.98 of the loss | one circuit cannot describe the batch; a stationary refit recovers half of a fixed telegraph loss and none of a wandering one | `decoder_task.nonstationary_tasks` (22 tasks), `scripts/run_nonstationary.sh`; first run in progress. A per-shot hot spot was measured and dropped: no method approaches its oracle (`docs/drift-pilot-2026-11-01.md`). |
| 4 Real hardware | public sets: Google color code (zenodo 14238944), dynamic surface codes (14238907), IBM ibm_berlin with pij DEMs (23335425), IBM Marrakesh heavy-hex (18993470); dev on Sycamore 2022 and Willow 2024 | PyMatching with the circuit DEM | best published number on the same set (pij-calibrated correlated matching, Lange et al. GNN, AlphaQubit where reported) | the circuit DEM misses what the data shows (correlated readout, leakage, drift across windows) | Data verified public, CC BY 4.0. No hidden split exists; ask Google Quantum AI or IBM for a private patch. |
| 5 Biased noise and bosonic | XZZX and repetition codes under hidden bias ratio; cat-qubit repetition codes at qubit-lab's cited hardware numbers; AWS cat data (14257632) | nominal matching | bias-tailored matching with the true bias | the bias is not what the nominal model says | Pranav's tier. qubit-lab noise-bias and flip-rate formulas with citations. |
| 6 Control under a wrong model (candidate) | design a DRAG or GRAPE pulse when the model's anharmonicity or coupling is off; grade by Dynamiqs fidelity | textbook DRAG on the nominal model | GRAPE on the true model | the model is wrong | Only if tiers 2 to 5 leave budget. Ties to the UCSB Infinite Game iSWAP task. |

## Task generation and hidden split

- Tiers 1, 2, 3 and 5 are procedural: seeds set the per-qubit scales, crosstalk pairs, drift
  schedule, bias ratio. Dev seeds are public; holdout seeds are private and rotate each release.
- Tier 4 holds out by patch, basis and round count within the public sets, and takes a private
  patch from a hardware lab when one is offered.
- About 40 tasks per tier, 200 in all, 3 seeds each. Tier 1 keeps its six scenarios as a floor.

## Harness

- Harbor task format, as used by QIQCBench and the science-speedrun repository, so Codex, Claude
  Code and Gemini agents run it unchanged.
- The existing `qec_drift.agent` sandbox (`sandbox-exec` allowlist, no network, no test labels,
  clean environment) becomes a container for release. Candidate decoders run in a separate
  interpreter with a wall-clock budget. Every trajectory is archived as returned by the API, and
  every episode gets a failure-mode leaf (`docs/failure-taxonomy.md`).
- Integrity checks ship with the harness: the trivial decoder scores 0, the floor scores 0, the
  ceiling scores 1, and a scripted agent that plants links or oversized files is refused with a
  true message. The pilot lost three episodes to a wrong message; that bug class is a test now.

## Baselines

- Reference ladder per tier (nominal plain, nominal correlated, fitted plain, fitted correlated,
  true-model correlated, BP plus matching, best published). The ladder doubles as the first
  head-to-head of calibration methods on one dataset, which nobody has.
- Human experts: Pranav and Niu-group students on a stratified sample under the same wall-clock
  and tools. Kaggle human track as the public baseline once the benchmark is up.
- Models: Claude arms now; open weights on Ollama and Modal; OpenAI and Gemini once the keys work.
  A one-vendor leaderboard is not a benchmark, so inference credits are part of the ask.

## Cost model

Pilot rates: Haiku about $0.03, Sonnet high about $1.2, Opus medium about $2.3 per episode at 24
turns. At 40 turns and 600 episodes per model: about $20 (Haiku), $900 (Sonnet), $1,700 (Opus).
Our budget is $200 a month. Launch plan: 60 tasks, one seed, two Claude arms, about $250, then
labs run the full matrix with their own credits.

## Predictions, written before any tier 2 to 5 run

1. Tier 1: Sonnet and Opus median g 0.85 or more over six tasks on the fixed harness (rerun in
   progress). Haiku under 0.30.
2. Tier 2 drift: best Claude arm median g between 0.30 and 0.60; awareness AUROC 0.60 to 0.75;
   fewer than half of the episodes refit from the test detectors even though `decode` sees them.
3. Stale-validation trap: more than half of the episodes report a validation number that is better
   than their true test number by 20% or more, and do not flag it.
4. Tier 4 real data: best arm median g 0.2 to 0.5 against the best published ceiling.
5. Tier 5: bias ratio is recovered within a factor of 2 in fewer than half of the episodes.

## Kill conditions

- If the best arm's tier 2 median g is above 0.80 and its awareness AUROC above 0.90 on the first
  40 drift tasks, the benchmark has no headroom on the cheapest hard tier. Stop and report it.
  Status 2026-11-01: the 14-task pilot tripped the awareness half (Sonnet AUROC 1.0, median g
  0.72), so tier 2 moved to local faults on a magnitude ladder with a diagnosis and a pass rule
  (`docs/drift-pilot-2026-11-01.md`). The condition now reads: pass rate above 60% on the hard
  set with the deploy batch at 20,000 shots and one fault per task.
- If tier 4 cannot get a ceiling that beats the floor by at least 20% in log error rate on a public
  set, the real-data tier is not gradable; drop it rather than ship a noisy number.

## Awareness report in the harness (built 2026-11-01)

With `--awareness`, the submit tool carries `model_adequate`, `confidence`, `what_is_wrong` and
`evidence`, the prompt asks for them, and a submit without them counts as adequate at 100; an
episode that never submits has an undefined Brier. The row keeps the report, the truth
(`Task.model_adequate`) and the Brier score. In tier 2 the validation shots come from the
pre-drift circuit by construction, so every drift task is also a stale-validation trap, and the
only evidence of drift before submit is `deploy.npz` (recent detection events, no labels). Every
task now ships `deploy.npz`; the tier 1 pilot and rerun predate it.

## Harness changes after the tier 1 rerun (2026-11-01, before tier 2)

The tier 1 rerun showed Sonnet 5.5 high spending all 40 turns on ever larger noise-model fits and
writing no `decoder.py` on 4 of 5 tasks (1 or 2 timeouts per episode, so not a compute limit). The
agent was never told its budget. From tier 2 on, the prompt states the tool-call budget and what
happens when it runs out, and the last five tool results carry a countdown. A review of the
harness on 2026-11-01 also led to: scoring in a throwaway copy of the agent folder (a failing
decoder can no longer leave the test shots behind), no-follow loads of the predictions file,
shape checks that fail a submit instead of crashing the run, an error row per episode and a
parquet write after every batch, strict parsing of the assessment fields, a price check so the
caps always fire, and a sandbox that kills its whole process session. One finding was not
adopted: on adequate-model tasks the gap denominator is the gain of correlated matching over
plain matching on the nominal model (20% to 50% in log error rate), not shot noise, so g stays
defined there and means "turned on correlated matching".

## Roadmap

1. Finish the tier 1 rerun and its note (today).
2. Tier 2 pilot: done for Sonnet (awareness saturated, see the drift note). Hard set built:
   local faults on a ladder, diagnosis, pass rule, pij baseline. Run it, then grow to 40 tasks
   with two faults per task, a smaller deploy batch, slow drift within the batch and bursts.
3. Pranav: tier 3 and tier 5 noise models from qubit-lab, and the conversation with the Niu group.
   Their Infinite Game site lists a QEC environment ("decoders and code design under realistic
   circuit-level noise") as "in generation". Coordinate before anything is announced; the mismatch
   and awareness axis is what we bring.
4. Tier 4 floor and ceiling on the Google color-code and IBM sets; verify the RL-control archive
   for drift runs.
5. Harbor packaging, integrity tests, leaderboard page, expert baseline.
6. Only after launch: send to Kate (DeepMind) and the Kaggle reps from the Bench Summit, with the
   private hardware split and inference credits as the two asks.

## Venues and timing

ICML 2027 (abstract about Jan 16 to 23, 2027) for the paper if the headroom holds; NeurIPS 2027
Datasets and Benchmarks as the natural home for the benchmark itself. The Kaggle and DeepMind
eval program reported for Q4 2026 does not need a paper first.
