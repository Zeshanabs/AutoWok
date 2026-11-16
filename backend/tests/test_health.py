from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_endpoint() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["message"] == "Autowok backend is running."


def test_health_endpoint() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_endpoint() -> None:
    # This module uses the real (possibly absent) database and Redis, so both
    # outcomes are valid here; the status code must agree with the payload.
    # tests/test_phase12_operations.py covers each state deterministically.
    response = client.get("/api/v1/ready")
    payload = response.json()
    assert payload["service"] == "Autowok"
    assert "dependencies" in payload
    ready = all(payload["dependencies"].values())
    assert response.status_code == (200 if ready else 503)
    assert payload["status"] == ("ready" if ready else "degraded")
