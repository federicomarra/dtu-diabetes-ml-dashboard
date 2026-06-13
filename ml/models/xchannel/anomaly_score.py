"""
XCHANNEL anomaly scoring.

Single score (decided 2026-06-11): the conditional forecast residual.
  score(window) = mean_t ( glucose[t] − ŷ[t] )²   over the H-min horizon
where ŷ is the model's glucose forecast given glucose history + insulin/carbs
known through the horizon. A missed/late bolus makes the real glucose diverge
from what the inputs imply → large residual.

large_meal is expected to be WEAK here (announced carb → the model predicts the
rise → small residual). We score it anyway and read the number off the
simulator before deciding whether a second (glucose-shape) score is worth it.

Metrics, calibration, any-anomaly headline: reused verbatim from the PatchTST
scorer so the comparison table is apples-to-apples.

Usage
-----
    bsub < ml/models/xchannel/hpc_xchannel_eval.sh
    python ml/models/xchannel/anomaly_score.py --checkpoint ml/data/checkpoints/xchannel_best.pt
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import average_precision_score, roc_auc_score
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from dataset import (  # noqa: E402
    make_patient_split, fit_scalers, load_patients, progress_log, ANOMALY_CLASSES,
)
from models.xchannel.model import (  # noqa: E402
    XChannelForecaster, forecaster_from_ckpt, anomaly_score as compute_score,
)
from models.xchannel.dataset import ForecastWindowDataset  # noqa: E402
from models.patch_tst.anomaly_score import (  # noqa: E402  — reuse, don't duplicate
    calibrate_per_patient, any_anomaly_label, auprc_per_class, auroc_per_class,
)

CHECKPOINT = Path("ml/data/checkpoints/xchannel_best.pt")
PARQUET    = Path("ml/data/sim_data/results_20000p_14d.parquet")
N_CAL_DAYS = 5
MINUTES_PER_DAY = 1440


@torch.no_grad()
def score_dataset(model, loader, device):
    """Forecast residual per window + per-class labels (dataset order)."""
    model.eval()
    all_scores: list[np.ndarray] = []
    all_labels: dict[str, list[np.ndarray]] = {c: [] for c in ANOMALY_CLASSES}
    n = len(loader); t0 = time.time()
    for i, (glu, ins, carb, target, label_dict) in enumerate(loader, 1):
        glu, ins, carb = glu.to(device), ins.to(device), carb.to(device)
        target = target.to(device)
        score = compute_score(model(glu, ins, carb), target)   # MSE or NLL [B]
        all_scores.append(score.cpu().numpy())
        for c in ANOMALY_CLASSES:
            all_labels[c].append(label_dict[c].numpy())
        progress_log(i, n, t0, label="forecast")
    scores = np.concatenate(all_scores).astype(np.float32)
    labels = {c: np.concatenate(v).astype(np.float32) for c, v in all_labels.items()}
    return scores, labels


def main():
    p = argparse.ArgumentParser(description="XCHANNEL anomaly scoring")
    p.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    p.add_argument("--batch_size",  type=int, default=512)
    p.add_argument("--num_workers", type=int, default=0)
    p.add_argument("--norm", choices=["per_patient", "global"], default="per_patient",
                   help="MUST match the pretrain run")
    p.add_argument("--test_stride", type=int, default=5,
                   help="eval window stride (min). 5 ≈ same AUPRC at 5x less compute")
    p.add_argument("--parquet", type=Path, default=PARQUET)
    p.add_argument("--features", choices=["raw", "iob_cob"], default="raw",
                   help="MUST match the pretrain run")
    p.add_argument("--smoke_test", action="store_true")
    args = p.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    if not args.checkpoint.exists():
        raise FileNotFoundError(f"Checkpoint not found: {args.checkpoint}\nRun pretrain.py first.")
    ckpt = torch.load(args.checkpoint, map_location=device)
    model = forecaster_from_ckpt(ckpt, device)
    print(f"Loaded checkpoint from epoch {ckpt['epoch']}  (val_loss={ckpt.get('val_loss', float('nan')):.4f})")

    # ── test data: ALL windows (train_on='all') so anomalies are scored ───────
    split = make_patient_split(args.parquet)
    test_ids = split["test"][:10] if args.smoke_test else split["test"]
    scalers = None
    if args.norm == "global":
        scalers = fit_scalers(load_patients(split["train"], args.parquet), parquet=args.parquet)
    test_ds = ForecastWindowDataset(
        test_ids, scalers=scalers, parquet=args.parquet,
        stride=args.test_stride, norm=args.norm, train_on="all", features=args.features,
    )
    print(f"Test windows: {len(test_ds):,}  (stride={args.test_stride} min, norm={args.norm})")

    loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False,
                        num_workers=args.num_workers, pin_memory=device.type == "cuda")

    print("Scoring — conditional forecast residual…")
    scores, labels = score_dataset(model, loader, device)
    print(f"  range min={scores.min():.4f} max={scores.max():.4f} mean={scores.mean():.4f}")

    # per-patient robust threshold (informational)
    n_cal = N_CAL_DAYS * MINUTES_PER_DAY // args.test_stride
    _, flagged = calibrate_per_patient(scores, test_ds.patient_window_counts(), n_cal)
    print(f"Threshold (per-patient median+2×IQR/1.349, first {N_CAL_DAYS} days): {flagged:.1f}% flagged")

    # headline: any-anomaly
    any_lbl = any_anomaly_label(labels)
    print(f"\nANY-ANOMALY detection (any class vs normal | random baseline ≈ {any_lbl.mean():.2%})")
    if any_lbl.sum() > 0:
        print(f"  AUPRC={average_precision_score(any_lbl, scores):.4f}  "
              f"AUROC={roc_auc_score(any_lbl, scores):.4f}")

    # per-class
    auprc = auprc_per_class(scores, labels)
    auroc = auroc_per_class(scores, labels)
    n_total = len(scores)
    print("\nResults per anomaly class  (PRIMARY: AUPRC | random baseline ≈ prevalence)")
    print(f"  {'class':<12} {'prev':>7} {'AUPRC':>9} {'AUROC':>9}")
    for cls in ANOMALY_CLASSES:
        prev = labels[cls].sum() / n_total if n_total else 0.0
        ap = f"{auprc[cls]:.4f}" if not np.isnan(auprc[cls]) else "   n/a"
        au = f"{auroc[cls]:.4f}" if not np.isnan(auroc[cls]) else "   n/a"
        print(f"  {cls:<12} {prev:>7.2%} {ap:>9} {au:>9}")


if __name__ == "__main__":
    main()
