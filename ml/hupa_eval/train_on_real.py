"""Train XCHANNEL-NLL on HUPA's rule-clean normal windows (real-N arm of the
data-matched train-on-real experiment)."""
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
from ohio_eval.eval_proxy import clean_meals, CLASS_IDX, LABEL_POST_MIN, ALIGNED  # noqa: E402
from hupa_eval.adapter import load_hupa_cohort                  # noqa: E402
from hupa_eval.split import hupa_split                          # noqa: E402
from realdata.excursion import excursion_window                 # noqa: E402

CHECKPOINT_DIR = Path("ml/data/checkpoints")


def labelled_render(p, cfg, meal_min_g, rescue_lookback, exclude="flat60"):
    """[T,8] with CLEANED rule anomaly flags in cols 3-7 (for train_on=normal).

    `exclude` sets the anomaly-tail length removed from the 'normal' training set:
      flat60    - legacy [m, m+60] (leaks the 60-300min hyper tail into 'normal')
      aligned   - [m, m+{180,240,300}] per class (removes the full anomaly tail)
      excursion - glucose-derived window, fixed-aligned fallback when no rise
    """
    arr = p.render()
    labels = classify_meals(clean_meals(p, meal_min_g, rescue_lookback), p.boluses, cfg)
    for cls, minutes in labels.items():
        col = N_CHANNELS + CLASS_IDX[cls]
        for m in minutes:
            if exclude == "excursion":
                w = excursion_window(p.glucose, m, cls)
                s, e = w if w is not None else (m, min(p.T, m + ALIGNED[cls]))
            elif exclude == "aligned":
                s, e = m, min(p.T, m + ALIGNED[cls])
            else:                                    # flat60
                s, e = m, min(p.T, m + LABEL_POST_MIN)
            arr[s:e, col] = 1.0
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
    ap.add_argument("--pooled", action="store_true",
                    help="train on pooled HUPA+Ohio real cohort (else HUPA only)")
    ap.add_argument("--init", type=str, default=None,
                    help="checkpoint to init from (sim-pretrain -> fine-tune); else scratch")
    ap.add_argument("--n_real_patients", type=int, default=0,
                    help="cap real train patients (0=all); data-efficiency sweep")
    ap.add_argument("--exclude", choices=["flat60", "aligned", "excursion"], default="flat60",
                    help="anomaly-tail length removed from the 'normal' training set")
    ap.add_argument("--tag", type=str, default="",
                    help="suffix appended to the checkpoint name (keep arms distinct)")
    args = ap.parse_args()
    torch.manual_seed(args.seed); np.random.seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if args.pooled:
        from realdata.pooled import load_pooled, pooled_split
        cohort, hu_pids, oh_pids, man_pids = load_pooled()
        sp = pooled_split(hu_pids, oh_pids, man_pids, seed=args.seed)
        ckpt_name = "xchannel_nll_pooled_best.pt"
    else:
        cohort = {p.pid: p for p in load_hupa_cohort()}
        sp = hupa_split(list(cohort), seed=args.seed)
        ckpt_name = "xchannel_nll_hupa_best.pt"
    if args.tag:
        ckpt_name = ckpt_name.replace("_best.pt", f"_{args.tag}_best.pt")
    cfg = RuleConfig()

    def pre(pids):
        return {pid: labelled_render(cohort[pid], cfg, args.meal_min_g,
                                     args.rescue_lookback, args.exclude) for pid in pids}
    train_pids = sp["train"][:args.n_real_patients] if args.n_real_patients else sp["train"]
    train_pre, val_pre = pre(train_pids), pre(sp["val"])
    print(f"real-train {len(train_pre)} / val {len(val_pre)} patients "
          f"(test held out: {len(sp['test'])})  device={device}"
          f"{'  | FT init=' + Path(args.init).name if args.init else '  | scratch'}")

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
    if args.init:                                            # sim-pretrain -> fine-tune
        model.load_state_dict(torch.load(args.init, map_location=device)["model_state"])
        print(f"  loaded init weights from {Path(args.init).name} (fine-tuning)", flush=True)
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
                       CHECKPOINT_DIR / ckpt_name)
            print(f"  [ok] saved (val={vl:.4f})", flush=True)
    print(f"Done. Best val {best:.4f}")


if __name__ == "__main__":
    main()
