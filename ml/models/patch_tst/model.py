"""
PatchTST encoder for CGM anomaly detection.

Architecture
------------
Input  : [B, 120, C] - 120-minute context window, C channels
Output : [B, 120, C] - reconstructed window (same shape as input)

Pipeline per forward pass
-------------------------
1. Split 120-minute window into 6 patches of 20 minutes each
2. Embed each patch: Linear(20 -> 128)
3. Replace masked patches with a learned mask token
4. Add positional encoding so the transformer knows patch order
5. Run each channel independently through the shared transformer encoder
6. Project each output token back to 20 raw values: Linear(128 -> 20)
7. Return reconstruction + boolean mask (needed to compute loss)

Channel independence
--------------------
The transformer loop (step 5) runs C times, once per channel, with
shared weights. Glucose, insulin, and carbs never attend to each other.
This is the PatchTST design choice.

Usage
-----
    model = PatchTST()

    # pretraining, mask 40% of patches
    recon, mask = model(x, mask_ratio=0.4)   # x: [B, 120, 3]

    # inference, no masking, full reconstruction for anomaly scoring
    recon, _ = model(x, mask_ratio=0.0)
"""

from __future__ import annotations

import math

import torch
import torch.nn as nn

# -- hyperparameters -----------------------------------------------------------

PATCH_LEN  = 20     # minutes per patch  ->  120 / 20 = 6 patches
N_PATCHES  = 6      # context window length / patch length
D_MODEL    = 128    # embedding dimension; must be divisible by N_HEADS
N_HEADS    = 8      # attention heads  ->  128 / 8 = 16 dims per head
N_LAYERS   = 3      # transformer encoder depth
MASK_RATIO = 0.4    # fraction of patches hidden during pretraining


# -- positional encoding -------------------------------------------------------

class PositionalEncoding(nn.Module):
    """
    Adds a fixed sinusoidal fingerprint to each patch so the transformer
    can distinguish position 0 from position 5.

    Stored as a buffer (not a parameter): saved in checkpoints, moved to
    GPU with .to(device), but never updated by the optimizer.
    """

    def __init__(self, d_model: int, max_len: int = N_PATCHES) -> None:
        super().__init__()

        pe  = torch.zeros(max_len, d_model)             # [6, 128]
        pos = torch.arange(max_len).unsqueeze(1)        # [6, 1]  - positions 0..5

        # 64 frequencies, geometrically spaced, each dim gets a different oscillation rate
        div = torch.exp(
            torch.arange(0, d_model, 2) * (-math.log(10000.0) / d_model)
        )                                               # [64]

        pe[:, 0::2] = torch.sin(pos * div)             # even dims
        pe[:, 1::2] = torch.cos(pos * div)             # odd  dims

        self.register_buffer("pe", pe.unsqueeze(0))    # [1, 6, 128]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, n_patches, d_model], pe broadcasts over batch dimension
        return x + self.pe


# -- model ---------------------------------------------------------------------

class PatchTST(nn.Module):

    def __init__(
        self,
        n_channels: int  = 3,
        patch_len:  int  = PATCH_LEN,
        n_patches:  int  = N_PATCHES,
        d_model:    int  = D_MODEL,
        n_heads:    int  = N_HEADS,
        n_layers:   int  = N_LAYERS,
        dropout:    float = 0.1,
    ) -> None:
        super().__init__()

        self.patch_len  = patch_len
        self.n_patches  = n_patches
        self.n_channels = n_channels

        # shared across all channels: one linear maps each 20-value patch -> 128-dim token
        self.patch_embed = nn.Linear(patch_len, d_model)

        # learned vector substituted for every hidden patch during pretraining
        self.mask_token  = nn.Parameter(torch.zeros(d_model))

        self.pos_enc = PositionalEncoding(d_model, n_patches)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model        = d_model,
            nhead          = n_heads,
            dim_feedforward = d_model * 4,  # inner MLP is 4x wider, standard convention
            dropout        = dropout,       # randomly zero out some activations for regularization
            batch_first    = True,          # input shape: [batch, seq, dim]
            norm_first     = True,          # pre-norm: more stable early in training
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

        # maps each 128-dim output token back to 20 raw values
        self.head = nn.Linear(d_model, patch_len)

    def forward(
        self,
        x: torch.Tensor,        # [B, 120, C]
        mask_ratio: float = 0.0,
        fixed_mask: torch.Tensor | None = None,  # [n_patches] or [B, n_patches] bool
        return_embeddings: bool = False,
    ) -> tuple[torch.Tensor, torch.Tensor] | torch.Tensor:
        B, T, C = x.shape

        # -- 1. split into patches ---------------------------------------------
        # [B, 120, C] -> [B, C, n_patches, patch_len]
        x = x.permute(0, 2, 1)                                 # [B, C, 120]
        x = x.reshape(B, C, self.n_patches, self.patch_len)    # [B, C, 6, 20]

        # -- 2. embed patches --------------------------------------------------
        # Linear(20 -> 128) applied to the last dim
        tokens = self.patch_embed(x)                            # [B, C, 6, 128]

        # -- 3. build mask -----------------------------------------------------
        # Same patch positions masked across all channels (one mask per sample).
        # fixed_mask: caller-supplied deterministic mask (used by validation and
        # last-patch scoring). A [n_patches] vector broadcasts to the batch.
        if fixed_mask is not None:
            mask = fixed_mask.to(device=x.device, dtype=torch.bool)
            if mask.dim() == 1:
                mask = mask.unsqueeze(0).expand(B, self.n_patches)
        else:
            mask = torch.zeros(B, self.n_patches, dtype=torch.bool, device=x.device)
            if mask_ratio > 0.0:
                n_mask = max(1, int(self.n_patches * mask_ratio))   # e.g. 40% of 6 = 2
                # Vectorised over the batch: per sample, random scores + topk pick
                # a uniform random subset of n_mask patches to hide. Replaces a
                # per-sample Python loop that throttled large-batch training.
                noise = torch.rand(B, self.n_patches, device=x.device)
                idx = noise.topk(n_mask, dim=1).indices             # [B, n_mask]
                mask.scatter_(1, idx, True)                         # True = this patch is hidden

        # -- 4. apply mask -----------------------------------------------------
        # Expand mask to match token shape, then replace hidden tokens
        mask_4d = mask.unsqueeze(1).unsqueeze(-1)               # [B, 1, 6, 1]
        mask_token = self.mask_token.reshape(1, 1, 1, -1)       # [1, 1, 1, 128]
        tokens = torch.where(mask_4d, mask_token.expand_as(tokens), tokens)

        # -- 5. transformer (channel-independent) -----------------------------
        # Process each channel separately through the same shared transformer
        out_channels = []
        for c in range(C):
            t = tokens[:, c, :, :]                              # [B, 6, 128]
            t = self.pos_enc(t)
            t = self.transformer(t)                             # [B, 6, 128]
            out_channels.append(t)

        out = torch.stack(out_channels, dim=1)                  # [B, C, 6, 128]

        # CARLA path: mean-pool over channels and patches -> [B, D_MODEL]
        if return_embeddings:
            return out.mean(dim=(1, 2))

        # -- 6. reconstruct ----------------------------------------------------
        recon = self.head(out)                                   # [B, C, 6, 20]

        # -- 7. reshape back to input format -----------------------------------
        recon = recon.reshape(B, C, T).permute(0, 2, 1)         # [B, 120, C]

        return recon, mask   # mask shape: [B, 6] - True where patch was hidden
