"""Patient API routes."""
from flask import jsonify, request
from flask_smorest import Blueprint
from app import db
from app.models.patient import Patient

patients_bp = Blueprint(
    "patients", __name__, description="Patient management"
)


@patients_bp.route("/list", methods=["GET"], endpoint="list_patients")
def list_patients():
    """List all patients with optional pagination."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    pagination = Patient.query.order_by(Patient.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "patients": [p.to_dict() for p in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    })


@patients_bp.route("/<int:patient_id>", methods=["GET"])
def get_patient(patient_id: int):
    """Get a single patient by ID."""
    patient = Patient.query.get_or_404(patient_id)
    return jsonify(patient.to_dict())


@patients_bp.route("/create", methods=["POST"], endpoint="create_patient")
def create_patient():
    """Create a new patient."""
    data = request.get_json()

    if not data or not data.get("external_id") or not data.get("name"):
        return jsonify({"error": "external_id and name are required"}), 400

    patient = Patient(
        external_id=data["external_id"],
        name=data["name"],
        diabetes_type=data.get("diabetes_type", "T1D"),
    )
    db.session.add(patient)
    db.session.commit()

    return jsonify(patient.to_dict()), 201
