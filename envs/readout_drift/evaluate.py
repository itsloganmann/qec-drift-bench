"""Score a solution: `python evaluate.py [--solution PATH] [--quick] [--seed N] [--report PATH] [--tier hard]`.

Prints one number, the score in [0, 1] (maximize). Without --seed or MISMATCH_SEED it scores the
fixed public smoke-test set. --report writes the per-instance breakdown, with the hidden truth,
to PATH; it is for maintainers, keep it out of the solver's reach.
"""

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "eval"))


def hide_seed(a: argparse.Namespace) -> int | None:
    """Return the secret seed. If it came from argv or the environment, re-exec once with the
    seed on a pipe and the variable removed, so /proc/<pid>/cmdline and environ never show it to
    the solver's child process."""
    if a.seed_fd is not None:
        with os.fdopen(a.seed_fd) as f:
            return int(f.read())
    seed = a.seed if a.seed is not None else os.environ.get("MISMATCH_SEED")
    if seed is None:
        return None
    r, w = os.pipe()
    os.write(w, str(int(seed)).encode())
    os.close(w)
    os.set_inheritable(r, True)
    argv = [sys.executable, str(HERE / "evaluate.py"), "--solution", a.solution, "--seed-fd", str(r)]
    argv += ["--quick"] * a.quick + (["--report", a.report] if a.report else [])
    argv += ["--tier", a.tier]
    env = {k: v for k, v in os.environ.items() if k != "MISMATCH_SEED"}
    os.execve(sys.executable, argv, env)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--solution", default=str(HERE / "sandbox" / "solution.py"))
    ap.add_argument("--quick", action="store_true", help="8 instances, smaller test sets")
    ap.add_argument("--seed", type=int, help="secret instance seed (or env MISMATCH_SEED)")
    ap.add_argument("--seed-fd", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--report", help="write the per-instance breakdown (with truth) here")
    ap.add_argument("--tier", choices=("standard", "hard"),
                    default=os.environ.get("MISMATCH_TIER", "standard"),
                    help="instance tier (or env MISMATCH_TIER); see TASK.md, hard tier")
    a = ap.parse_args()
    a.solution = str(Path(a.solution).resolve())
    if a.report:
        a.report = str(Path(a.report).resolve())
    seed = hide_seed(a)
    from harness import evaluate  # noqa: E402

    result = evaluate(a.solution, quick=a.quick, seed=seed, tier=a.tier)
    if a.report:
        Path(a.report).write_text(json.dumps(result, indent=1, default=float))
    print(f"{result['score']:.4f}")
