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
