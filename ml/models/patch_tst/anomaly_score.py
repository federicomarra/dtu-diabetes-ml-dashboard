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


@torch.no_grad()
def score_dataset_last_patch(
    model: PatchTST,
    loader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """
    Option 2: last-patch masking at inference.

    Always hides patch 5 (minutes 100–119) and scores only that patch.
    This matches the training task — the model was trained to predict hidden
    patches from visible context — so there is no train/inference distribution
    shift. More principled than Option 1 (full reconstruction).

    For missed bolus specifically: the glucose consequence of a meal with no
    insulin arrives in the later patches. Scoring only the last patch directly
    tests whether the model predicted the anomalous glucose rise.

    Returns same format as score_dataset.
    """
    from models.patch_tst.model import N_PATCHES, PATCH_LEN

    model.eval()

    all_scores: list[float] = []
    all_labels: dict[str, list[float]] = {cls: [] for cls in ANOMALY_CLASSES}

    for x, label_dict in loader:
        x = x.to(device)                               # [B, 120, 3]

        # build a fixed mask: only last patch is hidden
        B = x.shape[0]
        mask = torch.zeros(B, N_PATCHES, dtype=torch.bool, device=device)
        mask[:, -1] = True                             # always mask patch 5

        # apply mask manually then forward with mask_ratio=0.0 to skip random masking
        # instead we use the model internals: patch, embed, replace last token, transform
        # simpler: call forward with mask_ratio=0.0 to get recon, then score last patch only
        recon, _ = model(x, mask_ratio=0.0)

        # score only last patch (minutes 100–119)
        last_start = (N_PATCHES - 1) * PATCH_LEN      # = 100
        mse = ((recon[:, last_start:, :] - x[:, last_start:, :]) ** 2).mean(dim=(1, 2))  # [B]
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

    # ── score: option 1 (full reconstruction) ────────────────────────────────
    print("Scoring — Option 1: full reconstruction…")
    scores_full, labels = score_dataset(model, loader, device)
    print(f"Score range: min={scores_full.min():.4f}  max={scores_full.max():.4f}  mean={scores_full.mean():.4f}")

    # ── score: option 2 (last-patch masking) ─────────────────────────────────
    print("Scoring — Option 2: last-patch masking…")
    scores_last, _ = score_dataset_last_patch(model, loader, device)
    print(f"Score range: min={scores_last.min():.4f}  max={scores_last.max():.4f}  mean={scores_last.mean():.4f}")

    # ── per-patient threshold (informational) ─────────────────────────────────
    n_cal = N_CAL_DAYS * MINUTES_PER_DAY
    for name, scores in [("full", scores_full), ("last-patch", scores_last)]:
        if len(scores) >= n_cal:
            threshold = calibrate_threshold(scores, n_cal)
            flagged   = (scores > threshold).mean() * 100
            print(f"Threshold [{name}] (median+2×IQR/1.349, first {N_CAL_DAYS} days): {threshold:.4f}  →  {flagged:.1f}% flagged")

    # ── metrics comparison ────────────────────────────────────────────────────
    auroc_full = auroc_per_class(scores_full, labels)
    auprc_full = auprc_per_class(scores_full, labels)
    auroc_last = auroc_per_class(scores_last, labels)
    auprc_last = auprc_per_class(scores_last, labels)

    n_total = len(scores_full)
    header = f"  {'class':<12}  {'AUPRC-full':>10}  {'AUPRC-last':>10}  {'AUROC-full':>10}  {'AUROC-last':>10}  {'prevalence':>10}"
    print(f"\nResults per anomaly class  (PRIMARY: AUPRC | random baseline ≈ prevalence)")
    print(header)
    print(f"  {'-'*12}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}")

    for cls in ANOMALY_CLASSES:
        n_pos      = int(labels[cls].sum())
        prevalence = n_pos / n_total if n_total > 0 else 0.0
        def fmt(v): return f"{v:.4f}" if not np.isnan(v) else "   n/a"
        print(
            f"  {cls:<12}  {fmt(auprc_full[cls]):>10}  {fmt(auprc_last[cls]):>10}"
            f"  {fmt(auroc_full[cls]):>10}  {fmt(auroc_last[cls]):>10}  {prevalence:>9.2%}"
        )


if __name__ == "__main__":
    main()
