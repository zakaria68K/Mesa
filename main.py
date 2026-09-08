import asyncio
import json
import random
import statistics
from dotenv import load_dotenv
load_dotenv()
from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from modeling_agents.meta_agent import MetaAgent
import sys
sys.path.insert(0, '.opencode/skills')
from megamodel_toskill import MegamodelToSkill


def load_specialization_dataset(dataset_path: str) -> list[dict]:
    with open(dataset_path, "r") as f:
        raw_dataset = json.load(f)

    if isinstance(raw_dataset, dict):
        dataset_sections = raw_dataset.values()
    elif isinstance(raw_dataset, list):
        dataset_sections = [raw_dataset]
    else:
        raise TypeError(f"Unsupported dataset format: {type(raw_dataset).__name__}")

    samples: list[dict] = []
    for section in dataset_sections:
        if not isinstance(section, list):
            continue
        for sample in section:
            if not isinstance(sample, dict):
                continue
            if "instruction" not in sample or "relevant_apis" not in sample:
                continue
            samples.append(sample)

    return samples


async def main():
    N_RUNS       = 4
    MAX_ITER     = 8
    DATASET_PATH = "/Users/anonymoushachm/Documents/Phd_anonymous/MESA/datasets/testing_datatset.json"

    print("MESA Megamodel Instance Initialization")
    registry = MegamodelRegistry()
    await populate_registry(registry)

    full_dataset = load_specialization_dataset(DATASET_PATH)
    print(f"Loaded {len(full_dataset)} samples.")

    random.seed(42)
    random.shuffle(full_dataset)
    train_dataset = full_dataset[:40]
    test_dataset  = full_dataset[40:50]
    print(f"Train: {len(train_dataset)} | Test (held-out): {len(test_dataset)}")

    all_baseline_scores = []
    all_test_scores     = []

    for run_id in range(N_RUNS):
        print(f"\n{'='*50}\nRUN {run_id + 1}/{N_RUNS}\n{'='*50}")

        spec_log      = f"debug_logs/run{run_id + 1}_specialization.txt"
        baseline_log  = f"debug_logs/run{run_id + 1}_baseline.txt"
        test_log      = f"debug_logs/run{run_id + 1}_test.txt"

        # Reset skill files to initial state
        skill_generator = MegamodelToSkill(registry)
        skill_generator.generate_patterns()

        meta = MetaAgent()

        # --- Baseline (no skill, on held-out test set) ---
        print(f"\n[Run {run_id + 1}] Evaluating no-skill baseline...")
        baseline = meta.evaluate_no_skill_baseline(test_dataset, baseline_log)
        all_baseline_scores.append(baseline)

        # --- Specialization loop (train set, no threshold, fixed iterations) ---
        print(f"\n[Run {run_id + 1}] Starting specialization ({MAX_ITER} iterations)...")
        meta.specialize_agent(
            train_dataset,
            threshold=2.0,       # unreachable — loop always runs to max_iterations
            max_iterations=MAX_ITER,
            log_file=spec_log,
        )

        # --- Final evaluation on held-out test set ---
        print(f"\n[Run {run_id + 1}] Evaluating on held-out test set...")
        test_score = meta.evaluate_on_test_set(test_dataset, test_log)
        all_test_scores.append(test_score)

    # --- Summary ---
    summary_path = "debug_logs/summary.txt"
    from pathlib import Path
    Path("debug_logs").mkdir(exist_ok=True)

    lines = [
        "=" * 50,
        "RESULTS SUMMARY",
        "=" * 50,
        f"Runs        : {N_RUNS}",
        f"Iterations  : {MAX_ITER}",
        f"Train size  : {len(train_dataset)}",
        f"Test size   : {len(test_dataset)}",
        "",
        f"Baseline (no skill)",
        f"  scores : {[round(s, 2) for s in all_baseline_scores]}",
        f"  mean   : {statistics.mean(all_baseline_scores):.2f}",
        f"  std    : {statistics.stdev(all_baseline_scores):.2f}",
        "",
        f"After specialization (held-out test)",
        f"  scores : {[round(s, 2) for s in all_test_scores]}",
        f"  mean   : {statistics.mean(all_test_scores):.2f}",
        f"  std    : {statistics.stdev(all_test_scores):.2f}",
        "=" * 50,
    ]

    summary_text = "\n".join(lines)
    print(f"\n{summary_text}")
    Path(summary_path).write_text(summary_text)
    print(f"\n>>> Summary saved to {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())