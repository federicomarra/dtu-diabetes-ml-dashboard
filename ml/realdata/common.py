"""
Common types + stats for the real-patient datasets (sim->real gap assessment).

Each loader returns a list of `RealPatient` with the glucose series in mmol/L on
its native timestamps plus per-patient insulin/carb event counts. `pool_stats`
aggregates a cohort into the comparison metrics used to quantify how far the
simulator is from each real dataset.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MGDL_PER_MMOL = 18.0182
HYPO = 3.9      # mmol/L
HYPER = 10.0    # mmol/L


@dataclass
class RealPatient:
    pid: str
    t_min: np.ndarray        # minutes since first sample (int, monotonic)
    glu: np.ndarray          # glucose, mmol/L
    n_insulin: int           # insulin events (bolus dose > 0)
    n_carb: int              # carb/meal events (> 0)


def pool_stats(name: str, patients: list[RealPatient]) -> dict:
    """Aggregate cohort-level distribution + sampling + missingness + channel stats."""
    glu = np.concatenate([p.glu for p in patients])
    glu = glu[np.isfinite(glu)]

    dts, rocs, days, gap_hits, gap_tot = [], [], [], 0, 0
    for p in patients:
        if len(p.t_min) < 3:
            continue
        d = np.diff(p.t_min.astype(float))       # len N-1, aligned with diff(glu)
        pos = d[d > 0]
        if pos.size == 0:
            continue
        dts.append(pos)
        days.append((p.t_min[-1] - p.t_min[0]) / 1440.0)
        med = np.median(pos)
        gap_hits += int((d > 1.5 * med).sum()); gap_tot += len(d)
        # rate-of-change on consecutive (non-gap, non-dup) samples, mmol/L per min
        g = p.glu.astype(float)
        ok = (d > 0) & (d <= 1.5 * med) & np.isfinite(g[1:]) & np.isfinite(g[:-1])
        rocs.append(np.abs(np.diff(g))[ok] / d[ok])

    dt_all = np.concatenate(dts) if dts else np.array([np.nan])
    roc_all = np.concatenate(rocs) if rocs else np.array([np.nan])
    tot_days = sum(days) or 1.0
    return {
        "name": name,
        "n_pat": len(patients),
        "days_per_pat": np.mean(days) if days else 0.0,
        "dt_min": float(np.median(dt_all)),
        "gap_pct": 100.0 * gap_hits / max(1, gap_tot),
        "glu_mean": float(glu.mean()),
        "glu_std": float(glu.std()),
        "hypo_pct": 100.0 * (glu < HYPO).mean(),
        "hyper_pct": 100.0 * (glu > HYPER).mean(),
        "roc_std": float(np.nanstd(roc_all)),
        "ins_per_day": sum(p.n_insulin for p in patients) / tot_days,
        "carb_per_day": sum(p.n_carb for p in patients) / tot_days,
    }


HEADER = (f"{'dataset':<12}{'n':>4}{'d/pat':>7}{'dt':>5}{'gap%':>6}"
          f"{'glumu':>6}{'glusigma':>6}{'hypo%':>7}{'hyper%':>7}{'ROCsigma':>7}{'ins/d':>7}{'carb/d':>7}")


def fmt_row(s: dict) -> str:
    return (f"{s['name']:<12}{s['n_pat']:>4}{s['days_per_pat']:>7.1f}{s['dt_min']:>5.0f}"
            f"{s['gap_pct']:>6.1f}{s['glu_mean']:>6.1f}{s['glu_std']:>6.1f}{s['hypo_pct']:>7.1f}"
            f"{s['hyper_pct']:>7.1f}{s['roc_std']:>7.3f}{s['ins_per_day']:>7.1f}{s['carb_per_day']:>7.1f}")
