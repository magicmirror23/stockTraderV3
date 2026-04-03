# Health endpoint tests
"""Smoke-test for the health endpoint."""

from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_health_body():
    response = client.get("/api/v1/health")
    assert response.json() == {"status": "ok"}

