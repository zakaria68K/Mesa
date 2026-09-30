import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import os
import re
from pathlib import Path

# Run from the repo root, whatever the current directory is
os.chdir(Path(__file__).resolve().parents[1])
FIG_DIR = Path("outputs/atl/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Parse the online specialization log ──────────────────────────────────────
def find_online_log():
    """Find the most recent online specialization log."""
    logs = list(Path("outputs/atl/online_train").glob("run_*/log.txt"))
    if not logs:
        raise FileNotFoundError("No online specialization log found in outputs/atl/online_train/")
    return sorted(logs)[-1]

def parse_online_log(filepath):
    scores = []
    rewrites = []
    for line in Path(filepath).read_text().splitlines():
        m = re.search(r'sample=(\d+)/(\d+) \| score=(\d+\.\d+)', line)
        if m:
            idx = int(m.group(1))
            score = float(m.group(3))
            scores.append((idx, score))
        if '→ skill rewritten after sample' in line:
            m2 = re.search(r'sample (\d+)', line)
            if m2:
                rewrites.append(int(m2.group(1)))
    return scores, rewrites

# ── Find log ─────────────────────────────────────────────────────────────────
try:
    log_path = find_online_log()
except FileNotFoundError:
    # fallback: parse from hardcoded data in the script
    log_path = None

if log_path:
    print(f"Using log: {log_path}")
    scores, rewrites = parse_online_log(log_path)
else:
    # Hardcoded from the pasted log
    raw = """1 0.00 2 1.00 3 1.00 4 1.00 5 0.50 6 1.00 7 1.00 8 1.00 9 1.00 10 1.00
11 0.50 12 1.00 13 0.50 14 1.00 15 1.00 16 1.00 17 1.00 18 1.00 19 1.00 20 1.00
21 0.50 22 1.00 23 1.00 24 1.00 25 1.00 26 1.00 27 0.50 28 1.00 29 1.00 30 1.00
31 0.50 32 1.00 33 0.00 34 1.00 35 1.00 36 1.00 37 1.00 38 1.00 39 0.00 40 0.50
41 1.00 42 1.00 43 1.00 44 1.00 45 0.50 46 1.00 47 1.00 48 1.00 49 1.00 50 1.00
51 1.00 52 1.00 53 1.00 54 1.00 55 1.00 56 0.50 57 1.00 58 1.00 59 1.00 60 1.00
61 0.00 62 0.50 63 0.00 64 0.50 65 0.00 66 0.00 67 1.00 68 0.50 69 0.00 70 0.00
71 1.00 72 0.00 73 0.50 74 0.00 75 1.00 76 0.50 77 0.50 78 0.50 79 0.50 80 1.00"""
    vals = raw.split()
    scores = [(int(vals[i]), float(vals[i+1])) for i in range(0, len(vals), 2)]
    rewrites = [1, 5, 11, 13, 21, 27, 31, 33, 39, 40, 45, 56, 61, 62, 63, 64, 65, 66, 68, 69, 70, 72, 73, 74, 76, 77, 78, 79]

xs = [s[0] for s in scores]
ys = [s[1] for s in scores]

# Cumulative average
cum_avg = [sum(ys[:i+1]) / (i+1) for i in range(len(ys))]

# ── Plot ─────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 5))

# Individual sample scores as dots
colors = ['#d73027' if y < 1.0 else '#4393c3' for y in ys]
ax.scatter(xs, ys, c=colors, s=30, zorder=4, alpha=0.7, label="Sample score")

# Cumulative average line
ax.plot(xs, cum_avg, color='#08306b', linewidth=2.5, zorder=5, label="Cumulative avg")

# Mark skill rewrites as vertical lines
for rw in rewrites:
    ax.axvline(x=rw, color='#d73027', linewidth=0.7, alpha=0.4, linestyle='--')

# Final avg line
final_avg = sum(ys) / len(ys)
ax.axhline(y=final_avg, color='#08306b', linewidth=1.2, linestyle=':', alpha=0.6,
           label=f"Final avg = {final_avg:.2f}")

# Test score
TEST_AVG = 0.85
ax.axhline(y=TEST_AVG, color='#2ca25f', linewidth=1.5, linestyle='-.', alpha=0.9,
           label=f"Test score (held-out) = {TEST_AVG:.2f}")

# Dummy for legend
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0], [0], marker='o', color='w', markerfacecolor='#4393c3', markersize=8, label='Sample score = 1.0'),
    Line2D([0], [0], marker='o', color='w', markerfacecolor='#d73027', markersize=8, label='Sample score < 1.0'),
    Line2D([0], [0], color='#08306b', linewidth=2.5, label=f'Cumulative avg'),
    Line2D([0], [0], color='#08306b', linewidth=1.2, linestyle=':', label=f'Final avg = {final_avg:.2f}'),
    Line2D([0], [0], color='#d73027', linewidth=0.7, linestyle='--', alpha=0.6, label='Skill rewritten'),
    Line2D([0], [0], color='#2ca25f', linewidth=1.5, linestyle='-.', label=f'Test score = {TEST_AVG:.2f}'),
]
ax.legend(handles=legend_elements, fontsize=9, loc='lower left')

ax.set_xlim(0.5, len(xs) + 0.5)
ax.set_ylim(-0.05, 1.1)
ax.set_xlabel("Training sample index", fontsize=11)
ax.set_ylabel("Score", fontsize=11)
ax.set_title("ATL — Online specialization: per-sample score and cumulative average (1 pass, 80 samples)", fontsize=12)
ax.grid(alpha=0.3, linestyle='--')
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

plt.tight_layout()

out = FIG_DIR / "online_train.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
plt.savefig(str(out).replace('.png', '.pdf'), bbox_inches="tight")
print(f"Saved: {out}")
