"""
Pure transforms for the inference microservice: histories rows → model input.

The ML service is stateless. The backend sends the `histories` rows (glucose,
insulin, carbs per timestamp) as JSON; this module turns them into the [T,8]
array + valid mask the forecaster expects, and derives the meal/bolus events the
rule layer needs (missed/late). No DB, no torch here — trivially unit-testable.
`patient_id` is request-envelope metadata (handled by the Flask layer), NOT part
of these rows — the math never needs it.

`histories_to_array` builds a 1-minute grid from the timestamps (real CGM is
5-min, so most grid minutes are empty → `valid` is sparse, exactly like the Ohio
adapter). Channels: 0=glucose mmol/L, 1=insulin U/min, 2=carbs g; 3-7 are the
anomaly-label channels (zeros at inference).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

import numpy as np
from scipy.ndimage import median_filter

N_CHANNELS = 3            # glucose, insulin, carbs (label channels 3-7 stay zero)
_ARR_WIDTH = 8
_BASAL_WINDOW = 61        # median-filter window (min) to estimate basal → bolus = spike above it
_BOLUS_MIN_U = 0.05       # an insulin spike below this isn't a bolus


@dataclass
class _Meal:
    minute: int
    carb_g: float


@dataclass
class _Bolus:
    minute: int
    units: float


def _parse_ts(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts
    s = str(ts).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def histories_to_array(rows: Sequence[dict]) -> tuple[np.ndarray, np.ndarray, datetime | None]:
    """
    rows: list of {timestamp, glucose_mmoll, insulin_u, cho_grams} (any order).
    Returns (arr[T,8] float32, valid[T] bool, t0 datetime) on a 1-minute grid
    spanning first→last timestamp. `valid[t]` = a glucose reading exists at minute t.
    """
    if not rows:
        return np.zeros((0, _ARR_WIDTH), np.float32), np.zeros(0, bool), None

    parsed = sorted(((_parse_ts(r["timestamp"]), r) for r in rows), key=lambda x: x[0])
    t0 = parsed[0][0]
    minute_of = lambda ts: int(round((ts - t0).total_seconds() / 60.0))
    T = minute_of(parsed[-1][0]) + 1

    arr = np.zeros((T, _ARR_WIDTH), np.float32)
    valid = np.zeros(T, bool)
    for ts, r in parsed:
        m = minute_of(ts)
        if not (0 <= m < T):
            continue
        g = r.get("glucose_mmoll")
        if g is not None and np.isfinite(g):
            arr[m, 0] = float(g)
            valid[m] = True
        ins = r.get("insulin_u")
        if ins is not None and np.isfinite(ins):
            arr[m, 1] = float(ins)
        cho = r.get("cho_grams")
        if cho is not None and np.isfinite(cho):
            arr[m, 2] = float(cho)
    return arr, valid, t0


def derive_events(arr: np.ndarray) -> tuple[list[_Meal], list[_Bolus]]:
    """
    Meals = minutes with carbs > 0 (col 2). Boluses = insulin spikes above the
    rolling basal estimate (col 1 minus its median filter), the same basal/bolus
    split used in gap_assess. Feeds rules.classify_meals (.minute/.carb_g/.units).
    """
    if arr.shape[0] == 0:
        return [], []
    cho = arr[:, 2]
    meals = [_Meal(int(m), float(cho[m])) for m in np.nonzero(cho > 0)[0]]

    ins = arr[:, 1].astype(float)
    win = min(_BASAL_WINDOW, len(ins) if len(ins) % 2 else len(ins) - 1) or 1
    basal = median_filter(ins, size=win)
    spike = ins - basal
    boluses = [_Bolus(int(m), float(spike[m])) for m in np.nonzero(spike > _BOLUS_MIN_U)[0]]
    return meals, boluses


def zscore_channels(arr: np.ndarray) -> np.ndarray:
    """Per-patient z-score of channels 0-2 (deployment uses the patient's own stats),
    matching diary.py. Returns a new array; label channels untouched."""
    out = arr.copy()
    m = out[:, :N_CHANNELS].mean(0)
    s = out[:, :N_CHANNELS].std(0).clip(1e-8)
    out[:, :N_CHANNELS] = (out[:, :N_CHANNELS] - m) / s
    return out
