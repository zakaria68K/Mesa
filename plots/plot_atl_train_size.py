"""
Plot the train-size experiment (experiments/atl_train_size.py) as a box plot: held-out score
after ONE skill rewrite from N randomly selected train samples. Everything is on the same
20 held-out samples.

Usage:
    python plots/plot_atl_train_size.py

Reads   outputs/atl/train_size/run_*/checkpoint_final.json   (N = 20, 40, 60 and 80 runs)
Writes  outputs/atl/figures/train_size.png / .pdf

For each N: one box (median, quartiles, whiskers = min/max), one dot per run, and the mean
(white diamond, value written above).
"""
import json
import os
import random
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Run from the repo root, whatever the current directory is
os.chdir(Path(__file__).resolve().parents[1])
FIG_DIR = Path("outputs/atl/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

RUNS_DIR = Path("outputs/atl/train_size")
OUT      = FIG_DIR / "train_size.png"

BLUE, LIGHT, INK = "#2166ac", "#c6dbef", "#333333"


def load_scores() -> tuple[dict[int, list[float]], dict[int, float]]:
    """Return ({N: [held-out avg of each run]}, {N: mean number of errors used})."""
    scores: dict[int, list[float]] = {}
    errors: dict[int, list[int]] = {}

    # N = 20, 40, 60, 80: one score per finished run
    for final in sorted(RUNS_DIR.glob("run_*/checkpoint_final.json")):
        for r in json.loads(final.read_text())["results"]:
            scores.setdefault(r["n"], []).append(r["test_avg"])
            errors.setdefault(r["n"], []).append(r["n_errors"])

    if not scores:
        raise FileNotFoundError("No results found")
    for n in sorted(scores):
        print(f"N={n:>2}: {len(scores[n])} run(s) -> {[round(s, 3) for s in scores[n]]}")
    return dict(sorted(scores.items())), {n: statistics.mean(e) for n, e in errors.items()}


def plot(scores: dict[int, list[float]], errors: dict[int, float]) -> None:
    ns = list(scores)
    fig, ax = plt.subplots(figsize=(8, 4.8))

    # Boxes: median, quartiles, whiskers = min/max (no outlier points, every run is drawn below)
    ax.boxplot([scores[n] for n in ns], positions=ns, widths=9, whis=(0, 100), showfliers=False,
               patch_artist=True, manage_ticks=False,
               boxprops=dict(facecolor=LIGHT, edgecolor=BLUE, linewidth=1.2),
               medianprops=dict(color=BLUE, linewidth=2),
               whiskerprops=dict(color=BLUE, linewidth=1.2), capprops=dict(color=BLUE, linewidth=1.2))

    # One dot per run (small horizontal jitter so equal scores stay visible)
    rng = random.Random(0)
    for i, n in enumerate(ns):
        xs = [n + rng.uniform(-2.5, 2.5) for _ in scores[n]]
        ax.scatter(xs, scores[n], s=22, color=BLUE, alpha=0.75, zorder=3,
                   label="One run" if i == 0 else None)

    # Mean of each N, connected
    means = [statistics.mean(scores[n]) for n in ns]
    ax.plot(ns, means, color=BLUE, linewidth=1.2, linestyle="--", zorder=2)
    ax.scatter(ns, means, marker="D", s=45, color="white", edgecolor=BLUE, linewidth=1.5, zorder=4,
               label="Mean")
    for n, m in zip(ns, means):
        top = max(scores[n])
        ax.annotate(f"{m:.2f}\n~{errors[n]:.0f} errors\n{len(scores[n])} runs", (n, top), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=8, color=INK)

    ax.set_xticks(ns)
    ax.set_xlim(min(ns) - 10, max(ns) + 10)
    every = [v for n in ns for v in scores[n]]
    ax.set_ylim(max(0, min(every) - 0.1), min(1.05, max(every) + 0.15))   # zoom on the data
    ax.set_xlabel("Number of train samples used for the single rewrite (N, random draw from the 80)",
                  color=INK)
    ax.set_ylabel("Held-out avg (20 samples)", color=INK)
    ax.set_title("ATL (model transformations): one skill rewrite from N train samples", color=INK)
    ax.grid(axis="y", alpha=0.3, linestyle="--", linewidth=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(fontsize=8, loc="lower right")

    fig.tight_layout()
    fig.savefig(OUT, dpi=200, bbox_inches="tight")
    fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight")
    print("Mean held-out: " + ", ".join(
        f"N={n}: {statistics.mean(scores[n]):.2f}"
        + (f" ± {statistics.stdev(scores[n]):.2f}" if len(scores[n]) > 1 else "") for n in ns))
    print(f"Saved: {OUT} (+ .pdf)")


if __name__ == "__main__":
    plot(*load_scores())
