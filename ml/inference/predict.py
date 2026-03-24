"""Inference module for anomaly detection.

Provides functions to run trained ML models against new glucose data,
either as batch jobs (on HPC) or as a service endpoint.

TODO (Phase 3, w16-25): Implement inference pipeline.
"""
import numpy as np
from pathlib import Path


def load_model(model_path: str):
    """Load a trained model from disk.

    Args:
        model_path: Path to the saved model checkpoint.

    Returns:
        Loaded model ready for inference.
    """
    raise NotImplementedError("Model loading — Phase 3 (w16-25)")


def predict_anomalies(
    glucose_values: np.ndarray,
    timestamps: np.ndarray,
    model_path: str = "models/latest.pt",
) -> list[dict]:
    """Run anomaly detection on a glucose trace.

    Args:
        glucose_values: Array of glucose readings (mg/dL).
        timestamps: Array of corresponding timestamps.
        model_path: Path to the trained model.

    Returns:
        List of detected anomaly dicts with type, confidence, and timestamp.
    """
    raise NotImplementedError("Anomaly prediction — Phase 3 (w16-25)")


def batch_inference(data_dir: str, model_path: str, output_dir: str) -> None:
    """Run inference on all patients in a dataset.

    Designed for HPC batch jobs.

    Args:
        data_dir: Directory containing patient data.
        model_path: Path to the trained model.
        output_dir: Directory for results.
    """
    raise NotImplementedError("Batch inference — Phase 3 (w16-25)")
