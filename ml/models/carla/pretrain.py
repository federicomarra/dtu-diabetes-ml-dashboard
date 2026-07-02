"""
CARLA contrastive pretraining — SUPERVISED (oracle-negative) variant.

IMPORTANT: this is not the published CARLA. Negatives here are the simulator's
ground-truth anomaly windows, so this model sees labels PatchTST never sees and
cannot run on unlabelled real data. Treat its synthetic AUPRC as an oracle upper
bound, not a fair peer to PatchTST. The label-free CARLA (synthetic anomaly
injection — the actual Darban et al. method, fair vs PatchTST and real-data
capable) is planned separately. See ml/docs/CARLA.md (top note).

What this script does
---------------------
1. Loads the 500-patient dataset via load_patients() + ContrastiveDataset
2. Each batch: mix of normal (70%) and anomaly (30%) windows
3. Forward pass → z_proj [B, 64] + is_normal [B]
4. SupCon loss: normal windows attract each other, anomaly windows repel
5. Validates on val set every epoch (mean embedding distance as a proxy metric)
6. Saves best checkpoint (lowest val SupCon loss) to ml/data/checkpoints/

SupCon loss (asymmetric anchoring)
-----------------------------------
Only normal windows compute the loss. For each normal anchor i:
  - Positives P(i): all other normal windows in the batch
  - Denominator A(i): all other windows (normal + anomaly)
  - L_i = -1/|P(i)| × Σ_{p∈P(i)} log(exp(sim(z_i,z_p)/τ) / Σ_{a∈A(i)} exp(sim(z_i,z_a)/τ))
Anomaly windows push from the denominator but never anchor.

τ = 0.07 (temperature) — lower = sharper contrast, higher = smoother.

HPC usage
---------
    bsub < ml/models/carla/hpc_carla.sh         (submit job)
    python ml/models/carla/pretrain.py           (local smoke test)

Key flags
---------
    --epochs       number of training epochs (default 30)
    --batch_size   samples per step (default 256 for HPC, try 64 locally)
    --lr           initial learning rate (default 1e-4)
    --tau          SupCon temperature (default 0.07)
    --smoke_test   run 2 epochs on 10 patients to verify everything works
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.nn.utils.clip_grad import clip_grad_norm_
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dataset import (
    load_patients, fit_scalers, load_scalers,
    normalize_patients, make_patient_split, set_seed,
    WINDOW_LEN, N_CHANNELS,
)
from models.patch_tst.model import PatchTST
from models.carla.model import CARLAModel
from models.carla.dataset import ContrastiveDataset, ContrastiveBatchSampler

# ── paths ──────────────────────────────────────────────────────────────────────

CHECKPOINT_DIR = Path("ml/data/checkpoints")
LOG_PATH       = Path("ml/data/checkpoints/carla_pretrain_log.json")
PARQUET        = Path("ml/data/sim_data/results_20000p_14d.parquet")
SPLIT_FILE     = Path("ml/data/patient_split.json")
SCALER_FILE    = Path("ml/data/scalers.json")


# ── loss ───────────────────────────────────────────────────────────────────────

def supcon_loss(
    z_proj:    torch.Tensor,   # [B, D_proj] — L2-normalised projections
    is_normal: torch.Tensor,   # [B]         — 1 for normal, 0 for anomaly
    tau:       float = 0.07,
) -> torch.Tensor:
    """
    Supervised Contrastive Loss with asymmetric anchoring.

    Only normal windows (is_normal == 1) compute the loss.
    Anomaly windows appear in the denominator of all normal anchors,
    creating repulsion — but never anchor their own loss term.

    Steps:
    1. Compute all pairwise cosine similarities → [B, B] matrix.
       (z_proj is already L2-normalised, so dot product = cosine similarity)
    2. Scale by temperature τ.
    3. For each normal anchor i, sum exp(sim) over all j ≠ i → denominator.
    4. For each normal anchor i, sum log(numerator / denominator) over positives P(i).
    5. Normalise by |P(i)| and average over all normal anchors.

    Returns scalar loss. Returns 0 if no normal anchor has at least one positive.
    """
    B = z_proj.size(0)
    device = z_proj.device

    # [B, B] pairwise cosine similarity — diagonal is self-similarity (excluded below)
    sim = torch.mm(z_proj, z_proj.T) / tau   # [B, B]

    # Mask to exclude self-similarity from denominator
    not_self = ~torch.eye(B, dtype=torch.bool, device=device)   # [B, B]

    # Positive mask: normal anchor i, normal window j, j ≠ i
    normal_mask = is_normal.bool()                               # [B]
    pos_mask = (
        normal_mask.unsqueeze(0) &   # j is normal
        normal_mask.unsqueeze(1) &   # i is normal
        not_self                     # j ≠ i
    )  # [B, B]

    # Log-sum-exp denominator for each anchor (log of sum over all j ≠ i)
    # Numerically stable: subtract row-max before exponentiating
    sim_masked = sim.masked_fill(~not_self, float('-inf'))       # [B, B]
    log_denom = torch.logsumexp(sim_masked, dim=1)               # [B]

    # For each positive pair (i, j): log(exp(sim_ij/τ) / denominator_i)
    log_prob = sim - log_denom.unsqueeze(1)                      # [B, B]

    # Sum over positives for each normal anchor, normalise by |P(i)|
    n_positives = pos_mask.float().sum(dim=1)                    # [B]
    anchor_loss = -(log_prob * pos_mask).sum(dim=1)              # [B]

    # Only anchors that have at least one positive contribute
    has_positive = n_positives > 0
    if not has_positive.any():
        return torch.tensor(0.0, device=device, requires_grad=True)

    # clamp(min=1) prevents 0/0 — torch.where evaluates both branches in backward,
    # so NaN from 0/0 would pollute gradients even for anchors where condition is False
    anchor_loss = torch.where(has_positive, anchor_loss / n_positives.clamp(min=1), torch.zeros_like(anchor_loss))
    # Average over normal anchors only
    return anchor_loss[normal_mask].mean()


# ── training loop ──────────────────────────────────────────────────────────────

def train_one_epoch(
    model:    CARLAModel,
    loader:   DataLoader,
    optimiser: torch.optim.Optimizer,
    device:   torch.device,
    tau:      float,
    log_every: int = 500,
) -> float:
    model.train()
    total_loss = 0.0
    n = len(loader)
    t0 = time.time()
    for i, (windows, labels) in enumerate(loader, 1):
        windows   = windows.to(device)                           # [B, 120, 3]
        is_normal = labels.to(device)                            # [B]

        _, z_proj = model(windows)                               # [B, 64]
        loss = supcon_loss(z_proj, is_normal, tau)

        optimiser.zero_grad()
        loss.backward()
        clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimiser.step()

        total_loss += loss.item()

        if i % log_every == 0 or i == n:
            el  = time.time() - t0
            ips = i / el
            eta = (n - i) / ips / 60
            print(f"    step {i:>6}/{n}  loss={total_loss/i:.4f}  "
                  f"{ips:.1f} it/s  ETA {eta:.1f}m", flush=True)

    return total_loss / max(n, 1)


@torch.no_grad()
def validate(
    model:  CARLAModel,
    loader: DataLoader,
    device: torch.device,
    tau:    float,
) -> tuple[float, float, float]:
    """
    Val SupCon loss + collapse diagnostics on the ENCODER embedding z.

    SupCon with all-normals-as-positives can collapse every normal window to a
    single point. Then z (what the GMM scores) has ~zero variance and anomaly
    scores become noise — while the loss still looks fine. We monitor z, not
    z_proj, because z is what scoring uses.

    Returns (val_loss, emb_std, mean_cos):
      emb_std : mean per-dim std of z across the val set → 0.0 means collapsed.
      mean_cos: mean off-diagonal cosine of z on a capped sample → 1.0 means
                collapsed (all embeddings point the same way).
    """
    model.eval()
    total_loss = 0.0
    n_batches  = 0
    z_chunks: list[torch.Tensor] = []
    for windows, labels in loader:
        windows   = windows.to(device)
        is_normal = labels.to(device)
        z, z_proj = model(windows)
        loss = supcon_loss(z_proj, is_normal, tau)
        total_loss += loss.item()
        n_batches  += 1
        z_chunks.append(z.cpu())

    z_all   = torch.cat(z_chunks)                       # [N, D]
    emb_std = z_all.std(dim=0).mean().item()            # → 0 if collapsed

    sample  = F.normalize(z_all[:2048], dim=1)          # cap to keep O(n²) cheap
    n       = sample.size(0)
    if n > 1:
        cos = sample @ sample.T
        mean_cos = ((cos.sum() - n) / (n * (n - 1))).item()   # exclude diagonal
    else:
        mean_cos = float("nan")

    return total_loss / max(n_batches, 1), emb_std, mean_cos


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CARLA contrastive pretraining")
    parser.add_argument("--epochs",     type=int,   default=30)
    parser.add_argument("--batch_size", type=int,   default=256)
    parser.add_argument("--lr",         type=float, default=1e-4)
    parser.add_argument("--tau",        type=float, default=0.07)
    parser.add_argument("--normal_ratio", type=float, default=0.7)
    parser.add_argument("--norm", choices=["per_patient", "global"], default="per_patient",
                        help="normalization mode (default: per_patient, spec)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    parser.add_argument("--val_patients", type=int, default=800,
                        help="cap val to N patients for fast per-epoch checkpoint selection")
    parser.add_argument("--parquet",    type=Path,  default=PARQUET)
    parser.add_argument("--smoke_test", action="store_true",
                        help="2 epochs on 10 patients — verify setup works")
    args = parser.parse_args()
    set_seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # ── split ──────────────────────────────────────────────────────────────────
    if SPLIT_FILE.exists():
        split = json.loads(SPLIT_FILE.read_text())
    else:
        split = make_patient_split(args.parquet)

    train_ids = split["train"]
    val_ids   = split["val"]
    if args.smoke_test:
        train_ids = train_ids[:10]
        val_ids   = val_ids[:5]
        args.epochs = 2
    else:
        # cap val for a fast, stable checkpoint-selection signal (see PatchTST)
        val_ids = val_ids[:args.val_patients]

    # ── data ───────────────────────────────────────────────────────────────────
    print(f"Loading {len(train_ids)} training patients …")
    train_raw = load_patients(train_ids, args.parquet)

    # Global mode only: fit/cache population scalers on train. Per-patient mode
    # needs none — each patient self-normalizes.
    scalers = None
    if args.norm == "global":
        if SCALER_FILE.exists():
            cached = load_scalers()
            if cached.get("_parquet") == str(args.parquet):   # reject stale 500p cache
                scalers = cached
                print(f"Re-using cached scalers  ←  {SCALER_FILE}")
        if scalers is None:
            # never tag a smoke-test fit (10 patients) as valid for the full cohort
            scalers = fit_scalers(
                train_raw, parquet=args.parquet if not args.smoke_test else None
            )

    # inplace=True: normalize the arrays where they sit instead of copying the
    # ~8 GB training dict
    train_scaled = normalize_patients(train_raw, norm=args.norm, scalers=scalers, inplace=True)
    del train_raw

    print(f"Loading {len(val_ids)} val patients …")
    val_raw    = load_patients(val_ids, args.parquet)
    val_scaled = normalize_patients(val_raw, norm=args.norm, scalers=scalers, inplace=True)
    del val_raw

    train_ds = ContrastiveDataset(train_scaled)
    val_ds   = ContrastiveDataset(val_scaled)

    print(f"Train: {train_ds.n_normal:,} normal + {train_ds.n_anomaly:,} anomaly windows")
    print(f"Val:   {val_ds.n_normal:,}  normal + {val_ds.n_anomaly:,}  anomaly windows")

    # num_workers=4 is safe again: the dataset now holds a few large numpy
    # arrays, so forked workers share pages copy-on-write without duplicating
    # them (the old pandas-object layout forced per-worker copies).
    train_sampler = ContrastiveBatchSampler(train_ds, args.batch_size, args.normal_ratio)
    train_loader  = DataLoader(train_ds, batch_sampler=train_sampler, num_workers=4, pin_memory=True)
    # Val loader: plain shuffle, no composition control needed (just measuring loss)
    val_loader    = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=4)

    # ── model ──────────────────────────────────────────────────────────────────
    backbone = PatchTST().to(device)
    model    = CARLAModel(backbone).to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = ReduceLROnPlateau(optimiser, mode="min", factor=0.5, patience=3, min_lr=1e-6)

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    best_val_loss = float("inf")
    log: list[dict] = []

    # ── training ───────────────────────────────────────────────────────────────
    COLLAPSE_STD = 1e-3   # mean per-dim std of z below this ⇒ representation collapse
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        train_loss = train_one_epoch(model, train_loader, optimiser, device, args.tau)
        val_loss, emb_std, mean_cos = validate(model, val_loader, device, args.tau)
        scheduler.step(val_loss)
        elapsed = time.time() - t0

        lr_now = optimiser.param_groups[0]["lr"]
        print(f"Epoch {epoch:3d}/{args.epochs}  train={train_loss:.4f}  val={val_loss:.4f}  "
              f"emb_std={emb_std:.4f}  mean_cos={mean_cos:.3f}  lr={lr_now:.2e}  {elapsed:.0f}s")
        if emb_std < COLLAPSE_STD:
            print(f"  ⚠ COLLAPSE WARNING: encoder embedding std {emb_std:.2e} < {COLLAPSE_STD:.0e} — "
                  f"GMM scoring will be noise. Consider same-patient positives or a variance term.")

        log.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss,
                    "emb_std": emb_std, "mean_cos": mean_cos, "lr": lr_now})
        LOG_PATH.write_text(json.dumps(log, indent=2))

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(
                {
                    "epoch":       epoch,
                    "model_state": model.state_dict(),
                    "val_loss":    val_loss,
                    "emb_std":     emb_std,
                    "mean_cos":    mean_cos,
                    "args":        vars(args),
                },
                CHECKPOINT_DIR / "carla_best.pt",
            )
            print(f"  ✓ saved best checkpoint (val={best_val_loss:.4f})")

    torch.save(
        {"epoch": args.epochs, "model_state": model.state_dict(), "args": vars(args)},
        CHECKPOINT_DIR / "carla_final.pt",
    )
    print(f"\nDone. Best val loss: {best_val_loss:.4f}")
    print(f"Checkpoint: {CHECKPOINT_DIR}/carla_best.pt")


if __name__ == "__main__":
    main()
