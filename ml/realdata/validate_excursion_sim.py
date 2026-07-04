"""Sim-validation gate for glucose-derived label placement. The generator's per-minute
label columns (cols 3-7, ANOMALY_CLASSES order) ARE the ground-truth windows. For each
contiguous true-flag run of a class, the run is the true window and the meal minute 
~ run_start - 15 (LABEL_WINDOW_BOLUS_START). We anchor excursion_window there and report
IoU vs truth, and the placement recall (fraction of true runs where a rise was found).

GATE: if excursion median IoU meaningfully beats the fixed-aligned-window IoU baseline,
the rule recovers the true region -> proceed to real data. Else stop and retune.

Run: .venv/bin/python ml/realdata/validate_excursion_sim.py --n_patients 60
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import N_CHANNELS, ANOMALY_CLASSES, load_patients     # noqa: E402
from realdata.excursion import excursion_window, ALIGNED_CAP        # noqa: E402

BOLUS_START = 15   # generator LABEL_WINDOW_BOLUS_START
EVAL_CLASSES = ("missed", "late", "large")


def _runs(flag: np.ndarray):
    """Yield (start, end_exclusive) of contiguous 1-runs in a 0/1 array."""
    idx = np.flatnonzero(flag)
    if idx.size == 0:
        return
    splits = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate(([0], splits + 1))
    ends = np.concatenate((splits, [idx.size - 1]))
    for s, e in zip(starts, ends):
        yield idx[s], idx[e] + 1


def _iou(a, b):
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", type=Path,
                    default=Path("ml/data/sim_data/results_5000p_42d.parquet"))
    ap.add_argument("--n_patients", type=int, default=60)
    args = ap.parse_args()

    pf = pq.ParquetFile(args.parquet)
    ids: set[str] = set()
    for rg in range(pf.metadata.num_row_groups):
        ids.update(pf.read_row_group(rg, columns=["patient_id"]).column("patient_id").to_pylist())
        if len(ids) >= args.n_patients * 3:
            break
    pids = sorted(ids)[: args.n_patients]
    data = load_patients(pids, args.parquet)
    print(f"Validating excursion placement on {len(pids)} sim patients\n")
    print(f"  {'class':<8} {'true runs':>10} {'found':>7} {'recall':>8} "
          f"{'IoU excur':>11} {'IoU fixed':>11}")
    for cls in EVAL_CLASSES:
        col = N_CHANNELS + ANOMALY_CLASSES.index(cls)
        cap = ALIGNED_CAP[cls]
        n_runs = n_found = 0
        iou_exc, iou_fix = [], []
        for pid in pids:
            arr = data[pid]
            glu = arr[:, 0]
            for s, e in _runs(arr[:, col]):
                n_runs += 1
                meal = max(0, s - BOLUS_START)            # reconstruct meal minute
                truth = (s, e)
                fixed = (meal, min(glu.size, meal + cap))  # current aligned window
                iou_fix.append(_iou(fixed, truth))
                w = excursion_window(glu, meal, cls)    #type: ignore
                if w is not None:
                    n_found += 1
                    iou_exc.append(_iou(w, truth))
                else:
                    iou_exc.append(0.0)                    # no-rise -> would fall back
        rec = n_found / n_runs if n_runs else 0.0
        print(f"  {cls:<8} {n_runs:>10} {n_found:>7} {rec:>8.1%} "
              f"{np.median(iou_exc):>11.3f} {np.median(iou_fix):>11.3f}")
    print("\nGATE: excursion IoU should meaningfully exceed fixed IoU to proceed to real data.")


if __name__ == "__main__":
    main()
