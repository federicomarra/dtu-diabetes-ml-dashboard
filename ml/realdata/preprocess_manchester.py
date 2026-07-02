"""
Consolidate Manchester's per-stream CSVs into one tidy file per patient on a 5-min
grid (mirrors HUPA's Preprocessed/ layout) — for quick inspection and a simpler
single-file load. Does NOT delete the raw streams (source of truth).

Output: ml/data/real/manchester/Preprocessed/UoM{ID}.csv with columns
    time, glucose (mmol/L), basal_rate (U/hr), bolus (U, per 5-min), carbs (g, per 5-min)

Run:  .venv/bin/python ml/realdata/preprocess_manchester.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from realdata.manchester_adapter import load_manchester_cohort, ROOT  # noqa: E402

STEP = 5  # minutes


def consolidate(p) -> pd.DataFrame:
    arr = p.render()                                  # [T,8] at 1-min
    idx = np.arange(0, p.T, STEP)
    glucose = arr[idx, 0]
    basal_rate = p.basal_mU_min[idx] / 1000.0 * 60.0  # mU/min → U/hr
    bolus = np.zeros(len(idx)); carbs = np.zeros(len(idx))
    for b in p.boluses:
        bolus[min(len(idx) - 1, b.minute // STEP)] += b.units
    for m in p.meals:
        carbs[min(len(idx) - 1, m.minute // STEP)] += m.carb_g
    t0 = pd.Timestamp("2023-01-01")                   # synthetic origin (relative minutes)
    time = [t0 + pd.Timedelta(minutes=int(i)) for i in idx]
    return pd.DataFrame({"time": time, "glucose": np.round(glucose, 2),
                         "basal_rate": np.round(basal_rate, 4),
                         "bolus": np.round(bolus, 3), "carbs": np.round(carbs, 1)})


def main():
    out_dir = ROOT / "Preprocessed"
    out_dir.mkdir(exist_ok=True)
    cohort = load_manchester_cohort()
    print(f"{'pid':<8}{'days':>6}{'gluμ':>7}{'bolus':>7}{'meals':>7}  → file")
    for p in cohort:
        df = consolidate(p)
        f = out_dir / f"UoM{p.pid}.csv"
        df.to_csv(f, index=False)
        print(f"{p.pid:<8}{p.T/1440:>6.0f}{np.nanmean(p.glucose):>7.1f}"
              f"{len(p.boluses):>7}{len(p.meals):>7}  {f.name}")
    print(f"\n{len(cohort)} patients → {out_dir}  (raw streams kept as source of truth)")


if __name__ == "__main__":
    main()
