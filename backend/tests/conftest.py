# Pytest configuration
"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture()
def client():
    """Return a TestClient bound to the FastAPI app."""
    return TestClient(app)
