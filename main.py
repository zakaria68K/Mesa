import asyncio
import json
import random
import statistics
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from modeling_agents.meta_agent import MetaAgent
import sys
sys.path.insert(0, '.opencode/skills')
from megamodel_toskill import MegamodelToSkill


DATASET_PATH = "datasets/testing_datatset.json"
N_RUNS       = 4
MAX_ITER     = 8
STATE_FILE   = "debug_logs/run_state.json"


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


def load_state() -> dict:
    """Load incremental state from disk if it exists."""
    if Path(STATE_FILE).exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"completed_runs": [], "all_baseline_scores": [], "all_test_scores": []}


def save_state(state: dict) -> None:
    """Save incremental state to disk after every run."""
    Path("debug_logs").mkdir(exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def save_summary(state: dict, train_size: int, test_size: int) -> None:
    completed = len(state["all_baseline_scores"])
    baseline_scores = state["all_baseline_scores"]
    test_scores     = state["all_test_scores"]

    lines = [
        "=" * 50,
        "RESULTS SUMMARY (incremental)",
        "=" * 50,
        f"Runs completed : {completed}/{N_RUNS}",
        f"Iterations     : {MAX_ITER}",
        f"Train size     : {train_size}",
        f"Test size      : {test_size}",
        "",
        "Baseline (no skill)",
        f"  scores : {[round(s, 2) for s in baseline_scores]}",
    ]
    if len(baseline_scores) > 1:
        lines += [
            f"  mean   : {statistics.mean(baseline_scores):.2f}",
            f"  std    : {statistics.stdev(baseline_scores):.2f}",
        ]
    lines += [
        "",
        "After specialization (held-out test)",
        f"  scores : {[round(s, 2) for s in test_scores]}",
    ]
    if len(test_scores) > 1:
        lines += [
            f"  mean   : {statistics.mean(test_scores):.2f}",
            f"  std    : {statistics.stdev(test_scores):.2f}",
        ]
    lines.append("=" * 50)

    summary_text = "\n".join(lines)
    print(f"\n{summary_text}")
    Path("debug_logs/summary.txt").write_text(summary_text)


async def main():
    Path("debug_logs").mkdir(exist_ok=True)

    print("MESA Megamodel Instance Initialization")
    registry = MegamodelRegistry()
    await populate_registry(registry)

    full_dataset = load_specialization_dataset(DATASET_PATH)
    print(f"Loaded {len(full_dataset)} samples.")

    random.seed(42)
    random.shuffle(full_dataset)
    train_dataset = full_dataset[:80]
    test_dataset  = full_dataset[80:100]
    print(f"Train: {len(train_dataset)} | Test (held-out): {len(test_dataset)}")

    # Load existing state in case we are resuming after a crash
    state = load_state()
    completed_runs = set(state["completed_runs"])
    print(f"Resuming from state: {len(completed_runs)}/{N_RUNS} runs already done.")

    for run_id in range(N_RUNS):
        if run_id in completed_runs:
            print(f"\n[Run {run_id + 1}] Already completed, skipping.")
            continue

        print(f"\n{'='*50}\nRUN {run_id + 1}/{N_RUNS}\n{'='*50}")

        baseline_log = f"debug_logs/run{run_id + 1}_baseline.txt"
        spec_log     = f"debug_logs/run{run_id + 1}_specialization.txt"
        test_log     = f"debug_logs/run{run_id + 1}_test.txt"

        # Reset skill files to initial state
        skill_generator = MegamodelToSkill(registry)
        skill_generator.generate_patterns()

        meta = MetaAgent()

        # --- Baseline (no skill, sample by sample, saved incrementally) ---
        print(f"\n[Run {run_id + 1}] Evaluating no-skill baseline...")
        baseline_scores = []
        for i, sample in enumerate(test_dataset):
            print(f"  [Baseline {i+1}/{len(test_dataset)}] {sample['instruction']}")
            _, actual_calls = meta.agent.run(sample["instruction"], file=None)
            score = meta.evaluate(actual_calls, sample["relevant_apis"])
            baseline_scores.append(score)
            meta._append_log(baseline_log, f"sample={i+1}/{len(test_dataset)} | score={score:.2f} | instruction={sample['instruction']}")

        baseline_avg = sum(baseline_scores) / len(baseline_scores)
        meta._append_log(baseline_log, f"BASELINE avg_score={baseline_avg:.2f}")
        print(f">>> Baseline score: {baseline_avg:.2f}")

        # --- Specialization loop ---
        print(f"\n[Run {run_id + 1}] Starting specialization ({MAX_ITER} iterations)...")
        meta.specialize_agent(
            train_dataset,
            threshold=2.0,
            max_iterations=MAX_ITER,
            log_file=spec_log,
        )

        # --- Final evaluation on held-out test set, sample by sample ---
        print(f"\n[Run {run_id + 1}] Evaluating on held-out test set...")
        test_scores = []
        for i, sample in enumerate(test_dataset):
            print(f"  [Test {i+1}/{len(test_dataset)}] {sample['instruction']}")
            skill_file = meta._skill_for(sample["relevant_apis"])
            _, actual_calls = meta.agent.run(sample["instruction"], skill_file)
            score = meta.evaluate(actual_calls, sample["relevant_apis"])
            test_scores.append(score)
            meta._append_log(test_log, f"sample={i+1}/{len(test_dataset)} | score={score:.2f} | instruction={sample['instruction']}")

        test_avg = sum(test_scores) / len(test_scores)
        meta._append_log(test_log, f"TEST avg_score={test_avg:.2f}")
        print(f">>> Test score: {test_avg:.2f}")

        # --- Save state after this run completes ---
        state["completed_runs"].append(run_id)
        state["all_baseline_scores"].append(baseline_avg)
        state["all_test_scores"].append(test_avg)
        save_state(state)

        # Update summary after every run
        save_summary(state, len(train_dataset), len(test_dataset))

    print("\n>>> All runs complete.")
    save_summary(state, len(train_dataset), len(test_dataset))


if __name__ == "__main__":
    asyncio.run(main())