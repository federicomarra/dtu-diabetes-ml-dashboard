"""
Manchester (UoM Coordinated Diabetes Study) -> sim-format adapter, mirroring the
HUPA/Ohio adapters (same [T,8] encoding, Bolus/Meal, render).

Manchester per-stream CSVs (per patient ID, e.g. 2301):
  Glucose Data/UoMGlucose{ID}.csv        bg_ts (dd/mm/YYYY HH:MM), value [mmol/L]
  Insulin Data/Bolus Data/UoMBolus{ID}.csv   bolus_ts, bolus_dose [U]
  Insulin Data/Basal Data/UoMBasal{ID}.csv   basal_ts, basal_dose [U/hr], insulin_kind
  Nutrition Data/UoMNutrition{ID}.csv    meal_ts, ..., carbs_g [g], macros

Units are already physiological - glucose mmol/L (no conversion), carbs in GRAMS,
bolus U, basal U/hr. ~5-min CGM, ~98-day records, occasional real gaps.

Carbs and boluses are separate streams (like HUPA): the carb INPUT channel is the
ANNOUNCED carb (carb paired to a co-timed bolus, +/-15 min; unbolused -> 0, matching the
sim's cho_mg_announced + Ohio), while `meals` (all carbs) feed the rule labels.
"""
from __future__ import annotations

import glob
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ohio_eval.adapter import Bolus, Meal, MAX_GAP_MIN, BOLUS_DURATION, ANNOUNCE_DURATION, N_COLS

ROOT = Path("ml/data/real/manchester")
ANNOUNCE_PAIR_MIN = 15     # carb<->bolus pairing window for "announced" carbs (min)


@dataclass
class ManchesterPatient:
    pid: str
    T: int
    glucose: np.ndarray          # [T] mmol/L
    valid: np.ndarray            # [T] bool
    basal_mU_min: np.ndarray     # [T] mU/min (basal only)
    boluses: list[Bolus]
    meals: list[Meal]

    def render(self, boluses: list[Bolus] | None = None) -> np.ndarray:
        """[T,8]: insulin = basal + boluses(3-min); carb = announced carb on boluses(20-min)."""
        b = self.boluses if boluses is None else boluses
        arr = np.zeros((self.T, N_COLS), dtype=np.float32)
        arr[:, 0] = self.glucose
        insulin = self.basal_mU_min.astype(np.float64).copy()
        carb = np.zeros(self.T, dtype=np.float64)
        for bo in b:
            if 0 <= bo.minute < self.T:
                e = min(self.T, bo.minute + BOLUS_DURATION)
                insulin[bo.minute:e] += bo.units * 1000.0 / BOLUS_DURATION
                if bo.carb_g > 0:
                    ec = min(self.T, bo.minute + ANNOUNCE_DURATION)
                    carb[bo.minute:ec] += bo.carb_g * 1000.0 / ANNOUNCE_DURATION
        arr[:, 1] = insulin
        arr[:, 2] = carb
        return arr


def _dt(series) -> pd.Series:
    return pd.to_datetime(series.astype(str).str.strip(), dayfirst=True, errors="coerce")


def load_manchester_patient(pid: str, root: Path = ROOT) -> ManchesterPatient:
    g = pd.read_csv(root / "Glucose Data" / f"UoMGlucose{pid}.csv")
    t = _dt(g["bg_ts"]); t0 = t.min()
    gsec = (t - t0).dt.total_seconds().to_numpy(float)
    gval = pd.to_numeric(g["value"], errors="coerce").to_numpy(float)        # mmol/L
    ok = np.isfinite(gval) & np.isfinite(gsec)
    gmin = (gsec[ok] // 60).astype(np.int64); gval = gval[ok]
    order = np.argsort(gmin); gmin, gval = gmin[order], gval[order]
    gmin, uniq = np.unique(gmin, return_index=True); gval = gval[uniq]
    T = int(gmin[-1]) + 1
    glucose = np.interp(np.arange(T), gmin, gval).astype(np.float32)
    valid = np.zeros(T, dtype=bool)
    for a, b in zip(gmin[:-1], gmin[1:]):
        valid[a:b + 1] = (b - a) <= MAX_GAP_MIN
    valid[gmin] = True

    def minute(ts_series):
        return ((_dt(ts_series) - t0).dt.total_seconds() // 60).to_numpy(float)   # NaN for NaT

    # basal U/hr -> mU/min, piecewise-held by timestamp
    basal_mU_min = np.zeros(T, dtype=np.float64)
    bf = root / "Insulin Data" / "Basal Data" / f"UoMBasal{pid}.csv"
    if bf.exists():
        bd = pd.read_csv(bf)
        bm = minute(bd["basal_ts"]); rate = pd.to_numeric(bd["basal_dose"], errors="coerce").to_numpy(float)
        fm = np.isfinite(bm) & np.isfinite(rate)
        bm = bm[fm].astype(np.int64); rate = rate[fm]
        o = np.argsort(bm); bm, rate = bm[o], rate[o]
        for i, m in enumerate(bm):
            s = max(0, int(m)); e = int(bm[i + 1]) if i + 1 < len(bm) else T
            basal_mU_min[s:max(s, min(e, T))] = rate[i] / 60.0 * 1000.0

    # boluses (U) with announced carb paired from nutrition (+/-ANNOUNCE_PAIR_MIN)
    nf = root / "Nutrition Data" / f"UoMNutrition{pid}.csv"
    cmin = np.empty(0, np.int64); cg = np.empty(0, float)
    if nf.exists():
        nd = pd.read_csv(nf)
        cgv = pd.to_numeric(nd["carbs_g"], errors="coerce").to_numpy(float)
        cmin_all = minute(nd["meal_ts"]); m = np.isfinite(cgv) & (cgv > 0) & np.isfinite(cmin_all)
        cmin, cg = cmin_all[m].astype(np.int64), cgv[m]
    bfl = root / "Insulin Data" / "Bolus Data" / f"UoMBolus{pid}.csv"
    boluses = []
    if bfl.exists():
        bo = pd.read_csv(bfl)
        bom = minute(bo["bolus_ts"]); bou = pd.to_numeric(bo["bolus_dose"], errors="coerce").to_numpy(float)
        for i in np.where(np.isfinite(bou) & (bou > 0) & np.isfinite(bom))[0]:
            mb = int(bom[i])
            if not (0 <= mb < T):
                continue
            ann = 0.0
            if cmin.size:
                j = int(np.argmin(np.abs(cmin - mb)))
                if abs(int(cmin[j]) - mb) <= ANNOUNCE_PAIR_MIN:
                    ann = float(cg[j])
            boluses.append(Bolus(minute=mb, units=float(bou[i]), carb_g=ann))
    meals = [Meal(minute=int(cmin[k]), carb_g=float(cg[k])) for k in range(len(cmin)) if 0 <= cmin[k] < T]

    return ManchesterPatient(pid=pid, T=T, glucose=glucose, valid=valid,
                             basal_mU_min=basal_mU_min.astype(np.float32),
                             boluses=boluses, meals=meals)


def load_manchester_cohort(root: Path = ROOT) -> list[ManchesterPatient]:
    """Patients with all of glucose+bolus+basal+nutrition (cross-channel-usable)."""
    out = []
    for gf in sorted(glob.glob(str(root / "Glucose Data" / "UoMGlucose*.csv"))):
        pid = Path(gf).stem.replace("UoMGlucose", "")
        need = [root / "Insulin Data" / "Bolus Data" / f"UoMBolus{pid}.csv",
                root / "Insulin Data" / "Basal Data" / f"UoMBasal{pid}.csv",
                root / "Nutrition Data" / f"UoMNutrition{pid}.csv"]
        if all(p.exists() for p in need):
            out.append(load_manchester_patient(pid, root))
    return out
