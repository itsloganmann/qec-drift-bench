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


def mece_taxonomy():
    """Plot the complete conditional codebook beside saved transcript labels."""
    tax = json.loads((ROOT / "evidence/hierarchical-taxonomy.json").read_text())
    rows = tax["codebook"]
    assert len({r["label"] for r in rows}) == 8
    assert sum(tax["judge_labels"].get(r["label"], 0) for r in rows) == 387
    colors = {
        "Execution / delivery": GRAY,
        "Decoder repair": BLUE,
        "Diagnosis / report": ORANGE,
    }
    fig, ax = plt.subplots(figsize=(7.0, 3.1), layout="constrained")
    ax.set(xlim=(0, 10.8), ylim=(-0.85, 8.0))
    ax.axis("off")
    for x, title in [
        (0, "L1: failure area"),
        (2.0, "L2: failure class"),
        (4.35, "L3: assigned failure mode"),
        (7.45, "Trajectory-review distribution"),
    ]:
        ax.text(x, 7.72, title, fontsize=8, weight="bold", va="center")
    groups = {}
    pairs = {}
    for i, row in enumerate(rows):
        y = 7 - i
        groups.setdefault(row["l1"], []).append(y)
        pairs.setdefault((row["l1"], row["l2"]), []).append(y)
    labels1 = {
        "Execution / delivery": "Execution /\ndelivery",
        "Decoder repair": "Decoder\nrepair",
        "Diagnosis / report": "Diagnosis/report",
    }
    labels2 = {
        "Budget or early stop": "Budget or\nearly stop",
        "Scoring execution": "Scoring\nexecution",
        "Regression": "Regression",
        "Insufficient update": "Insufficient\nupdate",
        "Report correctness": "Report\ncorrectness",
    }
    for name, ys in groups.items():
        mid = sum(ys) / len(ys)
        n = tax["l1_review_counts"][name]
        ax.add_patch(
            FancyBboxPatch(
                (0, min(ys) - 0.34),
                1.65,
                max(ys) - min(ys) + 0.68,
                boxstyle="round,pad=0.03",
                fc=colors[name],
                ec="none",
                alpha=0.12,
            )
        )
        ax.text(
            0.825,
            mid + 0.15,
            labels1[name],
            ha="center",
            va="center",
            fontsize=8,
            weight="bold",
        )
        ax.text(
            0.825,
            mid - (0.35 if len(ys) == 1 else 0.65),
            f"{100 * n / 387:.1f}%",
            ha="center",
            fontsize=7,
            color=colors[name],
        )
    for (l1, l2), ys in pairs.items():
        mid = sum(ys) / len(ys)
        ax.plot(
            [1.7, 1.85, 1.85, 2],
            [
                sum(groups[l1]) / len(groups[l1]),
                sum(groups[l1]) / len(groups[l1]),
                mid,
                mid,
            ],
            color="#bac4cb",
            lw=0.8,
        )
        ax.add_patch(
            FancyBboxPatch(
                (2.0, min(ys) - 0.3),
                1.72,
                max(ys) - min(ys) + 0.6,
                boxstyle="round,pad=0.03",
                fc=colors[l1],
                ec="none",
                alpha=0.07,
            )
        )
        ax.text(2.86, mid, labels2[l2], ha="center", va="center", fontsize=7.5)
    for i, row in enumerate(rows):
        y = 7 - i
        ys = pairs[(row["l1"], row["l2"])]
        ax.plot(
            [3.76, 3.95, 3.95, 4.25],
            [sum(ys) / len(ys), sum(ys) / len(ys), y, y],
            color="#bac4cb",
            lw=0.8,
        )
        ax.text(4.35, y, row["l3"], fontsize=7.8, va="center")
        n = tax["judge_labels"].get(row["label"], 0)
        nr = tax["rule_labels"].get(row["label"], 0)
        ax.barh(y, 2.2 * n / 116, height=0.39, left=7.4, color=colors[row["l1"]], alpha=0.8)
        ax.text(9.7, y, f"{n} ({nr})", va="center", fontsize=7.4)
    ax.text(7.4, -0.48, "Review n (frozen-rule n)", fontsize=7, color=GRAY)
    save(fig, "mece-taxonomy")


def trajectory_example():
    """Show exact observable code fragments and their explicit review annotation."""
    ex = json.loads((ROOT / "evidence/trajectory-example.json").read_text())
    assert ex["review_label"] == "harmful_decoder"
    quoted = (
        "mismeasured nominal matching by broadcasting predictions against labels in `np.mean(p!=y)`"
    )
    assert quoted in ex["review_excerpt"]
    fig, ax = plt.subplots(figsize=(3.35, 2.9), layout="constrained")
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    ax.text(
        0,
        0.98,
        "Trajectory excerpt and failure annotation",
        fontsize=8.1,
        weight="bold",
        va="top",
    )
    ax.add_patch(
        FancyBboxPatch(
            (0, 0.55),
            1,
            0.34,
            boxstyle="round,pad=0.01",
            facecolor="#edf2f5",
            edgecolor="none",
        )
    )
    ax.text(0.025, 0.86, "Recorded tool-code fragments:", fontsize=7.2, va="top", color=GRAY)
    ax.text(
        0.025,
        0.78,
        "\n".join(ex["code_fragments"]),
        fontsize=7.1,
        va="top",
        family="DejaVu Sans Mono",
        linespacing=1.4,
    )
    ax.text(
        0.025,
        0.575,
        ex["observed_stdout_prefix"],
        fontsize=6.9,
        family="DejaVu Sans Mono",
        va="bottom",
        color=BLUE,
    )
    ax.text(0, 0.49, "Model-assisted review:", fontsize=7.4, weight="bold", va="top")
    ax.text(
        0,
        0.425,
        (
            "“mismeasured nominal matching by broadcasting\n"
            "predictions against labels in `np.mean(p!=y)`”"
        ),
        fontsize=7.1,
        va="top",
        linespacing=1.35,
    )
    ax.add_patch(
        FancyBboxPatch(
            (0, 0.02),
            1,
            0.24,
            boxstyle="round,pad=0.01",
            facecolor=ORANGE,
            alpha=0.11,
            edgecolor="none",
        )
    )
    ax.text(
        0.025,
        0.235,
        "L1 Decoder repair > L2 Regression",
        fontsize=7.4,
        weight="bold",
        va="top",
        color=ORANGE,
    )
    ax.text(0.025, 0.16, "L3 “harmful_decoder”", fontsize=7.8, weight="bold", va="top")
    ax.text(
        0.025,
        0.085,
        f"Frozen score: G = {ex['frozen_gap_closed']:.3f} < 0",
        fontsize=7.3,
        va="top",
    )
    save(fig, "trajectory-example")


if __name__ == "__main__":
    outcomes()
    mece_taxonomy()
    trajectory_example()
