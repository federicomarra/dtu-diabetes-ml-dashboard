"""
XCHANNEL - iTransformer-style cross-channel conditional glucose forecaster.

Forecast glucose over the next H minutes from glucose HISTORY + insulin/carbs
known THROUGH the horizon, and score anomalies by the forecast residual.
The cross-channel attention is the whole point - it is what PatchTST
(channel-independent) structurally lacks.

Layout (iTransformer inversion - one token per CHANNEL, attention over channels):

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
visible lengths (glucose L, exogenous L+H) - weights can't be shared.
"""

import os

import torch
import torch.nn as nn

# -- shapes (minutes; CGM is 1 sample/min in this cohort) ----------------------
# Env-overridable for the longer-horizon sweep: set XCH_HORIZON / XCH_CONTEXT for
# BOTH train and eval of a given run. ckpt args also carry horizon/context so
# forecaster_from_ckpt rebuilds the right output size.
CONTEXT_LEN = int(os.environ.get("XCH_CONTEXT", "120"))   # L - glucose history fed in
HORIZON = int(os.environ.get("XCH_HORIZON", "40"))        # H - minutes to forecast across
N_CHANNELS = 3        # glucose, insulin, carbs

# -- capacity (matched to PatchTST/CARLA for a fair comparison) ----------------
D_MODEL = 128
N_HEADS = 8
N_LAYERS = 2          # only 3 tokens to attend over - deep is pointless
DROPOUT = 0.1

# index of each channel's token in the stacked [B, 3, D] tensor
GLU, INS, CARB = 0, 1, 2


class XChannelForecaster(nn.Module):
    """
    Cross-channel conditional glucose forecaster.

    patch_len = 0 (default): the original iTransformer layout - ONE token per
        channel (3 tokens), each channel's whole series embedded by one Linear.
    patch_len > 0: temporal patching - each channel is split into patch_len-min
        patches, every patch is a token, so attention runs over BOTH time and
        channels (~ 6 glucose + 8 insulin + 8 carb tokens at L=120,H=40,P=20).
        Lifts the near-linear ceiling of the 3-token model. Quality-program
        Step 1; see project_quality_program memory.
    """

    def __init__(self, context_len=CONTEXT_LEN, horizon=HORIZON,
                 d_model=D_MODEL, n_heads=N_HEADS, n_layers=N_LAYERS,
                 dropout=DROPOUT, patch_len=0, probabilistic=False):
        super().__init__()
        self.context_len = context_len
        self.horizon = horizon
        self.patch_len = patch_len
        self.probabilistic = probabilistic       # predict mean + log-variance (NLL)
        exo_len = context_len + horizon          # insulin/carbs see the horizon

        if patch_len == 0:
            # one input embedding PER channel (different visible lengths)
            self.embed_glu = nn.Linear(context_len, d_model)
            self.embed_ins = nn.Linear(exo_len, d_model)
            self.embed_carb = nn.Linear(exo_len, d_model)
            # learned "which channel is this" embedding (3 channel tokens)
            self.channel_embed = nn.Parameter(torch.zeros(N_CHANNELS, d_model))
        else:
            assert context_len % patch_len == 0 and exo_len % patch_len == 0, \
                "patch_len must divide both context and context+horizon"
            self.n_g = context_len // patch_len           # glucose patches
            self.n_e = exo_len // patch_len               # insulin/carb patches
            # one patch embedding per channel (shared across that channel's patches)
            self.patch_glu = nn.Linear(patch_len, d_model)
            self.patch_ins = nn.Linear(patch_len, d_model)
            self.patch_carb = nn.Linear(patch_len, d_model)
            # joint channel+position embedding, one slot per token
            self.pos_embed = nn.Parameter(torch.zeros(self.n_g + 2 * self.n_e, d_model))

        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads,
            dim_feedforward=4 * d_model, dropout=dropout,
            batch_first=True,                    # input is [B, tokens, D]
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=n_layers, enable_nested_tensor=False)
        self.head = nn.Linear(d_model, horizon)                # mean
        if probabilistic:
            self.head_logvar = nn.Linear(d_model, horizon)     # log-variance

    def forward(self, glu_hist, ins_full, carb_full, return_embeddings=False):
        """
        glu_hist  [B, L]     glucose history (the rest is unknown -> never fed)
        ins_full  [B, L+H]   insulin known through the horizon
        carb_full [B, L+H]   announced carbs known through the horizon
        returns   [B, H]     forecast glucose over (t, t+H]
        """
        if self.patch_len == 0:
            tokens = torch.stack([
                self.embed_glu(glu_hist),
                self.embed_ins(ins_full),
                self.embed_carb(carb_full),
            ], dim=1)                            # [B, 3, D]
            tokens = tokens + self.channel_embed
            enc = self.encoder(tokens)
            rep = enc[:, GLU]                     # glucose token
        else:
            B = glu_hist.shape[0]
            g = self.patch_glu(glu_hist.reshape(B, self.n_g, self.patch_len))     # [B,n_g,D]
            i = self.patch_ins(ins_full.reshape(B, self.n_e, self.patch_len))     # [B,n_e,D]
            c = self.patch_carb(carb_full.reshape(B, self.n_e, self.patch_len))   # [B,n_e,D]
            tokens = torch.cat([g, i, c], dim=1) + self.pos_embed                 # [B,N,D]
            enc = self.encoder(tokens)
            rep = enc.mean(dim=1)                 # pool all tokens

        if return_embeddings:
            return rep
        mean = self.head(rep)                     # [B, H]
        if self.probabilistic:
            logvar = self.head_logvar(rep).clamp(-10.0, 10.0)   # stable exp()
            return mean, logvar
        return mean


# -- loss + score helpers (handle deterministic vs probabilistic uniformly) ------

def forecast_loss(out, target):
    """MSE for a point forecast; Gaussian NLL for a (mean, logvar) forecast."""
    if isinstance(out, tuple):
        mean, logvar = out
        return 0.5 * ((target - mean) ** 2 * torch.exp(-logvar) + logvar).mean()
    return nn.functional.mse_loss(out, target)


def anomaly_score(out, target, mode: str = "sym"):
    """Per-window score [B]. `mode` selects the residual aggregation:

      sym    : symmetric - squared residual (point) / per-element NLL (prob.). default.
      signed : mean POSITIVE-part residual (glucose ABOVE forecast) - targets the
               hyperglycemic anomalies (missed/late/large = under-insulinization).
      peak   : max SYMMETRIC per-element score over the horizon (a missed bolus diverges
               progressively; the mean dilutes the late, strongest part).
      end    : mean SYMMETRIC per-element score over the LAST quarter of the horizon.
               Only `signed` is directional; `peak`/`end` fire on hypo surprise too.

    For the probabilistic model the positive residual is standardized by sigma
    (directional surprise under uncertainty); for the point model it is the raw
    positive residual."""
    if isinstance(out, tuple):
        mean, logvar = out
        resid = target - mean
        elem = 0.5 * (resid ** 2 * torch.exp(-logvar) + logvar)      # per-element NLL (symmetric)
        pos = torch.clamp(resid * torch.exp(-0.5 * logvar), min=0.0)  # directional (refuted, kept)
    else:
        resid = target - out
        elem = resid ** 2                                            # per-element squared (symmetric)
        pos = torch.clamp(resid, min=0.0)
    if mode == "sym":
        return elem.mean(dim=1)
    if mode == "signed":                                            # directional over-forecast (refuted)
        return pos.mean(dim=1)
    if mode == "peak":                                              # max symmetric residual over horizon
        return elem.max(dim=1).values
    if mode == "end":                                               # symmetric residual over last quarter
        k = max(1, elem.shape[1] // 4)
        return elem[:, -k:].mean(dim=1)
    raise ValueError(f"unknown score mode: {mode}")


def forecaster_from_ckpt(ckpt: dict, device=None) -> "XChannelForecaster":
    """Reconstruct a forecaster matching how it was trained (reads arch args)."""
    a = ckpt.get("args", {})
    model = XChannelForecaster(
        context_len=int(a.get("context_len", CONTEXT_LEN)),
        horizon=int(a.get("horizon", HORIZON)),
        patch_len=int(a.get("patch_len", 0)),
        n_layers=int(a.get("n_layers", N_LAYERS)),
        probabilistic=bool(a.get("probabilistic", False)),
    )
    if device is not None:
        model = model.to(device)
    model.load_state_dict(ckpt["model_state"])
    return model
