"""
Per-patient calibration + adaptation on WEEKS of real data (quality-program
Step 3, retried at scale).

Step 3 with 5 baseline days overfit a 464k net (over-detection 15%→29%). But
OhioT1DM gives ~8 weeks per patient in the TRAIN split (temporally before the
~10-day TEST split). This uses the full train weeks to (a) calibrate the
per-patient threshold/stats and (b) fine-tune the detector, then evaluates on the
test split (rule-derived labels). Train/test are separate periods → no leakage.

Three arms, isolating the data-scarcity question:
  base + 5d   : un-adapted, threshold from the test split's first 5 days (old way)
  base + wk   : un-adapted, threshold from the WEEKS of train data (calibration only)
  adapt + wk  : fine-tuned on weeks, threshold from weeks (calibration + adaptation)

If 'base + wk' cuts over-detection, calibration was data-starved. If 'adapt + wk'
also lifts detection, Step-3's refutation was scarcity, not a wrong idea.

Usage
-----
    python ml/ohio_eval/eval_adapt_weeks.py
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import roc_auc_score, average_precision_score

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import N_CHANNELS, set_seed  # noqa: E402
from features.iob_cob import to_iob_cob  # noqa: E402
from characterization.rules import RuleConfig  # noqa: E402
from ohio_eval.adapter import load_ohio_cohort  # noqa: E402
from ohio_eval.eval_proxy import label_array, CLASS_IDX  # noqa: E402
from ohio_eval.eval_adapt import adapt, score, _threshold, WIN, L  # noqa: E402
from models.xchannel.model import forecaster_from_ckpt  # noqa: E402

DAY = 1440


def _valid_starts(p, stride):
    return [s for s in range(0, p.T - WIN + 1, stride) if p.valid[s : s + WIN].all()]


def _zsignals(p, xf):
    bz = xf(p.render())
    m, s = bz[:, :N_CHANNELS].mean(0), bz[:, :N_CHANNELS].std(0).clip(1e-8)
    return bz, m, s


def main():
    ap = argparse.ArgumentParser(description="Per-patient adaptation on weeks (Ohio train split)")
    ap.add_argument("--checkpoint", type=Path, default=Path("ml/data/checkpoints/xchannel_nll_best.pt"))
    ap.add_argument("--features", choices=["raw", "iob_cob"], default="raw")
    ap.add_argument("--ohio_root", type=Path, default=Path("ml/data/real/ohio"))
    ap.add_argument("--adapt_epochs", type=int, default=3)
    ap.add_argument("--adapt_lr", type=float, default=1e-4)
    ap.add_argument("--adapt_stride", type=int, default=15)
    ap.add_argument("--eval_stride", type=int, default=5)
    ap.add_argument("--batch_size", type=int, default=128)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    set_seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    base = forecaster_from_ckpt(torch.load(args.checkpoint, map_location=device), device).eval()
    xf = to_iob_cob if args.features == "iob_cob" else (lambda a: a)
    cfg = RuleConfig()

    train = {p.pid: p for p in load_ohio_cohort(args.ohio_root, split="train")}
    test = {p.pid: p for p in load_ohio_cohort(args.ohio_root, split="test")}
    pids = sorted(set(train) & set(test))
    print(f"Device: {device} | base={args.checkpoint.name} | {len(pids)} patients with train+test")
    print(f"Adapt: {args.adapt_epochs} epochs, lr {args.adapt_lr}, stride {args.adapt_stride} "
          f"on ~weeks of train data")

    arms = ["base+5d", "base+wk", "adapt+wk"]
    S = {a: [] for a in arms}
    flag = {a: [0, 0] for a in arms}
    Lb = {c: [] for c in CLASS_IDX}

    for k, pid in enumerate(pids, 1):
        ptr, pte = train[pid], test[pid]
        # per-patient z-score from TRAIN stats (the patient's own history), applied to both
        _, m, s = _zsignals(ptr, xf)
        ztr = xf(ptr.render()).copy(); ztr[:, :N_CHANNELS] = (ztr[:, :N_CHANNELS] - m) / s
        zte = xf(pte.render()).copy(); zte[:, :N_CHANNELS] = (zte[:, :N_CHANNELS] - m) / s

        tr_starts = _valid_starts(ptr, args.adapt_stride)
        te_starts = _valid_starts(pte, args.eval_stride)
        if len(tr_starts) < 200 or not te_starts:
            continue
        print(f"  [{k}/{len(pids)}] {pid}: adapt on {len(tr_starts):,} train windows…", flush=True)

        adapted = adapt(base, ztr, tr_starts, device, args.adapt_epochs, args.adapt_lr, args.batch_size)

        # thresholds
        thr_5d = _threshold(score(base, zte, te_starts[: 5 * DAY // args.eval_stride], device))
        thr_wk_b = _threshold(score(base, ztr, tr_starts, device))
        thr_wk_a = _threshold(score(adapted, ztr, tr_starts, device))

        sc_b = score(base, zte, te_starts, device)
        sc_a = score(adapted, zte, te_starts, device)
        for arm, sc, thr in [("base+5d", sc_b, thr_5d), ("base+wk", sc_b, thr_wk_b),
                             ("adapt+wk", sc_a, thr_wk_a)]:
            S[arm].append(sc)
            flag[arm][0] += int((sc > thr).sum()); flag[arm][1] += len(sc)

        flags = label_array(pte, cfg)
        for c, j in CLASS_IDX.items():
            Lb[c].append(np.array([flags[st + L : st + WIN, N_CHANNELS + j].max() for st in te_starts]))

    labels = {c: np.concatenate(v) for c, v in Lb.items()}
    cat = {a: np.concatenate(S[a]) for a in arms}
    print(f"\nTest windows: {len(cat['base+5d']):,}")
    print(f"  {'class':<8} {'pos':>6} | " + " ".join(f"{a:>9}" for a in arms) + "   (AUROC)")
    for c in ("missed", "late", "large"):
        y = labels[c]
        if y.sum() == 0:
            print(f"  {c:<8}   n/a"); continue
        row = " ".join(f"{roc_auc_score(y, cat[a]):>9.3f}" for a in arms)
        print(f"  {c:<8} {int(y.sum()):>6} | {row}")
    print(f"\n  over-detection (flagged test windows):  " +
          "  ".join(f"{a}={flag[a][0]/flag[a][1]:.1%}" for a in arms))


if __name__ == "__main__":
    main()
