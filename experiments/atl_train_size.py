"""
Train-size experiment (ATL): how many train samples are needed before ONE skill rewrite?

For each N in TRAIN_SIZES (each N starts from the initial megamodel skill):
  1. draw N train samples at random from the 80 (independent draw for each N and each seed);
  2. collect their errors with the initial skill;
  3. categorize the errors exactly like batch mode (MetaAgent._build_failure_payload:
     grouped by pattern = expected tools vs called tools, sorted by frequency) and rewrite
     the skill ONCE with them (one meta-agent call per skill file);
  4. evaluate the rewritten skill on the 20 held-out samples. Stop.

Reuse (REUSE_PHASE1 = True): Phase 1 of the error-batches experiment already ran the 80
train samples with the initial megamodel skill; those results are reused, so only the
rewrites and their held-out evaluations are run. Set REUSE_PHASE1 = False to run the
train samples again. The initial skill itself is not evaluated (no N=0 point).

Outputs (outputs/atl/train_size/run_<run_id>/):
  summary.txt              final table: N -> errors used -> held-out avg
  results.csv / .json      same, + per-test-sample scores
  skill_changes.txt        each rewrite: N, errors given, diff, full new text
  skills/N<N>_*.md         the rewritten skill for each N (N0 = initial megamodel skill)
  log.txt                  full detailed log

Usage (from anywhere):
    python experiments/atl_train_size.py            # one run, seed 2026
    python experiments/atl_train_size.py 3          # one run, seed 3
    for s in 1 2 3 4 5; do python experiments/atl_train_size.py $s; done   # 5 runs, N = 20, 40, 60
    for s in 1 2 3 4 5; do python experiments/atl_train_size.py $s 80; done   # 5 runs, N = 80 only
The optional 2nd argument chooses the N values (e.g. "80" or "20,40"); those runs go in
their own folders (run_<date>_seed<seed>_N80/) and never mix with the default ones.
Each seed = a different random selection of the N samples, in its own folder
run_<date>_seed<seed>/. Resumable per seed (outputs/atl/train_size/checkpoint_seed<seed>.json);
a seed that is already finished is skipped.
"""
import asyncio
import csv
import datetime
import difflib
import json
import os
import random
import sys
import time
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

RUN_ID       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR      = Path("outputs/atl/train_size")
TRAIN_SEED   = int(sys.argv[1]) if len(sys.argv) > 1 else 2026   # seed of the random selection
DEFAULT_SIZES = [20, 40, 60]
TRAIN_SIZES  = ([int(n) for n in sys.argv[2].split(",")] if len(sys.argv) > 2 else DEFAULT_SIZES)
TAG          = "" if TRAIN_SIZES == DEFAULT_SIZES else "_N" + "-".join(map(str, TRAIN_SIZES))
CHECKPOINT   = OUT_DIR / f"checkpoint_seed{TRAIN_SEED}{TAG}.json"   # checkpoint of this run
TEST_SIZE    = 20
MAX_RETRIES  = 1                             # extra attempts when opencode itself crashes

# Reuse of the error-batches experiment (same initial skill, same train and held-out sets)
REUSE_PHASE1  = True
PHASE1_RUN    = Path("outputs/atl/error_batches/run_20260929_153035")
PHASE1_CP     = PHASE1_RUN / "phase1/checkpoint.json"   # 80 train results + initial skills


# ── Helpers ──────────────────────────────────────────────────────────────────
class Progress:
    def __init__(self, cp: dict, total: int):
        self.cp, self.total = cp, total

    def tick(self, seconds: float) -> None:
        self.cp["runs_done"] += 1
        self.cp["run_seconds"] += seconds

    def line(self, label: str) -> str:
        done = self.cp["runs_done"]
        pct = 100 * done / self.total
        avg = self.cp["run_seconds"] / done if done else 0
        eta = datetime.timedelta(seconds=int(avg * max(self.total - done, 0)))
        bar = "#" * int(pct // 5) + "-" * (20 - int(pct // 5))
        return f"[{bar}] {pct:5.1f}% | {done}/{self.total} runs | ETA {eta} | {label}"


def run_sample(meta: MetaAgent, sample: dict, progress: Progress):
    """Run one sample through the agent and score it. Returns (score, actual_calls, exception)."""
    skill_file = meta._skill_for(sample["relevant_apis"])
    start, error, calls = time.time(), None, []
    for attempt in range(MAX_RETRIES + 1):
        try:
            _, calls = meta.agent.run(sample["instruction"], skill_file)
            error = None
            break
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)[:300]}"
            print(f"    ! agent exception (attempt {attempt + 1}): {error}")
    progress.tick(time.time() - start)
    return meta.evaluate(calls, sample["relevant_apis"]), calls, error


def names(calls: list[dict]) -> list[str]:
    return [c["api_name"] for c in calls]


def skill_name(skill_file: str) -> str:
    return Path(skill_file).parent.name   # mde-apply / mde-get


def save_checkpoint(cp: dict) -> None:
    CHECKPOINT.write_text(json.dumps(cp, indent=2, ensure_ascii=False))


def select_samples(n_train: int, n: int) -> list[int]:
    """Indices (in the train split) of N train samples drawn at random (independent for each N)."""
    return random.Random(f"{TRAIN_SEED}-{n}").sample(range(n_train), n)


def set_initial_skills(meta: MetaAgent, cp: dict) -> None:
    Path(meta.apply_skill).write_text(cp["initial_apply"])
    Path(meta.get_skill).write_text(cp["initial_get"])


def refine_once(meta, errors: list[dict], n: int, changes_file: Path, log) -> tuple[dict, dict]:
    """Rewrite the (initial) skill with all the errors, one call per skill file, errors
    categorized like batch mode. Returns ({skill: status}, {skill: error categories})."""
    by_skill: dict[str, list[dict]] = {}
    for e in errors:
        by_skill.setdefault(e["skill_file"], []).append(e)
    statuses, categories = {}, {}
    for skill_file, errs in by_skill.items():
        # Same call as MetaAgent.specialize_agent (batch mode): group by pattern, one example per pattern
        payload = meta._build_failure_payload(
            [{"instruction": e["instruction"], "expected_apis": e["expected_apis"],
              "actual_calls": e["actual_calls"]} for e in errs])
        categories[skill_name(skill_file)] = payload["pattern_summary"]
        before = Path(skill_file).read_text()
        try:
            refined = meta.refine_agent_definition_batch(payload, skill_file, backup=before)
            status = "unchanged" if refined.strip() == before.strip() else "rewritten"
        except Exception as ex:
            Path(skill_file).write_text(before)
            status = f"refine_error: {type(ex).__name__}: {str(ex)[:200]}"
        after = Path(skill_file).read_text()
        statuses[skill_name(skill_file)] = status
        diff = "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(),
                                              "initial", f"after N={n}", lineterm=""))
        with open(changes_file, "a", encoding="utf-8") as f:
            f.write("\n".join([
                "=" * 80,
                f"N={n} | skill={skill_file} | status={status} | errors={len(errs)} | "
                f"categories={payload['distinct_patterns']} | sent to the meta-agent: "
                f"{min(10, payload['distinct_patterns'])} categories, {min(8, len(payload['examples']))} examples "
                f"(refine_agent_definition_batch keeps the 10 most frequent categories and 8 examples)",
                "Error categories (count | expected -> called):",
                *[f"  {c['count']:>3} | {c['expected_tools']} -> {c['actual_tools'] or '(no tool)'}"
                  for c in payload["pattern_summary"]],
                "Errors:",
                *[f"  - sample {e['pos']} (orig {e['train_index']}) score={e['score']:.2f} | "
                  f"expected={names(e['expected_apis'])} | actual={names(e['actual_calls'])}"
                  for e in errs],
                "-" * 80, "DIFF:", diff or "(no change)", "-" * 80, "NEW SKILL:", after, "",
            ]) + "\n")
        log(f"REFINE | N={n} | skill={skill_file} | errors={len(errs)} | "
            f"categories={payload['distinct_patterns']} | status={status}")
        print(f"    {skill_name(skill_file)} ← {len(errs)} error(s) in "
              f"{payload['distinct_patterns']} categories → {status}")
    return statuses, categories


def write_results(cp: dict, run_dir: Path) -> None:
    fields = ["n", "n_errors", "n_categories", "refine_status", "test_avg"]
    with open(run_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in cp["results"]:
            row = {k: r.get(k) for k in fields}
            if isinstance(row["refine_status"], dict):
                row["refine_status"] = "; ".join(f"{a}: {b}" for a, b in row["refine_status"].items())
            w.writerow(row)
    (run_dir / "results.json").write_text(json.dumps(cp["results"], indent=2, ensure_ascii=False))


def save_summary(cp: dict, path: Path) -> None:
    lines = [
        "=" * 64,
        "ATL TRAIN-SIZE EXPERIMENT — one rewrite from N random train samples",
        "=" * 64,
        f"Run ID           : {cp['run_id']}",
        f"Selection        : random from the 80, independent draw per N, seed {cp['train_seed']}",
        f"Phase 1 reused   : {cp['reused']}",
        f"Agent runs       : {cp['runs_done']} ({datetime.timedelta(seconds=int(cp['run_seconds']))})",
        "",
        "   N | errors used | categories | held-out avg",
    ]
    for r in cp["results"]:
        lines.append(f"{r['n']:>4} | {r['n_errors']:>11} | {r['n_categories']:>10} | {r['test_avg']:>12.2f}")
    lines += ["", "Error categories given to the meta-agent (count | expected -> called):"]
    for r in cp["results"]:
        lines.append(f"  N={r['n']}")
        for skill, cats in r["categories"].items():
            lines.append(f"    {skill}:")
            lines += [f"      {c['count']:>3} | {c['expected_tools']} -> {c['actual_tools'] or '(no tool)'}"
                      for c in cats]
    lines.append("=" * 64)
    text = "\n".join(lines)
    print("\n" + text)
    path.write_text(text)


# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    full_dataset = load_specialization_dataset(DATASET_PATH)
    train_dataset, test_dataset = stratified_split(full_dataset, test_size=TEST_SIZE)
    n_train = len(train_dataset)
    print(f"Loaded {len(full_dataset)} samples | Train: {n_train} | Test (held-out): {len(test_dataset)}")

    finished = [d for d in OUT_DIR.glob(f"run_*_seed{TRAIN_SEED}{TAG}") if (d / "summary.txt").exists()]
    if finished and not CHECKPOINT.exists():
        print(f">>> Seed {TRAIN_SEED}{TAG} already done ({finished[0]}) — skipped.")
        return

    registry = MegamodelRegistry()
    await populate_registry(registry)
    meta = MetaAgent()

    if CHECKPOINT.exists():
        cp = json.loads(CHECKPOINT.read_text())
        print(f">>> Resuming run {cp['run_id']} (seed {cp['train_seed']}) | done: N = {[r['n'] for r in cp['results']]}")
    else:
        cp = {"run_id": RUN_ID, "train_seed": TRAIN_SEED,
              "selection": {str(n): select_samples(n_train, n) for n in TRAIN_SIZES},
              "reused": REUSE_PHASE1, "train_results": {},
              "results": [], "cur_refine": None, "cur_test_scores": [],
              "runs_done": 0, "run_seconds": 0.0}
        if REUSE_PHASE1:
            src = json.loads(PHASE1_CP.read_text())
            cp["initial_apply"], cp["initial_get"] = src["skill_apply"], src["skill_get"]
            # train_index is 1-based in the original (unshuffled) train order
            cp["train_results"] = {str(r["train_index"] - 1): r for r in src["train_results"]}
            print(f">>> Reusing the Phase 1 train results ({PHASE1_CP})")
        else:
            MegamodelToSkill(registry).generate_patterns()
            cp["initial_apply"] = Path(meta.apply_skill).read_text()
            cp["initial_get"] = Path(meta.get_skill).read_text()
        save_checkpoint(cp)

    run_dir = OUT_DIR / f"run_{cp['run_id']}_seed{cp['train_seed']}{TAG}"
    skills_dir = run_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    log_file, changes_file = run_dir / "log.txt", run_dir / "skill_changes.txt"
    log = lambda line: meta._append_log(log_file, line)
    selection = cp["selection"]
    needed = sorted({i for idxs in selection.values() for i in idxs})   # every sample used by some N
    todo = [n for n in TRAIN_SIZES if n not in {r["n"] for r in cp["results"]}]
    missing = sum(1 for i in needed if str(i) not in cp["train_results"])
    progress = Progress(cp, cp["runs_done"] + missing + len(todo) * TEST_SIZE - len(cp["cur_test_scores"]))
    set_initial_skills(meta, cp)
    (skills_dir / "N0_mde-apply.md").write_text(cp["initial_apply"])
    (skills_dir / "N0_mde-get.md").write_text(cp["initial_get"])

    # ── 1. Train samples with the initial skill (only those not reused) ─────
    if missing:
        print(f"\n── Running {missing} train sample(s) with the initial skill ──")
    for pos, idx in enumerate(needed):
        if str(idx) in cp["train_results"]:
            continue
        sample = train_dataset[idx]
        score, calls, exc = run_sample(meta, sample, progress)
        cp["train_results"][str(idx)] = {
            "train_index": idx + 1, "instruction": sample["instruction"], "level": sample.get("level"),
            "skill_file": meta._skill_for(sample["relevant_apis"]), "score": score,
            "expected_apis": sample["relevant_apis"], "actual_calls": calls}
        print(progress.line(f"train sample {pos + 1}/{len(needed)} score={score:.2f}"))
        log(f"TRAIN | sample {pos + 1} | orig={idx + 1} | score={score:.2f} | "
            f"expected={names(sample['relevant_apis'])} | actual={names(calls)}"
            + (f" | exception={exc}" if exc else ""))
        save_checkpoint(cp)

    # ── 2. For each N: one rewrite from the N selected samples, then held-out ──
    for n in todo:
        errors = []
        for pos, idx in enumerate(selection[str(n)]):
            r = cp["train_results"][str(idx)]
            if r["score"] < 1.0:
                errors.append({**r, "pos": pos + 1})

        if cp["cur_refine"] is None:
            print(f"\n══ N = {n}: {len(errors)} error(s) in {n} randomly selected samples → one rewrite ══")
            set_initial_skills(meta, cp)
            status, categories = (refine_once(meta, errors, n, changes_file, log) if errors
                                  else ({"-": "no errors"}, {}))
            cp["cur_refine"] = {"n": n, "status": status, "categories": categories,
                                "apply": Path(meta.apply_skill).read_text(),
                                "get": Path(meta.get_skill).read_text()}
            (skills_dir / f"N{n}_mde-apply.md").write_text(cp["cur_refine"]["apply"])
            (skills_dir / f"N{n}_mde-get.md").write_text(cp["cur_refine"]["get"])
            save_checkpoint(cp)
        else:   # resuming: restore the rewritten skill
            Path(meta.apply_skill).write_text(cp["cur_refine"]["apply"])
            Path(meta.get_skill).write_text(cp["cur_refine"]["get"])

        for j in range(len(cp["cur_test_scores"]), TEST_SIZE):
            sample = test_dataset[j]
            score, calls, exc = run_sample(meta, sample, progress)
            cp["cur_test_scores"].append(score)
            print(progress.line(f"N={n} held-out {j + 1}/{TEST_SIZE} score={score:.2f}"))
            log(f"TEST | N={n} | test={j + 1}/{TEST_SIZE} | score={score:.2f} | "
                f"expected={names(sample['relevant_apis'])} | actual={names(calls)}"
                + (f" | exception={exc}" if exc else ""))
            save_checkpoint(cp)

        scores = cp["cur_test_scores"]
        avg = sum(scores) / len(scores)
        cp["results"].append({"n": n, "n_errors": len(errors), "samples": [i + 1 for i in selection[str(n)]],
                              "refine_status": cp["cur_refine"]["status"],
                              "categories": cp["cur_refine"]["categories"],
                              "n_categories": sum(len(c) for c in cp["cur_refine"]["categories"].values()),
                              "test_avg": avg, "test_scores": scores})
        cp["cur_refine"], cp["cur_test_scores"] = None, []
        log(f"N={n} DONE | errors={len(errors)} | test_avg={avg:.2f}")
        print(f">>> N={n}: held-out avg = {avg:.2f}")
        write_results(cp, run_dir)
        save_checkpoint(cp)

    # ── Done ────────────────────────────────────────────────────────────────
    cp["results"].sort(key=lambda r: r["n"])
    write_results(cp, run_dir)
    save_summary(cp, run_dir / "summary.txt")
    CHECKPOINT.rename(run_dir / "checkpoint_final.json")
    set_initial_skills(meta, cp)
    print(f"\n>>> All done. Results: {run_dir}/summary.txt")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n>>> Interrupted — re-run the script to resume from the checkpoint.")
    except Exception:
        traceback.print_exc()
        print("\n>>> Crashed — re-run the script to resume from the checkpoint.")
        sys.exit(1)
