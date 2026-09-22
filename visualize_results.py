import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import re
import statistics
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────
RESULTS_DIR = Path("results")  # folder containing run_1 ... run_5

ATL_SPEC_FILES = [
    "run_1/20260914_114647_specialization.txt",
    "run_2/20260916_140543_specialization.txt",
    "run_3/20260918_093957_specialization.txt",
    "run_4/20260917_085836_specialization.txt",
    "run_5/20260918_205407_specialization.txt",
]

EMF_SPEC_FILES = [
    "run_1/20260915_152432_emf_specialization.txt",
    "run_2/20260916_140549_emf_specialization.txt",
    "run_3/20260916_225758_emf_specialization.txt",
    "run_4/20260917_081030_emf_specialization.txt",
    "run_5/20260917_161844_emf_specialization.txt",
]

# ── Parsing ───────────────────────────────────────────────────────────────────
def parse_iterations(filepath: Path) -> dict:
    iters = {}
    for line in filepath.read_text().splitlines():
        m = re.search(r'Iteration (\d+) summary \| avg_score=(\d+\.\d+)', line)
        if m:
            iters[int(m.group(1))] = float(m.group(2))
    return iters

def load_all(files):
    data = []
    for f in files:
        path = RESULTS_DIR / f
        if not path.exists():
            print(f"  WARNING: {path} not found, skipping")
            continue
        iters = parse_iterations(path)
        if iters:
            data.append(iters)
    return data

atl_data = load_all(ATL_SPEC_FILES)
emf_data = load_all(EMF_SPEC_FILES)

# ── Colors ────────────────────────────────────────────────────────────────────
ATL_COLORS = ["#f4a582", "#d6604d", "#b2182b", "#7f0000", "#fddbc7"]
ATL_MEAN   = "#67001f"

EMF_COLORS = ["#92c5de", "#4393c3", "#2166ac", "#053061", "#d1e5f0"]
EMF_MEAN   = "#02254a"

# ── Plot ──────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

for ax, data, label, run_colors, mean_color in [
    (axes[0], atl_data, "ATL (model transformations)", ATL_COLORS, ATL_MEAN),
    (axes[1], emf_data, "EMF (metamodel editing)",     EMF_COLORS, EMF_MEAN),
]:
    n_iters = max(max(d.keys()) for d in data) + 1

    # Individual run lines
    for idx, d in enumerate(data):
        xs = sorted(d.keys())
        ys = [d[i] for i in xs]
        ax.plot(xs, ys,
                color=run_colors[idx % len(run_colors)],
                linewidth=1.2,
                alpha=0.7,
                label=f"Run {idx+1}")

    # Mean ± std band
    means, stds = [], []
    valid_xs = []
    for i in range(n_iters):
        vals = [d[i] for d in data if i in d]
        if vals:
            means.append(statistics.mean(vals))
            stds.append(statistics.stdev(vals) if len(vals) > 1 else 0)
            valid_xs.append(i)

    means = np.array(means)
    stds  = np.array(stds)
    xs    = np.array(valid_xs)

    ax.plot(xs, means,
            color=mean_color,
            linewidth=2.5,
            label="Mean",
            zorder=5)
    ax.fill_between(xs,
                    means - stds,
                    means + stds,
                    alpha=0.15,
                    color=mean_color,
                    label="±1 std",
                    zorder=4)

    ax.set_xticks(xs)
    ax.set_xticklabels([str(i) for i in xs])
    ax.set_xlim(-0.3, n_iters - 0.7)
    ax.set_ylim(0.0, 1.05)
    ax.set_xlabel("Specialization iteration", fontsize=11)
    ax.set_ylabel("Avg score (train set)", fontsize=11)
    ax.set_title(label, fontsize=12)
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(alpha=0.35, linestyle="--")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

fig.suptitle("Score evolution across specialization iterations (5 runs each)",
             fontsize=13, y=1.01)
plt.tight_layout()

out = Path("debug_logs/fig_specialization_curve.png")
out.parent.mkdir(exist_ok=True)
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved: {out}")

out_pdf = Path("debug_logs/fig_specialization_curve.pdf")
plt.savefig(out_pdf, bbox_inches="tight")
print(f"Saved: {out_pdf}")