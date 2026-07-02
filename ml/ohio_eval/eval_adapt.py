"""
Per-patient self-supervised adaptation on OhioT1DM (quality-program Step 3).

The sim-trained detector forecasts REAL glucose poorly → noisy residual →
over-detection. Fix: for each patient, fine-tune a COPY of the detector on their
first N baseline days (forecasting needs no labels), so it learns THAT patient's
normal dynamics, then detect deviations on the held-out remainder. Matches
INSTRUCTIONS Stage 3 (per-patient adaptation).

Fair measurement: adapted vs un-adapted on the SAME held-out windows (anchors
after the baseline period), so the Δ is purely the adaptation effect — for both
detection (AUPRC/AUROC vs rule labels) and over-detection (flagged fraction at a
per-patient threshold calibrated on the baseline scores).

Usage
-----
    python ml/ohio_eval/eval_adapt.py                                  # NLL detector
    python ml/ohio_eval/eval_adapt.py --checkpoint ml/data/checkpoints/xchannel_best.pt
"""

import argparse
import copy
import sys
from pathlib import Path

import numpy as np
import torch
from scipy.stats import iqr
from sklearn.metrics import average_precision_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import N_CHANNELS, set_seed  # noqa: E402
from features.iob_cob import to_iob_cob  # noqa: E402
from characterization.rules import classify_meals, RuleConfig  # noqa: E402
from ohio_eval.adapter import load_ohio_cohort  # noqa: E402
from ohio_eval.eval_proxy import label_array, CLASS_IDX  # noqa: E402
from models.xchannel.model import (  # noqa: E402
    forecaster_from_ckpt, forecast_loss, anomaly_score as compute_score, CONTEXT_LEN, HORIZON,
)

L, H, WIN = CONTEXT_LEN, HORIZON, CONTEXT_LEN + HORIZON
DAY = 1440


def _tensors(z, starts, device):
    glu = torch.stack([torch.from_numpy(z[s : s + L, 0].copy()) for s in starts]).to(device)
    ins = torch.stack([torch.from_numpy(z[s : s + WIN, 1].copy()) for s in starts]).to(device)
    car = torch.stack([torch.from_numpy(z[s : s + WIN, 2].copy()) for s in starts]).to(device)
    tgt = torch.stack([torch.from_numpy(z[s + L : s + WIN, 0].copy()) for s in starts]).to(device)
    return glu, ins, car, tgt


def adapt(base, z, starts, device, epochs, lr, batch):
    """Fine-tune a copy of `base` on the patient's baseline windows (self-supervised)."""
    m = copy.deepcopy(base).to(device).train()
    opt = torch.optim.AdamW(m.parameters(), lr=lr, weight_decay=1e-4)
    starts = np.array(starts)
    for _ in range(epochs):
        for b in range(0, len(starts), batch):
            sel = starts[b : b + batch]
            glu, ins, car, tgt = _tensors(z, sel, device)
            opt.zero_grad()
            forecast_loss(m(glu, ins, car), tgt).backward()
            opt.step()
    return m.eval()


@torch.no_grad()
def score(model, z, starts, device, batch=512):
    out = []
    for b in range(0, len(starts), batch):
        glu, ins, car, tgt = _tensors(z, starts[b : b + batch], device)
        out.append(compute_score(model(glu, ins, car), tgt).cpu().numpy())
    return np.concatenate(out) if out else np.empty(0)


def _threshold(cal):                       # per-patient robust threshold
    return float(np.median(cal) + 2 * max(iqr(cal) / 1.349, 1e-6))


def main():
    ap = argparse.ArgumentParser(description="Per-patient adaptation eval on OhioT1DM")
    ap.add_argument("--checkpoint", type=Path, default=Path("ml/data/checkpoints/xchannel_nll_best.pt"))
    ap.add_argument("--features", choices=["raw", "iob_cob"], default="raw")
    ap.add_argument("--ohio_root", type=Path, default=Path("ml/data/real/ohio"))
    ap.add_argument("--baseline_days", type=int, default=5)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--batch_size", type=int, default=64)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    set_seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    base = forecaster_from_ckpt(torch.load(args.checkpoint, map_location=device), device).eval()
    print(f"Device: {device}  | base={args.checkpoint.name}  features={args.features}")
    print(f"Per-patient adaptation: {args.baseline_days}-day baseline, {args.epochs} epochs, lr {args.lr}")

    xf = to_iob_cob if args.features == "iob_cob" else (lambda a: a)
    cfg = RuleConfig()
    cohort = load_ohio_cohort(args.ohio_root)
    base_min = args.baseline_days * DAY

    # accumulate held-out scores/labels across patients, for base vs adapted
    S = {"base": [], "adapt": []}
    Lb = {c: [] for c in CLASS_IDX}
    flagged = {"base": [0, 0], "adapt": [0, 0]}   # [n_flagged, n_total]

    for p in cohort:
        bz = xf(p.render())
        m, s = bz[:, :N_CHANNELS].mean(0), bz[:, :N_CHANNELS].std(0).clip(1e-8)
        z = bz.copy(); z[:, :N_CHANNELS] = (bz[:, :N_CHANNELS] - m) / s
        flags = label_array(p, cfg)

        starts = [st for st in range(0, p.T - WIN + 1, args.stride) if p.valid[st : st + WIN].all()]
        base_starts = [st for st in starts if st + WIN <= base_min]
        eval_starts = [st for st in starts if st >= base_min]
        if len(base_starts) < 50 or not eval_starts:
            continue                                   # too little baseline to adapt

        adapted = adapt(base, z, base_starts, device, args.epochs, args.lr, args.batch_size)
        cal_b = score(base, z, base_starts, device)    # baseline scores → threshold
        cal_a = score(adapted, z, base_starts, device)
        thr_b, thr_a = _threshold(cal_b), _threshold(cal_a)

        for tag, model, thr in [("base", base, thr_b), ("adapt", adapted, thr_a)]:
            sc = score(model, z, eval_starts, device)
            S[tag].append(sc)
            flagged[tag][0] += int((sc > thr).sum()); flagged[tag][1] += len(sc)
        for c, j in CLASS_IDX.items():
            Lb[c].append(np.array([flags[st + L : st + WIN, N_CHANNELS + j].max() for st in eval_starts]))

    labels = {c: np.concatenate(v) for c, v in Lb.items()}
    print(f"\nHeld-out windows: {len(np.concatenate(S['base'])):,}  (anchors after baseline)")
    print(f"  {'class':<8} {'pos':>6} | {'AUROC base→adapt':>20} | {'AUPRC base→adapt':>20}")
    for c in ("missed", "late", "large"):
        y = labels[c];
        if y.sum() == 0:
            print(f"  {c:<8}   n/a"); continue
        sb, sa = np.concatenate(S["base"]), np.concatenate(S["adapt"])
        print(f"  {c:<8} {int(y.sum()):>6} | {roc_auc_score(y,sb):>9.3f} → {roc_auc_score(y,sa):<8.3f} | "
              f"{average_precision_score(y,sb):>9.3f} → {average_precision_score(y,sa):<8.3f}")
    fb, fa = flagged["base"], flagged["adapt"]
    print(f"\nOver-detection (flagged held-out windows at per-patient threshold):")
    print(f"  base  {fb[0]/fb[1]:.1%}   →   adapt {fa[0]/fa[1]:.1%}")


if __name__ == "__main__":
    main()
