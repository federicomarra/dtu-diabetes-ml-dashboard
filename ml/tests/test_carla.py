"""
Unit tests for CARLA: ContrastiveDataset, ContrastiveBatchSampler,
CARLAModel, SupCon loss, and anomaly scoring (fit_gmm, score_with_gmm,
embed_dataset).

All tests run on CPU with synthetic data — no checkpoint or Parquet required.

Run from repo root:
    .venv/bin/pytest ml/tests/test_carla.py -v
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).parent.parent))

from torch.utils.data import DataLoader

from dataset import WINDOW_LEN, N_CHANNELS, ANOMALY_CLASSES
from models.carla.anomaly_score import fit_gmm, score_with_gmm, embed_dataset
from models.patch_tst.model import PatchTST, D_MODEL
from models.carla.dataset import ContrastiveDataset, ContrastiveBatchSampler
from models.carla.model import CARLAModel, PROJ_DIM
from models.carla.pretrain import supcon_loss

# ── synthetic patient data ────────────────────────────────────────────────────

def _make_patient_data(
    n_patients: int = 5,
    n_minutes:  int = 2880,   # 2 days
    anomaly_frac: float = 0.02,   # low rate → many 120-min windows are all-zero (normal)
    seed: int = 0,
) -> dict[str, np.ndarray]:
    """
    Synthetic [T, 8] arrays: cols 0-2 signals, cols 3-7 binary anomaly flags.
    anomaly_frac fraction of rows have at least one flag set.
    """
    rng = np.random.default_rng(seed)
    data: dict[str, np.ndarray] = {}
    for i in range(n_patients):
        signals = rng.standard_normal((n_minutes, N_CHANNELS)).astype(np.float32)
        flags   = np.zeros((n_minutes, len(ANOMALY_CLASSES)), dtype=np.float32)
        # Mark anomaly_frac of rows — keep low so 120-min windows can be all-zero
        n_anomaly = int(n_minutes * anomaly_frac)
        rows = rng.choice(n_minutes, n_anomaly, replace=False)
        cols = rng.integers(0, len(ANOMALY_CLASSES), n_anomaly)
        flags[rows, cols] = 1.0
        data[f"p{i:03d}"] = np.concatenate([signals, flags], axis=1)
    return data


# ── ContrastiveDataset ────────────────────────────────────────────────────────

class TestContrastiveDataset:

    @pytest.fixture
    def data(self):
        return _make_patient_data()

    @pytest.fixture
    def ds(self, data):
        return ContrastiveDataset(data, stride=60)

    def test_len_equals_normal_plus_anomaly(self, ds):
        assert len(ds) == ds.n_normal + ds.n_anomaly

    def test_has_both_normal_and_anomaly(self, ds):
        assert ds.n_normal  > 0, "expected normal windows"
        assert ds.n_anomaly > 0, "expected anomaly windows"

    def test_window_shape(self, ds):
        x, label = ds[0]
        assert x.shape == (WINDOW_LEN, N_CHANNELS)

    def test_window_dtype(self, ds):
        x, _ = ds[0]
        assert x.dtype == torch.float32

    def test_normal_label_is_one(self, ds):
        # First n_normal entries are normal
        _, label = ds[0]
        assert label == 1

    def test_anomaly_label_is_zero(self, ds):
        # Entries after n_normal are anomalies
        _, label = ds[ds.n_normal]
        assert label == 0

    def test_normal_windows_have_no_flags(self, data, ds):
        # Verify: every window labelled normal truly has all-zero flags in raw data
        for i in range(min(10, ds.n_normal)):
            pid   = ds._pids[ds._normal_pid_idx[i]]
            start = int(ds._normal_starts[i])
            arr = data[pid][start : start + WINDOW_LEN, 3:]
            assert arr.max() == 0.0, f"Normal window {pid}@{start} has anomaly flags set"

    def test_anomaly_windows_have_at_least_one_flag(self, data, ds):
        # Verify: every window labelled anomaly has at least one flag set
        for i in range(min(10, ds.n_anomaly)):
            pid   = ds._pids[ds._anomaly_pid_idx[i]]
            start = int(ds._anomaly_starts[i])
            arr = data[pid][start : start + WINDOW_LEN, 3:]
            assert arr.max() > 0.0, f"Anomaly window {pid}@{start} has no flags set"

    def test_normal_by_patient_covers_all_normals(self, ds):
        # normal_by_patient should contain exactly the same starts as the normal pool
        from_index = set(
            (ds._pids[p], int(s))
            for p, s in zip(ds._normal_pid_idx, ds._normal_starts)
        )
        from_lookup = set(
            (pid, int(start))
            for pid, starts in ds.normal_by_patient.items()
            for start in starts
        )
        assert from_index == from_lookup

    def test_stride_controls_window_count(self, data):
        ds_s15 = ContrastiveDataset(data, stride=15)
        ds_s60 = ContrastiveDataset(data, stride=60)
        assert len(ds_s15) > len(ds_s60)


# ── ContrastiveBatchSampler ───────────────────────────────────────────────────

class TestContrastiveBatchSampler:

    @pytest.fixture
    def ds(self):
        return ContrastiveDataset(_make_patient_data(), stride=60)

    def test_batch_size(self, ds):
        sampler = ContrastiveBatchSampler(ds, batch_size=16, normal_ratio=0.75)
        batch = next(iter(sampler))
        assert len(batch) == 16

    def test_normal_ratio(self, ds):
        batch_size   = 20
        normal_ratio = 0.7
        sampler      = ContrastiveBatchSampler(ds, batch_size=batch_size, normal_ratio=normal_ratio)
        n_normal_expected  = int(batch_size * normal_ratio)   # 14
        n_anomaly_expected = batch_size - n_normal_expected   # 6

        for batch in sampler:
            n_normal  = sum(1 for idx in batch if idx < ds.n_normal)
            n_anomaly = sum(1 for idx in batch if idx >= ds.n_normal)
            assert n_normal  == n_normal_expected
            assert n_anomaly == n_anomaly_expected
            break

    def test_all_indices_in_range(self, ds):
        sampler = ContrastiveBatchSampler(ds, batch_size=16)
        for batch in sampler:
            assert all(0 <= idx < len(ds) for idx in batch)

    def test_no_duplicate_normals_within_batch(self, ds):
        # Normal indices in the batch should be unique (drawn without replacement from pool)
        sampler = ContrastiveBatchSampler(ds, batch_size=16, normal_ratio=0.75)
        for batch in sampler:
            normal_in_batch = [idx for idx in batch if idx < ds.n_normal]
            assert len(normal_in_batch) == len(set(normal_in_batch))
            break

    def test_len_equals_n_full_batches(self, ds):
        batch_size   = 16
        normal_ratio = 0.75
        sampler = ContrastiveBatchSampler(ds, batch_size=batch_size, normal_ratio=normal_ratio)
        n_per_batch = int(batch_size * normal_ratio)
        expected_len = ds.n_normal // n_per_batch
        assert len(sampler) == expected_len


# ── CARLAModel ────────────────────────────────────────────────────────────────

B = 4
T = 120
C = 3


class TestCARLAModel:

    @pytest.fixture
    def model(self):
        torch.manual_seed(0)
        return CARLAModel()

    @pytest.fixture
    def x(self):
        torch.manual_seed(1)
        return torch.randn(B, T, C)

    def test_forward_returns_two_tensors(self, model, x):
        out = model(x)
        assert len(out) == 2

    def test_z_shape(self, model, x):
        z, _ = model(x)
        assert z.shape == (B, D_MODEL)

    def test_z_proj_shape(self, model, x):
        _, z_proj = model(x)
        assert z_proj.shape == (B, PROJ_DIM)

    def test_z_proj_is_l2_normalised(self, model, x):
        _, z_proj = model(x)
        norms = z_proj.norm(dim=-1)
        assert torch.allclose(norms, torch.ones(B), atol=1e-5)

    def test_encode_shape(self, model, x):
        z = model.encode(x)
        assert z.shape == (B, D_MODEL)

    def test_encode_matches_forward_z(self, model, x):
        # Must be in eval mode — dropout makes two separate passes differ in train mode
        model.eval()
        with torch.no_grad():
            z_enc    = model.encode(x)
            z_fwd, _ = model(x)
        assert torch.allclose(z_enc, z_fwd, atol=1e-5)

    def test_return_embeddings_unchanged_from_pretrain(self):
        # Verify the PatchTST backbone flag still works after CARLAModel wraps it
        backbone = PatchTST()
        # Direct backbone call
        z_direct = backbone(torch.randn(B, T, C), return_embeddings=True)
        # Via CARLAModel.encode
        model = CARLAModel(backbone)
        z_via_model = model.encode(torch.randn(B, T, C))  # different x, just checking shape
        assert z_direct.shape == z_via_model.shape == (B, D_MODEL)

    def test_patchtst_reconstruction_still_works(self):
        # Ensure the return_embeddings flag didn't break the default PatchTST path
        backbone = PatchTST()
        recon, mask = backbone(torch.randn(B, T, C), mask_ratio=0.4)
        assert recon.shape == (B, T, C)
        assert mask.shape  == (B, 6)


# ── SupCon loss ───────────────────────────────────────────────────────────────

class TestSupConLoss:

    def _make_batch(self, b: int, d: int, n_normal: int, seed: int = 0):
        torch.manual_seed(seed)
        z_proj    = torch.randn(b, d)
        z_proj    = torch.nn.functional.normalize(z_proj, dim=-1)
        is_normal = torch.zeros(b, dtype=torch.long)
        is_normal[:n_normal] = 1
        return z_proj, is_normal

    def test_loss_is_scalar(self):
        z, labels = self._make_batch(8, PROJ_DIM, 6)
        loss = supcon_loss(z, labels)
        assert loss.shape == ()

    def test_loss_is_finite(self):
        z, labels = self._make_batch(8, PROJ_DIM, 6)
        loss = supcon_loss(z, labels)
        assert torch.isfinite(loss)

    def test_loss_is_non_negative(self):
        z, labels = self._make_batch(8, PROJ_DIM, 6)
        loss = supcon_loss(z, labels)
        assert loss.item() >= 0.0

    def test_loss_zero_when_no_normal_anchor(self):
        # All anomaly windows — no anchor has positives, loss should be 0
        z_proj    = torch.nn.functional.normalize(torch.randn(8, PROJ_DIM), dim=-1)
        is_normal = torch.zeros(8, dtype=torch.long)
        loss = supcon_loss(z_proj, is_normal)
        assert loss.item() == 0.0

    def test_higher_temp_gives_lower_loss_magnitude(self):
        # Higher temperature = softer distribution = lower loss
        z, labels = self._make_batch(8, PROJ_DIM, 6, seed=42)
        loss_low_tau  = supcon_loss(z, labels, tau=0.07)
        loss_high_tau = supcon_loss(z, labels, tau=1.0)
        assert loss_low_tau.item() > loss_high_tau.item()

    def test_loss_has_gradient(self):
        # Build loss through a model parameter so grad flows to a leaf tensor
        model = CARLAModel()
        x = torch.randn(8, T, C)
        is_normal = torch.ones(8, dtype=torch.long)
        _, z_proj = model(x)
        loss = supcon_loss(z_proj, is_normal)
        loss.backward()
        # Any model parameter should have a gradient if the graph is connected
        assert any(p.grad is not None for p in model.parameters())

    def test_loss_lower_when_normals_close_and_anomalies_far(self):
        # Loss should be lower when normals cluster tightly and anomalies are pushed far.
        # "Good" batch: normals all point in same direction, anomalies point opposite.
        torch.manual_seed(0)
        n_normal, n_anomaly, d = 6, 2, PROJ_DIM
        is_normal = torch.tensor([1]*n_normal + [0]*n_anomaly, dtype=torch.long)

        base = torch.zeros(d); base[0] = 1.0   # unit vector in dim 0
        z_good = torch.zeros(n_normal + n_anomaly, d)
        z_good[:n_normal] =  base               # normals cluster at +e0
        z_good[n_normal:] = -base               # anomalies at -e0
        z_good = torch.nn.functional.normalize(z_good, dim=-1)

        z_random = torch.nn.functional.normalize(torch.randn(n_normal + n_anomaly, d), dim=-1)

        loss_good   = supcon_loss(z_good,   is_normal, tau=0.07)
        loss_random = supcon_loss(z_random, is_normal, tau=0.07)
        assert loss_good.item() < loss_random.item()


# ── anomaly scoring ───────────────────────────────────────────────────────────

D_EMBED = 32   # small embedding dim for fast GMM tests


class TestFitGMM:

    def _normal_embeddings(self, n: int = 200, d: int = D_EMBED, seed: int = 0) -> np.ndarray:
        rng = np.random.default_rng(seed)
        return rng.standard_normal((n, d)).astype(np.float32)

    def test_returns_pca_and_gmm(self):
        from sklearn.decomposition import PCA
        from sklearn.mixture import GaussianMixture
        emb = self._normal_embeddings()
        pca, gmm = fit_gmm(emb, k_grid=[2, 3])
        assert isinstance(pca, PCA)
        assert isinstance(gmm, GaussianMixture)

    def test_selected_k_is_in_grid(self):
        k_grid = [2, 3, 5]
        emb = self._normal_embeddings()
        _, gmm = fit_gmm(emb, k_grid=k_grid)
        assert gmm.get_params()["n_components"] in k_grid

    def test_pca_reduces_dimension(self):
        emb = self._normal_embeddings(d=D_EMBED)
        pca, _ = fit_gmm(emb, k_grid=[2])
        # 95% variance of standard normal in D_EMBED dims — PCA should reduce it
        assert pca.n_components_ <= D_EMBED

    def test_gmm_fitted(self):
        # A fitted GMM has converged_ attribute set to True
        emb = self._normal_embeddings()
        _, gmm = fit_gmm(emb, k_grid=[2])
        assert gmm.converged_


class TestScoreWithGMM:

    @pytest.fixture
    def fitted(self):
        rng = np.random.default_rng(0)
        normal_emb = rng.standard_normal((300, D_EMBED)).astype(np.float32)
        pca, gmm = fit_gmm(normal_emb, k_grid=[3])
        return pca, gmm

    def test_output_shape(self, fitted):
        pca, gmm = fitted
        emb    = np.random.default_rng(1).standard_normal((50, D_EMBED)).astype(np.float32)
        scores = score_with_gmm(pca, gmm, emb)
        assert scores.shape == (50,)

    def test_output_dtype(self, fitted):
        pca, gmm = fitted
        emb    = np.random.default_rng(1).standard_normal((10, D_EMBED)).astype(np.float32)
        scores = score_with_gmm(pca, gmm, emb)
        assert scores.dtype == np.float32

    def test_scores_are_finite(self, fitted):
        pca, gmm = fitted
        emb    = np.random.default_rng(1).standard_normal((20, D_EMBED)).astype(np.float32)
        scores = score_with_gmm(pca, gmm, emb)
        assert np.isfinite(scores).all()

    def test_outliers_score_higher_than_inliers(self, fitted):
        # GMM was fit on N(0,1). Far-outlier embeddings (mean=50) should score
        # much higher (more anomalous) than in-distribution embeddings (mean=0).
        pca, gmm = fitted
        rng = np.random.default_rng(2)
        inliers  = rng.standard_normal((50, D_EMBED)).astype(np.float32)
        outliers = (rng.standard_normal((50, D_EMBED)) + 50).astype(np.float32)
        scores_in  = score_with_gmm(pca, gmm, inliers)
        scores_out = score_with_gmm(pca, gmm, outliers)
        assert scores_out.mean() > scores_in.mean()


class TestEmbedDataset:

    @pytest.fixture
    def model_and_loader(self):
        torch.manual_seed(0)
        model = CARLAModel()
        model.eval()
        data   = _make_patient_data(n_patients=2, n_minutes=600)
        ds     = ContrastiveDataset(data, stride=60)
        loader = DataLoader(ds, batch_size=16, shuffle=False)
        return model, loader, len(ds)

    def test_embeddings_shape(self, model_and_loader):
        model, loader, n_windows = model_and_loader
        emb, _ = embed_dataset(model, loader, torch.device("cpu"))
        assert emb.shape == (n_windows, D_MODEL)

    def test_labels_shape(self, model_and_loader):
        model, loader, n_windows = model_and_loader
        _, labels = embed_dataset(model, loader, torch.device("cpu"))
        assert labels.shape == (n_windows,)

    def test_labels_are_binary(self, model_and_loader):
        model, loader, _ = model_and_loader
        _, labels = embed_dataset(model, loader, torch.device("cpu"))
        assert set(labels.tolist()).issubset({0, 1})

    def test_embeddings_are_finite(self, model_and_loader):
        model, loader, _ = model_and_loader
        emb, _ = embed_dataset(model, loader, torch.device("cpu"))
        assert np.isfinite(emb).all()
