"""Unit tests for glucose-derived label placement."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from realdata.excursion import excursion_window, ExcursionCfg  # noqa: E402


def _trace(T=600, base=7.0):
    return np.full(T, base, dtype=float)


def _window(g, meal, cls):
    """excursion_window on a case known to rise; asserts (and narrows) the non-None path."""
    w = excursion_window(g, meal, cls)
    assert w is not None
    return w


def test_clean_rise_and_return():
    """A clear rise->return excursion is bracketed tightly around it."""
    g = _trace()
    meal = 100
    # flat baseline 7.0; ramp up to 11 by min 140, back to ~7 by min 240
    g[meal:140] = np.linspace(7.0, 11.0, 40)
    g[140:240] = np.linspace(11.0, 7.0, 100)
    w = excursion_window(g, meal, "missed")
    assert w is not None
    s, e = w
    assert meal <= s <= meal + 30          # onset shortly after the meal
    assert 200 <= e <= 245                 # ends as it returns to baseline


def test_no_rise_returns_none():
    """Flat glucose (logged meal, glucose never moved) -> no excursion."""
    g = _trace()
    assert excursion_window(g, 100, "missed") is None


def test_subthreshold_jitter_is_not_onset():
    """Noise below the rise threshold must not trigger a false onset."""
    rng = np.random.default_rng(0)
    g = _trace() + rng.normal(0, 0.3, 600)   # sigma 0.3 << rise 1.1
    assert excursion_window(g, 100, "missed") is None


def test_never_returns_is_capped():
    """A sustained rise that never comes back is capped at cap[cls]."""
    g = _trace()
    meal = 100
    g[meal:] = 12.0                          # steps up and stays high
    s, e = _window(g, meal, "missed")
    assert e == meal + ExcursionCfg().cap["missed"]   # 180


def test_class_cap_differs():
    """large has a longer cap than missed for a never-returning rise."""
    g = _trace(); g[100:] = 12.0
    _, e_missed = _window(g, 100, "missed")
    _, e_large = _window(g, 100, "large")
    assert e_large - e_missed == 300 - 180


def test_premeal_dropout_blocks_baseline():
    """Too few finite pre-meal samples -> cannot establish baseline -> None."""
    g = _trace(); g[100:] = 12.0             # clear rise
    g[70:100] = np.nan                       # but baseline window all-NaN
    assert excursion_window(g, 100, "missed") is None


def test_dropout_inside_rise_breaks_run():
    """An isolated dropout inside the rise breaks the sustain run; a real
    sustained rise after it is still detected."""
    g = _trace()
    g[100:300] = 11.0
    g[105] = np.nan                          # one dropout early
    s, e = _window(g, 100, "missed")
    assert s >= 106                          # onset run starts after the gap


def test_onset_beyond_cap_returns_none():
    """A rise that only starts after the search cap is not found."""
    g = _trace()
    g[100 + 200:] = 12.0                      # rise at +200, cap for missed is 180
    assert excursion_window(g, 100, "missed") is None


def test_meal_out_of_range():
    g = _trace()
    assert excursion_window(g, 700, "missed") is None
    assert excursion_window(g, -1, "missed") is None
