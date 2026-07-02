"""
Unit tests for the rule + calibration classifier (ml/characterization/rules.py).

CPU-only, synthetic events. Run from repo root:
    .venv/bin/pytest ml/tests/test_rules.py -v
"""

from dataclasses import dataclass

import pytest

from characterization.rules import classify_meals, RuleConfig, MINUTES_PER_DAY


@dataclass
class M:   # minimal meal/bolus stand-ins (need .minute, .carb_g / .units)
    minute: int
    carb_g: float = 0.0
    units: float = 0.0


CFG = RuleConfig()


class TestTiming:

    def test_timely_bolus_is_normal(self):
        meals = [M(minute=1000, carb_g=40)]
        boluses = [M(minute=995, units=5)]                 # 5 min before → on time
        out = classify_meals(meals, boluses, CFG)
        assert out["missed"] == [] and out["late"] == []

    def test_no_bolus_is_missed(self):
        out = classify_meals([M(1000, carb_g=40)], [], CFG)
        assert out["missed"] == [1000] and out["late"] == []

    def test_far_bolus_is_missed(self):
        # bolus 90 min later is beyond late_max (60) → still missed
        out = classify_meals([M(1000, carb_g=40)], [M(1090, units=5)], CFG)
        assert out["missed"] == [1000]

    def test_delayed_bolus_is_late(self):
        # bolus 40 min after meal → ≥ late_delay (30), ≤ late_max (60) → late
        out = classify_meals([M(1000, carb_g=40)], [M(1040, units=5)], CFG)
        assert out["late"] == [1000] and out["missed"] == []

    def test_zero_dose_bolus_does_not_count(self):
        out = classify_meals([M(1000, carb_g=40)], [M(1000, units=0)], CFG)
        assert out["missed"] == [1000]

    def test_small_snack_ignored(self):
        out = classify_meals([M(1000, carb_g=5)], [], CFG)   # < min_carb_g
        assert out["missed"] == []


class TestLargeCalibration:

    def _history(self, base_carb, n, large_at_end):
        # n prior normal meals one day apart, then one test meal
        meals = [M(minute=i * MINUTES_PER_DAY, carb_g=base_carb) for i in range(n)]
        meals.append(M(minute=n * MINUTES_PER_DAY, carb_g=large_at_end))
        # give each a timely bolus so timing flags stay clear
        boluses = [M(minute=m.minute - 5, units=5) for m in meals]
        return meals, boluses

    def test_large_meal_flagged_against_rolling_mean(self):
        meals, boluses = self._history(base_carb=40, n=6, large_at_end=120)
        out = classify_meals(meals, boluses, CFG)
        assert out["large"] == [6 * MINUTES_PER_DAY]

    def test_normal_size_not_flagged(self):
        meals, boluses = self._history(base_carb=40, n=6, large_at_end=42)
        out = classify_meals(meals, boluses, CFG)
        assert out["large"] == []

    def test_no_large_without_enough_calibration(self):
        # only 2 prior meals (< min_calib_meals) → cannot call large yet
        meals, boluses = self._history(base_carb=40, n=2, large_at_end=200)
        out = classify_meals(meals, boluses, CFG)
        assert out["large"] == []

    def test_large_and_missed_can_cooccur(self):
        meals, _ = self._history(base_carb=40, n=6, large_at_end=120)
        boluses = [M(minute=m.minute - 5, units=5) for m in meals[:-1]]  # no bolus for last
        out = classify_meals(meals, boluses, CFG)
        last = 6 * MINUTES_PER_DAY
        assert last in out["large"] and last in out["missed"]


def test_empty_inputs():
    out = classify_meals([], [], CFG)
    assert out == {"missed": [], "late": [], "large": []}
