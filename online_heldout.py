"""
Online specialization (ATL) evaluated on the held-out set.

Step 0  : initialize the skills from the megamodel and evaluate them on the 20
          held-out test samples.
Online  : go through the 80 training samples ONE BY ONE (shuffled with a fixed seed,
          see SHUFFLE_TRAIN) with the current skill. When a sample fails
          (score < 1.0), the meta-agent immediately rewrites the skill from that
          single error, and the new skill is evaluated on the 20 held-out samples.
          When a sample passes, the skill is unchanged, so its held-out score is
          the previous one (no re-evaluation).

Why shuffle: stratified_split() returns the train set grouped by level
(1-28 level 1, 29-55 level 2, 56-80 level 3). Without shuffling, the curve would
follow the difficulty ordering rather than the method. The held-out set is the
same 20 samples as every other experiment (seed 42).

Outputs (debug_logs/, prefix <run_id>_oh):
  <run_id>_oh_train_order.json        the shuffled train order (with original index + level)
  <run_id>_oh_items.csv               one row per train sample: score, rewrite, held-out avg after it
  <run_id>_oh_steps.csv / .json       one row per held-out evaluation (step 0 + one per rewrite)
  <run_id>_oh_log.txt                 full detailed log
  <run_id>_oh_skill_changes.txt       every skill change: triggering sample, diff, full new text
  <run_id>_oh_skills/step_XX_*.md     every skill version (step_00 = initial megamodel skill)
  <run_id>_oh_summary.txt             final summary

Resumable: re-run the script and it continues from debug_logs/oh_checkpoint.json.
"""
import asyncio
import csv
import datetime
import difflib
import json
import random
import time
import traceback
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from modeling_agents.meta_agent import MetaAgent
import sys
sys.path.insert(0, '.opencode/skills')
from megamodel_toskill import MegamodelToSkill
from main import DATASET_PATH, stratified_split, load_specialization_dataset

RUN_ID        = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
CHECKPOINT    = "debug_logs/oh_checkpoint.json"
TEST_SIZE     = 20
SHUFFLE_TRAIN = True   # shuffle the train order (recommended, see docstring)
TRAIN_SEED    = 2026   # seed of the train shuffle (the held-out split keeps seed 42)
MAX_RETRIES   = 1      # extra attempts when opencode itself crashes


# ── Progress ─────────────────────────────────────────────────────────────────
class Progress:
    """Overall progress in agent runs, with ETA based on the observed avg run time."""

    def __init__(self, cp: dict, n_train: int, n_test: int):
        self.cp = cp
        self.n_train = n_train
        self.n_test = n_test

    def total(self) -> int:
        items = self.cp["items"]
        done = len(items)
        rewrites = sum(1 for it in items if it["rewritten"])
        # Expected remaining rewrites from the rewrite rate so far (35% until 10 samples are done)
        rate = rewrites / done if done >= 10 else 0.35
        expected = rewrites + round(rate * (self.n_train - done))
        return self.n_test + self.n_train + expected * self.n_test

    def tick(self, run_seconds: float) -> None:
        self.cp["runs_done"] += 1
        self.cp["run_seconds"] += run_seconds

    def line(self, label: str) -> str:
        done = self.cp["runs_done"]
        total = max(self.total(), done)
        pct = 100 * done / total if total else 0
        avg = self.cp["run_seconds"] / done if done else 0
        eta = datetime.timedelta(seconds=int(avg * (total - done)))
        bar = "#" * int(pct // 5) + "-" * (20 - int(pct // 5))
        est = "" if self.cp["phase"] == "done" else " (est.)"
        return f"[{bar}] {pct:5.1f}% | {done}/{total}{est} runs | ETA {eta} | {label}"


# ── Checkpoint ───────────────────────────────────────────────────────────────
def load_checkpoint() -> dict | None:
    if Path(CHECKPOINT).exists():
        cp = json.loads(Path(CHECKPOINT).read_text())
        print(f">>> Checkpoint found: run={cp['run_id']} phase={cp['phase']} item={cp['cur_item']}")
        return cp
    return None


def save_checkpoint(cp: dict, meta: MetaAgent) -> None:
    cp["skill_apply"] = Path(meta.apply_skill).read_text()
    cp["skill_get"] = Path(meta.get_skill).read_text()
    Path(CHECKPOINT).write_text(json.dumps(cp, indent=2, ensure_ascii=False))


def new_checkpoint(train_order: list[int]) -> dict:
    return {
        "run_id": RUN_ID,
        "phase": "step0",            # step0 -> online -> done
        "shuffle_train": SHUFFLE_TRAIN,
        "train_seed": TRAIN_SEED,
        "train_order": train_order,  # train_order[pos] = index in the (unshuffled) train split
        "items": [],                 # finished train samples, one entry each
        "steps": [],                 # finished held-out evaluations (step 0 + one per rewrite)
        "cur_item": 0,               # position of the sample being processed
        "cur_result": None,          # train result of the current sample (once run)
        "cur_refine_status": None,   # refine status of the current sample (once refined)
        "cur_test_scores": [],       # held-out scores of the evaluation in progress
        "runs_done": 0,
        "run_seconds": 0.0,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────
def run_sample(meta: MetaAgent, sample: dict, progress: Progress) -> tuple[float, list[dict], str | None]:
    """Run one sample through the agent and score it. Returns (score, actual_calls, exception)."""
    skill_file = meta._skill_for(sample["relevant_apis"])
    start = time.time()
    error = None
    actual_calls: list[dict] = []
    for attempt in range(MAX_RETRIES + 1):
        try:
            _, actual_calls = meta.agent.run(sample["instruction"], skill_file)
            error = None
            break
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)[:300]}"
            print(f"    ! agent exception (attempt {attempt + 1}): {error}")
    progress.tick(time.time() - start)
    score = meta.evaluate(actual_calls, sample["relevant_apis"])
    return score, actual_calls, error


def names(calls: list[dict]) -> list[str]:
    return [c["api_name"] for c in calls]


def skill_name(skill_file: str) -> str:
    return Path(skill_file).parent.name   # mde-apply / mde-get


def save_skill_versions(meta: MetaAgent, skills_dir: Path, step: int) -> None:
    for skill_file in (meta.apply_skill, meta.get_skill):
        (skills_dir / f"step_{step:02d}_{skill_name(skill_file)}.md").write_text(Path(skill_file).read_text())


def log_skill_change(changes_file: str, step: int, skill_file: str, item: dict,
                     before: str, after: str, status: str) -> None:
    diff = "\n".join(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile=f"{skill_name(skill_file)} (before step {step})",
        tofile=f"{skill_name(skill_file)} (after step {step})",
        lineterm="",
    ))
    lines = [
        "=" * 80,
        f"STEP {step} | train sample {item['pos']} (original index {item['train_index']}, "
        f"level {item['level']}) | skill={skill_file} | status={status} | "
        f"{datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Error: score={item['score']:.2f} | expected={names(item['expected_apis'])} | "
        f"actual={names(item['actual_calls'])}",
        f"Instruction: {item['instruction']}",
        "-" * 80, "DIFF:", diff or "(no change)", "-" * 80, "NEW SKILL:", after, "",
    ]
    with open(changes_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_results(cp: dict, prefix: str) -> None:
    item_fields = ["pos", "train_index", "level", "skill_file", "score", "refine_status",
                   "rewritten", "step", "heldout_avg", "instruction"]
    with open(f"{prefix}_items.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=item_fields)
        w.writeheader()
        for it in cp["items"]:
            w.writerow({k: it.get(k) for k in item_fields})
    step_fields = ["step", "after_pos", "train_index", "level", "skill_file", "test_avg",
                   "delta_vs_prev", "delta_vs_initial"]
    with open(f"{prefix}_steps.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=step_fields)
        w.writeheader()
        for s in cp["steps"]:
            w.writerow({k: s.get(k) for k in step_fields})
    Path(f"{prefix}_steps.json").write_text(json.dumps(cp["steps"], indent=2, ensure_ascii=False))


def save_summary(cp: dict, path: str) -> None:
    items, steps = cp["items"], cp["steps"]
    initial, final = steps[0]["test_avg"], steps[-1]["test_avg"]
    best = max(steps, key=lambda s: s["test_avg"])
    fails = [it for it in items if it["score"] < 1.0]
    n0 = sum(1 for it in fails if it["score"] == 0.0)
    train_avg = sum(it["score"] for it in items) / max(len(items), 1)
    status_count = {}
    for it in fails:
        key = (it["refine_status"] or "").split(":")[0]
        status_count[key] = status_count.get(key, 0) + 1
    lines = [
        "=" * 70,
        "ATL ONLINE SPECIALIZATION — HELD-OUT EVALUATION — SUMMARY",
        "=" * 70,
        f"Run ID                  : {cp['run_id']}",
        f"Train order             : {'shuffled, seed ' + str(cp['train_seed']) if cp['shuffle_train'] else 'original (grouped by level)'}",
        f"Train samples           : {len(items)}",
        f"Train avg (prequential) : {train_avg:.2f}",
        f"Failures                : {len(fails)}  (score 0.0: {n0} | score 0.5: {len(fails) - n0})",
        f"Refinements             : {status_count}",
        f"Held-out evaluations    : {len(steps)}",
        f"Total agent runs        : {cp['runs_done']}",
        f"Total agent time        : {datetime.timedelta(seconds=int(cp['run_seconds']))}",
        "",
        f"Held-out test avg — initial skill : {initial:.2f}",
        f"Held-out test avg — final skill   : {final:.2f}",
        f"Best step                         : {best['step']} (after train sample {best['after_pos']}) "
        f"avg={best['test_avg']:.2f}",
        "",
        "step | after sample | orig idx | level | skill      | test_avg | delta",
    ]
    for s in steps:
        delta = "" if s["delta_vs_prev"] is None else f"{s['delta_vs_prev']:+.2f}"
        lines.append(f"{s['step']:>4} | {s['after_pos']:>12} | {str(s['train_index'] or '-'):>8} | "
                     f"{str(s['level'] or '-'):>5} | {skill_name(s['skill_file']) if s['skill_file'] else '-':<10} | "
                     f"{s['test_avg']:>8.2f} | {delta}")
    lines.append("=" * 70)
    text = "\n".join(lines)
    print("\n" + text)
    Path(path).write_text(text)


def evaluate_heldout(meta, cp, test_dataset, progress, log, label) -> float:
    """Evaluate the current skill on the held-out set (resumes a partial evaluation)."""
    for j in range(len(cp["cur_test_scores"]), len(test_dataset)):
        sample = test_dataset[j]
        score, actual_calls, exc = run_sample(meta, sample, progress)
        cp["cur_test_scores"].append(score)
        print(progress.line(f"{label} held-out {j+1}/{len(test_dataset)} "
                            f"({100 * (j+1) / len(test_dataset):.0f}%) score={score:.2f}"))
        log(f"TEST | {label} | test={j+1}/{len(test_dataset)} | score={score:.2f} | "
            f"expected={names(sample['relevant_apis'])} | actual={names(actual_calls)}"
            + (f" | exception={exc}" if exc else ""))
        save_checkpoint(cp, meta)
    return sum(cp["cur_test_scores"]) / len(cp["cur_test_scores"])


def record_step(cp: dict, test_avg: float, item: dict | None) -> dict:
    prev = cp["steps"][-1]["test_avg"] if cp["steps"] else None
    init = cp["steps"][0]["test_avg"] if cp["steps"] else test_avg
    step = {
        "step": len(cp["steps"]),
        "after_pos": item["pos"] if item else 0,
        "train_index": item["train_index"] if item else None,
        "level": item["level"] if item else None,
        "skill_file": item["skill_file"] if item else None,
        "test_avg": test_avg,
        "delta_vs_prev": None if prev is None else round(test_avg - prev, 4),
        "delta_vs_initial": round(test_avg - init, 4),
        "test_scores": list(cp["cur_test_scores"]),
    }
    cp["steps"].append(step)
    cp["cur_test_scores"] = []
    return step


# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    Path("debug_logs").mkdir(exist_ok=True)

    full_dataset = load_specialization_dataset(DATASET_PATH)
    train_dataset, test_dataset = stratified_split(full_dataset, test_size=TEST_SIZE)
    print(f"Loaded {len(full_dataset)} samples | Train: {len(train_dataset)} | Test (held-out): {len(test_dataset)}")

    registry = MegamodelRegistry()
    await populate_registry(registry)
    meta = MetaAgent()

    cp = load_checkpoint()
    if cp is None:
        order = list(range(len(train_dataset)))
        if SHUFFLE_TRAIN:
            random.Random(TRAIN_SEED).shuffle(order)
        cp = new_checkpoint(order)
        print("\nInitializing skills from the megamodel...")
        MegamodelToSkill(registry).generate_patterns()
        print("Skill files generated.")
    else:
        Path(meta.apply_skill).write_text(cp["skill_apply"])
        Path(meta.get_skill).write_text(cp["skill_get"])
        print("> Resuming — skills restored from checkpoint")

    run_id = cp["run_id"]
    prefix       = f"debug_logs/{run_id}_oh"
    log_file     = f"{prefix}_log.txt"
    changes_file = f"{prefix}_skill_changes.txt"
    summary_file = f"{prefix}_summary.txt"
    skills_dir   = Path(f"{prefix}_skills")
    skills_dir.mkdir(parents=True, exist_ok=True)
    log = lambda line: meta._append_log(log_file, line)

    order = cp["train_order"]
    Path(f"{prefix}_train_order.json").write_text(json.dumps(
        [{"pos": p + 1, "train_index": idx + 1, "level": train_dataset[idx].get("level"),
          "instruction": train_dataset[idx]["instruction"]} for p, idx in enumerate(order)],
        indent=2, ensure_ascii=False))

    progress = Progress(cp, len(train_dataset), len(test_dataset))
    print(f"MESA ATL online specialization (held-out eval) — {run_id} | "
          f"train order: {'shuffled, seed ' + str(cp['train_seed']) if cp['shuffle_train'] else 'original'}")
    log(f"=== run {run_id} (re)started at {datetime.datetime.now().isoformat(timespec='seconds')} "
        f"| phase={cp['phase']} | item={cp['cur_item']} ===")

    # ── Step 0: initial megamodel skill on the held-out set ─────────────────
    if cp["phase"] == "step0":
        print(f"\n── Step 0: initial megamodel skill on held-out test ──")
        if not (skills_dir / "step_00_mde-apply.md").exists():
            save_skill_versions(meta, skills_dir, 0)
        test_avg = evaluate_heldout(meta, cp, test_dataset, progress, log, "step 0")
        record_step(cp, test_avg, None)
        log(f"STEP 0 DONE | test_avg={test_avg:.2f}")
        print(f">>> Step 0 held-out avg = {test_avg:.2f}")
        cp["phase"] = "online"
        write_results(cp, prefix)
        save_checkpoint(cp, meta)

    # ── Online pass over the train samples ──────────────────────────────────
    if cp["phase"] == "online":
        n = len(order)
        for pos in range(cp["cur_item"], n):
            idx = order[pos]
            sample = train_dataset[idx]
            label = f"sample {pos+1}/{n}"

            # 1. Run the train sample with the current skill
            if cp["cur_result"] is None:
                score, actual_calls, exc = run_sample(meta, sample, progress)
                cp["cur_result"] = {
                    "pos": pos + 1,
                    "train_index": idx + 1,
                    "level": sample.get("level"),
                    "instruction": sample["instruction"],
                    "skill_file": meta._skill_for(sample["relevant_apis"]),
                    "score": score,
                    "expected_apis": sample["relevant_apis"],
                    "actual_calls": actual_calls,
                    "agent_exception": exc,
                }
                print(progress.line(f"{label} ({100 * (pos+1) / n:.0f}%) score={score:.2f}"))
                log(f"TRAIN | {label} | orig={idx+1} | level={sample.get('level')} | score={score:.2f} | "
                    f"expected={names(sample['relevant_apis'])} | actual={names(actual_calls)}"
                    + (f" | exception={exc}" if exc else ""))
                save_checkpoint(cp, meta)
            item = cp["cur_result"]

            # 2. Failure -> the meta-agent rewrites the skill from this single error
            if item["score"] < 1.0 and cp["cur_refine_status"] is None:
                skill_file = item["skill_file"]
                payload = meta._build_failure_payload([{
                    "instruction": item["instruction"],
                    "expected_apis": item["expected_apis"],
                    "actual_calls": item["actual_calls"],
                }], max_examples=1)
                backup = Path(skill_file).read_text()
                try:
                    refined = meta.refine_agent_definition_batch(payload, skill_file, backup=backup)
                    status = "unchanged" if refined.strip() == backup.strip() else "rewritten"
                except Exception as e:
                    Path(skill_file).write_text(backup)
                    status = f"refine_error: {type(e).__name__}: {str(e)[:200]}"
                cp["cur_refine_status"] = status
                step_no = len(cp["steps"])
                log_skill_change(changes_file, step_no, skill_file, item, backup,
                                 Path(skill_file).read_text(), status)
                log(f"REFINE | {label} | skill={skill_file} | status={status}")
                print(f"    → {skill_name(skill_file)} {status}")
                if status == "rewritten":
                    save_skill_versions(meta, skills_dir, step_no)
                save_checkpoint(cp, meta)

            # 3. Skill changed -> evaluate the new skill on the held-out set
            rewritten = cp["cur_refine_status"] == "rewritten"
            if rewritten:
                test_avg = evaluate_heldout(meta, cp, test_dataset, progress, log, f"step {len(cp['steps'])}")
                step = record_step(cp, test_avg, item)
                log(f"STEP {step['step']} DONE | after {label} | test_avg={test_avg:.2f} | "
                    f"delta_vs_prev={step['delta_vs_prev']:+.2f}")
                print(f">>> Step {step['step']} (after {label}) held-out avg = {test_avg:.2f} "
                      f"({step['delta_vs_prev']:+.2f} vs previous)")

            # 4. Close the sample
            cp["items"].append({
                **item,
                "refine_status": cp["cur_refine_status"],
                "rewritten": rewritten,
                "step": len(cp["steps"]) - 1,
                "heldout_avg": cp["steps"][-1]["test_avg"],
            })
            cp["cur_item"] = pos + 1
            cp["cur_result"] = None
            cp["cur_refine_status"] = None
            write_results(cp, prefix)
            save_checkpoint(cp, meta)

        cp["phase"] = "done"
        save_checkpoint(cp, meta)

    # ── Done ────────────────────────────────────────────────────────────────
    if cp["phase"] == "done":
        write_results(cp, prefix)
        save_summary(cp, summary_file)
        print(f"\n>>> All done. Results: {prefix}_steps.csv and {prefix}_items.csv")
        Path(CHECKPOINT).rename(f"{prefix}_checkpoint_final.json")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n>>> Interrupted — re-run the script to resume from the checkpoint.")
    except Exception:
        traceback.print_exc()
        print("\n>>> Crashed — re-run the script to resume from the checkpoint.")
        sys.exit(1)
