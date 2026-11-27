"""Rebuild site/data/ from a mismatch-envs checkout.

usage: uv run python site/build_data.py --envs PATH/TO/mismatch-envs [--out site/data]

Reads the scored results the benchmark already wrote (experiments/results/selection.json,
summary_hard.json, the held-out episode folders) and the public development instances of each
task. Writes results.json (leaderboard numbers) and instances.json (what an agent sees).
Run it with the mismatch-envs environment, which has numpy, scipy, stim and pymatching.

Rules kept here:
- Hard tier, held-out protocol, paper seeds only. No number is typed by hand.
- The instance viewer never gets an instance with the unlisted (out-of-model) change, and no
  name of that change is written. This mirrors the agents' own development data.
"""

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ENVS = ["readout_drift", "pulse_wrong_model", "flux_distortion", "qec_drift_d3"]
SHIPPED_ORDER = ["readout_drift", "pulse_wrong_model"]
BASE = ["reference", "trivial"]  # scripted arms; agent arms are read from the results
CHEATS = {  # strategy -> solution name per env, as in summary_hard.json
    "never": {"qec_drift_d3": "lazy_never_changed", "*": "lazy_blind_refit"},
    "always": {"qec_drift_d3": "lazy_always_changed", "pulse_wrong_model": "lazy_always_changed_robust",
               "*": "lazy_refit_changed"},
    "other": {"*": "lazy_always_other"},
    "const": {"qec_drift_d3": "qec_const", "*": "lazy_const"},
    "malformed": {"*": "lazy_malformed"},
    "frames": {"qec_drift_d3": "qec_frames", "*": "leak_frames"},
    "import": {"qec_drift_d3": "qec_import", "*": "leak_import"},
    "swapped": {"*": "reference_swapped_data"},
}
# The listed (in-model) kinds of change per task, as each TASK.md states them. The viewer keeps
# only instances made of these, so no unlisted change is ever exported or named.
LISTED = {
    "pulse_wrong_model": {"control", "scale", "freq", "compress", "scale_compress"},
    "flux_distortion": {"control", "tail_changed", "new_tail", "both"},
    "qec_drift_d3": {"none", "hot", "onset", "coupler", "burst", "tls"},
}
r3 = lambda x: round(float(x), 3)


def results(root: Path) -> dict:
    res = root / "experiments" / "results"
    sel = json.loads((res / "selection.json").read_text())
    summ = json.loads((res / "summary_hard.json").read_text())
    out = dict(source="mismatch-envs experiments/results (selection.json, summary_hard.json), hard tier, "
               "examples held out, paper seeds", threshold=sel["threshold"], tasks={})
    for t in sel["tasks"]:
        if t["tier"] != "hard" or t["protocol"] != "examples held out" or t["env"] not in ENVS:
            continue
        e, s = t["env"], summ[t["env"]]
        out["tasks"][e] = dict(
            status=t["status"], best=t["best"],
            pass_={m: dict(n=v["n"], rate=r3(v["pass_rate"]), ci=[r3(x) for x in v["pass_ci"]], score=r3(v["score"]))
                   for m, v in t["stats"].items()},
            native=dict(floor=[r3(x) for x in s["trivial"]["score"]],
                        reference=[r3(x) for x in s["reference"]["score"]]),
            cheats={k: r3(s[v.get(e, v.get("*"))]["score"][0]) for k, v in CHEATS.items()})
        out["tasks"][e]["pass"] = out["tasks"][e].pop("pass_")
    days = set()
    for f in glob.glob(str(res / "agent_solutions_hard" / "*-heldout" / "*" / "r*" / "done.json")):
        d = json.loads(Path(f).read_text())
        m = d["model"].replace("@", "-")  # "claude-fable-5-2@xhigh" is scored as "claude-fable-5-2-xhigh"
        if d["env"] not in out["tasks"] or m not in out["tasks"][d["env"]]["pass"]:
            continue
        p = out["tasks"][d["env"]]["pass"][m]
        p.setdefault("wall_min", []).append(round(d["wall_s"] / 60, 1))
        days.add(d["started"][:10])
    for t in out["tasks"].values():
        for p in t["pass"].values():
            if "wall_min" in p:
                p["wall_min"].sort()
    out["scored"] = [min(days), max(days)]
    by, split, boot = scored_rows(root)
    for (e, lab), v in split.items():
        if e in out["tasks"] and lab in out["tasks"][e]["pass"]:
            out["tasks"][e]["pass"][lab]["split"] = {k: dict(n=len(x), rate=r3(np.mean(x))) for k, x in v.items()}
    agents = sorted({m for t in out["tasks"].values() for m in t["pass"] if m not in BASE})
    out["models"] = agents
    shipped = [e for e in SHIPPED_ORDER if out["tasks"][e]["status"] == "included"]
    arms = [a for a in agents + BASE if all(a in out["tasks"][e]["pass"] for e in shipped)]
    out["composite"] = composite(by, boot, shipped, arms)
    return out


def scored_rows(root: Path):
    """Per-instance pass flags of the hard tier, held-out protocol, paper seeds: by (task, arm) and
    seed cluster, and by (task, arm) split into controls and changed devices."""
    sys.path.insert(0, str(root / "experiments"))
    import analyze  # noqa: E402
    import selection  # noqa: E402
    analyze.TIER = "hard"
    by = defaultdict(lambda: defaultdict(list))
    split = defaultdict(lambda: defaultdict(list))
    for r in selection.mismatch_rows(analyze.load()):
        if r["seed_set"] != "paper":
            continue
        if r["kind"] == "agent" and r["model"].endswith("-heldout"):
            lab = r["model"][: -len("-heldout")]
        elif r["solution"] in ("reference", "trivial"):
            lab = r["solution"]
        else:
            continue
        by[(r["task"], lab)][r["cluster"]].append(float(r["passed"]))
        split[(r["task"], lab)]["changed" if r["truth_changed"] else "controls"].append(float(r["passed"]))
    return by, split, analyze.BOOT


def composite(by: dict, boot: dict, shipped: list, arms_in: list) -> dict:
    """Mean pass rate over the shipped tasks. 95% interval: an independent seed-cluster bootstrap
    per task (the experiments' own resample count and seed), averaged draw by draw."""
    n, arms = boot["resamples"], {}
    for lab in arms_in:
        rng = np.random.default_rng(boot["rng_seed"])
        draws, points = [], []
        for e in shipped:
            vals = by[(e, lab)]
            keys = sorted(vals)
            a = [np.asarray(vals[k]) for k in keys]
            points.append(float(np.mean(np.concatenate(a))))
            b = np.empty(n)
            for i in range(n):
                pick = rng.integers(0, len(keys), len(keys))
                b[i] = np.mean(np.concatenate([a[j][rng.integers(0, len(a[j]), len(a[j]))] for j in pick]))
            draws.append(b)
        m = np.mean(draws, axis=0)
        arms[lab] = dict(mean=r3(np.mean(points)), ci=[r3(x) for x in np.quantile(m, [0.025, 0.975])],
                         per=[r3(p) for p in points])
    clusters = len(by[(shipped[0], "reference")])
    return dict(tasks=shipped, clusters=clusters, method="plain mean of per-task pass rates; 95% interval from "
                "independent seed-cluster bootstraps per task, averaged draw by draw", arms=arms)


def harness(root: Path, env: str):
    """Import one task's grader module. Each task's eval/ folder uses the same module names, so the
    previous task's folder and modules are dropped first; the folder stays on the path while used."""
    sys.path[:] = [p for p in sys.path if not p.endswith("/eval")]
    sys.path.insert(0, str(root / env / "eval"))
    for m in ("harness", "rubric", "_isolate", "evidence"):
        sys.modules.pop(m, None)
    import harness as h  # noqa: E402
    return h


def instances(root: Path, readout_examples: int = 5) -> dict:
    """A few public hard-tier development instances per task, one per kind of change, in-model only."""
    r = lambda a, k=3: [round(float(x), k) for x in a]
    out = {}
    h = harness(root, "readout_drift")
    ro, seen = [], set()
    for s, spec in h.instance_list(tier="hard"):
        kinds = tuple(sorted(k for k, _ in spec))
        if not set(kinds) <= set(h.KINDS) or kinds in seen or len(ro) >= readout_examples:
            continue
        seen.add(kinds)
        x = h.make_instance(s, spec, tier="hard")[0]
        idx = np.random.default_rng(0).choice(len(x["calib_iq"]), 600, replace=False)
        ro.append(dict(truth=[[k, str(m)] for k, m in spec], calib_n=len(x["calib_iq"]),
                       calib=[r(x["calib_iq"][i]) + [int(x["calib_labels"][i])] for i in idx],
                       shots=[r(x["shots_iq"][i]) + [int(x["shots_batch"][i])] for i in range(len(x["shots_iq"]))]))
    out["readout"] = ro
    h = harness(root, "pulse_wrong_model")
    h.use_tier("hard")
    pu, seen = [], set()
    for inst in h.build(h.PUBLIC_SEED, h.N_INSTANCES):
        k, d = inst["kind"], inst["data"]
        if k not in LISTED["pulse_wrong_model"] or k in seen:
            continue
        seen.add(k)
        pu.append(dict(truth=k, rabi_amps=r(d["rabi_amps"]), rabi=r(d["rabi_p_exc"]),
                       ram_t=r(d["ramsey_delays_ns"], 1), ram=r(d["ramsey_p1"])))
    out["pulse"] = pu
    h = harness(root, "flux_distortion")
    fl, seen = [], set()
    for s, i, fam in h.instance_list(tier="hard"):
        if fam not in LISTED["flux_distortion"] or fam in seen:
            continue
        seen.add(fam)
        d = h.build(s, i, fam)["data"]
        fl.append(dict(truth=fam, t=r(d["t_ns"], 2), step=r(d["step"], 5), sigma=r(d["sigma"], 6)))
    out["flux"] = fl
    h = harness(root, "qec_drift_d3")
    s, mix = h.instance_list(None, False, "hard")
    qe, seen = [], set()
    for i, fam in enumerate(mix):
        if fam not in LISTED["qec_drift_d3"] or fam in seen:
            continue
        seen.add(fam)
        d = h.build_instance(s, i, fam, "hard")[0]
        pre, post = np.asarray(d["pre_detectors"]), np.asarray(d["post_detectors"])
        qe.append(dict(truth=fam, coords={str(k): list(map(float, v)) for k, v in d["detector_coords"].items()},
                       qcoords={str(k): list(map(float, v)) for k, v in d["qubit_coords"].items()},
                       data_q=list(map(int, d["data_qubits"])), meas_q=list(map(int, d["measure_qubits"])),
                       pre=r(pre.mean(0), 4), post=r(post.mean(0), 4),
                       windows=[r(w.mean(0), 4) for w in np.array_split(post, 25)]))
    out["qec"] = qe
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envs", type=Path, required=True, help="path to a mismatch-envs checkout")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    a = ap.parse_args()
    root = a.envs.resolve()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "results.json").write_text(json.dumps(results(root), indent=1) + "\n")
    (a.out / "instances.json").write_text(json.dumps(instances(root), separators=(",", ":")))
    print("wrote", a.out / "results.json", a.out / "instances.json")


if __name__ == "__main__":
    main()
