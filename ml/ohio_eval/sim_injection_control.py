"""
Sim-injection CONTROL for the OhioT1DM generalization eval.

Question it answers: when XCHANNEL scores only ~0.58 AUROC on OhioT1DM, is that
the model failing to transfer, or the *injection protocol* having a low ceiling?
The Ohio protocol perturbs only the bolus and keeps REAL glucose, so the
"anomaly" is a counterfactual input mismatch, not a real excursion.

This runs the IDENTICAL protocol on SIMULATOR data - where the model fits well
(val_loss 0.032) and the native (glucose-reactive) anomalies score AUROC ~0.75.
If this input-only injection also caps at ~0.58 on sim, the protocol is the
limiter and the Ohio number says nothing about transfer. If it reaches ~0.75,
the Ohio gap is a real domain shift.

Injection mirrors eval_xchannel.inject, but sim insulin/carbs are continuous
arrays (no bolus list), so we recover the bolus from the signal:
  * meals      = starts of cho_mg_announced nonzero runs
  * bolus part = insulin above a rolling-median basal baseline (3-min spikes)
  missed = remove bolus insulin + zero its carb box ; late = shift both +delay ;
  large  = shrink the carb box. Glucose is never touched.

Usage
-----
    python ml/ohio_eval/sim_injection_control.py --features raw
    python ml/ohio_eval/sim_injection_control.py --features iob_cob
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from scipy.ndimage import median_filter
from sklearn.metrics import average_precision_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import (  # noqa: E402
    load_patients, make_patient_split, ANOMALY_CLASSES, N_CHANNELS,
)
from features.iob_cob import to_iob_cob  # noqa: E402
from models.xchannel.model import forecaster_from_ckpt  # noqa: E402
from ohio_eval.scoring import valid_starts, score_windows, L, WIN  # noqa: E402

CLASS_IDX = {c: i for i, c in enumerate(ANOMALY_CLASSES)}
BASAL_MEDIAN_WIN = 61          # min - rolling median removes 3-min bolus spikes


def _meal_events(carb: np.ndarray, min_mg: float):
    """(start, end) of each announced-carb box with total carbs >= min_mg."""
    nz = carb > 0
    starts = np.where(nz & ~np.concatenate([[False], nz[:-1]]))[0]
    ends = np.where(nz & ~np.concatenate([nz[1:], [False]]))[0] + 1   # exclusive
    return [(s, e) for s, e in zip(starts, ends) if carb[s:e].sum() >= min_mg]


def inject_sim(arr: np.ndarray, cls: str, late_delay: int, carb_keep: float,
               min_mg: float) -> np.ndarray:
    """Input-only injection on a sim [T,8] array (glucose untouched). Returns copy."""
    out = arr.copy()
    fcol = N_CHANNELS + CLASS_IDX[cls]
    insulin, carb = out[:, 1], out[:, 2]
    basal = median_filter(insulin, size=BASAL_MEDIAN_WIN, mode="nearest")
    bolus = np.maximum(0.0, insulin - basal)          # 3-min spikes above basal
    T = arr.shape[0]

    for s, e in _meal_events(carb, min_mg):
        if cls == "missed":
            insulin[s:e] -= bolus[s:e]                # -> basal (remove bolus)
            carb[s:e] = 0.0                           # drop the announcement
        elif cls == "late":
            d = late_delay
            seg_i, seg_c = bolus[s:e].copy(), carb[s:e].copy()
            insulin[s:e] -= seg_i; carb[s:e] = 0.0    # remove from origin
            t0, t1 = min(s + d, T), min(e + d, T)     # ...re-add later
            insulin[t0:t1] += seg_i[: t1 - t0]
            carb[t0:t1] += seg_c[: t1 - t0]
        elif cls == "large":
            carb[s:e] *= carb_keep
        out[s, fcol] = 1.0                            # flag at the meal onset
    return out


def score_patient(model, device, arr, mean, std, fcol, stride, batch_size):
    """Per-window (score, label) over every window (glucose is untouched here)."""
    z = (arr[:, :N_CHANNELS] - mean) / std
    starts = valid_starts(arr.shape[0], stride)
    if not starts:
        return np.empty(0), np.empty(0)
    scores = score_windows(model, z, starts, device, batch_size)
    labels = np.array([arr[s + L : s + WIN, fcol].max() for s in starts], dtype=np.float32)
    return scores, labels


def main():
    ap = argparse.ArgumentParser(description="Sim input-only injection control")
    ap.add_argument("--checkpoint", type=Path, default=None)
    ap.add_argument("--features", choices=["raw", "iob_cob"], default="raw")
    ap.add_argument("--parquet", type=Path, default=Path("ml/data/sim_data/results_500p_14d_clean.parquet"))
    ap.add_argument("--n_patients", type=int, default=100)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--batch_size", type=int, default=512)
    ap.add_argument("--late_delay", type=int, default=30)
    ap.add_argument("--carb_keep", type=float, default=0.7)
    ap.add_argument("--min_carb_g", type=float, default=20.0)
    args = ap.parse_args()
    if args.checkpoint is None:
        name = "xchannel_iobcob_best.pt" if args.features == "iob_cob" else "xchannel_best.pt"
        args.checkpoint = Path("ml/data/checkpoints") / name

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}  | features={args.features}")
    ckpt = torch.load(args.checkpoint, map_location=device)
    model = forecaster_from_ckpt(ckpt, device); model.eval()
    print(f"Loaded epoch {ckpt['epoch']} (val_loss={ckpt.get('val_loss', float('nan')):.4f})")

    split = make_patient_split(args.parquet)
    ids = split["test"][: args.n_patients]
    patients = load_patients(ids, args.parquet)
    xf = to_iob_cob if args.features == "iob_cob" else (lambda a: a)
    min_mg = args.min_carb_g * 1000.0
    print(f"Sim control: {len(patients)} test patients, input-only injection "
          f"(glucose untouched), same protocol as OhioT1DM")

    print(f"\n  {'class':<8} {'prev':>7} {'pos':>7} {'AUPRC':>9} {'AUROC':>9}")
    for cls in ("missed", "late", "large"):
        fcol = N_CHANNELS + CLASS_IDX[cls]
        all_s, all_l = [], []
        for arr in patients.values():
            inj = inject_sim(arr, cls, args.late_delay, args.carb_keep, min_mg)
            # z-score stats from the ORIGINAL (transformed) array, applied to the injected one
            ref = xf(arr.copy())
            mean = ref[:, :N_CHANNELS].mean(0); std = ref[:, :N_CHANNELS].std(0).clip(1e-8)
            s, lab = score_patient(model, device, xf(inj), mean, std, fcol, args.stride, args.batch_size)
            all_s.append(s); all_l.append(lab)
        scores, labels = np.concatenate(all_s), np.concatenate(all_l)
        if labels.sum() == 0:
            print(f"  {cls:<8}    n/a"); continue
        print(f"  {cls:<8} {labels.mean():>7.2%} {int(labels.sum()):>7} "
              f"{average_precision_score(labels, scores):>9.4f} {roc_auc_score(labels, scores):>9.4f}")


if __name__ == "__main__":
    main()
