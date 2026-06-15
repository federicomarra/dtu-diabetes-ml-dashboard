"""
Unit tests for the combined inference path (ml/inference/diary.py).

Uses a FAKE detector (forecast = 0 → residual = mean target²) so the diary logic
is testable without trained checkpoints; the head is the real (untrained) module.
Run from repo root:
    .venv/bin/pytest ml/tests/test_diary.py -v
"""

import numpy as np
import torch

from inference.diary import build_diary, Event
from models.xchannel.model import HORIZON, CONTEXT_LEN
from characterization.head import CharacterizationHead, fit_ood, CLASSES
from characterization.rules import RuleConfig


class FakeDetector:
    """forecast = zeros (residual = mean target²); embedding = ones."""
    def __call__(self, glu, ins, car, return_embeddings=False):
        B = glu.shape[0]
        return torch.ones(B, 128) if return_embeddings else torch.zeros(B, HORIZON)
    def eval(self):
        pass


def _setup(bump=True):
    T = 400
    arr = np.zeros((T, 8), dtype=np.float32)
    if bump:
        arr[200:240, 0] = 5.0                 # glucose excursion → high residual
    valid = np.ones(T, dtype=bool)
    head = CharacterizationHead()
    mu, inv_cov = fit_ood(np.random.default_rng(0).standard_normal((500, 128)))
    return arr, valid, head, mu, inv_cov


def _diary(arr, valid, head, mu, inv_cov, **kw):
    return build_diary(arr, valid, detector=FakeDetector(), head=head,
                       ood_mu=mu, ood_inv_cov=inv_cov, stride=5, mc_passes=5, **kw)


def test_detects_event_on_excursion():
    events = _diary(*_setup(bump=True))
    assert len(events) >= 1
    e = events[0]
    assert isinstance(e, Event)
    assert e.anomaly_score > 0
    assert e.duration_min > 0


def test_no_event_on_flat_signal():
    assert _diary(*_setup(bump=False)) == []


def test_soft_label_and_probs():
    e = _diary(*_setup())[0]
    assert e.soft_label in CLASSES
    assert abs(sum(e.class_probs.values()) - 1.0) < 1e-4
    assert e.mc_uncertainty >= 0


def test_ood_radius_controls_flag():
    arr, valid, head, mu, inv_cov = _setup()
    assert _diary(arr, valid, head, mu, inv_cov, ood_radius=0.0)[0].ood_flag is True
    assert _diary(arr, valid, head, mu, inv_cov, ood_radius=float("inf"))[0].ood_flag is False


def test_rule_label_wired_from_logs():
    arr, valid, head, mu, inv_cov = _setup()
    # a logged meal in the event window with NO bolus → rule says "missed"
    meals = [type("M", (), {"minute": 210, "carb_g": 40.0})()]
    boluses = []   # none → missed
    e = _diary(arr, valid, head, mu, inv_cov, meals=meals, boluses=boluses,
               rule_cfg=RuleConfig())[0]
    assert e.rule_label == "missed"


def test_rule_label_none_without_inputs():
    e = _diary(*_setup())[0]              # no meals/boluses passed
    assert e.rule_label is None


def test_min_event_duration_drops_short_events():
    arr, valid, head, mu, inv_cov = _setup()
    assert _diary(arr, valid, head, mu, inv_cov, min_event_min=10_000) == []


def test_low_confidence_is_uncharacterised():
    # impossible confidence floor → label withheld → to_text says 'uncharacterised'
    e = _diary(*_setup(), min_confidence=1.1)[0]
    assert e.characterised is False
    assert "uncharacterised" in e.to_text()


def test_rule_label_leads_in_text():
    arr, valid, head, mu, inv_cov = _setup()
    meals = [type("M", (), {"minute": 210, "carb_g": 40.0})()]
    e = _diary(arr, valid, head, mu, inv_cov, meals=meals, boluses=[])[0]
    assert "(rule)" in e.to_text() and "missed" in e.to_text()


def test_higher_threshold_k_flags_no_more():
    arr, valid, head, mu, inv_cov = _setup()
    loose = len(_diary(arr, valid, head, mu, inv_cov, threshold_k=2.0))
    strict = len(_diary(arr, valid, head, mu, inv_cov, threshold_k=6.0))
    assert strict <= loose
