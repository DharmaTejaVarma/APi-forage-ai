"""
Phase 3 API Connections and Endpoints Test Suite
Tests API connection creation, encrypted credentials management, secret masking,
OpenAPI import, cascading endpoint deletion, and user-level data isolation.
"""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.models import User, APIConnection, Endpoint
from app.security import decrypt_secret

client = TestClient(app)

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "samples" / "mock_openapi.json"


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield


def _create_user_and_token(email: str, password: str = "Password123!") -> tuple[int, str]:
    """Helper to register and login a user, returning (user_id, token)."""
    client.post("/auth/register", json={"email": email, "password": password})
    r_login = client.post("/auth/login", json={"email": email, "password": password})
    token = r_login.json()["access_token"]
    user_id = r_login.json()["user"]["id"]
    return user_id, token


# ============================================================================
# API Connection CRUD Tests
# ============================================================================

def test_create_connection_with_encrypted_credentials():
    """Verify connection creation securely encrypts credentials with Fernet and masks them in response."""
    user_id, token = _create_user_and_token("conn_tester_1@apiforge.ai")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": "Stripe Payments API",
        "description": "Payment Gateway",
        "base_url": "https://api.stripe.com/v1",
        "auth_type": "bearer",
        "credentials": {"api_key": "sk_test_secret_stripe_token_12345"},
        "default_headers": {"X-Custom": "header"},
    }

    response = client.post("/connections", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()

    assert data["name"] == "Stripe Payments API"
    assert data["has_credentials"] is True
    # Crucial: Raw secret must NOT be exposed in the response
    assert "sk_test_secret" not in json.dumps(data)
    conn_id = data["id"]

    # Verify that in the database, credentials are encrypted
    with SessionLocal() as db:
        conn_db = db.query(APIConnection).filter_by(id=conn_id).first()
        assert conn_db is not None
        assert conn_db.encrypted_credentials != "sk_test_secret_stripe_token_12345"
        # Decrypt with Fernet and verify original plaintext
        decrypted_json = decrypt_secret(conn_db.encrypted_credentials)
        decrypted_dict = json.loads(decrypted_json)
        assert decrypted_dict["api_key"] == "sk_test_secret_stripe_token_12345"

        # Clean up
        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()


def test_connections_user_isolation():
    """Verify User A cannot see, retrieve, or update User B's connections."""
    user_a_id, token_a = _create_user_and_token("user_a@apiforge.ai")
    user_b_id, token_b = _create_user_and_token("user_b@apiforge.ai")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates a connection
    r_create = client.post(
        "/connections",
        json={"name": "User A Private API", "base_url": "https://api.a.com"},
        headers=headers_a,
    )
    conn_a_id = r_create.json()["id"]

    # User B lists connections -> User A's connection must NOT be in the list
    r_list_b = client.get("/connections", headers=headers_b)
    assert r_list_b.status_code == 200
    b_ids = [c["id"] for c in r_list_b.json()]
    assert conn_a_id not in b_ids

    # User B attempts to access User A's connection directly -> 404 Not Found
    r_get_b = client.get(f"/connections/{conn_a_id}", headers=headers_b)
    assert r_get_b.status_code == 404

    # Clean up
    with SessionLocal() as db:
        for uid in [user_a_id, user_b_id]:
            u = db.query(User).filter_by(id=uid).first()
            if u:
                db.delete(u)
                db.commit()


def test_import_openapi_and_cascade_delete():
    """Verify importing OpenAPI spec creates endpoints and deleting connection cascade-deletes endpoints."""
    user_id, token = _create_user_and_token("openapi_import_user@apiforge.ai")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create connection
    r_create = client.post(
        "/connections",
        json={"name": "Mock Store Connection", "base_url": "http://127.0.0.1:8000/mock/api/v1"},
        headers=headers,
    )
    assert r_create.status_code == 201
    conn_id = r_create.json()["id"]

    # 2. Load mock OpenAPI spec
    with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
        spec_content = json.load(f)

    # 3. Import spec into connection
    r_import = client.post(
        f"/connections/{conn_id}/import-openapi",
        json=spec_content,
        headers=headers,
    )
    assert r_import.status_code == 200
    endpoints = r_import.json()
    assert len(endpoints) == 5

    paths = [ep["path"] for ep in endpoints]
    assert "/products" in paths
    assert "/products/{id}" in paths
    assert "/discounts/calculate" in paths
    assert "/orders" in paths
    assert "/orders/{id}" in paths

    # 4. Query /endpoints endpoint with filter
    r_ep_list = client.get(f"/endpoints?connection_id={conn_id}", headers=headers)
    assert r_ep_list.status_code == 200
    assert len(r_ep_list.json()) == 5

    # 5. Delete connection
    r_delete = client.delete(f"/connections/{conn_id}", headers=headers)
    assert r_delete.status_code == 204

    # 6. Verify endpoints are cascade-deleted
    with SessionLocal() as db:
        remaining_eps = db.query(Endpoint).filter_by(connection_id=conn_id).all()
        assert len(remaining_eps) == 0

        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()
