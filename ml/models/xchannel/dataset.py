"""
Forecast-window dataset for XCHANNEL.

Differs from the PatchTST GlucoseWindowDataset in two ways:
  1. Window length is CONTEXT_LEN + HORIZON (need the horizon to forecast over),
     not just CONTEXT_LEN.
  2. __getitem__ returns the forecaster's inputs split by channel + the target:
        glu_hist  [L]      glucose history only
        ins_full  [L+H]    insulin, known through the horizon
        carb_full [L+H]    carbs,   known through the horizon
        target    [H]      glucose over (t, t+H]  (what we forecast)
        labels    dict     per-class flag over the HORIZON region (for eval)

We reuse dataset.load_patients / normalize_patients verbatim — same parquet,
same per-patient z-score, same numpy-int32 window index trick (a Python list of
tuples OOMs at this scale).
"""

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from numpy.lib.stride_tricks import sliding_window_view
from torch.utils.data import Dataset

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from dataset import (  # noqa: E402
    load_patients, normalize_patients,
    ANOMALY_CLASSES, N_CHANNELS, _PARQUET,
)
from models.xchannel.model import CONTEXT_LEN, HORIZON  # noqa: E402

GLU_COL, INS_COL, CARB_COL = 0, 1, 2          # signal columns in the [T, 8] array
WIN = CONTEXT_LEN + HORIZON                     # full window length we slide


def _make_index(patient_data, stride, train_on):
    """
    Flat int32 window index. A window [s : s+WIN] is valid if it fits the series.
    If train_on='normal', additionally drop any window whose L+H span contains
    an anomaly flag — so the forecaster only ever learns clean dynamics.
    """
    pids = list(patient_data.keys())
    pid_parts, start_parts = [], []
    for i, pid in enumerate(pids):
        arr = patient_data[pid]
        T = arr.shape[0]
        starts = np.arange(0, T - WIN + 1, stride, dtype=np.int32)
        if train_on == "normal" and starts.size:
            flags = arr[:, N_CHANNELS:]                       # [T, 5]
            any_flag = flags.max(axis=1)                      # [T] — 1 if any class
            win_has = sliding_window_view(any_flag, WIN)[starts].max(axis=1)
            starts = starts[win_has == 0]                     # keep clean windows
        pid_parts.append(np.full(starts.shape[0], i, dtype=np.int32))
        start_parts.append(starts)
    if not pid_parts:
        return pids, np.empty(0, np.int32), np.empty(0, np.int32)
    return pids, np.concatenate(pid_parts), np.concatenate(start_parts)


class ForecastWindowDataset(Dataset):
    def __init__(
        self,
        patient_ids: list[str],
        scalers: Optional[dict] = None,
        parquet: Path = _PARQUET,
        stride: int = 5,
        _preloaded: Optional[dict[str, np.ndarray]] = None,
        norm: str = "per_patient",
        train_on: str = "normal",               # 'normal' (clean only) or 'all'
    ) -> None:
        raw = _preloaded if _preloaded is not None else load_patients(patient_ids, parquet)
        own = _preloaded is None
        self._data = normalize_patients(raw, norm=norm, scalers=scalers, inplace=own)
        del raw
        self._pids, self._pid_idx, self._starts = _make_index(self._data, stride, train_on)

    def __len__(self) -> int:
        return len(self._starts)

    def patient_window_counts(self) -> list[tuple[str, int]]:
        counts = np.bincount(self._pid_idx, minlength=len(self._pids))
        return [(pid, int(counts[i])) for i, pid in enumerate(self._pids)]

    def __getitem__(self, idx):
        pid = self._pids[self._pid_idx[idx]]
        s = int(self._starts[idx])
        w = self._data[pid][s : s + WIN]                      # [L+H, 8]

        glu_hist = torch.from_numpy(w[:CONTEXT_LEN, GLU_COL].copy())   # [L]
        ins_full = torch.from_numpy(w[:, INS_COL].copy())             # [L+H]
        carb_full = torch.from_numpy(w[:, CARB_COL].copy())           # [L+H]
        target = torch.from_numpy(w[CONTEXT_LEN:, GLU_COL].copy())     # [H]

        # label = does an anomaly occur in the HORIZON (where the forecast lands)?
        horizon_flags = w[CONTEXT_LEN:, N_CHANNELS:].max(axis=0)       # [5]
        labels = {c: float(horizon_flags[j]) for j, c in enumerate(ANOMALY_CLASSES)}
        return glu_hist, ins_full, carb_full, target, labels
