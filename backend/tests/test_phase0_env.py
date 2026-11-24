"""
Phase 0 Environment & Setup Verification Tests
Verifies that configuration, directory structure, environment variables,
and local Ollama AI endpoints are properly set up.
"""
import os
import sys
import pytest
import httpx
from pathlib import Path
from cryptography.fernet import Fernet

# Add backend directory to sys.path so backend.app is importable
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings, Settings


def test_settings_load():
    """Verify that Settings loads default and environment values correctly."""
    settings = get_settings()
    assert settings.PROJECT_NAME == "APIForge AI"
    assert settings.OLLAMA_BASE_URL.startswith("http")
    assert len(settings.cors_origins_list) > 0
    assert settings.SECRET_KEY is not None
    assert len(settings.SECRET_KEY) >= 32


def test_fernet_key_validity():
    """Verify that FERNET_KEY is a valid 32-byte base64-encoded key for Fernet encryption."""
    settings = get_settings()
    # Should not raise exception
    cipher = Fernet(settings.FERNET_KEY.encode())
    test_msg = b"test-secret-token"
    token = cipher.encrypt(test_msg)
    assert cipher.decrypt(token) == test_msg


def test_directory_structure():
    """Verify required folder skeleton exists."""
    project_root = BACKEND_DIR.parent
    expected_dirs = [
        BACKEND_DIR / "app",
        BACKEND_DIR / "app" / "routers",
        BACKEND_DIR / "app" / "services",
        BACKEND_DIR / "app" / "agents",
        BACKEND_DIR / "app" / "mock_server",
        BACKEND_DIR / "samples",
        BACKEND_DIR / "tests",
        project_root / "eval",
        project_root / "demo",
    ]
    for d in expected_dirs:
        assert d.exists() and d.is_dir(), f"Expected directory missing: {d}"


@pytest.mark.asyncio
async def test_ollama_connectivity():
    """Verify Ollama server is reachable and reports status."""
    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(url)
            assert resp.status_code == 200, f"Ollama returned status {resp.status_code}"
            data = resp.json()
            assert "models" in data, "Ollama response missing 'models' field"
            model_names = [m.get("name", "") for m in data.get("models", [])]
            # Ensure at least one model is available (e.g. qwen2.5:3b, qwen2.5:7b-instruct, or nomic-embed-text)
            assert len(model_names) > 0, "No models found in Ollama"
        except httpx.ConnectError:
            pytest.fail(f"Could not connect to Ollama at {settings.OLLAMA_BASE_URL}. Ensure Ollama is running.")
