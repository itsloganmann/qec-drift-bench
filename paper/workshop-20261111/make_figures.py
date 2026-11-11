"""Rebuild paper figures from the shipped, anonymous aggregate evidence."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parent
D = json.loads((ROOT / "evidence/paper-aggregates.json").read_text())
OUT = ROOT / "figures"
OUT.mkdir(exist_ok=True)
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
    }
)
TEAL, BLUE, ORANGE, GRAY = "#087e8b", "#496c9d", "#bf663b", "#737d88"


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=240, bbox_inches="tight")
    plt.close(fig)


def outcomes():
    fig, (ax, bx) = plt.subplots(
        1,
        2,
        figsize=(7.0, 2.65),
        gridspec_kw={"width_ratios": [1, 1.52]},
        layout="constrained",
    )
    q = D["development"]["quadrants"]
    matrix = np.array(
        [
            [q["diagnosis_0_fix_0"], q["diagnosis_0_fix_1"]],
            [q["diagnosis_1_fix_0"], q["diagnosis_1_fix_1"]],
        ]
    )
    assert matrix.sum() == 497
    for (y, x), n in np.ndenumerate(matrix):
        color = TEAL if x == y == 1 else (ORANGE if y == 1 else GRAY)
        ax.add_patch(
            FancyBboxPatch(
                (x - 0.46, y - 0.43),
                0.92,
                0.86,
                boxstyle="round,pad=0.02",
                facecolor=color,
                alpha=0.12,
                linewidth=0,
            )
        )
        ax.text(
            x,
            y + 0.06,
            str(n),
            ha="center",
            va="center",
            fontsize=17,
            color=color,
            weight="bold",
        )
        ax.text(x, y - 0.23, f"{100 * n / 497:.1f}%", ha="center", fontsize=8)
    ax.set(
        xlim=(-0.53, 1.53),
        ylim=(-0.53, 1.53),
        xticks=[0, 1],
        xticklabels=["Repair fails", "Repair passes"],
        yticks=[0, 1],
        yticklabels=["Wrong", "Correct"],
        ylabel="Diagnosis",
    )
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title("A  Diagnosis does not ensure repair", loc="left", fontsize=9, weight="bold")
    families = sorted(
        D["families"],
        key=lambda f: D["families"][f]["passes"] / D["families"][f]["valid"],
    )
    names = {
        "adequate nominal": "Adequate controls",
        "local qubit": "Local qubit",
        "measurement": "Readout",
        "moving gates": "Moving gates",
        "moving qubits": "Moving qubits",
        "spatial patch": "Spatial patch",
        "telegraph noise": "Telegraph",
        "combined faults": "Compound",
    }
    for y, f in enumerate(families):
        s = D["families"][f]
        a, b = 100 * s["passes"] / s["valid"], 100 * s["diagnosis_correct"] / s["valid"]
        bx.plot([a, b], [y, y], color="#c8cfd5", lw=2, zorder=1)
        bx.scatter(a, y, c=TEAL, s=24, label="Joint pass" if y == 0 else None, zorder=3)
        bx.scatter(
            b,
            y,
            c=BLUE,
            marker="s",
            s=20,
            label="Diagnosis" if y == 0 else None,
            zorder=3,
        )
    bx.set(
        yticks=range(len(families)),
        yticklabels=[f"{names[f]} (n={D['families'][f]['valid']})" for f in families],
        xlim=(-3, 104),
        xticks=[0, 25, 50, 75, 100],
        xlabel="Within-family episodes (%)",
    )
    bx.invert_yaxis()
    bx.grid(axis="x", color="#e7eaed", lw=0.6)
    bx.set_axisbelow(True)
    bx.legend(loc="upper right", frameon=True, facecolor="white", edgecolor="none", fontsize=7)
    bx.set_title("B  Moving faults expose larger gaps", loc="left", fontsize=9, weight="bold")
    save(fig, "diagnosis-repair")


def trajectories():
    fig, (ax, bx) = plt.subplots(
        1,
        2,
        figsize=(7.0, 2.65),
        gridspec_kw={"width_ratios": [1, 1.3]},
        layout="constrained",
    )
    keys = [
        "passed",
        "plain_matching",
        "under_adapted",
        "harmful_decoder",
        "nominal_unchanged",
        "misdiagnosis",
        "out_of_budget",
    ]
    names = [
        "Joint pass",
        "Plain fitted",
        "Under-adapted",
        "Harmful",
        "Nominal",
        "Diagnosis failure",
        "Budget exhausted",
    ]
    values = [
        [int(k) for k, n in D["tool_calls_by_rule_label"][key].items() for _ in range(n)]
        for key in keys
    ]
    assert sum(map(len, values)) == 533
    box = ax.boxplot(
        values,
        orientation="horizontal",
        tick_labels=[f"{s} ({len(v)})" for s, v in zip(names, values, strict=True)],
        widths=0.5,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "#233440", "linewidth": 1.1},
        whiskerprops={"color": GRAY},
        capprops={"color": GRAY},
    )
    for i, patch in enumerate(box["boxes"]):
        patch.set(facecolor=TEAL if i == 0 else (ORANGE if i == 6 else BLUE), alpha=0.35)
    ax.axvline(40, color=ORANGE, ls="--", lw=0.9)
    ax.set(
        xlim=(0, 44),
        xticks=[0, 10, 20, 30, 40],
        xlabel="Completed tool calls (archived count)",
    )
    ax.invert_yaxis()
    ax.set_title("A  Tool use overlaps", loc="left", fontsize=9, weight="bold")
    bx.set(xlim=(0, 3), ylim=(-0.65, 2.85))
    bx.axis("off")
    bx.set_title("B  Trace-grounded failure paths", loc="left", fontsize=9, weight="bold")
    cases = [
        [
            "Prediction/label\nshapes differ",
            "Broadcasted\nvalidation loss",
            "Harmful\ndecoder",
        ],
        [
            "Class index used\nas physical ID",
            "Wrong regime\ndispatch",
            "Insufficient\nrepair",
        ],
        [
            "49 qubits reported;\n21 changed",
            "Localization\nJaccard < 0.5",
            "Good repair;\nwrong diagnosis",
        ],
    ]
    for y, row in enumerate(cases):
        yy = 2.25 - y
        for x, text in enumerate(row):
            color = ORANGE if x == 2 else BLUE
            bx.add_patch(
                FancyBboxPatch(
                    (x + 0.02, yy - 0.29),
                    0.88,
                    0.6,
                    boxstyle="round,pad=0.03",
                    fc=color,
                    alpha=0.1,
                    ec="none",
                )
            )
            bx.text(x + 0.46, yy, text, ha="center", va="center", fontsize=7)
            if x < 2:
                bx.annotate(
                    "",
                    xy=(x + 1.01, yy),
                    xytext=(x + 0.93, yy),
                    arrowprops={"arrowstyle": "->", "color": GRAY, "lw": 0.8},
                )
    bx.text(
        1.48,
        -0.49,
        (
            "Selected cases; arrows summarize observed code paths,\n"
            "not controlled causal effects or measured prevalence."
        ),
        ha="center",
        va="center",
        fontsize=7,
        color=GRAY,
    )
    save(fig, "trajectory-audit")


if __name__ == "__main__":
    outcomes()
    trajectories()
