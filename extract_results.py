import re
import statistics
from pathlib import Path

RESULTS_DIR = Path("results")

ATL_FILES = [
    ("run_1", "20260914_114647_baseline.txt",    "20260914_114647_test.txt"),
    ("run_2", "20260916_140543_baseline.txt",    "20260916_140543_test.txt"),
    ("run_3", "20260918_093957_baseline.txt",    "20260918_093957_test.txt"),
    ("run_4", "20260917_085836_baseline.txt",    "20260917_085836_test.txt"),
    ("run_5", "20260918_205407_baseline.txt",    "20260918_205407_test.txt"),
]

EMF_FILES = [
    ("run_1", "20260915_152432_emf_baseline.txt", "20260915_152432_emf_test.txt"),
    ("run_2", "20260916_140549_emf_baseline.txt", "20260916_140549_emf_test.txt"),
    ("run_3", "20260916_225758_emf_baseline.txt", "20260916_225758_emf_test.txt"),
    ("run_4", "20260917_081030_emf_baseline.txt", "20260917_081030_emf_test.txt"),
    ("run_5", "20260917_161844_emf_baseline.txt", "20260917_161844_emf_test.txt"),
]


def parse_avg(filepath: Path) -> float:
    scores = []
    for line in filepath.read_text().splitlines():
        m = re.search(r'\| score=(\d+\.\d+)', line)
        if m:
            scores.append(float(m.group(1)))
    return round(sum(scores) / len(scores), 2) if scores else None


def print_table(agent, files):
    baselines, tests = [], []
    print(f"\n{'='*55}")
    print(f"  {agent}")
    print(f"{'='*55}")
    print(f"{'Run':<6} {'No Skill':>10} {'Specialized':>13} {'Delta':>8}")
    print("-" * 40)

    for i, (run, bf, tf) in enumerate(files):
        b = parse_avg(RESULTS_DIR / run / bf)
        t = parse_avg(RESULTS_DIR / run / tf)
        if b is None or t is None:
            print(f"R{i+1:<5} {'MISSING':>10}")
            continue
        delta = round(t - b, 2)
        sign = "+" if delta >= 0 else ""
        print(f"R{i+1:<5} {b:>10.2f} {t:>13.2f} {sign+str(delta):>8}")
        baselines.append(b)
        tests.append(t)

    if len(baselines) > 1:
        b_mean = statistics.mean(baselines)
        b_std  = statistics.stdev(baselines)
        t_mean = statistics.mean(tests)
        t_std  = statistics.stdev(tests)
        delta  = round(t_mean - b_mean, 2)
        sign   = "+" if delta >= 0 else ""
        print("-" * 40)
        print(f"{'Mean':<6} {f'{b_mean:.2f}±{b_std:.2f}':>10} {f'{t_mean:.2f}±{t_std:.2f}':>13} {sign+str(delta):>8}")


print_table("ATL", ATL_FILES)
print_table("EMF", EMF_FILES)