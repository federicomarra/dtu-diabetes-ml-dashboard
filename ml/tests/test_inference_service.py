"""Tests for the /infer endpoint's max_events contract (ml/inference/service.py).

The backend stores ALL returned anomalies and filters at read time (severity
slider), so by default the service must NOT truncate. An explicit positive
max_events still caps (opt-in).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inference import service  # noqa: E402
from inference.detect import Detection  # noqa: E402


def _fake_events(n: int) -> list[Detection]:
    """n detections with distinct severities (descending order not required).
    rule_label='missed' so the service surfaces them (None = timely = skipped)."""
    return [
        Detection(start_min=i * 10, duration_min=30, anomaly_score=1.0 + i,
                  severity=2.0 + 0.01 * i, rule_label="missed")
        for i in range(n)
    ]


def _histories() -> list[dict]:
    """Two glucose rows a minute apart -> non-empty grid, valid.sum() > 0."""
    return [
        {"timestamp": "2026-01-01T00:00:00", "glucose_mmoll": 7.0},
        {"timestamp": "2026-01-01T00:01:00", "glucose_mmoll": 7.5},
    ]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(service._MODEL, "detector", object())
    monkeypatch.setitem(service._MODEL, "device", "cpu")
    monkeypatch.setattr(service, "detect",
                        lambda *a, **k: (_fake_events(60), None))
    return service.app.test_client()


def test_no_max_events_returns_all(client):
    resp = client.post("/infer", json={"patient_id": 1, "histories": _histories()})
    assert resp.status_code == 200
    assert len(resp.get_json()["anomalies"]) == 60


def test_explicit_max_events_caps(client):
    resp = client.post("/infer", json={"patient_id": 1, "max_events": 10,
                                       "histories": _histories()})
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["anomalies"]) == 10
    # cap keeps the strongest: sorted by severity descending
    sevs = [a["severity"] for a in body["anomalies"]]
    assert sevs == sorted(sevs, reverse=True)
