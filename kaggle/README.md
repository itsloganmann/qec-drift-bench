# Hosted boundary probe

These files prepare the planned Kaggle isolation check. They do not launch a model,
upload a benchmark, or authorize scored runs. The implementation targets the environment
interface inspected at Kaggle Benchmarks v0.6.2, commit
`5ffefc57696e26b172fc3626392731ebecbb1195`.

Place both Python files together in the actual hosted SDK runtime. Run
`python kaggle_host_probe.py` and retain the JSON result with the runtime configuration.
The command checks `kaggle_benchmarks.envs.current`; it does not configure isolation.
To test another configured worker, call `run_probe(environment)` explicitly. The default
SDK local environment is unsandboxed, so a boundary failure there is expected.

The probe creates only synthetic canaries: a private file, a generator module, an
environment variable, an owned process with a minimal environment, and a loopback service.
It reports accessibility and canary matches without outputting file or environment contents.
The process probe requires a verified shared PID namespace and the owned process start
time. An unavailable or mismatched namespace or a changed start time reports `not_tested`.
Process-file access errors report `readable: false` with the exception type. Resources and parent
environment changes are cleaned up on setup and execution errors.

`boundary_failed` means a synthetic private canary was exposed. `probe_incomplete` means
at least one probe was not tested. `no_canary_exposure_observed` means only that these
probes did not find their canaries; it is not proof of adversarial containment. Every result
keeps `scored_runs_authorized` false. Listed cgroup and process limits are observations,
not proof that the required CPU, memory, or wall-clock limits are enforced.

Local checks: `uv run pytest tests/test_kaggle_host_probe.py`. These include a deliberately
unisolated control, setup-failure cleanup, PID namespace mismatch, PID reuse, and a readable
environment without the canary. They do not certify the hosted environment.

Actual hosted isolation, resource enforcement, scorer link handling, and known-decoder
parity remain required before the [planned benchmark port](../docs/kaggle-benchmarks-port.md)
can run scored model episodes. Keep real hidden shots, labels, generators, and credentials
out of this probe and out of any model-visible dataset.
