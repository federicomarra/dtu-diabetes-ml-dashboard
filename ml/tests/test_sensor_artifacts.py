import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from augment.sensor_artifacts import (  # noqa: E402
    apply_artifacts, ArtifactConfig, run_lengths,
    CLEAN, DROPOUT, JUMP, COMPRESSION,
)


def _series(T=2880):
    t = np.arange(T)
    return (7.0 + 2.0 * np.sin(2 * np.pi * t / 288)).astype(np.float32)


def test_intensity_zero_is_identity():
    g = _series()
    valid = np.ones(len(g), dtype=bool)
    rng = np.random.default_rng(0)
    g2, v2, mask = apply_artifacts(g, valid, rng, ArtifactConfig(intensity=0.0))
    assert np.array_equal(g2, g)
    assert np.array_equal(v2, valid)
    assert mask.dtype == np.int8 and (mask == CLEAN).all()
    assert g2.dtype == g.dtype


def test_jump_is_persistent_step_and_marked():
    g = _series()
    valid = np.ones(len(g), dtype=bool)
    rng = np.random.default_rng(1)
    cfg = ArtifactConfig(dropout_pct=0.0, jumps_per_14d=200.0,
                         compressions_per_14d=0.0, jump_mmol=2.0)
    g2, v2, mask = apply_artifacts(g, valid, rng, cfg)
    jump_idx = np.where(mask == JUMP)[0]
    assert len(jump_idx) > 0
    t = int(jump_idx[0])
    delta = (g2 - g)
    assert abs(delta[t:].mean()) >= 0.4               # offset persists downstream
    assert np.allclose(delta[:t], delta[0])           # baseline unshifted before first jump


def test_compression_is_transient_dip_and_recovers():
    g = np.full(2880, 8.0, dtype=np.float32)
    valid = np.ones(len(g), dtype=bool)
    rng = np.random.default_rng(2)
    cfg = ArtifactConfig(dropout_pct=0.0, jumps_per_14d=0.0,
                         compressions_per_14d=200.0, compression_mmol=3.0,
                         compression_min=20, compression_max=60)
    g2, v2, mask = apply_artifacts(g, valid, rng, cfg)
    comp_idx = np.where(mask == COMPRESSION)[0]
    assert len(comp_idx) > 0
    assert (g2[comp_idx] < 8.0 - 0.1).any()           # dipped below baseline
    clean_idx = np.where(mask == CLEAN)[0]
    assert np.allclose(g2[clean_idx], 8.0)            # untouched minutes recover


def test_run_lengths_extracts_true_runs():
    m = np.array([0, 1, 1, 0, 1, 1, 1, 0], dtype=bool)
    assert run_lengths(m) == [2, 3]


def test_dropout_invalidates_and_interpolates():
    g = _series()
    valid = np.ones(len(g), dtype=bool)
    rng = np.random.default_rng(3)
    cfg = ArtifactConfig(dropout_pct=0.15, jumps_per_14d=0.0, compressions_per_14d=0.0)
    g2, v2, mask = apply_artifacts(g, valid, rng, cfg)
    drop_idx = np.where(mask == DROPOUT)[0]
    assert len(drop_idx) > 0
    assert (~v2[drop_idx]).all()                      # dropout minutes invalid
    frac_missing = (~v2).mean()
    assert 0.08 <= frac_missing <= 0.30               # roughly hits target (stochastic)
    runs_start = int(drop_idx[0])
    if runs_start + 2 < len(g) and mask[runs_start + 2] == DROPOUT:
        seg = g2[runs_start:runs_start + 3]
        assert abs((seg[2] - seg[1]) - (seg[1] - seg[0])) < 1e-4   # linear interp


def test_determinism_same_seed():
    g = _series()
    valid = np.ones(len(g), dtype=bool)
    cfg = ArtifactConfig()
    a = apply_artifacts(g, valid, np.random.default_rng(7), cfg)
    b = apply_artifacts(g, valid, np.random.default_rng(7), cfg)
    assert np.array_equal(a[0], b[0])
    assert np.array_equal(a[1], b[1])
    assert np.array_equal(a[2], b[2])


def test_safety_floor_and_no_nan():
    g = np.full(2880, 2.0, dtype=np.float32)          # near floor -> must clamp
    valid = np.ones(len(g), dtype=bool)
    cfg = ArtifactConfig(jumps_per_14d=200.0, compressions_per_14d=200.0, jump_mmol=3.0)
    g2, v2, mask = apply_artifacts(g, valid, np.random.default_rng(9), cfg)
    assert np.isfinite(g2).all()
    assert (g2 >= 1.5 - 1e-6).all()
