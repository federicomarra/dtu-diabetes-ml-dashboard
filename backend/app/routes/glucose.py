"""Glucose data API routes."""
from datetime import datetime
from flask import jsonify, request
from flask_smorest import Blueprint
from app import db
from app.models.glucose_reading import GlucoseReading
from app.services.glucose_service import GlucoseService

glucose_bp = Blueprint(
    "glucose", __name__, description="Glucose readings and statistics"
)


@glucose_bp.route("/<int:patient_id>", methods=["GET"])
def get_glucose_readings(patient_id: int):
    """Get glucose readings for a patient within an optional time range.

    Query params:
        start: ISO datetime string (optional)
        end: ISO datetime string (optional)
        limit: max results (default 500)
    """
    start = request.args.get("start")
    end = request.args.get("end")
    limit = request.args.get("limit", 500, type=int)

    query = GlucoseReading.query.filter_by(patient_id=patient_id)

    if start:
        query = query.filter(GlucoseReading.timestamp >= datetime.fromisoformat(start))
    if end:
        query = query.filter(GlucoseReading.timestamp <= datetime.fromisoformat(end))

    readings = (
        query.order_by(GlucoseReading.timestamp.desc()).limit(limit).all()
    )

    return jsonify({
        "patient_id": patient_id,
        "readings": [r.to_dict() for r in readings],
        "count": len(readings),
    })


@glucose_bp.route("/<int:patient_id>/tir", methods=["GET"])
def get_time_in_range(patient_id: int):
    """Get time-in-range statistics for a patient.

    Query params:
        start: ISO datetime string (optional)
        end: ISO datetime string (optional)
    """
    start = request.args.get("start")
    end = request.args.get("end")

    tir = GlucoseService.calculate_time_in_range(patient_id, start, end)
    return jsonify(tir)


@glucose_bp.route("/<int:patient_id>/latest", methods=["GET"])
def get_latest_reading(patient_id: int):
    """Get the most recent glucose reading for a patient."""
    reading = (
        GlucoseReading.query
        .filter_by(patient_id=patient_id)
        .order_by(GlucoseReading.timestamp.desc())
        .first()
    )

    if not reading:
        return jsonify({"error": "No readings found"}), 404

    return jsonify(reading.to_dict())
