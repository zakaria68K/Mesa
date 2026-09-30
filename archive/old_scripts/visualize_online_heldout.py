"""
Plot the ATL online specialization evaluated on the held-out set (online_heldout.py).

Usage:
    python visualize_online_heldout.py              # latest run in debug_logs/
    python visualize_online_heldout.py 20260930_011825

Reads   debug_logs/<run_id>_oh_steps.json   (step 0 + one entry per skill rewrite)
        debug_logs/<run_id>_oh_items.csv    (one row per train sample, optional)
Writes  debug_logs/fig_atl_online_heldout.png / .pdf

What the figure shows (x = train sample, in the online order):
  - blue step curve : held-out avg (20 samples) of the skill in use;
                      it only changes when the skill is rewritten
  - red dotted lines: skill rewrites
  - grey dashed line: cumulative train avg (the old "prequential" measure)
  - dash-dot line   : held-out avg of the initial megamodel skill
"""
import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LOG_DIR = Path("debug_logs")
OUT     = LOG_DIR / "fig_atl_online_heldout.png"
N_TRAIN = 80

BLUE, RED, GREY, INK = "#2166ac", "#de2d26", "#8a8a8a", "#333333"


def load_run(run_id: str | None):
    """Return (run_id, steps, items). items is None if the items CSV is missing."""
    if run_id is None:
        run_id = sorted(LOG_DIR.glob("*_oh_steps.json"))[-1].name.split("_oh_")[0]
    steps = json.loads((LOG_DIR / f"{run_id}_oh_steps.json").read_text())
    items_file = LOG_DIR / f"{run_id}_oh_items.csv"
    items = list(csv.DictReader(items_file.open(encoding="utf-8"))) if items_file.exists() else None
    return run_id, steps, items


def plot(run_id: str, steps: list[dict], items: list[dict] | None) -> None:
    initial = steps[0]["test_avg"]
    final = steps[-1]["test_avg"]
    best = max(steps, key=lambda s: s["test_avg"])

    # Held-out curve: each step holds its value until the next rewrite, then until the last sample
    xs = [s["after_pos"] for s in steps] + [N_TRAIN]
    ys = [s["test_avg"] for s in steps] + [final]

    fig, ax = plt.subplots(figsize=(9, 4.5))

    # Skill rewrites
    for i, s in enumerate(steps[1:]):
        ax.axvline(s["after_pos"], color=RED, linestyle=":", linewidth=0.9, alpha=0.7,
                   label="Skill rewritten" if i == 0 else None)

    # Old measure: cumulative train avg (only if the per-sample CSV is available)
    if items:
        scores = [float(it["score"]) for it in items]
        cum = [sum(scores[:i]) / i for i in range(1, len(scores) + 1)]
        ax.plot(range(1, len(cum) + 1), cum, color=GREY, linestyle="--", linewidth=1.2,
                label=f"Cumulative avg (train) = {cum[-1]:.2f}")

    # Held-out avg of the current skill
    ax.step(xs, ys, where="post", color=BLUE, linewidth=2.2,
            label=f"Held-out avg (20 samples): final = {final:.2f}")
    ax.plot(xs[:-1], ys[:-1], "o", color=BLUE, markersize=4.5,
            markeredgecolor="white", markeredgewidth=1)
    ax.axhline(initial, color=BLUE, linestyle="-.", linewidth=0.9, alpha=0.6,
               label=f"Initial skill (held-out) = {initial:.2f}")

    # Best step
    ax.annotate(f"best {best['test_avg']:.2f}", (best["after_pos"], best["test_avg"]),
                textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color=INK)

    ax.set_xlim(0, N_TRAIN + 1)
    ax.set_ylim(0, 1.05)
    ax.set_xticks(range(0, N_TRAIN + 1, 10))
    ax.set_xlabel("Training sample index (online order)", color=INK)
    ax.set_ylabel("Score", color=INK)
    ax.set_title("ATL (model transformations): online specialization, held-out evaluation", color=INK)
    ax.grid(alpha=0.3, linestyle="--", linewidth=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(fontsize=8, loc="lower left")

    fig.tight_layout()
    fig.savefig(OUT, dpi=200, bbox_inches="tight")
    fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight")
    print(f"Run {run_id}: {len(steps) - 1} rewrites, held-out {initial:.2f} -> {final:.2f} "
          f"(best {best['test_avg']:.2f} after sample {best['after_pos']})")
    print(f"Saved: {OUT} (+ .pdf)")


if __name__ == "__main__":
    plot(*load_run(sys.argv[1] if len(sys.argv) > 1 else None))
