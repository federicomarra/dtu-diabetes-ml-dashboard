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
    x      : float32 tensor [WINDOW_LEN x N_CHANNELS]   - z-scored signals
    labels : dict[str, float]                             - binary per class
             1.0 if that anomaly class is present anywhere in the window, else 0.0

Channels (columns 0-2 of x)
----------------------------
    0  blood_glucose    (mmol/L)
    1  insulin_mU_min   (mU/min - basal + bolus)
    2  cho_mg_announced (mg/min - bolus_carbs spread from bolus delivery time; 0 if missed bolus)
       This matches real CGM datasets: carbs are logged when the patient boluses,
       not the physiological absorption curve. cho_mg_min stays in the Parquet for reference.

Anomaly classes in labels
-------------------------
    bolus   : missed, late
    meal    : large
    exercise: prolonged, anaerobic
    (aerobic is not an anomaly - it is the expected exercise behavior)

Memory note
-----------
load_patients streams the Parquet in Arrow batches and stores one compact
float32 [T, 8] array per patient - the 12k-patient training split costs
~8 GB. Window indexes are int32 numpy arrays (a Python tuple list at
stride=1 alone was ~8 GB). Never convert the full cohort to pandas: the
object-dtype string columns need >64 GB and OOM-killed the HPC jobs.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import torch
from torch.utils.data import Dataset

# -- public constants -----------------------------------------------------------

CHANNELS: list[str] = ["blood_glucose", "insulin_mU_min", "cho_mg_announced"]
N_CHANNELS: int = len(CHANNELS)  # 3

ANOMALY_CLASSES: list[str] = ["missed", "late", "large", "prolonged", "anaerobic"]

WINDOW_LEN: int = 120   # 2h context window (minutes)
TRAIN_STRIDE: int = 15  # 15-min stride -> ~7x window overlap during training
EVAL_STRIDE: int = 1    # 1-min stride -> per-minute anomaly scores at inference

# Default file paths (relative to project root, i.e. run from dtu-diabetes-ml-dashboard/)
_PARQUET = Path("ml/data/sim_data/results_5000p_42d.parquet")
_SCALER_FILE = Path("ml/data/scalers.json")
_SPLIT_FILE = Path("ml/data/patient_split.json")

# -- reproducibility ---------------------------------------------------------

def set_seed(seed: int = 42) -> None:
    """Seed Python, NumPy and torch (CPU+CUDA) RNGs for reproducible runs."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def progress_log(i: int, n: int, t0: float, label: str = "", every: int = 500) -> None:
    """
    Print throughput + ETA every `every` steps (and on the last step).

    For the stride-1 eval loops (~80M test windows) so they are not a silent
    multi-hour black box.
    """
    if i % every == 0 or i == n:
        el  = time.time() - t0
        ips = i / el if el > 0 else 0.0
        eta = (n - i) / ips / 60 if ips > 0 else 0.0
        tag = f"{label} " if label else ""
        print(f"    {tag}{i:>7}/{n}  {ips:.1f} it/s  ETA {eta:.1f}m", flush=True)


# Which parquet column carries each anomaly class label
_CLASS_TO_COL: dict[str, str] = {
    "missed":    "bolus_status",
    "late":      "bolus_status",
    "large":     "meal_size",
    "prolonged": "exercise_type",
    "anaerobic": "exercise_type",
}


# -- patient split --------------------------------------------------------------

def make_patient_split(
    parquet: Path = _PARQUET,
    seed: int = 42,
    ratios: tuple[float, float, float] = (0.60, 0.20, 0.20),
    out: Path = _SPLIT_FILE,
) -> dict[str, list[str]]:
    """
    Read all patient IDs from the Parquet, shuffle, split 60/20/20 by patient ID.

    Split is deterministic (fixed seed) and saved to JSON so training runs are
    reproducible without re-computing.  Always split by patient, never by day -
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
        "_parquet": str(parquet),   # type: ignore  # metadata key; the rest are ID lists
        "train": all_ids[:n_train],
        "val":   all_ids[n_train : n_train + n_val],
        "test":  all_ids[n_train + n_val :],
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(split, indent=2))
    print(
        f"Split: {len(split['train'])} train / {len(split['val'])} val / "
        f"{len(split['test'])} test  ->  {out}"
    )
    return split


# -- data loading ---------------------------------------------------------------

def load_patients(
    patient_ids: list[str],
    parquet: Path = _PARQUET,
    batch_rows: int = 262_144,
) -> dict[str, np.ndarray]:
    """
    Load signal + label arrays for the requested patients from Parquet.

    Streams the file in Arrow record batches and converts each batch straight
    to numpy - the full cohort is never materialised as an Arrow table or a
    pandas DataFrame. (A pandas conversion of the 12k-patient training split
    needs >64 GB because the string columns become Python objects; it
    OOM-killed the HPC jobs.) Peak memory ~ the compact output dict.

    Returns
    -------
    dict pid -> float32 array of shape [T, 8]  where T = n_days x 1440 minutes:
        columns 0-2  : signal channels (CHANNELS order, see module docstring)
        columns 3-7  : binary anomaly flags per minute (ANOMALY_CLASSES order)

    cho_mg_announced is zero-filled if the column is absent from the Parquet (pre-HPC re-run).
    """
    schema_names = set(pq.read_schema(parquet).names)
    has_cho = "cho_mg_announced" in schema_names

    base_cols = [
        "patient_id", "absolute_minute",
        "blood_glucose", "insulin_mU_min",
        "bolus_status", "meal_size", "exercise_type",
    ]
    if has_cho:
        base_cols.append("cho_mg_announced")

    want = pa.array(sorted({str(p) for p in patient_ids}), type=pa.large_string())

    # Per-patient chunk accumulators - a patient can span several batches
    arr_chunks: dict[str, list[np.ndarray]] = {}
    min_chunks: dict[str, list[np.ndarray]] = {}

    pf = pq.ParquetFile(parquet)
    for batch in pf.iter_batches(batch_size=batch_rows, columns=base_cols):
        keep = pc.is_in(batch.column("patient_id"), value_set=want)   # type: ignore  # pyarrow.compute is dynamically generated
        n_keep = pc.sum(keep).as_py() or 0   # type: ignore  # pyarrow.compute is dynamically generated
        if n_keep == 0:
            continue
        if n_keep < batch.num_rows:
            batch = batch.filter(keep)

        pids    = batch.column("patient_id").to_numpy(zero_copy_only=False)
        minutes = batch.column("absolute_minute").to_numpy(zero_copy_only=False)

        n = batch.num_rows
        arr = np.empty((n, N_CHANNELS + len(ANOMALY_CLASSES)), dtype=np.float32)
        for j, ch in enumerate(CHANNELS):
            if ch == "cho_mg_announced" and not has_cho:
                arr[:, j] = 0.0  # zero until HPC re-run produces new cohort
            else:
                arr[:, j] = batch.column(ch).to_numpy(zero_copy_only=False)
        for k, cls in enumerate(ANOMALY_CLASSES):
            # null labels mean "normal"/"none" - never equal to an anomaly class
            eq = pc.fill_null(pc.equal(batch.column(_CLASS_TO_COL[cls]), cls), False)   # type: ignore  # pyarrow.compute is dynamically generated
            arr[:, N_CHANNELS + k] = eq.to_numpy(zero_copy_only=False)

        for pid in np.unique(pids):
            m = pids == pid
            key = str(pid)
            arr_chunks.setdefault(key, []).append(arr[m])
            min_chunks.setdefault(key, []).append(minutes[m])

    data: dict[str, np.ndarray] = {}
    for pid, chunks in arr_chunks.items():
        full = np.concatenate(chunks, axis=0) if len(chunks) > 1 else chunks[0]
        mins = np.concatenate(min_chunks[pid]) if len(min_chunks[pid]) > 1 else min_chunks[pid][0]
        if np.any(mins[:-1] > mins[1:]):  # only re-sort if rows arrived out of time order
            full = full[np.argsort(mins, kind="stable")]
        data[pid] = full

    return data


# -- scalers --------------------------------------------------------------------

def fit_scalers(
    patient_data: dict[str, np.ndarray],
    out: Path = _SCALER_FILE,
    parquet: Optional[Path] = None,
) -> dict[str, dict[str, float]]:
    """
    Compute per-channel mean and std from training patient data.

    Only the first N_CHANNELS columns are used (signal channels, not labels).
    std is clamped to 1e-8 so a constant channel (e.g. ac_counts = 0) does not
    cause a division-by-zero at normalisation time.

    Accumulates per-patient sums instead of concatenating all patients
    (the concat alone copies ~3 GB on the 12k-patient split).

    parquet : if given, stored under "_parquet" in the JSON so build_datasets
              can validate the cache against the cohort it was fit on.
    """
    n_rows = 0
    s  = np.zeros(N_CHANNELS, dtype=np.float64)
    ss = np.zeros(N_CHANNELS, dtype=np.float64)
    for arr in patient_data.values():
        sig = arr[:, :N_CHANNELS].astype(np.float64)
        n_rows += sig.shape[0]
        s  += sig.sum(axis=0)
        ss += np.square(sig).sum(axis=0)

    mean = s / n_rows
    std = np.sqrt(np.maximum(ss / n_rows - mean ** 2, 0.0))

    scalers: dict[str, dict[str, float]] = {}
    for i, ch in enumerate(CHANNELS):
        scalers[ch] = {"mean": float(mean[i]), "std": max(float(std[i]), 1e-8)}

    payload: dict = dict(scalers)
    if parquet is not None:
        payload["_parquet"] = str(parquet)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(f"Scalers saved  ->  {out}")
    return scalers


def load_scalers(path: Path = _SCALER_FILE) -> dict[str, dict[str, float]]:
    return json.loads(path.read_text())


def _apply_scalers(
    arr: np.ndarray,
    scalers: dict[str, dict[str, float]],
    inplace: bool = False,
) -> np.ndarray:
    """
    GLOBAL z-score: signal columns (0-2) scaled by population stats. Labels
    untouched.

    inplace=True mutates arr and returns it - skips the full-array copy,
    which matters when scaling the 12k-patient training dict (~8 GB).
    """
    out = arr if inplace else arr.copy()
    for i, ch in enumerate(CHANNELS):
        out[:, i] = (out[:, i] - scalers[ch]["mean"]) / scalers[ch]["std"]
    return out


# -- normalization modes ------------------------------------------------------

NORM_MODES = ("per_patient", "global")


def _patient_zscore(arr: np.ndarray, inplace: bool = False) -> np.ndarray:
    """
    PER-PATIENT z-score: signal columns (0-2) scaled by THIS patient's own
    mean/std (full series). Labels untouched.

    This is the spec default. It removes the cross-patient baseline confound
    (a patient with naturally high glucose no longer looks "elevated" vs the
    population), puts every patient on a comparable scale for population
    pretraining, and matches the per-patient threshold calibration downstream.

    Uses the patient's whole series, so it is acausal - fine for synthetic
    training/eval. The causal, deployment-faithful version (baseline-days
    stats only) is scheduled separately for real-data evaluation.
    """
    out = arr if inplace else arr.copy()
    sig = out[:, :N_CHANNELS]
    mean = sig.mean(axis=0)
    std = np.maximum(sig.std(axis=0), 1e-8)   # guard constant channels
    out[:, :N_CHANNELS] = (sig - mean) / std
    return out


def normalize_patients(
    patient_data: dict[str, np.ndarray],
    norm: str = "per_patient",
    scalers: Optional[dict[str, dict[str, float]]] = None,
    inplace: bool = False,
) -> dict[str, np.ndarray]:
    """
    Scale a patient_data dict. norm='per_patient' (default, spec) scales each
    patient by its own stats; norm='global' requires fitted population scalers.
    """
    if norm == "per_patient":
        return {pid: _patient_zscore(arr, inplace) for pid, arr in patient_data.items()}
    if norm == "global":
        if scalers is None:
            raise ValueError("norm='global' requires fitted scalers")
        return {pid: _apply_scalers(arr, scalers, inplace) for pid, arr in patient_data.items()}
    raise ValueError(f"unknown norm mode {norm!r}; expected one of {NORM_MODES}")


# -- window index ---------------------------------------------------------------

def _make_window_index(
    patient_data: dict[str, np.ndarray],
    stride: int,
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """
    Build a flat index of every valid window as two parallel int32 arrays.

    A window is valid when [start : start + WINDOW_LEN] fits entirely within
    the patient's continuous time series.  Windows freely cross day boundaries
    - physiological dynamics are continuous across midnight.

    Returns (pids, pid_idx, starts): window i belongs to patient
    pids[pid_idx[i]] and begins at row starts[i].  Stored as numpy because a
    Python list of (pid, start) tuples at stride=1 on a 4k-patient split is
    ~80M tuples ~ 8 GB.
    """
    pids = list(patient_data.keys())
    pid_parts: list[np.ndarray] = []
    start_parts: list[np.ndarray] = []
    for i, pid in enumerate(pids):
        T = patient_data[pid].shape[0]
        starts = np.arange(0, T - WINDOW_LEN + 1, stride, dtype=np.int32)
        pid_parts.append(np.full(starts.shape[0], i, dtype=np.int32))
        start_parts.append(starts)
    if not pid_parts:
        return pids, np.empty(0, dtype=np.int32), np.empty(0, dtype=np.int32)
    return pids, np.concatenate(pid_parts), np.concatenate(start_parts)


# -- dataset class --------------------------------------------------------------

class GlucoseWindowDataset(Dataset):
    """
    Sliding-window PyTorch Dataset over glucose/insulin/carbs time series.

    __getitem__(i) returns
    ----------------------
    x      : float32 tensor  [WINDOW_LEN, N_CHANNELS]
             z-scored signal channels for the i-th window
    labels : dict[str, float]
             binary flag per ANOMALY_CLASS - 1.0 if that class appears
             at any minute within the window, else 0.0
    """

    def __init__(
        self,
        patient_ids: list[str],
        scalers: Optional[dict[str, dict[str, float]]] = None,
        parquet: Path = _PARQUET,
        stride: int = TRAIN_STRIDE,
        _preloaded: Optional[dict[str, np.ndarray]] = None,
        norm: str = "per_patient",
    ) -> None:
        """
        Parameters
        ----------
        patient_ids : list of patient ID strings to include
        scalers     : population mean/std from fit_scalers(); required only for
                      norm='global', ignored (may be None) for norm='per_patient'
        parquet     : path to the Parquet file
        stride      : window step in minutes (TRAIN_STRIDE or EVAL_STRIDE)
        _preloaded  : if given, skip the Parquet read and use this dict directly
                      (used internally by build_datasets to avoid a double load)
        norm        : 'per_patient' (default, spec) or 'global'
        """
        raw = _preloaded if _preloaded is not None else load_patients(patient_ids, parquet)
        # Scale in place only when we loaded the data ourselves - a caller's
        # _preloaded dict must not be mutated (build_datasets frees its copy).
        own = _preloaded is None
        self._data: dict[str, np.ndarray] = normalize_patients(
            raw, norm=norm, scalers=scalers, inplace=own
        )
        del raw  # free the unscaled copy; self._data holds the only reference from here on
        self._pids, self._pid_idx, self._starts = _make_window_index(self._data, stride)

    def __len__(self) -> int:
        return len(self._starts)

    def patient_window_counts(self) -> list[tuple[str, int]]:
        """
        (pid, n_windows) per patient, in flat-index order.

        Windows are stored contiguous per patient (see _make_window_index) and
        the eval loader runs shuffle=False, so a score array produced in this
        same order can be sliced into per-patient blocks - needed for
        per-patient threshold calibration. Within each block the windows are in
        time order, so "first N days" means this patient's first N days.
        """
        counts = np.bincount(self._pid_idx, minlength=len(self._pids))
        return [(pid, int(counts[i])) for i, pid in enumerate(self._pids)]

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, dict[str, float]]:
        pid = self._pids[self._pid_idx[idx]]
        start = int(self._starts[idx])
        window = self._data[pid][start : start + WINDOW_LEN]  # [120, 8]

        x = torch.from_numpy(window[:, :N_CHANNELS].copy())   # [120, 3]

        # Collapse per-minute flags to window-level binary presence
        label_flags = window[:, N_CHANNELS:].max(axis=0)      # [5] - max over time
        labels = {cls: float(label_flags[j]) for j, cls in enumerate(ANOMALY_CLASSES)}

        return x, labels


# -- convenience builder --------------------------------------------------------

def build_datasets(
    split: Optional[dict[str, list[str]]] = None,
    parquet: Path = _PARQUET,
    train_stride: int = TRAIN_STRIDE,
    eval_stride: int = EVAL_STRIDE,
    max_per_split: Optional[int] = None,
    max_val: Optional[int] = None,
    include_train: bool = True,
    include_val: bool = True,
    include_test: bool = True,
    norm: str = "per_patient",
) -> tuple[
    Optional[GlucoseWindowDataset],
    Optional[GlucoseWindowDataset],
    Optional[GlucoseWindowDataset],
]:
    """
    One-call setup: load/create split, build the requested datasets.

    Parameters
    ----------
    split        : pre-computed split dict; if None loads from _SPLIT_FILE or
                   calls make_patient_split() to create it
    parquet      : path to Parquet data file
    train_stride : window stride for the training set (default 15 min)
    eval_stride  : window stride for val/test (default 1 min)
    max_per_split: cap each split to N patients (for memory-limited dev runs)
    max_val      : cap the val split to N patients (after max_per_split) - a
                   stable checkpoint-selection signal needs far fewer than the
                   full 4k val patients, and scoring 5M val windows every epoch
                   is wasteful. Train and test are untouched.
    include_*    : skip building unused splits - None is returned in their
                   place. Pretraining doesn't need test; anomaly scoring
                   doesn't need train/val. Skipping the 12k-patient train
                   load saves minutes of I/O and ~16 GB of RAM.
    norm         : 'per_patient' (default, spec) or 'global'.

    Normalization
    -------------
    norm='per_patient' (default): each patient is z-scored by its own stats -
    no population scalers, no cache, and eval-only runs never touch the train
    split (so include_train=False skips it for free).

    norm='global': population scalers are fit on the train split, written to
    ml/data/scalers.json tagged with the parquet path, and re-used when the
    tag matches (lets eval-only runs skip the train load). Caching is disabled
    when max_per_split is set - scalers fit on a subset must never leak into
    full runs.

    Returns
    -------
    (train_ds, val_ds, test_ds)  - GlucoseWindowDataset or None per include flag
    """
    if norm not in NORM_MODES:
        raise ValueError(f"unknown norm mode {norm!r}; expected one of {NORM_MODES}")

    if split is None:
        if _SPLIT_FILE.exists():
            cached = json.loads(_SPLIT_FILE.read_text())
            if cached.get("_parquet") == str(parquet):
                split = cached
            else:
                print("Split cache is for a different parquet - regenerating...")
                split = make_patient_split(parquet)
        else:
            split = make_patient_split(parquet)

    train_ids = split["train"]          # type: ignore[assignment]
    val_ids   = split["val"]            # type: ignore[assignment]
    test_ids  = split["test"]           # type: ignore[assignment]

    if max_per_split is not None:
        train_ids = train_ids[:max_per_split]
        val_ids   = val_ids[:max_per_split]
        test_ids  = test_ids[:max_per_split]

    # Validation only needs a representative subset for a stable checkpoint-
    # selection signal - capping it avoids scoring millions of val windows
    # every epoch. Does not touch train (gradient steps) or test (final eval).
    if max_val is not None:
        val_ids = val_ids[:max_val]

    # Global mode fits/caches population scalers on the train split. Per-patient
    # mode needs none of this - each patient self-normalizes.
    use_scaler_cache = norm == "global" and max_per_split is None
    scalers: Optional[dict[str, dict[str, float]]] = None
    if use_scaler_cache and _SCALER_FILE.exists():
        cached_sc = load_scalers()
        if cached_sc.get("_parquet") == str(parquet):
            scalers = {ch: cached_sc[ch] for ch in CHANNELS}
            print(f"Re-using cached scalers  <-  {_SCALER_FILE}")

    train_ds = val_ds = test_ds = None

    # Train patients are loaded if the train dataset is wanted, OR (global mode
    # only) population scalers still need fitting on the train split.
    need_scalers = norm == "global" and scalers is None
    if include_train or need_scalers:
        print(f"Loading {len(train_ids)} training patients ...")
        train_raw = load_patients(train_ids, parquet)
        if need_scalers:
            scalers = fit_scalers(
                train_raw, parquet=parquet if use_scaler_cache else None
            )
        if include_train:
            print(f"Building train dataset ({len(train_ids)} patients, stride={train_stride}, norm={norm}) ...")
            train_ds = GlucoseWindowDataset(
                train_ids, scalers, parquet, stride=train_stride,
                _preloaded=train_raw, norm=norm,
            )
        del train_raw  # scaled copy now lives only in train_ds._data

    if include_val:
        print(f"Building val dataset ({len(val_ids)} patients, stride={eval_stride}, norm={norm}) ...")
        val_ds = GlucoseWindowDataset(val_ids, scalers, parquet, stride=eval_stride, norm=norm)

    if include_test:
        print(f"Building test dataset ({len(test_ids)} patients, stride={eval_stride}, norm={norm}) ...")
        test_ds = GlucoseWindowDataset(test_ids, scalers, parquet, stride=eval_stride, norm=norm)

    return train_ds, val_ds, test_ds
