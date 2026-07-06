"""Tests for classify_detection - the detection-anchored missed/late-bolus rule.

Two layers:
  1. Unit tests of the rule's decision boundaries on synthetic events.
  2. A validation against the simulator ground truth (demo cohort), skipped when
     the parquet is absent. This is the number that justifies the rule: it names
     missed boluses that leave NO carb log, which classify_meals cannot.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ML = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML))
from characterization.rules import classify_detection, RuleConfig  # noqa: E402

cfg = RuleConfig()


# ── 1. decision boundaries ────────────────────────────────────────────────

def test_no_bolus_is_missed():
    assert classify_detection(1000, [], cfg) == "missed"
    assert classify_detection(1000, [200, 5000], cfg) == "missed"   # far-away boluses


def test_timely_bolus_is_none():
    # bolus at onset -> covered, not a bolus-timing anomaly
    assert classify_detection(1000, [1000], cfg) is None
    assert classify_detection(1000, [995], cfg) is None             # slightly before


def test_delayed_bolus_is_late():
    # bolus det_late_delay (15) min after onset -> late
    assert classify_detection(1000, [1015], cfg) == "late"
    assert classify_detection(1000, [1043], cfg) == "late"


def test_late_boundary_is_exclusive_below():
    # 14 min < det_late_delay(15) -> still timely; 15 -> late
    assert classify_detection(1000, [1014], cfg) is None
    assert classify_detection(1000, [1015], cfg) == "late"


def test_bolus_beyond_attribute_window_is_missed():
    # a bolus later than det_attribute_max(75) belongs to the NEXT meal -> missed
    assert classify_detection(1000, [1076], cfg) == "missed"
    assert classify_detection(1000, [1075], cfg) == "late"          # exactly at the edge


def test_earliest_covering_bolus_wins():
    # a timely bolus present alongside a later one -> covered (None)
    assert classify_detection(1000, [1000, 1050], cfg) is None
    # only the late one present -> late
    assert classify_detection(1000, [1050], cfg) == "late"


def test_bolus_units_gate_via_detect_uses_minutes_only():
    # classify_detection takes minutes; ordering/duplicates must not matter
    assert classify_detection(1000, [1050, 1000, 1000], cfg) is None


# ── 2. simulator ground-truth validation ─────────────────────────────────

PARQUET = ML / "data" / "sim_data" / "demo_cohort_25p_14d.parquet"
BASAL_MAX = 50.0   # mU/min above basal (~13.3) = a bolus spike


def _runs(mask):
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return []
    br = np.where(np.diff(idx) > 1)[0]
    return list(zip([idx[0]] + [idx[i + 1] for i in br],
                    [idx[i] for i in br] + [idx[-1]]))


@pytest.mark.skipif(not PARQUET.exists(), reason="demo cohort parquet not present")
def test_matches_simulator_ground_truth():
    import pandas as pd

    df = pd.read_parquet(PARQUET)
    tp = {"missed": 0, "late": 0}
    fn = {"missed": 0, "late": 0}
    fp = {"missed": 0, "late": 0}
    normal_flagged = 0
    n_normal = 0

    for _, p in df.groupby("patient_id"):
        p = p.sort_values("absolute_minute").reset_index(drop=True)
        status = p.bolus_status.fillna("normal").values
        ann = p.cho_mg_announced.values
        bol = [s for s, _ in _runs(p.insulin_mU_min.values > BASAL_MAX)]

        events = [(s, "missed") for s, _ in _runs(status == "missed")]
        events += [(s, "late") for s, _ in _runs(status == "late")]
        for s, e in _runs(ann > 0):
            if np.all(status[s:e + 1] == "normal"):
                events.append((s, "normal"))
                n_normal += 1

        for onset, truth in events:
            pred = classify_detection(onset, bol, cfg)
            if truth in ("missed", "late"):
                if pred == truth:
                    tp[truth] += 1
                else:
                    fn[truth] += 1
                    if pred in fp:
                        fp[pred] += 1
            else:  # normal meal must NOT be flagged missed/late
                if pred is not None:
                    normal_flagged += 1

    def f1(lbl):
        p = tp[lbl] / (tp[lbl] + fp[lbl]) if tp[lbl] + fp[lbl] else 0.0
        r = tp[lbl] / (tp[lbl] + fn[lbl]) if tp[lbl] + fn[lbl] else 0.0
        return 2 * p * r / (p + r) if p + r else 0.0

    # specificity: normal meals almost never mislabelled as a bolus-timing anomaly
    assert normal_flagged / n_normal < 0.01, f"{normal_flagged}/{n_normal} normal meals flagged"
    assert f1("missed") > 0.90, f"missed f1={f1('missed'):.3f}"
    assert f1("late") > 0.90, f"late f1={f1('late'):.3f}"
