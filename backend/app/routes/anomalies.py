"""Anomaly detection API routes."""
from flask import jsonify, request
from flask_smorest import Blueprint
from app import db
from app.models.anomaly_detection import AnomalyDetection

anomalies_bp = Blueprint(
    "anomalies", __name__, description="Anomaly detection results"
)


@anomalies_bp.route("/<int:patient_id>", methods=["GET"])
def get_anomalies(patient_id: int):
    """Get detected anomalies for a patient.

    Query params:
        acknowledged: filter by acknowledgment status (true/false)
        limit: max results (default 50)
    """
    limit = request.args.get("limit", 50, type=int)
    acknowledged = request.args.get("acknowledged")

    query = AnomalyDetection.query.filter_by(patient_id=patient_id)

    if acknowledged is not None:
        query = query.filter_by(is_acknowledged=acknowledged.lower() == "true")

    anomalies = (
        query.order_by(AnomalyDetection.detected_at.desc()).limit(limit).all()
    )

    return jsonify({
        "patient_id": patient_id,
        "anomalies": [a.to_dict() for a in anomalies],
        "count": len(anomalies),
    })


@anomalies_bp.route("/<int:anomaly_id>/acknowledge", methods=["POST"])
def acknowledge_anomaly(anomaly_id: int):
    """Mark an anomaly as acknowledged by a clinician."""
    anomaly = AnomalyDetection.query.get_or_404(anomaly_id)
    anomaly.is_acknowledged = True
    db.session.commit()

    return jsonify(anomaly.to_dict())
