"""
Sensor-artifact augmentation for CGM glucose: dropouts, calibration jumps,
compression lows. Pure + seeded — same (inputs, rng state) → same output.
Sensor-only: operates on the glucose channel; insulin/carbs are never passed in.

Dropout gap-lengths are intended to be sourced from Ohio's real gaps (see
`run_lengths`); jump/compression parameters are literature-based (Dexcom
recalibration steps; nocturnal compression lows) and live in ArtifactConfig.

Injection order is jumps → compression → dropouts, so a dropout's linear
interpolation spans whatever the other artifacts left (a real dropout hides
whatever the sensor was doing). Glucose is clamped to the CGM floor last.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CGM_FLOOR = 1.5  # mmol/L — matches simulator cgm_min_glucose_mmol
CLEAN, DROPOUT, JUMP, COMPRESSION = 0, 1, 2, 3


@dataclass
class ArtifactConfig:
    # dropouts
    dropout_pct: float = 0.10            # target fraction of timeline made missing
    gap_len_samples: tuple[int, ...] = ()  # empirical Ohio gap lengths (min); empty → lognormal
    gap_len_mu: float = 3.0              # lognormal(log-min) fallback mean
    gap_len_sigma: float = 0.8           # lognormal fallback sigma
    # calibration jumps
    jumps_per_14d: float = 2.0           # Poisson rate per 14 days
    jump_mmol: float = 2.0               # |offset| ~ U(0.5, jump_mmol), random sign
    # compression lows
    compressions_per_14d: float = 3.0
    compression_mmol: float = 3.0        # max dip depth
    compression_min: int = 20            # duration min (minutes)
    compression_max: int = 60            # duration max (minutes)
    nocturnal_frac: float = 0.7          # fraction placed in 00:00–06:00
    # global
    intensity: float = 1.0               # 0 → identity (ablation "off")


def run_lengths(mask_bool) -> list[int]:
    """Lengths of consecutive-True runs in a boolean array."""
    m = np.asarray(mask_bool, dtype=bool)
    if not m.any():
        return []
    idx = np.flatnonzero(np.diff(np.r_[0, m.view(np.int8), 0]))
    return [int(idx[i + 1] - idx[i]) for i in range(0, len(idx), 2)]


def _inject_jumps(g, mask, rng, cfg, days):
    n = int(rng.poisson(cfg.jumps_per_14d * days / 14.0))
    for _ in range(n):
        t = int(rng.integers(1, len(g)))
        delta = float(rng.uniform(0.5, cfg.jump_mmol)) * float(rng.choice([-1.0, 1.0]))
        g[t:] += delta
        mask[t] = JUMP


def _inject_compression(g, mask, rng, cfg, days, T):
    n = int(rng.poisson(cfg.compressions_per_14d * days / 14.0))
    n_days = max(1, T // 1440)
    for _ in range(n):
        dur = int(rng.integers(cfg.compression_min, cfg.compression_max + 1))
        if dur >= T:
            continue
        if rng.random() < cfg.nocturnal_frac:
            day = int(rng.integers(0, n_days))
            start = day * 1440 + int(rng.integers(0, 360))   # 00:00–06:00
        else:
            start = int(rng.integers(0, T - dur))
        start = min(start, T - dur)
        depth = float(rng.uniform(cfg.compression_mmol * 0.5, cfg.compression_mmol))
        idx = np.arange(dur)
        ramp = np.clip(np.minimum(idx, dur - 1 - idx) / (dur / 2.0), 0.0, 1.0)  # triangular
        g[start:start + dur] -= depth * ramp
        mask[start:start + dur] = COMPRESSION


def _inject_dropouts(g, v, mask, rng, cfg, T):
    target = int(cfg.dropout_pct * T)
    placed, guard = 0, 0
    while placed < target and guard < 10000:
        guard += 1
        if cfg.gap_len_samples:
            length = int(rng.choice(cfg.gap_len_samples))
        else:
            length = int(np.exp(rng.normal(cfg.gap_len_mu, cfg.gap_len_sigma)))
        length = max(1, min(length, T // 4))
        start = int(rng.integers(0, T - length))
        end = start + length
        left = g[start - 1] if start > 0 else g[end]
        right = g[end] if end < T else g[start - 1]
        g[start:end] = np.linspace(left, right, length)
        v[start:end] = False
        mask[start:end] = DROPOUT
        placed += length


def apply_artifacts(glucose, valid, rng, cfg):
    """Return (glucose2, valid2, artifact_mask). intensity 0 → identity.

    glucose [T] mmol/L (1-min grid); valid [T] bool; rng a np.random.Generator;
    cfg an ArtifactConfig. artifact_mask is int8: 0=clean 1=dropout 2=jump
    3=compression. Insulin/carb channels are never touched (not passed in).
    """
    g = glucose.astype(np.float64).copy()
    v = valid.copy()
    mask = np.zeros(len(g), dtype=np.int8)
    if cfg.intensity <= 0:
        return g.astype(glucose.dtype), v, mask
    T = len(g)
    days = T / 1440.0
    _inject_jumps(g, mask, rng, cfg, days)
    _inject_compression(g, mask, rng, cfg, days, T)
    _inject_dropouts(g, v, mask, rng, cfg, T)
    np.clip(g, CGM_FLOOR, None, out=g)
    return g.astype(glucose.dtype), v, mask
