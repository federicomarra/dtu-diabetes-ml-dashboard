"""
Sim→real DISTRIBUTION comparison (per-patient spread, not just pooled scalars).

`gap_assess.py` pools every glucose sample together and reports cohort scalars
(glu mean/std, hypo%, hyper%, …). That conflates *within-patient* variation with
*between-patient* variation. Domain randomisation is about the latter: are the
simulator's virtual patients clustered too tightly compared to the spread of real
patients? If sim's between-patient spread on a metric is much narrower than real,
that metric is a knob to widen so real patients fall inside the training manifold.

This tool computes per-patient metrics, then reports the cross-patient
distribution (median and 10–90th percentile band) for each cohort, plus a SPREAD
RATIO = sim_band_width / real_band_width. Ratio ≪ 1 ⇒ sim too narrow on that axis.

Targets (tune toward): ohio, manchester.  Held-out (never tune to): hupa.

Usage
-----
    python ml/realdata/dist_compare.py
    python ml/realdata/dist_compare.py --sim_patients 200
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import load_patients, make_patient_split  # noqa: E402
from realdata.common import RealPatient, HYPO, HYPER  # noqa: E402
from realdata.loaders import LOADERS  # noqa: E402

SIM_PARQUET = Path("ml/data/sim_data/results_5000p_42d.parquet")
VERY_HYPER = 13.9  # mmol/L (~250 mg/dL), the tail the sim under-produces

# metric key → (label, format)
METRICS = [
    ("glu_mean", "gluμ"),
    ("glu_std", "gluσ"),
    ("cv", "CV%"),
    ("tir_pct", "TIR%"),
    ("hypo_pct", "hypo%"),
    ("hyper_pct", "hyper%"),
    ("vhyper_pct", "v.hyper%"),
    ("roc_std", "ROCσ"),
]


def load_sim(parquet: Path, n_patients: int) -> list[RealPatient]:
    ids = make_patient_split(parquet)["train"][:n_patients]
    out = []
    for pid, arr in load_patients(ids, parquet).items():
        glu, ins, carb = arr[:, 0], arr[:, 1], arr[:, 2]
        carb_edges = int(((carb > 0) & (np.r_[False, carb[:-1] > 0] == False)).sum())
        bolus = ins - median_filter(ins, 61)
        ins_edges = int(((bolus > 200) & (np.r_[False, bolus[:-1] > 200] == False)).sum())
        out.append(RealPatient(pid, np.arange(arr.shape[0]), glu, ins_edges, carb_edges))
    return out


def patient_metrics(p: RealPatient) -> dict | None:
    """Per-patient distribution + volatility metrics; None if too little finite data."""
    g = p.glu.astype(float)
    finite = g[np.isfinite(g)]
    if finite.size < 100:
        return None
    mean = float(finite.mean())
    std = float(finite.std())

    # rate-of-change on consecutive non-gap samples (mmol/L per min)
    roc_std = np.nan
    if len(p.t_min) >= 3:
        d = np.diff(p.t_min.astype(float))
        med = np.median(d[d > 0]) if (d > 0).any() else 1.0
        ok = (d > 0) & (d <= 1.5 * med) & np.isfinite(g[1:]) & np.isfinite(g[:-1])
        if ok.any():
            roc_std = float(np.std(np.abs(np.diff(g))[ok] / d[ok]))

    return {
        "glu_mean": mean,
        "glu_std": std,
        "cv": 100.0 * std / mean if mean else np.nan,
        "tir_pct": 100.0 * ((finite >= HYPO) & (finite <= HYPER)).mean(),
        "hypo_pct": 100.0 * (finite < HYPO).mean(),
        "hyper_pct": 100.0 * (finite > HYPER).mean(),
        "vhyper_pct": 100.0 * (finite > VERY_HYPER).mean(),
        "roc_std": roc_std,
    }


def cohort_table(name: str, patients: list[RealPatient]) -> dict:
    rows = [m for m in (patient_metrics(p) for p in patients) if m is not None]
    out = {"name": name, "n": len(rows)}
    for key, _ in METRICS:
        vals = np.array([r[key] for r in rows], float)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            out[key] = (np.nan, np.nan, np.nan)
            continue
        out[key] = (
            float(np.percentile(vals, 50)),                 # median
            float(np.percentile(vals, 10)),                 # p10
            float(np.percentile(vals, 90)),                 # p90
        )
    return out


def main():
    ap = argparse.ArgumentParser(description="sim→real per-patient distribution comparison")
    ap.add_argument("--parquet", type=Path, default=SIM_PARQUET)
    ap.add_argument("--sim_patients", type=int, default=150)
    ap.add_argument("--datasets", nargs="+", default=["ohio", "manchester", "hupa"])
    args = ap.parse_args()

    print("loading sim…", flush=True)
    tables = [cohort_table("sim", load_sim(args.parquet, args.sim_patients))]
    for name in args.datasets:
        print(f"loading {name}…", flush=True)
        try:
            tables.append(cohort_table(name, LOADERS[name]()))
        except Exception as e:
            print(f"  {name} FAILED: {e}")

    sim = tables[0]
    # one block per metric: median (p10–p90) per cohort + spread ratio vs each real
    for key, label in METRICS:
        print(f"\n== {label} ==  median [p10–p90] across patients")
        sim_med, sim_lo, sim_hi = sim[key]
        sim_w = sim_hi - sim_lo
        for t in tables:
            med, lo, hi = t[key]
            w = hi - lo
            tag = ""
            if t["name"] != "sim" and np.isfinite(w) and w > 0 and np.isfinite(sim_w):
                ratio = sim_w / w
                flag = "  <-- sim TOO NARROW" if ratio < 0.6 else ""
                tag = f"   spread_ratio(sim/{t['name']})={ratio:.2f}{flag}"
            print(f"  {t['name']:<11} n={t['n']:>3}  {med:>7.2f} [{lo:>6.2f}–{hi:>6.2f}]{tag}")

    print("\nspread_ratio = sim p10–p90 width / real p10–p90 width.")
    print("ratio < 0.6 ⇒ sim's between-patient spread is much narrower than real on that axis")
    print("            ⇒ widen that knob (domain randomisation) so real patients fall inside.")
    print("TIR/CV/v.hyper are the variability+tail axes the sim is suspected to under-produce.")


if __name__ == "__main__":
    main()
