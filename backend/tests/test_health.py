"""
Health Check Endpoint Tests
Verifies that GET /health and GET /api/health report backend,
database, and Ollama service statuses accurately.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_endpoint():
    """Verify root endpoint responds with status online."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "APIForge AI" in data["app"]


def test_health_endpoint_structure():
    """Verify GET /health returns structured JSON with expected service keys."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()

    assert "status" in data
    assert "timestamp" in data
    assert "version" in data
    assert "services" in data

    services = data["services"]
    assert "backend" in services
    assert services["backend"]["status"] == "ok"

    assert "database" in services
    assert services["database"]["status"] == "ok"
    assert services["database"]["connected"] is True
    assert services["database"]["dialect"] == "sqlite"

    assert "ollama" in services
    assert services["ollama"]["connected"] is True
    assert "models" in services["ollama"]
    assert "chat_model" in services["ollama"]["models"]
    assert "embed_model" in services["ollama"]["models"]


def test_api_health_alias():
    """Verify GET /api/health alias matches /health."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["services"]["backend"]["status"] == "ok"
    assert data["services"]["database"]["connected"] is True
