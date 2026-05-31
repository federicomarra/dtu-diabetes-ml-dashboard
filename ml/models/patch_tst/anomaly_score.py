"""
PatchTST anomaly scoring and evaluation.

Anomaly score
-------------
Option 1 (current): full-window reconstruction MSE.
  - Feed a 120-min window to the model with no masking.
  - Score = mean((recon - actual)^2) over all minutes and channels.
  - High score → the model could not reconstruct this window well → anomaly.

Option 2 (future): last-patch masking.
  - Always mask the last patch (minutes 100-119) at inference.
  - Score = MSE on that patch only → closer to "predict next 20 min."
  - Requires no model change — just pass mask_ratio targeting the last patch.

Per-patient threshold calibration
----------------------------------
Robust estimator on the first N_CAL_DAYS days of scores:
  threshold = median + 2 × (IQR / 1.349)
IQR / 1.349 converts the interquartile range to a std-equivalent for a
Gaussian. Using median + IQR instead of mean + std makes the threshold
resistant to anomaly windows that happen to fall inside the calibration
period — no ground-truth labels needed, so this works on OhioT1DM too.

Evaluation metrics
------------------
Both AUROC and AUPRC are reported.

AUROC (Area Under ROC Curve):
  - Threshold-free ranking metric. 0.5 = random, 1.0 = perfect.
  - Standard in anomaly detection literature — included for comparability.
  - Can be optimistic on imbalanced data: a model that scores everything
    low still ranks rare positives slightly above average.

AUPRC (Area Under Precision-Recall Curve):
  - PRIMARY metric for this project.
  - Only evaluates how well the model finds the positive (anomaly) class.
  - Random baseline ≈ class prevalence (~0.02 here), not 0.5.
  - Harder to fake on <2% anomaly rates — more honest than AUROC here.

Usage
-----
    python ml/models/patch_tst/anomaly_score.py
    python ml/models/patch_tst/anomaly_score.py --checkpoint ml/data/checkpoints/patchtst_best.pt
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.stats import iqr
import torch
from sklearn.metrics import average_precision_score, roc_auc_score
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dataset import build_datasets, ANOMALY_CLASSES, EVAL_STRIDE
from models.patch_tst.model import PatchTST

# ── config ────────────────────────────────────────────────────────────────────

CHECKPOINT    = Path("ml/data/checkpoints/patchtst_best.pt")
PARQUET       = Path("ml/data/sim_data/results_500p_14d_clean.parquet")
N_CAL_DAYS    = 5      # days used to calibrate per-patient threshold
MINUTES_PER_DAY = 1440


# ── scoring ───────────────────────────────────────────────────────────────────

@torch.no_grad()
def score_dataset(
    model: PatchTST,
    loader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """
    Run inference on every window in the loader.

    Returns
    -------
    scores : float32 array [N_windows]
        Reconstruction MSE per window — the raw anomaly score.
    labels : dict class → bool array [N_windows]
        Ground-truth binary label per window per anomaly class.
    """
    model.eval()

    all_scores: list[float] = []
    all_labels: dict[str, list[float]] = {cls: [] for cls in ANOMALY_CLASSES}

    for x, label_dict in loader:
        x = x.to(device)                            # [B, 120, 3]

        recon, _ = model(x, mask_ratio=0.0)         # no masking at inference

        # MSE per window: mean over time and channel dims → scalar per sample
        mse = ((recon - x) ** 2).mean(dim=(1, 2))  # [B]
        all_scores.extend(mse.cpu().tolist())

        for cls in ANOMALY_CLASSES:
            all_labels[cls].extend(label_dict[cls].tolist())

    scores = np.array(all_scores, dtype=np.float32)
    labels = {cls: np.array(v, dtype=np.float32) for cls, v in all_labels.items()}
    return scores, labels


# ── threshold calibration ─────────────────────────────────────────────────────

def calibrate_threshold(
    scores: np.ndarray,
    n_cal_windows: int,
) -> float:
    """
    Robust threshold: median + 2 × (IQR-derived σ).

    Uses median and IQR instead of mean/std — both are resistant to
    outlier anomaly windows in the calibration period. Works without
    ground-truth labels, so compatible with Ohio and real deployments.

    Parameters
    ----------
    scores        : all anomaly scores for one patient, in time order
    n_cal_windows : number of windows from the start to use for calibration
                    (= N_CAL_DAYS × MINUTES_PER_DAY when stride=1)
    """
    cal = scores[:n_cal_windows]
    mu  = np.median(cal)
    std = iqr(cal) / 1.349   # IQR ≈ 1.349σ for a Gaussian → converts to std-equivalent
    std = max(std, 1e-6)
    return float(mu + 2 * std)


# ── metrics ───────────────────────────────────────────────────────────────────

def auroc_per_class(
    scores: np.ndarray,
    labels: dict[str, np.ndarray],
) -> dict[str, float]:
    """
    AUROC per anomaly class. 0.5 = random, 1.0 = perfect.
    Included for comparability with prior work; see AUPRC for primary metric.
    Returns nan for classes with no positive windows.
    """
    results: dict[str, float] = {}
    for cls in ANOMALY_CLASSES:
        y = labels[cls]
        if y.sum() == 0:
            results[cls] = float("nan")
            continue
        results[cls] = float(roc_auc_score(y, scores))
    return results


def auprc_per_class(
    scores: np.ndarray,
    labels: dict[str, np.ndarray],
) -> dict[str, float]:
    """
    AUPRC (average precision) per anomaly class. PRIMARY metric.

    Random baseline ≈ class prevalence (~0.02). Much harder to inflate than
    AUROC on imbalanced data — a model that scores everything low cannot fake
    a high AUPRC because precision collapses when there are no true positives.
    Returns nan for classes with no positive windows.
    """
    results: dict[str, float] = {}
    for cls in ANOMALY_CLASSES:
        y = labels[cls]
        if y.sum() == 0:
            results[cls] = float("nan")
            continue
        results[cls] = float(average_precision_score(y, scores))
    return results


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="PatchTST anomaly scoring")
    parser.add_argument(
        "--checkpoint", type=Path, default=CHECKPOINT,
        help="Path to pretrained checkpoint (.pt)"
    )
    parser.add_argument("--batch_size",  type=int, default=512)
    parser.add_argument("--num_workers", type=int, default=4)
    parser.add_argument("--smoke_test",  action="store_true",
                        help="Score 10 test patients only")
    args = parser.parse_args()

    # ── device ────────────────────────────────────────────────────────────────
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # ── load checkpoint ───────────────────────────────────────────────────────
    if not args.checkpoint.exists():
        raise FileNotFoundError(
            f"Checkpoint not found: {args.checkpoint}\n"
            "Run pretrain.py first."
        )
    ckpt = torch.load(args.checkpoint, map_location=device)
    model = PatchTST().to(device)
    model.load_state_dict(ckpt["model_state"])
    print(f"Loaded checkpoint from epoch {ckpt['epoch']}  (val_loss={ckpt['val_loss']:.4f})")

    # ── data ──────────────────────────────────────────────────────────────────
    max_per_split = 10 if args.smoke_test else None
    _, _, test_ds = build_datasets(
        parquet       = PARQUET,
        max_per_split = max_per_split,
    )
    print(f"Test windows: {len(test_ds):,}  (stride={EVAL_STRIDE} min)")

    loader = DataLoader(
        test_ds,
        batch_size  = args.batch_size,
        shuffle     = False,   # keep time order — needed for calibration
        num_workers = args.num_workers,
        pin_memory  = device.type == "cuda",
    )

    # ── score all windows ─────────────────────────────────────────────────────
    print("Scoring…")
    scores, labels = score_dataset(model, loader, device)
    print(f"Score range: min={scores.min():.4f}  max={scores.max():.4f}  mean={scores.mean():.4f}")

    # ── per-patient threshold (informational — not needed for AUROC) ──────────
    # With eval_stride=1 and N_CAL_DAYS=5 the first 7200 windows are calibration.
    # In a real deployment this runs per patient; here we demo on the full test set.
    n_cal = N_CAL_DAYS * MINUTES_PER_DAY
    if len(scores) >= n_cal:
        threshold = calibrate_threshold(scores, n_cal)
        flagged   = (scores > threshold).mean() * 100
        print(f"Threshold (median+2×IQR/1.349, first {N_CAL_DAYS} days): {threshold:.4f}  →  {flagged:.1f}% windows flagged")

    # ── metrics ───────────────────────────────────────────────────────────────
    auroc = auroc_per_class(scores, labels)
    auprc = auprc_per_class(scores, labels)

    print("\nResults per anomaly class  (PRIMARY: AUPRC | random baseline ≈ prevalence)")
    print(f"  {'class':<12}  {'AUPRC':>6}  {'AUROC':>6}  {'pos windows':>12}  {'prevalence':>10}")
    print(f"  {'-'*12}  {'-'*6}  {'-'*6}  {'-'*12}  {'-'*10}")

    n_total = len(scores)
    for cls in ANOMALY_CLASSES:
        n_pos      = int(labels[cls].sum())
        prevalence = n_pos / n_total if n_total > 0 else 0.0
        auprc_str  = f"{auprc[cls]:.4f}" if not np.isnan(auprc[cls]) else "  n/a "
        auroc_str  = f"{auroc[cls]:.4f}" if not np.isnan(auroc[cls]) else "  n/a "
        print(f"  {cls:<12}  {auprc_str:>6}  {auroc_str:>6}  {n_pos:>12,}  {prevalence:>9.2%}")


if __name__ == "__main__":
    main()
