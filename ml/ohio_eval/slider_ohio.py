"""Precision per slider cutoff for the model we ACTUALLY serve, on the domain we
actually serve it in: xchannel_nll_pooled_best.pt on OhioT1DM, rule-derived labels.

The sim table (slider_calibration.py) used the sim-trained checkpoint on sim data.
Both are wrong for a number printed under the dashboard slider.
"""
import sys
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import average_precision_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dataset import N_CHANNELS  # noqa: E402
from characterization.rules import RuleConfig  # noqa: E402
from ohio_eval.adapter import load_ohio_cohort  # noqa: E402
from ohio_eval.eval_xchannel import score_patient, _zscore_stats, CLASS_IDX  # noqa: E402
from ohio_eval.eval_proxy import label_array, clean_meals  # noqa: E402
from models.xchannel.model import forecaster_from_ckpt  # noqa: E402
from models.patch_tst.anomaly_score import robust_baseline  # noqa: E402
from inference.detect import SCORE_MODE  # noqa: E402

CKPT = Path("ml/data/checkpoints/xchannel_nll_pooled_best.pt")
STRIDE = 5
CUTOFFS = [2, 4, 6, 8, 10, 15, 20, 30]

device = torch.device("cpu")
model = forecaster_from_ckpt(torch.load(CKPT, map_location=device), device); model.eval()
cohort = load_ohio_cohort(Path("ml/data/real/ohio"), year="both", split="test")
cfg = RuleConfig()
print(f"checkpoint={CKPT.name}  score_mode={SCORE_MODE}  ohio test patients={len(cohort)}")

sev_all, lab_all = [], []
for p in cohort:
    base = p.render()
    meals = clean_meals(p, meal_min_g=30.0, rescue_lookback=30)
    lab = label_array(p, cfg, meals, None, "flat", False, None)
    mean, std = _zscore_stats(base)

    per_class = []
    for cls in ("missed", "late"):
        arr = base.copy()
        arr[:, N_CHANNELS:] = lab[:, N_CHANNELS:]
        fcol = N_CHANNELS + CLASS_IDX[cls]
        s, l = score_patient(model, device, arr, p.valid, mean, std, fcol,
                             STRIDE, 512, SCORE_MODE)
        per_class.append(l)
    if len(per_class[0]) == 0:
        continue
    truth = (per_class[0] > 0) | (per_class[1] > 0)     # missed OR late
    med, sigma, _ = robust_baseline(s, k=2.0)           # `s` is score-mode identical per class
    sev_all.append((s - med) / sigma)
    lab_all.append(truth)

sev = np.concatenate(sev_all); truth = np.concatenate(lab_all)
days = len(sev) * STRIDE / 1440.0
print(f"windows={len(sev):,}  patient-days={days:,.0f}  prevalence(missed|late)={truth.mean():.2%}")
print(f"AUPRC of the severity ranking: {average_precision_score(truth, sev):.4f}\n")

print(f"{'cutoff':>7} {'shown':>8} {'precision':>10} {'recall':>8} {'per day':>9} {'lift':>7}")
base_rate = truth.mean()
for c in CUTOFFS:
    sel = sev >= c
    n = int(sel.sum())
    if n == 0:
        print(f"{c:>6}σ {n:>8} {'—':>10} {'—':>8} {0:>9.2f} {'—':>7}"); continue
    prec = truth[sel].mean()
    rec = (truth & sel).sum() / truth.sum()
    print(f"{c:>6}σ {n:>8} {prec:>9.1%} {rec:>7.1%} {n/days:>9.2f} {prec/base_rate:>6.2f}x")
