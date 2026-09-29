"""
Error-by-error specialization (EMF) — batches of 4 errors.

Phase 1 — Collect : run the 80 training samples with the initial megamodel skills
                    (no refinement). Every sample with score < 1.0 (0.0 or 0.5) is
                    added, ungrouped and in order, to the error list with its train index.
Phase 2 — Step 0  : evaluate the initial skills on the 20 held-out test samples.
Phase 3 — Refine  : split the errors, in order, into batches of 4. For each batch:
                    give the 4 errors together to the meta-agent (one call per skill
                    file touched), rewrite the skill (cumulatively), evaluate on the
                    20 held-out test samples, log the average. Then the next 4, etc.

Outputs (debug_logs/, prefix <run_id>_emf_b4):
  <run_id>_emf_b4_errors.json            every error, one entry each, with train index + batch
  <run_id>_emf_b4_results.csv            one row per batch: errors -> held-out test avg
  <run_id>_emf_b4_results.json           same + per-test-sample scores
  <run_id>_emf_b4_log.txt                full detailed log
  <run_id>_emf_b4_skill_changes.txt      every skill change: batch, errors, diff, full new text
  <run_id>_emf_b4_skills/batch_XX_*.md   every skill version (batch_00 = initial megamodel skill)
  <run_id>_emf_b4_summary.txt            final summary

Resumable: re-run the script and it continues from debug_logs/emf_b4_checkpoint.json.
"""
import asyncio
import csv
import datetime
import difflib
import json
import time
import traceback
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
import sys
sys.path.insert(0, '.opencode/skills')
from megamodel_toskill import MegamodelToSkill
from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from modeling_agents.meta_agent import MetaAgent
from main import DATASET_PATH, METAMODEL, stratified_split, load_specialization_dataset

RUN_ID      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
CHECKPOINT  = "debug_logs/emf_b4_checkpoint.json"
BATCH_SIZE  = 4
TEST_SIZE   = 20
MAX_RETRIES = 1        # extra attempts when opencode itself crashes
STOP_AFTER_COLLECT = False   # True = stop after Phase 1 (re-run to continue)


# ── Progress ─────────────────────────────────────────────────────────────────
class Progress:
    """Overall progress in agent runs, with ETA based on the observed avg run time."""

    def __init__(self, cp: dict, n_train: int, n_test: int):
        self.cp = cp
        self.n_train = n_train
        self.n_test = n_test

    def n_batches(self) -> int:
        n_errors = self.cp["n_errors"]
        if n_errors is None:
            # Estimate errors from the failure rate seen so far (35% until 10 samples are done)
            done = len(self.cp["train_results"])
            failed = sum(1 for r in self.cp["train_results"] if r["score"] < 1.0)
            rate = failed / done if done >= 10 else 0.35
            n_errors = round(rate * self.n_train)
        return -(-n_errors // BATCH_SIZE)

    def total(self) -> int:
        return self.n_train + (self.n_batches() + 1) * self.n_test

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
    Path(CHECKPOINT).write_text(json.dumps(cp, indent=2, ensure_ascii=False))


def new_checkpoint() -> dict:
    return {
        "run_id": RUN_ID,
        "phase": "collect",       # collect -> refine -> done
        "train_results": [],      # one entry per train sample
        "errors": [],             # every failing train sample, ungrouped
        "n_errors": None,
        "batches": [],            # list of lists of error_ids
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


def skill_name(skill_file: str) -> str:
    return Path(skill_file).parent.name   # emf-write / emf-read


def save_skill_versions(meta: MetaAgent, skills_dir: Path, step: int) -> None:
    for skill_file in (meta.apply_skill, meta.get_skill):
        (skills_dir / f"batch_{step:02d}_{skill_name(skill_file)}.md").write_text(Path(skill_file).read_text())


def log_skill_change(changes_file: str, step: int, skill_file: str, errors: list[dict],
                     before: str, after: str, status: str) -> None:
    diff = "\n".join(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile=f"{skill_name(skill_file)} (before batch {step})",
        tofile=f"{skill_name(skill_file)} (after batch {step})",
        lineterm="",
    ))
    lines = [
        "=" * 80,
        f"BATCH {step} | skill={skill_file} | status={status} | "
        f"{datetime.datetime.now().isoformat(timespec='seconds')}",
        "Errors given to the meta-agent:",
    ]
    for e in errors:
        lines.append(f"  - error_id={e['error_id']} | train_index={e['train_index']} | score={e['score']:.2f} | "
                     f"expected={[a['api_name'] for a in e['expected_apis']]} | "
                     f"actual={[a['api_name'] for a in e['actual_calls']]} | {e['instruction']}")
    lines += ["-" * 80, "DIFF:", diff or "(no change)", "-" * 80, "NEW SKILL:", after, ""]
    with open(changes_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_results(cp: dict, results_csv: str, results_json: str) -> None:
    fields = ["step", "error_ids", "train_indexes", "error_scores", "refine_status",
              "test_avg", "delta_vs_prev", "delta_vs_initial"]
    with open(results_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in cp["steps"]:
            row = {k: s.get(k) for k in fields}
            for k in ("error_ids", "train_indexes", "error_scores"):
                row[k] = " ".join(str(v) for v in (s.get(k) or [])) or "-"
            if isinstance(row["refine_status"], dict):
                row["refine_status"] = "; ".join(f"{k}: {v}" for k, v in row["refine_status"].items())
            w.writerow(row)
    Path(results_json).write_text(json.dumps(cp["steps"], indent=2, ensure_ascii=False))


def save_summary(cp: dict, path: str) -> None:
    steps = cp["steps"]
    initial, final = steps[0]["test_avg"], steps[-1]["test_avg"]
    best = max(steps, key=lambda s: s["test_avg"])
    n0 = sum(1 for e in cp["errors"] if e["score"] == 0.0)
    train_avg = sum(r["score"] for r in cp["train_results"]) / max(len(cp["train_results"]), 1)
    lines = [
        "=" * 70,
        f"EMF ERROR-BY-ERROR SPECIALIZATION SUMMARY — batches of {BATCH_SIZE}",
        "=" * 70,
        f"Run ID                  : {cp['run_id']}",
        f"Train samples           : {len(cp['train_results'])}",
        f"Train avg (init skill)  : {train_avg:.2f}",
        f"Errors                  : {len(cp['errors'])}  (score 0.0: {n0} | score 0.5: {len(cp['errors']) - n0})",
        f"Batches                 : {len(cp['batches'])}",
        f"Total agent runs        : {cp['runs_done']}",
        f"Total agent time        : {datetime.timedelta(seconds=int(cp['run_seconds']))}",
        "",
        f"Held-out test avg — initial skill : {initial:.2f}",
        f"Held-out test avg — final skill   : {final:.2f}",
        f"Best batch                        : {best['step']} avg={best['test_avg']:.2f}",
        "",
        "batch | error_ids        | train_idx        | test_avg | delta",
    ]
    for s in steps:
        ids = " ".join(map(str, s["error_ids"])) or "initial"
        idx = " ".join(map(str, s["train_indexes"])) or "-"
        delta = "" if s["delta_vs_prev"] is None else f"{s['delta_vs_prev']:+.2f}"
        lines.append(f"{s['step']:>5} | {ids:<16} | {idx:<16} | {s['test_avg']:>8.2f} | {delta}")
    lines.append("=" * 70)
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
    await populate_registry(registry, servers=["emf"])
    meta = MetaAgent(metamodel_file=METAMODEL)

    cp = load_checkpoint()
    if cp is None:
        cp = new_checkpoint()
        print("\nInitializing skills from the megamodel...")
        base_dir = str(Path(".opencode/skills").resolve())
        generated = MegamodelToSkill(registry).generate_all_skills(base_dir=base_dir)
        print(f"Skill files generated: {[p.parent.name for p in generated]}")
    else:
        Path(meta.apply_skill).write_text(cp["skill_apply"])
        Path(meta.get_skill).write_text(cp["skill_get"])
        print("> Resuming — skills restored from checkpoint")

    run_id = cp["run_id"]
    prefix       = f"debug_logs/{run_id}_emf_b4"
    log_file     = f"{prefix}_log.txt"
    errors_file  = f"{prefix}_errors.json"
    changes_file = f"{prefix}_skill_changes.txt"
    results_csv  = f"{prefix}_results.csv"
    results_json = f"{prefix}_results.json"
    summary_file = f"{prefix}_summary.txt"
    skills_dir   = Path(f"{prefix}_skills")
    skills_dir.mkdir(parents=True, exist_ok=True)
    log = lambda line: meta._append_log(log_file, line)
    if not (skills_dir / f"batch_00_{skill_name(meta.apply_skill)}.md").exists():
        save_skill_versions(meta, skills_dir, 0)

    progress = Progress(cp, len(train_dataset), len(test_dataset))
    print(f"MESA EMF batch run — {run_id}")
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
            print(progress.line(f"train {i+1}/{len(train_dataset)} ({100 * (i+1) / len(train_dataset):.0f}%) "
                                f"score={score:.2f} errors so far={len(cp['errors'])}"))
            log(f"COLLECT | train={i+1}/{len(train_dataset)} | score={score:.2f} | "
                f"expected={expected_names(sample)} | actual={[a['api_name'] for a in actual_calls]}"
                + (f" | exception={exc}" if exc else ""))
            Path(errors_file).write_text(json.dumps(cp["errors"], indent=2, ensure_ascii=False))
            save_checkpoint(cp, meta)

        errors = cp["errors"]
        cp["n_errors"] = len(errors)
        cp["batches"] = [[e["error_id"] for e in errors[i:i + BATCH_SIZE]]
                         for i in range(0, len(errors), BATCH_SIZE)]
        for b, ids in enumerate(cp["batches"], start=1):
            for e in errors:
                if e["error_id"] in ids:
                    e["batch"] = b
        Path(errors_file).write_text(json.dumps(errors, indent=2, ensure_ascii=False))
        cp["phase"] = "refine"
        n0 = sum(1 for e in errors if e["score"] == 0.0)
        log(f"COLLECT done | errors={cp['n_errors']} (0.0: {n0} | 0.5: {cp['n_errors'] - n0}) | "
            f"batches={len(cp['batches'])}")
        print(f">>> Phase 1 done — {cp['n_errors']} errors (0.0: {n0} | 0.5: {cp['n_errors'] - n0}) "
              f"→ {len(cp['batches'])} batches of {BATCH_SIZE} → {errors_file}")
        save_checkpoint(cp, meta)
        if STOP_AFTER_COLLECT:
            print(">>> Stopping after Phase 1 — re-run to continue with the refinement batches.")
            return

    # ── PHASE 2 + 3: step 0 (initial skill) then one step per batch of 4 ────
    if cp["phase"] == "refine":
        errors_by_id = {e["error_id"]: e for e in cp["errors"]}
        n_steps = len(cp["batches"]) + 1
        for step in range(cp["current_step"], n_steps):
            batch = [errors_by_id[i] for i in cp["batches"][step - 1]] if step > 0 else []

            # Refine the skill with this batch (only once per step)
            if batch and cp["current_refine_status"] is None:
                print(f"\n── Batch {step}/{n_steps - 1}: errors {[e['error_id'] for e in batch]} "
                      f"(train samples {[e['train_index'] for e in batch]}) ──")
                # One meta-agent call per skill file touched by this batch
                by_skill: dict[str, list[dict]] = {}
                for e in batch:
                    by_skill.setdefault(e["skill_file"], []).append(e)
                statuses = {}
                for skill_file, errs in by_skill.items():
                    payload = meta._build_failure_payload(
                        [{"instruction": e["instruction"], "expected_apis": e["expected_apis"],
                          "actual_calls": e["actual_calls"]} for e in errs],
                        max_examples=len(errs),
                        max_total_instruction_chars=4000,
                    )
                    backup = Path(skill_file).read_text()
                    try:
                        refined = meta.refine_agent_definition_batch(payload, skill_file, backup=backup)
                        status = "unchanged" if refined.strip() == backup.strip() else "rewritten"
                    except Exception as e:
                        Path(skill_file).write_text(backup)
                        status = f"refine_error: {type(e).__name__}: {str(e)[:200]}"
                    statuses[skill_name(skill_file)] = status
                    log_skill_change(changes_file, step, skill_file, errs, backup,
                                     Path(skill_file).read_text(), status)
                    log(f"REFINE | batch={step}/{n_steps - 1} | skill={skill_file} | "
                        f"error_ids={[e['error_id'] for e in errs]} | "
                        f"train_indexes={[e['train_index'] for e in errs]} | status={status}")
                    print(f"    {skill_name(skill_file)} ← {len(errs)} error(s) → {status}")
                cp["current_refine_status"] = statuses
                save_skill_versions(meta, skills_dir, step)
                save_checkpoint(cp, meta)
            elif not batch and not cp["current_test_scores"]:
                print(f"\n── Step 0/{n_steps - 1}: initial megamodel skill on held-out test ──")

            # Evaluate on the held-out test set
            for j in range(len(cp["current_test_scores"]), len(test_dataset)):
                sample = test_dataset[j]
                score, actual_calls, exc = run_sample(meta, sample, progress)
                cp["current_test_scores"].append(score)
                print(progress.line(f"batch {step}/{n_steps - 1} ({100 * step / max(n_steps - 1, 1):.0f}% of batches) "
                                    f"test {j+1}/{len(test_dataset)} ({100 * (j+1) / len(test_dataset):.0f}%) "
                                    f"score={score:.2f}"))
                log(f"TEST | batch={step} | test={j+1}/{len(test_dataset)} | score={score:.2f} | "
                    f"expected={expected_names(sample)} | actual={[a['api_name'] for a in actual_calls]}"
                    + (f" | exception={exc}" if exc else ""))
                save_checkpoint(cp, meta)

            scores = cp["current_test_scores"]
            test_avg = sum(scores) / len(scores)
            prev_avg = cp["steps"][-1]["test_avg"] if cp["steps"] else None
            init_avg = cp["steps"][0]["test_avg"] if cp["steps"] else test_avg
            cp["steps"].append({
                "step": step,
                "error_ids": [e["error_id"] for e in batch],
                "train_indexes": [e["train_index"] for e in batch],
                "error_scores": [e["score"] for e in batch],
                "refine_status": cp["current_refine_status"] if batch else "initial",
                "test_avg": test_avg,
                "delta_vs_prev": None if prev_avg is None else round(test_avg - prev_avg, 4),
                "delta_vs_initial": round(test_avg - init_avg, 4),
                "test_scores": scores,
            })
            log(f"BATCH {step} DONE | test_avg={test_avg:.2f}"
                + ("" if prev_avg is None else f" | delta_vs_prev={test_avg - prev_avg:+.2f}"))
            print(f">>> Batch {step} test avg = {test_avg:.2f}"
                  + ("" if prev_avg is None else f" ({test_avg - prev_avg:+.2f} vs previous)"))

            cp["current_step"] = step + 1
            cp["current_test_scores"] = []
            cp["current_refine_status"] = None
            write_results(cp, results_csv, results_json)
            save_checkpoint(cp, meta)

        cp["phase"] = "done"
        save_checkpoint(cp, meta)

    # ── Done ────────────────────────────────────────────────────────────────
    if cp["phase"] == "done":
        write_results(cp, results_csv, results_json)
        save_summary(cp, summary_file)
        print(f"\n>>> All done. Results: {results_csv}")
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
