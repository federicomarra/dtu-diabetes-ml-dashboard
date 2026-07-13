"""What does a slider position actually buy you? Answer it with numbers, so the frontend
knob is chosen on evidence rather than taste.

For each severity cutoff it reports, at the WINDOW level:
  precision  - of the windows shown, how many are truly missed/late
  recall     - of the true missed/late windows, how many are shown
  shown/day  - the review workload the clinician actually feels
and the same three with the direction gate applied (below-forecast windows dropped),
so the gate's contribution is separable from the cutoff's.

CAUTION - match the checkpoint to the domain. This script defaults to the SIM-TRAINED
checkpoint on SIMULATED patients, which is an in-domain upper bound and NOT what the
dashboard serves. The dashboard serves xchannel_nll_pooled_best.pt on real CGM; measure
that with ml/ohio_eval/slider_ohio.py. At 6 sigma the two disagree by 3.5x
(sim 31.8% precision, real Ohio 9.2%). Quoting the sim number in the UI would be a lie.

A Glooko/pump export carries no labels at all (carbs are logged only when a bolus fired),
so precision cannot be measured on the patient actually being displayed.

    python ml/scripts/slider_calibration.py --n_patients 40 --stride 10
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import average_precision_score
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dataset import make_patient_split, progress_log, ANOMALY_CLASSES  # noqa: E402
from models.xchannel.model import forecaster_from_ckpt, anomaly_score  # noqa: E402
from models.xchannel.dataset import ForecastWindowDataset  # noqa: E402
from models.patch_tst.anomaly_score import robust_baseline  # noqa: E402
from inference.detect import SCORE_MODE  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--checkpoint", type=Path, default=Path("ml/data/checkpoints/xchannel_nll_best.pt"),
               help="sim-trained by default: the simulator is its own domain")
p.add_argument("--parquet", type=Path, default=Path("ml/data/sim_data/results_5000p_42d.parquet"))
p.add_argument("--n_patients", type=int, default=40)
p.add_argument("--stride", type=int, default=10)
p.add_argument("--batch_size", type=int, default=512)
p.add_argument("--num_workers", type=int, default=4)
p.add_argument("--cutoffs", type=float, nargs="+", default=[2, 4, 6, 8, 10, 15, 20, 30])
args = p.parse_args()

device = torch.device("cpu")
model = forecaster_from_ckpt(torch.load(args.checkpoint, map_location=device), device)
model.eval()

split = make_patient_split(args.parquet)
ds = ForecastWindowDataset(split["test"][:args.n_patients], scalers=None, parquet=args.parquet,
                           stride=args.stride, norm="per_patient", train_on="all", features="raw")
loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)
print(f"checkpoint={args.checkpoint.name}  score_mode={SCORE_MODE}  "
      f"patients={args.n_patients}  windows={len(ds):,}  stride={args.stride}")

scores, directions, labels = [], [], {c: [] for c in ANOMALY_CLASSES}
import time; t0 = time.time(); n = len(loader)
with torch.no_grad():
    for i, (glu, ins, carb, target, ld) in enumerate(loader, 1):
        out = model(glu, ins, carb)
        mean = out[0] if isinstance(out, tuple) else out
        tail = max(1, mean.shape[1] // 4)
        scores.append(anomaly_score(out, target, SCORE_MODE).numpy())
        directions.append((target[:, -tail:] - mean[:, -tail:]).mean(dim=1).numpy())
        for c in ANOMALY_CLASSES:
            labels[c].append(ld[c].numpy())
        progress_log(i, n, t0, label="forecast")

scores = np.concatenate(scores)
directions = np.concatenate(directions)
labels = {c: np.concatenate(v).astype(bool) for c, v in labels.items()}
truth = labels["missed"] | labels["late"]

# severity per patient, exactly as detect.py computes it
sev = np.empty_like(scores, dtype=float)
off = 0
for _pid, cnt in ds.patient_window_counts():
    s = scores[off:off + cnt]
    med, sigma, _ = robust_baseline(s, k=2.0)
    sev[off:off + cnt] = (s - med) / sigma
    off += cnt
assert off == len(scores)

minutes_per_window = args.stride
total_days = len(scores) * minutes_per_window / 1440.0
print(f"\nprevalence of true missed|late windows: {truth.mean():.2%}   "
      f"cohort spans {total_days:,.0f} patient-days")
print(f"AUPRC of the severity ranking (primary metric): {average_precision_score(truth, sev):.4f}")
print(f"AUPRC with below-forecast windows demoted     : "
      f"{average_precision_score(truth, np.where(directions >= 0, sev, sev.min() - 1)):.4f}")

hdr = (f"\n{'cutoff':>7} | {'shown':>8} {'prec':>7} {'recall':>7} {'per day':>8} "
       f"| {'shown':>8} {'prec':>7} {'recall':>7} {'per day':>8}")
print(hdr)
print(f"{'':>7} | {'--- no direction gate ---':^34} | {'--- with direction gate ---':^34}")
print("-" * len(hdr))
for c in args.cutoffs:
    for gate in (False, True):
        sel = sev >= c
        if gate:
            sel = sel & (directions >= 0)
        shown = int(sel.sum())
        prec = truth[sel].mean() if shown else float("nan")
        rec = (truth & sel).sum() / truth.sum() if truth.sum() else float("nan")
        per_day = shown / total_days
        cells = f"{shown:>8} {prec:>7.1%} {rec:>7.1%} {per_day:>8.2f}"
        if not gate:
            line = f"{c:>6.0f}σ | {cells} |"
        else:
            print(line + f" {cells}")
