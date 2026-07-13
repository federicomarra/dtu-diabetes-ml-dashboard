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
    rows = _rows(n=12, step_min=5)               # 12 readings, 5-min -> spans 55 min -> T=56
    arr, valid, t0 = histories_to_array(rows)
    assert arr.shape == (56, 8)
    assert valid.all()                             # 5-min gaps are bridged, whole span usable
    assert arr[0, 0] == 7.0                         # glucose channel filled


def test_glucose_interpolated_between_5min_samples():
    """Real CGM is 5-min. Minutes between samples must carry an interpolated glucose
    (not 0.0) or the z-score and the forecaster see a square wave of zeros."""
    rows = _rows(n=12, step_min=5)                  # glucose 7.00, 7.01, ...
    arr, _, _ = histories_to_array(rows)
    assert arr[1, 0] > 0.0
    assert 7.0 < arr[3, 0] < 7.01                  # linear between sample 0 and sample 5


def test_long_gap_marked_invalid():
    """A CGM dropout longer than MAX_GAP_MIN must NOT be bridged."""
    base = datetime.fromisoformat("2026-01-01T00:00:00")
    rows = [
        {"timestamp": base.isoformat(), "glucose_mmoll": 7.0},
        {"timestamp": (base + timedelta(minutes=90)).isoformat(), "glucose_mmoll": 9.0},
    ]
    _, valid, _ = histories_to_array(rows)
    assert valid[0] and valid[90]
    assert not valid[45]                            # 90-min hole stays invalid


def test_five_min_cgm_yields_scoreable_windows():
    """Regression: the detector needs `valid[s:s+WIN].all()` over a 160-min window.
    With raw 5-min sampling no window ever qualified -> every real upload returned
    0 anomalies."""
    WIN = 160
    rows = _rows(n=200, step_min=5)                 # ~16.6 h of real-cadence CGM
    arr, valid, _ = histories_to_array(rows)
    starts = [s for s in range(0, arr.shape[0] - WIN + 1, 5) if valid[s:s + WIN].all()]
    assert len(starts) > 0


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


def test_rate_carbs_aggregate_to_one_meal():
    # sim/histories store carbs as g/min over absorption: 30 min @ 2 g/min = one 60 g meal.
    # The rule's min_carb_g=10 would drop each minute individually -> must aggregate the run.
    base = datetime.fromisoformat("2026-01-01T00:00:00")
    rows = [{"timestamp": (base + timedelta(minutes=i)).isoformat(),
             "glucose_mmoll": 7.0, "insulin_u": 0.0,
             "cho_grams": 2.0 if 100 <= i < 130 else 0.0} for i in range(300)]
    arr, _, _ = histories_to_array(rows)
    meals, _ = derive_events(arr)
    assert len(meals) == 1
    assert meals[0].minute == 100                 # onset of the run
    assert abs(meals[0].carb_g - 60.0) < 1e-6      # sum over the 30-min run


def test_zscore_only_touches_channels():
    arr, _, _ = histories_to_array(_rows())
    z = zscore_channels(arr)
    assert abs(z[:, :N_CHANNELS].mean()) < 1e-5      # ~zero mean on channels
    assert np.all(z[:, N_CHANNELS:] == 0)            # label channels untouched
    assert z.shape == arr.shape
