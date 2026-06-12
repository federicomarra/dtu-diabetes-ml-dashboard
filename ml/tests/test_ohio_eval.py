"""
Unit tests for the OhioT1DM adapter (ml/ohio_eval/adapter.py) and the synthetic
injection (ml/ohio_eval/eval_xchannel.py).

CPU-only. The adapter test builds a tiny XML on disk; injection tests construct
an OhioPatient directly. Run from repo root:
    .venv/bin/pytest ml/tests/test_ohio_eval.py -v
"""

import numpy as np
import pytest

from dataset import N_CHANNELS, ANOMALY_CLASSES
from ohio_eval.adapter import (
    load_ohio_patient, OhioPatient, Bolus,
    MGDL_PER_MMOL, BOLUS_DURATION, ANNOUNCE_DURATION, MAX_GAP_MIN,
)
from ohio_eval.eval_xchannel import inject, CLASS_IDX

CLS_COL = {c: N_CHANNELS + i for c, i in CLASS_IDX.items()}   # flag column per class


# ── synthetic XML for the parser ────────────────────────────────────────────────

def _xml(glucose_events, boluses=(), basals=(), temp_basals=()):
    def evs(items):
        return "\n".join(items)
    g = evs(f'<event ts="{ts}" value="{v}"/>' for ts, v in glucose_events)
    b = evs(f'<event ts_begin="{ts}" ts_end="{ts}" type="normal" dose="{d}" bwz_carb_input="{c}"/>'
            for ts, d, c in boluses)
    ba = evs(f'<event ts="{ts}" value="{v}"/>' for ts, v in basals)
    tb = evs(f'<event ts_begin="{s}" ts_end="{e}" value="{v}"/>' for s, e, v in temp_basals)
    return f"""<?xml version="1.0"?>
<patient id="999">
  <glucose_level>{g}</glucose_level>
  <basal>{ba}</basal>
  <temp_basal>{tb}</temp_basal>
  <bolus>{b}</bolus>
  <meal></meal>
</patient>"""


@pytest.fixture
def patient_file(tmp_path):
    # 5-min CGM for one hour + a meal bolus at 00:30 + basal 1.0 U/hr
    glu = [(f"01-01-2022 00:{m:02d}:00", 180) for m in range(0, 60, 5)] + [("01-01-2022 01:00:00", 180)]
    boluses = [("01-01-2022 00:30:00", 5.0, 40)]
    basals = [("01-01-2022 00:00:00", 1.0)]
    p = tmp_path / "999-ws-testing.xml"
    p.write_text(_xml(glu, boluses, basals))
    return p


class TestAdapter:

    def test_grid_length_and_glucose_units(self, patient_file):
        p = load_ohio_patient(patient_file)
        assert p.T == 61                                       # 00:00..01:00 inclusive
        np.testing.assert_allclose(p.glucose[0], 180 / MGDL_PER_MMOL, rtol=1e-5)

    def test_bolus_captured_with_carbs(self, patient_file):
        p = load_ohio_patient(patient_file)
        assert len(p.boluses) == 1
        b = p.boluses[0]
        assert b.minute == 30 and b.units == 5.0 and b.carb_g == 40

    def test_render_bolus_spread_and_carb_box(self, patient_file):
        p = load_ohio_patient(patient_file)
        arr = p.render()
        basal = 1.0 * 1000.0 / 60.0                            # mU/min
        # bolus insulin spread over BOLUS_DURATION minutes from minute 30
        bolus_rate = 5.0 * 1000.0 / BOLUS_DURATION
        np.testing.assert_allclose(arr[30, 1], basal + bolus_rate, rtol=1e-4)
        np.testing.assert_allclose(arr[30 + BOLUS_DURATION, 1], basal, rtol=1e-4)
        # announced carb box: 40 g over ANNOUNCE_DURATION minutes
        np.testing.assert_allclose(arr[30, 2], 40 * 1000.0 / ANNOUNCE_DURATION, rtol=1e-4)
        assert arr[30 + ANNOUNCE_DURATION, 2] == 0.0

    def test_basal_is_continuous(self, patient_file):
        p = load_ohio_patient(patient_file)
        assert (p.basal_mU_min > 0).all()

    def test_large_gap_marked_invalid(self, tmp_path):
        # readings at 0 and 5 min, then a 50-min jump (> MAX_GAP_MIN) to 55
        glu = [("01-01-2022 00:00:00", 150), ("01-01-2022 00:05:00", 150),
               ("01-01-2022 00:55:00", 150)]
        f = tmp_path / "1-ws.xml"; f.write_text(_xml(glu))
        p = load_ohio_patient(f)
        assert p.valid[0] and p.valid[5]                       # real samples valid
        assert not p.valid[30]                                 # inside the >30-min gap
        assert not p.valid.all()


# ── injection ───────────────────────────────────────────────────────────────────

def _patient(T=400):
    """OhioPatient with one meal bolus (40g) at minute 100 + one correction (0g)."""
    return OhioPatient(
        pid="t", T=T,
        glucose=np.full(T, 8.0, np.float32),
        valid=np.ones(T, bool),
        basal_mU_min=np.full(T, 16.0, np.float32),
        boluses=[Bolus(minute=100, units=5.0, carb_g=40.0),
                 Bolus(minute=250, units=0.5, carb_g=0.0)],   # correction, not a meal
    )


class TestInjection:

    def test_missed_drops_bolus_and_sets_flag(self):
        p = _patient()
        base = p.render()
        arr = inject(p, "missed", late_delay=30, carb_keep=0.7, min_carb_g=20)
        assert arr[100, CLS_COL["missed"]] == 1.0              # flag at the bolus minute
        assert arr[100, 2] == 0.0                              # announced carb gone
        assert arr[100, 1] < base[100, 1]                      # bolus insulin removed

    def test_late_shifts_bolus_keeps_flag_at_origin(self):
        p = _patient()
        arr = inject(p, "late", late_delay=30, carb_keep=0.7, min_carb_g=20)
        assert arr[100, CLS_COL["late"]] == 1.0                # flag at original minute
        assert arr[100, 2] == 0.0                              # carb gone from origin
        assert arr[130, 2] > 0.0                               # …reappears 30 min later

    def test_large_reduces_carb(self):
        p = _patient()
        base = p.render()
        arr = inject(p, "large", late_delay=30, carb_keep=0.7, min_carb_g=20)
        assert arr[100, CLS_COL["large"]] == 1.0
        np.testing.assert_allclose(arr[100, 2], 0.7 * base[100, 2], rtol=1e-4)

    def test_correction_bolus_not_perturbed(self):
        # the 0-carb correction bolus (minute 250) is below min_carb_g → no flag there
        p = _patient()
        arr = inject(p, "missed", late_delay=30, carb_keep=0.7, min_carb_g=20)
        assert arr[250, CLS_COL["missed"]] == 0.0

    def test_min_carb_threshold_excludes_small_meals(self):
        p = _patient()
        arr = inject(p, "missed", late_delay=30, carb_keep=0.7, min_carb_g=50)  # 40g < 50
        assert arr[:, CLS_COL["missed"]].sum() == 0            # nothing eligible
