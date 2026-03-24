"""Tests for API routes."""
import pytest
from app import create_app, db


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
        response = client.get("/api/patients/")
        assert response.status_code == 200
        data = response.get_json()
        assert data["patients"] == []
        assert data["total"] == 0

    def test_create_patient(self, client):
        response = client.post(
            "/api/patients/",
            json={"external_id": "P001", "name": "Test Patient"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["external_id"] == "P001"
        assert data["name"] == "Test Patient"

    def test_create_patient_missing_fields(self, client):
        response = client.post("/api/patients/", json={})
        assert response.status_code == 400


class TestGlucoseAPI:
    def test_get_readings_no_patient(self, client):
        response = client.get("/api/glucose/999/latest")
        assert response.status_code == 404
