"""
Unit tests for XCHANNEL: the cross-channel conditional forecaster, its
forecast-window dataset index, and the scoring path.

All tests run on CPU with tiny tensors - no checkpoint or Parquet required.

Run from repo root:
    .venv/bin/pytest ml/tests/test_xchannel.py -v
"""

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader

from dataset import ANOMALY_CLASSES, N_CHANNELS as DS_NCHAN
from models.xchannel.model import (
    XChannelForecaster, forecaster_from_ckpt, forecast_loss, anomaly_score,
    CONTEXT_LEN, HORIZON, D_MODEL, GLU,
)
from models.xchannel.dataset import ForecastWindowDataset, _make_index, WIN
from models.xchannel.anomaly_score import score_dataset

# -- shared constants ------------------------------------------------------------

B = 4               # batch size
L = CONTEXT_LEN     # 120 - glucose history length
H = HORIZON         # 40  - forecast horizon
N_FLAGS = len(ANOMALY_CLASSES)        # 5
N_COLS = DS_NCHAN + N_FLAGS           # 8 - [glu, ins, carb, 5 flags]


# -- fixtures --------------------------------------------------------------------

@pytest.fixture
def model() -> XChannelForecaster:
    torch.manual_seed(0)
    return XChannelForecaster()


@pytest.fixture
def inputs():
    """A batch of forecaster inputs: glucose history + exogenous through horizon."""
    torch.manual_seed(1)
    glu = torch.randn(B, L)
    ins = torch.randn(B, L + H)
    carb = torch.randn(B, L + H)
    return glu, ins, carb


def _make_patient(T: int, flag_rows: tuple[int, ...] = ()) -> np.ndarray:
    """Synthetic [T, 8] patient array; 1.0 in the 'missed' flag at flag_rows."""
    rng = np.random.default_rng(0)
    arr = np.zeros((T, N_COLS), dtype=np.float32)
    arr[:, :DS_NCHAN] = rng.standard_normal((T, DS_NCHAN)).astype(np.float32)
    for r in flag_rows:
        arr[r, DS_NCHAN] = 1.0   # first anomaly class flag
    return arr


# -- XChannelForecaster ----------------------------------------------------------

class TestXChannelForecaster:

    def test_forecast_shape(self, model, inputs):
        out = model(*inputs)
        assert out.shape == (B, H), f"expected {(B, H)}, got {out.shape}"

    def test_embedding_shape(self, model, inputs):
        emb = model(*inputs, return_embeddings=True)
        assert emb.shape == (B, D_MODEL)

    def test_output_dtype_float32(self, model, inputs):
        assert model(*inputs).dtype == torch.float32

    def test_forecast_is_finite(self, model, inputs):
        assert torch.isfinite(model(*inputs)).all()

    def test_forecast_depends_on_insulin(self, model, inputs):
        # THE defining property - opposite of PatchTST's channel independence.
        # Changing insulin must change the glucose forecast (cross-channel mixing).
        glu, ins, carb = inputs
        model.eval()
        with torch.no_grad():
            base = model(glu, ins, carb)
            alt = model(glu, ins * 5.0, carb)
        assert not torch.allclose(base, alt), (
            "Forecast unchanged when insulin changed - cross-channel attention is dead"
        )

    def test_forecast_depends_on_carbs(self, model, inputs):
        glu, ins, carb = inputs
        model.eval()
        with torch.no_grad():
            base = model(glu, ins, carb)
            alt = model(glu, ins, carb * 5.0)
        assert not torch.allclose(base, alt), "Forecast ignores carbs"

    def test_forecast_depends_on_glucose_history(self, model, inputs):
        glu, ins, carb = inputs
        model.eval()
        with torch.no_grad():
            base = model(glu, ins, carb)
            alt = model(glu * 5.0, ins, carb)
        assert not torch.allclose(base, alt), "Forecast ignores glucose history"

    def test_channel_embed_is_learned_parameter(self, model):
        names = {n for n, _ in model.named_parameters()}
        assert "channel_embed" in names, "channel_embed must be a learned parameter"

    def test_configurable_horizon(self):
        m = XChannelForecaster(horizon=20)
        out = m(torch.randn(B, L), torch.randn(B, L + 20), torch.randn(B, L + 20))
        assert out.shape == (B, 20)

    def test_gradients_flow(self, model, inputs):
        # one backward step must populate grads on every parameter
        out = model(*inputs)
        out.mean().backward()
        for name, p in model.named_parameters():
            assert p.grad is not None, f"no gradient reached {name}"


# -- patched architecture (quality-program Step 1) -------------------------------

class TestPatching:

    def test_patched_forecast_and_embedding_shape(self, inputs):
        m = XChannelForecaster(patch_len=20, n_layers=3)
        glu, ins, carb = inputs
        assert m(glu, ins, carb).shape == (B, H)
        assert m(glu, ins, carb, return_embeddings=True).shape == (B, D_MODEL)

    def test_patched_has_more_params_than_default(self):
        small = sum(p.numel() for p in XChannelForecaster(patch_len=0).parameters())
        big = sum(p.numel() for p in XChannelForecaster(patch_len=20, n_layers=3).parameters())
        assert big > small                       # more tokens/layers -> more capacity

    def test_patch_len_must_divide_lengths(self):
        with pytest.raises(AssertionError):
            XChannelForecaster(patch_len=7)       # 120 % 7 != 0

    def test_patched_still_cross_channel(self, inputs):
        glu, ins, carb = inputs
        m = XChannelForecaster(patch_len=20, n_layers=3).eval()
        with torch.no_grad():
            base = m(glu, ins, carb)
            alt = m(glu, ins * 5.0, carb)
        assert not torch.allclose(base, alt)      # insulin still influences forecast

    def test_forecaster_from_ckpt_roundtrips_arch(self):
        m = XChannelForecaster(patch_len=20, n_layers=3).eval()
        ckpt = {"model_state": m.state_dict(), "args": {"patch_len": 20, "n_layers": 3}}
        m2 = forecaster_from_ckpt(ckpt).eval()
        assert m2.patch_len == 20
        g, i, c = torch.randn(2, L), torch.randn(2, L + H), torch.randn(2, L + H)
        with torch.no_grad():
            torch.testing.assert_close(m(g, i, c), m2(g, i, c))

    def test_forecaster_from_ckpt_defaults_to_3token(self):
        m = XChannelForecaster()                  # patch_len=0
        ckpt = {"model_state": m.state_dict(), "args": {}}   # legacy ckpt, no patch_len
        assert forecaster_from_ckpt(ckpt).patch_len == 0


# -- probabilistic / NLL (quality-program Step 2) --------------------------------

class TestProbabilistic:

    def test_forward_returns_mean_and_logvar(self, inputs):
        m = XChannelForecaster(probabilistic=True)
        out = m(*inputs)
        assert isinstance(out, tuple) and len(out) == 2
        mean, logvar = out
        assert mean.shape == (B, H) and logvar.shape == (B, H)

    def test_embeddings_unaffected_by_probabilistic(self, inputs):
        m = XChannelForecaster(probabilistic=True)
        assert m(*inputs, return_embeddings=True).shape == (B, D_MODEL)

    def test_forecast_loss_point_is_mse(self):
        out = torch.randn(B, H); tgt = torch.randn(B, H)
        torch.testing.assert_close(forecast_loss(out, tgt),
                                   torch.nn.functional.mse_loss(out, tgt))

    def test_anomaly_score_point_is_mean_sq_residual(self):
        out = torch.randn(B, H); tgt = torch.randn(B, H)
        torch.testing.assert_close(anomaly_score(out, tgt), ((out - tgt) ** 2).mean(1))

    def test_nll_score_is_surprise_under_uncertainty(self):
        # same residual, but higher predicted variance -> LOWER anomaly score
        tgt = torch.zeros(B, H); mean = torch.ones(B, H)            # residual = 1
        confident = anomaly_score((mean, torch.full((B, H), -2.0)), tgt)   # small sigma^2
        uncertain = anomaly_score((mean, torch.full((B, H),  2.0)), tgt)   # large sigma^2
        assert (uncertain < confident).all()

    def test_forecaster_from_ckpt_roundtrips_probabilistic(self):
        m = XChannelForecaster(probabilistic=True).eval()
        ckpt = {"model_state": m.state_dict(), "args": {"probabilistic": True}}
        m2 = forecaster_from_ckpt(ckpt).eval()
        assert m2.probabilistic
        g, i, c = torch.randn(2, L), torch.randn(2, L + H), torch.randn(2, L + H)
        with torch.no_grad():
            mean1, lv1 = m(g, i, c); mean2, lv2 = m2(g, i, c)
        torch.testing.assert_close(mean1, mean2); torch.testing.assert_close(lv1, lv2)


# -- _make_index (window index + clean-window filter) ----------------------------

class TestMakeIndex:

    def test_all_window_count(self):
        # T=200, WIN=160, stride 5 -> starts 0,5,...,40 = 9 windows
        T = WIN + 40
        data = {"p0": _make_patient(T)}
        _, pid_idx, starts = _make_index(data, stride=5, train_on="all")
        expected = len(range(0, T - WIN + 1, 5))
        assert len(starts) == expected == 9
        assert len(pid_idx) == len(starts)

    def test_int32_dtype(self):
        data = {"p0": _make_patient(WIN + 40)}
        _, pid_idx, starts = _make_index(data, stride=5, train_on="all")
        assert pid_idx.dtype == np.int32 and starts.dtype == np.int32

    def test_two_patients_indexed_separately(self):
        data = {"p0": _make_patient(WIN + 20), "p1": _make_patient(WIN + 20)}
        pids, pid_idx, _ = _make_index(data, stride=10, train_on="all")
        assert pids == ["p0", "p1"]
        assert set(np.unique(pid_idx)) == {0, 1}

    def test_normal_filter_drops_flagged_windows(self):
        # a flag deep in the series should remove every window that spans it
        T = WIN + 40
        data = {"p0": _make_patient(T, flag_rows=(WIN + 5,))}
        _, _, all_starts = _make_index(data, stride=5, train_on="all")
        _, _, clean_starts = _make_index(data, stride=5, train_on="normal")
        assert len(clean_starts) < len(all_starts), "normal filter dropped nothing"

    def test_kept_windows_have_no_flags(self):
        T = WIN + 60
        arr = _make_patient(T, flag_rows=(WIN + 10, WIN + 30))
        data = {"p0": arr}
        _, _, clean_starts = _make_index(data, stride=5, train_on="normal")
        flags = arr[:, DS_NCHAN:]
        for s in clean_starts:
            assert flags[s : s + WIN].max() == 0, f"window at {s} contains a flag"

    def test_normal_equals_all_when_no_flags(self):
        data = {"p0": _make_patient(WIN + 30)}   # all-zero flags
        _, _, all_s = _make_index(data, stride=5, train_on="all")
        _, _, clean_s = _make_index(data, stride=5, train_on="normal")
        assert len(all_s) == len(clean_s)


# -- ForecastWindowDataset.__getitem__ (built without Parquet) -------------------

def _dataset_from_arrays(data: dict[str, np.ndarray], stride: int, train_on: str):
    """Construct a ForecastWindowDataset bypassing the Parquet load."""
    ds = object.__new__(ForecastWindowDataset)
    ds._data = data
    ds._pids, ds._pid_idx, ds._starts = _make_index(data, stride, train_on)
    return ds


class TestGetItem:

    def test_item_shapes_and_target(self):
        arr = _make_patient(WIN + 20)
        ds = _dataset_from_arrays({"p0": arr}, stride=5, train_on="all")
        glu, ins, carb, target, labels = ds[0]
        assert glu.shape == (L,)
        assert ins.shape == (L + H,)
        assert carb.shape == (L + H,)
        assert target.shape == (H,)
        # target is the glucose horizon slice of window starting at 0
        torch.testing.assert_close(target, torch.from_numpy(arr[L : L + H, GLU]))

    def test_label_reflects_horizon_flag(self):
        # flag inside the horizon of the window starting at 0 -> 'missed' label = 1
        arr = _make_patient(WIN + 20, flag_rows=(L + 5,))
        ds = _dataset_from_arrays({"p0": arr}, stride=5, train_on="all")
        *_, labels = ds[0]
        assert labels["missed"] == 1.0
        assert labels["late"] == 0.0

    def test_label_zero_when_flag_outside_horizon(self):
        # flag in the CONTEXT (before the horizon) -> horizon label stays 0
        arr = _make_patient(WIN + 20, flag_rows=(10,))
        ds = _dataset_from_arrays({"p0": arr}, stride=5, train_on="all")
        *_, labels = ds[0]
        assert labels["missed"] == 0.0

    def test_patient_window_counts_sum_to_len(self):
        data = {"p0": _make_patient(WIN + 30), "p1": _make_patient(WIN + 50)}
        ds = _dataset_from_arrays(data, stride=5, train_on="all")
        counts = ds.patient_window_counts()
        assert sum(n for _, n in counts) == len(ds)


# -- scoring path ----------------------------------------------------------------

class TestScoreDataset:

    def test_scores_and_labels_shapes(self, model):
        data = {"p0": _make_patient(WIN + 40), "p1": _make_patient(WIN + 40, flag_rows=(L + 3,))}
        ds = _dataset_from_arrays(data, stride=5, train_on="all")
        loader = DataLoader(ds, batch_size=8, shuffle=False)
        scores, labels = score_dataset(model, loader, torch.device("cpu"))
        assert scores.shape == (len(ds),)
        assert np.isfinite(scores).all()
        assert set(labels.keys()) == set(ANOMALY_CLASSES)
        for c in ANOMALY_CLASSES:
            assert labels[c].shape == (len(ds),)

    def test_scores_are_nonnegative(self, model):
        # score is a mean squared residual -> must be >= 0
        data = {"p0": _make_patient(WIN + 40)}
        ds = _dataset_from_arrays(data, stride=5, train_on="all")
        loader = DataLoader(ds, batch_size=8, shuffle=False)
        scores, _ = score_dataset(model, loader, torch.device("cpu"))
        assert (scores >= 0).all()
