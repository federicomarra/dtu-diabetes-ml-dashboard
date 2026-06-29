"""
Stateless ML inference microservice (Flask, port 5000).

The C# backend orchestrates; this service only does INFERENCE. The backend POSTs
a patient's `histories` window as JSON; we run XCHANNEL detection + the missed/late
rule layer and return the anomalies (filtered to the frontend-chosen threshold).
The backend writes them to the DB and returns them to the caller — this service
never touches the database.

Design (see ml/docs/SYSTEM_INTEGRATION.md):
  - model loaded ONCE at startup (torch + checkpoint = seconds; never per request).
  - `patient_id` is request-envelope metadata, echoed back; the math ignores it.
  - confidence = the characterisation head's class probability when available, else
    a score-derived fallback. It is a SURPRISE score, NOT a calibrated probability —
    labelled accordingly. Only `missed_bolus`/`late_bolus` are surfaced (others = future work).

Request  (POST /infer):
  {"patient_id": 12, "threshold_k": 3.0, "min_event_min": 30, "max_events": 50,
   "histories": [{"timestamp": "...", "glucose_mmoll": 7.1, "insulin_u": 0.01, "cho_grams": 0}, ...]}
Response:
  {"patient_id": 12, "n_windows": ..., "anomalies": [
     {"start": "<iso>", "end": "<iso>", "start_minute": int, "duration_min": int,
      "anomaly_type": "missed_bolus"|"late_bolus", "confidence": 0.0-1.0, "score": float}]}
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import numpy as np
import torch
from flask import Flask, jsonify, request

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from inference.loader import histories_to_array, derive_events, zscore_channels  # noqa: E402
from inference.diary import build_diary  # noqa: E402
from models.xchannel.model import forecaster_from_ckpt  # noqa: E402
from characterization.head import CharacterizationHead  # noqa: E402

CKPT_DIR = Path(os.environ.get("CKPT_DIR", "ml/data/checkpoints"))
DETECTOR_CKPT = Path(os.environ.get("DETECTOR_CKPT", CKPT_DIR / "xchannel_nll_pooled_best.pt"))
HEAD_CKPT = Path(os.environ.get("HEAD_CKPT", CKPT_DIR / "characterization_head.pt"))

# DB anomaly_type CHECK allows only these two; everything else stays future work.
_TYPE_MAP = {"missed": "missed_bolus", "late": "late_bolus"}

app = Flask(__name__)
_MODEL: dict = {}


def _load_model() -> dict:
    """Load detector + characterisation head + OOD params ONCE (called at startup)."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    det = forecaster_from_ckpt(torch.load(DETECTOR_CKPT, map_location=device), device)
    det.eval()
    hk = torch.load(HEAD_CKPT, map_location=device)
    head = CharacterizationHead().to(device)
    head.load_state_dict(hk["head_state"])
    head.eval()
    mu, inv_cov = np.asarray(hk["ood_mu"]), np.asarray(hk["ood_inv_cov"])
    radius = float(hk.get("ood_radius", np.sqrt(len(mu)) * 3.0))
    return {"device": device, "detector": det, "head": head,
            "ood_mu": mu, "ood_inv_cov": inv_cov, "ood_radius": radius}


@app.get("/health")
def health():
    ok = bool(_MODEL)
    return jsonify(status="ok" if ok else "loading",
                   detector=DETECTOR_CKPT.name, head=HEAD_CKPT.name,
                   device=str(_MODEL.get("device", "n/a"))), (200 if ok else 503)


@app.post("/infer")
def infer():
    body = request.get_json(force=True, silent=True) or {}
    rows = body.get("histories") or []
    patient_id = body.get("patient_id")
    threshold_k = float(body.get("threshold_k", 3.0))
    min_event_min = int(body.get("min_event_min", 30))
    max_events = int(body.get("max_events", 50))

    arr, valid, t0 = histories_to_array(rows)
    if arr.shape[0] == 0 or valid.sum() == 0:
        return jsonify(patient_id=patient_id, n_windows=0, anomalies=[]), 200

    meals, boluses = derive_events(arr)
    z = zscore_channels(arr)
    events = build_diary(
        z, valid,
        detector=_MODEL["detector"], head=_MODEL["head"],
        ood_mu=_MODEL["ood_mu"], ood_inv_cov=_MODEL["ood_inv_cov"], ood_radius=_MODEL["ood_radius"],
        meals=meals, boluses=boluses, device=_MODEL["device"],
        threshold_k=threshold_k, min_event_min=min_event_min,
    )

    out = []
    for e in events:
        # type = deterministic rule label first, else similarity head's top class
        label = e.rule_label or e.soft_label
        atype = _TYPE_MAP.get(label)
        if atype is None:                       # large/prolonged/anaerobic/normal → future work
            continue
        conf = float(e.class_probs.get(label, 0.0)) if e.class_probs else 0.0
        out.append({
            "start": (t0 + timedelta(minutes=e.start_min)).isoformat(),
            "end": (t0 + timedelta(minutes=e.start_min + e.duration_min)).isoformat(),
            "start_minute": int(e.start_min),
            "duration_min": int(e.duration_min),
            "anomaly_type": atype,
            "confidence": round(conf, 3),       # head class prob — a surprise score, not calibrated
            "score": round(float(e.anomaly_score), 4),
        })
    out.sort(key=lambda a: a["score"], reverse=True)
    return jsonify(patient_id=patient_id, n_windows=int(valid.sum()),
                   anomalies=out[:max_events]), 200


# Load the model at import time so gunicorn/flask workers are ready before the first request.
try:
    _MODEL = _load_model()
    print(f"[ml-service] model ready: {DETECTOR_CKPT.name} + {HEAD_CKPT.name} on {_MODEL['device']}",
          flush=True)
except Exception as exc:  # keep the service up so /health reports 'loading' instead of crashing
    print(f"[ml-service] WARNING model load failed: {exc}", flush=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
