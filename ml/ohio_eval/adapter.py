"""
OhioT1DM → sim-format adapter (faithful to the simulator's input encoding).

Produces the same per-patient [T, 8] float32 array the simulator pipeline uses:

    col 0  blood_glucose      mmol/L   (Ohio mg/dL ÷ 18.0182)
    col 1  insulin_mU_min     mU/min   basal + boluses
    col 2  cho_mg_announced   mg/min   announced carbs (from the bolus)
    col 3..7  anomaly flags    all ZERO — Ohio has no labels; injection
                               (eval_xchannel.py) sets them synthetically.

Faithful to the generator (`dtu-mt-patient-generator/src/input.py`):
  * bolus insulin spread over BOLUS_DURATION = 3 min  (dose·1000/3 mU/min)
  * announced carb = bolus_carbs·1000/ANNOUNCE_DURATION mg/min, spread over the
    eating window starting at the bolus minute (sim: meal.duration from
    bolus_start). 0 when a bolus has no carb input → matches "0 if missed".
    Ohio carries the announced carbs on the bolus itself (`bwz_carb_input`), so
    the carb channel is built from BOLUSES, not meal events. ANNOUNCE_DURATION
    is a fixed approximation (sim varies 5–25 min by meal slot; Ohio has no
    eating-duration field).
  * basal = value·1000/60 mU/min, piecewise, temp_basal overrides.

Real-data facts the simulator lacks:
  * 5-min CGM with gaps → 1-min grid by linear interp; minutes inside a gap
    longer than MAX_GAP_MIN are marked INVALID (windower drops those windows).

The series are rendered from a (basal, bolus-list) decomposition so injection
can drop/shift/shrink a bolus and re-render exactly.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from dataset import N_CHANNELS, ANOMALY_CLASSES   # 3 signals, 5 flag classes

TS_FMT = "%d-%m-%Y %H:%M:%S"
MGDL_PER_MMOL = 18.0182
MAX_GAP_MIN = 30
N_COLS = N_CHANNELS + len(ANOMALY_CLASSES)       # 8

BOLUS_DURATION = 3        # min — bolus insulin spread (sim: BOLUS_DURATION)
ANNOUNCE_DURATION = 20    # min — announced-carb spread (sim: per-meal eating duration)


@dataclass
class Bolus:
    minute: int
    units: float          # U
    carb_g: float         # announced carbs (bwz_carb_input), grams


@dataclass
class Meal:
    minute: int
    carb_g: float         # carbs actually eaten (logged), grams


@dataclass
class OhioPatient:
    pid: str
    T: int
    glucose: np.ndarray          # [T] mmol/L
    valid: np.ndarray            # [T] bool
    basal_mU_min: np.ndarray     # [T] mU/min (basal only)
    boluses: list[Bolus]
    meals: list[Meal]            # logged meals (independent of boluses) — for rule labels

    def render(self, boluses: list[Bolus] | None = None) -> np.ndarray:
        """Build the [T, 8] array (flags zero) from basal + a bolus list."""
        b = self.boluses if boluses is None else boluses
        arr = np.zeros((self.T, N_COLS), dtype=np.float32)
        arr[:, 0] = self.glucose
        insulin = self.basal_mU_min.astype(np.float64).copy()
        carb = np.zeros(self.T, dtype=np.float64)
        for bo in b:
            m = bo.minute
            i_end = min(self.T, m + BOLUS_DURATION)
            if m < self.T:
                insulin[m:i_end] += bo.units * 1000.0 / BOLUS_DURATION       # mU/min
            if bo.carb_g > 0:
                c_end = min(self.T, m + ANNOUNCE_DURATION)
                if m < self.T:
                    carb[m:c_end] += bo.carb_g * 1000.0 / ANNOUNCE_DURATION  # mg/min
        arr[:, 1] = insulin
        arr[:, 2] = carb
        return arr


def _ts(s: str) -> datetime:
    return datetime.strptime(s, TS_FMT)


def _events(root: ET.Element, tag: str) -> list[ET.Element]:
    node = root.find(tag)
    return list(node) if node is not None else []


def load_ohio_patient(path: Path) -> OhioPatient:
    root = ET.parse(path).getroot()
    pid = root.get("id", path.stem.split("-")[0])

    glu = _events(root, "glucose_level")
    if not glu:
        raise ValueError(f"{path}: no glucose_level events")

    times = [_ts(e.get("ts")) for e in glu]
    t0, t1 = min(times), max(times)
    T = int((t1 - t0).total_seconds() // 60) + 1

    def minute(dt: datetime) -> int:
        return int((dt - t0).total_seconds() // 60)

    # ── glucose: real readings → interp grid + validity ──────────────────────
    g_min = np.array([minute(t) for t in times])
    g_val = np.array([float(e.get("value")) / MGDL_PER_MMOL for e in glu], dtype=np.float64)
    order = np.argsort(g_min)
    g_min, g_val = g_min[order], g_val[order]
    g_min, uniq = np.unique(g_min, return_index=True)
    g_val = g_val[uniq]
    glucose = np.interp(np.arange(T), g_min, g_val).astype(np.float32)

    valid = np.zeros(T, dtype=bool)
    for a, b in zip(g_min[:-1], g_min[1:]):
        valid[a : b + 1] = (b - a) <= MAX_GAP_MIN
    valid[g_min] = True

    # ── basal (U/hr) piecewise + temp_basal override → mU/min ────────────────
    basal_rate = np.zeros(T, dtype=np.float64)
    basal = sorted(((_ts(e.get("ts")), float(e.get("value"))) for e in _events(root, "basal")),
                   key=lambda x: x[0])
    for i, (ts, val) in enumerate(basal):
        s = max(0, minute(ts))
        e = minute(basal[i + 1][0]) if i + 1 < len(basal) else T
        basal_rate[s : max(s, min(e, T))] = val
    for ev in _events(root, "temp_basal"):
        s, e = max(0, minute(_ts(ev.get("ts_begin")))), min(T, minute(_ts(ev.get("ts_end"))) + 1)
        if s < e:
            basal_rate[s:e] = float(ev.get("value"))
    basal_mU_min = (basal_rate / 60.0 * 1000.0).astype(np.float32)

    # ── boluses (units + announced carbs) ────────────────────────────────────
    boluses: list[Bolus] = []
    for ev in _events(root, "bolus"):
        m = minute(_ts(ev.get("ts_begin")))
        if 0 <= m < T:
            carb_g = float(ev.get("bwz_carb_input") or 0.0)
            boluses.append(Bolus(minute=m, units=float(ev.get("dose")), carb_g=carb_g))

    # ── meals (logged carbs, independent of boluses) ─────────────────────────
    meals: list[Meal] = []
    for ev in _events(root, "meal"):
        m = minute(_ts(ev.get("ts")))
        if 0 <= m < T:
            meals.append(Meal(minute=m, carb_g=float(ev.get("carbs"))))

    return OhioPatient(pid=pid, T=T, glucose=glucose, valid=valid,
                       basal_mU_min=basal_mU_min, boluses=boluses, meals=meals)


def load_ohio_cohort(root_dir: Path, year: str = "both", split: str = "test") -> list[OhioPatient]:
    """All patients for a year ('2018'|'2020'|'both') and split ('test'|'train')."""
    years = ["2018", "2020"] if year == "both" else [year]
    out: list[OhioPatient] = []
    for y in years:
        for xml in sorted((root_dir / y / split).glob("*.xml")):
            out.append(load_ohio_patient(xml))
    return out
