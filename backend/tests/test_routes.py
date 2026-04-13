"""Tests for API routes."""
import pytest
from datetime import datetime, timedelta
from app import create_app, db
from app.models.patient import Patient
from app.models.glucose_reading import GlucoseReading
from app.models.anomaly_detection import AnomalyDetection


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Test client."""
    return app.test_client()


class TestHealthCheck:
    def test_health_endpoint(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.get_json()["status"] == "healthy"


class TestPatientsAPI:
    def test_list_patients_empty(self, client):
        response = client.get("/api/patients/list")
        assert response.status_code == 200
        data = response.get_json()
        assert data["patients"] == []
        assert data["total"] == 0

    def test_create_patient(self, client):
        test_id = "P001"
        test_name = "Test Patient"
        response = client.post(
            "/api/patients/create",
            json={"external_id": test_id, "name": test_name},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["external_id"] == test_id
        assert data["name"] == test_name

    def test_create_patient_missing_fields(self, client):
        response = client.post("/api/patients/create", json={})
        assert response.status_code == 400


class TestGlucoseAPI:
    def test_get_readings(self, client, app):
        with app.app_context():
            p = Patient(external_id="P_G", name="G Patient")
            db.session.add(p)
            db.session.commit()
            
            r = GlucoseReading(patient_id=p.id, timestamp=datetime.utcnow(), glucose_mgdl=120)
            db.session.add(r)
            db.session.commit()

            response = client.get(f"/api/glucose/{p.id}")
            assert response.status_code == 200
            data = response.get_json()
            assert data["count"] == 1
            assert data["readings"][0]["glucose_mgdl"] == 120

    def test_get_latest_reading_not_found(self, client):
        response = client.get("/api/glucose/999/latest")
        assert response.status_code == 404

    def test_get_tir(self, client, app):
        with app.app_context():
            p = Patient(external_id="P_TIR", name="TIR Patient")
            db.session.add(p)
            db.session.commit()
            
            # 2 readings: one in range (100), one high (200)
            r1 = GlucoseReading(patient_id=p.id, timestamp=datetime.utcnow() - timedelta(minutes=5), glucose_mgdl=100)
            r2 = GlucoseReading(patient_id=p.id, timestamp=datetime.utcnow(), glucose_mgdl=200)
            db.session.add_all([r1, r2])
            db.session.commit()

            response = client.get(f"/api/glucose/{p.id}/tir")
            assert response.status_code == 200
            data = response.get_json()
            # TIR calculation is in the service, we trust it for now or verify results
            assert "in_range_pct" in data
            assert data["in_range_pct"] == 50.0

class TestAnomaliesAPI:
    def test_get_anomalies(self, client, app):
        with app.app_context():
            p = Patient(external_id="P_A", name="A Patient")
            db.session.add(p)
            db.session.commit()
            
            a = AnomalyDetection(patient_id=p.id, anomaly_type="missed_bolus", confidence=0.9)
            db.session.add(a)
            db.session.commit()

            response = client.get(f"/api/anomalies/{p.id}")
            assert response.status_code == 200
            data = response.get_json()
            assert data["count"] == 1
            assert data["anomalies"][0]["anomaly_type"] == "missed_bolus"

    def test_acknowledge_anomaly(self, client, app):
        with app.app_context():
            p = Patient(external_id="P_ACK", name="ACK Patient")
            db.session.add(p)
            db.session.commit()
            
            a = AnomalyDetection(patient_id=p.id, anomaly_type="late_bolus", confidence=0.8)
            db.session.add(a)
            db.session.commit()
            
            anomaly_id = a.id

            response = client.post(f"/api/anomalies/{anomaly_id}/acknowledge")
            assert response.status_code == 200
            assert response.get_json()["is_acknowledged"] is True
