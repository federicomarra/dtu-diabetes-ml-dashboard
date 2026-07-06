"""
Day 1-2 diagnostic: plot 3 random patients from the 20k Parquet.

Checks:
  - glucose events are visible and labels align with them
  - exercise is stochastic (not every day)
  - sensor noise (lag + AR(1)) is visible as small fluctuations

Usage:
  python ml/explore_patients.py                     # 3 random patients, first 3 days
  python ml/explore_patients.py --days 5            # show 5 days
  python ml/explore_patients.py --ids 000042 001337 # specific patients

NOTE on orange->red (late->missed) transitions on the same patient-day:
  The simulator allows 1 late bolus + 1 missed bolus on *different* meal slots
  within the same day. The constraint is "2 late boluses -> no missed bolus that day",
  not "any late bolus -> no missed bolus". So adjacent orange+red bands are two
  separate meal events and are valid simulator behaviour.
"""

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

PARQUET = Path("ml/data/sim_data/results_500p_14d_clean.parquet")

# Set to True once the new cohort with ac_counts is generated (Days 6-7 HPC re-run).
# When True: each patient gets a 4th panel showing the accelerometer signal.
SHOW_AC = False

N_PANELS = 4 if SHOW_AC else 3   # glucose / insulin / cho [/ ac]
SPACER_HEIGHT = 1.0               # height ratio for blank row between patient groups
PANEL_HEIGHTS = [3, 2, 2, 2]     # glucose taller; ac same height as insulin/cho

# -- label colour scheme --------------------------------------------------------
LABEL_COLORS = {
    "missed":    ("#d62728", 0.30),
    "late":      ("#ff7f0e", 0.40),
    "large":     ("#9467bd", 0.40),
    "aerobic":   ("#2ca02c", 0.30),
    "prolonged": ("#17becf", 0.50),
    "anaerobic": ("#e377c2", 0.60),
}

_meal_keys = ["missed", "late", "large"]
_ex_keys   = ["aerobic", "prolonged", "anaerobic"]

# ncol=3: row 1 = meal anomalies, row 2 = exercise - 2 rows, half the height of ncol=2.
LEGEND_PATCHES = [
    mpatches.Patch(color=LABEL_COLORS[k][0], alpha=LABEL_COLORS[k][1], label=k)
    for k in _meal_keys + _ex_keys
]


def load_patients(patient_ids: list[str]) -> pd.DataFrame:
    """Read only the requested patient_ids from the Parquet."""
    cols = [
        "patient_id", "day", "minute", "absolute_minute",
        "blood_glucose", "insulin_mU_min", "cho_mg_min",
        "bolus_status", "meal_size", "exercise_type",
        "base_scenario",
    ]
    if SHOW_AC and "ac_counts" in pq.read_schema(PARQUET).names:
        cols.append("ac_counts")

    table = pq.read_table(
        PARQUET,
        filters=[("patient_id", "in", patient_ids)],
        columns=cols,
    )
    return table.to_pandas()


def sample_patient_ids(n: int = 3, seed: int = 0) -> list[str]:
    """Pick n patient IDs spread across the file."""
    pf = pq.ParquetFile(PARQUET)
    n_groups = pf.metadata.num_row_groups
    step = max(1, n_groups // (n * 4))
    candidates: set[str] = set()
    for i in range(0, n_groups, step):
        batch = pf.read_row_group(i, columns=["patient_id"])
        candidates.update(batch.column("patient_id").to_pylist())
        if len(candidates) >= n * 10:
            break
    rng = np.random.default_rng(seed)
    chosen = rng.choice(sorted(candidates), size=n, replace=False)
    return list(chosen)


def shade_events(ax, minutes: pd.Series, series: pd.Series, color: str, alpha: float,
                 ymin: float = 0.0, ymax: float = 1.0):
    """
    Shade ax for contiguous runs where series holds an anomaly label.
    ymin/ymax are in axes-normalised coordinates (0=bottom, 1=top).
    Use ymax<1 to confine shading to a strip (e.g. exercise at bottom).
    """
    mins = minutes.values
    active = (series.notna() & (series != "none") & (series != "normal")).values
    runs_start, runs_end = [], []
    in_run = False
    for i, (m, flag) in enumerate(zip(mins, active)):
        if flag and not in_run:
            runs_start.append(m)
            in_run = True
        elif not flag and in_run:
            runs_end.append(mins[i - 1])
            in_run = False
    if in_run:
        runs_end.append(mins[-1])
    for s, e in zip(runs_start, runs_end):
        ax.axvspan(s, e, ymin=ymin, ymax=ymax, color=color, alpha=alpha, linewidth=0)


def plot_patient(axes, df: pd.DataFrame, days: int, show_xaxis: bool = False):
    """
    Fill a column of N_PANELS axes for one patient.
    axes order: [ax_glucose, ax_insulin, ax_cho]  (+ ax_ac when SHOW_AC=True)
    show_xaxis: if True, render day tick labels on the bottom panel.
    """
    ax_g, ax_u, ax_d = axes[0], axes[1], axes[2]

    df = df[df["day"] < days].sort_values("absolute_minute").copy()
    for col in ["bolus_status", "meal_size", "exercise_type"]:
        df[col] = df[col].fillna("none")

    t = df["absolute_minute"]
    pid = df["patient_id"].iloc[0]
    sc = int(df["base_scenario"].iloc[0])
    sc_name = {1: "normal", 2: "active", 3: "sedentary"}.get(sc, "?")

    x_min, x_max = t.iloc[0], t.iloc[-1]
    day_ticks = np.arange(0, days + 1) * 1440

    # -- glucose ----------------------------------------------------------------
    ax_g.plot(t, df["blood_glucose"].values, lw=0.8, color="#1f77b4", zorder=3)
    ax_g.axhline(3.9,  color="red",    lw=0.7, ls="--", alpha=0.5, zorder=2)
    ax_g.axhline(10.0, color="orange", lw=0.7, ls="--", alpha=0.5, zorder=2)

    # Draw order: bolus/meal first, exercise on top.
    shade_events(ax_g, t, df["meal_size"].where(df["meal_size"] == "large"),
                 *LABEL_COLORS["large"])
    shade_events(ax_g, t, df["bolus_status"].where(df["bolus_status"] == "late"),
                 *LABEL_COLORS["late"])
    shade_events(ax_g, t, df["bolus_status"].where(df["bolus_status"] == "missed"),
                 *LABEL_COLORS["missed"])
    for ex_type in ("aerobic", "prolonged", "anaerobic"):
        shade_events(ax_g, t, df["exercise_type"].where(df["exercise_type"] == ex_type),
                     *LABEL_COLORS[ex_type])

    ax_g.set_ylabel("Glucose\n(mmol/L)", fontsize=8)
    ax_g.set_ylim(1.5, 20)
    ax_g.set_title(f"Patient {pid}  |  base scenario: {sc_name}", fontsize=9, fontweight="bold",
                   pad=4)

    # -- insulin ----------------------------------------------------------------
    ax_u.plot(t, df["insulin_mU_min"].values, lw=0.7, color="#d62728")
    ax_u.set_ylabel("Insulin\n(mU/min)", fontsize=8)
    ax_u.set_ylim(bottom=0)

    # -- carbs ------------------------------------------------------------------
    ax_d.fill_between(t, df["cho_mg_min"].values, alpha=0.6, color="#8c564b", lw=0)
    ax_d.set_ylabel("Carbs\n(mg/min)", fontsize=8)
    ax_d.set_ylim(bottom=0)

    # -- AC panel ---------------------------------------------------------------
    # Uncomment the block below (and set SHOW_AC = True at the top) once the
    # new HPC cohort with ac_counts is available (Days 6-7).
    #
    # ax_ac = axes[3]
    # ax_ac.fill_between(t, df["ac_counts"].values, alpha=0.7, color="#2ca02c", lw=0)
    # ax_ac.set_ylabel("AC counts\n(steps/min)", fontsize=8)
    # ax_ac.set_ylim(bottom=0)
    # # Shade exercise windows on AC panel too (same as glucose)
    # for ex_type in ("aerobic", "prolonged", "anaerobic"):
    #     shade_events(ax_ac, t, df["exercise_type"].where(df["exercise_type"] == ex_type),
    #                  *LABEL_COLORS[ex_type])

    # -- shared x-axis formatting -----------------------------------------------
    bottom_ax = axes[N_PANELS - 1]
    for ax in axes:
        ax.set_xticks(day_ticks)
        ax.set_xlim(x_min, x_max)
        ax.tick_params(axis="y", labelsize=7)
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        # Day grid lines on all panels (subtle)
        for tick in day_ticks:
            ax.axvline(tick, color="gray", lw=0.4, alpha=0.4, zorder=1)

    # x tick labels only on the bottom panel of the last patient
    for ax in axes:
        ax.tick_params(labelbottom=False)
    if show_xaxis:
        bottom_ax.set_xticklabels(
            [f"Day {d}" for d in range(days + 1)], fontsize=8
        )
        bottom_ax.tick_params(labelbottom=True)


def build_gridspec(fig, n_patients: int) -> list[list[plt.Axes]]:  # type: ignore[type-arg]
    """
    Build a GridSpec with spacer rows between patient groups.
    Returns list of axes groups: [[ax_g, ax_u, ax_d], ...] per patient.
    """
    panel_h = PANEL_HEIGHTS[:N_PANELS]

    # height_ratios: patient panels interleaved with spacer rows
    heights = []
    for i in range(n_patients):
        heights.extend(panel_h)
        if i < n_patients - 1:
            heights.append(SPACER_HEIGHT)

    gs = gridspec.GridSpec(len(heights), 1, figure=fig,
                           height_ratios=heights, hspace=0.06)

    axes_groups = []
    row = 0
    for i in range(n_patients):
        group = []
        first_ax = None
        for _ in range(N_PANELS):
            if first_ax is None:
                ax = fig.add_subplot(gs[row])
                first_ax = ax
            else:
                ax = fig.add_subplot(gs[row], sharex=first_ax)
            group.append(ax)
            row += 1
        axes_groups.append(group)
        if i < n_patients - 1:
            row += 1  # skip spacer row (no axis created there)

    return axes_groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--ids", nargs="*", default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=str, default="ml/figures/patient_overview.png")
    args = parser.parse_args()

    if not PARQUET.exists():
        sys.exit(f"Parquet not found: {PARQUET}")

    patient_ids = args.ids if args.ids else sample_patient_ids(3, seed=args.seed)
    print(f"Patients: {patient_ids}")

    df = load_patients(patient_ids)
    print(f"Loaded {len(df):,} rows for {df['patient_id'].nunique()} patients")

    n_patients = len(patient_ids)
    fig_height = (sum(PANEL_HEIGHTS[:N_PANELS]) + SPACER_HEIGHT) * n_patients * 0.55
    fig = plt.figure(figsize=(15, fig_height))

    axes_groups = build_gridspec(fig, n_patients)

    for i, pid in enumerate(patient_ids):
        pat_df = df[df["patient_id"] == pid]
        if pat_df.empty:
            print(f"  Warning: patient {pid} not found in data")
            continue
        is_last = (i == n_patients - 1)
        plot_patient(axes_groups[i], pat_df, days=args.days, show_xaxis=is_last)

    fig.subplots_adjust(top=0.81)

    fig.suptitle(
        f"3-Patient Diagnostic - first {args.days} days\n"
        "dashed: hypo 3.9 / hyper 10.0 mmol/L",
        fontsize=14,
        fontweight="bold",
        ha="center",
        y=0.995,
    )

    leg = fig.legend(
        handles=LEGEND_PATCHES,
        bbox_to_anchor=(0.5, 0.940),
        loc="upper center",
        ncol=3,
        fontsize=10,
        title="Event anomalies",
        title_fontsize=10,
        framealpha=0.92,
        borderpad=0.9,
        handlelength=1.4,
    )
    leg.get_title().set_fontweight("bold")
    leg.get_title().set_ha("center")        # type: ignore[attr-defined]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved -> {out_path}")


if __name__ == "__main__":
    main()
