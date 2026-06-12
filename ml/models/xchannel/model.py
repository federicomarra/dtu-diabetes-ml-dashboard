"""
XCHANNEL — iTransformer-style cross-channel conditional glucose forecaster.

See ml/docs/XCHANNEL.md for the why. In one line: forecast glucose over the
next H minutes from glucose HISTORY + insulin/carbs known THROUGH the horizon,
and score anomalies by the forecast residual. The cross-channel attention is
the whole point — it is what PatchTST (channel-independent) structurally lacks.

Layout (iTransformer inversion — one token per CHANNEL, attention over channels):

    glucose  [B, L]    --Linear(L  ->D)-->  token_g  [B, D]
    insulin  [B, L+H]  --Linear(L+H->D)-->  token_i  [B, D]   stack -> [B, 3, D]
    carbs    [B, L+H]  --Linear(L+H->D)-->  token_c  [B, D]
                                                  |
                              + per-channel type embedding [3, D]
                                                  |
                              TransformerEncoder (attention OVER the 3 tokens)
                                                  |
                              take glucose output token  [B, D]
                                                  |
                              Linear(D -> H)  ->  glucose forecast  [B, H]

Each channel gets its OWN input Linear because the channels have different
visible lengths (glucose L, exogenous L+H) — weights can't be shared.
"""

import torch
import torch.nn as nn

# ── shapes (minutes; CGM is 1 sample/min in this cohort) ──────────────────────
CONTEXT_LEN = 120     # L — glucose history fed in (matches PatchTST window)
HORIZON = 40          # H — minutes of glucose to forecast across
N_CHANNELS = 3        # glucose, insulin, carbs

# ── capacity (matched to PatchTST/CARLA for a fair comparison) ────────────────
D_MODEL = 128
N_HEADS = 8
N_LAYERS = 2          # only 3 tokens to attend over — deep is pointless
DROPOUT = 0.1

# index of each channel's token in the stacked [B, 3, D] tensor
GLU, INS, CARB = 0, 1, 2


class XChannelForecaster(nn.Module):
    def __init__(self, context_len=CONTEXT_LEN, horizon=HORIZON,
                 d_model=D_MODEL, n_heads=N_HEADS, n_layers=N_LAYERS,
                 dropout=DROPOUT):
        super().__init__()
        self.context_len = context_len
        self.horizon = horizon
        exo_len = context_len + horizon          # insulin/carbs see the horizon

        # one input embedding PER channel (different visible lengths)
        self.embed_glu = nn.Linear(context_len, d_model)
        self.embed_ins = nn.Linear(exo_len, d_model)
        self.embed_carb = nn.Linear(exo_len, d_model)

        # learned "which channel is this" embedding, added to each token so the
        # attention can tell glucose/insulin/carbs apart (tokens are otherwise
        # order-only, like positional encodings but over channels)
        self.channel_embed = nn.Parameter(torch.zeros(N_CHANNELS, d_model))

        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads,
            dim_feedforward=4 * d_model, dropout=dropout,
            batch_first=True,                    # input is [B, tokens, D]
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=n_layers)

        # glucose output token -> H-step glucose forecast
        self.head = nn.Linear(d_model, horizon)

    def forward(self, glu_hist, ins_full, carb_full, return_embeddings=False):
        """
        glu_hist  [B, L]     glucose history (the rest is unknown -> never fed)
        ins_full  [B, L+H]   insulin known through the horizon
        carb_full [B, L+H]   announced carbs known through the horizon
        returns   [B, H]     forecast glucose over (t, t+H]
        """
        tokens = torch.stack([
            self.embed_glu(glu_hist),
            self.embed_ins(ins_full),
            self.embed_carb(carb_full),
        ], dim=1)                                # [B, 3, D]
        tokens = tokens + self.channel_embed     # broadcast [3, D] over batch

        enc = self.encoder(tokens)               # [B, 3, D] — cross-channel mix
        glu_token = enc[:, GLU]                   # [B, D]
        if return_embeddings:
            return glu_token
        return self.head(glu_token)              # [B, H]
