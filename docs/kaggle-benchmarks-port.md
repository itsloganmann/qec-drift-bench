# Porting QEC-Drift to Kaggle Benchmarks (plan, updated 2026-11-08)

**Status: scored deployment is blocked on isolation and run limits.** The API harness
(`src/qec_drift/agent/decoder_run.py`) can supply the tool loop and score rules. Two points
need an answer from Kaggle before running model-written code against hidden data:

1. How to keep the hidden test shots, their labels and the true noise away from model-written
   code that runs inside the same Kaggle notebook as the scorer.
2. Whether an agent episode of up to 40 tool calls, 23 times per model, fits the run limits.

Nothing in this plan changes the tasks. Comparison with the API-harness column requires
verified isolation, matching budgets, and the parity check below. The 23 core tasks are a
development set selected during the earlier grid; reusing them does not create a held-out set.

## What Kaggle Benchmarks gives

Source checked on November 8: `Kaggle/kaggle-benchmarks` commit
`5ffefc57696e26b172fc3626392731ebecbb1195` (November 6; changelog latest release v0.6.2).
The SDK source and launch post describe:

- A task is a Python function with the `@kbench.task` decorator. It gets an `llm` object and
  calls `llm.prompt(...)`. Kaggle runs it for each model through its model proxy and builds a
  leaderboard from the stored runs.
- Tool calls: automatic through the `genai` API path, manual through the OpenAI-compatible path
  (the task code runs the loop). `prompt()` takes `tools`, `reasoning` and `include_thoughts`.
- Code execution: `tools.python.script_runner` uses `envs.current`, whose default is
  `InternalUnsafeLocalEnvironment`. Its source explicitly says it provides no sandboxing.
  `IPythonREPL` starts another kernel, with no confinement configured in that constructor.
  `DockerEnvironment` requires a Docker client and creates a container with caller-supplied
  options. Its existence does not establish that the hosted benchmark runner permits it.
- Data: Kaggle datasets attach to a task (`kaggle b t push <task> -f task.py -d owner/dataset`).
- Runs: `kaggle b t run`, `status`, `log`, `download`. With `WRITE_ATIF=True` each run also
  writes an ATIF trajectory and a result file, the formats that Harbor reads.
- Cost and latency are tracked per call; `evaluate` runs a task over a DataFrame of inputs.

## How the parts map

| QEC-Drift (API harness) | Kaggle Benchmarks |
|---|---|
| Task files: `nominal.stim`, `train.npz`, `val.npz`, `deploy.npz` | Files in an attached dataset, copied into a fresh work folder for each run |
| `run_python(code)` in a macOS `sandbox-exec` profile | A function tool backed by a verified isolated worker, with the same 120 s timeout and 5,000-character output limit; hosted worker not yet available |
| `submit()` with the report fields | A function tool with the same schema; it ends the episode |
| 40 turns, two nudges, a countdown, three failed submits | The same loop in the task function, with manual tool calls through the OpenAI-compatible path |
| Scoring on 300,000 hidden shots in a throwaway copy (the harness makes them with `decoder_task`) | Trusted scoring outside the model-code runtime; test data and decoder execution need separate access controls |
| `gap_closed`, `gap_drift`, the relative pass rule (`references.json`) | Numbers that the task returns, plus one assertion for the pass |
| Failure taxonomy and transcript judge | Offline, on the downloaded runs (ATIF) |
| One table per model and effort | One Kaggle benchmark that groups the 23 core tasks |

## The integrity problem

On our machine the agent's code runs under `sandbox-exec`: it can read only its work folder and
the Python install, and it has no network (`agent/sandbox.py`). A Kaggle notebook runs Linux, and
the agent's code would run as the same user as the scorer. Without changes it could:

- read the test shots and labels if they are files in the dataset;
- import the benchmark package and rebuild the true noise of a task (the defect that
  `isolation.own_install` closed on our machine);
- read the notebook's tokens from the environment;
- fetch the public repository if the run has internet.

Use a Kaggle-managed scoring boundary if one is supported, or run model code in a separate
confined worker. The worker must receive only the visible files during the episode. During
scoring, the decoder may receive hidden detector inputs, but never their labels or the true
noise. Do not mount scorer state, its credentials, a Docker socket, or the benchmark source
into that worker. Restrict the worker's network separately from the model proxy connection.

Encryption at rest can supplement this boundary. It cannot replace it: clearing a child's
environment does not prevent same-user filesystem access or establish process isolation.
Kaggle's public secret client reads an authorization token from the environment, so clearing
it removes that direct inheritance route. This does not prove that a child cannot recover
credentials from another accessible surface. Whether hosted benchmark runs support secrets,
Docker, or separate trusted scoring remains unverified. Fresh secret seeds also do not solve
access to the scorer that holds them.

Before scored deployment, test the actual hosted worker against canary labels and credentials:
reads outside its work folder, imports of the task generator, access to scorer processes and
environment, network access to private services, and links left for the scorer. These checks
must fail while a known-method decoder still runs and scores correctly. Keep the configuration
and probe results with each runner version. A local test does not certify the hosted boundary.

## Time and size

- Budget per episode in the API harness: 40 tool calls, 120 s per `run_python`, 300 s to score.
  The worst case for one model on 23 tasks run one after another is above a day, so episodes
  must run in parallel (`evaluate(n_jobs=...)`) or as separate task runs.
- The visible files of a d = 7 task are about 2.7 MB. Measure the hidden test set per task
  before we choose how to store it.
- The API harness stops an episode at an estimated $4 of model calls. Who pays model calls for
  a community benchmark is a question for Kaggle.

## Build steps (each with its check)

1. Confirm the hosted isolation boundary and resource limits with Kaggle. Prepare exporter
   fixtures locally while this is pending; do not launch scored model episodes.
2. Local fixture export is implemented in `scripts/export_kaggle_tasks.py`: visible files and
   a separate scorer-only bundle of hidden files and references. All 23 core tasks load with
   exact visible field checks. Choose hosted storage after the scoring boundary is established.
3. `kaggle/qec_drift_task.py`: the task function, built from `decoder_run.py` (work folder, two
   tools, loop, scorer, metrics). Check: one local run against the model proxy.
4. A Linux runner for `run_python` and a self-test: model code must fail to read the key, the
   hidden files in clear, and the environment tokens. Check: the self-test passes on Kaggle.
5. Parity: one model on the 23 tasks through our API harness and through Kaggle. Check: pass
   rates agree within sampling noise.
6. Push and group: `kaggle b t push qec-drift -f kaggle/qec_drift_task.py -d <owner>/qec-drift-core --wait`,
   then group the task in the Kaggle web UI.
7. Trajectories: set `WRITE_ATIF=True`; run the failure taxonomy on the ATIF files, and use the
   same files for the Harbor package.

## Local exporter

`scripts/export_kaggle_tasks.py` prepares fixtures without calling a model or the Kaggle API:

```sh
uv run python scripts/export_kaggle_tasks.py \
  --references data/agent_launch2/references.json \
  --visible-out .cache/kaggle-visible \
  --scorer-out .cache/kaggle-scorer
```

The default is the 23-task development core. Both output paths must be new, distinct
directories; neither may contain the other. Existing outputs are never replaced.
The exporter checks every selected reference row before writing files and applies the
same gap and known-method gate as `run_grid.py`.

The visible root contains random task IDs, each holding exactly `nominal.stim`, `train.npz`,
`val.npz` and `deploy.npz`. Train and validation have `det` and `obs`; deployment has `det`
only. The scorer root uses the same IDs and holds `test.npz` (`det`, `obs`, `regime`),
`task.json` (identity and truth), and `references.json`. Only the scorer root has a manifest,
with file hashes, sizes, generator source hashes, library versions, shot counts and seeds.
The manifest is written last; a directory without it is an incomplete export.

The generator preserves shot order and uses the existing seeds. The exporter checks exact
array keys, dimensions and dtypes, rejects extra visible files and links, and removes outputs
from a failed export. A process killed before cleanup can leave incomplete directories.
On November 8, all 23 core fixtures passed the schema and file-hash checks: 162 files,
including the private manifest, with 6.9 million hidden shots. The visible bundle is about
34 MB and the scorer bundle about 84 MB. All 24 exporter tests passed, including both
directions of case-aliased path nesting on the local filesystem and failure cleanup.
These fixtures use the disclosed development tasks, not fresh held-out tasks. The exporter
copies reference rates from the named cache and records that it did not recompute them.

A subsequent local check recomputed nominal and pairwise-refit matching, both plain and
correlated, on all 23 exported test sets. Of 92 rates, 68 matched within the predeclared
1e-12 tolerance. The other 24 each differed by one error in 300,000 shots and matched the
cache after rounding to five decimal places. The strict parity check failed; the differences
are consistent with the stored cache precision, whose original conversion path is unverified.
The cache and historical scores were preserved. Oracle, stale, adaptive and window reference
parity remains pending before use as scored benchmark evidence.

Separate directories are a packaging rule, not an execution sandbox. Keep the scorer bundle
and manifest out of any dataset or filesystem visible to model code. Do not attach the parent
directory of both bundles. Hosted deployment still requires the boundary tests above.

## Questions for the Kaggle Benchmarks team

1. Can a task keep a held-out test set away from code that the model writes? Are Kaggle secrets
   available in task runs?
2. What are the run limits: wall-clock time per run, CPU and memory, parallel runs per model,
   and can internet be off?
3. Are agentic tasks of about 40 tool calls and up to an hour per episode in scope?
4. Which models and reasoning settings can a community benchmark use, and who pays for the
   model calls?
5. Can a task drive a CLI agent (Claude Code, Codex), or only calls through the model proxy?
6. Do stored runs keep the reasoning output when `include_thoughts` is on? We archive every
   trace that an API returns.
7. Can a paper cite the Kaggle leaderboard, and how does Kaggle credit the authors?

## Sources

- [Default local environment](https://github.com/Kaggle/kaggle-benchmarks/blob/5ffefc57696e26b172fc3626392731ebecbb1195/src/kaggle_benchmarks/envs/__init__.py#L18-L22)
- [Local executor and its isolation warning](https://github.com/Kaggle/kaggle-benchmarks/blob/5ffefc57696e26b172fc3626392731ebecbb1195/src/kaggle_benchmarks/envs/local.py#L22-L91)
- [Python execution tools](https://github.com/Kaggle/kaggle-benchmarks/blob/5ffefc57696e26b172fc3626392731ebecbb1195/src/kaggle_benchmarks/tools/python.py#L105-L149)
- [Docker client and container configuration](https://github.com/Kaggle/kaggle-benchmarks/blob/5ffefc57696e26b172fc3626392731ebecbb1195/src/kaggle_benchmarks/envs/docker.py#L35-L82)
- [Secret client's environment credential](https://github.com/Kaggle/docker-python/blob/main/patches/kaggle_web_client.py#L20-L36), checked November 8
- SDK repository: https://github.com/Kaggle/kaggle-benchmarks (README, `CHANGELOG.md`,
  `atif_mapping.md`, `src/kaggle_benchmarks/tools/`, `src/kaggle_benchmarks/envs/`,
  `documentation/examples/prompt_with_tools.py`, `documentation/examples/code_generation.py`)
- Authoring skill: https://github.com/Kaggle/kaggle-skills/blob/main/write-kaggle-benchmarks/SKILL.md
- Launch post: https://blog.google/innovation-and-ai/technology/developers-tools/kaggle-community-benchmarks/
- PyPI: https://pypi.org/project/kaggle_benchmarks/
