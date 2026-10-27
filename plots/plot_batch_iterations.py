"""
Score evolution across batch specialization iterations, ATL and EMF in ONE plot.

Usage:
    python plots/plot_batch_iterations.py

Reads   results/run_*/<id>_specialization.txt       (ATL, 5 runs)
        results/run_*/<id>_emf_specialization.txt   (EMF, 5 runs)
        lines "Iteration k summary | avg_score=..."  (average on the train set)
Writes  outputs/figures/batch_iterations_atl_emf.png / .pdf

For each domain: thin lines = runs, thick line = mean, band = ±1 std.
"""
import os
import re
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Run from the repo root, whatever the current directory is
os.chdir(Path(__file__).resolve().parents[1])
OUT = Path("outputs/figures/batch_iterations_atl_emf.png")
OUT.parent.mkdir(parents=True, exist_ok=True)

SUMMARY = re.compile(r"Iteration (\d+) summary \| avg_score=(\d+\.\d+)")
DOMAINS = {   # name: (log filter, mean colour, run colour)
    "ATL (model transformations)": (lambda name: "emf" not in name, "#a50f15", "#fc9272"),
    "EMF (metamodel editing)":     (lambda name: "emf" in name,     "#08306b", "#9ecae1"),
}
INK = "#333333"


def load_runs(keep) -> list[dict[int, float]]:
    """One {iteration: avg_score} dict per run of the domain."""
    runs = []
    for log in sorted(Path("results").glob("run_*/*_specialization.txt")):
        if keep(log.name):
            iters = {int(k): float(v) for k, v in SUMMARY.findall(log.read_text())}
            if iters:
                runs.append(iters)
    return runs


fig, ax = plt.subplots(figsize=(8, 4.5))

for name, (keep, mean_color, run_color) in DOMAINS.items():
    runs = load_runs(keep)
    iters = sorted({k for r in runs for k in r})
    mean = [statistics.mean(r[k] for r in runs if k in r) for k in iters]
    std = [statistics.stdev([r[k] for r in runs if k in r]) if len(runs) > 1 else 0 for k in iters]
    short = name.split()[0]

    for i, r in enumerate(runs):
        ks = sorted(r)
        ax.plot(ks, [r[k] for k in ks], color=run_color, linewidth=0.9, alpha=0.8,
                label=f"{short}: one run" if i == 0 else None)
    ax.fill_between(iters, [m - s for m, s in zip(mean, std)], [m + s for m, s in zip(mean, std)],
                    color=mean_color, alpha=0.12, linewidth=0, label=f"{short}: ±1 std")
    ax.plot(iters, mean, color=mean_color, linewidth=2.5, marker="o", markersize=5,
            label=f"{name}: mean of {len(runs)} runs")
    print(f"{short}: {len(runs)} runs, mean {mean[0]:.2f} (iter 0) -> {mean[-1]:.2f} (iter {iters[-1]})")

ax.set_xticks(range(0, 9))
ax.set_ylim(0, 1.05)
ax.set_xlabel("Specialization iteration", color=INK)
ax.set_ylabel("Avg score (train set)", color=INK)
ax.set_title("Score evolution across specialization iterations (5 runs each)", color=INK)
ax.grid(alpha=0.3, linestyle="--", linewidth=0.6)
for side in ("top", "right"):
    ax.spines[side].set_visible(False)
ax.legend(fontsize=8, loc="lower right", ncol=2)

fig.tight_layout()
fig.savefig(OUT, dpi=200, bbox_inches="tight")
fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight")
print(f"Saved: {OUT} (+ .pdf)")
