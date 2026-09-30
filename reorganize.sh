#!/usr/bin/env bash
# Reorganize the ATL experiments. Run from the repo root:  bash reorganize.sh
# Only mkdir / mv / cat. Nothing is deleted (old files go to archive/). Git is not touched.
set -e
[ -f main.py ] || { echo "Run this from the repo root."; exit 1; }
[ -e debug_logs/oh_checkpoint.json ] && { echo "An experiment is still running. Finish it first."; exit 1; }

mkdir -p experiments plots archive/old_scripts archive/debug_logs \
         outputs/atl/figures \
         outputs/atl/online_train/run_20260922_153137 \
         outputs/atl/error_batches/run_20260929_153035/phase1 \
         outputs/atl/online_heldout/run_20260930_011825

# ── 1. Old online run (score averaged on the train set) ─────────────────────
R=outputs/atl/online_train/run_20260922_153137
mv debug_logs/20260922_153137_online_specialization.txt  $R/log.txt
mv debug_logs/20260922_153137_test.txt                   $R/test.txt
mv debug_logs/20260922_153137_atl_summary.txt            $R/summary.txt

# ── 2. Error batches (experiment A) ─────────────────────────────────────────
R=outputs/atl/error_batches/run_20260929_153035
mv debug_logs/20260929_153035_b4_summary.txt             $R/summary.txt
mv debug_logs/20260929_153035_b4_results.csv             $R/results.csv
mv debug_logs/20260929_153035_b4_results.json            $R/results.json
mv debug_logs/20260929_153035_b4_skill_changes.txt       $R/skill_changes.txt
mv debug_logs/20260929_153035_b4_errors.json             $R/errors.json
mv debug_logs/20260929_153035_b4_log.txt                 $R/log.txt
mv debug_logs/20260929_153035_b4_checkpoint_final.json   $R/checkpoint_final.json
mv debug_logs/20260929_153035_b4_skills                  $R/skills
mv debug_logs/20260929_153035_errors.json                $R/phase1/errors.json
mv debug_logs/20260929_153035_eb_log.txt                 $R/phase1/log.txt
mv debug_logs/eb_checkpoint.json                         $R/phase1/checkpoint.json
[ -d debug_logs/20260929_153035_eb_skills ] && mv debug_logs/20260929_153035_eb_skills $R/phase1/skills

# ── 3. Online held-out (experiment B) ───────────────────────────────────────
R=outputs/atl/online_heldout/run_20260930_011825
mv debug_logs/20260930_011825_oh_summary.txt             $R/summary.txt
mv debug_logs/20260930_011825_oh_steps.csv               $R/steps.csv
mv debug_logs/20260930_011825_oh_steps.json              $R/steps.json
mv debug_logs/20260930_011825_oh_items.csv               $R/items.csv
mv debug_logs/20260930_011825_oh_train_order.json        $R/train_order.json
mv debug_logs/20260930_011825_oh_skill_changes.txt       $R/skill_changes.txt
mv debug_logs/20260930_011825_oh_log.txt                 $R/log.txt
mv debug_logs/20260930_011825_oh_checkpoint_final.json   $R/checkpoint_final.json
mv debug_logs/20260930_011825_oh_skills                  $R/skills

# ── 4. Figures (all in one folder) ──────────────────────────────────────────
F=outputs/atl/figures
for e in png pdf; do
  mv debug_logs/fig_online_specialization.$e         $F/online_train.$e
  mv debug_logs/fig_atl_online_vs_batch_log.$e       $F/online_train_vs_batch.$e
  mv debug_logs/fig_atl_batch_vs_error_batches.$e    $F/error_batches_vs_batch.$e
  mv debug_logs/fig_atl_online_heldout.$e            $F/online_heldout.$e
done

# ── 5. Everything else left in debug_logs/ -> archive ───────────────────────
mv debug_logs/* archive/debug_logs/ 2>/dev/null || true
rmdir debug_logs 2>/dev/null || true
[ -d debug_logs_backup ] && mv debug_logs_backup archive/debug_logs_backup

# ── 6. Scripts: old versions -> archive, new versions (updated paths) written below
for f in error_by_error.py online_heldout.py visualize_error_batches.py \
         visualize_online_heldout.py visualize_online.py visualize_comparison_atl.py; do
  [ -f "$f" ] && mv "$f" archive/old_scripts/
done

cat > experiments/atl_error_batches.py <<'EOF_FILE'
"""
Error-by-error specialization (ATL) — batches of 4 errors.

Phase 1 — Collect : DISABLED (commented out below). The errors and the initial
                    megamodel skills are loaded from the Phase 1 checkpoint
                    (PHASE1_CHECKPOINT), which is only read, never modified.
Phase 2 — Step 0  : evaluate the initial skill on the 20 held-out test samples.
Phase 3 — Refine  : split the errors, in order, into batches of 4. For each batch:
                    give the 4 errors together to the meta-agent, rewrite the skill
                    (cumulatively), evaluate on the 20 held-out test samples, log
                    the average. Then the next 4, and so on.

Outputs (outputs/atl/error_batches/run_<run_id>/):
  summary.txt              final summary
  results.csv / .json      one row per batch: errors -> held-out test avg (+ per-sample scores)
  skill_changes.txt        every skill change: batch, errors, diff, full new text
  skills/batch_XX_*.md     every skill version (batch_00 = initial megamodel skill)
  errors.json              the error list used, with batch numbers
  log.txt                  full detailed log

Usage (from anywhere): python experiments/atl_error_batches.py
Resumable: re-run it and it continues from outputs/atl/error_batches/checkpoint.json.
"""
import asyncio
import csv
import datetime
import difflib
import json
import time
import os
import sys
import traceback
from pathlib import Path

# Run from the repo root, whatever the current directory is
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()
from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from modeling_agents.meta_agent import MetaAgent
sys.path.insert(0, '.opencode/skills')
from megamodel_toskill import MegamodelToSkill
from main import DATASET_PATH, stratified_split, load_specialization_dataset

OUT_DIR           = Path("outputs/atl/error_batches")
PHASE1_CHECKPOINT = OUT_DIR / "run_20260929_153035/phase1/checkpoint.json"  # read-only: errors + initial skills
CHECKPOINT        = OUT_DIR / "checkpoint.json"   # checkpoint of the run in progress
BATCH_SIZE  = 4
TEST_SIZE   = 20
MAX_RETRIES = 1   # extra attempts when opencode itself crashes


# ── Progress ─────────────────────────────────────────────────────────────────
class Progress:
    """Overall progress in agent runs, with ETA based on the observed avg run time."""

    def __init__(self, cp: dict, n_test: int):
        self.cp = cp
        self.n_test = n_test

    def total(self) -> int:
        return (len(self.cp["batches"]) + 1) * self.n_test

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
        return f"[{bar}] {pct:5.1f}% | {done}/{total} runs | ETA {eta} | {label}"


# ── Checkpoint ───────────────────────────────────────────────────────────────
def save_checkpoint(cp: dict, meta: MetaAgent) -> None:
    cp["skill_apply"] = Path(meta.apply_skill).read_text()
    cp["skill_get"] = Path(meta.get_skill).read_text()
    Path(CHECKPOINT).write_text(json.dumps(cp, indent=2, ensure_ascii=False))


def new_checkpoint_from_phase1(registry) -> dict:
    """Build this run's state from the Phase 1 checkpoint (errors + initial skills)."""
    if not Path(PHASE1_CHECKPOINT).exists():
        raise FileNotFoundError(f"{PHASE1_CHECKPOINT} not found — Phase 1 results are required.")
    src = json.loads(Path(PHASE1_CHECKPOINT).read_text())
    errors = src["errors"]
    n_train_done = len(src.get("train_results", []))
    print(f">>> Loaded Phase 1 from {PHASE1_CHECKPOINT}: run={src['run_id']} | "
          f"train samples run={n_train_done} | errors={len(errors)}")
    if src.get("phase") == "collect":
        print(f"    ! Phase 1 was interrupted — using the errors from the first {n_train_done} samples")

    # Initial skills: those saved by Phase 1 (untouched megamodel skills), else regenerate
    if src.get("skill_apply") and src.get("skill_get"):
        skill_apply, skill_get = src["skill_apply"], src["skill_get"]
    else:
        MegamodelToSkill(registry).generate_patterns()
        skill_apply = Path(".opencode/skills/mde-apply/SKILL.md").read_text()
        skill_get = Path(".opencode/skills/mde-get/SKILL.md").read_text()

    batches = [
        [e["error_id"] for e in errors[i:i + BATCH_SIZE]]
        for i in range(0, len(errors), BATCH_SIZE)
    ]
    for b, ids in enumerate(batches, start=1):
        for e in errors:
            if e["error_id"] in ids:
                e["batch"] = b

    # Reuse a finished step 0 from Phase 1 if there is one (same initial skill, same test set)
    step0 = next((s for s in src.get("steps", []) if s.get("step") == 0), None)

    return {
        "run_id": src["run_id"],
        "phase1_train_samples": n_train_done,
        "errors": errors,
        "batches": batches,             # list of lists of error_ids
        "steps": [],                    # finished steps (0 = initial skill)
        "current_step": 0,
        "current_test_scores": list(step0["test_scores"]) if step0 else [],
        "current_refine_status": None,
        "runs_done": 0,
        "run_seconds": 0.0,
        "skill_apply": skill_apply,
        "skill_get": skill_get,
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
    return Path(skill_file).parent.name   # mde-apply / mde-get


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
    lines = [
        "=" * 70,
        f"ATL ERROR-BY-ERROR SPECIALIZATION SUMMARY — batches of {BATCH_SIZE}",
        "=" * 70,
        f"Run ID                  : {cp['run_id']}",
        f"Phase 1 train samples   : {cp['phase1_train_samples']}",
        f"Errors                  : {len(cp['errors'])}  (score 0.0: {n0} | score 0.5: {len(cp['errors']) - n0})",
        f"Batches                 : {len(cp['batches'])}",
        f"Agent runs (this run)   : {cp['runs_done']}",
        f"Agent time (this run)   : {datetime.timedelta(seconds=int(cp['run_seconds']))}",
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
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    full_dataset = load_specialization_dataset(DATASET_PATH)
    train_dataset, test_dataset = stratified_split(full_dataset, test_size=TEST_SIZE)
    print(f"Loaded {len(full_dataset)} samples | Train: {len(train_dataset)} | Test (held-out): {len(test_dataset)}")

    registry = MegamodelRegistry()
    await populate_registry(registry)
    meta = MetaAgent()

    if Path(CHECKPOINT).exists():
        cp = json.loads(Path(CHECKPOINT).read_text())
        print(f">>> Resuming batch run: run={cp['run_id']} | step={cp['current_step']}")
    else:
        cp = new_checkpoint_from_phase1(registry)
        done = OUT_DIR / f"run_{cp['run_id']}" / "summary.txt"
        if done.exists():
            raise SystemExit(f"{done} already exists: this run is finished. "
                             f"Move that folder away to redo it.")
    # Restore the skills this run is at (initial megamodel skills on a fresh start)
    Path(meta.apply_skill).write_text(cp["skill_apply"])
    Path(meta.get_skill).write_text(cp["skill_get"])

    run_id = cp["run_id"]
    run_dir      = OUT_DIR / f"run_{run_id}"
    log_file     = run_dir / "log.txt"
    errors_file  = run_dir / "errors.json"
    changes_file = run_dir / "skill_changes.txt"
    results_csv  = run_dir / "results.csv"
    results_json = run_dir / "results.json"
    summary_file = run_dir / "summary.txt"
    skills_dir   = run_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    log = lambda line: meta._append_log(log_file, line)

    Path(errors_file).write_text(json.dumps(cp["errors"], indent=2, ensure_ascii=False))
    errors_by_id = {e["error_id"]: e for e in cp["errors"]}
    n_steps = len(cp["batches"]) + 1
    if cp["current_step"] == 0 and not (skills_dir / "batch_00_mde-apply.md").exists():
        save_skill_versions(meta, skills_dir, 0)

    progress = Progress(cp, len(test_dataset))
    print(f"MESA ATL batch run — {run_id} | {len(cp['errors'])} errors → "
          f"{len(cp['batches'])} batches of {BATCH_SIZE}")
    log(f"=== run {run_id} (re)started at {datetime.datetime.now().isoformat(timespec='seconds')} "
        f"| step={cp['current_step']}/{n_steps - 1} ===")

    # ── PHASE 1: collect errors with the initial skill — DISABLED ───────────
    # Errors are loaded from the Phase 1 checkpoint (see new_checkpoint_from_phase1).
    #
    # if cp["phase"] == "collect":
    #     for i in range(len(cp["train_results"]), len(train_dataset)):
    #         sample = train_dataset[i]
    #         score, actual_calls, exc = run_sample(meta, sample, progress)
    #         entry = {"train_index": i + 1, "instruction": sample["instruction"],
    #                  "level": sample.get("level"),
    #                  "skill_file": meta._skill_for(sample["relevant_apis"]),
    #                  "score": score, "expected_apis": sample["relevant_apis"],
    #                  "actual_calls": actual_calls, "agent_exception": exc}
    #         cp["train_results"].append(entry)
    #         if score < 1.0:
    #             cp["errors"].append({"error_id": len(cp["errors"]) + 1, **entry})
    #         save_checkpoint(cp, meta)

    # ── PHASE 2 + 3: step 0 (initial skill) then one step per batch of 4 ────
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
        elif not batch:
            print(f"\n── Step 0/{n_steps - 1}: {len(cp['current_test_scores'])}/{len(test_dataset)} "
                  f"test scores reused from Phase 1 ──")

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

    # ── Done ────────────────────────────────────────────────────────────────
    write_results(cp, results_csv, results_json)
    save_summary(cp, summary_file)
    print(f"\n>>> All done. Results: {results_csv}")
    Path(CHECKPOINT).rename(run_dir / "checkpoint_final.json")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n>>> Interrupted — re-run the script to resume from the checkpoint.")
    except Exception:
        traceback.print_exc()
        print("\n>>> Crashed — re-run the script to resume from the checkpoint.")
        sys.exit(1)
EOF_FILE

cat > experiments/atl_online_heldout.py <<'EOF_FILE'
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

Outputs (outputs/atl/online_heldout/run_<run_id>/):
  summary.txt              final summary
  steps.csv / .json        one row per held-out evaluation (step 0 + one per rewrite)
  items.csv                one row per train sample: score, rewrite, held-out avg after it
  train_order.json         the shuffled train order (with original index + level)
  skill_changes.txt        every skill change: triggering sample, diff, full new text
  skills/step_XX_*.md      every skill version (step_00 = initial megamodel skill)
  log.txt                  full detailed log

Usage (from anywhere): python experiments/atl_online_heldout.py
Resumable: re-run it and it continues from outputs/atl/online_heldout/checkpoint.json.
"""
import asyncio
import csv
import datetime
import difflib
import json
import random
import time
import os
import sys
import traceback
from pathlib import Path

# Run from the repo root, whatever the current directory is
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()
from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from modeling_agents.meta_agent import MetaAgent
sys.path.insert(0, '.opencode/skills')
from megamodel_toskill import MegamodelToSkill
from main import DATASET_PATH, stratified_split, load_specialization_dataset

RUN_ID        = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR       = Path("outputs/atl/online_heldout")
CHECKPOINT    = OUT_DIR / "checkpoint.json"   # checkpoint of the run in progress
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


def write_results(cp: dict, run_dir: Path) -> None:
    item_fields = ["pos", "train_index", "level", "skill_file", "score", "refine_status",
                   "rewritten", "step", "heldout_avg", "instruction"]
    with open(run_dir / "items.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=item_fields)
        w.writeheader()
        for it in cp["items"]:
            w.writerow({k: it.get(k) for k in item_fields})
    step_fields = ["step", "after_pos", "train_index", "level", "skill_file", "test_avg",
                   "delta_vs_prev", "delta_vs_initial"]
    with open(run_dir / "steps.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=step_fields)
        w.writeheader()
        for s in cp["steps"]:
            w.writerow({k: s.get(k) for k in step_fields})
    (run_dir / "steps.json").write_text(json.dumps(cp["steps"], indent=2, ensure_ascii=False))


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
    OUT_DIR.mkdir(parents=True, exist_ok=True)

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
    run_dir      = OUT_DIR / f"run_{run_id}"
    log_file     = run_dir / "log.txt"
    changes_file = run_dir / "skill_changes.txt"
    summary_file = run_dir / "summary.txt"
    skills_dir   = run_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    log = lambda line: meta._append_log(log_file, line)

    order = cp["train_order"]
    (run_dir / "train_order.json").write_text(json.dumps(
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
        write_results(cp, run_dir)
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
            write_results(cp, run_dir)
            save_checkpoint(cp, meta)

        cp["phase"] = "done"
        save_checkpoint(cp, meta)

    # ── Done ────────────────────────────────────────────────────────────────
    if cp["phase"] == "done":
        write_results(cp, run_dir)
        save_summary(cp, summary_file)
        print(f"\n>>> All done. Results: {run_dir}/summary.txt")
        Path(CHECKPOINT).rename(run_dir / "checkpoint_final.json")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n>>> Interrupted — re-run the script to resume from the checkpoint.")
    except Exception:
        traceback.print_exc()
        print("\n>>> Crashed — re-run the script to resume from the checkpoint.")
        sys.exit(1)
EOF_FILE

cat > plots/plot_atl_error_batches.py <<'EOF_FILE'
"""
ATL :batch specialization (5 runs, 8 iterations) on a training-items axis,
with a zoom on items 0–80 showing the error-batch specialization (batches of 4).

Batch runs    : results/run_*/<id>_specialization.txt   (iteration k -> k * 80 items)
Error batches : outputs/atl/error_batches/run_<run_id>/results.json  (batch b -> train index of its last error)

Usage : python plots/plot_atl_error_batches.py
Output: outputs/atl/figures/error_batches_vs_batch.png / .pdf
"""
import json
import os
import re
import statistics
from pathlib import Path

# Run from the repo root, whatever the current directory is
os.chdir(Path(__file__).resolve().parents[1])
FIG_DIR = Path("outputs/atl/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

N_TRAIN = 80

# Fallback = numbers from the 20260929_153035 run, used if the results file is missing
FALLBACK_STEPS = [
    {"step": 0, "train_indexes": [],               "test_avg": 0.675},
    {"step": 1, "train_indexes": [1, 5, 21, 31],   "test_avg": 0.70},
    {"step": 2, "train_indexes": [33, 36, 37, 39], "test_avg": 0.75},
    {"step": 3, "train_indexes": [40, 41, 42, 45], "test_avg": 0.72},
    {"step": 4, "train_indexes": [48, 50, 53, 56], "test_avg": 0.725},
    {"step": 5, "train_indexes": [57, 61, 62, 63], "test_avg": 0.725},
    {"step": 6, "train_indexes": [64, 66, 67, 68], "test_avg": 0.775},
    {"step": 7, "train_indexes": [69, 70, 71, 72], "test_avg": 0.725},
    {"step": 8, "train_indexes": [73, 74, 75, 76], "test_avg": 0.70},
    {"step": 9, "train_indexes": [77, 78, 79],     "test_avg": 0.725},
]

RED_RUNS = ["#fcae91", "#fb6a4a", "#de2d26", "#a50f15", "#fdd0bc"]
RED_MEAN = "#a50f15"
BLUE     = "#2166ac"
INK      = "#333333"
MUTED    = "#8a8a8a"


def parse_batch_log(path: Path) -> dict[int, float]:
    iters = {}
    for line in path.read_text().splitlines():
        m = re.search(r"Iteration (\d+) summary \| avg_score=(\d+\.\d+)", line)
        if m:
            iters[int(m.group(1))] = float(m.group(2))
    return iters


def load_batch_runs() -> list[dict[int, float]]:
    logs = sorted(p for p in Path("results").glob("run_*/*specialization*.txt")
                  if "emf" not in p.name and "online" not in p.name)
    runs = [r for r in (parse_batch_log(p) for p in logs) if r]
    print(f"Batch runs: {len(runs)} ({', '.join(str(p) for p in logs)})")
    return runs


def load_error_batches() -> list[dict]:
    files = sorted(Path("outputs/atl/error_batches").glob("run_*/results.json"))
    if files:
        print(f"Error batches: {files[-1]}")
        return json.loads(files[-1].read_text())
    print("Error batches: results file not found ,using the 20260929_153035 numbers")
    return FALLBACK_STEPS


def style(ax):
    ax.grid(alpha=0.3, linestyle="--", linewidth=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors=INK, labelsize=9)


runs = load_batch_runs()
steps = load_error_batches()

# ── Batch curves: iteration k -> k * 80 training items ───────────────────────
iters = sorted({k for r in runs for k in r})
bx = np.array([k * N_TRAIN for k in iters])
mean = np.array([statistics.mean(r[k] for r in runs if k in r) for k in iters])
std = np.array([statistics.stdev([r[k] for r in runs if k in r]) if len(runs) > 1 else 0 for k in iters])

# ── Error batches: batch b -> train index of its last error ──────────────────
ex = np.array([max(s["train_indexes"]) if s["train_indexes"] else 0 for s in steps])
ey = np.array([s["test_avg"] for s in steps])

fig, ax = plt.subplots(figsize=(11, 5))

for i, r in enumerate(runs):
    ks = sorted(r)
    ax.plot([k * N_TRAIN for k in ks], [r[k] for k in ks],
            color=RED_RUNS[i % len(RED_RUNS)], linewidth=1.0, alpha=0.7, label=f"Run {i + 1}")
ax.fill_between(bx, mean - std, mean + std, color=RED_MEAN, alpha=0.15, linewidth=0, label="±1 std")
ax.plot(bx, mean, color=RED_MEAN, linewidth=2.5, marker="o", markersize=5, label="Batch mean (train set)",
        zorder=4)
ax.plot(ex, ey, color=BLUE, linewidth=2, marker="o", markersize=4, zorder=5,
        label="Error batches of 4 (held-out test)")

ax.set_xlim(-10, bx[-1] + 20)
ax.set_xticks(bx)
ax.set_ylim(0, 1.05)
ax.set_xlabel("Training items processed", fontsize=11, color=INK)
ax.set_ylabel("Avg score", fontsize=11, color=INK)
ax.set_title("ATL (model transformations): batch iterations vs. error batches", fontsize=12, color=INK)
style(ax)

# ── Zoom on items 0–80 ───────────────────────────────────────────────────────
axin = ax.inset_axes([0.36, 0.17, 0.61, 0.38])
for x in ex[1:]:
    axin.axvline(x, color=MUTED, linestyle=":", linewidth=0.8, zorder=1)
axin.plot(ex, ey, color=BLUE, linewidth=2, marker="o", markersize=7, zorder=5,
          markeredgecolor="white", markeredgewidth=1.5)
for s, x, y in zip(steps, ex, ey):
    label = "init" if s["step"] == 0 else f"B{s['step']}"
    axin.annotate(label, (x, y), textcoords="offset points", xytext=(0, 9),
                  ha="center", fontsize=8, color=INK)
axin.set_xlim(-3, N_TRAIN + 3)
axin.set_xticks(range(0, N_TRAIN + 1, 10))
lo, hi = ey.min(), ey.max()
axin.set_ylim(lo - 0.06, hi + 0.07)
axin.set_xlabel("Training item index (last error in the batch)", fontsize=8, color=INK)
axin.set_ylabel("Held-out avg", fontsize=8, color=INK)
axin.set_facecolor("white")
style(axin)
axin.tick_params(labelsize=8)
ax.indicate_inset_zoom(axin, edgecolor=MUTED, alpha=0.8)

ax.legend(fontsize=8, loc="upper left", ncol=2, frameon=False)

plt.tight_layout()
out = FIG_DIR / "error_batches_vs_batch.png"
plt.savefig(out, dpi=200, bbox_inches="tight")
plt.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
print(f"Saved: {out} (+ .pdf)")
EOF_FILE

cat > plots/plot_atl_online_heldout.py <<'EOF_FILE'
"""
Plot the ATL online specialization evaluated on the held-out set (online_heldout.py).

Usage:
    python plots/plot_atl_online_heldout.py                   # latest run
    python plots/plot_atl_online_heldout.py 20260930_011825

Reads   outputs/atl/online_heldout/run_<run_id>/steps.json  (step 0 + one entry per skill rewrite)
        outputs/atl/online_heldout/run_<run_id>/items.csv   (one row per train sample, optional)
Writes  outputs/atl/figures/online_heldout.png / .pdf

What the figure shows (x = train sample, in the online order):
  - blue step curve : held-out avg (20 samples) of the skill in use;
                      it only changes when the skill is rewritten
  - red dotted lines: skill rewrites
  - grey dashed line: cumulative train avg (the old "prequential" measure)
  - dash-dot line   : held-out avg of the initial megamodel skill
"""
import csv
import json
import os
import sys
from pathlib import Path

# Run from the repo root, whatever the current directory is
os.chdir(Path(__file__).resolve().parents[1])
FIG_DIR = Path("outputs/atl/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RUNS_DIR = Path("outputs/atl/online_heldout")
OUT      = FIG_DIR / "online_heldout.png"
N_TRAIN = 80

BLUE, RED, GREY, INK = "#2166ac", "#de2d26", "#8a8a8a", "#333333"


def load_run(run_id: str | None):
    """Return (run_id, steps, items). items is None if the items CSV is missing."""
    if run_id is None:
        run_id = sorted(RUNS_DIR.glob("run_*/steps.json"))[-1].parent.name.removeprefix("run_")
    run_dir = RUNS_DIR / f"run_{run_id}"
    steps = json.loads((run_dir / "steps.json").read_text())
    items_file = run_dir / "items.csv"
    items = list(csv.DictReader(items_file.open(encoding="utf-8"))) if items_file.exists() else None
    return run_id, steps, items


def plot(run_id: str, steps: list[dict], items: list[dict] | None) -> None:
    initial = steps[0]["test_avg"]
    final = steps[-1]["test_avg"]
    best = max(steps, key=lambda s: s["test_avg"])

    # Held-out curve: each step holds its value until the next rewrite, then until the last sample
    xs = [s["after_pos"] for s in steps] + [N_TRAIN]
    ys = [s["test_avg"] for s in steps] + [final]

    fig, ax = plt.subplots(figsize=(9, 4.5))

    # Skill rewrites
    for i, s in enumerate(steps[1:]):
        ax.axvline(s["after_pos"], color=RED, linestyle=":", linewidth=0.9, alpha=0.7,
                   label="Skill rewritten" if i == 0 else None)

    # Old measure: cumulative train avg (only if the per-sample CSV is available)
    if items:
        scores = [float(it["score"]) for it in items]
        cum = [sum(scores[:i]) / i for i in range(1, len(scores) + 1)]
        ax.plot(range(1, len(cum) + 1), cum, color=GREY, linestyle="--", linewidth=1.2,
                label=f"Cumulative avg (train) = {cum[-1]:.2f}")

    # Held-out avg of the current skill
    ax.step(xs, ys, where="post", color=BLUE, linewidth=2.2,
            label=f"Held-out avg (20 samples) — final = {final:.2f}")
    ax.plot(xs[:-1], ys[:-1], "o", color=BLUE, markersize=4.5,
            markeredgecolor="white", markeredgewidth=1)
    ax.axhline(initial, color=BLUE, linestyle="-.", linewidth=0.9, alpha=0.6,
               label=f"Initial skill (held-out) = {initial:.2f}")

    # Best step
    ax.annotate(f"best {best['test_avg']:.2f}", (best["after_pos"], best["test_avg"]),
                textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color=INK)

    ax.set_xlim(0, N_TRAIN + 1)
    ax.set_ylim(0, 1.05)
    ax.set_xticks(range(0, N_TRAIN + 1, 10))
    ax.set_xlabel("Training sample index (online order)", color=INK)
    ax.set_ylabel("Score", color=INK)
    ax.set_title("ATL (model transformations): online specialization, held-out evaluation", color=INK)
    ax.grid(alpha=0.3, linestyle="--", linewidth=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(fontsize=8, loc="lower left")

    fig.tight_layout()
    fig.savefig(OUT, dpi=200, bbox_inches="tight")
    fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight")
    print(f"Run {run_id}: {len(steps) - 1} rewrites, held-out {initial:.2f} -> {final:.2f} "
          f"(best {best['test_avg']:.2f} after sample {best['after_pos']})")
    print(f"Saved: {OUT} (+ .pdf)")


if __name__ == "__main__":
    plot(*load_run(sys.argv[1] if len(sys.argv) > 1 else None))
EOF_FILE

cat > plots/plot_atl_online_train.py <<'EOF_FILE'
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
EOF_FILE

cat > plots/plot_atl_online_train_vs_batch.py <<'EOF_FILE'
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
EOF_FILE

cat > outputs/README.md <<'EOF_FILE'
# Experiment outputs

Everything is under `outputs/atl/`. Each run has its own folder, `run_<date>_<time>/`.
Start with `summary.txt`.

| Folder | Experiment | Script |
|---|---|---|
| `online_train/` | old online specialization, score averaged on the train set | `main.py` (ONLINE = True) |
| `error_batches/` | errors of the initial skill, fixed 4 at a time, scored on the 20 held-out items | `experiments/atl_error_batches.py` |
| `online_heldout/` | online specialization (1 error at a time), scored on the 20 held-out items | `experiments/atl_online_heldout.py` |
| `figures/` | all figures, for the paper | `plots/plot_atl_*.py` |

The batch-mode runs (5 runs × 8 iterations) are in `results/run_1` … `results/run_5`.

## Files in a run folder

| File | Contents |
|---|---|
| `summary.txt` | final table: read this first |
| `results.csv` / `steps.csv` | one row per skill version with its held-out average (used by the plots) |
| `items.csv` | (online_heldout) one row per train item |
| `skill_changes.txt` | each skill rewrite: the errors given, the diff, the new skill |
| `skills/` | every skill version |
| `errors.json` | (error_batches) the errors used, with their batch |
| `phase1/` | (error_batches) collection of the errors with the untouched skill |
| `log.txt` | every agent run, for debugging |
| `checkpoint_final.json` | full final state (archive) |

A run in progress keeps its state in `<experiment>/checkpoint.json`.
Stop with Ctrl+C and run the same script again to resume.

## Commands (from anywhere)

    python experiments/atl_error_batches.py
    python experiments/atl_online_heldout.py
    python plots/plot_atl_error_batches.py
    python plots/plot_atl_online_heldout.py [run_id]
    python plots/plot_atl_online_train.py
    python plots/plot_atl_online_train_vs_batch.py
EOF_FILE

echo "Done. Start with outputs/README.md"
