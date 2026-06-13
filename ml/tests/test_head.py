"""
Unit tests for the characterization head (ml/characterization/head.py).

CPU-only, tiny tensors. Run from repo root:
    .venv/bin/pytest ml/tests/test_head.py -v
"""

import numpy as np
import pytest
import torch

from characterization.head import (
    CharacterizationHead, mc_predict, fit_ood, ood_distance,
    window_class, CLASSES, N_CLASSES,
)


class TestWindowClass:

    def test_normal_when_no_flags(self):
        assert window_class({c: 0.0 for c in CLASSES[1:]}) == 0

    def test_single_class(self):
        assert window_class({"missed": 0, "late": 0, "large": 1.0,
                             "prolonged": 0, "anaerobic": 0}) == CLASSES.index("large")

    def test_precedence_missed_over_late(self):
        # both present → missed wins (higher precedence)
        assert window_class({"missed": 1.0, "late": 1.0, "large": 0,
                             "prolonged": 0, "anaerobic": 0}) == CLASSES.index("missed")

    def test_array_form(self):
        # [missed, late, large, prolonged, anaerobic]
        assert window_class(np.array([0, 0, 0, 0, 1.0])) == CLASSES.index("anaerobic")


class TestHead:

    def test_forward_shape(self):
        head = CharacterizationHead()
        out = head(torch.randn(8, 128))
        assert out.shape == (8, N_CLASSES)

    def test_mc_predict_probs_and_uncertainty(self):
        torch.manual_seed(0)
        head = CharacterizationHead(dropout=0.5)
        z = torch.randn(16, 128)
        mean, unc = mc_predict(head, z, n_passes=20)
        assert mean.shape == (16, N_CLASSES)
        torch.testing.assert_close(mean.sum(-1), torch.ones(16), atol=1e-5, rtol=1e-4)
        assert unc.shape == (16,)
        assert (unc > 0).all(), "dropout should make MC passes disagree → nonzero uncertainty"

    def test_mc_predict_restores_mode(self):
        head = CharacterizationHead()
        head.eval()
        mc_predict(head, torch.randn(4, 128), n_passes=5)
        assert not head.training, "mc_predict must restore the original train/eval mode"


class TestOOD:

    def test_normal_centroid_near_zero_distance(self):
        rng = np.random.default_rng(0)
        normal = rng.standard_normal((2000, 16))
        mu, inv_cov = fit_ood(normal)
        # distance at the mean is ~0; distances are non-negative
        assert ood_distance(mu[None, :], mu, inv_cov)[0] < 1e-6
        assert (ood_distance(normal, mu, inv_cov) >= 0).all()

    def test_far_point_has_larger_distance(self):
        rng = np.random.default_rng(1)
        normal = rng.standard_normal((2000, 16))
        mu, inv_cov = fit_ood(normal)
        near = ood_distance(normal, mu, inv_cov).mean()
        far = ood_distance((mu + 10.0)[None, :], mu, inv_cov)[0]
        assert far > near
