"""
Error-by-error specialization (ATL).

Phase 1 — Collect : run the 80 training samples with the initial megamodel skill
                    (no refinement). Every sample with score < 1.0 (0.0 or 0.5) is
                    logged, ungrouped, to <run_id>_errors.json with its train index.
Phase 2 — Step 0  : evaluate the initial skill on the 20 held-out test samples.
Phase 3 — Refine  : for each error k (in order): give that single error to the
                    meta-agent, refine the skill (cumulatively), evaluate on the
                    20 held-out test samples, log the average.

Outputs (debug_logs/):
  <run_id>_errors.json            every error, one entry each, with train index
  <run_id>_eb_results.csv         one row per step: error -> held-out test avg
  <run_id>_eb_results.json        same + per-test-sample scores
  <run_id>_eb_log.txt             full detailed log
  <run_id>_eb_skills/step_XX_*.md skill snapshot after each step
  <run_id>_eb_summary.txt         final summary

Resumable: re-run the script and it continues from debug_logs/eb_checkpoint.json.
"""
import asyncio
import csv
import datetime
import json
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

RUN_ID      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
CHECKPOINT  = "debug_logs/eb_checkpoint.json"
TEST_SIZE   = 20
MAX_RETRIES = 1   # extra attempts when opencode itself crashes


# ── Progress ─────────────────────────────────────────────────────────────────
class Progress:
    """Overall progress in agent runs, with ETA based on the observed avg run time."""

    def __init__(self, cp: dict, n_train: int, n_test: int):
        self.cp = cp
        self.n_train = n_train
        self.n_test = n_test

    def total(self) -> int:
        n_errors = self.cp["n_errors"]
        if n_errors is None:
            # Estimate errors from the failure rate seen so far (fallback: 35%)
            done = len(self.cp["train_results"])
            failed = sum(1 for r in self.cp["train_results"] if r["score"] < 1.0)
            rate = failed / done if done else 0.35
            n_errors = round(rate * self.n_train)
        return self.n_train + self.n_test + n_errors * self.n_test

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
        est = "" if self.cp["n_errors"] is not None else " (est.)"
        return f"[{bar}] {pct:5.1f}% | {done}/{total}{est} runs | ETA {eta} | {label}"


# ── Checkpoint ───────────────────────────────────────────────────────────────
def load_checkpoint() -> dict | None:
    if Path(CHECKPOINT).exists():
        cp = json.loads(Path(CHECKPOINT).read_text())
        print(f">>> Checkpoint found: run={cp['run_id']} phase={cp['phase']}")
        return cp
    return None


def save_checkpoint(cp: dict, meta: MetaAgent) -> None:
    cp["skill_apply"] = Path(meta.apply_skill).read_text()
    cp["skill_get"] = Path(meta.get_skill).read_text()
    Path(CHECKPOINT).write_text(json.dumps(cp, indent=2))


def new_checkpoint() -> dict:
    return {
        "run_id": RUN_ID,
        "phase": "collect",       # collect -> step0 -> refine -> done
        "train_results": [],      # one entry per train sample
        "errors": [],             # every failing train sample, ungrouped
        "n_errors": None,
        "steps": [],              # finished steps (0 = initial skill)
        "current_step": 0,
        "current_test_scores": [],
        "current_refine_status": None,
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


def expected_names(sample: dict) -> list[str]:
    return [e["api_name"] for e in sample["relevant_apis"]]


def write_results(cp: dict, results_csv: str, results_json: str) -> None:
    fields = ["step", "error_id", "train_index", "error_score", "skill_file",
              "refine_status", "test_avg", "delta_vs_prev", "delta_vs_initial", "instruction"]
    with open(results_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in cp["steps"]:
            w.writerow({k: s.get(k) for k in fields})
    Path(results_json).write_text(json.dumps(cp["steps"], indent=2, ensure_ascii=False))


def save_summary(cp: dict, path: str) -> None:
    steps = cp["steps"]
    initial = steps[0]["test_avg"] if steps else None
    final = steps[-1]["test_avg"] if steps else None
    best = max(steps, key=lambda s: s["test_avg"]) if steps else None
    n0 = sum(1 for e in cp["errors"] if e["score"] == 0.0)
    n05 = len(cp["errors"]) - n0
    train_avg = sum(r["score"] for r in cp["train_results"]) / max(len(cp["train_results"]), 1)
    lines = [
        "=" * 60,
        "ATL ERROR-BY-ERROR SPECIALIZATION SUMMARY",
        "=" * 60,
        f"Run ID                 : {cp['run_id']}",
        f"Train samples          : {len(cp['train_results'])}",
        f"Train avg (init skill) : {train_avg:.2f}",
        f"Errors                 : {len(cp['errors'])}  (score 0.0: {n0} | score 0.5: {n05})",
        f"Total agent runs       : {cp['runs_done']}",
        f"Total agent time       : {datetime.timedelta(seconds=int(cp['run_seconds']))}",
        "",
        f"Held-out test avg — initial skill : {initial:.2f}",
        f"Held-out test avg — final skill   : {final:.2f}",
        f"Best step                         : {best['step']} (error_id={best['error_id']}, "
        f"train_index={best['train_index']}) avg={best['test_avg']:.2f}",
        "",
        "step | error_id | train_idx | err_score | test_avg",
    ]
    for s in steps:
        err_score = "-" if s["error_score"] is None else f"{s['error_score']:.2f}"
        lines.append(
            f"{s['step']:>4} | {str(s['error_id'] or '-'):>8} | {str(s['train_index'] or '-'):>9} | "
            f"{err_score:>9} | {s['test_avg']:.2f}"
        )
    lines.append("=" * 60)
    text = "\n".join(lines)
    print("\n" + text)
    Path(path).write_text(text)


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
        cp = new_checkpoint()
        print("\nInitializing skills from the megamodel...")
        MegamodelToSkill(registry).generate_patterns()
        print("Skill files generated.")
    else:
        Path(meta.apply_skill).write_text(cp["skill_apply"])
        Path(meta.get_skill).write_text(cp["skill_get"])
        print("> Resuming — skills restored from checkpoint")

    run_id = cp["run_id"]
    log_file     = f"debug_logs/{run_id}_eb_log.txt"
    errors_file  = f"debug_logs/{run_id}_errors.json"
    results_csv  = f"debug_logs/{run_id}_eb_results.csv"
    results_json = f"debug_logs/{run_id}_eb_results.json"
    summary_file = f"debug_logs/{run_id}_eb_summary.txt"
    skills_dir   = Path(f"debug_logs/{run_id}_eb_skills")
    skills_dir.mkdir(parents=True, exist_ok=True)
    log = lambda line: meta._append_log(log_file, line)

    progress = Progress(cp, len(train_dataset), len(test_dataset))
    print(f"MESA ATL error-by-error run — {run_id}")
    log(f"=== run {run_id} (re)started at {datetime.datetime.now().isoformat(timespec='seconds')} "
        f"| phase={cp['phase']} ===")

    # ── PHASE 1: collect errors with the initial skill ──────────────────────
    if cp["phase"] == "collect":
        print(f"\n── Phase 1: running {len(train_dataset)} train samples with the initial skill ──")
        for i in range(len(cp["train_results"]), len(train_dataset)):
            sample = train_dataset[i]
            score, actual_calls, exc = run_sample(meta, sample, progress)
            entry = {
                "train_index": i + 1,
                "instruction": sample["instruction"],
                "level": sample.get("level"),
                "skill_file": meta._skill_for(sample["relevant_apis"]),
                "score": score,
                "expected_apis": sample["relevant_apis"],
                "actual_calls": actual_calls,
                "agent_exception": exc,
            }
            cp["train_results"].append(entry)
            if score < 1.0:
                cp["errors"].append({"error_id": len(cp["errors"]) + 1, **entry})
            print(progress.line(f"train {i+1}/{len(train_dataset)} score={score:.2f} "
                                f"errors so far={len(cp['errors'])}"))
            log(f"COLLECT | train={i+1}/{len(train_dataset)} | score={score:.2f} | "
                f"expected={expected_names(sample)} | actual={[a['api_name'] for a in actual_calls]}"
                + (f" | exception={exc}" if exc else ""))
            Path(errors_file).write_text(json.dumps(cp["errors"], indent=2, ensure_ascii=False))
            save_checkpoint(cp, meta)

        cp["n_errors"] = len(cp["errors"])
        cp["phase"] = "step0"
        n0 = sum(1 for e in cp["errors"] if e["score"] == 0.0)
        log(f"COLLECT done | errors={cp['n_errors']} (0.0: {n0} | 0.5: {cp['n_errors'] - n0})")
        print(f">>> Phase 1 done — {cp['n_errors']} errors (0.0: {n0} | 0.5: {cp['n_errors'] - n0}) "
              f"→ {errors_file}")
        save_checkpoint(cp, meta)

    # ── PHASE 2 + 3: step 0 (initial skill) then one step per error ─────────
    if cp["phase"] in ("step0", "refine"):
        n_steps = cp["n_errors"] + 1
        for step in range(cp["current_step"], n_steps):
            error = cp["errors"][step - 1] if step > 0 else None

            # Refine the skill with this single error (only once per step)
            if error is not None and cp["current_refine_status"] is None:
                skill_file = error["skill_file"]
                payload = meta._build_failure_payload([{
                    "instruction": error["instruction"],
                    "expected_apis": error["expected_apis"],
                    "actual_calls": error["actual_calls"],
                }], max_examples=1)
                backup = Path(skill_file).read_text()
                try:
                    refined = meta.refine_agent_definition_batch(payload, skill_file, backup=backup)
                    status = "unchanged" if refined == backup else "rewritten"
                except Exception as e:
                    Path(skill_file).write_text(backup)
                    status = f"refine_error: {type(e).__name__}: {str(e)[:200]}"
                cp["current_refine_status"] = status
                log(f"REFINE | step={step}/{n_steps - 1} | error_id={error['error_id']} | "
                    f"train_index={error['train_index']} | score={error['score']:.2f} | "
                    f"skill={skill_file} | status={status}")
                print(f"\n── Step {step}/{n_steps - 1}: error_id={error['error_id']} "
                      f"(train sample {error['train_index']}, score={error['score']:.2f}) → {status}")
                save_checkpoint(cp, meta)
            elif error is None and not cp["current_test_scores"]:
                print(f"\n── Step 0/{n_steps - 1}: initial megamodel skill on held-out test ──")

            # Evaluate on the held-out test set
            for j in range(len(cp["current_test_scores"]), len(test_dataset)):
                sample = test_dataset[j]
                score, actual_calls, exc = run_sample(meta, sample, progress)
                cp["current_test_scores"].append(score)
                print(progress.line(f"step {step}/{n_steps - 1} test {j+1}/{len(test_dataset)} "
                                    f"score={score:.2f}"))
                log(f"TEST | step={step} | test={j+1}/{len(test_dataset)} | score={score:.2f} | "
                    f"expected={expected_names(sample)} | actual={[a['api_name'] for a in actual_calls]}"
                    + (f" | exception={exc}" if exc else ""))
                save_checkpoint(cp, meta)

            scores = cp["current_test_scores"]
            test_avg = sum(scores) / len(scores)
            prev_avg = cp["steps"][-1]["test_avg"] if cp["steps"] else None
            init_avg = cp["steps"][0]["test_avg"] if cp["steps"] else test_avg
            cp["steps"].append({
                "step": step,
                "error_id": error["error_id"] if error else None,
                "train_index": error["train_index"] if error else None,
                "error_score": error["score"] if error else None,
                "skill_file": error["skill_file"] if error else None,
                "refine_status": cp["current_refine_status"] if error else "initial",
                "test_avg": test_avg,
                "delta_vs_prev": None if prev_avg is None else round(test_avg - prev_avg, 4),
                "delta_vs_initial": round(test_avg - init_avg, 4),
                "test_scores": scores,
                "instruction": error["instruction"] if error else None,
            })
            (skills_dir / f"step_{step:02d}_mde-apply.md").write_text(Path(meta.apply_skill).read_text())
            (skills_dir / f"step_{step:02d}_mde-get.md").write_text(Path(meta.get_skill).read_text())
            log(f"STEP {step} DONE | test_avg={test_avg:.2f}"
                + ("" if prev_avg is None else f" | delta_vs_prev={test_avg - prev_avg:+.2f}"))
            print(f">>> Step {step} test avg = {test_avg:.2f}"
                  + ("" if prev_avg is None else f" ({test_avg - prev_avg:+.2f} vs previous)"))

            cp["current_step"] = step + 1
            cp["current_test_scores"] = []
            cp["current_refine_status"] = None
            cp["phase"] = "refine"
            write_results(cp, results_csv, results_json)
            save_checkpoint(cp, meta)

        cp["phase"] = "done"
        save_checkpoint(cp, meta)

    # ── Done ────────────────────────────────────────────────────────────────
    if cp["phase"] == "done":
        write_results(cp, results_csv, results_json)
        save_summary(cp, summary_file)
        print(f"\n>>> All done. Results: {results_csv}")
        Path(CHECKPOINT).rename(f"debug_logs/{run_id}_eb_checkpoint_final.json")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n>>> Interrupted — re-run the script to resume from the checkpoint.")
    except Exception:
        traceback.print_exc()
        print("\n>>> Crashed — re-run the script to resume from the checkpoint.")
        sys.exit(1)
