"""
Unit tests for Week 2: PatchTST model, pretraining loss, and anomaly scoring.

All tests run on CPU with tiny tensors - no checkpoint or Parquet required.

Run from repo root:
    .venv/bin/pytest ml/tests/test_patch_tst.py -v
"""

import numpy as np
import pytest
import torch
import torch.nn as nn

from dataset import ANOMALY_CLASSES
from models.patch_tst.model import (
    PatchTST,
    PositionalEncoding,
    PATCH_LEN,
    N_PATCHES,
    D_MODEL,
)
from models.patch_tst.pretrain import masked_mse_loss
from models.patch_tst.anomaly_score import (
    calibrate_threshold,
    calibrate_per_patient,
    any_anomaly_label,
    auroc_per_class,
    auprc_per_class,
)

# -- shared constants ---------------------------------------------------------

B = 4        # batch size used in model tests
T = 120      # context window length (WINDOW_LEN)
C = 3        # number of input channels


# -- fixtures ---------------------------------------------------------------

@pytest.fixture
def model() -> PatchTST:
    torch.manual_seed(0)
    return PatchTST()


@pytest.fixture
def x() -> torch.Tensor:
    torch.manual_seed(1)
    return torch.randn(B, T, C)


# -- PositionalEncoding --------------------------------------------------------

class TestPositionalEncoding:

    def test_output_shape_unchanged(self):
        # PE adds a fixed vector to each token - shape must stay the same
        pe = PositionalEncoding(D_MODEL, N_PATCHES)
        x = torch.randn(B, N_PATCHES, D_MODEL)
        out = pe(x)
        assert out.shape == x.shape

    def test_pe_is_buffer_not_parameter(self):
        # PE must NOT be updated by the optimizer
        # Buffers appear in state_dict but not in parameters()
        pe = PositionalEncoding(D_MODEL, N_PATCHES)
        param_names = {name for name, _ in pe.named_parameters()}
        assert "pe" not in param_names, "pe should be a buffer, not a learned parameter"

    def test_pe_is_deterministic(self):
        # Two fresh instances must produce identical positional encodings
        pe1 = PositionalEncoding(D_MODEL, N_PATCHES)
        pe2 = PositionalEncoding(D_MODEL, N_PATCHES)
        torch.testing.assert_close(pe1.pe, pe2.pe)


# -- PatchTST ------------------------------------------------------------------

class TestPatchTST:

    def test_output_shape(self, model, x):
        # Reconstruction must match input shape exactly
        recon, _ = model(x, mask_ratio=0.0)
        assert recon.shape == (B, T, C), f"Expected {(B, T, C)}, got {recon.shape}"

    def test_mask_shape(self, model, x):
        # Mask is patch-level: one bool per patch per sample
        _, mask = model(x, mask_ratio=0.4)
        assert mask.shape == (B, N_PATCHES), f"Expected {(B, N_PATCHES)}, got {mask.shape}"

    def test_mask_is_bool(self, model, x):
        _, mask = model(x, mask_ratio=0.4)
        assert mask.dtype == torch.bool

    def test_no_mask_when_ratio_zero(self, model, x):
        # mask_ratio=0.0 -> no patches hidden -> mask is all False
        _, mask = model(x, mask_ratio=0.0)
        assert not mask.any(), "Expected no masked patches when mask_ratio=0.0"

    def test_mask_count_with_ratio(self, model, x):
        # mask_ratio=0.4 on 6 patches -> floor(6 * 0.4) = 2 patches masked per sample
        torch.manual_seed(42)
        _, mask = model(x, mask_ratio=0.4)
        expected_n_masked = max(1, int(N_PATCHES * 0.4))  # = 2
        for b in range(B):
            n = mask[b].sum().item()
            assert n == expected_n_masked, (
                f"Sample {b}: expected {expected_n_masked} masked patches, got {n}"
            )

    def test_fixed_mask_returned_verbatim(self, model, x):
        # fixed_mask [n_patches] broadcasts to the batch and is returned unchanged
        fixed = torch.zeros(N_PATCHES, dtype=torch.bool)
        fixed[-1] = True
        _, mask = model(x, fixed_mask=fixed)
        assert mask.shape == (B, N_PATCHES)
        for b in range(B):
            assert mask[b, -1].item() is True or mask[b, -1].item() == 1
            assert mask[b, :-1].sum().item() == 0

    def test_fixed_mask_changes_masked_patch_output(self, model, x):
        # Hiding the last patch must change its reconstruction vs no masking -
        # proves the mask token actually replaces the patch (not dead code).
        torch.manual_seed(0)
        recon_open, _ = model(x, mask_ratio=0.0)
        fixed = torch.zeros(N_PATCHES, dtype=torch.bool)
        fixed[-1] = True
        recon_masked, _ = model(x, fixed_mask=fixed)
        last_start = (N_PATCHES - 1) * 20
        diff = (recon_masked[:, last_start:, :] - recon_open[:, last_start:, :]).abs().max()
        assert diff > 1e-6, "Masking the last patch did not change its output"

    def test_output_dtype_is_float32(self, model, x):
        recon, _ = model(x, mask_ratio=0.0)
        assert recon.dtype == torch.float32

    def test_channel_independence(self, model):
        # PatchTST processes channels separately with shared weights.
        # The reconstruction of channel 0 must not change when channel 1 is altered,
        # because no attention crosses channel boundaries.
        torch.manual_seed(5)
        model.eval()
        x_base = torch.randn(1, T, C)
        x_alt  = x_base.clone()
        x_alt[:, :, 1] = x_alt[:, :, 1] * 99  # drastically change channel 1

        with torch.no_grad():
            recon_base, _ = model(x_base, mask_ratio=0.0)
            recon_alt,  _ = model(x_alt,  mask_ratio=0.0)

        # channel 0 reconstruction must be identical in both cases
        torch.testing.assert_close(
            recon_base[:, :, 0], recon_alt[:, :, 0],
            msg="Channel 0 reconstruction changed when channel 1 was modified - "
                "channel independence violated"
        )

    def test_reconstruction_differs_from_input(self, model, x):
        # A randomly initialised model won't reconstruct perfectly - recon != x
        model.eval()
        with torch.no_grad():
            recon, _ = model(x, mask_ratio=0.0)
        assert not torch.allclose(recon, x), (
            "Reconstruction equals input on random init - likely a passthrough bug"
        )


# -- masked_mse_loss ----------------------------------------------------------

class TestMaskedMSELoss:

    def test_returns_scalar_tensor(self):
        recon  = torch.randn(B, T, C)
        target = torch.randn(B, T, C)
        mask   = torch.ones(B, N_PATCHES, dtype=torch.bool)
        loss   = masked_mse_loss(recon, target, mask)
        assert loss.shape == torch.Size([]), "Loss must be a scalar (0-dim tensor)"

    def test_zero_when_recon_equals_target(self):
        # If the model reconstructs perfectly, loss must be 0 for any mask
        x    = torch.randn(B, T, C)
        mask = torch.ones(B, N_PATCHES, dtype=torch.bool)
        loss = masked_mse_loss(x, x, mask)
        assert loss.item() == pytest.approx(0.0, abs=1e-6)

    def test_all_false_mask_returns_zero(self):
        # No patches masked -> nothing to score -> loss = 0
        recon  = torch.randn(B, T, C)
        target = torch.zeros(B, T, C)
        mask   = torch.zeros(B, N_PATCHES, dtype=torch.bool)   # all False
        loss   = masked_mse_loss(recon, target, mask)
        assert loss.item() == pytest.approx(0.0, abs=1e-6)

    def test_all_true_mask_equals_standard_mse(self):
        # Full mask -> loss must equal nn.functional.mse_loss(recon, target)
        torch.manual_seed(7)
        recon  = torch.randn(B, T, C)
        target = torch.randn(B, T, C)
        mask   = torch.ones(B, N_PATCHES, dtype=torch.bool)

        loss_masked   = masked_mse_loss(recon, target, mask)
        loss_standard = nn.functional.mse_loss(recon, target)

        assert loss_masked.item() == pytest.approx(loss_standard.item(), rel=1e-4)

    def test_only_masked_patches_contribute(self):
        # Patch 0 differs from target; patch 0 is the ONLY masked patch.
        # All other patches are identical to target -> loss must be > 0.
        # Then mask patch 1 instead -> loss must be 0 (patch 0 diff is not masked).
        recon  = torch.zeros(B, T, C)
        target = torch.zeros(B, T, C)

        # Make patch 0 (minutes 0-19) differ
        recon[:, :PATCH_LEN, :] = 1.0

        # Mask only patch 0
        mask_patch0 = torch.zeros(B, N_PATCHES, dtype=torch.bool)
        mask_patch0[:, 0] = True
        loss_patch0_masked = masked_mse_loss(recon, target, mask_patch0)
        assert loss_patch0_masked.item() > 0, "Expected non-zero loss when differing patch is masked"

        # Mask only patch 1 (minutes 20-39, which are identical)
        mask_patch1 = torch.zeros(B, N_PATCHES, dtype=torch.bool)
        mask_patch1[:, 1] = True
        loss_patch1_masked = masked_mse_loss(recon, target, mask_patch1)
        assert loss_patch1_masked.item() == pytest.approx(0.0, abs=1e-6), (
            "Expected zero loss when masking a patch where recon == target"
        )

    def test_loss_is_non_negative(self):
        recon  = torch.randn(B, T, C)
        target = torch.randn(B, T, C)
        mask   = torch.randint(0, 2, (B, N_PATCHES)).bool()
        loss   = masked_mse_loss(recon, target, mask)
        assert loss.item() >= 0.0


# -- calibrate_threshold ------------------------------------------------------

class TestCalibrateThreshold:

    def test_returns_float(self):
        scores = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        result = calibrate_threshold(scores, n_cal_windows=5)
        assert isinstance(result, float)

    def test_threshold_above_median(self):
        # threshold = median + positive offset -> always > median
        rng = np.random.default_rng(0)
        scores = rng.normal(loc=1.0, scale=0.3, size=500).astype(np.float32)
        threshold = calibrate_threshold(scores, n_cal_windows=500)
        assert threshold > float(np.median(scores))

    def test_uses_only_n_cal_windows(self):
        # First 10 scores are near 0, next 100 are near 100.
        # With n_cal=10 the threshold should be low; with n_cal=110 it should be high.
        scores = np.concatenate([
            np.zeros(10, dtype=np.float32),
            np.full(100, 100.0, dtype=np.float32),
        ])
        thresh_small = calibrate_threshold(scores, n_cal_windows=10)
        thresh_large = calibrate_threshold(scores, n_cal_windows=110)
        assert thresh_small < 1.0,   f"Expected low threshold from normal window, got {thresh_small}"
        assert thresh_large > 50.0,  f"Expected high threshold from anomaly window, got {thresh_large}"

    def test_constant_scores_does_not_crash(self):
        # std is 0 -> clamped to 1e-6 -> threshold = constant + 2e-6
        scores = np.ones(100, dtype=np.float32)
        result = calibrate_threshold(scores, n_cal_windows=100)
        assert result == pytest.approx(1.0, abs=1e-4)

    def test_robust_to_outliers(self):
        # Insert a few very large outliers into the calibration window.
        # Median+IQR threshold should stay near the bulk of the data.
        rng = np.random.default_rng(3)
        scores = rng.normal(1.0, 0.2, size=200).astype(np.float32)
        scores_with_outliers = scores.copy()
        scores_with_outliers[:5] = 1000.0   # 5 extreme outliers

        thresh_clean    = calibrate_threshold(scores,               n_cal_windows=200)
        thresh_outliers = calibrate_threshold(scores_with_outliers, n_cal_windows=200)

        # Threshold should not shift drastically due to 5/200 outliers
        assert abs(thresh_outliers - thresh_clean) < 2.0, (
            f"Threshold shifted too much with outliers: "
            f"clean={thresh_clean:.3f}, with outliers={thresh_outliers:.3f}"
        )


# -- any_anomaly_label ---------------------------------------------------------

class TestAnyAnomalyLabel:
    def test_or_of_classes(self):
        n = 6
        labels = {cls: np.zeros(n, np.float32) for cls in ANOMALY_CLASSES}
        labels["missed"][0] = 1.0
        labels["late"][1]   = 1.0
        labels["large"][1]  = 1.0   # overlapping classes on same window
        any_lbl = any_anomaly_label(labels)
        np.testing.assert_array_equal(any_lbl, [1, 1, 0, 0, 0, 0])

    def test_all_zero_gives_all_zero(self):
        labels = {cls: np.zeros(4, np.float32) for cls in ANOMALY_CLASSES}
        assert any_anomaly_label(labels).sum() == 0

    def test_dtype_float32(self):
        labels = {cls: np.zeros(3, np.float32) for cls in ANOMALY_CLASSES}
        labels["anaerobic"][2] = 1.0
        assert any_anomaly_label(labels).dtype == np.float32


# -- calibrate_per_patient -----------------------------------------------------

class TestCalibratePerPatient:

    def test_each_patient_uses_own_baseline(self):
        # Patient A: low baseline (~1) with a spike at the end.
        # Patient B: high baseline (~100), no anomaly.
        # A global threshold from A's baseline would flag ALL of B.
        # Per-patient must flag A's spike and leave B's high-but-normal scores alone.
        a = np.concatenate([np.ones(50, np.float32), np.full(10, 20.0, np.float32)])
        b = np.full(60, 100.0, np.float32)
        scores = np.concatenate([a, b])
        counts = [("A", 60), ("B", 60)]

        flagged, pct = calibrate_per_patient(scores, counts, n_cal_windows=50)

        assert flagged[50:60].all(), "A's spike windows should be flagged"
        assert not flagged[60:].any(), "B's constant baseline must not be flagged"
        assert pct == pytest.approx(100 * 10 / 120, abs=1e-6)

    def test_short_patient_calibrates_on_all_windows(self):
        # Patient has fewer windows than n_cal_windows -> calibrate on all of them.
        scores = np.concatenate([np.ones(20, np.float32), np.full(5, 50.0, np.float32)])
        counts = [("short", 25)]
        flagged, _ = calibrate_per_patient(scores, counts, n_cal_windows=7200)
        assert flagged[20:].all()       # the 5 spikes
        assert not flagged[:20].any()   # the flat baseline

    def test_flagged_length_matches_scores(self):
        scores = np.random.default_rng(0).normal(1.0, 0.2, size=300).astype(np.float32)
        counts = [("p1", 100), ("p2", 100), ("p3", 100)]
        flagged, _ = calibrate_per_patient(scores, counts, n_cal_windows=50)
        assert flagged.shape == scores.shape


# - auroc_per_class / auprc_per_class ----------------------------------------

def _make_labels(n: int, positive_class: str, frac: float = 0.1, seed: int = 0) -> dict[str, np.ndarray]:
    """Binary label dict. Only `positive_class` has any 1s."""
    rng = np.random.default_rng(seed)
    labels = {cls: np.zeros(n, dtype=np.float32) for cls in ANOMALY_CLASSES}
    n_pos = max(1, int(n * frac))
    idx   = rng.choice(n, size=n_pos, replace=False)
    labels[positive_class][idx] = 1.0
    return labels


class TestAUROCAndAUPRC:

    def test_nan_when_no_positives(self):
        # A class with zero positive windows -> both metrics must return nan
        n = 200
        scores = np.random.default_rng(0).random(n).astype(np.float32)
        labels = {cls: np.zeros(n, dtype=np.float32) for cls in ANOMALY_CLASSES}

        auroc = auroc_per_class(scores, labels)
        auprc = auprc_per_class(scores, labels)

        for cls in ANOMALY_CLASSES:
            assert np.isnan(auroc[cls]), f"auroc[{cls}] should be nan, got {auroc[cls]}"
            assert np.isnan(auprc[cls]), f"auprc[{cls}] should be nan, got {auprc[cls]}"

    def test_returns_all_anomaly_classes(self):
        n = 100
        scores = np.random.default_rng(1).random(n).astype(np.float32)
        labels = _make_labels(n, positive_class="missed")

        auroc = auroc_per_class(scores, labels)
        auprc = auprc_per_class(scores, labels)

        assert set(auroc.keys()) == set(ANOMALY_CLASSES)
        assert set(auprc.keys()) == set(ANOMALY_CLASSES)

    def test_perfect_separation_auroc(self):
        # Anomalies always have higher score than normals -> AUROC = 1.0
        n = 200
        labels   = _make_labels(n, positive_class="missed", frac=0.2)
        scores   = labels["missed"].copy()   # score = 1 for positives, 0 for normals

        auroc = auroc_per_class(scores, labels)
        assert auroc["missed"] == pytest.approx(1.0, abs=1e-6)

    def test_perfect_separation_auprc(self):
        n = 200
        labels   = _make_labels(n, positive_class="large", frac=0.2)
        scores   = labels["large"].copy()

        auprc = auprc_per_class(scores, labels)
        assert auprc["large"] == pytest.approx(1.0, abs=1e-6)

    def test_random_scores_auroc_near_half(self):
        # Random scores -> AUROC should be near 0.5 (not strict: 0.3-0.7 range)
        rng    = np.random.default_rng(99)
        n      = 2000
        scores = rng.random(n).astype(np.float32)
        labels = _make_labels(n, positive_class="late", frac=0.1, seed=99)

        auroc = auroc_per_class(scores, labels)
        assert 0.3 < auroc["late"] < 0.7, (
            f"Expected AUROC near 0.5 for random scores, got {auroc['late']:.4f}"
        )

    def test_auprc_random_baseline_near_prevalence(self):
        # Random scores -> AUPRC ~ prevalence, not 0.5
        rng        = np.random.default_rng(42)
        n          = 2000
        frac       = 0.05
        scores     = rng.random(n).astype(np.float32)
        labels     = _make_labels(n, positive_class="anaerobic", frac=frac, seed=42)
        prevalence = labels["anaerobic"].mean()

        auprc = auprc_per_class(scores, labels)
        # Allow generous tolerance - small n, but should be in the same ballpark
        assert abs(auprc["anaerobic"] - prevalence) < 0.1, (
            f"AUPRC={auprc['anaerobic']:.4f} far from prevalence={prevalence:.4f}"
        )
