"""
CARLA encoder for CGM anomaly detection.

Architecture
------------
Input  : [B, 120, C] — 120-minute context window, C channels
Output : z     [B, D_MODEL]  — encoder embedding (used for GMM scoring)
         z_proj [B, PROJ_DIM] — projected embedding (used for SupCon loss only)

Pipeline per forward pass
-------------------------
1. PatchTST backbone (same as Arc 1) with return_embeddings=True
   → patch embed + channel-independent transformer → mean-pool → [B, 128]
2. Projection head: Linear(128→128) → ReLU → Linear(128→64) → L2-normalise
   → [B, 64]

The projection head is used only during contrastive pretraining.
At inference (anomaly scoring), discard it and use z directly.

Why mean-pool over channels AND patches?
PatchTST outputs [B, C, N_patches, D_MODEL] after the transformer.
Mean over dim=(1,2) collapses both channel and patch dimensions → [B, D_MODEL].
This gives one representation per window, needed by the contrastive loss.

Usage
-----
    from models.patch_tst.model import PatchTST
    from models.carla.model import CARLAModel

    backbone = PatchTST()
    model = CARLAModel(backbone)

    # Training: returns both embeddings
    z, z_proj = model(x)            # x: [B, 120, 3]

    # Inference / scoring: encoder embedding only
    z = model.encode(x)             # [B, 128]
"""

from __future__ import annotations

import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from models.patch_tst.model import PatchTST, D_MODEL

PROJ_DIM = 64   # projection head output dimension


class CARLAModel(nn.Module):

    def __init__(
        self,
        backbone: PatchTST | None = None,
        d_model:  int = D_MODEL,
        proj_dim: int = PROJ_DIM,
    ) -> None:
        super().__init__()
        self.backbone = backbone if backbone is not None else PatchTST()

        # Two-layer projection head — used only during contrastive training.
        self.proj_head = nn.Sequential(
            nn.Linear(d_model, d_model),
            nn.ReLU(),
            nn.Linear(d_model, proj_dim),
        )

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        """
        Run the backbone only — no projection head.
        Used at inference time to produce embeddings for GMM scoring.

        x   : [B, 120, C]
        returns z : [B, D_MODEL]
        """
        return self.backbone(x, return_embeddings=True)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Full forward pass for contrastive pretraining.

        x   : [B, 120, C]
        returns (z, z_proj)
            z      : [B, D_MODEL]  — encoder output (for GMM, not for loss)
            z_proj : [B, PROJ_DIM] — L2-normalised projection (for SupCon loss)
        """
        z      = self.encode(x)                          # [B, D_MODEL]
        z_proj = self.proj_head(z)                       # [B, PROJ_DIM]
        z_proj = F.normalize(z_proj, dim=-1)             # L2 normalise → cosine sim = dot product
        return z, z_proj
