import asyncio
from collections import defaultdict
import datetime
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

RUN_ID       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
DATASET_PATH = "datasets/testing_datatset.json"
MAX_ITER     = 8
ONLINE       = True   # True = online specialization, False = batch
CHECKPOINT   = "debug_logs/atl_checkpoint.json"


def stratified_split(dataset, test_size=20, seed=42):
    random.seed(seed)
    groups = defaultdict(list)
    for item in dataset:
        level = item.get("level", "none")
        groups[level].append(item)
    for key in groups:
        random.shuffle(groups[key])
    train, test = [], []
    total = len(dataset)
    test_ratio = test_size / total
    for level, items in groups.items():
        n_test = max(1, round(len(items) * test_ratio))
        test.extend(items[:n_test])
        train.extend(items[n_test:])
    random.shuffle(test)
    while len(test) > test_size:
        train.append(test.pop())
    while len(test) < test_size and train:
        test.append(train.pop())
    return train, test


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


def load_checkpoint() -> dict:
    if Path(CHECKPOINT).exists():
        with open(CHECKPOINT) as f:
            cp = json.load(f)
            print(f">>> Checkpoint found: phase={cp.get('phase')} | sample={cp.get('sample_index')}")
            return cp
    return {
        "run_id": RUN_ID,
        "phase": "specialization",  # start directly here
        "sample_index": 0,
        "test_scores": [],
        "test_avg": None,
        "mode": "online" if ONLINE else "batch",
    }


def save_checkpoint(cp: dict) -> None:
    Path("debug_logs").mkdir(exist_ok=True)
    with open(CHECKPOINT, "w") as f:
        json.dump(cp, f, indent=2)


def save_summary(cp: dict, train_size: int, test_size: int) -> None:
    mode = cp.get("mode", "batch")
    lines = [
        "=" * 50,
        "ATL RESULTS SUMMARY",
        "=" * 50,
        f"Run ID     : {cp['run_id']}",
        f"Mode       : {mode}",
        f"Iterations : {MAX_ITER if mode == 'batch' else 'online (1 pass)'}",
        f"Train size : {train_size}",
        f"Test size  : {test_size}",
        "",
        "After specialization (held-out test)",
        f"  scores : {[round(s, 2) for s in cp['test_scores']]}",
        f"  avg    : {cp['test_avg']:.2f}" if cp['test_avg'] is not None else "  avg    : pending",
        "=" * 50,
    ]
    summary_text = "\n".join(lines)
    print(f"\n{summary_text}")
    Path(f"debug_logs/{cp['run_id']}_atl_summary.txt").write_text(summary_text)


async def main():
    Path("debug_logs").mkdir(exist_ok=True)

    cp = load_checkpoint()
    run_id = cp.get("run_id", RUN_ID)

    mode = "online" if ONLINE else "batch"
    baseline_log = f"debug_logs/{run_id}_baseline.txt"
    spec_log     = f"debug_logs/{run_id}_{mode}_specialization.txt"
    test_log     = f"debug_logs/{run_id}_test.txt"
    spec_ckpt    = f"debug_logs/{run_id}_atl_{mode}_spec_checkpoint.json"

    print(f"MESA ATL Run — {run_id} — mode={mode}")

    full_dataset = load_specialization_dataset(DATASET_PATH)
    print(f"Loaded {len(full_dataset)} samples.")

    train_dataset, test_dataset = stratified_split(full_dataset, test_size=20)
    print(f"Train: {len(train_dataset)} | Test (held-out): {len(test_dataset)}")

    if cp["phase"] == "baseline":
        print("\nInitializing Megamodel Registry...")
        registry = MegamodelRegistry()
        await populate_registry(registry)
        skill_generator = MegamodelToSkill(registry)
        skill_generator.generate_patterns()
        print("Skill files generated.")
    else:
        print("\n> Resuming — skipping skill regeneration to preserve existing SKILL.md")
        registry = MegamodelRegistry()
        await populate_registry(registry)

    meta = MetaAgent()

    # # ── PHASE 1: Baseline ────────────────────────────────────
    # if cp["phase"] == "baseline":
    #     print(f"\nEvaluating no-skill baseline (resuming from sample {cp['sample_index'] + 1})...")
    #     baseline_scores = cp["baseline_scores"]

    #     for i in range(cp["sample_index"], len(test_dataset)):
    #         sample = test_dataset[i]
    #         pct = round((i / len(test_dataset)) * 100)
    #         print(f"  [Baseline {i+1}/{len(test_dataset)} — {pct}%] {sample['instruction']}")
    #         _, actual_calls = meta.agent.run(sample["instruction"], file=None)
    #         score = meta.evaluate(actual_calls, sample["relevant_apis"])
    #         baseline_scores.append(score)
    #         print(f"  → score={score:.2f}")
    #         meta._append_log(
    #             baseline_log,
    #             f"sample={i+1}/{len(test_dataset)} | score={score:.2f} | instruction={sample['instruction']}"
    #         )
    #         cp["baseline_scores"] = baseline_scores
    #         cp["sample_index"] = i + 1
    #         save_checkpoint(cp)

    #     baseline_avg = sum(baseline_scores) / len(baseline_scores)
    #     cp["baseline_avg"] = baseline_avg
    #     cp["phase"] = "specialization"
    #     cp["sample_index"] = 0
    #     save_checkpoint(cp)
    #     meta._append_log(baseline_log, f"BASELINE avg_score={baseline_avg:.2f}")
    #     print(f">>> Baseline complete — avg score: {baseline_avg:.2f}")

    # ── PHASE 2: Specialization ──────────────────────────────
    if cp["phase"] == "specialization":
        if ONLINE:
            print(f"\nStarting ONLINE specialization ({len(train_dataset)} samples, 1 pass)...")
            meta.specialize_agent_online(
                train_dataset,
                log_file=spec_log,
                checkpoint_file=spec_ckpt,
            )
        else:
            print(f"\nStarting BATCH specialization ({MAX_ITER} iterations)...")
            meta.specialize_agent(
                train_dataset,
                threshold=2.0,
                max_iterations=MAX_ITER,
                log_file=spec_log,
                checkpoint_file=spec_ckpt,
            )
        cp["phase"] = "test"
        cp["sample_index"] = 0
        save_checkpoint(cp)
        print(">>> Specialization complete.")

    # ── PHASE 3: Test ────────────────────────────────────────
    if cp["phase"] == "test":
        print(f"\nEvaluating on held-out test set (resuming from sample {cp['sample_index'] + 1})...")
        test_scores = cp["test_scores"]

        for i in range(cp["sample_index"], len(test_dataset)):
            sample = test_dataset[i]
            pct = round((i / len(test_dataset)) * 100)
            print(f"  [Test {i+1}/{len(test_dataset)} — {pct}%] {sample['instruction']}")
            skill_file = meta._skill_for(sample["relevant_apis"])
            _, actual_calls = meta.agent.run(sample["instruction"], skill_file)
            score = meta.evaluate(actual_calls, sample["relevant_apis"])
            test_scores.append(score)
            print(f"  → score={score:.2f}")
            meta._append_log(
                test_log,
                f"sample={i+1}/{len(test_dataset)} | score={score:.2f} | instruction={sample['instruction']}"
            )
            cp["test_scores"] = test_scores
            cp["sample_index"] = i + 1
            save_checkpoint(cp)

        test_avg = sum(test_scores) / len(test_scores)
        cp["test_avg"] = test_avg
        cp["phase"] = "done"
        save_checkpoint(cp)
        meta._append_log(test_log, f"TEST avg_score={test_avg:.2f}")
        print(f">>> Test complete — avg score: {test_avg:.2f}")

    # ── Done ─────────────────────────────────────────────────
    if cp["phase"] == "done":
        save_summary(cp, len(train_dataset), len(test_dataset))
        print("\n>>> All done.")
        Path(CHECKPOINT).unlink(missing_ok=True)
        if Path(spec_ckpt).exists():
            Path(spec_ckpt).unlink()


if __name__ == "__main__":
    asyncio.run(main())