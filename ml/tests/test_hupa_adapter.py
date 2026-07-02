import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from hupa_eval.adapter import load_hupa_patient, EXCHANGE_G  # noqa: E402
from ohio_eval.adapter import MGDL_PER_MMOL, ANNOUNCE_DURATION  # noqa: E402


def _write_csv(tmp_path, rows):
    cols = ["time", "glucose", "calories", "heart_rate", "steps",
            "basal_rate", "bolus_volume_delivered", "carb_input"]
    df = pd.DataFrame(rows, columns=cols)
    f = tmp_path / "HUPA9999P.csv"
    df.to_csv(f, sep=";", index=False)
    return f


def _grid(n, glucose=180.0, basal=0.05):
    # n regular 5-min rows, default glucose 180 mg/dL, basal 0.05 U/5min
    t0 = pd.Timestamp("2020-01-01 00:00:00")
    return [[(t0 + pd.Timedelta(minutes=5 * i)).isoformat(), glucose, 0, 80, 0, basal, 0.0, 0.0]
            for i in range(n)]


def test_glucose_mgdl_to_mmol(tmp_path):
    p = load_hupa_patient(_write_csv(tmp_path, _grid(20, glucose=180.0)))
    assert abs(p.glucose[0] - 180.0 / MGDL_PER_MMOL) < 1e-3      # ~9.99 mmol/L
    assert p.valid.all()                                         # regular 5-min grid


def test_announced_carb_semantics_and_render(tmp_path):
    rows = _grid(40)
    rows[5][7] = 4.0;  rows[5][6] = 3.0   # min25: carb 4 servings + bolus → ANNOUNCED meal
    rows[10][7] = 2.0                     # min50: carb 2 servings, NO bolus → unannounced meal
    rows[14][6] = 2.0                     # min70: bolus only → correction (no carb)
    p = load_hupa_patient(_write_csv(tmp_path, rows))
    assert len(p.meals) == 2 and len(p.boluses) == 2          # 2 carb events, 2 bolus events
    # the min25 bolus carries its announced carb (4 servings → 40 g); the min70 bolus none
    bg = {b.minute: b.carb_g for b in p.boluses}
    assert abs(bg[25] - 4.0 * EXCHANGE_G) < 1e-6 and bg[70] == 0.0
    arr = p.render()
    assert arr.shape[1] == 8
    assert arr[25:25 + ANNOUNCE_DURATION, 2].sum() > 0        # announced carb in channel
    assert arr[50, 2] == 0                                    # unbolused carb NOT in channel (matches sim "0 if missed")
    assert arr[70, 2] == 0                                    # correction bolus, no carb
    assert arr[25, 1] > arr[0, 1] and arr[70, 1] > arr[0, 1]  # both boluses spike insulin


def test_basal_daily_total_physiological(tmp_path):
    p = load_hupa_patient(_write_csv(tmp_path, _grid(288, basal=0.056)))   # one day
    daily_U = p.basal_mU_min.sum() / 1000.0                                # mU/min·min → U
    assert 8.0 <= daily_U <= 40.0, f"daily basal {daily_U:.1f} U non-physiological"
