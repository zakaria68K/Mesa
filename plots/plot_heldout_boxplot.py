"""
Box plot of the held-out score (20 test samples) before and after specialization,
ATL and EMF, 5 runs each (same data as the "No Skill / Specialized" table of the paper).

Usage:
    python plots/plot_heldout_boxplot.py

Writes  outputs/figures/heldout_boxplot_atl_emf.png / .pdf

For each domain: one box for "No skill" and one for "Specialized" (median, quartiles,
whiskers = min/max), one dot per run, a grey line joining the two scores of the same run,
and the mean (white diamond, value written above).
"""
import os
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Run from the repo root, whatever the current directory is
os.chdir(Path(__file__).resolve().parents[1])
OUT = Path("outputs/figures/heldout_boxplot_atl_emf.png")
OUT.parent.mkdir(parents=True, exist_ok=True)

# Held-out avg per run R1..R5 (table of the paper)
SCORES = {
    "ATL": {"No skill": [0.69, 0.75, 0.80, 0.62, 0.75], "Specialized": [0.82, 0.90, 0.78, 0.75, 0.72]},
    "EMF": {"No skill": [0.85, 0.88, 0.85, 0.80, 0.78], "Specialized": [0.98, 0.95, 0.87, 0.93, 0.90]},
}
COLORS = {"ATL": ("#a50f15", "#fcbba1"), "EMF": ("#08306b", "#c6dbef")}   # (dark, light)
INK = "#333333"
POS = {"ATL": (1, 2), "EMF": (3.6, 4.6)}   # x positions of (No skill, Specialized)

fig, ax = plt.subplots(figsize=(8, 4.8))

for domain, groups in SCORES.items():
    dark, light = COLORS[domain]
    xs = POS[domain]
    data = list(groups.values())

    # Boxes: the no-skill box is light, the specialized box is filled with the domain colour
    for x, values, face in zip(xs, data, (light, dark)):
        ax.boxplot([values], positions=[x], widths=0.5, whis=(0, 100), showfliers=False,
                   patch_artist=True, manage_ticks=False,
                   boxprops=dict(facecolor=face, edgecolor=dark, linewidth=1.2,
                                 alpha=0.35 if face == dark else 1),
                   medianprops=dict(color=dark, linewidth=2),
                   whiskerprops=dict(color=dark, linewidth=1.2), capprops=dict(color=dark, linewidth=1.2))

    # One dot per run, the two scores of the same run joined by a line
    for before, after in zip(*data):
        ax.plot(xs, (before, after), color="#999999", linewidth=0.8, alpha=0.7, zorder=2)
    for x, values in zip(xs, data):
        ax.scatter([x] * len(values), values, s=24, color=dark, alpha=0.8, zorder=3)

    # Mean of each box
    for x, values in zip(xs, data):
        m = statistics.mean(values)
        ax.scatter([x], [m], marker="D", s=45, color="white", edgecolor=dark, linewidth=1.5, zorder=4)
        ax.annotate(f"mean {m:.2f}", (x, max(values)), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color=INK)

    gain = statistics.mean(data[1]) - statistics.mean(data[0])
    print(f"{domain}: no skill {statistics.mean(data[0]):.2f} -> specialized "
          f"{statistics.mean(data[1]):.2f} ({gain:+.2f})")

ax.set_xticks([x for d in POS for x in POS[d]])
ax.set_xticklabels(["No skill", "Specialized"] * 2)
for domain, xs in POS.items():
    ax.text(sum(xs) / 2, -0.13, domain, transform=ax.get_xaxis_transform(), ha="center",
            fontsize=11, fontweight="bold", color=COLORS[domain][0])
ax.set_xlim(0.4, 5.2)
every = [v for g in SCORES.values() for vs in g.values() for v in vs]
ax.set_ylim(max(0, min(every) - 0.08), min(1.05, max(every) + 0.08))   # zoom on the data
ax.set_ylabel("Held-out avg (20 samples)", color=INK)
ax.set_title("Held-out score before and after specialization (5 runs each)", color=INK)
ax.grid(axis="y", alpha=0.3, linestyle="--", linewidth=0.6)
for side in ("top", "right"):
    ax.spines[side].set_visible(False)

fig.tight_layout()
fig.savefig(OUT, dpi=200, bbox_inches="tight")
fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight")
print(f"Saved: {OUT} (+ .pdf)")
