"""
Train the characterization head on the FROZEN XCHANNEL encoder (sim labels only).

Pipeline:
  1. load a trained XCHANNEL checkpoint, freeze it
  2. stream simulator windows -> frozen 128-d embeddings + single-label class
     (balanced: cap per class so abundant 'normal' doesn't swamp rare anomalies)
  3. train the 2-layer MLP head (cross-entropy)
  4. fit the latent-OOD cluster on 'normal' embeddings
  5. save head + OOD stats -> ml/data/checkpoints/characterization_head.pt

Usage
-----
    python ml/characterization/train_head.py --smoke_test --parquet ml/data/sim_data/results_500p_14d_clean.parquet
    bsub < ... (HPC: full 20k, default parquet)
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import make_patient_split, set_seed, ANOMALY_CLASSES, TRAIN_STRIDE  # noqa: E402
from models.xchannel.model import forecaster_from_ckpt  # noqa: E402
from models.xchannel.dataset import ForecastWindowDataset  # noqa: E402
from characterization.head import (  # noqa: E402
    CharacterizationHead, fit_ood, ood_distance, CLASSES, N_CLASSES,
)

CHECKPOINT_DIR = Path("ml/data/checkpoints")
PARQUET = Path("ml/data/sim_data/results_20000p_14d.parquet")


def _batch_classes(label_dict) -> np.ndarray:
    """[B] class index from the per-class window flags, by precedence (missed->anaerobic)."""
    flags = np.stack([label_dict[c].numpy() for c in ANOMALY_CLASSES], axis=1)   # [B,5]
    cls = np.zeros(len(flags), dtype=np.int64)                                    # normal
    for j in range(len(ANOMALY_CLASSES) - 1, -1, -1):      # anaerobic..missed -> missed wins
        cls[flags[:, j] > 0] = j + 1
    return cls


@torch.no_grad()
def collect_embeddings(encoder, loader, device, max_per_class, log_every=200):
    """Stream frozen embeddings + classes, capped per class for balance."""
    buf_z = [[] for _ in range(N_CLASSES)]
    counts = np.zeros(N_CLASSES, dtype=int)
    t0 = time.time()
    for i, (glu, ins, carb, _t, labels) in enumerate(loader, 1):
        z = encoder(glu.to(device), ins.to(device), carb.to(device),
                    return_embeddings=True).cpu().numpy()
        cls = _batch_classes(labels)
        for c in range(N_CLASSES):
            if counts[c] >= max_per_class:
                continue
            take = np.where(cls == c)[0]
            if take.size:
                room = max_per_class - counts[c]
                sel = take[:room]
                buf_z[c].append(z[sel]); counts[c] += len(sel)
        if i % log_every == 0:
            print(f"    batch {i}  counts={counts.tolist()}  {i/(time.time()-t0):.1f} it/s", flush=True)
        if counts[0] >= max_per_class and counts.sum() >= max_per_class * 2:
            break       # normal capped + plenty of anomalies -> stop scanning
    Z = np.concatenate([np.concatenate(b) for b in buf_z if b])
    y = np.concatenate([np.full(len(np.concatenate(b)), c) for c, b in enumerate(buf_z) if b])
    return Z.astype(np.float32), y, counts


def main():
    p = argparse.ArgumentParser(description="Train characterization head")
    p.add_argument("--xchannel_checkpoint", type=Path, default=None)
    p.add_argument("--features", choices=["raw", "iob_cob"], default="raw")
    p.add_argument("--parquet", type=Path, default=PARQUET)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch_size", type=int, default=512)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--dropout", type=float, default=0.3)
    p.add_argument("--stride", type=int, default=TRAIN_STRIDE)
    p.add_argument("--max_per_class", type=int, default=20000)
    p.add_argument("--n_patients", type=int, default=2000)
    p.add_argument("--num_workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--smoke_test", action="store_true")
    args = p.parse_args()
    set_seed(args.seed)
    if args.smoke_test:
        args.epochs, args.batch_size, args.num_workers = 5, 64, 0
        args.max_per_class, args.n_patients = 300, 60
    if args.xchannel_checkpoint is None:
        name = "xchannel_iobcob_best.pt" if args.features == "iob_cob" else "xchannel_best.pt"
        args.xchannel_checkpoint = CHECKPOINT_DIR / name

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}  | features={args.features}")

    # -- frozen encoder --------------------------------------------------------
    ckpt = torch.load(args.xchannel_checkpoint, map_location=device)
    encoder = forecaster_from_ckpt(ckpt, device)
    encoder.eval()
    for prm in encoder.parameters():
        prm.requires_grad_(False)
    print(f"Frozen XCHANNEL encoder (epoch {ckpt['epoch']}, val_loss={ckpt.get('val_loss', float('nan')):.4f})")

    # -- labelled sim windows -> embeddings ------------------------------------
    ids = make_patient_split(args.parquet)["train"][: args.n_patients]
    ds = ForecastWindowDataset(ids, parquet=args.parquet, stride=args.stride,
                               train_on="all", features=args.features)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=True,
                        num_workers=args.num_workers, pin_memory=device.type == "cuda")
    print(f"Collecting embeddings (<={args.max_per_class}/class) from {len(ds):,} windows...", flush=True)
    Z, y, counts = collect_embeddings(encoder, loader, device, args.max_per_class)
    print("  per-class counts: " + ", ".join(f"{CLASSES[c]}={counts[c]}" for c in range(N_CLASSES)))

    # -- train the head (class-weighted CE for residual imbalance) -------------
    head = CharacterizationHead(dropout=args.dropout).to(device)
    Zt = torch.from_numpy(Z).to(device); yt = torch.from_numpy(y).to(device)
    weights = torch.tensor([1.0 / max(1, (y == c).sum()) for c in range(N_CLASSES)],
                           dtype=torch.float32, device=device)
    weights = weights / weights.sum() * N_CLASSES
    opt = torch.optim.AdamW(head.parameters(), lr=args.lr, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss(weight=weights)
    n = len(Zt); idx = torch.arange(n, device=device)
    for ep in range(1, args.epochs + 1):
        head.train(); perm = idx[torch.randperm(n, device=device)]; tot = 0.0
        for b in range(0, n, args.batch_size):
            sel = perm[b : b + args.batch_size]
            opt.zero_grad()
            loss = loss_fn(head(Zt[sel]), yt[sel])
            loss.backward(); opt.step(); tot += loss.item() * len(sel)
        if ep % 5 == 0 or ep == args.epochs:
            head.eval()
            with torch.no_grad():
                acc = (head(Zt).argmax(-1) == yt).float().mean().item()
            print(f"Epoch {ep:02d}/{args.epochs}  loss={tot/n:.4f}  train_acc={acc:.3f}", flush=True)

    # -- OOD cluster on normal embeddings (+ a calibrated radius) + save -------
    mu, inv_cov = fit_ood(Z[y == 0])
    ood_radius = float(np.percentile(ood_distance(Z[y == 0], mu, inv_cov), 99))  # 99th pct of normal
    print(f"OOD: normal-cluster radius (99th pct) = {ood_radius:.2f}")
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    out = CHECKPOINT_DIR / "characterization_head.pt"
    torch.save({"head_state": head.state_dict(), "classes": CLASSES,
                "ood_mu": mu, "ood_inv_cov": inv_cov, "ood_radius": ood_radius,
                "features": args.features, "xchannel_checkpoint": str(args.xchannel_checkpoint),
                "args": vars(args)}, out)
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()
