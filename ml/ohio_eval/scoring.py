"""
Shared XCHANNEL windowing/scoring primitives for the OhioT1DM eval scripts.

Every eval here (plain, adaptation, artifact stress, sim-injection control) needs
the same three steps: z-score the channels, slice sliding windows into the model's
(glucose history, insulin+carb context, glucose target) tensors, and run the model
in batches to get a per-window anomaly score. Only the label/flag bookkeeping differs
between scripts, so that part stays in each caller.
"""

import sys
from pathlib import Path

import numpy as np
import torch
from scipy.stats import iqr as _iqr

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import N_CHANNELS  # noqa: E402
from models.xchannel.model import (  # noqa: E402
    anomaly_score as compute_score, CONTEXT_LEN, HORIZON,
)

L, H, WIN = CONTEXT_LEN, HORIZON, CONTEXT_LEN + HORIZON


def robust_threshold(x, k=2.0, floor=0.0):
    """Robust anomaly threshold: median + k * IQR/1.349 (IQR/1.349 is the std of a
    Gaussian). `floor` puts a lower bound on the IQR term to avoid a zero width."""
    return float(np.median(x) + k * max(_iqr(x) / 1.349, floor))


def zscore_stats(arr):
    """Per-patient (mean, std) over the model channels; std floored to avoid /0."""
    sig = arr[:, :N_CHANNELS]
    return sig.mean(0), sig.std(0).clip(min=1e-8)


def valid_starts(T, stride, valid=None):
    """Window start indices in [0, T-WIN]. If `valid` is given, keep only windows
    whose every minute has a glucose reading (real CGM is sparse)."""
    rng = range(0, T - WIN + 1, stride)
    if valid is None:
        return list(rng)
    return [s for s in rng if valid[s : s + WIN].all()]


def window_tensors(z, starts, device):
    """Stack the four model inputs for a batch of window starts on `z` [T, C]:
    glucose history [B, L], insulin/carb context [B, WIN], glucose target [B, H]."""
    glu = torch.stack([torch.from_numpy(z[s : s + L, 0].copy()) for s in starts]).to(device)
    ins = torch.stack([torch.from_numpy(z[s : s + WIN, 1].copy()) for s in starts]).to(device)
    car = torch.stack([torch.from_numpy(z[s : s + WIN, 2].copy()) for s in starts]).to(device)
    tgt = torch.stack([torch.from_numpy(z[s + L : s + WIN, 0].copy()) for s in starts]).to(device)
    return glu, ins, car, tgt


@torch.no_grad()
def score_windows(model, z, starts, device, batch=512, score_mode="sym"):
    """Per-window anomaly score for the given starts, evaluated in batches."""
    out = []
    for b in range(0, len(starts), batch):
        glu, ins, car, tgt = window_tensors(z, starts[b : b + batch], device)
        out.append(compute_score(model(glu, ins, car), tgt, score_mode).cpu().numpy())
    return np.concatenate(out) if out else np.empty(0)
