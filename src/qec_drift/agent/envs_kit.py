"""The work folder of a data-out task: what the agent may see, and nothing else.

A data-out task (envs/README.md) is a folder under envs/ with TASK.md, evaluate.py, eval/ (the
hidden device, truth, grader and rubric) and sandbox/solution.py (the starter). The agent
writes `solve(data) -> dict`, which returns data, not code that runs next to hidden shots. Each
task's own grader applies that data to hidden test data.

The kit is the folder the agent works in: TASK.md, the starter solution.py, dev_data/*.pkl (the
`data` dict of every public instance, without truth), check.py (runs solve() on dev_data and
checks the return shape and time, no scoring) and PROMPT.md. eval/ is not copied. The kit is
byte-reproducible: the same task and tier give the same files.
"""

from __future__ import annotations

import pickle
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from qec_drift import paths

ENVS = paths.REPO_ROOT / "envs"


def _readout(h: ModuleType, tier: str) -> list[tuple[str, dict]]:
    out = []
    for s, spec in h.instance_list(None, tier=tier):
        kinds = "+".join(k for k, _ in spec) or "none"
        out.append((kinds, h.make_instance(s, spec, tier=tier)[0]))
    return out


# task -> (time limit per instance in s, its public instances as (family, data), the families
# whose change lies outside the model TASK.md states). One entry per task in envs/; each
# harness builds its instances in its own way.
TASKS: dict[str, tuple[int, Callable[[ModuleType, str], list], Callable[[str], bool]]] = {
    "readout_drift": (120, _readout, lambda fam: "iq_stretch" in fam.split("+")),
}

CHECK = '''"""Run solve() from solution.py on every dev_data instance; report shape errors and time.
This does not score: the answers are hidden. Usage: python check.py [N]"""
import pickle, sys, time
from pathlib import Path
import solution
files = sorted(Path("dev_data").glob("*.pkl"))[: int(sys.argv[1]) if len(sys.argv) > 1 else None]
for f in files:
    data = pickle.loads(f.read_bytes())
    t = time.time()
    out = solution.solve(data)
    dt = time.time() - t
    said = out.get("diagnosis", {}).get("changed") if isinstance(out, dict) else None
    ok = isinstance(said, bool)
    print(f"{f.name}: {'ok' if ok else 'BAD RETURN'}  changed={said}  {dt:.1f} s"
          f"{'  OVER LIMIT' if dt > __LIMIT__ else ''}")
'''

PROMPT = """You are solving a research task. Read TASK.md in this folder first.

Rules for this run:
- Work only inside this folder. Do not use the web. Do not look for the task's grader or its
  source anywhere on this machine: it is not here, and looking for it ends the run.
- `python evaluate.py` from TASK.md is not available. Instead, dev_data/ holds the `data`
  dict of each public instance (pickled), without answers. `python check.py` runs your
  solve() on them and checks the return shape and the time limit ({limit} s per instance).
- Edit solution.py. When you are done, it must define solve(data) -> dict as TASK.md says.
  It will be scored afterwards on fresh secret instances you have not seen.
- Python packages available: numpy, scipy, stim, pymatching. Do not install others.
- When you are finished, write a short NOTES_AGENT.md: what you think changes in this task, how
  your solution decides "changed", and what it does about it.
"""

HARD_NOTE = """- Every instance in this run is from the hard tier (`data["tier"] == "hard"`).
  Read the "Hard tier" section of TASK.md: it changes what can happen and what you may report.
- dev_data/ holds only instances whose change, if any, fits the model TASK.md states. The
  scored instances also include devices that break the model in a way no dev instance shows.
"""


def instances(task: str, tier: str) -> list[tuple[str, dict]]:
    """Every public instance of `tier` as (family, data), in the order evaluate.py builds them,
    without truth. Imports the task's own harness, then forgets it: every task's eval/ uses the
    same module names."""
    sys.path.insert(0, str(ENVS / task / "eval"))
    try:
        import harness  # noqa: PLC0415

        return TASKS[task][1](harness, tier)
    finally:
        sys.path.pop(0)
        for name in ("harness", "rubric", "_isolate"):
            sys.modules.pop(name, None)


def public_data(task: str, tier: str) -> list[dict]:
    """The `data` dict of every public instance the agent may see. On the hard tier, every
    instance whose change lies outside the stated model is left out: the scored instances still
    hold them, so a solution must notice a broken model without an example of it, not fit a
    form it saw in the dev data."""
    out_of_model = TASKS[task][2]
    return [d for fam, d in instances(task, tier) if tier != "hard" or not out_of_model(fam)]


def write_kit(task: str, out: Path, tier: str = "hard") -> int:
    """Write one task's kit into the new folder `out`; return the instance count. PROMPT.md is
    written last, so a folder without it is a half-built kit."""
    limit = TASKS[task][0]
    (out / "dev_data").mkdir(parents=True)
    shutil.copy(ENVS / task / "TASK.md", out / "TASK.md")
    shutil.copy(ENVS / task / "sandbox" / "solution.py", out / "solution.py")
    for i, data in enumerate(public_data(task, tier)):
        (out / "dev_data" / f"{i:02d}.pkl").write_bytes(pickle.dumps(data))
    (out / "check.py").write_text(CHECK.replace("__LIMIT__", str(limit)))
    text = PROMPT.format(limit=limit)
    if tier == "hard":
        text = text.replace("- Python packages", HARD_NOTE + "- Python packages")
    (out / "PROMPT.md").write_text(text)
    return len(list((out / "dev_data").glob("*.pkl")))
