"""
Sim->real gap assessment: quantify how far the simulator is from each real
dataset on the axes that drive the model's behaviour - glucose distribution,
sampling, missingness, volatility (rate-of-change), and channel density.

Zero training; pure analysis on the existing parquet + the four real datasets.

Usage
-----
    python ml/realdata/gap_assess.py
    python ml/realdata/gap_assess.py --datasets hupa manchester   # subset
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from realdata.common import pool_stats, HEADER, fmt_row  # noqa: E402
from realdata.loaders import LOADERS, load_sim  # noqa: E402

SIM_PARQUET = Path("ml/data/sim_data/results_5000p_42d.parquet")


def main():
    ap = argparse.ArgumentParser(description="sim->real gap assessment")
    ap.add_argument("--parquet", type=Path, default=SIM_PARQUET)
    ap.add_argument("--sim_patients", type=int, default=150)
    ap.add_argument("--datasets", nargs="+", default=["ohio", "hupa", "manchester", "shanghai"])
    args = ap.parse_args()

    rows = []
    print("loading sim...", flush=True)
    rows.append(pool_stats("sim", load_sim(args.parquet, args.sim_patients)))
    for name in args.datasets:
        print(f"loading {name}...", flush=True)
        try:
            rows.append(pool_stats(name, LOADERS[name]()))
        except Exception as e:
            print(f"  {name} FAILED: {e}")

    print("\n" + HEADER)
    print("-" * len(HEADER))
    for r in rows:
        print(fmt_row(r))
    print("\ndt=median sampling (min); gap%=samples with a >1.5xdt gap; ROCsigma=|deltaglu|/min std (mmol/L/min);"
          "\nins/d,carb/d=events per patient-day. Shanghai carb/d is a free-text meal tally.")


if __name__ == "__main__":
    main()
