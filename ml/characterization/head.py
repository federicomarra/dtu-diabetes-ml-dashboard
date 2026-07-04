"""
Characterization (similarity) head.

A small supervised classifier on top of the FROZEN XCHANNEL encoder. It is
trained ONLY on simulator ground-truth labels and, on real data, its output is
framed as a humble *similarity to synthetic archetypes* - never a diagnosis:

    "this window most resembles missed bolus (72%), late bolus (21%), other (7%)"

Three honesty mechanisms, all here:
  * MC Dropout - keep dropout ON at inference, run N passes -> mean probability +
    variance (predictive uncertainty).
  * latent-OOD - Mahalanobis distance from the NORMAL-class embedding cluster;
    a window far from it + high anomaly score is flagged "uncharacterized"
    rather than force-fit to a class.
  * it classifies the DETECTOR'S representation; it does not re-detect.

Classes (6): normal + the 5 simulator anomaly classes, single-label per window
by precedence (missed > late > large > prolonged > anaerobic; else normal).
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from dataset import ANOMALY_CLASSES   # [missed, late, large, prolonged, anaerobic]

CLASSES: list[str] = ["normal", *ANOMALY_CLASSES]          # 6
N_CLASSES = len(CLASSES)
# single-label precedence when a window carries several flags
_PRECEDENCE = ["missed", "late", "large", "prolonged", "anaerobic"]


def window_class(label_flags: dict[str, float] | np.ndarray) -> int:
    """Collapse per-class window flags -> one class index (0=normal)."""
    if isinstance(label_flags, dict):
        present = {c for c in ANOMALY_CLASSES if label_flags.get(c, 0.0) > 0}
    else:
        present = {c for c, v in zip(ANOMALY_CLASSES, label_flags) if v > 0}
    for c in _PRECEDENCE:
        if c in present:
            return CLASSES.index(c)
    return 0   # normal


class CharacterizationHead(nn.Module):
    """2-layer MLP with dropout, on the frozen 128-d encoder embedding."""

    def __init__(self, d_in: int = 128, hidden: int = 128,
                 n_classes: int = N_CLASSES, dropout: float = 0.3):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_in, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),          # kept active for MC Dropout at inference
            nn.Linear(hidden, n_classes),
        )

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.net(z)                # logits [B, n_classes]


@torch.no_grad()
def mc_predict(head: CharacterizationHead, z: torch.Tensor, n_passes: int = 30):
    """
    MC-Dropout prediction. Dropout stays ON (head.train()) so each pass samples a
    sub-network. Returns (mean_probs [B,C], uncertainty [B]) where uncertainty is
    the mean per-class std across passes - high = the model disagrees with itself.
    """
    was_training = head.training
    head.train()                          # enable dropout
    probs = torch.stack([head(z).softmax(-1) for _ in range(n_passes)])   # [P,B,C]
    head.train(was_training)
    return probs.mean(0), probs.std(0).mean(-1)


# -- latent OOD (Mahalanobis to the normal cluster) ------------------------------

def fit_ood(normal_embeddings: np.ndarray, reg: float = 1e-3):
    """Mean + inverse covariance of the NORMAL-class embeddings."""
    mu = normal_embeddings.mean(0)
    cov = np.cov(normal_embeddings, rowvar=False) + reg * np.eye(normal_embeddings.shape[1])
    return mu.astype(np.float64), np.linalg.inv(cov)


def ood_distance(z: np.ndarray, mu: np.ndarray, inv_cov: np.ndarray) -> np.ndarray:
    """Mahalanobis distance of each row of z from the normal cluster."""
    d = z.astype(np.float64) - mu
    return np.sqrt(np.einsum("ij,jk,ik->i", d, inv_cov, d))
