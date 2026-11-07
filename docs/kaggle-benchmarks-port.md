# Porting QEC-Drift to Kaggle Benchmarks (plan, 2026-11-07)

**Outcome.** The API harness (`src/qec_drift/agent/decoder_run.py`) maps almost one to one onto
a `kaggle-benchmarks` task: two tools, a tool-call budget, and scoring in a throwaway folder.
Two points need an answer from Kaggle before we build:

1. How to keep the hidden test shots, their labels and the true noise away from model-written
   code that runs inside the same Kaggle notebook as the scorer.
2. Whether an agent episode of up to 40 tool calls, 23 times per model, fits the run limits.

Nothing in this plan changes the tasks. A Kaggle leaderboard on the same 23 core tasks is
comparable with the API-harness column of our own grid.

## What Kaggle Benchmarks gives

From the SDK source (`Kaggle/kaggle-benchmarks`, v0.6.2, 2026-10-21) and the launch post:

- A task is a Python function with the `@kbench.task` decorator. It gets an `llm` object and
  calls `llm.prompt(...)`. Kaggle runs it for each model through its model proxy and builds a
  leaderboard from the stored runs.
- Tool calls: automatic through the `genai` API path, manual through the OpenAI-compatible path
  (the task code runs the loop). `prompt()` takes `tools`, `reasoning` and `include_thoughts`.
- Code execution: `tools.python.script_runner` (a subprocess per script) and `IPythonREPL` (a
  second kernel). `envs.DockerEnvironment` exists, but it needs a Docker daemon, which a Kaggle
  notebook does not appear to have.
- Data: Kaggle datasets attach to a task (`kaggle b t push <task> -f task.py -d owner/dataset`).
- Runs: `kaggle b t run`, `status`, `log`, `download`. With `WRITE_ATIF=True` each run also
  writes an ATIF trajectory and a result file, the formats that Harbor reads.
- Cost and latency are tracked per call; `evaluate` runs a task over a DataFrame of inputs.

## How the parts map

| QEC-Drift (API harness) | Kaggle Benchmarks |
|---|---|
| Task files: `nominal.stim`, `train.npz`, `val.npz`, `deploy.npz` | Files in an attached dataset, copied into a fresh work folder for each run |
| `run_python(code)` in a macOS `sandbox-exec` profile | A function tool that runs the code in a subprocess: work folder as cwd, a clean environment, 120 s timeout, 5,000-character output |
| `submit()` with the report fields | A function tool with the same schema; it ends the episode |
| 40 turns, two nudges, a countdown, three failed submits | The same loop in the task function, with manual tool calls through the OpenAI-compatible path |
| Scoring on 300,000 hidden shots in a throwaway copy (the harness makes them with `decoder_task`) | The same scorer code, called after `submit`, on test shots made in advance and shipped hidden |
| `gap_closed`, `gap_drift`, the relative pass rule (`references.json`) | Numbers that the task returns, plus one assertion for the pass |
| Failure taxonomy and blinded judge | Offline, on the downloaded runs (ATIF) |
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

Options, best first:

1. **Encrypted hidden files.** The dataset carries the test shots, the labels and the true
   circuit encrypted. The scorer reads the key from a Kaggle secret into memory. The agent's
   subprocess starts with an empty environment, so it cannot fetch the key, and the notebook
   does not install the task generator: the test shots are made in advance, so the scorer needs
   only numpy, and the agent's decoder brings stim and pymatching. The tasks stay exactly the
   same. Open point: are secrets available when Kaggle runs a task?
2. **A test set that Kaggle holds.** If Kaggle Benchmarks can keep a held-out file away from the
   task code, or score on its side, use that.
3. **Fresh instances at run time.** Make each instance from a secret seed and relabel the
   qubits, so nothing hidden is on disk. The cost: the references (oracle and honest adaptive
   decoder) must be computed again for each instance, and scores are no longer on fixed tasks.

Recommendation: option 1, or option 2 if Kaggle offers it. With any option, runs need internet
off, and the legitimacy check (`scripts/legitimacy.py`) runs on the downloaded trajectories.

## Time and size

- Budget per episode in the API harness: 40 tool calls, 120 s per `run_python`, 300 s to score.
  The worst case for one model on 23 tasks run one after another is above a day, so episodes
  must run in parallel (`evaluate(n_jobs=...)`) or as separate task runs.
- The visible files of a d = 7 task are about 2.7 MB. Measure the hidden test set per task
  before we choose how to store it.
- The API harness stops an episode at an estimated $4 of model calls. Who pays model calls for
  a community benchmark is a question for Kaggle.

## Build steps (each with its check)

1. `scripts/export_kaggle_tasks.py`: write the 23 core tasks as a dataset folder (visible files,
   encrypted hidden files, the reference numbers). Check: a dry-run task loads every task.
2. `kaggle/qec_drift_task.py`: the task function, built from `decoder_run.py` (work folder, two
   tools, loop, scorer, metrics). Check: one local run against the model proxy.
3. A Linux runner for `run_python` and a self-test: model code must fail to read the key, the
   hidden files in clear, and the environment tokens. Check: the self-test passes on Kaggle.
4. Parity: one model on the 23 tasks through our API harness and through Kaggle. Check: pass
   rates agree within sampling noise.
5. Push and group: `kaggle b t push qec-drift -f kaggle/qec_drift_task.py -d <owner>/qec-drift-core --wait`,
   then group the task in the Kaggle web UI.
6. Trajectories: set `WRITE_ATIF=True`; run the failure taxonomy on the ATIF files, and use the
   same files for the Harbor package.

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

- SDK repository: https://github.com/Kaggle/kaggle-benchmarks (README, `CHANGELOG.md`,
  `atif_mapping.md`, `src/kaggle_benchmarks/tools/`, `src/kaggle_benchmarks/envs/`,
  `documentation/examples/prompt_with_tools.py`, `documentation/examples/code_generation.py`)
- Authoring skill: https://github.com/Kaggle/kaggle-skills/blob/main/write-kaggle-benchmarks/SKILL.md
- Launch post: https://blog.google/innovation-and-ai/technology/developers-tools/kaggle-community-benchmarks/
- PyPI: https://pypi.org/project/kaggle_benchmarks/
