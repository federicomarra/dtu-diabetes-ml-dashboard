"""
PatchTST masked patch pretraining.

What this script does
---------------------
1. Loads the 500-patient dataset via build_datasets()
2. Each epoch: forward pass with mask_ratio=0.4, MSE loss on hidden patches only
3. Validates on val set every epoch (no masking → checks reconstruction quality)
4. Saves the best checkpoint (lowest val loss) to ml/data/checkpoints/

Loss
----
MSE computed only on the masked (hidden) patches.
The patch-level mask [B, 6] is expanded to minute-level [B, 120, C] by
repeating each patch flag across its 20 constituent minutes.

HPC usage
---------
    bsub < ml/models/patch_tst/hpc_patchtst.sh        (submit job)
    python ml/models/patch_tst/pretrain.py            (local smoke test)

Key flags
---------
    --epochs       number of training epochs (default 15)
    --batch_size   samples per step (default 256 for HPC, try 64 locally)
    --lr           initial learning rate (default 1e-4)
    --smoke_test   run 2 epochs on 10 patients to verify everything works
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn
from torch.nn.utils.clip_grad import clip_grad_norm_
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader

# make ml/ importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dataset import build_datasets, WINDOW_LEN, N_CHANNELS
from models.patch_tst.model import PatchTST, MASK_RATIO, PATCH_LEN

# ── paths ─────────────────────────────────────────────────────────────────────

CHECKPOINT_DIR = Path("ml/data/checkpoints")
LOG_PATH       = Path("ml/data/checkpoints/pretrain_log.json")
PARQUET        = Path("ml/data/sim_data/results_20000p_14d.parquet")


# ── loss ──────────────────────────────────────────────────────────────────────

def masked_mse_loss(
    recon: torch.Tensor,   # [B, 120, C] — model reconstruction
    target: torch.Tensor,  # [B, 120, C] — original (unmasked) signal
    mask: torch.Tensor,    # [B, 6]      — True where patch was hidden
) -> torch.Tensor:
    """
    MSE computed only on the hidden patches.

    Steps:
      1. Expand patch mask [B, 6] → minute mask [B, 120] using repeat_interleave
         (each patch flag is repeated PATCH_LEN=20 times along the time axis)
      2. Expand minute mask [B, 120] → [B, 120, C] to cover all channels
      3. Compute MSE only where mask is True
    """
    # [B, 6] → [B, 120]: each patch flag repeated 20 times
    mask_min = mask.repeat_interleave(PATCH_LEN, dim=1)         # [B, 120]

    # [B, 120] → [B, 120, C]: same mask applied to all channels
    mask_min = mask_min.unsqueeze(-1).expand_as(recon)          # [B, 120, C]

    # squared error everywhere, then zero-out visible patches
    sq_err = (recon - target) ** 2                              # [B, 120, C]

    # mean over masked positions only
    # clamp denominator to avoid division by zero on edge cases
    n_masked = mask_min.sum().clamp(min=1)
    return (sq_err * mask_min).sum() / n_masked


# ── train / eval loops ────────────────────────────────────────────────────────

def train_one_epoch(
    model: PatchTST,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> float:
    """One full pass over the training set. Returns mean loss."""
    model.train()
    total_loss = 0.0

    for x, _ in loader:             # _ = labels dict, not used during pretraining
        x = x.to(device)            # [B, 120, 3]

        recon, mask = model(x, mask_ratio=MASK_RATIO)
        loss = masked_mse_loss(recon, x, mask)

        optimizer.zero_grad()
        loss.backward()
        # gradient clipping: prevents exploding gradients, safe default for transformers
        clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        total_loss += loss.item()

    return total_loss / len(loader)


@torch.no_grad()
def eval_one_epoch(
    model: PatchTST,
    loader: DataLoader,
    device: torch.device,
) -> float:
    """
    Validation pass — no masking.

    We measure full reconstruction MSE here (not masked), which tells us
    how well the model has learned the underlying signal structure.
    """
    model.eval()
    total_loss = 0.0

    for x, _ in loader:
        x = x.to(device)
        recon, _ = model(x, mask_ratio=0.0)   # no masking at eval time
        loss = nn.functional.mse_loss(recon, x)
        total_loss += loss.item()

    return total_loss / len(loader)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="PatchTST pretraining")
    parser.add_argument("--epochs",     type=int,   default=15)
    parser.add_argument("--batch_size", type=int,   default=256)
    parser.add_argument("--lr",         type=float, default=1e-4)
    parser.add_argument("--num_workers",type=int,   default=4)
    parser.add_argument("--smoke_test", action="store_true",
                        help="2 epochs, 10 patients — quick sanity check")
    args = parser.parse_args()

    # smoke test: override for a fast local run
    if args.smoke_test:
        args.epochs     = 2
        args.batch_size = 32
        args.num_workers = 0

    # ── device ────────────────────────────────────────────────────────────────
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # ── data ──────────────────────────────────────────────────────────────────
    max_per_split = 10 if args.smoke_test else None
    print("Building datasets…")
    train_ds, val_ds, _ = build_datasets(
        parquet       = PARQUET,
        max_per_split = max_per_split,
    )
    print(f"  train windows: {len(train_ds):,}  |  val windows: {len(val_ds):,}")

    train_loader = DataLoader(
        train_ds,
        batch_size  = args.batch_size,
        shuffle     = True,               # random order every epoch
        num_workers = args.num_workers,
        pin_memory  = device.type == "cuda",
    )
    val_loader = DataLoader(
        val_ds,
        batch_size  = args.batch_size * 2,  # no gradients → fit more on GPU
        shuffle     = False,
        num_workers = args.num_workers,
        pin_memory  = device.type == "cuda",
    )

    # ── model + optimiser ─────────────────────────────────────────────────────
    model = PatchTST().to(device)
    print(f"Parameters: {sum(p.numel() for p in model.parameters()):,}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)

    # ReduceLROnPlateau: halves lr whenever val loss doesn't improve for 3 epochs.
    # More adaptive than cosine — no T_max to tune, scales naturally from 500 to 20k patients.
    scheduler = ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=3, min_lr=1e-6
    )

    # ── checkpointing ─────────────────────────────────────────────────────────
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    best_val_loss = float("inf")
    log = []   # list of dicts, one per epoch — saved to JSON at the end

    # ── training loop ─────────────────────────────────────────────────────────
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()

        train_loss = train_one_epoch(model, train_loader, optimizer, device)
        val_loss   = eval_one_epoch(model, val_loader, device)
        scheduler.step(val_loss)   # ReduceLROnPlateau monitors val loss directly

        elapsed = time.time() - t0
        lr_now  = optimizer.param_groups[0]["lr"]

        print(
            f"Epoch {epoch:02d}/{args.epochs}  "
            f"train={train_loss:.4f}  val={val_loss:.4f}  "
            f"lr={lr_now:.2e}  ({elapsed:.0f}s)"
        )

        log.append({
            "epoch": epoch, "train_loss": train_loss,
            "val_loss": val_loss, "lr": lr_now,
        })

        # save best checkpoint
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(
                {
                    "epoch":      epoch,
                    "model_state": model.state_dict(),
                    "val_loss":   val_loss,
                    "args":       vars(args),
                },
                CHECKPOINT_DIR / "patchtst_best.pt",
            )
            print(f"  ✓ saved best checkpoint (val={val_loss:.4f})")

    # save final checkpoint regardless of val loss (useful for resuming)
    torch.save(
        {"epoch": args.epochs, "model_state": model.state_dict(), "args": vars(args)},
        CHECKPOINT_DIR / "patchtst_final.pt",
    )

    # save loss log
    LOG_PATH.write_text(json.dumps(log, indent=2))
    print(f"\nDone. Best val loss: {best_val_loss:.4f}")
    print(f"Checkpoints → {CHECKPOINT_DIR}")
    print(f"Loss log    → {LOG_PATH}")


if __name__ == "__main__":
    main()
