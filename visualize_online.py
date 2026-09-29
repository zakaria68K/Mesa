import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import re
from pathlib import Path
from matplotlib.lines import Line2D


def find_latest_log(pattern: str) -> Path:
    logs = list(Path("debug_logs").glob(pattern))
    if not logs:
        raise FileNotFoundError(f"No file matching '{pattern}' found in debug_logs/")
    return sorted(logs)[-1]


def parse_online_log(filepath: Path):
    scores = []
    rewrites = []
    for line in filepath.read_text().splitlines():
        m = re.search(r'sample=(\d+)/\d+ \| score=(\d+\.\d+)', line)
        if m and '(restored)' not in line:
            scores.append((int(m.group(1)), float(m.group(2))))
        if '→ skill rewritten after sample' in line:
            m2 = re.search(r'sample (\d+)', line)
            if m2:
                rewrites.append(int(m2.group(1)))
    return scores, rewrites


def parse_test_score(filepath: Path) -> float:
    for line in reversed(filepath.read_text().splitlines()):
        m = re.search(r'avg_score=(\d+\.\d+)', line)
        if m:
            return float(m.group(1))
    return None


# ── Load files ────────────────────────────────────────────────────────────────
online_log = find_latest_log("*emf_online_specialization.txt")
test_log   = find_latest_log("*emf_test.txt")

print(f"Online log : {online_log}")
print(f"Test log   : {test_log}")

scores, rewrites = parse_online_log(online_log)
test_avg = parse_test_score(test_log)

xs = [s[0] for s in scores]
ys = [s[1] for s in scores]
cum_avg = [sum(ys[:i+1]) / (i+1) for i in range(len(ys))]
final_avg = sum(ys) / len(ys)

print(f"Samples    : {len(xs)}")
print(f"Rewrites   : {len(rewrites)}")
print(f"Train avg  : {final_avg:.2f}")
print(f"Test avg   : {test_avg:.2f}")

# ── Plot ──────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 6))

colors = ['#d73027' if y < 1.0 else '#4393c3' for y in ys]
ax.scatter(xs, ys, c=colors, s=50, zorder=4, alpha=0.7)

ax.plot(xs, cum_avg, color='#08306b', linewidth=2.5, zorder=5)

for rw in rewrites:
    ax.axvline(x=rw, color='#d73027', linewidth=0.7, alpha=0.4, linestyle='--')

ax.axhline(y=final_avg, color='#08306b', linewidth=1.2, linestyle=':', alpha=0.7)

if test_avg is not None:
    ax.axhline(y=test_avg, color='#2ca25f', linewidth=1.8, linestyle='-.', alpha=0.9)

legend_elements = [
    Line2D([0], [0], marker='o', color='w', markerfacecolor='#4393c3',
           markersize=8, label='Sample score = 1.0'),
    Line2D([0], [0], marker='o', color='w', markerfacecolor='#d73027',
           markersize=8, label='Sample score < 1.0'),
    Line2D([0], [0], color='#08306b', linewidth=2.5, label='Cumulative avg (train)'),
    Line2D([0], [0], color='#08306b', linewidth=1.2, linestyle=':',
           label=f'Final train avg = {final_avg:.2f}'),
    Line2D([0], [0], color='#d73027', linewidth=0.7, linestyle='--',
           alpha=0.6, label='Skill rewritten'),
]
if test_avg is not None:
    legend_elements.append(
        Line2D([0], [0], color='#2ca25f', linewidth=1.8, linestyle='-.',
               label=f'Test score (held-out) = {test_avg:.2f}')
    )

ax.legend(handles=legend_elements, fontsize=11, loc='lower left')
ax.set_xlim(0.5, len(xs) + 0.5)
ax.set_ylim(-0.05, 1.1)
ax.set_xlabel("Training sample index", fontsize=13)
ax.set_ylabel("Score", fontsize=13)
ax.tick_params(axis='both', labelsize=11)

ax.grid(alpha=0.3, linestyle='--')
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

plt.tight_layout()

out = Path("debug_logs/fig_emf_online_specialization.png")
plt.savefig(out, dpi=200, bbox_inches="tight")
plt.savefig(str(out).replace('.png', '.pdf'), bbox_inches="tight")
print(f"Saved: {out}")