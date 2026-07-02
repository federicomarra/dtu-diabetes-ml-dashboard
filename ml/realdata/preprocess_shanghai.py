"""
Consolidate Shanghai_T1DM per patient-visit xlsx into one tidy CSV per patient
(quick inspection only). NOTE: Shanghai carbs are FREE-TEXT food descriptions
('Dietary intake', e.g. "Steamed bun 100 g") — grams of FOOD, not carbohydrate —
so Shanghai is NOT usable for the cross-channel model / rule labels. This is for
inspection / glucose-level analysis, not for training XCHANNEL.

Output: ml/data/real/shanghai/Preprocessed/{pid}.csv with columns
    time, glucose (mmol/L), bolus (IU, s.c.+CSII), basal_rate (IU/h), dietary_intake (free text)

Run:  .venv/bin/python ml/realdata/preprocess_shanghai.py
"""
import glob
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("ml/data/real/shanghai")
MGDL_PER_MMOL = 18.0182
CGM = "CGM (mg / dl)"; SC = "Insulin dose - s.c."
CSII_B = "CSII - bolus insulin (Novolin R, IU)"; CSII_BASAL = "CSII - basal insulin (Novolin R, IU / H)"
DIET = "Dietary intake"


def _num(d, col):
    s = d[col] if col in d.columns else pd.Series(0.0, index=d.index)
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


def main():
    out_dir = ROOT / "Preprocessed"
    out_dir.mkdir(exist_ok=True)
    files = {}
    for f in sorted(glob.glob(str(ROOT / "*.xls*"))):
        if "Summary" in Path(f).name:
            continue
        files.setdefault(Path(f).name.split("_")[0], []).append(f)
    print(f"{'pid':<14}{'rows':>7}{'days':>6}{'gluμ':>7}{'bolus':>7}{'meals':>7}")
    for pid, fs in files.items():
        d = pd.concat([pd.read_excel(f, engine="calamine") for f in fs], ignore_index=True)
        t = pd.to_datetime(d["Date"], errors="coerce")
        glu = pd.to_numeric(d[CGM], errors="coerce") / MGDL_PER_MMOL
        diet = d[DIET].astype(str) if DIET in d.columns else pd.Series("", index=d.index)
        diet = diet.where(diet.str.strip().ne("") & ~diet.str.contains("nan", case=False), "")
        out = pd.DataFrame({
            "time": t, "glucose": glu.round(2),
            "bolus": (_num(d, SC) + _num(d, CSII_B)).round(3),
            "basal_rate": _num(d, CSII_BASAL).round(4),
            "dietary_intake": diet.str.replace("\n", " ").str.strip(),
        }).sort_values("time")
        f = out_dir / f"{pid}.csv"
        out.to_csv(f, index=False)
        days = (t.max() - t.min()).total_seconds() / 86400 if t.notna().any() else 0
        print(f"{pid:<14}{len(out):>7}{days:>6.0f}{np.nanmean(glu):>7.1f}"
              f"{int((out['bolus'] > 0).sum()):>7}{int((out['dietary_intake'] != '').sum()):>7}")
    print(f"\n{len(files)} patients → {out_dir}  (quick-check only; free-text carbs → NOT cross-channel usable)")


if __name__ == "__main__":
    main()
