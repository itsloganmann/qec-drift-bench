"""Run a solution's solve(data) in a fresh, isolated Python process. Same file in every env.

The child runs `python -I` (no PYTHONPATH, no user site, no script dir) in an empty temp dir,
with sys.path = [solution's own folder] + the interpreter's stdlib and site-packages. eval/ and
the env folder are not on it. It gets only `data` (pickled by the grader), and an environment
stripped of everything but PATH and thread pins, so MISMATCH_SEED is not visible. It returns
plain JSON; complex numbers come back as {"__complex__": [re, im]}. The grader never unpickles
anything the solver wrote. Real sandboxing (filesystem, /proc) is the platform's job.

Data ablation (maintainers): with MISMATCH_ABLATE=1 in the grader's environment, each call hands
the solver the previous instance's data instead of its own (the first instance keeps its own,
which can only raise the ablated score). A task that needs its data must then collapse; see
run_all.py --ablate. The solver's environment is stripped, so it cannot see the flag.
Licence: Apache-2.0.
"""
import json
import os
import pickle
import subprocess
import sys
import tempfile
import time

import numpy as np

_CHILD = r"""
import importlib.util, json, pickle, sys
sol, tmp = sys.argv[1], sys.argv[2]
sys.path.insert(0, sys.argv[3])
import numpy as np
def plain(o):
    if isinstance(o, dict):
        return {str(k): plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        a = np.asarray(o) if len(o) and all(isinstance(x, (int, float, complex, np.number)) for x in o) else None
        return plain(a) if a is not None and a.dtype.kind in "biufc" else [plain(x) for x in o]
    if isinstance(o, np.ndarray):
        return {"__complex__": [o.real.tolist(), o.imag.tolist()]} if o.dtype.kind == "c" else o.tolist()
    if isinstance(o, (complex, np.complexfloating)):
        return {"__complex__": [float(o.real), float(o.imag)]}
    return o.item() if isinstance(o, np.generic) else o
with open(tmp + "/data.pkl", "rb") as f:
    data = pickle.load(f)
spec = importlib.util.spec_from_file_location("solution", sol)
mod = importlib.util.module_from_spec(spec)
sys.modules["solution"] = mod
spec.loader.exec_module(mod)
out = plain(mod.solve(data))
with open(tmp + "/out.json", "w") as f:
    json.dump(out, f, allow_nan=True)
"""


def _unplain(o):
    if isinstance(o, dict):
        if set(o) == {"__complex__"}:
            re, im = o["__complex__"]
            return np.asarray(re, dtype=float) + 1j * np.asarray(im, dtype=float)
        return {k: _unplain(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_unplain(x) for x in o]
    return o


_PREV = []


def _not_dumpable():
    """Linux: mark the grader process non-dumpable (prctl PR_SET_DUMPABLE = 0), so a solver
    running as the same user cannot read the grader's memory, which holds the hidden truth,
    through /proc/<pid>/mem. A no-op elsewhere; a process with CAP_SYS_PTRACE can still read
    it, which only the sealed harness closes."""
    if sys.platform.startswith("linux"):
        try:
            import ctypes
            ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)
        except (OSError, AttributeError):
            pass


def run_solver(solution_path, data, timeout_s):
    """Return (ok, output_or_error_text, seconds). Never raises for solver faults."""
    _not_dumpable()
    if os.environ.get("MISMATCH_ABLATE") == "1":
        _PREV.append(data)
        data = _PREV.pop(0) if len(_PREV) > 1 else data
    sol = os.path.abspath(solution_path)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"}
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        env[v] = "1"
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="solve_") as tmp:
        with open(os.path.join(tmp, "data.pkl"), "wb") as f:
            pickle.dump(data, f)
        cmd = [sys.executable, "-I", "-c", _CHILD, sol, tmp, os.path.dirname(sol)]
        try:
            p = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True,
                               timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return False, "timeout", time.time() - t0
        if p.returncode != 0:
            return False, (p.stderr.strip().splitlines() or ["exit %d" % p.returncode])[-1][:300], \
                time.time() - t0
        try:
            with open(os.path.join(tmp, "out.json")) as f:
                return True, _unplain(json.load(f)), time.time() - t0
        except (OSError, ValueError) as e:
            return False, "malformed output: %s" % e, time.time() - t0
