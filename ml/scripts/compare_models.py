"""
Side-by-side AUPRC / AUROC comparison: PatchTST vs CARLA.

Loads both trained checkpoints, scores the same test set, and prints a unified
table. Also saves a bar chart to ml/figures/model_comparison.png.

Both models are evaluated on the same test patients with the same eval stride
(EVAL_STRIDE = 1 min) so the comparison is fair.

PatchTST anomaly score : reconstruction MSE (full-window, no masking at inference)
CARLA anomaly score    : GMM negative log-likelihood on encoder embeddings

PRIMARY metric: AUPRC. AUROC secondary. Both are rank-based — absolute score
scales differ between models but comparisons via these metrics are valid.

Usage
-----
    python ml/scripts/compare_models.py
    python ml/scripts/compare_models.py --smoke_test   # 10 test patients, fast
    python ml/scripts/compare_models.py \\
        --patchtst_ckpt ml/data/checkpoints/patchtst_best.pt \\
        --carla_ckpt    ml/data/checkpoints/carla_best.pt
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent.parent))

from dataset import (
    build_datasets, load_patients, load_scalers, _apply_scalers,
    ANOMALY_CLASSES, EVAL_STRIDE,
)
from models.patch_tst.model import PatchTST
from models.patch_tst.anomaly_score import score_dataset as patchtst_score_dataset
from models.carla.model import CARLAModel
from models.carla.anomaly_score import embed_dataset, fit_gmm, score_with_gmm
from models.carla.dataset import ContrastiveDataset
from sklearn.metrics import average_precision_score, roc_auc_score

PATCHTST_CKPT = Path("ml/data/checkpoints/patchtst_best.pt")
CARLA_CKPT    = Path("ml/data/checkpoints/carla_best.pt")
PARQUET       = Path("ml/data/sim_data/results_20000p_14d.parquet")
SPLIT_FILE    = Path("ml/data/patient_split.json")
FIGURES_DIR   = Path("ml/figures")


# ── shared helpers ────────────────────────────────────────────────────────────

def _metrics(scores: np.ndarray, labels: dict[str, np.ndarray]) -> tuple[dict, dict]:
    auprc = {
        cls: float(average_precision_score(labels[cls], scores))
        if labels[cls].sum() > 0 else float("nan")
        for cls in ANOMALY_CLASSES
    }
    auroc = {
        cls: float(roc_auc_score(labels[cls], scores))
        if labels[cls].sum() > 0 else float("nan")
        for cls in ANOMALY_CLASSES
    }
    return auprc, auroc


# ── PatchTST scoring ──────────────────────────────────────────────────────────

def score_patchtst(
    checkpoint: Path,
    test_loader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    model = PatchTST().to(device)
    ckpt  = torch.load(checkpoint, map_location=device)
    # PatchTST checkpoints are saved as {"model_state": ..., "epoch": ..., ...}
    state = ckpt["model_state"] if isinstance(ckpt, dict) and "model_state" in ckpt else ckpt
    model.load_state_dict(state)
    model.eval()
    scores, labels = patchtst_score_dataset(model, test_loader, device)
    return scores, labels


# ── CARLA scoring ─────────────────────────────────────────────────────────────

def score_carla(
    checkpoint: Path,
    train_ids: list[str],
    test_loader: DataLoader,
    device: torch.device,
    parquet: Path,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    backbone = PatchTST()
    model    = CARLAModel(backbone)
    model.load_state_dict(torch.load(checkpoint, map_location=device))
    model.to(device)
    model.eval()

    scalers = load_scalers()

    # Fit GMM on normal training embeddings
    print("  Embedding training set for GMM fitting …")
    raw_train    = load_patients(train_ids, parquet)
    scaled_train = {pid: _apply_scalers(arr, scalers, inplace=True)   # no 8 GB copy
                    for pid, arr in raw_train.items()}
    train_ds     = ContrastiveDataset(scaled_train, stride=15)
    train_loader = DataLoader(train_ds, batch_size=512, shuffle=False, num_workers=4)
    train_emb, train_normal = embed_dataset(model, train_loader, device)
    normal_emb = train_emb[train_normal == 1]
    pca, gmm   = fit_gmm(normal_emb)

    # Score test set (reuse GlucoseWindowDataset from test_loader for labels)
    print("  Scoring test set …")
    # numpy chunks, not Python floats — stride-1 test scoring is 80M windows
    all_scores: list[np.ndarray]            = []
    all_labels: dict[str, list[np.ndarray]] = {cls: [] for cls in ANOMALY_CLASSES}

    with torch.no_grad():
        for x, label_dict in test_loader:
            z      = model.encode(x.to(device))
            scores = score_with_gmm(pca, gmm, z.cpu().numpy())
            all_scores.append(scores)
            for cls in ANOMALY_CLASSES:
                all_labels[cls].append(label_dict[cls].numpy())

    scores_arr = np.concatenate(all_scores).astype(np.float32)
    labels_arr = {cls: np.concatenate(v).astype(np.float32) for cls, v in all_labels.items()}
    return scores_arr, labels_arr


# ── table printing ────────────────────────────────────────────────────────────

def print_table(
    pt_auprc: dict, pt_auroc: dict,
    ca_auprc: dict, ca_auroc: dict,
    prevalence: dict,
) -> None:
    header = f"{'Class':<12} {'Prev':>6}  {'AUPRC-PatchTST':>14}  {'AUPRC-CARLA':>11}  {'AUROC-PatchTST':>14}  {'AUROC-CARLA':>11}"
    print("\n" + header)
    print("-" * len(header))
    for cls in ANOMALY_CLASSES:
        pt_ap = pt_auprc[cls]
        ca_ap = ca_auprc[cls]
        winner_ap = "◀" if ca_ap > pt_ap else ("▶" if pt_ap > ca_ap else " ")
        print(
            f"{cls:<12} {prevalence[cls]:>5.2%}  "
            f"{pt_ap:>14.4f}  {ca_ap:>11.4f} {winner_ap} "
            f"{pt_auroc[cls]:>14.4f}  {ca_auroc[cls]:>11.4f}"
        )
    mean_pt = np.nanmean(list(pt_auprc.values()))
    mean_ca = np.nanmean(list(ca_auprc.values()))
    print("-" * len(header))
    print(f"{'mean AUPRC':<12} {'':>6}  {mean_pt:>14.4f}  {mean_ca:>11.4f}")


# ── bar chart ─────────────────────────────────────────────────────────────────

def save_bar_chart(
    pt_auprc: dict, ca_auprc: dict, prevalence: dict,
) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    x    = np.arange(len(ANOMALY_CLASSES))
    w    = 0.25
    fig, ax = plt.subplots(figsize=(10, 5))

    ax.bar(x - w, [pt_auprc[c] for c in ANOMALY_CLASSES], w, label="PatchTST", color="#4C72B0")
    ax.bar(x,     [ca_auprc[c] for c in ANOMALY_CLASSES], w, label="CARLA",    color="#DD8452")
    ax.bar(x + w, [prevalence[c] for c in ANOMALY_CLASSES], w, label="Prevalence (random baseline)",
           color="#999999", alpha=0.6)

    ax.set_xticks(x)
    ax.set_xticklabels(ANOMALY_CLASSES, fontsize=11)
    ax.set_ylabel("AUPRC", fontsize=12)
    ax.set_title("PatchTST vs CARLA — AUPRC per anomaly class", fontsize=13)
    ax.legend(fontsize=10)
    ax.set_ylim(0, max(max(pt_auprc.values()), max(ca_auprc.values())) * 1.3)
    ax.yaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)

    out = FIGURES_DIR / "model_comparison.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"\nFigure saved → {out}")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="PatchTST vs CARLA comparison")
    parser.add_argument("--patchtst_ckpt", type=Path, default=PATCHTST_CKPT)
    parser.add_argument("--carla_ckpt",    type=Path, default=CARLA_CKPT)
    parser.add_argument("--parquet",       type=Path, default=PARQUET)
    parser.add_argument("--smoke_test", action="store_true",
                        help="10 test patients only — fast sanity check")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    split     = json.loads(SPLIT_FILE.read_text())
    train_ids = split["train"]
    test_ids  = split["test"]
    if args.smoke_test:
        train_ids = train_ids[:10]
        test_ids  = test_ids[:10]

    # Build shared test loader (GlucoseWindowDataset for per-class labels)
    print("Building test dataset …")
    # include_train=False: scalers come from the cache written during
    # pretraining, so the 12k-patient train split is never loaded here.
    # Keep the full train list in the split — if the scaler cache is ever
    # missing, scalers must be refit on all train patients, not a subset.
    _, _, test_ds = build_datasets(
        split={"train": split["train"], "val": split["val"], "test": test_ids},
        parquet=args.parquet,
        eval_stride=EVAL_STRIDE if not args.smoke_test else 15,
        include_train=False,
        include_val=False,
    )
    test_loader = DataLoader(test_ds, batch_size=512, shuffle=False, num_workers=4)

    # ── PatchTST ───────────────────────────────────────────────────────────────
    print(f"\n[PatchTST] Loading checkpoint: {args.patchtst_ckpt}")
    pt_scores, pt_labels = score_patchtst(args.patchtst_ckpt, test_loader, device)
    pt_auprc, pt_auroc   = _metrics(pt_scores, pt_labels)

    # ── CARLA ──────────────────────────────────────────────────────────────────
    print(f"\n[CARLA] Loading checkpoint: {args.carla_ckpt}")
    ca_scores, ca_labels = score_carla(
        args.carla_ckpt, train_ids, test_loader, device, args.parquet
    )
    ca_auprc, ca_auroc   = _metrics(ca_scores, ca_labels)

    prevalence = {cls: float(pt_labels[cls].mean()) for cls in ANOMALY_CLASSES}

    print_table(pt_auprc, pt_auroc, ca_auprc, ca_auroc, prevalence)
    save_bar_chart(pt_auprc, ca_auprc, prevalence)


if __name__ == "__main__":
    main()
