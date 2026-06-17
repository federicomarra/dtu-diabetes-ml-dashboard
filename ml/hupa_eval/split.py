"""Deterministic patient-level split for HUPA (train/val/test)."""
import numpy as np


def hupa_split(pids, seed: int = 42, n_train: int = 15, n_val: int = 3) -> dict:
    pids = sorted(pids)
    order = np.random.default_rng(seed).permutation(len(pids))
    shuf = [pids[i] for i in order]
    return {"train": shuf[:n_train],
            "val":   shuf[n_train:n_train + n_val],
            "test":  shuf[n_train + n_val:]}
