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
    normalize_patients, progress_log, ANOMALY_CLASSES, EVAL_STRIDE,
)
from models.patch_tst.model import PatchTST
from models.patch_tst.anomaly_score import any_anomaly_label
from models.carla.model import CARLAModel
from models.carla.dataset import ContrastiveDataset
import time

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

    n = len(loader); t0 = time.time()
    for i, (windows, labels) in enumerate(loader, 1):
        windows = windows.to(device)
        z = model.encode(windows)          # [B, D_MODEL]
        all_emb.append(z.cpu().numpy())
        all_normal.extend(labels.tolist())
        progress_log(i, n, t0, label="embed")

    return np.concatenate(all_emb, axis=0), np.array(all_normal, dtype=np.int32)


# ── GMM fitting ───────────────────────────────────────────────────────────────

def fit_gmm(
    normal_embeddings: np.ndarray,    # [N_normal, D_MODEL]
    k_grid: list[int] = GMM_K_GRID,
    max_samples: int = 300_000,
    seed: int = 42,
) -> tuple[PCA, GaussianMixture]:
    """
    Fit PCA + GMM on normal training embeddings.

    PCA: retains 95% of variance, reduces dimensionality for numerical stability.
    GMM: K selected by BIC over k_grid. reg_covar=1e-4 guarantees positive definiteness.

    Subsampling
    -----------
    At stride 15 the 12k-patient train split yields ~14M normal embeddings.
    EM with full covariance over that many points is hours-to-days on CPU and
    buys nothing — a K≤40 GMM has only a few thousand parameters, so 300k
    points already over-determines it ~100×. We fit on a fixed-seed random
    sample of max_samples (set max_samples=0 to disable). All test windows are
    still scored against the fitted GMM; only the *fit* is subsampled.

    Returns (pca, gmm) fitted objects — save them with joblib for reuse.
    """
    n_total = len(normal_embeddings)
    if max_samples and n_total > max_samples:
        idx = np.random.default_rng(seed).choice(n_total, max_samples, replace=False)
        normal_embeddings = normal_embeddings[idx]
        print(f"GMM fit: subsampled {n_total:,} → {max_samples:,} normal embeddings (seed={seed})")

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
    parser.add_argument("--gmm_sample", type=int, default=300_000,
                        help="max normal embeddings for GMM fit (0 = use all)")
    parser.add_argument("--norm", choices=["per_patient", "global"], default="per_patient",
                        help="normalization mode — MUST match the pretrain run")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # ── load model ─────────────────────────────────────────────────────────────
    backbone = PatchTST()
    model    = CARLAModel(backbone)
    ckpt  = torch.load(args.checkpoint, map_location=device)
    state = ckpt["model_state"] if isinstance(ckpt, dict) and "model_state" in ckpt else ckpt
    model.load_state_dict(state)
    model.to(device)
    print(f"Loaded checkpoint: {args.checkpoint}")

    # ── load data ──────────────────────────────────────────────────────────────
    split   = json.loads(SPLIT_FILE.read_text())
    # global mode needs population scalers; per-patient needs none
    scalers = load_scalers() if args.norm == "global" else None

    def make_contrastive_loader(ids: list[str], stride: int) -> DataLoader:
        raw    = load_patients(ids, args.parquet)
        scaled = normalize_patients(raw, norm=args.norm, scalers=scalers, inplace=True)
        ds     = ContrastiveDataset(scaled, stride=stride)
        return DataLoader(ds, batch_size=256, shuffle=False, num_workers=4)

    # Training embeddings for GMM fitting. stride=60 not 15: fit_gmm subsamples
    # to ~300k anyway, so embedding all 16M stride-15 windows is pure waste.
    # stride 60 → ~4M windows (still >>300k), ~4× faster, no quality loss.
    print("Embedding training set (stride 60) …")
    train_loader            = make_contrastive_loader(split["train"], stride=60)
    train_emb, train_normal = embed_dataset(model, train_loader, device)
    normal_emb = train_emb[train_normal == 1]
    print(f"Normal training embeddings: {normal_emb.shape}")

    # ── fit GMM ────────────────────────────────────────────────────────────────
    pca, gmm = fit_gmm(normal_emb, max_samples=args.gmm_sample)

    # ── test set evaluation ────────────────────────────────────────────────────
    # For evaluation we need per-window anomaly class labels (not just is_normal).
    # Re-use GlucoseWindowDataset for test set — it returns the full label dict.
    print("Scoring test set …")
    _, _, test_ds = build_datasets(
        split=split, parquet=args.parquet, eval_stride=EVAL_STRIDE,
        include_train=False, include_val=False, norm=args.norm,
    )

    test_loader = DataLoader(test_ds, batch_size=256, shuffle=False, num_workers=4)

    # numpy chunks, not Python floats — 80M stride-1 windows × 6 columns of
    # Python floats would cost >15 GB
    all_scores: list[np.ndarray]               = []
    all_labels: dict[str, list[np.ndarray]]    = {cls: [] for cls in ANOMALY_CLASSES}

    model.eval()
    n = len(test_loader); t0 = time.time()
    with torch.no_grad():
        for i, (x, label_dict) in enumerate(test_loader, 1):
            z      = model.encode(x.to(device))
            scores = score_with_gmm(pca, gmm, z.cpu().numpy())
            all_scores.append(scores)
            for cls in ANOMALY_CLASSES:
                all_labels[cls].append(label_dict[cls].numpy())
            progress_log(i, n, t0, label="score")

    scores_arr = np.concatenate(all_scores).astype(np.float32)
    labels_arr = {cls: np.concatenate(v).astype(np.float32) for cls, v in all_labels.items()}

    # headline detection metric: any-anomaly (any class vs normal), free of the
    # cross-class contamination that depresses the per-class numbers
    any_lbl = any_anomaly_label(labels_arr)
    any_prev = float(any_lbl.mean())
    print(f"\nANY-ANOMALY detection (any class vs normal | random baseline ≈ {any_prev:.2%})")
    if any_lbl.sum() > 0:
        print(f"  AUPRC={average_precision_score(any_lbl, scores_arr):.4f}  "
              f"AUROC={roc_auc_score(any_lbl, scores_arr):.4f}")

    auprc = auprc_per_class(scores_arr, labels_arr)
    auroc = auroc_per_class(scores_arr, labels_arr)

    # ── per-class results (classification-flavoured; see any_anomaly_label) ────
    print(f"\n{'Class':<12} {'AUPRC':>8} {'Prevalence':>12} {'AUROC':>8}")
    print("-" * 44)
    for cls in ANOMALY_CLASSES:
        prev = labels_arr[cls].mean()
        print(f"{cls:<12} {auprc[cls]:>8.4f} {prev:>12.2%} {auroc[cls]:>8.4f}")


if __name__ == "__main__":
    main()
