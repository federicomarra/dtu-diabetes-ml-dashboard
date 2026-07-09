"""Baseline calibration + serving score mode for the inference detector."""
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).parent.parent))
from models.patch_tst.anomaly_score import calibrate_threshold, robust_baseline  # noqa: E402
from inference.detect import detect, score_windows  # noqa: E402
from models.xchannel.model import CONTEXT_LEN, HORIZON  # noqa: E402

WIN = CONTEXT_LEN + HORIZON


def _scores_with_anomalies_at(where: str, n=2000, n_anom=60, seed=0):
    """Normal-ish scores plus a block of large anomalies placed early or late."""
    rng = np.random.default_rng(seed)
    s = rng.normal(0.0, 1.0, n)
    idx = slice(50, 50 + n_anom) if where == "early" else slice(n - 110, n - 110 + n_anom)
    s[idx] += 25.0
    return s


def test_robust_baseline_is_invariant_to_when_anomalies_occur():
    """The old calibration fit only the FIRST n windows, so a patient whose anomalies
    land in the calibration period got a different (inflated) threshold than the same
    patient whose anomalies land later. Calibrating on all windows removes that."""
    early = _scores_with_anomalies_at("early")
    late = _scores_with_anomalies_at("late")

    _, _, thr_early = robust_baseline(early, k=2.0)
    _, _, thr_late = robust_baseline(late, k=2.0)
    assert thr_early == pytest.approx(thr_late, rel=0.05)


def test_old_calibration_did_depend_on_when_anomalies_occur():
    """Characterises the bug this replaces (guards against silently reverting)."""
    n_cal = 400
    thr_early = calibrate_threshold(_scores_with_anomalies_at("early"), n_cal, k=2.0)
    thr_late = calibrate_threshold(_scores_with_anomalies_at("late"), n_cal, k=2.0)
    assert thr_early > thr_late * 1.2


def test_trimming_recovers_the_clean_scale():
    """sigma must describe NORMAL windows. With 3% of windows 25 sigma out, an untrimmed
    fit still absorbs them into the spread; the trimmed fit matches the clean data."""
    rng = np.random.default_rng(1)
    clean = rng.normal(0.0, 1.0, 2000)
    dirty = clean.copy()
    dirty[:60] += 25.0

    med_c, sig_c, _ = robust_baseline(clean, k=2.0)
    med_d, sig_d, _ = robust_baseline(dirty, k=2.0)
    assert med_d == pytest.approx(med_c, abs=0.1)
    assert sig_d == pytest.approx(sig_c, rel=0.15)


def test_robust_baseline_keeps_a_majority_of_windows():
    """Trimming must never eat the distribution: a pathological all-tail input still
    leaves a defined scale rather than collapsing sigma to the floor."""
    s = np.concatenate([np.zeros(10), np.linspace(0, 100, 90)])
    med, sigma, thr = robust_baseline(s, k=2.0)
    assert sigma > 0 and np.isfinite(thr) and thr > med


class _StubForecaster:
    """Predicts a flat zero mean with unit variance; the target carries the signal."""

    def __call__(self, glu, ins, carb):
        b = glu.shape[0]
        return torch.zeros(b, HORIZON), torch.zeros(b, HORIZON)


def _ramp_window(n_win=6):
    """arr[T,8] where glucose ramps up late in each horizon -> 'end' should out-score 'sym'."""
    T = WIN + (n_win - 1) * 5
    arr = np.zeros((T, 8), np.float32)
    t = np.arange(T)
    arr[:, 0] = np.where(t > CONTEXT_LEN, (t - CONTEXT_LEN) * 0.05, 0.0)
    return arr, np.ones(T, bool)


def test_score_mode_is_threaded_through_to_the_scorer():
    arr, valid = _ramp_window()
    det = _StubForecaster()
    _, s_sym = score_windows(arr, valid, det, torch.device("cpu"), 5, score_mode="sym")
    _, s_end = score_windows(arr, valid, det, torch.device("cpu"), 5, score_mode="end")
    assert not np.allclose(s_sym, s_end)


def test_detect_defaults_to_end_mode():
    """`end` beat `sym` on both the simulator and OhioT1DM (missed AUPRC +21% on real
    data), so it is the serving default."""
    arr, valid = _ramp_window()
    det = _StubForecaster()
    _, scores_default = detect(arr, valid, detector=det)
    _, scores_end = detect(arr, valid, detector=det, score_mode="end")
    assert np.allclose(scores_default, scores_end)
