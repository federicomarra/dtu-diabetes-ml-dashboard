"""
Rule + per-patient calibration classifier for behavioural glucose anomalies.

This is the deterministic classification layer of the detect/classify split: the
ML forecaster DETECTS an anomalous window; this module says WHICH behavioural
type it is, using the logged inputs (meals, boluses) - no labels, no training.
It is interpretable, recalibrates per patient, and serves three roles:

  1. deployment classifier  - label a detected anomaly when inputs are present
  2. OhioT1DM label source  - derive missed/late/large ground truth from logs
  3. baseline               - the simple rule the similarity head must beat

Rules (operate on logged meal/bolus events):
  missed : a meal with NO bolus in [meal-bolus_lead, meal+late_max]
  late   : a meal whose nearest bolus is >= late_delay min after the meal
  large  : a meal whose carbs exceed the patient's ROLLING mean + k*std over a
           trailing window - so the threshold tracks patient drift (aging,
           weight change) instead of a fixed cutoff.

`missed`/`late` are mutually exclusive (timing); `large` is orthogonal (size),
so a meal can be both missed and large. Defaults mirror the simulator
(_LATE_BOLUS_DELAY_MIN=30, _BOLUS_LEAD_PRE_MIN=10).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MINUTES_PER_DAY = 1440


@dataclass
class RuleConfig:
    bolus_lead: int = 10          # min a normal bolus precedes the meal
    late_delay: int = 30          # bolus this many min late -> "late"
    late_max: int = 60            # no bolus within this window -> "missed"
    large_k: float = 1.5          # large if carbs > rolling mean + k*std
    large_min_cv: float = 0.1     # floor on std as a fraction of mean (avoids
                                  # over-flagging when meal history is too uniform)
    calib_window_days: int = 7    # trailing window for the rolling meal stats
    min_calib_meals: int = 3      # need this many prior meals to call "large"
    min_carb_g: float = 10.0      # ignore tiny snacks
    # --- detection-anchored labelling (classify_detection) ---
    # A DETECTED glucose excursion is the anchor (not a logged meal), so this works
    # on real data where missed meals leave NO carb log - only a glucose rise. We ask
    # of the excursion's onset: is there a bolus that covers it, and was it on time?
    # Windows fit from the simulator: a timely bolus lands at onset+0, a late bolus at
    # onset+[16,72] (median 43); a missed excursion has no bolus in [onset-15, onset+75]
    # 93% of the time. See ml/tests/test_detection_rule.py for the validation.
    det_lookback: int = 15        # a covering bolus may precede the rise by this much
    det_attribute_max: int = 75   # a bolus later than this belongs to the NEXT meal
    det_late_delay: int = 15      # covering bolus >= this many min after onset -> "late"


def _rolling_large(meal_min: np.ndarray, meal_carb: np.ndarray, cfg: RuleConfig) -> np.ndarray:
    """Bool per meal: carbs exceed the patient's trailing mean + k*std."""
    W = cfg.calib_window_days * MINUTES_PER_DAY
    is_large = np.zeros(len(meal_min), dtype=bool)
    for i, (m, c) in enumerate(zip(meal_min, meal_carb)):
        prior = (meal_min >= m - W) & (meal_min < m)        # trailing meals only
        if prior.sum() < cfg.min_calib_meals:
            continue                                         # not enough to calibrate yet
        hist = meal_carb[prior]
        sd = max(hist.std(), cfg.large_min_cv * hist.mean())   # floor uniform history
        if c > hist.mean() + cfg.large_k * sd:
            is_large[i] = True
    return is_large


def classify_meals(meals, boluses, cfg: RuleConfig = RuleConfig()) -> dict[str, list[int]]:
    """
    Rule-classify each logged meal. `meals` and `boluses` are lists with
    `.minute` and (`.carb_g` for meals, `.units` for boluses).

    Returns {'missed': [...], 'late': [...], 'large': [...]} of meal minutes.
    """
    meals = sorted((m for m in meals if m.carb_g >= cfg.min_carb_g), key=lambda x: x.minute)
    bolus_min = np.array(sorted(b.minute for b in boluses if b.units > 0))
    if not meals:
        return {"missed": [], "late": [], "large": []}

    meal_min = np.array([m.minute for m in meals])
    meal_carb = np.array([m.carb_g for m in meals], dtype=float)
    large = _rolling_large(meal_min, meal_carb, cfg)

    out = {"missed": [], "late": [], "large": []}
    for i, m in enumerate(meal_min):
        if large[i]:
            out["large"].append(int(m))
        if bolus_min.size:
            near = bolus_min[(bolus_min >= m - cfg.bolus_lead) & (bolus_min <= m + cfg.late_max)]
        else:
            near = np.empty(0)
        if near.size == 0:
            out["missed"].append(int(m))
        elif near.min() - m >= cfg.late_delay:
            out["late"].append(int(m))
        # else: timely bolus -> normal (no timing flag)
    return out


def classify_detection(onset_min: int, bolus_minutes, cfg: RuleConfig = RuleConfig()) -> str | None:
    """
    Name a DETECTED glucose excursion by the bolus that should have covered it.

    Unlike classify_meals (which starts from a logged meal), this starts from the
    detector's excursion onset - so it names missed boluses, whose meal is never
    logged (no announced carb, no bolus) and shows up ONLY as a glucose rise. That
    is the real-data case: OhioT1DM etc. give announced carbs + boluses but no
    "actual eaten" signal, so a log-anchored rule is structurally blind to misses.

      missed : no bolus in [onset - det_lookback, onset + det_attribute_max]
      late   : the covering bolus lands >= det_late_delay after onset
      None   : a timely bolus covers it (the excursion has some other cause -
               e.g. a large but correctly-bolused meal) -> not a behavioural flag

    `bolus_minutes` are event onsets in the SAME minute base as `onset_min`.
    """
    b = np.asarray(sorted(int(x) for x in bolus_minutes), dtype=int)
    if b.size:
        near = b[(b >= onset_min - cfg.det_lookback) & (b <= onset_min + cfg.det_attribute_max)]
    else:
        near = np.empty(0, dtype=int)
    if near.size == 0:
        return "missed"
    if int(near.min()) - onset_min >= cfg.det_late_delay:
        return "late"
    return None
