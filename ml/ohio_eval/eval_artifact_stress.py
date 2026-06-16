"""
Sensor-artifact stress test: inject dropouts/jumps/compression into glucose,
score with the existing XCHANNEL checkpoint, and measure (a) AUROC on true
anomalies (clean vs injected) and (b) false-positive rate at artifact-only
windows. Decision gate for the train-time augmentation (Step 2).

    .venv/bin/python ml/ohio_eval/eval_artifact_stress.py                 # sim-test
    .venv/bin/python ml/ohio_eval/eval_artifact_stress.py --data ohio     # real target

Dropouts set valid=False → those windows stay skipped by the scorer (realistic
deployment). Jumps/compression keep valid=True → those windows ARE scored, which
is where false positives show. The int-coded artifact mask attributes each FP.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import load_patients, make_patient_split, N_CHANNELS  # noqa: E402
from augment.sensor_artifacts import apply_artifacts, ArtifactConfig, CLEAN  # noqa: E402
from models.xchannel.model import (  # noqa: E402
    forecaster_from_ckpt, anomaly_score as compute_score, CONTEXT_LEN, HORIZON,
)

L, H, WIN = CONTEXT_LEN, HORIZON, CONTEXT_LEN + HORIZON


def _zscore_stats(arr):
    sig = arr[:, :N_CHANNELS]
    return sig.mean(0), sig.std(0).clip(min=1e-8)


@torch.no_grad()
def score(model, device, arr, valid, amask, mean, std, stride, bs):
    """Per-window (score, true_label, artifact_flag) for valid windows."""
    T = arr.shape[0]
    z = (arr[:, :N_CHANNELS] - mean) / std
    starts = [s for s in range(0, T - WIN + 1, stride) if valid[s:s + WIN].all()]
    if not starts:
        return np.empty(0), np.empty(0), np.empty(0, dtype=bool)
    sc, lab, art = [], [], []
    for i in range(0, len(starts), bs):
        chunk = starts[i:i + bs]
        glu = torch.stack([torch.from_numpy(z[s:s + L, 0].copy()) for s in chunk]).to(device)
        ins = torch.stack([torch.from_numpy(z[s:s + WIN, 1].copy()) for s in chunk]).to(device)
        car = torch.stack([torch.from_numpy(z[s:s + WIN, 2].copy()) for s in chunk]).to(device)
        tgt = torch.stack([torch.from_numpy(z[s + L:s + WIN, 0].copy()) for s in chunk]).to(device)
        sc.append(compute_score(model(glu, ins, car), tgt).cpu().numpy())
        lab.append(np.array([arr[s + L:s + WIN, N_CHANNELS:].max() for s in chunk], dtype=np.float32))
        art.append(np.array([(amask[s + L:s + WIN] != CLEAN).any() for s in chunk], dtype=bool))
    return np.concatenate(sc), np.concatenate(lab), np.concatenate(art)


def threshold(scores, k=2.0):
    """Per-cohort robust threshold: median + k·IQR/1.349 (matches diary default)."""
    med = np.median(scores)
    iqr = np.subtract(*np.percentile(scores, [75, 25]))
    return med + k * (iqr / 1.349)


def run_pairs(model, device, patients, cfg, args, label):
    """patients: iterable of (pid, arr[T,>=N_CHANNELS+5], valid[T]).

    Scores each patient clean and artifact-injected (same z-score stats), then
    reports true-anomaly AUROC and FP-rate at artifact-only windows.
    """
    clean_s, clean_l = [], []
    inj_s, inj_l, inj_a = [], [], []
    for j, (pid, arr, valid) in enumerate(patients):
        T = arr.shape[0]
        mean, std = _zscore_stats(arr)
        s, l, _ = score(model, device, arr, valid, np.zeros(T, np.int8),
                        mean, std, args.stride, args.batch_size)
        clean_s.append(s); clean_l.append(l)
        rng = np.random.default_rng(args.seed + j)
        g2, v2, amask = apply_artifacts(arr[:, 0], valid, rng, cfg)
        arr2 = arr.copy(); arr2[:, 0] = g2
        s2, l2, a2 = score(model, device, arr2, v2, amask,
                           mean, std, args.stride, args.batch_size)
        inj_s.append(s2); inj_l.append(l2); inj_a.append(a2)

    cs, cl = np.concatenate(clean_s), np.concatenate(clean_l)
    is_, il, ia = np.concatenate(inj_s), np.concatenate(inj_l), np.concatenate(inj_a)
    thr = threshold(cs)
    artonly = ia & (il == 0)
    nonart = (~ia) & (il == 0)

    print(f"\n=== {label}  ({len(cs):,} clean / {len(is_):,} injected windows) ===")
    print(f"Threshold (clean median+2·IQR/1.349) = {thr:.4f}")
    print(f"True-anomaly AUROC   clean={roc_auc_score(cl, cs):.4f}   injected={roc_auc_score(il, is_):.4f}")
    print(f"FP-rate @ artifact-only windows = {(is_[artonly] > thr).mean():.4%}  (n={int(artonly.sum())})")
    print(f"FP-rate @ clean-normal windows  = {(is_[nonart] > thr).mean():.4%}  (n={int(nonart.sum())})")


def _sim_patients(args):
    ids = make_patient_split(args.parquet)["test"][:args.test_patients]
    for pid, arr in load_patients(ids, args.parquet).items():
        yield pid, arr, np.ones(arr.shape[0], dtype=bool)


def _ohio_patients(args):
    from ohio_eval.adapter import load_ohio_cohort
    from ohio_eval.eval_proxy import label_array
    from characterization.rules import RuleConfig
    cfg = RuleConfig()
    for p in load_ohio_cohort(args.ohio_root, year="both", split="test"):
        arr = p.render()
        arr[:, N_CHANNELS:] = label_array(p, cfg)[:, N_CHANNELS:]   # rule anomaly flags
        yield p.pid, arr, p.valid


def main():
    ap = argparse.ArgumentParser(description="XCHANNEL sensor-artifact stress test")
    ap.add_argument("--checkpoint", type=Path, default=Path("ml/data/checkpoints/xchannel_nll_best.pt"))
    ap.add_argument("--data", choices=["sim", "ohio"], default="sim")
    ap.add_argument("--parquet", type=Path, default=Path("ml/data/sim_data/results_5000p_42d.parquet"))
    ap.add_argument("--ohio_root", type=Path, default=Path("ml/data/real/ohio"))
    ap.add_argument("--test_patients", type=int, default=200)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--batch_size", type=int, default=512)
    ap.add_argument("--dropout_pct", type=float, default=0.10)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(args.checkpoint, map_location=device)
    model = forecaster_from_ckpt(ckpt, device); model.eval()
    print(f"Device {device} | data={args.data} | epoch {ckpt['epoch']} "
          f"val={ckpt.get('val_loss', float('nan')):.4f}")

    cfg = ArtifactConfig(dropout_pct=args.dropout_pct)
    patients = _ohio_patients(args) if args.data == "ohio" else _sim_patients(args)
    run_pairs(model, device, patients, cfg, args, label=args.data)


if __name__ == "__main__":
    main()
