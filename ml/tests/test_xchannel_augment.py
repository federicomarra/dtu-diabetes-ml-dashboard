import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from augment.sensor_artifacts import ArtifactConfig  # noqa: E402
from models.xchannel.dataset import (  # noqa: E402
    ForecastWindowDataset, GLU_COL, INS_COL, CARB_COL,
)


def _preloaded(T=4000):
    rng = np.random.default_rng(0)
    arr = np.zeros((T, 8), dtype=np.float32)
    arr[:, GLU_COL] = 7.0 + 2.0 * np.sin(2 * np.pi * np.arange(T) / 288)
    arr[:, INS_COL] = rng.random(T).astype(np.float32)
    arr[:, CARB_COL] = rng.random(T).astype(np.float32)
    return {"p0": arr}


def test_augment_off_matches_baseline():
    base = ForecastWindowDataset(["p0"], _preloaded={k: v.copy() for k, v in _preloaded().items()},
                                 stride=20, train_on="all")
    off = ForecastWindowDataset(["p0"], _preloaded={k: v.copy() for k, v in _preloaded().items()},
                                stride=20, train_on="all", augment=False)
    assert np.array_equal(base._data["p0"], off._data["p0"])


def test_augment_on_changes_glucose_only():
    pre = _preloaded()
    off = ForecastWindowDataset(["p0"], _preloaded={k: v.copy() for k, v in pre.items()},
                                stride=20, train_on="all", augment=False)
    on = ForecastWindowDataset(["p0"], _preloaded={k: v.copy() for k, v in pre.items()},
                               stride=20, train_on="all", augment=True,
                               artifact_cfg=ArtifactConfig(dropout_pct=0.1, jumps_per_14d=50.0,
                                                           compressions_per_14d=50.0),
                               augment_seed=123)
    assert not np.array_equal(on._data["p0"][:, GLU_COL], off._data["p0"][:, GLU_COL])  # glucose changed
    assert np.array_equal(on._data["p0"][:, INS_COL], off._data["p0"][:, INS_COL])      # insulin untouched
    assert np.array_equal(on._data["p0"][:, CARB_COL], off._data["p0"][:, CARB_COL])    # carbs untouched


def test_augment_deterministic_seed():
    pre = _preloaded()
    a = ForecastWindowDataset(["p0"], _preloaded={k: v.copy() for k, v in pre.items()},
                              stride=20, train_on="all", augment=True, augment_seed=7)
    b = ForecastWindowDataset(["p0"], _preloaded={k: v.copy() for k, v in pre.items()},
                              stride=20, train_on="all", augment=True, augment_seed=7)
    assert np.array_equal(a._data["p0"], b._data["p0"])
