import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import re
import statistics
import numpy as np
import os
from pathlib import Path

# Run from the repo root, whatever the current directory is
os.chdir(Path(__file__).resolve().parents[1])
FIG_DIR = Path("outputs/atl/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)


def find_latest_log(pattern: str) -> Path:
    logs = list(Path("outputs/atl/online_train").glob(pattern))
    if not logs:
        raise FileNotFoundError(f"No file matching '{pattern}' found in outputs/atl/online_train/")
    return sorted(logs)[-1]


def parse_online_log(filepath: Path):
    scores = []
    for line in filepath.read_text().splitlines():
        m = re.search(r'sample=(\d+)/\d+ \| score=(\d+\.\d+)', line)
        if m and '(restored)' not in line:
            scores.append(float(m.group(2)))
    return scores


def parse_batch_log(filepath: Path) -> dict:
    iters = {}
    for line in filepath.read_text().splitlines():
        m = re.search(r'Iteration (\d+) summary \| avg_score=(\d+\.\d+)', line)
        if m:
            iters[int(m.group(1))] = float(m.group(2))
    return iters


def find_all_atl_batch_logs() -> list[Path]:
    # New naming convention in results/run_*/
    logs = [p for p in Path("results").rglob("*specialization*.txt")
            if "emf" not in p.name and "online" not in p.name]
    if logs:
        return sorted(logs)
    # Fallback: old naming, now archived
    logs = [p for p in Path("archive/debug_logs").glob("specialization_iterations*.txt")
            if "emf" not in p.name]
    if logs:
        return sorted(logs)
    raise FileNotFoundError("No batch ATL specialization log found")


# ── Load online log ───────────────────────────────────────────────────────────
online_log    = find_latest_log("run_*/log.txt")
online_scores = parse_online_log(online_log)
print(f"Online log : {online_log} ({len(online_scores)} samples)")

# ── Load all ATL batch logs ───────────────────────────────────────────────────
atl_spec_files = find_all_atl_batch_logs()
print(f"Found {len(atl_spec_files)} ATL batch logs:")
for f in atl_spec_files:
    print(f"  {f}")

all_batch = [parse_batch_log(f) for f in atl_spec_files]
all_batch = [b for b in all_batch if b]

if not online_scores:
    raise ValueError("No scores found in online log")
if not all_batch:
    raise ValueError("No batch iterations found")

# ── Prepare curves ────────────────────────────────────────────────────────────
n_samples = len(online_scores)
online_x  = list(range(1, n_samples + 1))
online_y  = [sum(online_scores[:i+1]) / (i+1) for i in range(n_samples)]

batch_runs_x, batch_runs_y = [], []
for b in all_batch:
    xs = [max(1, i * n_samples) for i in sorted(b.keys())]
    ys = [b[i] for i in sorted(b.keys())]
    batch_runs_x.append(xs)
    batch_runs_y.append(ys)

all_iter_keys = sorted(set(k for b in all_batch for k in b.keys()))
batch_mean_x  = [max(1, i * n_samples) for i in all_iter_keys]
batch_mean_y, batch_std_y = [], []
for i in all_iter_keys:
    vals = [b[i] for b in all_batch if i in b]
    batch_mean_y.append(statistics.mean(vals))
    batch_std_y.append(statistics.stdev(vals) if len(vals) > 1 else 0)

batch_mean_y = np.array(batch_mean_y)
batch_std_y  = np.array(batch_std_y)

print(f"Online : final avg = {online_y[-1]:.3f}")
print(f"Batch  : {len(all_batch)} runs, {len(all_iter_keys)} iters, mean final = {batch_mean_y[-1]:.3f}")

# ── Plot ──────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(11, 5))

batch_colors = ['#fcae91', '#fb6a4a', '#de2d26', '#a50f15', '#fee5d9']
for idx, (xs, ys) in enumerate(zip(batch_runs_x, batch_runs_y)):
    ax.plot(xs, ys,
            color=batch_colors[idx % len(batch_colors)],
            linewidth=1.0, alpha=0.6,
            label=f'Batch run {idx+1}')

ax.plot(batch_mean_x, batch_mean_y,
        color='#a50f15', linewidth=2.5,
        marker='o', markersize=5,
        label='Batch mean', zorder=5)
ax.fill_between(batch_mean_x,
                batch_mean_y - batch_std_y,
                batch_mean_y + batch_std_y,
                alpha=0.15, color='#a50f15',
                label='Batch ±1 std')

ax.plot(online_x, online_y,
        color='#2166ac', linewidth=2.5,
        label='Online (sample-by-sample)', zorder=5)

ax.set_xscale('log')
max_calls = max(batch_mean_x)
ticks = [t for t in [1, 5, 10, 20, 40, 80, 160, 320, 640, 720]
         if t <= max_calls * 1.2]
ax.set_xticks(ticks)
ax.set_xlim(1, max_calls * 1.2)
ax.get_xaxis().set_major_formatter(plt.ScalarFormatter())

ax.set_ylim(0, 1.05)
ax.set_xlabel("Total agent calls (log scale)", fontsize=11)
ax.set_ylabel("Avg score (train set)", fontsize=11)
ax.set_title("ATL — Online vs Batch specialization (log scale)", fontsize=12)
ax.legend(fontsize=8, loc='lower right')
ax.grid(alpha=0.3, linestyle='--', which='both')
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

plt.tight_layout()

out = FIG_DIR / "online_train_vs_batch.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
plt.savefig(str(out).replace('.png', '.pdf'), bbox_inches="tight")
print(f"Saved: {out}")
