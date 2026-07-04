"""
Head-free detection for the demo: XCHANNEL forecast-residual -> per-patient robust
threshold -> events -> deterministic missed/late rule label.

This is the lean path `build_diary` minus the characterisation head: for a
missed/late-only demo the head is redundant (the rule labels missed/late
deterministically from logged carbs+insulin, and anomaly_strength comes from the
score), so we drop it - no head checkpoint, no MC-dropout, no OOD, and only ONE
detector forward pass per window (we skip the embedding pass build_diary needs).

DETECTION generalises ("unusual vs this patient's baseline"); the rule label is
deterministic, not a diagnosis. Returns events + the full window-score array so
the caller can map each event to a per-patient strength percentile.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import N_CHANNELS  # noqa: E402
from models.xchannel.model import CONTEXT_LEN, HORIZON, anomaly_score as compute_score  # noqa: E402
from models.patch_tst.anomaly_score import calibrate_threshold  # noqa: E402
from characterization.rules import classify_meals, RuleConfig  # noqa: E402

L, H, WIN = CONTEXT_LEN, HORIZON, CONTEXT_LEN + HORIZON
MERGE_GAP_MIN = 30          # flagged window starts within this gap -> one event


@dataclass
class Detection:
    start_min: int
    duration_min: int
    anomaly_score: float
    severity: float          # sigma above the patient's baseline median (same units as threshold_k)
    rule_label: str | None   # 'missed' / 'late' (deterministic) or None


def score_windows(arr, valid, detector, device, stride):
    """Per valid window: (start minute, forecast-residual score). One forward pass
    (no embeddings - the head path is dropped)."""
    T = arr.shape[0]
    z = arr[:, :N_CHANNELS]
    starts = [s for s in range(0, T - WIN + 1, stride) if valid[s : s + WIN].all()]
    if not starts:
        return [], np.empty(0)
    scores = []
    with torch.no_grad():
        for i in range(0, len(starts), 512):
            ch = starts[i : i + 512]
            glu = torch.stack([torch.from_numpy(z[s : s + L, 0].copy()) for s in ch]).to(device)
            ins = torch.stack([torch.from_numpy(z[s : s + WIN, 1].copy()) for s in ch]).to(device)
            car = torch.stack([torch.from_numpy(z[s : s + WIN, 2].copy()) for s in ch]).to(device)
            tgt = torch.stack([torch.from_numpy(z[s + L : s + WIN, 0].copy()) for s in ch]).to(device)
            scores.append(compute_score(detector(glu, ins, car), tgt).cpu().numpy())
    return starts, np.concatenate(scores)


def _group(flagged, stride):
    if not flagged:
        return []
    groups, cur = [], [flagged[0]]
    for s in flagged[1:]:
        if s - cur[-1] <= MERGE_GAP_MIN:
            cur.append(s)
        else:
            groups.append(cur); cur = [s]
    groups.append(cur)
    return groups


def detect(arr, valid, *, detector, device=None, stride=5, n_cal_days=5,
           threshold_k=2.0, min_event_min=30, meals=None, boluses=None,
           rule_cfg=RuleConfig()) -> tuple[list[Detection], np.ndarray]:
    """Returns (events, all_window_scores). arr must be per-patient z-scored already."""
    device = device or torch.device("cpu")
    starts, scores = score_windows(arr, valid, detector, device, stride)
    if not starts:
        return [], np.asarray([], dtype=float)

    n_cal = min(len(scores), n_cal_days * 1440 // stride)
    thr = calibrate_threshold(scores, n_cal, k=threshold_k)         # median + k*IQR on baseline days
    flagged = [s for s, sc in zip(starts, scores) if sc > thr]

    # robust baseline stats (same window/spread the threshold uses) -> per-event severity
    # in sigma above the patient's median: interpretable AND magnitude-discriminating (unlike a
    # percentile, which saturates near 100% for every flagged tail event).
    base = scores[:n_cal]
    med = float(np.median(base))
    sigma = max(float(np.subtract(*np.percentile(base, [75, 25])) / 1.349), 1e-9)

    rule_minutes = classify_meals(meals, boluses or [], rule_cfg) if meals is not None else {}
    pos = {s: i for i, s in enumerate(starts)}

    events: list[Detection] = []
    for grp in _group(flagged, stride):
        start_min = grp[0] + L                                       # anomaly lives in the horizon
        end_min = grp[-1] + WIN
        if end_min - start_min < min_event_min:
            continue
        label = None
        for cls, mins in rule_minutes.items():
            if cls in ("missed", "late") and any(start_min - WIN <= m <= end_min for m in mins):
                label = cls; break
        peak = float(max(scores[pos[s]] for s in grp))
        severity = (peak - med) / sigma
        events.append(Detection(start_min, end_min - start_min, peak, severity, label))
    return events, np.asarray(scores, dtype=float)
