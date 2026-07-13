"""
PatchTST anomaly scoring and evaluation.

Anomaly score (two complementary scores; glucose channel only by default)
-------------------------------------------------------------------------
Option 1 - whole-window reconstruction deviation.
  - Feed a 120-min window with no masking; score = mean((recon - actual)^2).
  - Measures how unusual the whole window looks. NOT prediction.

Option 2 - next-N-min prediction error (the "forecast" score).
  - Mask the last `horizon_patches` patches (default 1 = 20 min) and score only
    them. The model predicts the hidden tail from the visible prefix - same as
    the masked training task, so no train/inference shift. This is genuine
    prediction error.
  - Horizon is a CLI flag (--horizon_patches); 2 = 40 min.

Per-patient threshold calibration
----------------------------------
Robust estimator on the first N_CAL_DAYS days of scores:
  threshold = median + 2 x (IQR / 1.349)
IQR / 1.349 converts the interquartile range to a std-equivalent for a
Gaussian. Using median + IQR instead of mean + std makes the threshold
resistant to anomaly windows that happen to fall inside the calibration
period - no ground-truth labels needed, so this works on OhioT1DM too.

Evaluation metrics
------------------
Both AUROC and AUPRC are reported.

AUROC (Area Under ROC Curve):
  - Threshold-free ranking metric. 0.5 = random, 1.0 = perfect.
  - Standard in anomaly detection literature - included for comparability.
  - Can be optimistic on imbalanced data: a model that scores everything
    low still ranks rare positives slightly above average.

AUPRC (Area Under Precision-Recall Curve):
  - PRIMARY metric for this project.
  - Only evaluates how well the model finds the positive (anomaly) class.
  - Random baseline ~ class prevalence (~0.02 here), not 0.5.
  - Harder to fake on <2% anomaly rates - more honest than AUROC here.

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

from dataset import build_datasets, progress_log, ANOMALY_CLASSES
import time
from models.patch_tst.model import PatchTST

# -- config --------------------------------------------------------------------

CHECKPOINT    = Path("ml/data/checkpoints/patchtst_best.pt")
PARQUET       = Path("ml/data/sim_data/results_20000p_14d.parquet")
N_CAL_DAYS    = 5      # days used to calibrate per-patient threshold
MINUTES_PER_DAY = 1440


# -- scoring -------------------------------------------------------------------

@torch.no_grad()
def score_dataset(
    model: PatchTST,
    loader: DataLoader,
    device: torch.device,
    score_channels: tuple[int, ...] = (0,),
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """
    Run inference on every window in the loader.

    score_channels selects which channels enter the MSE. Default (0,) = glucose
    only. Glucose is the sensor-corrupted output where anomalies manifest;
    insulin (ch 1) and carbs (ch 2) are known inputs whose reconstruction error
    is mostly spike-noise and, when averaged in, can swamp the glucose signal.
    Pass (0, 1, 2) to reproduce the old all-channel score.

    Returns
    -------
    scores : float32 array [N_windows]
        Reconstruction MSE per window - the raw anomaly score.
    labels : dict class -> bool array [N_windows]
        Ground-truth binary label per window per anomaly class.
    """
    model.eval()
    ch = list(score_channels)

    # Accumulate numpy chunks, not Python floats - 80M stride-1 windows as
    # Python list elements cost ~3 GB per metric column.
    all_scores: list[np.ndarray] = []
    all_labels: dict[str, list[np.ndarray]] = {cls: [] for cls in ANOMALY_CLASSES}

    n = len(loader); t0 = time.time()
    for i, (x, label_dict) in enumerate(loader, 1):
        x = x.to(device)                            # [B, 120, 3]

        recon, _ = model(x, mask_ratio=0.0)         # no masking at inference

        # MSE per window over selected channels (glucose only by default)
        mse = ((recon[:, :, ch] - x[:, :, ch]) ** 2).mean(dim=(1, 2))  # [B]
        all_scores.append(mse.cpu().numpy())

        for cls in ANOMALY_CLASSES:
            all_labels[cls].append(label_dict[cls].numpy())
        progress_log(i, n, t0, label="score")

    scores = np.concatenate(all_scores).astype(np.float32)
    labels = {cls: np.concatenate(v).astype(np.float32) for cls, v in all_labels.items()}
    return scores, labels


@torch.no_grad()
def score_dataset_last_patch(
    model: PatchTST,
    loader: DataLoader,
    device: torch.device,
    score_channels: tuple[int, ...] = (0,),
    horizon_patches: int = 1,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """
    Prediction score: mask the last `horizon_patches` patches, score only them.

    The model predicts the hidden tail from the visible context - matching the
    masked training task, so there is no train/inference distribution shift.
    This is true prediction error, not cropped full reconstruction.

    horizon_patches sets the forecast length: 1 patch = 20 min (default),
    2 = 40 min. At least one context patch is always kept visible, so the value
    is clamped to [1, N_PATCHES - 1]. Missed bolus is the motivation for a
    longer horizon - its glucose consequence takes 60-90 min to develop, so a
    20-min tail may end before the anomalous rise diverges. NB: with a
    channel-independent backbone glucose is predicted from glucose alone, so a
    longer horizon may still not separate missed bolus.

    Returns same format as score_dataset.
    """
    from models.patch_tst.model import N_PATCHES, PATCH_LEN

    model.eval()
    ch = list(score_channels)   # glucose only by default (see score_dataset)
    k = max(1, min(horizon_patches, N_PATCHES - 1))   # keep >=1 visible context patch

    # fixed mask hiding the last k patches - broadcasts across the batch
    last_mask = torch.zeros(N_PATCHES, dtype=torch.bool, device=device)
    last_mask[-k:] = True
    last_start = (N_PATCHES - k) * PATCH_LEN          # first masked minute

    all_scores: list[np.ndarray] = []
    all_labels: dict[str, list[np.ndarray]] = {cls: [] for cls in ANOMALY_CLASSES}

    n = len(loader); t0 = time.time()
    for i, (x, label_dict) in enumerate(loader, 1):
        x = x.to(device)                               # [B, 120, 3]

        # hide the last k patches -> model must predict them from the prefix
        recon, _ = model(x, fixed_mask=last_mask)

        # score only the predicted (masked) tail, selected channels
        err = (recon[:, last_start:, ch] - x[:, last_start:, ch]) ** 2  # [B, k*20, |ch|]
        mse = err.mean(dim=(1, 2))                                       # [B]
        all_scores.append(mse.cpu().numpy())

        for cls in ANOMALY_CLASSES:
            all_labels[cls].append(label_dict[cls].numpy())
        progress_log(i, n, t0, label="predict")

    scores = np.concatenate(all_scores).astype(np.float32)
    labels = {cls: np.concatenate(v).astype(np.float32) for cls, v in all_labels.items()}
    return scores, labels


# -- threshold calibration -----------------------------------------------------

def calibrate_threshold(
    scores: np.ndarray,
    n_cal_windows: int,
    k: float = 2.0,
) -> float:
    """
    Robust threshold: median + k x (IQR-derived sigma).

    Uses median and IQR instead of mean/std - both are resistant to
    outlier anomaly windows in the calibration period. Works without
    ground-truth labels, so compatible with Ohio and real deployments.

    Parameters
    ----------
    scores        : all anomaly scores for one patient, in time order
    n_cal_windows : number of windows from the start to use for calibration
                    (= N_CAL_DAYS x MINUTES_PER_DAY when stride=1)
    k             : sensitivity. Higher = fewer flags (curbs over-detection);
                    2.0 ~ flags the top few % under a Gaussian.
    """
    cal = scores[:n_cal_windows]
    mu  = np.median(cal)
    std = iqr(cal) / 1.349   # IQR ~ 1.349sigma for a Gaussian -> converts to std-equivalent
    std = max(std, 1e-6)
    return float(mu + k * std)


def robust_baseline(
    scores: np.ndarray,
    k: float = 2.0,
    trim_iters: int = 3,
) -> tuple[float, float, float]:
    """
    Median, sigma and threshold of this patient's NON-anomalous windows.

    Two differences from `calibrate_threshold`, which fits the leading
    `n_cal_windows` and keeps whatever anomalies live there:

      * every window is used, so the result no longer depends on whether the
        patient happened to be well-behaved during their first five days;
      * the fit is iterated, dropping windows above median + k*sigma each pass,
        so sigma describes normal behaviour instead of absorbing the anomalies
        it is supposed to measure distance from.

    Returns (median, sigma, threshold). At least half the windows are always
    retained, so a pathological all-tail input still yields a defined scale.
    """
    s = np.asarray(scores, dtype=float)
    if s.size == 0:
        return 0.0, 1e-6, 0.0

    keep = np.ones(s.size, dtype=bool)
    mu = float(np.median(s))
    std = max(iqr(s) / 1.349, 1e-6)
    floor = max(s.size // 2, 1)          # never trim past half the record

    for _ in range(trim_iters):
        thr = mu + k * std
        nxt = s <= thr
        if nxt.sum() < floor or nxt.sum() == keep.sum():
            break
        keep = nxt
        mu = float(np.median(s[keep]))
        std = max(iqr(s[keep]) / 1.349, 1e-6)

    return mu, std, float(mu + k * std)


def calibrate_per_patient(
    scores: np.ndarray,
    patient_counts: list[tuple[str, int]],
    n_cal_windows: int,
) -> tuple[np.ndarray, float]:
    """
    Per-patient robust threshold, applied per patient.

    Each patient is calibrated on its OWN first n_cal_windows scores (or all of
    its windows if it has fewer - short real-data patients), then flagged
    against its OWN threshold. This is the per-patient baseline the spec
    requires: a global threshold would calibrate everyone on patient #1's first
    days, which is meaningless.

    `scores` must be in dataset order (eval loader shuffle=False), so each
    patient's windows are the contiguous block given by patient_counts.

    Returns (flagged_bool [N], overall_flagged_pct).
    """
    flagged = np.zeros(len(scores), dtype=bool)
    offset = 0
    for _pid, n in patient_counts:
        s = scores[offset : offset + n]
        thr = calibrate_threshold(s, min(n_cal_windows, n))   # short patient -> use all
        flagged[offset : offset + n] = s > thr
        offset += n
    return flagged, float(flagged.mean() * 100)


# -- metrics -------------------------------------------------------------------

def any_anomaly_label(labels: dict[str, np.ndarray]) -> np.ndarray:
    """
    OR the per-class labels -> 1.0 where ANY anomaly class is present.

    This is the headline DETECTION target (anomaly vs normal). Per-class AUPRC
    is confounded: for class X, windows of other anomaly classes count as
    negatives, so the model is penalised for correctly scoring them high. The
    any-anomaly label removes that cross-class contamination.
    """
    stacked = np.stack([labels[cls] for cls in ANOMALY_CLASSES], axis=0)  # [C, N]
    return (stacked.max(axis=0) > 0).astype(np.float32)  # type: ignore  # numpy stub types don't match np.ndarray


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

    Random baseline ~ class prevalence (~0.02). Much harder to inflate than
    AUROC on imbalanced data - a model that scores everything low cannot fake
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


# -- main ----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="PatchTST anomaly scoring")
    parser.add_argument(
        "--checkpoint", type=Path, default=CHECKPOINT,
        help="Path to pretrained checkpoint (.pt)"
    )
    parser.add_argument("--batch_size",  type=int, default=512)
    parser.add_argument("--num_workers", type=int, default=4)
    parser.add_argument("--score_channels", type=int, nargs="+", default=[0],
                        help="channels in the MSE score; 0=glucose 1=insulin 2=carbs "
                             "(default: 0 = glucose only)")
    parser.add_argument("--horizon_patches", type=int, default=1,
                        help="prediction horizon for Option 2, in 20-min patches "
                             "(1=20min default, 2=40min)")
    parser.add_argument("--norm", choices=["per_patient", "global"], default="per_patient",
                        help="normalization mode - MUST match the pretrain run")
    parser.add_argument("--test_stride", type=int, default=1,
                        help="eval window stride. 1 = per-minute (80M windows, slow); "
                             "5 ~ same AUPRC at 5x less compute (windows overlap ~99%)")
    parser.add_argument("--last_only", action="store_true",
                        help="score only Option 2 (prediction); skip Option 1 full reconstruction")
    parser.add_argument("--smoke_test",  action="store_true",
                        help="Score 10 test patients only")
    args = parser.parse_args()
    score_channels = tuple(args.score_channels)

    # -- device ----------------------------------------------------------------
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # -- load checkpoint -------------------------------------------------------
    if not args.checkpoint.exists():
        raise FileNotFoundError(
            f"Checkpoint not found: {args.checkpoint}\n"
            "Run pretrain.py first."
        )
    ckpt = torch.load(args.checkpoint, map_location=device)
    model = PatchTST().to(device)
    model.load_state_dict(ckpt["model_state"])
    print(f"Loaded checkpoint from epoch {ckpt['epoch']}  (val_loss={ckpt['val_loss']:.4f})")

    # -- data ------------------------------------------------------------------
    max_per_split = 10 if args.smoke_test else None
    # Only the test set is needed; cached scalers (written by pretrain.py)
    # let build_datasets skip the 12k-patient train load entirely.
    _, _, test_ds = build_datasets(
        parquet       = PARQUET,
        max_per_split = max_per_split,
        eval_stride   = args.test_stride,
        include_train = False,
        include_val   = False,
        norm          = args.norm,
    )
    print(f"Test windows: {len(test_ds):,}  (stride={args.test_stride} min)")   #type: ignore

    loader = DataLoader(
        test_ds,    #type: ignore
        batch_size  = args.batch_size,
        shuffle     = False,   # keep time order - needed for calibration
        num_workers = args.num_workers,
        pin_memory  = device.type == "cuda",
    )

    _names = ["glucose", "insulin", "carbs"]
    print(f"Scoring channels: {[_names[c] for c in score_channels]}")

    # Active scores: Option 2 (prediction) always; Option 1 (full recon) unless
    # --last_only. Everything below iterates `scored`, so dropping Option 1 just
    # removes a column.
    scored: list[tuple[str, np.ndarray]] = []
    labels: dict[str, np.ndarray] | None = None

    if not args.last_only:
        print("Scoring - Option 1: whole-window reconstruction deviation...")
        scores_full, labels = score_dataset(model, loader, device, score_channels)
        print(f"  range min={scores_full.min():.4f} max={scores_full.max():.4f} mean={scores_full.mean():.4f}")
        scored.append(("full", scores_full))

    print(f"Scoring - Option 2: next-{args.horizon_patches * 20}-min prediction error...")
    scores_last, labels_last = score_dataset_last_patch(model, loader, device, score_channels, args.horizon_patches)
    print(f"  range min={scores_last.min():.4f} max={scores_last.max():.4f} mean={scores_last.mean():.4f}")
    scored.append(("last", scores_last))
    if labels is None:
        labels = labels_last

    # -- per-patient threshold (informational) ---------------------------------
    # n_cal_windows = first N_CAL_DAYS days, in windows (one window ~ test_stride min).
    n_cal = N_CAL_DAYS * MINUTES_PER_DAY // args.test_stride
    patient_counts = test_ds.patient_window_counts()   # type: ignore
    for name, scores in scored:
        _, flagged = calibrate_per_patient(scores, patient_counts, n_cal)
        print(f"Threshold [{name}] (per-patient median+2xIQR/1.349, first {N_CAL_DAYS} days): {flagged:.1f}% flagged")

    # -- headline detection metric: any-anomaly (any class vs normal) ----------
    any_lbl = any_anomaly_label(labels)
    print(f"\nANY-ANOMALY detection (any class vs normal | random baseline ~ {any_lbl.mean():.2%})")
    for name, scores in scored:
        ap = average_precision_score(any_lbl, scores) if any_lbl.sum() > 0 else float("nan")
        au = roc_auc_score(any_lbl, scores)           if any_lbl.sum() > 0 else float("nan")
        print(f"  {name:<10}  AUPRC={ap:.4f}  AUROC={au:.4f}")

    # -- per-class metrics (classification-flavoured; see any_anomaly_label) ----
    def _fmt(v): return f"{v:.4f}" if not np.isnan(v) else "   n/a"
    metrics = {name: (auprc_per_class(s, labels), auroc_per_class(s, labels)) for name, s in scored}
    n_total = len(scored[0][1])

    cols = "  ".join(f"{name+'-AUPRC':>11} {name+'-AUROC':>11}" for name, _ in scored)
    print("\nResults per anomaly class  (PRIMARY: AUPRC | random baseline ~ prevalence)")
    print(f"  {'class':<12} {'prev':>7}  {cols}")
    for cls in ANOMALY_CLASSES:
        prevalence = labels[cls].sum() / n_total if n_total > 0 else 0.0
        row = "  ".join(f"{_fmt(metrics[n][0][cls]):>11} {_fmt(metrics[n][1][cls]):>11}" for n, _ in scored)
        print(f"  {cls:<12} {prevalence:>7.2%}  {row}")


if __name__ == "__main__":
    main()
