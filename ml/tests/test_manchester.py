import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from realdata.manchester_adapter import load_manchester_patient, load_manchester_cohort, ROOT  # noqa: E402

_HAVE = (ROOT / "Glucose Data").exists()
pytestmark = pytest.mark.skipif(not _HAVE, reason="Manchester data not present")


def test_manchester_patient_units_and_render():
    p = load_manchester_patient("2301")
    arr = p.render()
    assert arr.shape[1] == 8 and arr.shape[0] == p.T          # [T,8]
    assert (arr[:, N_idx:] == 0).all() if (N_idx := 3) else True   # flags zero
    assert 4.0 < float(np.nanmean(p.glucose)) < 20.0          # mmol/L physiological
    daily_basal = p.basal_mU_min.sum() / 1000.0 / (p.T / 1440.0)
    assert 5.0 <= daily_basal <= 80.0                          # U/day physiological
    assert len(p.meals) > 0 and len(p.boluses) > 0
    # carb channel only where a bolus carried an announced carb (<= bolus minutes)
    assert (arr[:, 1] > p.basal_mU_min + 1e-6).any()           # boluses spike insulin


def test_manchester_icr_physiological():
    coh = load_manchester_cohort()
    assert len(coh) >= 10
    icrs = []
    for p in coh:
        bmin = np.array([b.minute for b in p.boluses]); bun = np.array([b.units for b in p.boluses])
        for me in p.meals:
            near = np.where((bmin >= me.minute - 5) & (bmin <= me.minute + 60) & (bun > 0))[0]
            if near.size:
                icrs.append(me.carb_g / bun[near[np.argmin(np.abs(bmin[near] - me.minute))]])
    assert 6.0 <= float(np.median(icrs)) <= 18.0               # g/U - confirms carbs=grams, bolus=U
