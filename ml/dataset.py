"""
Data pipeline for T1D anomaly detection.

Typical usage
-------------
    # one-time setup (creates ml/data/patient_split.json + ml/data/scalers.json):
    split = make_patient_split()
    train_ds, val_ds, test_ds = build_datasets(split)

    # subsequent runs (re-uses saved split + scalers):
    train_ds, val_ds, test_ds = build_datasets()

Window format
-------------
    x      : float32 tensor [WINDOW_LEN x N_CHANNELS]   — z-scored signals
    labels : dict[str, float]                             — binary per class
             1.0 if that anomaly class is present anywhere in the window, else 0.0

Channels (columns 0-2 of x)
----------------------------
    0  blood_glucose    (mmol/L)
    1  insulin_mU_min   (mU/min — basal + bolus)
    2  cho_mg_announced (mg/min — bolus_carbs spread from bolus delivery time; 0 if missed bolus)
       This matches real CGM datasets: carbs are logged when the patient boluses,
       not the physiological absorption curve. cho_mg_min stays in the Parquet for reference.

Anomaly classes in labels
-------------------------
    bolus   : missed, late
    meal    : large
    exercise: prolonged, anaerobic
    (aerobic is not an anomaly — it is the expected exercise behavior)

Memory note
-----------
Loading all patients into RAM is fine for the 500-patient HPC cohort (Days 6-7).
For exploratory use with the full 20k dataset pass a small subset via build_datasets(split,
max_per_split=N) or call GlucoseWindowDataset directly with a chosen patient_ids list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
from torch.utils.data import Dataset

# ── public constants ───────────────────────────────────────────────────────────

CHANNELS: list[str] = ["blood_glucose", "insulin_mU_min", "cho_mg_announced"]
N_CHANNELS: int = len(CHANNELS)  # 3

ANOMALY_CLASSES: list[str] = ["missed", "late", "large", "prolonged", "anaerobic"]

WINDOW_LEN: int = 120   # 2h context window (minutes)
TRAIN_STRIDE: int = 15  # 15-min stride → ~7× window overlap during training
EVAL_STRIDE: int = 1    # 1-min stride → per-minute anomaly scores at inference

# Default file paths (relative to project root, i.e. run from dtu-diabetes-ml-dashboard/)
_PARQUET = Path("ml/data/sim_data/results_20000p_14d_clean.parquet")
_SCALER_FILE = Path("ml/data/scalers.json")
_SPLIT_FILE = Path("ml/data/patient_split.json")

# Which parquet column carries each anomaly class label
_CLASS_TO_COL: dict[str, str] = {
    "missed":    "bolus_status",
    "late":      "bolus_status",
    "large":     "meal_size",
    "prolonged": "exercise_type",
    "anaerobic": "exercise_type",
}


# ── patient split ──────────────────────────────────────────────────────────────

def make_patient_split(
    parquet: Path = _PARQUET,
    seed: int = 42,
    ratios: tuple[float, float, float] = (0.60, 0.20, 0.20),
    out: Path = _SPLIT_FILE,
) -> dict[str, list[str]]:
    """
    Read all patient IDs from the Parquet, shuffle, split 60/20/20 by patient ID.

    Split is deterministic (fixed seed) and saved to JSON so training runs are
    reproducible without re-computing.  Always split by patient, never by day —
    mixing days from the same patient across train/val/test leaks physiology.
    """
    pf = pq.ParquetFile(parquet)
    ids: set[str] = set()
    for rg in range(pf.metadata.num_row_groups):
        batch = pf.read_row_group(rg, columns=["patient_id"])
        ids.update(batch.column("patient_id").to_pylist())

    all_ids: list[str] = sorted(ids)
    rng = np.random.default_rng(seed)
    rng.shuffle(all_ids)  # type: ignore[arg-type]

    n = len(all_ids)
    n_train = int(n * ratios[0])
    n_val = int(n * ratios[1])

    split: dict[str, list[str]] = {
        "train": all_ids[:n_train],
        "val":   all_ids[n_train : n_train + n_val],
        "test":  all_ids[n_train + n_val :],
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(split, indent=2))
    print(
        f"Split: {len(split['train'])} train / {len(split['val'])} val / "
        f"{len(split['test'])} test  →  {out}"
    )
    return split


# ── data loading ───────────────────────────────────────────────────────────────

def load_patients(
    patient_ids: list[str],
    parquet: Path = _PARQUET,
) -> dict[str, np.ndarray]:
    """
    Load signal + label arrays for the requested patients from Parquet.

    Returns
    -------
    dict pid → float32 array of shape [T, 8]  where T = n_days × 1440 minutes:
        columns 0-2  : signal channels (CHANNELS order, see module docstring)
        columns 3-7  : binary anomaly flags per minute (ANOMALY_CLASSES order)

    cho_mg_announced is zero-filled if the column is absent from the Parquet (pre-HPC re-run).
    """
    schema_names = set(pq.read_schema(parquet).names)
    base_cols = [
        "patient_id", "absolute_minute",
        "blood_glucose", "insulin_mU_min",
        "bolus_status", "meal_size", "exercise_type",
    ]
    # cho_mg_announced exists after the HPC re-run; fall back to zeros if absent
    if "cho_mg_announced" in schema_names:
        base_cols.append("cho_mg_announced")

    table = pq.read_table(
        parquet,
        filters=[("patient_id", "in", patient_ids)],
        columns=base_cols,
    )
    df: pd.DataFrame = table.to_pandas()

    if "cho_mg_announced" not in df.columns:
        df["cho_mg_announced"] = 0.0  # zero until HPC re-run produces new cohort

    # Fill label NaN / None with neutral values
    df["bolus_status"] = df["bolus_status"].fillna("normal")
    df["meal_size"] = df["meal_size"].fillna("normal")
    df["exercise_type"] = df["exercise_type"].fillna("none")

    # Precompute binary per-minute anomaly flags as extra columns
    for cls in ANOMALY_CLASSES:
        df[f"_lbl_{cls}"] = (df[_CLASS_TO_COL[cls]] == cls).astype(np.float32)

    signal_cols = CHANNELS
    label_cols = [f"_lbl_{cls}" for cls in ANOMALY_CLASSES]

    data: dict[str, np.ndarray] = {}
    for pid, gdf in df.groupby("patient_id", sort=False):
        gdf = gdf.sort_values("absolute_minute").reset_index(drop=True)
        signals = gdf[signal_cols].to_numpy(dtype=np.float32)  # [T, 3]
        labels  = gdf[label_cols].to_numpy(dtype=np.float32)   # [T, 5]
        data[str(pid)] = np.concatenate([signals, labels], axis=1)  # [T, 8]

    return data


# ── scalers ────────────────────────────────────────────────────────────────────

def fit_scalers(
    patient_data: dict[str, np.ndarray],
    out: Path = _SCALER_FILE,
) -> dict[str, dict[str, float]]:
    """
    Compute per-channel mean and std from training patient data.

    Only the first N_CHANNELS columns are used (signal channels, not labels).
    std is clamped to 1e-8 so a constant channel (e.g. ac_counts = 0) does not 
    cause a division-by-zero at normalisation time.

    """
    all_signals = np.concatenate(
        [arr[:, :N_CHANNELS] for arr in patient_data.values()], axis=0
    )
    scalers: dict[str, dict[str, float]] = {}
    for i, ch in enumerate(CHANNELS):
        mean = float(all_signals[:, i].mean())
        std  = max(float(all_signals[:, i].std()), 1e-8)
        scalers[ch] = {"mean": mean, "std": std}

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scalers, indent=2))
    print(f"Scalers saved  →  {out}")
    return scalers


def load_scalers(path: Path = _SCALER_FILE) -> dict[str, dict[str, float]]:
    return json.loads(path.read_text())


def _apply_scalers(arr: np.ndarray, scalers: dict[str, dict[str, float]]) -> np.ndarray:
    """Return a copy of arr with signal columns (0-2) z-scored. Labels untouched."""
    out = arr.copy()
    for i, ch in enumerate(CHANNELS):
        out[:, i] = (arr[:, i] - scalers[ch]["mean"]) / scalers[ch]["std"]
    return out


# ── window index ───────────────────────────────────────────────────────────────

def _make_window_index(
    patient_data: dict[str, np.ndarray],
    stride: int,
) -> list[tuple[str, int]]:
    """
    Build a flat list of (patient_id, start_row_index) for every valid window.

    A window is valid when [start : start + WINDOW_LEN] fits entirely within
    the patient's continuous time series.  Windows freely cross day boundaries
    — physiological dynamics are continuous across midnight.
    """
    index: list[tuple[str, int]] = []
    for pid, arr in patient_data.items():
        T = arr.shape[0]
        for start in range(0, T - WINDOW_LEN + 1, stride):
            index.append((pid, start))
    return index


# ── dataset class ──────────────────────────────────────────────────────────────

class GlucoseWindowDataset(Dataset):
    """
    Sliding-window PyTorch Dataset over glucose/insulin/carbs time series.

    __getitem__(i) returns
    ----------------------
    x      : float32 tensor  [WINDOW_LEN, N_CHANNELS]
             z-scored signal channels for the i-th window
    labels : dict[str, float]
             binary flag per ANOMALY_CLASS — 1.0 if that class appears
             at any minute within the window, else 0.0
    """

    def __init__(
        self,
        patient_ids: list[str],
        scalers: dict[str, dict[str, float]],
        parquet: Path = _PARQUET,
        stride: int = TRAIN_STRIDE,
        _preloaded: Optional[dict[str, np.ndarray]] = None,
    ) -> None:
        """
        Parameters
        ----------
        patient_ids : list of patient ID strings to include
        scalers     : per-channel mean/std from fit_scalers() (training set only)
        parquet     : path to the Parquet file
        stride      : window step in minutes (TRAIN_STRIDE or EVAL_STRIDE)
        _preloaded  : if given, skip the Parquet read and use this dict directly
                      (used internally by build_datasets to avoid a double load)
        """
        raw = _preloaded if _preloaded is not None else load_patients(patient_ids, parquet)
        self._data: dict[str, np.ndarray] = {
            pid: _apply_scalers(arr, scalers) for pid, arr in raw.items()
        }
        self._index: list[tuple[str, int]] = _make_window_index(self._data, stride)

    def __len__(self) -> int:
        return len(self._index)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, dict[str, float]]:
        pid, start = self._index[idx]
        window = self._data[pid][start : start + WINDOW_LEN]  # [120, 8]

        x = torch.from_numpy(window[:, :N_CHANNELS].copy())   # [120, 3]

        # Collapse per-minute flags to window-level binary presence
        label_flags = window[:, N_CHANNELS:].max(axis=0)      # [5] — max over time
        labels = {cls: float(label_flags[j]) for j, cls in enumerate(ANOMALY_CLASSES)}

        return x, labels


# ── convenience builder ────────────────────────────────────────────────────────

def build_datasets(
    split: Optional[dict[str, list[str]]] = None,
    parquet: Path = _PARQUET,
    train_stride: int = TRAIN_STRIDE,
    eval_stride: int = EVAL_STRIDE,
    max_per_split: Optional[int] = None,
) -> tuple[GlucoseWindowDataset, GlucoseWindowDataset, GlucoseWindowDataset]:
    """
    One-call setup: load/create split, fit scalers, build all three datasets.

    Parameters
    ----------
    split        : pre-computed split dict; if None loads from _SPLIT_FILE or
                   calls make_patient_split() to create it
    parquet      : path to Parquet data file
    train_stride : window stride for the training set (default 15 min)
    eval_stride  : window stride for val/test (default 1 min)
    max_per_split: cap each split to N patients (for memory-limited dev runs)

    Returns
    -------
    (train_ds, val_ds, test_ds)  — all GlucoseWindowDataset instances
    """
    if split is None:
        if _SPLIT_FILE.exists():
            split = json.loads(_SPLIT_FILE.read_text())
        else:
            split = make_patient_split(parquet)

    train_ids = split["train"]          # type: ignore[assignment]
    val_ids   = split["val"]            # type: ignore[assignment]
    test_ids  = split["test"]           # type: ignore[assignment]

    if max_per_split is not None:
        train_ids = train_ids[:max_per_split]
        val_ids   = val_ids[:max_per_split]
        test_ids  = test_ids[:max_per_split]

    print(f"Loading {len(train_ids)} training patients for scaler fitting …")
    train_raw = load_patients(train_ids, parquet)
    scalers   = fit_scalers(train_raw)

    print(f"Building train dataset ({len(train_ids)} patients, stride={train_stride}) …")
    train_ds = GlucoseWindowDataset(
        train_ids, scalers, parquet, stride=train_stride, _preloaded=train_raw
    )

    print(f"Building val dataset ({len(val_ids)} patients, stride={eval_stride}) …")
    val_ds = GlucoseWindowDataset(val_ids, scalers, parquet, stride=eval_stride)

    print(f"Building test dataset ({len(test_ids)} patients, stride={eval_stride}) …")
    test_ds = GlucoseWindowDataset(test_ids, scalers, parquet, stride=eval_stride)

    return train_ds, val_ds, test_ds
