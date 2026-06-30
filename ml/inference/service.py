"""
Stateless ML inference microservice (Flask, port 5000).

The C# backend orchestrates; this service only does INFERENCE. The backend POSTs
a patient's `histories` window as JSON; we run XCHANNEL detection + the missed/late
rule layer and return the anomalies (filtered to the frontend-chosen threshold).
The backend writes them to the DB and returns them to the caller — this service
never touches the database.

Design (see ml/docs/SYSTEM_INTEGRATION.md):
  - DETECTOR-ONLY for the demo: the characterisation head is dropped. For a
    missed/late-only demo it is redundant — the rule layer labels missed/late
    deterministically from logged carbs+insulin, and anomaly_strength comes from the
    score. No head checkpoint, no MC-dropout/OOD, one forward pass per window.
  - model loaded ONCE at startup (torch + checkpoint = seconds; never per request).
  - `patient_id` is request-envelope metadata, echoed back; the math ignores it.
  - anomaly_strength = the event score's percentile among THIS patient's windows
    (0-100%) — the honest, self-calibrating UI knob. Only `missed_bolus`/`late_bolus`
    are surfaced (other classes = future work).

Request  (POST /infer):
  {"patient_id": 12, "threshold_k": 3.0, "min_event_min": 30, "max_events": 50,
   "histories": [{"timestamp": "...", "glucose_mmoll": 7.1, "insulin_u": 0.01, "cho_grams": 0}, ...],
   "meals":   [{"timestamp": "...", "carb_g": 60}, ...],   # optional: logged meal events (rule input)
   "boluses": [{"timestamp": "...", "units": 5.0}, ...]}   # optional: logged bolus events (rule input)
  histories.cho_grams = ANNOUNCED carbs (detector input, as trained); meals/boluses are the
  SEPARATE logged-event stream the rule uses to name missed vs late. If meals/boluses are
  omitted, they are derived from the carb/insulin channels (degrades to announced-only).
Response:
  {"patient_id": 12, "n_windows": ..., "anomalies": [
     {"start": "<iso>", "end": "<iso>", "start_minute": int, "duration_min": int,
      "anomaly_type": "missed_bolus"|"late_bolus",   # DB-allowed type (rule-named or default)
      "description": str,              # honest qualifier (rule-confirmed vs model-detected/unconfirmed)
      "rule_confirmed": bool,          # True = a logged meal/bolus pattern named it; False = detector-only
      "anomaly_strength": 0.0-100.0,   # score percentile vs THIS patient's windows — the honest UI knob
      "score": float}]}                # raw surprise (forecast residual)
The frontend thresholds on `anomaly_strength` ("show anomalies above X%"); it is
self-calibrating per patient, so no absolute score knowledge is needed.
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
from inference.loader import (histories_to_array, derive_events, zscore_channels,  # noqa: E402
                              _Meal, _Bolus, _parse_ts)
from inference.detect import detect  # noqa: E402
from models.xchannel.model import forecaster_from_ckpt  # noqa: E402

CKPT_DIR = Path(os.environ.get("CKPT_DIR", "ml/data/checkpoints"))
DETECTOR_CKPT = Path(os.environ.get("DETECTOR_CKPT", CKPT_DIR / "xchannel_nll_pooled_best.pt"))

app = Flask(__name__)
_MODEL: dict = {}


def _load_model() -> dict:
    """Load the detector ONCE (called at startup). No head — detector-only demo."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    det = forecaster_from_ckpt(torch.load(DETECTOR_CKPT, map_location=device), device)
    det.eval()
    return {"device": device, "detector": det}


@app.get("/health")
def health():
    ok = bool(_MODEL)
    return jsonify(status="ok" if ok else "loading",
                   detector=DETECTOR_CKPT.name,
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

    # Rule input = logged meal/bolus EVENTS (actual carb vs bolus timing), a stream
    # SEPARATE from the detector's announced-carb histories channel. The backend sends
    # them from the meals/insulins tables; minutes are relative to the histories start.
    # Fall back to deriving from the (announced) carb channel only if not provided.
    def _to_min(ts):
        return int(round((_parse_ts(ts) - t0).total_seconds() / 60.0))
    body_meals = body.get("meals")
    body_boluses = body.get("boluses")
    if body_meals is not None or body_boluses is not None:
        meals = [_Meal(_to_min(m["timestamp"]), float(m["carb_g"])) for m in (body_meals or [])]
        boluses = [_Bolus(_to_min(b["timestamp"]), float(b["units"])) for b in (body_boluses or [])]
    else:
        meals, boluses = derive_events(arr)

    z = zscore_channels(arr)
    events, all_scores = detect(
        z, valid, detector=_MODEL["detector"], device=_MODEL["device"],
        meals=meals, boluses=boluses, threshold_k=threshold_k, min_event_min=min_event_min,
    )

    def strength(score: float) -> float:
        # honest per-patient 0-100%: how anomalous vs ALL of this patient's windows.
        # Self-calibrating, score-derived — no absolute threshold knowledge needed.
        if all_scores.size == 0:
            return 0.0
        return round(100.0 * float((all_scores < score).mean()), 1)

    # DETECTOR-SURFACED: every detected excursion is an anomaly (the model's contribution).
    # The rule only NAMES it when a logged meal/bolus pattern coincides; otherwise it's an
    # honest model-detected excursion with no logged cause. On real data the rule rarely
    # coincides (proxy labels are sparse), so gating on it would surface ~nothing — hence
    # we surface the detection and annotate. DB type stays missed/late (CHECK); the honest
    # qualifier lives in `description`.
    out = []
    for e in events:
        if e.rule_label == "late":
            atype, desc = "late_bolus", "delayed bolus after a logged meal (rule-confirmed)"
        elif e.rule_label == "missed":
            atype, desc = "missed_bolus", "logged meal with no bolus (rule-confirmed)"
        else:
            atype, desc = "missed_bolus", "model-detected excursion; no logged cause (unconfirmed)"
        out.append({
            "start": (t0 + timedelta(minutes=e.start_min)).isoformat(),
            "end": (t0 + timedelta(minutes=e.start_min + e.duration_min)).isoformat(),
            "start_minute": int(e.start_min),
            "duration_min": int(e.duration_min),
            "anomaly_type": atype,
            "description": desc,
            "rule_confirmed": e.rule_label is not None,
            "anomaly_strength": strength(e.anomaly_score),  # per-patient score percentile 0-100% (UI knob)
            "score": round(float(e.anomaly_score), 4),      # raw surprise (forecast residual)
        })
    out.sort(key=lambda a: a["anomaly_strength"], reverse=True)
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
