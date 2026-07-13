"""Residual direction gates the `missed` label (not the detector).

Sim ground truth: P(glucose above forecast | missed) = 82.8%, vs 49.7% for normal
windows. So a below-forecast excursion with no covering bolus is NOT a missed bolus -
it is exercise, over-basal, a stacked correction, a compression low.

`late` is deliberately NOT gated: P(above | late) = 55.0%, a coin flip, because the
late bolus lands and drives glucose back under the forecast. Gating late costs AUPRC
(sim: 0.0955 -> 0.0810; AUROC 0.776 -> 0.605). Gating missed gains it (0.1843 -> 0.2165).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from characterization.rules import classify_detection, RuleConfig  # noqa: E402

CFG = RuleConfig()


def test_missed_requires_glucose_above_forecast():
    """No bolus + glucose ABOVE forecast -> missed."""
    assert classify_detection(1000, [], CFG, direction=+1.5) == "missed"


def test_below_forecast_with_no_bolus_is_not_a_missed_bolus():
    """The bug: 52% of surfaced `missed` events on the real patient ran BELOW forecast."""
    assert classify_detection(1000, [], CFG, direction=-1.5) is None


def test_direction_omitted_keeps_the_old_behaviour():
    """Callers without a forecast residual (rule-only paths, tests) must not change."""
    assert classify_detection(1000, [], CFG) == "missed"
    assert classify_detection(1000, [], CFG, direction=None) == "missed"


def test_late_is_not_gated_on_direction():
    """A late bolus drives glucose back under the forecast -> direction carries no signal."""
    bolus = [1000 + CFG.det_late_delay + 5]
    assert classify_detection(1000, bolus, CFG, direction=+1.0) == "late"
    assert classify_detection(1000, bolus, CFG, direction=-1.0) == "late"


def test_timely_bolus_still_wins_over_direction():
    """A covering, on-time bolus means no timing anomaly, whatever the residual did."""
    assert classify_detection(1000, [1000], CFG, direction=+5.0) is None
    assert classify_detection(1000, [1000], CFG, direction=-5.0) is None


@pytest.mark.parametrize("direction", [0.0, 1e-9])
def test_zero_residual_counts_as_above(direction):
    """Boundary: `direction >= 0` is the above-forecast branch, matching the sim measurement."""
    assert classify_detection(1000, [], CFG, direction=direction) == "missed"
