"""Unit tests for the pure inference loader transforms (no DB, no torch)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from inference.loader import histories_to_array, derive_events, zscore_channels, N_CHANNELS  # noqa: E402


def _rows(n=60, step_min=5, t0="2026-01-01T00:00:00"):
    base = datetime.fromisoformat(t0)
    rows = []
    for i in range(n):
        rows.append({
            "timestamp": (base + timedelta(minutes=i * step_min)).isoformat(),
            "glucose_mmoll": 7.0 + i * 0.01,
            "insulin_u": 0.01,                       # basal
            "cho_grams": 0.0,
        })
    return rows


def test_empty_rows():
    arr, valid, t0 = histories_to_array([])
    assert arr.shape == (0, 8) and valid.shape == (0,) and t0 is None


def test_grid_and_valid_mask():
    rows = _rows(n=12, step_min=5)               # 12 readings, 5-min → spans 55 min → T=56
    arr, valid, t0 = histories_to_array(rows)
    assert arr.shape == (56, 8)
    assert valid.sum() == 12                       # only sampled minutes are valid
    assert valid[0] and valid[5] and not valid[1]  # 5-min grid, gaps between
    assert arr[0, 0] == 7.0                         # glucose channel filled


def test_unordered_input_sorted():
    rows = _rows(n=5, step_min=5)
    arr_sorted, _, _ = histories_to_array(rows)
    arr_shuf, _, _ = histories_to_array(list(reversed(rows)))
    assert np.allclose(arr_sorted, arr_shuf)        # order-independent


def test_derive_events_meals_and_boluses():
    rows = _rows(n=60, step_min=5)
    rows[10]["cho_grams"] = 45.0                     # a meal at minute 50
    rows[10]["insulin_u"] = 5.0                      # a bolus spike same minute
    arr, _, _ = histories_to_array(rows)
    meals, boluses = derive_events(arr)
    assert any(m.carb_g == 45.0 and m.minute == 50 for m in meals)
    assert any(b.minute == 50 and b.units > 1.0 for b in boluses)   # spike above basal


def test_no_meal_when_no_carbs():
    arr, _, _ = histories_to_array(_rows())
    meals, _ = derive_events(arr)
    assert meals == []


def test_zscore_only_touches_channels():
    arr, _, _ = histories_to_array(_rows())
    z = zscore_channels(arr)
    assert abs(z[:, :N_CHANNELS].mean()) < 1e-5      # ~zero mean on channels
    assert np.all(z[:, N_CHANNELS:] == 0)            # label channels untouched
    assert z.shape == arr.shape
