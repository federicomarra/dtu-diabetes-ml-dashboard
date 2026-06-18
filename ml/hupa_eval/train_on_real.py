"""Train XCHANNEL-NLL on HUPA's rule-clean normal windows (real-N arm of the
data-matched train-on-real experiment). See ml/docs/TRAIN_ON_REAL.md."""
import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from torch.optim.lr_scheduler import ReduceLROnPlateau

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import N_CHANNELS                                  # noqa: E402
from models.xchannel.model import XChannelForecaster            # noqa: E402
from models.xchannel.dataset import ForecastWindowDataset       # noqa: E402
from models.xchannel.pretrain import run_epoch                  # noqa: E402
from characterization.rules import classify_meals, RuleConfig   # noqa: E402
from ohio_eval.eval_proxy import clean_meals, CLASS_IDX, LABEL_POST_MIN  # noqa: E402
from hupa_eval.adapter import load_hupa_cohort                  # noqa: E402
from hupa_eval.split import hupa_split                          # noqa: E402

CHECKPOINT_DIR = Path("ml/data/checkpoints")


def labelled_render(p, cfg, meal_min_g, rescue_lookback):
    """[T,8] with CLEANED rule anomaly flags in cols 3-7 (for train_on=normal)."""
    arr = p.render()
    labels = classify_meals(clean_meals(p, meal_min_g, rescue_lookback), p.boluses, cfg)
    for cls, minutes in labels.items():
        col = N_CHANNELS + CLASS_IDX[cls]
        for m in minutes:
            arr[m: min(p.T, m + LABEL_POST_MIN), col] = 1.0
    return arr


def main():
    ap = argparse.ArgumentParser(description="train XCHANNEL-NLL on HUPA (real-N)")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch_size", type=int, default=512)
    ap.add_argument("--stride", type=int, default=15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--meal_min_g", type=float, default=30.0)
    ap.add_argument("--rescue_lookback", type=int, default=30)
    ap.add_argument("--num_workers", type=int, default=0)
    args = ap.parse_args()
    torch.manual_seed(args.seed); np.random.seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    cohort = {p.pid: p for p in load_hupa_cohort()}
    sp = hupa_split(list(cohort), seed=args.seed)
    cfg = RuleConfig()

    def pre(pids):
        return {pid: labelled_render(cohort[pid], cfg, args.meal_min_g,
                                     args.rescue_lookback) for pid in pids}
    train_pre, val_pre = pre(sp["train"]), pre(sp["val"])
    print(f"real-train {len(train_pre)} / val {len(val_pre)} patients "
          f"(test held out: {len(sp['test'])})  device={device}")

    def mk(d):
        return ForecastWindowDataset(list(d), _preloaded=d, stride=args.stride,
                                     norm="per_patient", train_on="normal")
    train_ds, val_ds = mk(train_pre), mk(val_pre)
    print(f"train windows {len(train_ds):,} | val windows {len(val_ds):,}", flush=True)
    pin = device.type == "cuda"
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=args.num_workers, pin_memory=pin)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size * 2, shuffle=False,
                            num_workers=args.num_workers, pin_memory=pin)

    model = XChannelForecaster(n_layers=2, probabilistic=True).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = ReduceLROnPlateau(opt, mode="min", factor=0.5, patience=3, min_lr=1e-6)
    ckpt_args = {"patch_len": 0, "n_layers": 2, "probabilistic": True,
                 "norm": "per_patient", "features": "raw"}
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    best = float("inf")
    for ep in range(1, args.epochs + 1):
        tr = run_epoch(model, train_loader, device, opt)
        vl = run_epoch(model, val_loader, device)
        sched.step(vl)
        print(f"Epoch {ep:02d}/{args.epochs} train={tr:.4f} val={vl:.4f} "
              f"lr={opt.param_groups[0]['lr']:.2e}", flush=True)
        if vl < best:
            best = vl
            torch.save({"epoch": ep, "model_state": model.state_dict(),
                        "args": ckpt_args, "val_loss": vl},
                       CHECKPOINT_DIR / "xchannel_nll_hupa_best.pt")
            print(f"  ✓ saved (val={vl:.4f})", flush=True)
    print(f"Done. Best val {best:.4f}")


if __name__ == "__main__":
    main()
