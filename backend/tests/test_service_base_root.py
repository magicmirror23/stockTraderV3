# Service app base tests
"""Tests for shared microservice app factory behavior."""

from fastapi.testclient import TestClient

from backend.api.services.base import create_service_app


def test_base_app_root_get_and_head():
    app = create_service_app("Test Service")
    client = TestClient(app)

    get_resp = client.get("/")
    head_resp = client.head("/")

    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "ok"
    assert head_resp.status_code == 200
