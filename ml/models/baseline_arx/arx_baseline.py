"""
ARX residual baseline — tests the core hypothesis.

Hypothesis
----------
The anomaly signal these classes need is CONDITIONAL: does glucose follow from
the known inputs (insulin, announced carbs)? PatchTST is channel-independent
(glucose predicted from glucose alone) and so is structurally blind to this.

This script fits a cheap linear ARX model — glucose[t] from lagged glucose +
lagged/current insulin + lagged/current carbs — on NORMAL training behaviour,
then scores anomalies by the prediction residual. It runs TWO variants:

  conditional : features = past glucose + insulin + carbs   (uses the inputs)
  glucose_only: features = past glucose only                (mimics PatchTST's
                                                              channel-independence)

If `conditional` beats `glucose_only` on missed/late AUPRC, the channel-
independence ceiling is real and cross-channel conditioning is the fix — and a
~100-line linear model establishing that is the strongest insight-per-hour we
can get before building a new transformer.

Usage
-----
    python ml/models/baseline_arx/arx_baseline.py            # 500p local
    python ml/models/baseline_arx/arx_baseline.py --n_train 150 --n_test 100
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.linear_model import Ridge
from sklearn.metrics import average_precision_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from dataset import (
    load_patients, _patient_zscore, make_patient_split,
    ANOMALY_CLASSES, WINDOW_LEN, N_CHANNELS,
)

PARQUET_500 = Path("ml/data/sim_data/results_500p_14d_clean.parquet")
LAG = 30          # minutes of history fed to the linear model
STRIDE = 5        # window stride for scoring


def build_xy(arr: np.ndarray, lag: int, horizon: int, conditional: bool):
    """
    H-step forecast: predict glucose[t+H] WITHOUT seeing glucose in (t, t+H].

    glucose feature : glucose[t-lag : t]            (history only)
    exogenous       : insulin/carbs over [t-lag : t+H]  (known through horizon)
                      — only if conditional.
    target          : glucose[t+H]

    The control (glucose_only) must extrapolate H minutes with no knowledge of
    meals/insulin in the gap — exactly PatchTST's channel-independent blind spot.
    Returns (X, y, anchor_t).
    """
    glu, ins, carb = arr[:, 0], arr[:, 1], arr[:, 2]
    T = arr.shape[0]
    n = T - lag - horizon                                         # number of anchors
    glu_past = sliding_window_view(glu, lag)[:n]                  # [n, lag], anchor t=i+lag
    feats = [glu_past]
    if conditional:
        w = lag + horizon                                        # cover [t-lag, t+H)
        feats.append(sliding_window_view(ins,  w)[:n])
        feats.append(sliding_window_view(carb, w)[:n])
    X = np.hstack(feats)
    y = glu[lag + horizon : T]                                   # glucose[t+H]
    anchor_t = np.arange(lag, T - horizon)
    return X.astype(np.float32), y.astype(np.float32), anchor_t


def per_minute_residual(arr, model, lag, horizon, conditional):
    """Squared H-step forecast residual, indexed at the anchor minute t."""
    X, y, anchor_t = build_xy(arr, lag, horizon, conditional)
    pred = model.predict(X)
    r = np.zeros(arr.shape[0], dtype=np.float32)
    r[anchor_t] = (y - pred) ** 2
    return r


def window_scores_labels(arr, r, lag, horizon, stride):
    """Window-level score (mean residual over anchors) + per-class max-flag labels."""
    T = arr.shape[0]
    flags = arr[:, N_CHANNELS:]
    csum = np.concatenate([[0.0], np.cumsum(r)])
    starts = np.arange(lag, T - horizon - WINDOW_LEN + 1, stride)
    scores = (csum[starts + WINDOW_LEN] - csum[starts]) / WINDOW_LEN
    win_max = sliding_window_view(flags, WINDOW_LEN, axis=0).max(axis=2)
    sel = win_max[starts]
    labels = {cls: sel[:, j] for j, cls in enumerate(ANOMALY_CLASSES)}
    return scores, labels


def fit_and_eval(train, test, lag, horizon, conditional, stride, max_rows=800_000):
    # Subsample rows PER PATIENT before stacking — stacking all rows first
    # OOM's a laptop (150 features × millions of rows).
    rng = np.random.default_rng(42)
    per = max(1, max_rows // max(1, len(train)))
    Xs, ys = [], []
    for arr in train.values():
        X, y, _ = build_xy(arr, lag, horizon, conditional)
        if len(X) > per:
            idx = rng.choice(len(X), per, replace=False)
            X, y = X[idx], y[idx]
        Xs.append(X); ys.append(y)
    X = np.vstack(Xs); y = np.concatenate(ys)
    model = Ridge(alpha=1.0).fit(X, y)
    del Xs, ys, X, y

    all_s, all_l = [], {cls: [] for cls in ANOMALY_CLASSES}
    for arr in test.values():
        r = per_minute_residual(arr, model, lag, horizon, conditional)
        s, lab = window_scores_labels(arr, r, lag, horizon, stride)
        all_s.append(s)
        for cls in ANOMALY_CLASSES:
            all_l[cls].append(lab[cls])
    scores = np.concatenate(all_s)
    labels = {cls: np.concatenate(v) for cls, v in all_l.items()}
    return scores, labels


def report(tag, scores, labels):
    anyl = (np.stack([labels[c] for c in ANOMALY_CLASSES]).max(0) > 0).astype(np.float32)
    print(f"\n[{tag}]  windows={len(scores):,}  any-anomaly baseline={anyl.mean():.2%}")
    print(f"  ANY-ANOMALY  AUPRC={average_precision_score(anyl, scores):.4f}  "
          f"AUROC={roc_auc_score(anyl, scores):.4f}")
    print(f"  {'class':<12} {'prev':>7} {'AUPRC':>9} {'AUROC':>9}")
    for cls in ANOMALY_CLASSES:
        y = labels[cls]
        ap = average_precision_score(y, scores) if y.sum() else float("nan")
        au = roc_auc_score(y, scores) if y.sum() else float("nan")
        print(f"  {cls:<12} {y.mean():>7.2%} {ap:>9.4f} {au:>9.4f}")


def main():
    ap = argparse.ArgumentParser(description="ARX residual baseline")
    ap.add_argument("--parquet", type=Path, default=PARQUET_500)
    ap.add_argument("--n_train", type=int, default=150)
    ap.add_argument("--n_test",  type=int, default=100)
    ap.add_argument("--lag",     type=int, default=LAG)
    ap.add_argument("--horizon", type=int, default=30, help="forecast horizon in minutes")
    ap.add_argument("--stride",  type=int, default=STRIDE)
    args = ap.parse_args()

    split = make_patient_split(args.parquet, out=Path("/tmp/_arx_split.json"))
    train_ids = split["train"][: args.n_train]
    test_ids  = split["test"][: args.n_test]

    t0 = time.time()
    print(f"Loading {len(train_ids)} train + {len(test_ids)} test patients …")
    train = {p: _patient_zscore(a, inplace=True) for p, a in load_patients(train_ids, args.parquet).items()}
    test  = {p: _patient_zscore(a, inplace=True) for p, a in load_patients(test_ids,  args.parquet).items()}
    print(f"  loaded in {time.time()-t0:.0f}s")

    print(f"Forecast horizon H={args.horizon} min, lag={args.lag} min")
    for conditional in (False, True):
        tag = "conditional (glu+insulin+carbs)" if conditional else "glucose_only (PatchTST-like)"
        s, l = fit_and_eval(train, test, args.lag, args.horizon, conditional, args.stride)
        report(tag, s, l)


if __name__ == "__main__":
    main()
