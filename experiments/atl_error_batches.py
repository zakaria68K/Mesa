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
