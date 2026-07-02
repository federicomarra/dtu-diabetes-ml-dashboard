"""
HUPA-UCM → sim-format adapter, mirroring `ohio_eval.adapter` (same [T,8] encoding,
same Bolus/Meal dataclasses, same render()), so `eval_proxy` runs on HUPA via a
loader swap. See ml/docs/HUPA_ADAPTER.md.

HUPA differences from Ohio:
  * regular 5-min grid (preprocessed, ~no gaps) → interp to 1-min like Ohio.
  * glucose in mg/dL → mmol/L.
  * basal_rate is units-delivered-per-5-min-step (median 0.056 → ~16 U/day) → mU/min.
  * carbs and boluses are SEPARATE columns (not Ohio's bolus-carried announced carb),
    so the carb channel is built from `carb_input`, and meals (for rule labels) =
    carb_input>0 rows, boluses = bolus_volume_delivered>0 rows.
  * `carb_input` is SERVINGS, not grams (HUPA-UCM docs: 1 serving = 10 g; data
    confirms — median 3.5 servings ≈ 35 g, ICR ~9 g/U). carb_g = carb_input *
    EXCHANGE_G (10). load_hupa_cohort asserts median ICR ∈ [7,15] as a guard.
"""
from __future__ import annotations

import glob
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from dataset import N_CHANNELS, ANOMALY_CLASSES
from ohio_eval.adapter import (
    Bolus, Meal, MGDL_PER_MMOL, MAX_GAP_MIN, BOLUS_DURATION, ANNOUNCE_DURATION, N_COLS,
)

HUPA_ROOT = Path("ml/data/real/hupa/Preprocessed")
EXCHANGE_G = 10.0          # carb_input is SERVINGS; HUPA-UCM docs: 1 serving = 10 g
BASAL_STEP_MIN = 5         # basal_rate is units delivered per 5-min sample
ANNOUNCE_PAIR_MIN = 15     # carb↔bolus pairing window for "announced" carbs (min)


@dataclass
class HupaPatient:
    pid: str
    T: int
    glucose: np.ndarray          # [T] mmol/L
    valid: np.ndarray            # [T] bool
    basal_mU_min: np.ndarray     # [T] mU/min (basal only)
    boluses: list[Bolus]
    meals: list[Meal]            # carb_input>0 (grams, after exchange conversion)

    def render(self, boluses: list[Bolus] | None = None) -> np.ndarray:
        """[T,8] (flags zero): insulin = basal + boluses(3-min); carb = ANNOUNCED
        carbs carried on the boluses (20-min), matching the sim's cho_mg_announced
        and the Ohio adapter — unbolused carbs (missed/rescue/snack) are 0 here."""
        b = self.boluses if boluses is None else boluses
        arr = np.zeros((self.T, N_COLS), dtype=np.float32)
        arr[:, 0] = self.glucose
        insulin = self.basal_mU_min.astype(np.float64).copy()
        carb = np.zeros(self.T, dtype=np.float64)
        for bo in b:
            if 0 <= bo.minute < self.T:
                e = min(self.T, bo.minute + BOLUS_DURATION)
                insulin[bo.minute:e] += bo.units * 1000.0 / BOLUS_DURATION       # mU/min
                if bo.carb_g > 0:
                    ec = min(self.T, bo.minute + ANNOUNCE_DURATION)
                    carb[bo.minute:ec] += bo.carb_g * 1000.0 / ANNOUNCE_DURATION  # mg/min
        arr[:, 1] = insulin
        arr[:, 2] = carb
        return arr


def load_hupa_patient(csv: Path, exchange_g: float = EXCHANGE_G) -> HupaPatient:
    d = pd.read_csv(csv, sep=";")
    t = pd.to_datetime(d["time"])
    tmin = ((t - t.iloc[0]).dt.total_seconds() // 60).to_numpy().astype(np.int64)
    T = int(tmin[-1]) + 1

    def num(col):
        return pd.to_numeric(d[col], errors="coerce").to_numpy(dtype=np.float64)

    # ── glucose: mg/dL → mmol/L, 5-min readings → 1-min interp + validity ─────────
    g_min, uniq = np.unique(tmin, return_index=True)
    g_val = (num("glucose")[uniq]) / MGDL_PER_MMOL
    glucose = np.interp(np.arange(T), g_min, g_val).astype(np.float32)
    valid = np.zeros(T, dtype=bool)
    for a, b in zip(g_min[:-1], g_min[1:]):
        valid[a:b + 1] = (b - a) <= MAX_GAP_MIN
    valid[g_min] = True

    # ── basal: units per 5-min step → mU/min (held at each sample) ────────────────
    basal = num("basal_rate")
    basal_mU_min = np.zeros(T, dtype=np.float64)
    for i, m in enumerate(tmin):
        e = int(tmin[i + 1]) if i + 1 < len(tmin) else T
        basal_mU_min[m:max(m, min(e, T))] = basal[i] * 1000.0 / BASAL_STEP_MIN

    # ── boluses (units, with co-timed ANNOUNCED carb) and meals (all carbs) ───────
    # Announced carb = the carb_input paired to a bolus within ±ANNOUNCE_PAIR_MIN
    # (the sim announces carbs AT bolus time; unbolused carbs → 0 in the channel,
    # but still kept as `meals` so a meal-with-no-bolus becomes a 'missed' label).
    bol = num("bolus_volume_delivered"); carb = num("carb_input")
    carb_idx = np.where(carb > 0)[0]
    carb_min = tmin[carb_idx]; carb_g_all = carb[carb_idx] * exchange_g
    boluses = []
    for i in np.where(bol > 0)[0]:
        mb = int(tmin[i])
        if not (0 <= mb < T):
            continue
        ann = 0.0
        if carb_min.size:
            j = int(np.argmin(np.abs(carb_min - mb)))
            if abs(int(carb_min[j]) - mb) <= ANNOUNCE_PAIR_MIN:
                ann = float(carb_g_all[j])
        boluses.append(Bolus(minute=mb, units=float(bol[i]), carb_g=ann))
    meals = [Meal(minute=int(carb_min[k]), carb_g=float(carb_g_all[k]))
             for k in range(len(carb_idx)) if 0 <= carb_min[k] < T]

    return HupaPatient(pid=csv.stem, T=T, glucose=glucose, valid=valid,
                       basal_mU_min=basal_mU_min.astype(np.float32),
                       boluses=boluses, meals=meals)


def load_hupa_cohort(root: Path = HUPA_ROOT, exchange_g: float = EXCHANGE_G) -> list[HupaPatient]:
    cohort = [load_hupa_patient(Path(f), exchange_g)
              for f in sorted(glob.glob(str(root / "*.csv")))]
    # sanity: inferred carb units should give a physiological median ICR (g/U)
    icrs = []
    for p in cohort:
        bmin = np.array([b.minute for b in p.boluses]); bun = np.array([b.units for b in p.boluses])
        for me in p.meals:
            near = np.where((bmin >= me.minute - 5) & (bmin <= me.minute + 60) & (bun > 0))[0]
            if near.size:
                icrs.append(me.carb_g / bun[near[np.argmin(np.abs(bmin[near] - me.minute))]])
    if icrs:
        med = float(np.median(icrs))
        assert 7.0 <= med <= 15.0, f"HUPA median ICR {med:.1f} g/U non-physiological — check EXCHANGE_G/units"
    return cohort
