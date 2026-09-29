"""
EMF — batch specialization (5 runs, 8 iterations) on a training-items axis,
with a zoom on items 0–80 showing the error-batch specialization (batches of 4).

Batch runs    : results/run_*/<id>_emf_specialization.txt   (iteration k -> k * 80 items)
Error batches : debug_logs/<run_id>_emf_b4_results.json       (batch b -> train index of its last error)

Output: debug_logs/fig_emf_batch_vs_error_batches.png / .pdf
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

BLUE_RUNS = ["#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#c6dbef"]
BLUE_MEAN = "#2c5a9e"
ORANGE    = "#d95f02"
INK       = "#333333"
MUTED     = "#8a8a8a"


def parse_batch_log(path: Path) -> dict[int, float]:
    iters = {}
    for line in path.read_text().splitlines():
        m = re.search(r"Iteration (\d+) summary \| avg_score=(\d+\.\d+)", line)
        if m:
            iters[int(m.group(1))] = float(m.group(2))
    return iters


def load_batch_runs() -> list[dict[int, float]]:
    logs = sorted(p for p in Path("results").glob("run_*/*emf_specialization*.txt")
                  if "online" not in p.name)
    runs = [r for r in (parse_batch_log(p) for p in logs) if r]
    print(f"Batch runs: {len(runs)} ({', '.join(str(p) for p in logs)})")
    return runs


def load_error_batches() -> list[dict] | None:
    files = sorted(Path("debug_logs").glob("*_emf_b4_results.json"))
    if files:
        print(f"Error batches: {files[-1]}")
        return json.loads(files[-1].read_text())
    print("Error batches: no debug_logs/*_emf_b4_results.json yet — plotting the batch runs only")
    return None


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

fig, ax = plt.subplots(figsize=(11, 5))

for i, r in enumerate(runs):
    ks = sorted(r)
    ax.plot([k * N_TRAIN for k in ks], [r[k] for k in ks],
            color=BLUE_RUNS[i % len(BLUE_RUNS)], linewidth=1.0, alpha=0.8, label=f"Run {i + 1}")
ax.fill_between(bx, mean - std, mean + std, color=BLUE_MEAN, alpha=0.15, linewidth=0, label="±1 std")
ax.plot(bx, mean, color=BLUE_MEAN, linewidth=2.5, marker="o", markersize=5, label="Batch mean (train set)",
        zorder=4)

# ── Error batches: batch b -> train index of its last error ──────────────────
if steps:
    ex = np.array([max(s["train_indexes"]) if s["train_indexes"] else 0 for s in steps])
    ey = np.array([s["test_avg"] for s in steps])
    ax.plot(ex, ey, color=ORANGE, linewidth=2, marker="o", markersize=4, zorder=5,
            label="Error batches of 4 (held-out test)")

ax.set_xlim(-10, bx[-1] + 20)
ax.set_xticks(bx)
ax.set_ylim(0, 1.05)
ax.set_xlabel("Training items processed", fontsize=11, color=INK)
ax.set_ylabel("Avg score", fontsize=11, color=INK)
ax.set_title("EMF (metamodel editing) — batch iterations vs. error batches", fontsize=12, color=INK)
style(ax)

# ── Zoom on items 0–80 ───────────────────────────────────────────────────────
axin = ax.inset_axes([0.36, 0.14, 0.61, 0.38])
axin.set_xlim(-3, N_TRAIN + 3)
axin.set_xticks(range(0, N_TRAIN + 1, 10))
axin.set_xlabel("Training item index (last error in the batch)", fontsize=8, color=INK)
axin.set_ylabel("Held-out avg", fontsize=8, color=INK)
axin.set_facecolor("white")
style(axin)
axin.tick_params(labelsize=8)
if steps:
    for x in ex[1:]:
        axin.axvline(x, color=MUTED, linestyle=":", linewidth=0.8, zorder=1)
    axin.plot(ex, ey, color=ORANGE, linewidth=2, marker="o", markersize=7, zorder=5,
              markeredgecolor="white", markeredgewidth=1.5)
    for s, x, y in zip(steps, ex, ey):
        label = "init" if s["step"] == 0 else f"B{s['step']}"
        axin.annotate(label, (x, y), textcoords="offset points", xytext=(0, 9),
                      ha="center", fontsize=8, color=INK)
    lo, hi = ey.min(), ey.max()
    axin.set_ylim(max(0, lo - 0.06), min(1.05, hi + 0.07))
    zoom_lo, zoom_hi = axin.get_ylim()
else:
    axin.set_ylim(0.8, 1.0)
    axin.text(0.5, 0.5, "No error-batch results yet\n(run error_by_error.py)", transform=axin.transAxes,
              ha="center", va="center", fontsize=9, color=MUTED)
ax.indicate_inset_zoom(axin, edgecolor=MUTED, alpha=0.8)

ax.legend(fontsize=8, loc="lower left", ncol=2, frameon=False)

plt.tight_layout()
out = Path("debug_logs/fig_emf_batch_vs_error_batches.png")
out.parent.mkdir(exist_ok=True)
plt.savefig(out, dpi=200, bbox_inches="tight")
plt.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
print(f"Saved: {out} (+ .pdf)")
