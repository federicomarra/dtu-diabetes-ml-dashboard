"""
XCHANNEL OhioT1DM generalization eval via RULE-DERIVED proxy labels.

This is the valid real-data test (the synthetic input-only injection was proven
invalid — below chance on sim — because it keeps real glucose fixed). Here we
do NOT perturb anything: we take the patient's REAL data and label which real
meals were missed/late/large using the rule classifier (ml/characterization).
These are genuine behavioural anomalies where glucose ACTUALLY reacts, so the
conditional-forecast residual can detect them — exactly as on the simulator's
native anomalies.

Labels are noisy proxies (a logged meal with no bolus might be a snack the
patient correctly skipped; 12 patients; low prevalence) — state that. But it is
the real thing, not a fabrication.

Usage
-----
    python ml/ohio_eval/eval_proxy.py                       # raw checkpoint
    python ml/ohio_eval/eval_proxy.py --features iob_cob
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import average_precision_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import N_CHANNELS  # noqa: E402
from features.iob_cob import to_iob_cob  # noqa: E402
from characterization.rules import classify_meals, RuleConfig  # noqa: E402
from ohio_eval.adapter import load_ohio_cohort  # noqa: E402
from ohio_eval.eval_xchannel import score_patient, _zscore_stats, CLASS_IDX  # noqa: E402
from models.xchannel.model import forecaster_from_ckpt  # noqa: E402

LABEL_POST_MIN = 60          # flag [meal, meal+POST] — the early post-meal excursion


def label_array(p, cfg: RuleConfig) -> np.ndarray:
    """[T,8] flag array: rule-labelled meals marked over their post-meal window."""
    flags = np.zeros((p.T, N_CHANNELS + 5), dtype=np.float32)
    labels = classify_meals(p.meals, p.boluses, cfg)
    for cls, minutes in labels.items():
        col = N_CHANNELS + CLASS_IDX[cls]
        for m in minutes:
            flags[m : min(p.T, m + LABEL_POST_MIN), col] = 1.0
    return flags


def main():
    ap = argparse.ArgumentParser(description="XCHANNEL OhioT1DM eval via rule-derived labels")
    ap.add_argument("--checkpoint", type=Path, default=None)
    ap.add_argument("--features", choices=["raw", "iob_cob"], default="raw")
    ap.add_argument("--ohio_root", type=Path, default=Path("ml/data/real/ohio"))
    ap.add_argument("--year", default="both", choices=["2018", "2020", "both"])
    ap.add_argument("--split", default="test", choices=["test", "train"])
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--batch_size", type=int, default=512)
    args = ap.parse_args()
    if args.checkpoint is None:
        name = "xchannel_iobcob_best.pt" if args.features == "iob_cob" else "xchannel_best.pt"
        args.checkpoint = Path("ml/data/checkpoints") / name

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}  | features={args.features}")
    ckpt = torch.load(args.checkpoint, map_location=device)
    model = forecaster_from_ckpt(ckpt, device); model.eval()
    print(f"Loaded epoch {ckpt['epoch']} (val_loss={ckpt.get('val_loss', float('nan')):.4f})")

    cohort = load_ohio_cohort(args.ohio_root, year=args.year, split=args.split)
    cfg = RuleConfig()
    xf = to_iob_cob if args.features == "iob_cob" else (lambda a: a)

    # rule-label counts across the cohort
    counts = {"missed": 0, "late": 0, "large": 0}
    for p in cohort:
        for cls, mins in classify_meals(p.meals, p.boluses, cfg).items():
            counts[cls] += len(mins)
    n_meals = sum(len(p.meals) for p in cohort)
    print(f"OhioT1DM: {len(cohort)} patients, {n_meals} logged meals → "
          f"rule labels: missed={counts['missed']} late={counts['late']} large={counts['large']}")

    print("\nDetection on REAL anomalies (rule-derived labels, glucose reacts)")
    print(f"  {'class':<8} {'prev':>7} {'pos':>7} {'AUPRC':>9} {'AUROC':>9}")
    for cls in ("missed", "late", "large"):
        fcol = N_CHANNELS + CLASS_IDX[cls]
        all_s, all_l = [], []
        for p in cohort:
            base = xf(p.render())                       # model input (real data)
            arr = base.copy()
            arr[:, N_CHANNELS:] = label_array(p, cfg)[:, N_CHANNELS:]   # attach rule flags
            mean, std = _zscore_stats(base)
            s, l = score_patient(model, device, arr, p.valid, mean, std, fcol,
                                 args.stride, args.batch_size)
            all_s.append(s); all_l.append(l)
        scores, labels = np.concatenate(all_s), np.concatenate(all_l)
        if labels.sum() == 0:
            print(f"  {cls:<8}    n/a (no rule labels)"); continue
        print(f"  {cls:<8} {labels.mean():>7.2%} {int(labels.sum()):>7} "
              f"{average_precision_score(labels, scores):>9.4f} {roc_auc_score(labels, scores):>9.4f}")


if __name__ == "__main__":
    main()
