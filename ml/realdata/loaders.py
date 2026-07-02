"""
Loaders for the four real T1D datasets → list[RealPatient] (glucose in mmol/L).

  ohio       OhioT1DM XML (reuses ml/ohio_eval/adapter)         CGM 5-min, mg/dL
  hupa       HUPA-UCM, one ;-CSV per patient                    CGM 5-min, mg/dL
  manchester UoM Coordinated Diabetes Study, per-stream CSV     CGM 5-min, mmol/L
  shanghai   Shanghai_T1DM, one xlsx/xls per patient-visit      CGM 15-min, mg/dL

Carbs in Shanghai are free-text ('Dietary intake'), so its carb count is a rough
meal tally, not grams — flagged.
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from realdata.common import RealPatient, MGDL_PER_MMOL  # noqa: E402

REAL = Path("ml/data/real")


def _tmin(ts: pd.Series) -> np.ndarray:
    ts = pd.to_datetime(ts)
    return ((ts - ts.iloc[0]).dt.total_seconds() // 60).to_numpy().astype(np.int64)


def load_hupa(root: Path = REAL / "hupa") -> list[RealPatient]:
    out = []
    for f in sorted(glob.glob(str(root / "Preprocessed" / "*.csv"))):
        d = pd.read_csv(f, sep=";")
        out.append(RealPatient(
            pid=Path(f).stem, t_min=_tmin(d["time"]),
            glu=d["glucose"].to_numpy(float) / MGDL_PER_MMOL,
            n_insulin=int((d["bolus_volume_delivered"] > 0).sum()),
            n_carb=int((d["carb_input"] > 0).sum()),
        ))
    return out


def load_manchester(root: Path = REAL / "manchester") -> list[RealPatient]:
    out = []
    for gf in sorted(glob.glob(str(root / "Glucose Data" / "UoMGlucose*.csv"))):
        pid = Path(gf).stem.replace("UoMGlucose", "")
        g = pd.read_csv(gf)                                   # bg_ts (dd/mm/YYYY HH:MM), value mmol/L
        t = pd.to_datetime(g["bg_ts"], dayfirst=True)
        glu = pd.to_numeric(g["value"], errors="coerce").to_numpy(float)
        bf = root / "Insulin Data" / "Bolus Data" / f"UoMBolus{pid}.csv"
        nf = root / "Nutrition Data" / f"UoMNutrition{pid}.csv"
        n_ins = int((pd.read_csv(bf)["bolus_dose"] > 0).sum()) if bf.exists() else 0
        n_carb = int((pd.read_csv(nf)["carbs_g"] > 0).sum()) if nf.exists() else 0
        out.append(RealPatient(pid, _tmin(t), glu, n_ins, n_carb))
    return out


def load_shanghai(root: Path = REAL / "shanghai") -> list[RealPatient]:
    # group visits by patient (filename: <pid>_<visit>_<date>.xls[x])
    files: dict[str, list[str]] = {}
    for f in sorted(glob.glob(str(root / "*.xls*"))):
        if "Summary" in Path(f).name:
            continue                                          # cohort metadata, not a patient
        files.setdefault(Path(f).name.split("_")[0], []).append(f)
    cgm = "CGM (mg / dl)"; sc = "Insulin dose - s.c."; csii = "CSII - bolus insulin (Novolin R, IU)"
    out = []
    for pid, fs in files.items():
        d = pd.concat([pd.read_excel(f, engine="calamine") for f in fs], ignore_index=True)

        def num(col):   # numeric Series of len(d), zeros if column absent
            s = d[col] if col in d.columns else pd.Series(0.0, index=d.index)
            return pd.to_numeric(s, errors="coerce").fillna(0.0)

        ins = num(sc) + num(csii)
        diet = d["Dietary intake"] if "Dietary intake" in d.columns else pd.Series(dtype=object)
        n_carb = int(diet.notna().sum()
                     - diet.astype(str).str.contains("not available", na=False).sum())
        out.append(RealPatient(
            pid, _tmin(d["Date"]), d[cgm].to_numpy(float) / MGDL_PER_MMOL,
            int((ins > 0).sum()), n_carb,
        ))
    return out


def load_ohio() -> list[RealPatient]:
    from ohio_eval.adapter import load_ohio_cohort
    out = []
    for split in ("train", "test"):
        for p in load_ohio_cohort(Path("ml/data/real/ohio"), split=split):
            tmin = np.arange(p.T)[p.valid]                    # 1-min grid; keep valid minutes
            out.append(RealPatient(p.pid + "_" + split, tmin, p.glucose[p.valid],
                                   len(p.boluses), len(p.meals)))
    return out


LOADERS = {"ohio": load_ohio, "hupa": load_hupa,
           "manchester": load_manchester, "shanghai": load_shanghai}
