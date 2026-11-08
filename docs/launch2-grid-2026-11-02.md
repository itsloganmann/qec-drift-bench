# QEC-Drift v2: one task per scenario, every model and effort on two subscriptions

Date: 2026-11-02. Status: running. The tables at the end fill in as arms finish.

## Why a second launch set

The first launch set (docs/drift-pilot-2026-11-01.md) put Opus 5.5 at 48% absolute and 24%
relative, Sonnet 5.5 at 14% and 10%. It had two weaknesses for a model card. Eighteen of its
twenty-one tasks were the same two kinds (`wander`, `patch`) on three seeds, so the set was a
ladder of replicates, not a set of scenarios. And it had one mechanism: every fault scaled all
the noise of a qubit. The second set keeps the task format, the scoring and the pass rules and
changes the tasks: one task per physical story about a superconducting chip, no seed replicates,
two more mechanisms, three code distances, and a heterogeneous base.

## The scenarios (the `launch2` pool, agent/decoder_task.py)

Each drift task is a different thing that goes wrong on a chip, in the grammar of
agent/drift.py. The gate below keeps the ones where the fault costs the stale decoder at least
20% and the honest adaptive decoder recovers at least half of that.

| story | kinds in the pool | what the agent must say |
|---|---|---|
| a two-level-system defect on one qubit switches in and out of resonance | `tls30` | local, not stationary, that qubit |
| a defect drifts into resonance over the batch | `ramp20`, `ramp30`, `ramp40` | local, not stationary, that qubit |
| defects on several qubits, one bad at a time | `wander20`, `wander30`, `wander50d60`, `wander30d30` | moving, the qubits that were bad |
| the same, seen through a short deploy batch | `wander30-n5000`, `wander30-n2000` | moving |
| a high-energy impact hits a region | `patch20`, `patch30`, `patch50d40` | moving, the qubits in the disks |
| a coupler's two-qubit gate fails at changing places | `gwander60`, `gwander60d60` | moving, mechanism gate |
| a permanently bad qubit or coupler under a wandering fault | `bq15+wander30`, `bg40+wander30` | moving, both sets |
| a chip whose qubits already differ from the model, under drift | `hetero` base with `wander30`, `patch30`, `ramp30` | as above |
| the main faults on a bigger chip | distance 7: `tls30`, `ramp30`, `wander30`, `patch30`, `gwander60`; distance 9: `wander30`, `patch30` | as above |
| nothing is wrong | distance 5 (two seeds), 7, 9 | adequate, scope none |

New in the grammar: `gwander{f}` (each bad stretch picks a new CX pair out of twelve and makes
its two-qubit depolarizing f times more likely; the truth's mechanism is `gate`) and `ramp{f}`
(one qubit's noise climbs from its base to f times in eight geometric steps, in time order;
the truth is local and not stationary). The family draw order is pinned, so every recorded v1
task keeps its fault location.

The honest adaptive baseline (decoders/adaptive.py) now also tries the two-qubit gate of every
CX pair at every factor, so it covers the coupler faults it is held against. The v1 numbers in
the pilot note were computed with the qubit-and-disk baseline and stay as they are.

## Scaffolds

Three scaffolds run the same task text and the same scoring:

- the API harness (agent/decoder_run.py), used for the earlier tiers;
- Claude Code on the claude.ai subscription (agent/decoder_run_cc.py);
- Codex on the ChatGPT subscription (agent/decoder_run_codex.py, new).

The two subscription scaffolds share agent/isolation.py: an allowlisted environment with no API
keys, a sandbox-exec profile that confines writes to the task folder and the episode's own state
directory and hides the repository and this machine's secret stores, a login copy without the
refresh token that is locked at the model's first reply, and a one-hour outer episode limit.
The prompt asks for about 50 minutes to leave time for scoring. Codex runs
with its own sandbox off (the outer one confines it), with browser, computer use, apps,
memories, plugins, skill search, hooks, code mode and web search off, and with its real binary
rather than this machine's wrapper. Both scaffolds wait and retry when a subscription refuses
an episode before any tool call. A provider limit after tool calls archives an invalid attempt
without scoring and stops the arm; the supervisor can resume it when quota permits.

## Arms

Claude Code accepts every pair of seven models and five effort levels on the Max subscription:
Fable 5.1, Opus 5.5, Sonnet 5.5, Haiku 5.5, Opus 4.8, Sonnet 4.6, Haiku 4.5, at low, medium,
high, xhigh and max. Codex lists four models on the ChatGPT Pro Lite login: GPT-6-Astra,
GPT-5.6-Sol, GPT-5.6-Terra (low to ultra) and GPT-5.6-Luna (low to max). The grid driver
(scripts/run_grid.py) runs the corners first (the strongest model at its highest effort, the
weakest at its lowest), so the band check comes before the interior.

## Fable 5.1 at max effort on the v1 launch set

Run first, on the old set, for one question: is the strongest model saturated there?

No answer: the arm stopped at 6 of 21 tasks when the Fable week ran out, and 4 of the 6 ran
under the PATH defect of the fairness log (their shells found a `python3` without stim), so
they are `invalid_run`. The other two did not pass. The v2 set replaced v1; the Fable 5.1 max
arm on the v2 core is in the live table.

## The gate on the v2 pool

As of November 8, `data/agent_launch2/references.json` holds 48 tasks; 40 pass the gate, including
all 23 core tasks. The original pool held 39 tasks, of which 33 passed (the fixed
30x TLS, the ramps at 20x to 40x and the coupler wander at 60x on d5 and d7 leave the stale
decoder less than 20% to lose). The eight tasks of the supplement were computed on their own;
the others were
recorded from the reference run's log at five decimals after the run was stopped to free the
machine (its two distance-9 tasks are recomputed later). Every arm scores against the same
file, so the rounding is shared by every row.

The core, run first by every arm (`LAUNCH2_CORE` in agent/decoder_task.py), first 13 tasks: the
negatives `d5-none-s6` and `d9-none`; the stationary rung `d5-none-dbq30-s1` and
`d5-none-dmeas5`; the moving faults `d5-none-dtls30-s2`, `d5-none-dpatch30`,
`d5-none-dwander30d30-s6`, `d5-none-dgwander100d60-s1`, `d5-none-dwander30-s5-n2000`,
`d5-none-dbg40+wander30-s3`, `d7-none-dwander30-s1`, `d5-none-dpatch50d40-s1`; and the hard
rung `d7-none-dgwander100`. On 2026-11-04 GPT-6-Astra max passed 11 of these 13 clean tasks,
failing only the two fastest-moving faults, so five harder tasks joined the hard rung (18 in
all): `d5-none-dgwander60d60-s1`, `d5-none-dwander50d60-s2`, `d5-none-dbq15+wander30-s2` from
the pool, and the new `d5-none-dgwander100d30-s2` and `d5-none-dbq15+wander30d30-s4`. Each
passes the gate and the ideal-reader check. A dwell of 15 or 20 shots failed the gate (the
honest decoder recovers 0.27 and 0.44 of the loss), so the rung stops at 30. On the 18 tasks GPT-6-Astra max
still passed 15, failing two single-qubit defects that hop every 30 or 60 shots and the coupler
moving every 60. A second rung of that family joined (23 in all), chosen by dwell and honest
headroom rather than by any model's results: `d5-none-dwander30d40-s8`, `d5-none-dwander50d30-s9`,
`d5-none-dwander80d60-s10`, `d7-none-dwander30d30-s2` and `d7-none-dgwander100d60-s1`. Arms extend to the rest of the gated pool
while the weekly quotas allow (the Claude week was 53% used and the Fable week 68% when the
grid started; the ChatGPT week 6%).

The expansion decisions followed observed model scores. The core is therefore a development
set, even though physical dwell and baseline headroom guided the individual additions. Scores
on it are descriptive; fresh instances and repeated runs are needed to assess generalization
within these families or differences between effort settings.

## Results

(filled in by scripts/launch_scores.py as arms finish)

## Quota monitoring

`scripts/usage.py` reads each subscription independently. A credential, network or response
error for one provider does not suppress the other provider's reading. Failed reads appear
as `unknown`, with only the exception type saved in the usage log. The supervisor leaves a
provider's grid state unchanged when its usage is unknown; unknown is not zero usage.
HTTP authorization headers pass through stdin, outside process arguments. Requests have
timeouts, ignore curl config files and do not follow redirects. Malformed credentials are
rejected without trying to repair them.

## Results set aside on 2026-11-03 (the task-name leak)

The v2 grid as it stood at 23:16 PST on 2026-11-03, when the task-name leak of the fairness
log was found (relative / absolute pass rate on the 13-task core). Every agent could read its
task's name; these rows are in `data/agent_launch2/name_leak/` and are rerun from the start.

| model | low | max | ultra |
|---|---|---|---|
| Fable 5.1 (Claude Code) |  | 12% / 38% (8/13) |  |
| GPT-5.6-Luna (Codex) | 0% / 0% (core) | 8% / 8% (core) |  |
| GPT-5.6-Sol (Codex) |  | 69% / 69% (core) |  |
| GPT-5.6-Terra (Codex) |  | 38% / 46% (core) |  |
| GPT-6-Astra (Codex) |  | 77% / 77% (core) | 100% / 100% (4/13) |
| Haiku 4.5 (Claude Code) |  | 0% / 0% (6/13) |  |
| Haiku 5.5 (Claude Code) |  | 15% / 31% (core) |  |
| Opus 4.8 (Claude Code) |  | 0% / 15% (core) |  |
| Opus 5.5 (Claude Code) |  | 77% / 85% (core) |  |
| Sonnet 4.6 (Claude Code) |  | 0% / 0% (core) |  |
| Sonnet 5.5 (Claude Code) |  | 85% / 85% (core) |  |

## Fairness log (2026-11-03)

Every defect found in the harness or the task text, what it did, and what was done. The
checks that found them: `scripts/legitimacy.py` (`docs/legitimacy.md`), the transcript
judge (`scripts/judge_transcripts.py`, `docs/judge.md`), and reading the transcripts. A row is
set aside (kept in a folder named for the defect) and rerun when the defect could change how
that task is scored; otherwise the defect is fixed for later episodes and recorded here.

| defect | found by | effect | fix | rows set aside and rerun |
|---|---|---|---|---|
| The 40-tool-call budget in the task text was not enforced | reading the counts | some GPT-6-Astra episodes ran 49 to 96 calls | the harness kills the CLI at the first call past 40 (c16f27e) | the over-budget episodes |
| Codex shells found a system `python3` without stim (a login zsh reorders PATH) | missing-module errors in transcripts | 14 Codex episodes lost their environment | an episode `.zprofile` puts the venv first (88da24c) | 14, in `env_defect/` |
| The same PATH defect in the v1 Claude Code runs of 2026-11-02 | the one taxonomy, applied to every set on 2026-11-03 | every episode of Opus 5.5 medium and Sonnet 5.5 high on Claude Code and 4 of Fable 5.1 max saw `No module named 'stim'` and spent calls to find a working Python; 37 of these 46 installed their own copy | fixed for v2 by the same `.zprofile` | none: v1 is not rerun (v2 replaced it); these episodes are `invalid_run` and the live table leaves them out |
| The 60 s start guard killed CLIs that were still thinking | zero-call rows at 60 s | 6 Haiku 5.5 max episodes never acted | only a silent CLI is killed (088cf23) | 6 |
| "stationary" did not say within which shots | legitimacy task table, then transcripts | strong arms answered "not stationary" for a calibration-to-deploy change and failed the two stationary tasks | defined within deploy.npz (674acb9) | the two stationary tasks for every arm, in `prompt_v1/` |
| The scope list omitted "moving" | the judge (53 episodes) | agents chose "local"; the scorer already accepts local with "not stationary", so no score changed | "moving" listed (6aaedde) | none |
| "The real noise differs from that circuit" is false on the two negatives | the judge | a false premise on the tasks where nothing is wrong | "may differ" | the two negatives for every arm, in `prompt_v2/` |
| zsh here-documents need `/tmp`, which the sandbox denies | the judge (environment_problem) | 110 of 132 episodes lost one or two of their 40 calls, evenly across arms; no outcome depended on it: the 9 episodes that ended at the cap (8 GPT-5.6-Luna max, 1 GPT-5.6-Terra max) lost call 1, 2 or 3 and had not started a `decoder.py` by call 40 | TMPPREFIX in the episode's temp folder | none |
| The task folder was named after the task, and a task name says what is wrong (`dwander30`: a wandering fault; `dpatch50`: a patch present about half the time; `dmeas5`: readout noise at 5x) | the judge (one episode's `pgrep` showed another agent's command line), then a search of every v2 transcript | every agent saw the name in its working directory; 20 of 156 v2 episodes mention it, and Opus 4.8 max used it to direct its analysis ("The folder name hints at 'wander' (drift). I need to check whether the hot region moves") | each episode runs in a folder with a random name, renamed to the task after scoring; no harness command line names a task (an episode can read every process's command line with `pgrep`, and sandbox-exec cannot hide it on this macOS) | every v2 row, in `name_leak/`; v1 and the pilots had the same folder names and are not rerun |
| At the tool-call limit, macOS can refuse to kill the CLI's process group (EPERM) | an error row with a traceback in `os.killpg` | one GPT-6-Astra max episode that used its 40 calls became an error row instead of being scored | the harness kills the CLI alone when the group kill is refused | that row (error rows rerun) |
| The shared venv held the benchmark's own install record: `qec_drift.pth` (the path of the hidden source) and a dist-info whose METADATA copies an early README (the pass rule, the fault families, that negatives exist) | the `probe` flag on a GPT-5.6-Sol max episode, which imported `qec_drift` (refused: the source is hidden) and read the `.pth` | three episodes listed the dist-info; none read the README (no README text in any v2 transcript) | episodes cannot read the package's `.pth` or dist-info; stim and pymatching still load | none |
| The sandbox hides the repository and secret stores but not the rest of the home folder | the secret scan before publishing | a GPT-5.6-Terra max episode ran `find /Users/logan ... -iname '*drift*'` and printed 200 paths from other projects; no copy of the benchmark source exists outside the hidden repository, so no answer was reachable | the public snapshot leaves out the transcripts, which can hold such listings | none |
| The benchmark source is public from 2026-11-05 (github.com/itsloganmann/qec-drift-bench), and episodes have network access | publishing | an agent could fetch the task generator | the `probe` flag now matches the public repository's name; any such episode is set aside | none so far |
| A rerun could inherit read-only caches of an earlier attempt | a harness error row | none observed | the task folder is force-cleared | none |
| A provider usage limit after the first tool call was counted as a model failure | the transcript judge, then the original terminal error events | three GPT-5.6-Luna high episodes stopped after 2 to 5 calls, but were labelled no_submission and treated as finished | partial provider-interrupted episodes are archived as error rows without scoring; the arm stops and the grid cannot exit successfully with tasks still pending; the taxonomy also recognizes historical quota failures | the three original attempts are preserved; the November 8 reruns yielded two submitted decoders and one tool-budget failure, with no pass |

November 8 trace audit: the Luna high stationary-qubit episode began with `pwd` in a parent
scratch workspace and failed to find its task files. It listed unrelated filenames, then
recovered the episode folder. Later path errors include explicit wrong paths in the agent's
commands. Repository traversal was denied; the full trace shows no successful hidden-data
read. It completed normally, wrote both required files in its episode folder, used 34 of
40 tool calls and passed. The command events omit requested tool working directories, and
the ephemeral CLI state retains no tool requests. The cause of the first working directory
is unresolved. The row is retained with this concern; completion does not prove the lost
calls had no effect. A non-benchmark CLI diagnostic is pending quota availability.

November 8 correction: the original arm table, archive, work folders and affected rendered
pages were copied to `.cache/provider-interrupted-backup-20261108` with SHA-256 hashes before
changing the three rows. The other 20 rows in the arm and all 23 other arm tables were
unchanged. The archive preserves all 23 original records and appends three fresh attempts.
The reruns finished on November 8: two submitted decoders and one ended at the 40-call limit
without a decoder. All three are valid failures; Luna high has 23 valid episodes and no task
pending. The capped attempt searched outside its folder for nominal.stim, but repository
traversal was denied; the recorded trace shows no hidden test, task-name or continuation-note
exposure. The reruns took place later than the original grid, so provider revision drift
remains possible.

Checked, not a harness defect: in 8 of 13 clean GPT-5.6-Luna low episodes some shell calls could not find `nominal.stim` or the `.npz` files, while the calls before and after them in the same episode could (failures at calls 1, 3, 5, 9 and 15 of one episode). The harness starts the CLI in one folder for the whole episode, and no other arm shows it (GPT-6-Astra, GPT-5.6-Sol and GPT-5.6-Terra: none), so the folder changes with the model's own calls; Codex lets a model name a working folder per call, which its event stream does not record. Luna low stops on its own after 7 to 17 calls, far from the 40-call cap.

Checked and fair: GPT-6-Astra max beats the per-shot true-model oracle on 6 of 13 clean core tasks (up to 11 standard errors on the same test shots). Its decoders are stronger than matching, not informed by anything hidden: an approximate maximum-likelihood search that sums fault covers over candidates from perturbed correlated matchings, compiled in C++, and a learned reranker over several matchings. They read only their own folder and embedded weights fitted on the calibration and deploy files. The oracle is matching with the true model, not the best possible decoder, so `gap_drift` above 1 is possible.

The saved detector cache covered only 11 of the current 21 non-adequate core tasks on November
8. The ten later additions lacked saved detector evidence; the earlier whole-core claim was
unsupported. All ten missing checks were completed on November 8, and the current report
covers 21 of 21 non-adequate core tasks. An ideal-reader check concerns truth-qubit support in
the deploy sequence; it does not prove that an evaluated agent can infer those qubits.
After the three reruns,
533 valid episodes covered the 23 core tasks: four tasks had no absolute-rule pass and five
had no relative-rule pass. No task was passed by every arm. The totals were 159 absolute-rule
passes and 144 relative-rule passes. The three provider-interrupted attempts remain archived
and excluded; their replacements count. The earlier statement that every task had been passed was
incorrect. The simulation gate and known-method baselines establish the inclusion criterion;
model success is measured separately.

The earlier trajectory review found no successful write at the outside paths flagged by the
judge and no access to hidden test shots or the scorer. This is evidence from the reviewed
traces, not a proof covering arbitrary code. The subscription scaffolds allow package installs
from the network (including ldpc, tesseract-decoder and beliefmatching), recorded per episode
as the `network` flag. The API harness blocks network access.

November 8 audit of the old judge: its review payloads retained model and effort in filesystem
paths, so the earlier blinded-review claim was incorrect. Of 533 valid scored rows, the old
reader exposed 532 transcripts and 515 had a matching judgment. The other 17 were skipped
because the cache deduplicated by arm and an incomplete content key, without the task. One
transcript appeared missing. These were review-coverage gaps, not evidence of clean episodes.
Original judgments and transcripts are preserved. The repairs and current coverage follow.

November 8 repair: the apparently missing transcript was present in the unchanged gzip
archive. The reader split a valid compressed member at bytes that resembled a gzip header.
It now follows decompressor boundaries and can recover later members after a damaged header.
All 24 current archives match strict gzip decoding (545 historical records); all 533 valid
rows now have an archived transcript. The recovered record matches its decoder, report,
21 tool calls, tokens and cost. No record was reconstructed or changed.

The judge now uses protocol `identifier-masked-v2`. Known model identifiers and arm paths are
masked throughout facts and transcript text, preserving path relationships and outside-file
evidence. Scaffold and tool syntax still provide clues, so this is not complete blinding.
The cache hashes the exact submitted input, rubric, schema and judge settings and uses arm,
task and key together. Legacy judgments stay archived and do not count under the new
protocol. The hourly publisher takes at most eight pending reviews per tick. Its coverage
report must be read with every partial result. Rows and raw attempts still lack shared attempt
IDs; no mismatch was found in the current rows, but a crash between archive append and table
replacement could create one. That recovery risk remains open.

November 8 protocol pilot: before the calls, the plan predicted identifier masking, distinct
request keys, preserved legacy records and report coverage for three selected cases. The
cases covered the recovered archive, a provider-limit rerun and an old cache collision.
All 533 submitted inputs passed the identifier and key preflight. The three live reviews
completed, matched their rule labels and preserved every legacy log prefix. The report now
counts 3 current reviews, 530 awaiting review and no missing transcripts; 687 older judgment
records remain excluded. This selected smoke test is not a performance estimate.

Two pilot reviews flagged outside-folder probes: an attempted scratch write under `/tmp`
and an attempted listing of the machine's Claude project directory. The judge found no
successful hidden-shot or harness access in the submitted excerpts. These flags remain
visible; identifier masking and matching labels do not establish a clean integrity review.
The judge sees a rendered transcript with output limits and, for long episodes, a middle cut.

## Adaptive reference provenance (November 8)

`adaptive_corr` is a benchmark-specific reference. DGR learns graph weights from decoded-edge
occurrences and decoded-edge-pair statistics ([Wang et al., Section IV-A and IV-B](https://arxiv.org/html/2311.16214v3#S4)).
Our implementation instead simulates detector rates for a fixed bank of one-qubit, disk and
CX-pair faults, selects hypotheses with a centred-window likelihood test, then runs correlated
matching. The DGR citation is related work, not evidence that this code reproduces DGR.

The reference builder passes the pre-drift circuit and the private task seed, which controls
hypothesis simulation. It does not pass the changed locations, regime labels or test
observables into `Adaptive`. For all 23 current core tasks, the supplied circuit exactly
matches the visible nominal circuit; this equivalence is specific to that core. Each shot
can use 50 future shots as well as 50 past shots. This is offline batch decoding.

The reference provides measured decoding recovery, not an optimality bound or a full diagnosis
pass. Its hypothesis bank shares the benchmark's fault families. The current gate therefore
does not establish diagnosis reachability or performance on unseen fault structures. A future
visible-only diagnosis baseline needs a fixed simulation seed, explicit scope and stationarity
inference, and evaluation separate from the existing truth-assisted detector table. Historical
reference values and task thresholds are unchanged.
