"""
XCHANNEL pretraining — cross-channel conditional glucose forecasting.

Objective (plain MSE, no masking trick): given glucose history + insulin/carbs
through the horizon, predict glucose over the horizon. Train on CLEAN windows
only (--train_on normal) so the model learns normal dynamics; anomalies then
show up as large forecast residuals at scoring time.

Usage
-----
    bsub < ml/models/xchannel/hpc_xchannel.sh        (HPC)
    python ml/models/xchannel/pretrain.py --smoke_test   (local sanity)

Key flags
---------
    --epochs 40 --batch_size 512 --lr 2e-4
    --stride 15        train window stride (minutes)
    --train_on normal  'normal' = clean windows only, 'all' = every window
    --norm per_patient --seed 42 --val_patients 800
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

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from dataset import (  # noqa: E402
    make_patient_split, fit_scalers, load_patients, set_seed, TRAIN_STRIDE,
)
from models.xchannel.model import XChannelForecaster  # noqa: E402
from models.xchannel.dataset import ForecastWindowDataset  # noqa: E402

CHECKPOINT_DIR = Path("ml/data/checkpoints")
LOG_PATH       = Path("ml/data/checkpoints/xchannel_pretrain_log.json")
PARQUET        = Path("ml/data/sim_data/results_20000p_14d.parquet")


def run_epoch(model, loader, device, optimizer=None, log_every=500):
    """One pass. Train if optimizer given, else eval. Returns mean MSE."""
    train = optimizer is not None
    model.train() if train else model.eval()
    total, n = 0.0, len(loader)
    t0 = time.time()
    loss_fn = nn.MSELoss()

    torch.set_grad_enabled(train)
    for i, (glu, ins, carb, target, _) in enumerate(loader, 1):
        glu, ins = glu.to(device), ins.to(device)
        carb, target = carb.to(device), target.to(device)

        pred = model(glu, ins, carb)               # [B, H]
        loss = loss_fn(pred, target)

        if train:
            optimizer.zero_grad()
            loss.backward()
            clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        total += loss.item()
        if train and (i % log_every == 0 or i == n):
            el = time.time() - t0
            ips = i / el
            print(f"    step {i:>6}/{n}  loss={total/i:.4f}  "
                  f"{ips:.1f} it/s  ETA {(n-i)/ips/60:.1f}m", flush=True)
    torch.set_grad_enabled(True)
    return total / max(1, n)


def build_loaders(args, device):
    split = make_patient_split(args.parquet)
    train_ids = split["train"]
    val_ids   = split["val"][: args.val_patients]
    if args.smoke_test:
        train_ids, val_ids = train_ids[:10], val_ids[:10]

    # global norm needs population scalers fit on TRAIN patients only
    scalers = None
    if args.norm == "global":
        scalers = fit_scalers(load_patients(train_ids, args.parquet), parquet=args.parquet)

    def make(ids):
        return ForecastWindowDataset(
            ids, scalers=scalers, parquet=args.parquet, stride=args.stride,
            norm=args.norm, train_on=args.train_on, features=args.features,
        )
    train_ds, val_ds = make(train_ids), make(val_ids)
    print(f"  train windows: {len(train_ds):,}  |  val windows: {len(val_ds):,}", flush=True)

    pin = device.type == "cuda"
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=args.num_workers, pin_memory=pin)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size * 2, shuffle=False,
                            num_workers=args.num_workers, pin_memory=pin)
    return train_loader, val_loader


def main():
    p = argparse.ArgumentParser(description="XCHANNEL pretraining")
    p.add_argument("--epochs",      type=int,   default=40)
    p.add_argument("--batch_size",  type=int,   default=512)
    p.add_argument("--lr",          type=float, default=2e-4)
    p.add_argument("--stride",      type=int,   default=TRAIN_STRIDE)
    p.add_argument("--num_workers", type=int,   default=4)
    p.add_argument("--train_on", choices=["normal", "all"], default="normal")
    p.add_argument("--features", choices=["raw", "iob_cob"], default="raw",
                   help="input channels: raw insulin/carbs, or IOB/COB physiology")
    p.add_argument("--patch_len", type=int, default=0,
                   help="0 = 3-token iTransformer; >0 = temporal patch tokens (e.g. 20)")
    p.add_argument("--n_layers", type=int, default=2,
                   help="transformer layers (use 3 with patching)")
    p.add_argument("--norm", choices=["per_patient", "global"], default="per_patient")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--val_patients", type=int, default=800)
    p.add_argument("--parquet", type=Path, default=PARQUET)
    p.add_argument("--smoke_test", action="store_true")
    args = p.parse_args()
    set_seed(args.seed)
    if args.smoke_test:
        args.epochs, args.batch_size, args.num_workers = 2, 32, 0

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}  | train_on={args.train_on}  norm={args.norm}", flush=True)

    print("Building datasets…", flush=True)
    train_loader, val_loader = build_loaders(args, device)

    model = XChannelForecaster(patch_len=args.patch_len, n_layers=args.n_layers).to(device)
    print(f"Model: patch_len={args.patch_len} n_layers={args.n_layers} | "
          f"params={sum(p.numel() for p in model.parameters()):,}", flush=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=3, min_lr=1e-6)

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    parts = (["iobcob"] if args.features == "iob_cob" else []) + (["patched"] if args.patch_len else [])
    tag = "_".join(parts)
    best_name  = f"xchannel_{tag}_best.pt"  if tag else "xchannel_best.pt"
    final_name = f"xchannel_{tag}_final.pt" if tag else "xchannel_final.pt"
    best_val, log = float("inf"), []

    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        train_loss = run_epoch(model, train_loader, device, optimizer)
        val_loss   = run_epoch(model, val_loader, device)
        scheduler.step(val_loss)
        lr_now = optimizer.param_groups[0]["lr"]
        print(f"Epoch {epoch:02d}/{args.epochs}  train={train_loss:.4f}  "
              f"val={val_loss:.4f}  lr={lr_now:.2e}  ({time.time()-t0:.0f}s)", flush=True)
        log.append({"epoch": epoch, "train_loss": train_loss,
                    "val_loss": val_loss, "lr": lr_now})

        if val_loss < best_val:
            best_val = val_loss
            torch.save({"epoch": epoch, "model_state": model.state_dict(),
                        "val_loss": val_loss, "args": vars(args)},
                       CHECKPOINT_DIR / best_name)
            print(f"  ✓ saved best checkpoint (val={val_loss:.4f})", flush=True)

    torch.save({"epoch": args.epochs, "model_state": model.state_dict(), "args": vars(args)},
               CHECKPOINT_DIR / final_name)
    LOG_PATH.write_text(json.dumps(log, indent=2))
    print(f"\nDone. Best val loss: {best_val:.4f}", flush=True)


if __name__ == "__main__":
    main()
