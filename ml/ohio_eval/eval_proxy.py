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

LABEL_POST_MIN = 60          # flat fallback (legacy)
# Class-specific post-meal label windows — MATCH the sim generator's
# LABEL_WINDOW_{MISSED,LATE,LARGE}_END so the real-eval positive region lines up with
# where the model was trained to fire (and where glucose actually diverges: audit shows
# Ohio missed peaks 90-120min, flat at 30-60). Flat 60 caught almost none of the signal.
LABEL_WIN = {"flat":    {"missed": 60,  "late": 60,  "large": 60},
             "aligned": {"missed": 180, "late": 240, "large": 300}}


def clean_meals(p, meal_min_g: float, rescue_lookback: int = 30):
    """Drop snacks (< meal_min_g) and hypo-rescue carbs (glucose <3.9 in the prior
    `rescue_lookback` min) — both are correct no-bolus behaviour and must NOT count
    as 'missed'. See ml/docs/DETECTION_RATIONALE.md §6."""
    out = []
    for m in p.meals:
        if m.carb_g < meal_min_g:
            continue
        lo = max(0, m.minute - rescue_lookback)
        win = p.glucose[lo : m.minute + 1]
        if win.size and np.nanmin(win) < 3.9:            # preceded by a low → rescue
            continue
        out.append(m)
    return out


def label_array(p, cfg: RuleConfig, meals, win=None) -> np.ndarray:
    """[T,8] flag array: rule-labelled meals marked over their post-meal window.
    `win` is a class→minutes dict (defaults to the flat 60-min window)."""
    win = win or LABEL_WIN["flat"]
    flags = np.zeros((p.T, N_CHANNELS + 5), dtype=np.float32)
    labels = classify_meals(meals, p.boluses, cfg)
    for cls, minutes in labels.items():
        col = N_CHANNELS + CLASS_IDX[cls]
        for m in minutes:
            flags[m : min(p.T, m + win[cls]), col] = 1.0
    return flags


def main():
    ap = argparse.ArgumentParser(description="XCHANNEL OhioT1DM eval via rule-derived labels")
    ap.add_argument("--checkpoint", type=Path, default=None)
    ap.add_argument("--features", choices=["raw", "iob_cob"], default="raw")
    ap.add_argument("--dataset", choices=["ohio", "hupa", "manchester"], default="ohio")
    ap.add_argument("--ohio_root", type=Path, default=Path("ml/data/real/ohio"))
    ap.add_argument("--hupa_root", type=Path, default=Path("ml/data/real/hupa/Preprocessed"))
    ap.add_argument("--hupa_split", choices=["all", "train", "val", "test"], default="all")
    ap.add_argument("--hupa_seed", type=int, default=42)
    ap.add_argument("--pooled_test", action="store_true",
                    help="eval only the pooled-split test patients for --dataset (uses --hupa_seed)")
    ap.add_argument("--year", default="both", choices=["2018", "2020", "both"])
    ap.add_argument("--split", default="test", choices=["test", "train"])
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--batch_size", type=int, default=512)
    ap.add_argument("--score", choices=["sym", "signed", "peak", "end"], default="sym",
                    help="anomaly-score aggregation (directional over-forecast variants)")
    ap.add_argument("--label_mode", choices=["flat", "aligned"], default="flat",
                    help="post-meal label window: flat 60min, or aligned to sim (180/240/300)")
    ap.add_argument("--clean", action="store_true",
                    help="cleaned labels: drop snacks (<meal_min_g) + hypo-rescue meals")
    ap.add_argument("--meal_min_g", type=float, default=30.0)
    ap.add_argument("--rescue_lookback", type=int, default=30)
    args = ap.parse_args()
    if args.checkpoint is None:
        name = "xchannel_iobcob_best.pt" if args.features == "iob_cob" else "xchannel_best.pt"
        args.checkpoint = Path("ml/data/checkpoints") / name

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}  | features={args.features}")
    ckpt = torch.load(args.checkpoint, map_location=device)
    model = forecaster_from_ckpt(ckpt, device); model.eval()
    print(f"Loaded epoch {ckpt['epoch']} (val_loss={ckpt.get('val_loss', float('nan')):.4f})")

    if args.pooled_test:
        from realdata.pooled import load_pooled, pooled_split
        pc, hu_pids, oh_pids, man_pids = load_pooled()
        sp = pooled_split(hu_pids, oh_pids, man_pids, seed=args.hupa_seed)
        test_pids = sp[f"{args.dataset}_test"]
        cohort = [pc[pid] for pid in test_pids]
        print(f"Dataset: POOLED-{args.dataset} test ({len(cohort)} patients, seed={args.hupa_seed})")
    elif args.dataset == "hupa":
        from hupa_eval.adapter import load_hupa_cohort
        cohort = load_hupa_cohort(args.hupa_root)
        if args.hupa_split != "all":
            from hupa_eval.split import hupa_split
            sel = set(hupa_split([p.pid for p in cohort], seed=args.hupa_seed)[args.hupa_split])
            cohort = [p for p in cohort if p.pid in sel]
        print(f"Dataset: HUPA ({len(cohort)} patients, split={args.hupa_split})")
    else:
        cohort = load_ohio_cohort(args.ohio_root, year=args.year, split=args.split)
        print(f"Dataset: OhioT1DM ({len(cohort)} patients, {args.year}/{args.split})")
    cfg = RuleConfig()
    xf = to_iob_cob if args.features == "iob_cob" else (lambda a: a)
    meals_of = ((lambda p: clean_meals(p, args.meal_min_g, args.rescue_lookback))
                if args.clean else (lambda p: p.meals))
    print(f"Labels: {'CLEANED (meal≥%gg, no prior low)' % args.meal_min_g if args.clean else 'raw'}")

    # rule-label counts across the cohort
    counts = {"missed": 0, "late": 0, "large": 0}
    for p in cohort:
        for cls, mins in classify_meals(meals_of(p), p.boluses, cfg).items():
            counts[cls] += len(mins)
    n_meals = sum(len(meals_of(p)) for p in cohort)
    print(f"OhioT1DM: {len(cohort)} patients, {n_meals} meals (post-filter) → "
          f"rule labels: missed={counts['missed']} late={counts['late']} large={counts['large']}")

    print("\nDetection on REAL anomalies (rule-derived labels, glucose reacts)")
    print(f"  {'class':<8} {'prev':>7} {'pos':>7} {'AUPRC':>9} {'AUROC':>9}")
    for cls in ("missed", "late", "large"):
        fcol = N_CHANNELS + CLASS_IDX[cls]
        all_s, all_l = [], []
        for p in cohort:
            base = xf(p.render())                       # model input (real data)
            arr = base.copy()
            arr[:, N_CHANNELS:] = label_array(p, cfg, meals_of(p), LABEL_WIN[args.label_mode])[:, N_CHANNELS:]   # attach rule flags
            mean, std = _zscore_stats(base)
            s, l = score_patient(model, device, arr, p.valid, mean, std, fcol,
                                 args.stride, args.batch_size, args.score)
            all_s.append(s); all_l.append(l)
        scores, labels = np.concatenate(all_s), np.concatenate(all_l)
        if labels.sum() == 0:
            print(f"  {cls:<8}    n/a (no rule labels)"); continue
        print(f"  {cls:<8} {labels.mean():>7.2%} {int(labels.sum()):>7} "
              f"{average_precision_score(labels, scores):>9.4f} {roc_auc_score(labels, scores):>9.4f}")


if __name__ == "__main__":
    main()
