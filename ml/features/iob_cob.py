"""
Physiological feature transforms: insulin-on-board (IOB) and carbs-on-board (COB).

Why: raw insulin/carb channels are encoded differently across datasets (the
simulator spreads a bolus over 3 min and announces carbs as a box; OhioT1DM logs
them as near-impulses). A model trained on one raw encoding does not transfer
(see ml/ohio_eval). IOB/COB are convolutions of the delivery with a smooth,
multi-hour decay kernel, so the fine encoding (impulse vs box) washes out — the
same physiological "amount still active" curve results either way. This is the
standard input representation for glucose models (Loop, OpenAPS, Hovorka).

We reuse the simulator's OWN two-compartment dynamics (from
dtu-mt-patient-generator), so a model trained on these features matches the
generator's internal insulin/carb kinetics exactly:

  IOB:  S1' = u    − S1/tauI ;  S2' = (S1 − S2)/tauI ;  IOB = S1 + S2
        (simulation_control.estimate_iob_from_state: iob = (x[2]+x[3]))
  COB:  D1' = Ag·d − D1/tauG ;  D2' = (D1 − D2)/tauG ;  COB = D1 + D2
        (model.py gut compartments; Ag = carb bioavailability)

Population means (parameters.py): tauI 55.871 min, tauG 39.908 min, Ag 0.7943.
Discrete 1-min forward-Euler — the SAME kernel must be applied to every dataset.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

TAU_I = 55.871     # min — insulin absorption time constant
TAU_G = 39.908     # min — glucose (carb) absorption time constant
AG = 0.7943        # carb bioavailability


def _two_compartment(u: np.ndarray, tau: float, gain: float = 1.0) -> np.ndarray:
    """Sum of two cascaded leaky integrators driven by u (1-min Euler).

    s1[t] = (1-1/tau)·s1[t-1] + gain·u[t-1]
    s2[t] = (1-1/tau)·s2[t-1] + (1/tau)·s1[t-1]
    returns s1 + s2  (the "on-board" amount in the same units·min as u).

    Each compartment is a first-order IIR filter, so the cascade is computed
    with scipy.signal.lfilter (C-speed) instead of a Python loop — essential at
    12k patients × ~20k minutes. The leading [0, ·] numerator gives the one-step
    delay (out[t] depends on u[0..t-1]).
    """
    u = np.asarray(u, dtype=np.float64)
    a = 1.0 / tau
    pole = [1.0, -(1.0 - a)]
    s1 = lfilter([0.0, gain], pole, u)
    s2 = lfilter([0.0, a], pole, s1)
    return s1 + s2


def insulin_on_board(insulin_rate: np.ndarray, tau: float = TAU_I) -> np.ndarray:
    """IOB from a per-minute insulin delivery rate (basal + bolus)."""
    return _two_compartment(np.asarray(insulin_rate, dtype=np.float64), tau)


def carbs_on_board(carb_rate: np.ndarray, tau: float = TAU_G, ag: float = AG) -> np.ndarray:
    """COB from a per-minute announced-carb rate."""
    return _two_compartment(np.asarray(carb_rate, dtype=np.float64), tau, gain=ag)


def to_iob_cob(arr: np.ndarray) -> np.ndarray:
    """
    Replace the raw insulin/carb channels with IOB/COB in a [T, C] (or [T, 8])
    array whose columns 0,1,2 are glucose, insulin_rate, carb_rate. Glucose and
    any trailing flag columns are passed through untouched. Returns a copy.
    """
    out = arr.astype(np.float32).copy()
    out[:, 1] = insulin_on_board(arr[:, 1]).astype(np.float32)
    out[:, 2] = carbs_on_board(arr[:, 2]).astype(np.float32)
    return out
