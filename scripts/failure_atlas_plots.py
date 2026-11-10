"""Export atlas aggregates as standalone PNG and SVG figures.

uv run --with matplotlib python scripts/failure_atlas_plots.py ATLAS_JSON OUTPUT
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def plots(source: Path, output: Path) -> None:
    data = json.loads(source.read_text())
    current = data["cohorts"]["agent_launch2"]
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
        }
    )

    def save(fig, name):
        for ext in ("png", "svg"):
            fig.savefig(output / f"{name}.{ext}", dpi=170, bbox_inches="tight")
        plt.close(fig)

    labels = sorted(current["labels"], key=current["labels"].get)
    values = [current["labels"][key] for key in labels]
    fig, ax = plt.subplots(figsize=(11, 6), constrained_layout=True)
    colors = ["#168f85" if key == "passed" else "#547c9f" for key in labels]
    ax.barh([data["names"][k] for k in labels], values, color=colors)
    ax.bar_label(ax.containers[0], padding=5)
    ax.set_xlim(0, max(values) * 1.15)
    ax.set(
        xlabel="Recorded development episodes (count)",
        title=f"Only {current['passes']} of {current['valid']} development runs pass jointly",
    )
    fig.supxlabel(
        "Frozen rule labels. Cross-check: labels total 533, matching the scored-row inventory.",
        fontsize=10,
        color="#526570",
    )
    save(fig, "development-failure-mix")

    families = sorted(
        current["families"], key=lambda f: current["families"][f]["valid"], reverse=True
    )
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), constrained_layout=True)
    for ax, metric, denominator, title, color in (
        (axes[0], "passes", "valid", "Joint diagnosis + repair", "#168f85"),
        (axes[1], "diagnosis_correct", "diagnosis_measured", "Correct diagnosis", "#547c9f"),
    ):
        nums = [current["families"][f][metric] for f in families]
        dens = [current["families"][f][denominator] for f in families]
        rates = [100 * n / d if d else 0 for n, d in zip(nums, dens, strict=True)]
        ax.barh(families, rates, color=color)
        ax.invert_yaxis()
        ax.set(xlim=(0, 115), xlabel="Within-family rate (%)", title=title)
        for index, (n, den, rate) in enumerate(zip(nums, dens, rates, strict=True)):
            ax.text(rate + 1.5, index, f"{n}/{den}", va="center", fontsize=10)
    fig.suptitle(
        "Diagnosis accuracy and joint repair success have different bottlenecks", fontsize=15
    )
    fig.supxlabel(
        "Each bar shows its own denominator. Families share templates; rates are descriptive.",
        fontsize=10,
        color="#526570",
    )
    save(fig, "development-fault-families")

    models = current["models"]
    leaves = [key for key in data["names"] if any(m["labels"].get(key) for m in models.values())]
    matrix = np.array([[models[arm]["labels"].get(leaf, 0) for leaf in leaves] for arm in models])
    fig, ax = plt.subplots(figsize=(12, 11), constrained_layout=True)
    ax.imshow(matrix, cmap="Blues", vmin=0, vmax=max(int(matrix.max()), 1), aspect="auto")
    ax.set_yticks(range(len(models)), [arm.replace("_", " ") for arm in models], fontsize=9)
    ax.set_xticks(
        range(len(leaves)), [data["names"][key] for key in leaves], rotation=40, ha="right"
    )
    for i, _arm in enumerate(models):
        for j, count in enumerate(matrix[i]):
            if count:
                ax.text(
                    j,
                    i,
                    str(count),
                    ha="center",
                    va="center",
                    color="white" if count > matrix.max() * 0.55 else "#163746",
                    fontsize=9,
                )
    ax.set(
        title="Arms show different failure mixes on the selected development tasks",
        xlabel="Failure or success label; cell values are episode counts",
    )
    fig.supxlabel(
        "Alphabetical arm order. Most arms have n=23; Claude arm n=4. This is not a ranking.",
        fontsize=10,
        color="#526570",
    )
    save(fig, "development-arm-matrix")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    plots(args.source, args.output)
