"""Glucose-derived label placement (eval-side).

Model-INDEPENDENT: a positive window is derived from the raw glucose trace + the
logged meal minute only - never from a forecast residual (that would make labels and
scores circular). Anchors a rule-labelled meal's positive window to the ACTUAL glucose
excursion it caused, instead of a fixed clock window after the logged timestamp.
"""
from dataclasses import dataclass, field

import numpy as np

# per-class search/return caps (min) - reuse the sim-aligned window ends
ALIGNED_CAP = {"missed": 180, "late": 240, "large": 300}


@dataclass
class ExcursionCfg:
    baseline_pre: int = 30        # min before meal to average for baseline
    rise: float = 1.1             # mmol/L above baseline = excursion threshold (~20 mg/dL)
    sustain: int = 10             # consecutive finite min above thr to confirm onset/return
    return_frac: float = 0.5      # end when glucose within return_frac*rise of baseline
    cap: dict = field(default_factory=lambda: dict(ALIGNED_CAP))


def _sustained_run(mask: np.ndarray, need: int) -> int | None:
    """Index of the first element starting a run of `need` consecutive True in `mask`."""
    if mask.size < need:
        return None
    run = 0
    for i, ok in enumerate(mask):
        run = run + 1 if ok else 0
        if run >= need:
            return i - need + 1
    return None


def excursion_window(glucose: np.ndarray, meal_minute: int, cls: str,
                     cfg: ExcursionCfg | None = None) -> tuple[int, int] | None:
    """Return (start, end) minutes bracketing the post-meal glucose excursion, or None
    if no sustained rise is found (the 'no-excursion' case). All indices clamped to the
    series. `glucose` is 1-min mmol/L (may contain NaN dropouts)."""
    cfg = cfg or ExcursionCfg()
    T = glucose.size
    cap = cfg.cap[cls]
    m = int(meal_minute)
    if m < 0 or m >= T:
        return None

    # baseline from the pre-meal window; need >=50% finite samples
    lo = max(0, m - cfg.baseline_pre)
    pre = glucose[lo:m]
    if pre.size == 0 or np.isfinite(pre).mean() < 0.5:
        return None
    baseline = np.nanmean(pre)

    # search region [m, m+cap]
    hi = min(T, m + cap + 1)
    seg = glucose[m:hi]
    if seg.size == 0:
        return None

    # onset: first sustained run >= baseline+rise. Treat NaN as "not above" (False);
    # _sustained_run requires consecutive minutes, so isolated dropouts break a run.
    above = np.where(np.isfinite(seg), seg >= baseline + cfg.rise, False)
    onset_rel = _sustained_run(above, cfg.sustain)
    if onset_rel is None:
        return None
    start = m + onset_rel

    # peak after onset, then end = first sustained return within return_frac*rise
    post = glucose[start:hi]
    peak_rel = int(np.nanargmax(post))
    after_peak = post[peak_rel:]
    near = np.where(np.isfinite(after_peak),
                    after_peak <= baseline + cfg.return_frac * cfg.rise, False)
    ret_rel = _sustained_run(near, cfg.sustain)
    end = (start + peak_rel + ret_rel) if ret_rel is not None else min(T, m + cap)
    end = min(T, max(end, start + 1))
    return start, end
