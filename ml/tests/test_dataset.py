"""
Unit tests for ml/dataset.py.

All tests use synthetic in-memory data, no Parquet file required.
The _preloaded argument on GlucoseWindowDataset is the hook that lets us
bypass the file read and inject a dict of numpy arrays directly.

Run from repo root:
    .venv/bin/pytest ml/tests/test_dataset.py -v
"""

import numpy as np
import pytest
import torch

from dataset import (
    WINDOW_LEN,
    N_CHANNELS,
    ANOMALY_CLASSES,
    TRAIN_STRIDE,
    EVAL_STRIDE,
    fit_scalers,
    _apply_scalers,
    _patient_zscore,
    normalize_patients,
    GlucoseWindowDataset,
)

# -- helpers -------------------------------------------------------------------

T = 300  # minutes per fake patient, fits at least 2 windows at stride=120


def _make_fake_data(n_patients: int = 3, t: int = T, seed: int = 0) -> dict[str, np.ndarray]:
    """
    Synthetic patient data matching the shape that load_patients() produces:
      [T, 8], columns 0-2 are signal channels, columns 3-7 are binary labels.

    Signals are given plausible ranges so scaler tests are meaningful:
      col 0 (blood_glucose):    ~ N(7.5, 2.0) mmol/L
      col 1 (insulin_mU_min):   ~ Uniform(0, 30) mU/min
      col 2 (cho_mg_announced): ~ Uniform(0, 500) mg/min, mostly zero
    Labels are sparse Bernoulli(0.05), anomalies are rare.
    """
    rng = np.random.default_rng(seed)
    data: dict[str, np.ndarray] = {}
    for i in range(n_patients):
        pid = f"fake_{i:03d}"

        signals = np.zeros((t, N_CHANNELS), dtype=np.float32)
        signals[:, 0] = rng.normal(7.5, 2.0, t)          # blood_glucose
        signals[:, 1] = rng.uniform(0, 30, t)             # insulin_mU_min
        signals[:, 2] = rng.uniform(0, 500, t) * (rng.random(t) < 0.1)  # sparse carbs

        labels = (rng.random((t, len(ANOMALY_CLASSES))) < 0.05).astype(np.float32)

        data[pid] = np.concatenate([signals, labels], axis=1)  # [T, 8]
    return data


# -- fixtures ------------------------------------------------------------------

@pytest.fixture
def fake_data() -> dict[str, np.ndarray]:
    return _make_fake_data()


@pytest.fixture
def scalers(fake_data, tmp_path) -> dict[str, dict[str, float]]:
    # tmp_path is a pytest built-in: a fresh temp dir per test
    return fit_scalers(fake_data, out=tmp_path / "scalers.json")


@pytest.fixture
def dataset(fake_data, scalers) -> GlucoseWindowDataset:
    return GlucoseWindowDataset(
        patient_ids=list(fake_data.keys()),
        scalers=scalers,
        stride=TRAIN_STRIDE,
        _preloaded=fake_data,
    )


# -- fit_scalers ---------------------------------------------------------------

class TestFitScalers:
    def test_returns_all_channels(self, scalers):
        # Every channel in CHANNELS must have an entry
        from dataset import CHANNELS
        assert set(scalers.keys()) == set(CHANNELS)

    def test_each_entry_has_mean_and_std(self, scalers):
        for ch, stats in scalers.items():
            assert "mean" in stats, f"missing mean for {ch}"
            assert "std"  in stats, f"missing std for {ch}"

    def test_std_is_positive(self, scalers):
        # std is clamped to 1e-8 in fit_scalers - must never be zero or negative
        for ch, stats in scalers.items():
            assert stats["std"] > 0, f"std <= 0 for {ch}"

    def test_values_are_finite(self, scalers):
        for ch, stats in scalers.items():
            assert np.isfinite(stats["mean"]), f"mean not finite for {ch}"
            assert np.isfinite(stats["std"]),  f"std not finite for {ch}"

    def test_mean_is_close_to_data_mean(self, fake_data, scalers):
        # Concatenate all training signals and check the scaler mean matches
        all_signals = np.concatenate(
            [arr[:, :N_CHANNELS] for arr in fake_data.values()], axis=0
        )
        from dataset import CHANNELS
        for i, ch in enumerate(CHANNELS):
            expected_mean = float(all_signals[:, i].mean())
            assert abs(scalers[ch]["mean"] - expected_mean) < 1e-4, (
                f"mean mismatch for {ch}: got {scalers[ch]['mean']:.4f}, "
                f"expected {expected_mean:.4f}"
            )

    def test_saves_json(self, fake_data, tmp_path):
        import json
        out = tmp_path / "scalers.json"
        fit_scalers(fake_data, out=out)
        assert out.exists()
        loaded = json.loads(out.read_text())
        from dataset import CHANNELS
        assert set(loaded.keys()) == set(CHANNELS)


# -- _apply_scalers ------------------------------------------------------------

class TestApplyScalers:
    def test_does_not_mutate_input(self, fake_data, scalers):
        pid = list(fake_data.keys())[0]
        original = fake_data[pid].copy()
        _apply_scalers(fake_data[pid], scalers)
        np.testing.assert_array_equal(fake_data[pid], original)

    def test_signal_columns_are_zscored(self, fake_data, scalers):
        # Apply scalers to the same data used to fit them.
        # The resulting signal columns should have mean ~0 and std ~1.
        all_scaled = np.concatenate(
            [_apply_scalers(arr, scalers) for arr in fake_data.values()], axis=0
        )
        for i in range(N_CHANNELS):
            col_mean = all_scaled[:, i].mean()
            col_std  = all_scaled[:, i].std()
            assert abs(col_mean) < 1e-3, f"channel {i} mean after scaling: {col_mean:.4f}"
            assert abs(col_std - 1.0) < 1e-3, f"channel {i} std after scaling: {col_std:.4f}"

    def test_label_columns_unchanged(self, fake_data, scalers):
        # Columns 3-7 (anomaly labels) must not be touched by the scaler
        pid = list(fake_data.keys())[0]
        arr = fake_data[pid]
        scaled = _apply_scalers(arr, scalers)
        np.testing.assert_array_equal(
            scaled[:, N_CHANNELS:], arr[:, N_CHANNELS:],
            err_msg="Label columns were modified by _apply_scalers"
        )

    def test_output_dtype_preserved(self, fake_data, scalers):
        pid = list(fake_data.keys())[0]
        arr = fake_data[pid]
        scaled = _apply_scalers(arr, scalers)
        assert scaled.dtype == arr.dtype


# -- per-patient normalization -------------------------------------------------

class TestPerPatientNorm:
    def test_each_patient_zero_mean_unit_std(self, fake_data):
        # Per-patient z-score -> EACH patient's signal cols have mean~0, std~1
        for arr in fake_data.values():
            z = _patient_zscore(arr)
            sig = z[:, :N_CHANNELS]
            np.testing.assert_allclose(sig.mean(axis=0), 0.0, atol=1e-4)
            np.testing.assert_allclose(sig.std(axis=0),  1.0, atol=1e-4)

    def test_labels_untouched(self, fake_data):
        pid = list(fake_data.keys())[0]
        arr = fake_data[pid]
        z = _patient_zscore(arr)
        np.testing.assert_array_equal(z[:, N_CHANNELS:], arr[:, N_CHANNELS:])

    def test_does_not_mutate_when_not_inplace(self, fake_data):
        pid = list(fake_data.keys())[0]
        original = fake_data[pid].copy()
        _patient_zscore(fake_data[pid], inplace=False)
        np.testing.assert_array_equal(fake_data[pid], original)

    def test_normalize_patients_per_patient_differs_from_global(self, fake_data, scalers):
        # Per-patient and global give different results when patients differ
        per = normalize_patients(fake_data, norm="per_patient")
        glob = normalize_patients(fake_data, norm="global", scalers=scalers)
        pid = list(fake_data.keys())[0]
        assert not np.allclose(per[pid][:, :N_CHANNELS], glob[pid][:, :N_CHANNELS])

    def test_global_requires_scalers(self, fake_data):
        with pytest.raises(ValueError):
            normalize_patients(fake_data, norm="global", scalers=None)

    def test_unknown_mode_raises(self, fake_data):
        with pytest.raises(ValueError):
            normalize_patients(fake_data, norm="bogus")

    def test_dataset_per_patient_default(self, fake_data):
        # Dataset defaults to per_patient and needs no scalers
        ds = GlucoseWindowDataset(
            patient_ids=list(fake_data.keys()),
            _preloaded=fake_data,
            stride=TRAIN_STRIDE,
        )
        assert len(ds) > 0
        x, _ = ds[0]
        assert x.shape == (WINDOW_LEN, N_CHANNELS)


# -- GlucoseWindowDataset ------------------------------------------------------

class TestGlucoseWindowDataset:

    # -- __len__ ---------------------------------------------------------------

    def test_patient_window_counts_sum_to_len(self, fake_data, scalers):
        ds = GlucoseWindowDataset(
            patient_ids=list(fake_data.keys()),
            scalers=scalers,
            stride=TRAIN_STRIDE,
            _preloaded=fake_data,
        )
        counts = ds.patient_window_counts()
        assert [pid for pid, _ in counts] == list(fake_data.keys())   # flat-index order
        assert sum(n for _, n in counts) == len(ds)

    def test_patient_window_counts_match_flat_blocks(self, fake_data, scalers):
        # The window at flat index inside patient i's block must belong to patient i
        ds = GlucoseWindowDataset(
            patient_ids=list(fake_data.keys()),
            scalers=scalers,
            stride=TRAIN_STRIDE,
            _preloaded=fake_data,
        )
        offset = 0
        for pid, n in ds.patient_window_counts():
            for j in (0, n - 1):
                assert ds._pids[ds._pid_idx[offset + j]] == pid
            offset += n

    def test_len_matches_expected_window_count(self, fake_data, scalers):
        # For each patient with T rows and a given stride,
        # valid windows = floor((T - WINDOW_LEN) / stride) + 1
        stride = TRAIN_STRIDE
        expected = sum(
            len(range(0, arr.shape[0] - WINDOW_LEN + 1, stride))
            for arr in fake_data.values()
        )
        ds = GlucoseWindowDataset(
            patient_ids=list(fake_data.keys()),
            scalers=scalers,
            stride=stride,
            _preloaded=fake_data,
        )
        assert len(ds) == expected

    def test_len_is_larger_with_smaller_stride(self, fake_data, scalers):
        # stride=1 should produce far more windows than stride=15
        ds_train = GlucoseWindowDataset(
            patient_ids=list(fake_data.keys()),
            scalers=scalers,
            stride=TRAIN_STRIDE,
            _preloaded=fake_data,
        )
        ds_eval = GlucoseWindowDataset(
            patient_ids=list(fake_data.keys()),
            scalers=scalers,
            stride=EVAL_STRIDE,
            _preloaded=fake_data,
        )
        assert len(ds_eval) > len(ds_train)

    def test_single_patient_len(self, scalers):
        # Isolate one patient to make the window count easy to verify
        data = {"p0": _make_fake_data(n_patients=1, t=T)["fake_000"]}
        stride = TRAIN_STRIDE
        expected = len(range(0, T - WINDOW_LEN + 1, stride))
        ds = GlucoseWindowDataset(
            patient_ids=["p0"],
            scalers=scalers,
            stride=stride,
            _preloaded=data,
        )
        assert len(ds) == expected

    # -- __getitem__ -----------------------------------------------------------

    def test_x_shape(self, dataset):
        x, _ = dataset[0]
        assert x.shape == (WINDOW_LEN, N_CHANNELS), (
            f"Expected ({WINDOW_LEN}, {N_CHANNELS}), got {x.shape}"
        )

    def test_x_is_float_tensor(self, dataset):
        x, _ = dataset[0]
        assert isinstance(x, torch.Tensor)
        assert x.dtype == torch.float32

    def test_labels_has_all_classes(self, dataset):
        _, labels = dataset[0]
        assert set(labels.keys()) == set(ANOMALY_CLASSES), (
            f"Missing classes: {set(ANOMALY_CLASSES) - set(labels.keys())}"
        )

    def test_label_values_are_binary(self, dataset):
        # Labels must be exactly 0.0 or 1.0 - no other values
        for idx in range(min(len(dataset), 20)):
            _, labels = dataset[idx]
            for cls, val in labels.items():
                assert val in (0.0, 1.0), (
                    f"label '{cls}' at index {idx} is {val}, expected 0.0 or 1.0"
                )

    def test_all_indices_accessible(self, dataset):
        # Iterating every index must not raise
        for idx in range(len(dataset)):
            dataset[idx]

    def test_window_does_not_exceed_patient_length(self, fake_data, scalers):
        # The last window's end index must be <= patient T
        # We verify this indirectly: if any window were out of bounds,
        # numpy would return a shorter array and x.shape would fail.
        ds = GlucoseWindowDataset(
            patient_ids=list(fake_data.keys()),
            scalers=scalers,
            stride=TRAIN_STRIDE,
            _preloaded=fake_data,
        )
        last_x, _ = ds[len(ds) - 1]
        assert last_x.shape == (WINDOW_LEN, N_CHANNELS)

    # -- label binarisation ----------------------------------------------------

    def test_label_is_1_when_anomaly_present_in_window(self, tmp_path):
        # Build a patient where the first WINDOW_LEN minutes have a missed bolus
        # at minute 50. The label for 'missed' must be 1.0.
        arr = np.zeros((T, N_CHANNELS + len(ANOMALY_CLASSES)), dtype=np.float32)
        arr[:, :N_CHANNELS] = 1.0  # flat signals - scaler won't crash
        missed_col = ANOMALY_CLASSES.index("missed")  # column index in label block
        arr[50, N_CHANNELS + missed_col] = 1.0        # anomaly at minute 50

        data = {"p_anomaly": arr}
        sc = fit_scalers(data, out=tmp_path / "sc.json")
        ds = GlucoseWindowDataset(
            patient_ids=["p_anomaly"],
            scalers=sc,
            stride=TRAIN_STRIDE,
            _preloaded=data,
        )
        # Window 0 covers minutes 0-119, which includes minute 50
        _, labels = ds[0]
        assert labels["missed"] == 1.0

    def test_label_is_0_when_anomaly_outside_window(self, tmp_path):
        # Anomaly at minute 200, which is beyond the first window (0-119)
        arr = np.zeros((T, N_CHANNELS + len(ANOMALY_CLASSES)), dtype=np.float32)
        arr[:, :N_CHANNELS] = 1.0
        missed_col = ANOMALY_CLASSES.index("missed")
        arr[200, N_CHANNELS + missed_col] = 1.0  # outside first window

        data = {"p_clean": arr}
        sc = fit_scalers(data, out=tmp_path / "sc.json")
        ds = GlucoseWindowDataset(
            patient_ids=["p_clean"],
            scalers=sc,
            stride=TRAIN_STRIDE,
            _preloaded=data,
        )
        _, labels = ds[0]
        assert labels["missed"] == 0.0
