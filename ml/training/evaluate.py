"""Model evaluation and metrics.

TODO (Phase 3, w16-25): Implement evaluation metrics for anomaly detection:
- Precision, recall, F1 for missed bolus detection
- ROC-AUC curves
- Confusion matrix analysis
- Time-to-detection metrics
"""


def evaluate_model(model_path: str, test_data_path: str) -> dict:
    """Evaluate a trained anomaly detection model on test data.

    Args:
        model_path: Path to the saved model.
        test_data_path: Path to test dataset.

    Returns:
        Dictionary of evaluation metrics.
    """
    raise NotImplementedError("Model evaluation — Phase 3 (w16-25)")
