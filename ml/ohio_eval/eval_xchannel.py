"""
XCHANNEL generalization test on OhioT1DM (real patients) via synthetic injection.

OhioT1DM has no anomaly labels, so we create them honestly by perturbing only
the bolus (an INPUT), never fabricating glucose, then scoring with the
sim-trained XCHANNEL checkpoint:

  missed : drop a real meal bolus entirely (insulin AND its announced carb → 0)
  late   : shift the bolus later by --late_delay min (insulin + announcement)
  large  : keep only --carb_keep of the bolus's announced carbs (under-report)

Real glucose stays; the model (which learned the normal carb→insulin coupling
on the simulator) sees an anomalous input combination, its forecast diverges
from real glucose → high residual. Labels are exact (the perturbed bolus minute).

This is the "A" half of the A→B plan: the adapter now matches the simulator's
raw-channel encoding (3-min bolus spread, bolus-time announced-carb box, missed
→ carb 0). If transfer is still near-chance, that is the raw-channel
generalization gap; "B" (IOB/COB features) is the encoding-robust fix.

Per-patient z-scoring uses each patient's ORIGINAL (un-injected) render.

Usage
-----
    python ml/ohio_eval/eval_xchannel.py \
        --checkpoint ml/data/checkpoints/xchannel_best.pt
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import average_precision_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).parent.parent))   # put ml/ on the path
from dataset import ANOMALY_CLASSES, N_CHANNELS  # noqa: E402
from ohio_eval.adapter import load_ohio_cohort, OhioPatient, Bolus  # noqa: E402
from features.iob_cob import to_iob_cob  # noqa: E402
from models.xchannel.model import XChannelForecaster, CONTEXT_LEN, HORIZON  # noqa: E402

L, H, WIN = CONTEXT_LEN, HORIZON, CONTEXT_LEN + HORIZON
CLASS_IDX = {c: i for i, c in enumerate(ANOMALY_CLASSES)}   # missed=0 late=1 large=2


# ── injection ───────────────────────────────────────────────────────────────────

def inject(p: OhioPatient, cls: str, late_delay: int, carb_keep: float,
           min_carb_g: float) -> np.ndarray:
    """Render a [T,8] array with `cls` injected at every eligible meal bolus."""
    fcol = N_CHANNELS + CLASS_IDX[cls]
    new = [Bolus(b.minute, b.units, b.carb_g) for b in p.boluses]   # copies
    flag_minutes = []
    for i, b in enumerate(new):
        if b.carb_g < min_carb_g:                       # only meal boluses
            continue
        if cls == "missed":
            flag_minutes.append(b.minute)
            new[i] = None                               # drop it (insulin + carb)
        elif cls == "late":
            flag_minutes.append(b.minute)
            b.minute = min(p.T - 1, b.minute + late_delay)
        elif cls == "large":
            flag_minutes.append(b.minute)
            b.carb_g = b.carb_g * carb_keep             # under-report carbs
        else:
            raise ValueError(cls)

    arr = p.render([b for b in new if b is not None])
    for m in flag_minutes:
        arr[m, fcol] = 1.0
    return arr


# ── scoring ─────────────────────────────────────────────────────────────────────

def _zscore_stats(arr):
    sig = arr[:, :N_CHANNELS]
    return sig.mean(0), sig.std(0).clip(min=1e-8)


@torch.no_grad()
def score_patient(model, device, arr, valid, mean, std, fcol, stride, batch_size):
    T = arr.shape[0]
    z = (arr[:, :N_CHANNELS] - mean) / std
    starts = [s for s in range(0, T - WIN + 1, stride) if valid[s : s + WIN].all()]
    if not starts:
        return np.empty(0), np.empty(0)
    scores, labels = [], []
    for i in range(0, len(starts), batch_size):
        chunk = starts[i : i + batch_size]
        glu = torch.stack([torch.from_numpy(z[s : s + L, 0].copy()) for s in chunk]).to(device)
        ins = torch.stack([torch.from_numpy(z[s : s + WIN, 1].copy()) for s in chunk]).to(device)
        car = torch.stack([torch.from_numpy(z[s : s + WIN, 2].copy()) for s in chunk]).to(device)
        tgt = torch.stack([torch.from_numpy(z[s + L : s + WIN, 0].copy()) for s in chunk]).to(device)
        pred = model(glu, ins, car)
        scores.append(((pred - tgt) ** 2).mean(dim=1).cpu().numpy())
        labels.append(np.array([arr[s + L : s + WIN, fcol].max() for s in chunk], dtype=np.float32))
    return np.concatenate(scores), np.concatenate(labels)


def eval_class(model, device, cohort, cls, args):
    fcol = N_CHANNELS + CLASS_IDX[cls]
    xf = to_iob_cob if args.features == "iob_cob" else (lambda a: a)
    all_s, all_l = [], []
    for p in cohort:
        arr = xf(inject(p, cls, args.late_delay, args.carb_keep, args.min_carb_g))
        mean, std = _zscore_stats(xf(p.render()))       # ORIGINAL stats, same transform
        s, l = score_patient(model, device, arr, p.valid, mean, std, fcol,
                             args.stride, args.batch_size)
        all_s.append(s); all_l.append(l)
    return np.concatenate(all_s), np.concatenate(all_l)


def main():
    ap = argparse.ArgumentParser(description="XCHANNEL OhioT1DM generalization eval")
    ap.add_argument("--checkpoint", type=Path, default=None,
                    help="default: xchannel_best.pt (raw) or xchannel_iobcob_best.pt (iob_cob)")
    ap.add_argument("--features", choices=["raw", "iob_cob"], default="raw",
                    help="MUST match the checkpoint's training features")
    ap.add_argument("--ohio_root",  type=Path, default=Path("ml/data/OhioT1DM"))
    ap.add_argument("--year",  default="both", choices=["2018", "2020", "both"])
    ap.add_argument("--split", default="test", choices=["test", "train"])
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--batch_size", type=int, default=512)
    ap.add_argument("--late_delay", type=int, default=30, help="minutes to delay the bolus (sim: 30)")
    ap.add_argument("--carb_keep", type=float, default=0.7, help="fraction of carbs kept (sim large: 0.70)")
    ap.add_argument("--min_carb_g", type=float, default=20.0, help="min announced carbs to call a bolus a meal")
    args = ap.parse_args()
    if args.checkpoint is None:
        name = "xchannel_iobcob_best.pt" if args.features == "iob_cob" else "xchannel_best.pt"
        args.checkpoint = Path("ml/data/checkpoints") / name

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}  | features={args.features}")

    ckpt = torch.load(args.checkpoint, map_location=device)
    model = XChannelForecaster().to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    print(f"Loaded checkpoint epoch {ckpt['epoch']}  (val_loss={ckpt.get('val_loss', float('nan')):.4f})")

    cohort = load_ohio_cohort(args.ohio_root, year=args.year, split=args.split)
    n_meal_bolus = sum(sum(1 for b in p.boluses if b.carb_g >= args.min_carb_g) for p in cohort)
    print(f"OhioT1DM: {len(cohort)} patients ({args.year}/{args.split}), "
          f"{sum(p.T for p in cohort):,} minutes, "
          f"{sum(len(p.boluses) for p in cohort)} boluses ({n_meal_bolus} meal-boluses ≥{args.min_carb_g:g}g)")

    print("\nSynthetic-injection generalization (real glucose, perturbed bolus)")
    print(f"  {'class':<8} {'prev':>7} {'pos':>7} {'AUPRC':>9} {'AUROC':>9}")
    for cls in ("missed", "late", "large"):
        scores, labels = eval_class(model, device, cohort, cls, args)
        n_pos = int(labels.sum())
        if n_pos == 0:
            print(f"  {cls:<8}    n/a (no eligible sites)")
            continue
        print(f"  {cls:<8} {labels.mean():>7.2%} {n_pos:>7} "
              f"{average_precision_score(labels, scores):>9.4f} {roc_auc_score(labels, scores):>9.4f}")


if __name__ == "__main__":
    main()
