"""
Plot PatchTST anomaly detection evaluation figures.

Produces two figures saved to ml/figures/:
  1. pr_curves.png    — Precision-recall curve per anomaly class (AUPRC in legend)
  2. score_dist.png   — Anomaly score distribution: normal vs anomaly windows

Both figures are thesis-quality (300 dpi, labelled axes, clean style).

Usage
-----
    python ml/scripts/plot_eval.py
    python ml/scripts/plot_eval.py --checkpoint ml/data/checkpoints/patchtst_best.pt
    python ml/scripts/plot_eval.py --smoke_test   # 10 test patients, fast
"""

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import precision_recall_curve, average_precision_score
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent.parent))

from dataset import build_datasets, ANOMALY_CLASSES, EVAL_STRIDE
from models.patch_tst.model import PatchTST
from models.patch_tst.anomaly_score import score_dataset

# ── config ────────────────────────────────────────────────────────────────────

CHECKPOINT  = Path("ml/data/checkpoints/patchtst_best.pt")
PARQUET     = Path("ml/data/sim_data/results_500p_14d_clean.parquet")
FIGURES_DIR = Path("ml/figures")

# one colour per anomaly class — colourblind-safe palette
CLASS_COLORS = {
    "missed":    "#2563eb",
    "late":      "#dc2626",
    "large":     "#16a34a",
    "prolonged": "#d97706",
    "anaerobic": "#7c3aed",
}


# ── figure 1: precision-recall curves ────────────────────────────────────────

def plot_pr_curves(
    scores: np.ndarray,
    labels: dict[str, np.ndarray],
    out_path: Path,
) -> None:
    """One PR curve per anomaly class, AUPRC annotated in the legend."""
    fig, ax = plt.subplots(figsize=(7, 6))

    for cls in ANOMALY_CLASSES:
        y = labels[cls]
        if y.sum() == 0:
            continue

        precision, recall, _ = precision_recall_curve(y, scores)
        auprc = average_precision_score(y, scores)
        prevalence = y.mean()

        ax.plot(
            recall, precision,
            label=f"{cls}  (AUPRC={auprc:.3f})",
            color=CLASS_COLORS[cls],
            linewidth=2,
        )
        # dashed horizontal = random baseline for this class
        ax.axhline(
            prevalence, color=CLASS_COLORS[cls],
            linestyle=":", linewidth=0.8, alpha=0.5,
        )

    ax.set_xlabel("Recall", fontsize=12)
    ax.set_ylabel("Precision", fontsize=12)
    ax.set_title(
        "Precision-Recall curves per anomaly class\n"
        "(dotted = random baseline ≈ prevalence)",
        fontsize=12, fontweight="bold",
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"Saved → {out_path}")


# ── figure 2: score distribution ─────────────────────────────────────────────

def plot_score_distribution(
    scores: np.ndarray,
    labels: dict[str, np.ndarray],
    out_path: Path,
) -> None:
    """
    Histogram of anomaly scores split by label.

    'anomaly' = any window flagged by at least one class.
    'normal'  = all class labels are 0.

    Separation between the two distributions indicates how discriminative
    the reconstruction error is.
    """
    any_anomaly = np.stack(list(labels.values()), axis=1).any(axis=1)
    normal_scores  = scores[~any_anomaly]
    anomaly_scores = scores[any_anomaly]

    fig, ax = plt.subplots(figsize=(8, 4.5))

    bins = np.linspace(scores.min(), np.percentile(scores, 99.5), 80)

    ax.hist(normal_scores,  bins=bins, alpha=0.6, color="#2563eb",
            label=f"Normal  (n={len(normal_scores):,})",  density=True)
    ax.hist(anomaly_scores, bins=bins, alpha=0.6, color="#dc2626",
            label=f"Anomaly (n={len(anomaly_scores):,})", density=True)

    ax.set_xlabel("Reconstruction MSE (anomaly score)", fontsize=12)
    ax.set_ylabel("Density", fontsize=12)
    ax.set_title(
        "Anomaly score distribution — normal vs anomaly windows",
        fontsize=12, fontweight="bold",
    )
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"Saved → {out_path}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Plot PatchTST eval figures")
    parser.add_argument("--checkpoint",  type=Path, default=CHECKPOINT)
    parser.add_argument("--batch_size",  type=int,  default=512)
    parser.add_argument("--num_workers", type=int,  default=4)
    parser.add_argument("--smoke_test",  action="store_true",
                        help="Use 10 test patients only — fast local run")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # ── load model ────────────────────────────────────────────────────────────
    if not args.checkpoint.exists():
        raise FileNotFoundError(
            f"Checkpoint not found: {args.checkpoint}\n"
            "Run pretrain.py first."
        )
    ckpt  = torch.load(args.checkpoint, map_location=device)
    model = PatchTST().to(device)
    model.load_state_dict(ckpt["model_state"])
    print(f"Loaded checkpoint epoch {ckpt['epoch']}  val_loss={ckpt['val_loss']:.4f}")

    # ── data ──────────────────────────────────────────────────────────────────
    max_per_split = 10 if args.smoke_test else None
    _, _, test_ds = build_datasets(parquet=PARQUET, max_per_split=max_per_split)
    print(f"Test windows: {len(test_ds):,}  (stride={EVAL_STRIDE} min)")

    loader = DataLoader(
        test_ds,
        batch_size  = args.batch_size,
        shuffle     = False,
        num_workers = args.num_workers,
        pin_memory  = device.type == "cuda",
    )

    # ── score ─────────────────────────────────────────────────────────────────
    print("Scoring…")
    scores, labels = score_dataset(model, loader, device)
    print(f"Score range: min={scores.min():.4f}  max={scores.max():.4f}  mean={scores.mean():.4f}")

    # ── figures ───────────────────────────────────────────────────────────────
    plot_pr_curves(scores, labels, FIGURES_DIR / "pr_curves.png")
    plot_score_distribution(scores, labels, FIGURES_DIR / "score_dist.png")


if __name__ == "__main__":
    main()
