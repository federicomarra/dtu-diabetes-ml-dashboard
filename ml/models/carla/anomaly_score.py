"""
CARLA anomaly scoring and evaluation.

Anomaly score: GMM negative log-likelihood
-------------------------------------------
After contrastive pretraining, the encoder maps normal windows into a compact
cluster in latent space and anomaly windows farther away. We fit a Gaussian
Mixture Model on the normal training embeddings to capture the shape of the
normal manifold (multiple components = multiple patient archetypes).

Anomaly score = -gmm.score_samples(pca.transform(z))
Higher score = more anomalous.

PCA before GMM
--------------
PCA removes near-zero variance dimensions first, which would otherwise destabilise
the GMM's covariance matrix. We keep 95% of variance. reg_covar=1e-4 adds εI
regularisation to all covariance matrices (sklearn applies this internally via
Cholesky decomposition — no manual implementation needed).

K selection
-----------
K is selected by BIC over K ∈ {2, 3, 5, 8, 10}. Fit once after training on
normal training embeddings. Actual optimal K depends on the encoder's learned
latent geometry and will be reported in CARLA.md after the first HPC run.

Evaluation
----------
AUPRC is the PRIMARY metric (same as PatchTST).
AUROC is reported as secondary for comparability.
Results are printed per anomaly class (missed, late, large, prolonged, anaerobic).

Usage
-----
    python ml/models/carla/anomaly_score.py
    python ml/models/carla/anomaly_score.py --checkpoint ml/data/checkpoints/carla_best.pt
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from sklearn.decomposition import PCA
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.mixture import GaussianMixture
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dataset import (
    build_datasets, load_patients, load_scalers,
    _apply_scalers, ANOMALY_CLASSES, EVAL_STRIDE,
)
from models.patch_tst.model import PatchTST
from models.carla.model import CARLAModel
from models.carla.dataset import ContrastiveDataset

# ── config ────────────────────────────────────────────────────────────────────

CHECKPOINT  = Path("ml/data/checkpoints/carla_best.pt")
PARQUET     = Path("ml/data/sim_data/results_20000p_14d.parquet")
SPLIT_FILE  = Path("ml/data/patient_split.json")
SCALER_FILE = Path("ml/data/scalers.json")
GMM_K_GRID  = [2, 3, 5, 8, 10, 15, 20, 30, 40]   # BIC search grid — extended; smoke test hit edge at K=20


# ── embedding extraction ──────────────────────────────────────────────────────

@torch.no_grad()
def embed_dataset(
    model:  CARLAModel,
    loader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Run encoder on every window in the loader.

    Returns
    -------
    embeddings : float32 array [N, D_MODEL]
    is_normal  : int array [N]  — 1 for normal windows, 0 for anomaly
    """
    model.eval()
    all_emb:    list[np.ndarray] = []
    all_normal: list[int]        = []

    for windows, labels in loader:
        windows = windows.to(device)
        z = model.encode(windows)          # [B, D_MODEL]
        all_emb.append(z.cpu().numpy())
        all_normal.extend(labels.tolist())

    return np.concatenate(all_emb, axis=0), np.array(all_normal, dtype=np.int32)


# ── GMM fitting ───────────────────────────────────────────────────────────────

def fit_gmm(
    normal_embeddings: np.ndarray,    # [N_normal, D_MODEL]
    k_grid: list[int] = GMM_K_GRID,
) -> tuple[PCA, GaussianMixture]:
    """
    Fit PCA + GMM on normal training embeddings.

    PCA: retains 95% of variance, reduces dimensionality for numerical stability.
    GMM: K selected by BIC over k_grid. reg_covar=1e-4 guarantees positive definiteness.

    Returns (pca, gmm) fitted objects — save them with joblib for reuse.
    """
    pca = PCA(n_components=0.95, random_state=42)
    reduced = pca.fit_transform(normal_embeddings)
    print(f"PCA: {normal_embeddings.shape[1]} → {reduced.shape[1]} dims (95% variance)")

    best_k, best_bic, best_gmm = k_grid[0], float("inf"), None
    for k in k_grid:
        gmm = GaussianMixture(
            n_components=k,
            covariance_type="full",
            reg_covar=1e-4,
            random_state=42,
            max_iter=200,
        )
        gmm.fit(reduced)
        bic = gmm.bic(reduced)
        print(f"  K={k:2d}  BIC={bic:.1f}")
        if bic < best_bic:
            best_bic, best_k, best_gmm = bic, k, gmm

    assert best_gmm is not None   # k_grid is always non-empty
    print(f"Selected K={best_k} (BIC={best_bic:.1f})")
    return pca, best_gmm


# ── scoring ───────────────────────────────────────────────────────────────────

def score_with_gmm(
    pca: PCA,
    gmm: GaussianMixture,
    embeddings: np.ndarray,    # [N, D_MODEL]
) -> np.ndarray:
    """
    Anomaly score = -log_likelihood under GMM.
    Higher score = more anomalous.
    """
    reduced = pca.transform(embeddings)
    return -gmm.score_samples(reduced).astype(np.float32)   # [N]


# ── metrics ───────────────────────────────────────────────────────────────────

def auprc_per_class(
    scores: np.ndarray,
    labels: dict[str, np.ndarray],
) -> dict[str, float]:
    """AUPRC per anomaly class. PRIMARY metric. Returns nan if no positives."""
    result: dict[str, float] = {}
    for cls in ANOMALY_CLASSES:
        y = labels[cls]
        result[cls] = float(average_precision_score(y, scores)) if y.sum() > 0 else float("nan")
    return result


def auroc_per_class(
    scores: np.ndarray,
    labels: dict[str, np.ndarray],
) -> dict[str, float]:
    """AUROC per anomaly class. Secondary metric. Returns nan if no positives."""
    result: dict[str, float] = {}
    for cls in ANOMALY_CLASSES:
        y = labels[cls]
        result[cls] = float(roc_auc_score(y, scores)) if y.sum() > 0 else float("nan")
    return result


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CARLA anomaly scoring")
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--parquet",    type=Path, default=PARQUET)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # ── load model ─────────────────────────────────────────────────────────────
    backbone = PatchTST()
    model    = CARLAModel(backbone)
    model.load_state_dict(torch.load(args.checkpoint, map_location=device))
    model.to(device)
    print(f"Loaded checkpoint: {args.checkpoint}")

    # ── load data ──────────────────────────────────────────────────────────────
    split   = json.loads(SPLIT_FILE.read_text())
    scalers = load_scalers()

    def make_contrastive_loader(ids: list[str], stride: int) -> DataLoader:
        raw    = load_patients(ids, args.parquet)
        scaled = {pid: _apply_scalers(arr, scalers) for pid, arr in raw.items()}
        ds     = ContrastiveDataset(scaled, stride=stride)
        return DataLoader(ds, batch_size=256, shuffle=False, num_workers=4)

    # Training embeddings: stride=15 (fast), only normal windows needed for GMM
    print("Embedding training set …")
    train_loader            = make_contrastive_loader(split["train"], stride=15)
    train_emb, train_normal = embed_dataset(model, train_loader, device)
    normal_emb = train_emb[train_normal == 1]
    print(f"Normal training embeddings: {normal_emb.shape}")

    # ── fit GMM ────────────────────────────────────────────────────────────────
    pca, gmm = fit_gmm(normal_emb)

    # ── test set evaluation ────────────────────────────────────────────────────
    # For evaluation we need per-window anomaly class labels (not just is_normal).
    # Re-use GlucoseWindowDataset for test set — it returns the full label dict.
    print("Scoring test set …")
    _, _, test_ds = build_datasets(split=split, parquet=args.parquet, eval_stride=EVAL_STRIDE)

    test_loader = DataLoader(test_ds, batch_size=256, shuffle=False, num_workers=4)

    all_scores: list[float]                    = []
    all_labels: dict[str, list[float]]         = {cls: [] for cls in ANOMALY_CLASSES}

    model.eval()
    with torch.no_grad():
        for x, label_dict in test_loader:
            z      = model.encode(x.to(device))
            scores = score_with_gmm(pca, gmm, z.cpu().numpy())
            all_scores.extend(scores.tolist())
            for cls in ANOMALY_CLASSES:
                all_labels[cls].extend(label_dict[cls].tolist())

    scores_arr = np.array(all_scores, dtype=np.float32)
    labels_arr = {cls: np.array(v, dtype=np.float32) for cls, v in all_labels.items()}

    auprc = auprc_per_class(scores_arr, labels_arr)
    auroc = auroc_per_class(scores_arr, labels_arr)

    # ── print results ──────────────────────────────────────────────────────────
    print(f"\n{'Class':<12} {'AUPRC':>8} {'Prevalence':>12} {'AUROC':>8}")
    print("-" * 44)
    for cls in ANOMALY_CLASSES:
        prev = labels_arr[cls].mean()
        print(f"{cls:<12} {auprc[cls]:>8.4f} {prev:>12.2%} {auroc[cls]:>8.4f}")


if __name__ == "__main__":
    main()
