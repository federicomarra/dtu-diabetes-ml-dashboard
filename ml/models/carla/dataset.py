"""
ContrastiveDataset and ContrastiveBatchSampler for CARLA pretraining.

Dataset design
--------------
Each __getitem__ returns a single window plus a binary label:
    (window [WINDOW_LEN, N_CHANNELS], is_normal: int)

is_normal = 1 for normal windows, 0 for anomaly windows.

A window is anomalous if any of the 5 anomaly flags (columns 3-7 of the
[T, 8] patient array) is 1 at any minute within the window.

The SupCon loss handles triplet logic itself - it receives a full batch of
(window, label) pairs and constructs positive/negative sets from the labels.

Batch composition
-----------------
At true data prevalence (~5% anomaly), batches would be dominated by normal
windows and the anomaly repulsion signal would be too weak. ContrastiveBatchSampler
enforces 70% normal / 30% anomaly per batch by oversampling the anomaly pool.

Usage
-----
    from dataset import load_patients, fit_scalers, _apply_scalers
    from models.carla.dataset import ContrastiveDataset, ContrastiveBatchSampler
    from torch.utils.data import DataLoader

    raw = load_patients(train_ids, parquet)
    scalers = fit_scalers(raw)
    scaled = {pid: _apply_scalers(arr, scalers) for pid, arr in raw.items()}

    ds = ContrastiveDataset(scaled)
    sampler = ContrastiveBatchSampler(ds, batch_size=256, normal_ratio=0.7)
    loader = DataLoader(ds, batch_sampler=sampler)

    for windows, labels in loader:   # windows: [B, 120, 3], labels: [B]
        ...
"""

import random
from typing import Iterator

import numpy as np
import torch
from torch.utils.data import Dataset, Sampler

# Lazy import to avoid circular dependency - dataset.py is in ml/
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from dataset import WINDOW_LEN, N_CHANNELS, TRAIN_STRIDE


class ContrastiveDataset(Dataset):
    """
    Sliding-window dataset returning (window, is_normal) pairs.

    Parameters
    ----------
    patient_data : dict pid -> np.ndarray [T, 8], already z-scored (signals in
                   cols 0-2, binary anomaly flags in cols 3-7)
    stride       : window stride in minutes
    window_len   : window length in minutes (default WINDOW_LEN = 120)
    """

    def __init__(
        self,
        patient_data: dict[str, np.ndarray],
        stride: int = TRAIN_STRIDE,
        window_len: int = WINDOW_LEN,
    ) -> None:
        self._data = patient_data
        self._window_len = window_len
        self._pids: list[str] = list(patient_data.keys())

        # Separate index pools so BatchSampler can address each independently.
        # Stored as parallel int32 numpy arrays (pid_idx into self._pids +
        # window start row) - a Python list of (pid, start) tuples on the
        # 12k-patient training split is ~16M tuples ~ 2 GB.
        self._normal_pid_idx:  np.ndarray
        self._normal_starts:   np.ndarray
        self._anomaly_pid_idx: np.ndarray
        self._anomaly_starts:  np.ndarray

        # O(1) lookup for positive pair sampling (used by pretrain.py if needed).
        # Maps patient_id -> sorted array of normal window start indices.
        self.normal_by_patient: dict[str, np.ndarray] = {}

        self._build_index(stride)

    def _build_index(self, stride: int) -> None:
        n_pid, n_start, a_pid, a_start = [], [], [], []
        for i, pid in enumerate(self._pids):
            arr = self._data[pid]
            T = arr.shape[0]
            starts = np.arange(0, T - self._window_len + 1, stride, dtype=np.int32)

            # Anomaly if ANY flag (cols 3-7) is non-zero at ANY minute in the
            # window. Vectorised: cumulative sum of the per-minute flag turns
            # "any flag inside [start, start+W)" into two lookups per window.
            flags = (arr[:, N_CHANNELS:] != 0).any(axis=1)
            csum = np.concatenate(([0], np.cumsum(flags, dtype=np.int64)))
            is_anom = (csum[starts + self._window_len] - csum[starts]) > 0

            n_pid.append(np.full(int((~is_anom).sum()), i, dtype=np.int32))
            n_start.append(starts[~is_anom])
            a_pid.append(np.full(int(is_anom.sum()), i, dtype=np.int32))
            a_start.append(starts[is_anom])
            self.normal_by_patient[pid] = starts[~is_anom]

        empty = np.empty(0, dtype=np.int32)
        self._normal_pid_idx  = np.concatenate(n_pid)   if n_pid   else empty
        self._normal_starts   = np.concatenate(n_start) if n_start else empty
        self._anomaly_pid_idx = np.concatenate(a_pid)   if a_pid   else empty
        self._anomaly_starts  = np.concatenate(a_start) if a_start else empty

    # -- flat indexing: normals first, then anomalies --------------------------

    @property
    def n_normal(self) -> int:
        return len(self._normal_starts)

    @property
    def n_anomaly(self) -> int:
        return len(self._anomaly_starts)

    def __len__(self) -> int:
        return self.n_normal + self.n_anomaly

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        if idx < self.n_normal:
            pid = self._pids[self._normal_pid_idx[idx]]
            start = int(self._normal_starts[idx])
            is_normal = 1
        else:
            j = idx - self.n_normal
            pid = self._pids[self._anomaly_pid_idx[j]]
            start = int(self._anomaly_starts[j])
            is_normal = 0

        window = self._data[pid][start : start + self._window_len, :N_CHANNELS]
        x = torch.from_numpy(window.copy())   # [WINDOW_LEN, N_CHANNELS]
        return x, is_normal


class ContrastiveBatchSampler(Sampler):
    """
    Yields batches with a fixed normal/anomaly composition.

    Each batch contains `n_normal` indices into the normal pool and
    `n_anomaly` indices into the anomaly pool. The two pools are shuffled
    independently at the start of each epoch. Anomaly windows are cycled
    (with replacement) if the anomaly pool is smaller than the normal pool.

    Parameters
    ----------
    dataset      : ContrastiveDataset instance
    batch_size   : total windows per batch
    normal_ratio : fraction of each batch that is normal (default 0.7)
    """

    def __init__(
        self,
        dataset: ContrastiveDataset,
        batch_size: int,
        normal_ratio: float = 0.7,
    ) -> None:
        self._n_normal_per_batch  = int(batch_size * normal_ratio)
        self._n_anomaly_per_batch = batch_size - self._n_normal_per_batch
        self._n_normal  = dataset.n_normal
        self._n_anomaly = dataset.n_anomaly
        # Normal indices in dataset flat space = [0, n_normal)
        # Anomaly indices in dataset flat space = [n_normal, n_normal + n_anomaly)
        self._normal_offset  = 0
        self._anomaly_offset = dataset.n_normal

    def __len__(self) -> int:
        return self._n_normal // self._n_normal_per_batch

    def __iter__(self) -> Iterator[list[int]]:
        normal_pool  = list(range(self._n_normal))
        anomaly_pool = list(range(self._n_anomaly))
        random.shuffle(normal_pool)
        random.shuffle(anomaly_pool)

        ni = 0
        ai = 0
        while ni + self._n_normal_per_batch <= len(normal_pool):
            normal_batch  = normal_pool[ni : ni + self._n_normal_per_batch]
            anomaly_batch = [
                anomaly_pool[(ai + j) % len(anomaly_pool)]
                for j in range(self._n_anomaly_per_batch)
            ]
            # Translate to flat dataset indices
            batch = (
                [self._normal_offset  + i for i in normal_batch] +
                [self._anomaly_offset + i for i in anomaly_batch]
            )
            random.shuffle(batch)   # mix normal/anomaly within the batch
            yield batch
            ni += self._n_normal_per_batch
            ai += self._n_anomaly_per_batch
