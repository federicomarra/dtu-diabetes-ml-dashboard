"""
Stateless ML inference microservice (Flask, port 5001).

The C# backend orchestrates; this service only does INFERENCE. The backend POSTs
a patient's `histories` window as JSON; we run XCHANNEL detection + the missed/late
rule layer and return the anomalies (filtered to the frontend-chosen threshold).
The backend writes them to the DB and returns them to the caller - this service
never touches the database.

Design:
  - DETECTOR-ONLY for the demo: the characterisation head is dropped. For a
    missed/late-only demo it is redundant - the rule layer labels missed/late
    deterministically from logged carbs+insulin, and anomaly_strength comes from the
    score. No head checkpoint, no MC-dropout/OOD, one forward pass per window.
  - model loaded ONCE at startup (torch + checkpoint = seconds; never per request).
  - `patient_id` is request-envelope metadata, echoed back; the math ignores it.
  - anomaly_strength = the event score's percentile among THIS patient's windows
    (0-100%) - the honest, self-calibrating UI knob. Only `missed_bolus`/`late_bolus`
    are surfaced (other classes = future work).

Request  (POST /infer):
  {"patient_id": 12, "threshold_k": 3.0, "min_event_min": 30, "max_events": 0,  # 0 = no cap (default); >0 keeps top-k by severity
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
      "severity": float,               # sigma above THIS patient's baseline median (interpretable, stable across queries)
      "anomaly_strength": 0.0-100.0,   # severity relative to the strongest flag - magnitude bar (UI knob)
      "score": float}]}                # raw surprise (forecast residual)
The frontend thresholds on `severity` (sigma, e.g. "show > 3sigma") or `anomaly_strength`
(0-100 bar). Both self-calibrate per patient - no absolute score knowledge needed.
Severity is the honest cross-query number; strength is a within-query display bar.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import torch
from flask import Flask
from flask.views import MethodView
from flask_smorest import Api, Blueprint
import marshmallow as ma

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from inference.loader import (histories_to_array, derive_events, zscore_channels,  # noqa: E402
                              _Meal, _Bolus, _parse_ts)
from inference.detect import detect  # noqa: E402
from models.xchannel.model import forecaster_from_ckpt  # noqa: E402

CKPT_DIR = Path(os.environ.get("CKPT_DIR", "ml/data/checkpoints"))
DETECTOR_CKPT = Path(os.environ.get("DETECTOR_CKPT", CKPT_DIR / "xchannel_nll_pooled_best.pt"))

# ─── Marshmallow schemas ──────────────────────────────────────────────────────

class HistoryPointSchema(ma.Schema):
    timestamp  = ma.fields.Str(required=True, metadata={"description": "ISO-8601 timestamp"})
    glucose_mmoll = ma.fields.Float(required=True, allow_none=True)
    insulin_u  = ma.fields.Float(load_default=0.0, allow_none=True)
    cho_grams  = ma.fields.Float(load_default=0.0, allow_none=True)

class MealEventSchema(ma.Schema):
    timestamp = ma.fields.Str(required=True)
    carb_g    = ma.fields.Float(required=True, metadata={"description": "Carbohydrates in grams"})

class BolusEventSchema(ma.Schema):
    timestamp = ma.fields.Str(required=True)
    units     = ma.fields.Float(required=True, metadata={"description": "Bolus units"})

class InferRequestSchema(ma.Schema):
    patient_id    = ma.fields.Int(required=True, metadata={"description": "Patient identifier echoed back in the response"})
    threshold_k   = ma.fields.Float(load_default=3.0, metadata={"description": "Anomaly threshold in σ above baseline"})
    min_event_min = ma.fields.Int(load_default=30, metadata={"description": "Minimum event duration in minutes"})
    max_events    = ma.fields.Int(load_default=0, metadata={"description": "Maximum number of anomalies returned (0 = no cap)"})
    histories     = ma.fields.List(ma.fields.Nested(HistoryPointSchema), required=True, metadata={"description": "CGM + bolus + carb time-series"})
    meals         = ma.fields.List(ma.fields.Nested(MealEventSchema), load_default=None, allow_none=True, metadata={"description": "Logged meal events (optional rule input)"})
    boluses       = ma.fields.List(ma.fields.Nested(BolusEventSchema), load_default=None, allow_none=True, metadata={"description": "Logged bolus events (optional rule input)"})

class AnomalySchema(ma.Schema):
    start            = ma.fields.Str()
    end              = ma.fields.Str()
    start_minute     = ma.fields.Int()
    duration_min     = ma.fields.Int()
    anomaly_type     = ma.fields.Str(metadata={"description": "missed_bolus or late_bolus"})
    description      = ma.fields.Str()
    rule_confirmed   = ma.fields.Bool()
    severity         = ma.fields.Float(metadata={"description": "σ above this patient's baseline"})
    anomaly_strength = ma.fields.Float(metadata={"description": "0-100 bar relative to strongest flag"})
    score            = ma.fields.Float(metadata={"description": "Raw forecast residual"})

class InferResponseSchema(ma.Schema):
    patient_id = ma.fields.Int(allow_none=True)
    n_windows  = ma.fields.Int()
    anomalies  = ma.fields.List(ma.fields.Nested(AnomalySchema))

class HealthResponseSchema(ma.Schema):
    status   = ma.fields.Str(metadata={"description": "ok | loading"})
    detector = ma.fields.Str()
    device   = ma.fields.Str()


# ─── Flask app + smorest Api ──────────────────────────────────────────────────

app = Flask(__name__)
app.config.update(
    API_TITLE="Diabetes ML Inference API",
    API_VERSION="v1",
    OPENAPI_VERSION="3.0.3",
    OPENAPI_URL_PREFIX="/",
    OPENAPI_SWAGGER_UI_PATH="/swagger/",
    OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist/",
)
api = Api(app)

_MODEL: dict = {}


def _load_model() -> dict:
    """Load the detector ONCE (called at startup). No head — detector-only demo."""
    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")
    det = forecaster_from_ckpt(torch.load(DETECTOR_CKPT, map_location=device), device)
    det.eval()
    return {"device": device, "detector": det}
  

# ─── Blueprints ───────────────────────────────────────────────────────────────

blp = Blueprint("ml", __name__, description="Inference endpoints")

@blp.route("/health")
class Health(MethodView):
    @blp.response(200, HealthResponseSchema, description="Service is healthy and model is loaded")
    @blp.alt_response(503, description="Service is still loading the model")
    def get(self):
        """Health check — returns model status and device."""
        ok = bool(_MODEL)
        from flask import jsonify
        return jsonify(
            status="ok" if ok else "loading",
            detector=DETECTOR_CKPT.name,
            device=str(_MODEL.get("device", "n/a"))
        ), (200 if ok else 503)


@blp.route("/infer")
class Infer(MethodView):
    @blp.arguments(InferRequestSchema)
    @blp.response(200, InferResponseSchema, description="Detected anomalies for the patient")
    def post(self, body):
        """
        Run anomaly detection on a patient's CGM history window.

        Pass the full `histories` array plus optional `meals` / `boluses` event
        streams. The service runs XCHANNEL detection + the missed/late rule layer
        and returns ranked anomalies. It never touches the database.
        """
        from flask import jsonify
        
        rows = body.get("histories") or []
        patient_id = body.get("patient_id")
        threshold_k = float(body.get("threshold_k", 3.0))
        min_event_min = int(body.get("min_event_min", 30))
        # 0 (default) = no cap: the backend stores ALL anomalies and the frontend's
        # severity slider filters at read time; a silent top-k here would make every
        # patient show the same saturated count. A positive value caps (opt-in).
        max_events = int(body.get("max_events", 0))

        arr, valid, t0 = histories_to_array(rows)
        if arr.shape[0] == 0 or valid.sum() == 0 or t0 is None:
            return jsonify(patient_id=patient_id, n_windows=0, anomalies=[]), 200
        assert t0 is not None  # narrowed by the guard above (non-empty rows -> a start time)

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
        events, _ = detect(
            z, valid, detector=_MODEL["detector"], device=_MODEL["device"],
            meals=meals, boluses=boluses, threshold_k=threshold_k, min_event_min=min_event_min,
        )

        # 0-100 strength bar = each event's severity (sigma above baseline) relative to the
        # STRONGEST surfaced anomaly -> magnitude-discriminating (the true outlier reads 100%,
        # marginal flags read low), unlike a percentile that saturates at ~100% for all of them.
        sev_max = max((e.severity for e in events), default=1.0) or 1.0

        def strength(sev: float) -> float:
            return round(100.0 * sev / sev_max, 1)

        # DETECTION-ANCHORED naming: the detector surfaces the excursion; the rule names it
        # by the bolus that should have covered it (see rules.classify_detection). This is a
        # missed/late-bolus demo, so we surface ONLY those two - an excursion with a timely
        # covering bolus (rule_label is None: e.g. a correctly-bolused large meal) is a real
        # anomaly but not a BOLUS-timing one, so it is not shown here. DB type is missed/late
        # (CHECK-constrained); both surfaced types are rule-confirmed.
        out = []
        for e in events:
            if e.rule_label == "late":
                atype, desc = "late_bolus", "bolus delivered well after the glucose rise began (detection-anchored)"
            elif e.rule_label == "missed":
                atype, desc = "missed_bolus", "glucose excursion with no covering bolus (detection-anchored)"
            else:
                continue   # timely bolus covers the excursion -> not a missed/late-bolus event
            out.append({
                "start": (t0 + timedelta(minutes=e.start_min)).isoformat(),
                "end": (t0 + timedelta(minutes=e.start_min + e.duration_min)).isoformat(),
                "start_minute": int(e.start_min),
                "duration_min": int(e.duration_min),
                "anomaly_type": atype,
                "description": desc,
                "rule_confirmed": e.rule_label is not None,
                "severity": round(float(e.severity), 2),        # sigma above this patient's baseline (interpretable, stable)
                "anomaly_strength": strength(e.severity),        # 0-100 bar relative to the strongest flag (UI knob)
                "score": round(float(e.anomaly_score), 4),      # raw surprise (forecast residual)
            })
        out.sort(key=lambda a: a["severity"], reverse=True)
        if max_events > 0:
            out = out[:max_events]
        return jsonify(patient_id=patient_id, n_windows=int(valid.sum()),
                       anomalies=out), 200


api.register_blueprint(blp)


# ─── Startup ──────────────────────────────────────────────────────────────────

# Load the model at import time so gunicorn/flask workers are ready before the first request.
try:
    _MODEL = _load_model()
    print(f"[ml-service] model ready: {DETECTOR_CKPT.name} on {_MODEL['device']}", flush=True)
except Exception as exc:  # keep the service up so /health reports 'loading' instead of crashing
    print(f"[ml-service] WARNING model load failed: {exc}", flush=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)))
