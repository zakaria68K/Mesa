"""
ATL :batch specialization (5 runs, 8 iterations) on a training-items axis,
with a zoom on items 0–80 showing the error-batch specialization (batches of 4).

Batch runs    : results/run_*/<id>_specialization.txt   (iteration k -> k * 80 items)
Error batches : debug_logs/<run_id>_b4_results.json       (batch b -> train index of its last error)

Output: debug_logs/fig_atl_batch_vs_error_batches.png / .pdf
"""
import json
import re
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

N_TRAIN = 80

# Fallback = numbers from the 20260929_153035 run, used if the results file is missing
FALLBACK_STEPS = [
    {"step": 0, "train_indexes": [],               "test_avg": 0.675},
    {"step": 1, "train_indexes": [1, 5, 21, 31],   "test_avg": 0.70},
    {"step": 2, "train_indexes": [33, 36, 37, 39], "test_avg": 0.75},
    {"step": 3, "train_indexes": [40, 41, 42, 45], "test_avg": 0.72},
    {"step": 4, "train_indexes": [48, 50, 53, 56], "test_avg": 0.725},
    {"step": 5, "train_indexes": [57, 61, 62, 63], "test_avg": 0.725},
    {"step": 6, "train_indexes": [64, 66, 67, 68], "test_avg": 0.775},
    {"step": 7, "train_indexes": [69, 70, 71, 72], "test_avg": 0.725},
    {"step": 8, "train_indexes": [73, 74, 75, 76], "test_avg": 0.70},
    {"step": 9, "train_indexes": [77, 78, 79],     "test_avg": 0.725},
]

RED_RUNS = ["#fcae91", "#fb6a4a", "#de2d26", "#a50f15", "#fdd0bc"]
RED_MEAN = "#a50f15"
BLUE     = "#2166ac"
INK      = "#333333"
MUTED    = "#8a8a8a"


def parse_batch_log(path: Path) -> dict[int, float]:
    iters = {}
    for line in path.read_text().splitlines():
        m = re.search(r"Iteration (\d+) summary \| avg_score=(\d+\.\d+)", line)
        if m:
            iters[int(m.group(1))] = float(m.group(2))
    return iters


def load_batch_runs() -> list[dict[int, float]]:
    logs = sorted(p for p in Path("results").glob("run_*/*specialization*.txt")
                  if "emf" not in p.name and "online" not in p.name)
    runs = [r for r in (parse_batch_log(p) for p in logs) if r]
    print(f"Batch runs: {len(runs)} ({', '.join(str(p) for p in logs)})")
    return runs


def load_error_batches() -> list[dict]:
    files = sorted(Path("debug_logs").glob("*_b4_results.json"))
    if files:
        print(f"Error batches: {files[-1]}")
        return json.loads(files[-1].read_text())
    print("Error batches: results file not found ,using the 20260929_153035 numbers")
    return FALLBACK_STEPS


def style(ax):
    ax.grid(alpha=0.3, linestyle="--", linewidth=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors=INK, labelsize=9)


runs = load_batch_runs()
steps = load_error_batches()

# ── Batch curves: iteration k -> k * 80 training items ───────────────────────
iters = sorted({k for r in runs for k in r})
bx = np.array([k * N_TRAIN for k in iters])
mean = np.array([statistics.mean(r[k] for r in runs if k in r) for k in iters])
std = np.array([statistics.stdev([r[k] for r in runs if k in r]) if len(runs) > 1 else 0 for k in iters])

# ── Error batches: batch b -> train index of its last error ──────────────────
ex = np.array([max(s["train_indexes"]) if s["train_indexes"] else 0 for s in steps])
ey = np.array([s["test_avg"] for s in steps])

fig, ax = plt.subplots(figsize=(11, 5))

for i, r in enumerate(runs):
    ks = sorted(r)
    ax.plot([k * N_TRAIN for k in ks], [r[k] for k in ks],
            color=RED_RUNS[i % len(RED_RUNS)], linewidth=1.0, alpha=0.7, label=f"Run {i + 1}")
ax.fill_between(bx, mean - std, mean + std, color=RED_MEAN, alpha=0.15, linewidth=0, label="±1 std")
ax.plot(bx, mean, color=RED_MEAN, linewidth=2.5, marker="o", markersize=5, label="Batch mean (train set)",
        zorder=4)
ax.plot(ex, ey, color=BLUE, linewidth=2, marker="o", markersize=4, zorder=5,
        label="Error batches of 4 (held-out test)")

ax.set_xlim(-10, bx[-1] + 20)
ax.set_xticks(bx)
ax.set_ylim(0, 1.05)
ax.set_xlabel("Training items processed", fontsize=11, color=INK)
ax.set_ylabel("Avg score", fontsize=11, color=INK)
ax.set_title("ATL (model transformations): batch iterations vs. error batches", fontsize=12, color=INK)
style(ax)

# ── Zoom on items 0–80 ───────────────────────────────────────────────────────
axin = ax.inset_axes([0.36, 0.17, 0.61, 0.38])
for x in ex[1:]:
    axin.axvline(x, color=MUTED, linestyle=":", linewidth=0.8, zorder=1)
axin.plot(ex, ey, color=BLUE, linewidth=2, marker="o", markersize=7, zorder=5,
          markeredgecolor="white", markeredgewidth=1.5)
for s, x, y in zip(steps, ex, ey):
    label = "init" if s["step"] == 0 else f"B{s['step']}"
    axin.annotate(label, (x, y), textcoords="offset points", xytext=(0, 9),
                  ha="center", fontsize=8, color=INK)
axin.set_xlim(-3, N_TRAIN + 3)
axin.set_xticks(range(0, N_TRAIN + 1, 10))
lo, hi = ey.min(), ey.max()
axin.set_ylim(lo - 0.06, hi + 0.07)
axin.set_xlabel("Training item index (last error in the batch)", fontsize=8, color=INK)
axin.set_ylabel("Held-out avg", fontsize=8, color=INK)
axin.set_facecolor("white")
style(axin)
axin.tick_params(labelsize=8)
ax.indicate_inset_zoom(axin, edgecolor=MUTED, alpha=0.8)

ax.legend(fontsize=8, loc="upper left", ncol=2, frameon=False)

plt.tight_layout()
out = Path("debug_logs/fig_atl_batch_vs_error_batches.png")
out.parent.mkdir(exist_ok=True)
plt.savefig(out, dpi=200, bbox_inches="tight")
plt.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
print(f"Saved: {out} (+ .pdf)")
