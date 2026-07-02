"""
Unit tests for the IOB/COB physiological feature transform (ml/features/iob_cob.py).

CPU-only, tiny arrays. Run from repo root:
    .venv/bin/pytest ml/tests/test_iob_cob.py -v
"""

import numpy as np
import pytest

from features.iob_cob import (
    _two_compartment, insulin_on_board, carbs_on_board, to_iob_cob,
    TAU_I, TAU_G, AG,
)


def _reference(u, tau, gain=1.0):
    """Explicit Python recursion the lfilter version must reproduce."""
    out = np.empty(len(u))
    s1 = s2 = 0.0
    a = 1.0 / tau
    for t in range(len(u)):
        out[t] = s1 + s2
        s1, s2 = s1 + gain * u[t] - s1 * a, s2 + s1 * a - s2 * a
    return out


class TestTwoCompartment:

    def test_matches_reference_recursion(self):
        u = np.random.default_rng(0).random(3000)
        np.testing.assert_allclose(_two_compartment(u, TAU_I), _reference(u, TAU_I), atol=1e-9)

    def test_gain_matches_reference(self):
        u = np.random.default_rng(1).random(1000)
        np.testing.assert_allclose(
            _two_compartment(u, TAU_G, gain=AG), _reference(u, TAU_G, AG), atol=1e-9
        )

    def test_zero_input_zero_output(self):
        assert not _two_compartment(np.zeros(500), TAU_I).any()

    def test_nonnegative_for_nonnegative_input(self):
        u = np.abs(np.random.default_rng(2).standard_normal(800))
        assert (_two_compartment(u, TAU_I) >= 0).all()

    def test_one_step_delay(self):
        # out[t] depends on u[0..t-1] → an impulse at t=0 yields out[0]==0
        u = np.zeros(50); u[0] = 1.0
        assert _two_compartment(u, TAU_I)[0] == 0.0
        assert _two_compartment(u, TAU_I)[1] > 0.0

    def test_decays_after_input_stops(self):
        u = np.zeros(2000); u[10] = 100.0
        out = _two_compartment(u, TAU_I)
        peak = out.argmax()
        assert out[peak] > out[-1]                      # decays toward 0
        assert out[-1] < 0.05 * out[peak]               # nearly gone after long tail

    def test_constant_input_steady_state(self):
        # constant u → steady state IOB = 2·u·tau (each compartment → u·tau)
        u = np.ones(4000)
        out = _two_compartment(u, TAU_I)
        np.testing.assert_allclose(out[-1], 2 * 1.0 * TAU_I, rtol=0.02)


class TestEncodingRobustness:
    """The reason IOB/COB exists: impulse vs spread inputs converge after the peak."""

    def test_impulse_vs_box_tail_converges(self):
        T = 600
        impulse = np.zeros(T); impulse[100] = 6300.0          # 6.3 U in 1 min
        box = np.zeros(T); box[100:103] = 6300.0 / 3          # same dose over 3 min
        a, b = insulin_on_board(impulse), insulin_on_board(box)
        # 15 min past delivery the curves are within 1% of the peak (raw differ by 100%)
        lag = 115
        assert np.abs(a[lag:] - b[lag:]).max() < 0.01 * a.max()
        # and the total integrals match (same dose in)
        assert abs(a.sum() - b.sum()) < 1e-3 * a.sum()


class TestToIobCob:

    def test_replaces_insulin_carb_keeps_glucose_and_flags(self):
        rng = np.random.default_rng(3)
        arr = rng.random((400, 8)).astype(np.float32)
        out = to_iob_cob(arr)
        np.testing.assert_array_equal(out[:, 0], arr[:, 0])          # glucose untouched
        np.testing.assert_array_equal(out[:, 3:], arr[:, 3:])        # flags untouched
        assert not np.allclose(out[:, 1], arr[:, 1])                 # insulin → IOB
        assert not np.allclose(out[:, 2], arr[:, 2])                 # carbs → COB

    def test_does_not_mutate_input(self):
        arr = np.ones((100, 8), dtype=np.float32)
        before = arr.copy()
        to_iob_cob(arr)
        np.testing.assert_array_equal(arr, before)

    def test_iob_uses_tau_i_cob_uses_tau_g(self):
        # COB has the Ag gain and a shorter tau → different curve from IOB on same input
        u = np.zeros(500); u[50] = 1000.0
        assert not np.allclose(insulin_on_board(u), carbs_on_board(u))
