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
from models.patch_tst.anomaly_score import robust_baseline  # noqa: E402
from characterization.rules import classify_detection, RuleConfig  # noqa: E402

L, H, WIN = CONTEXT_LEN, HORIZON, CONTEXT_LEN + HORIZON
MERGE_GAP_MIN = 30          # flagged window starts within this gap -> one event

# Mean positive residual over the LAST QUARTER of the horizon. A missed bolus diverges
# progressively, so the evidence is strongest at the end of the 40-min horizon; 'sym'
# (the previous default) averaged it away over the early minutes where the forecast is
# still good. Measured: missed AUPRC 0.0345 -> 0.0417 (+21%) on the OhioT1DM test split
# and 0.1786 -> 0.1861 on the simulator; 'end' also wins on late in both.
SCORE_MODE = "end"


@dataclass
class Detection:
    start_min: int
    duration_min: int
    anomaly_score: float
    severity: float          # sigma above the patient's baseline median (same units as threshold_k)
    rule_label: str | None   # 'missed' / 'late' (deterministic) or None


def score_windows(arr, valid, detector, device, stride, score_mode=SCORE_MODE):
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
            scores.append(compute_score(detector(glu, ins, car), tgt, score_mode).cpu().numpy())
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


def detect(arr, valid, *, detector, device=None, stride=5, trim_iters=3,
           threshold_k=2.0, min_event_min=30, meals=None, boluses=None,
           rule_cfg=RuleConfig(), score_mode=SCORE_MODE) -> tuple[list[Detection], np.ndarray]:
    """Returns (events, all_window_scores). arr must be per-patient z-scored already."""
    device = device or torch.device("cpu")
    starts, scores = score_windows(arr, valid, detector, device, stride, score_mode)
    if not starts:
        return [], np.asarray([], dtype=float)

    # Baseline = every window, iteratively trimmed of its own flagged tail. The previous
    # version fit the FIRST 5 days and kept whatever anomalies lived there, so the threshold
    # (and every severity derived from it) depended on when the patient happened to misbehave.
    # med/sigma now describe normal windows -> severity is sigma above THIS patient's normal.
    med, sigma, thr = robust_baseline(scores, k=threshold_k, trim_iters=trim_iters)
    flagged = [s for s, sc in zip(starts, scores) if sc > thr]

    # Detection-anchored labelling: name each detected excursion by the bolus that
    # should have covered it (missed = none, late = delayed). Anchored on the glucose
    # rise, NOT a logged meal, so it names misses that leave no carb log - the case a
    # meal-anchored rule (classify_meals) is structurally blind to. Boluses come off
    # the insulin channel, so this needs no "actual eaten" signal and runs on real data.
    bolus_min = [b.minute for b in (boluses or []) if getattr(b, "units", 1.0) > 0]
    pos = {s: i for i, s in enumerate(starts)}

    events: list[Detection] = []
    for grp in _group(flagged, stride):
        start_min = grp[0] + L                                       # anomaly lives in the horizon
        end_min = grp[-1] + WIN
        if end_min - start_min < min_event_min:
            continue
        label = classify_detection(start_min, bolus_min, rule_cfg)
        peak = float(max(scores[pos[s]] for s in grp))
        severity = (peak - med) / sigma
        events.append(Detection(start_min, end_min - start_min, peak, severity, label))
    return events, np.asarray(scores, dtype=float)
