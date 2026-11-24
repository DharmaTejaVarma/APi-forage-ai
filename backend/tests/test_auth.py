"""
Phase 2 Authentication & Security Test Suite
Tests password hashing (bcrypt), Fernet credential encryption, secret masking,
JWT generation and verification, user registration, login, and Role-Based Access Control (RBAC).
"""
import pytest
from datetime import timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db import SessionLocal, init_db
from app.models import User, AuditLog
from app.security import (
    get_password_hash,
    verify_password,
    encrypt_secret,
    decrypt_secret,
    mask_secret,
    create_access_token,
    decode_access_token,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield


# ============================================================================
# Unit Tests: Security Utilities
# ============================================================================

def test_password_hashing():
    """Verify bcrypt hash generation and verification."""
    password = "SuperSecretPassword123!"
    hashed = get_password_hash(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_fernet_credential_encryption():
    """Verify Fernet symmetric encryption and decryption."""
    api_key = "sk_live_9876543210abcdefg"
    encrypted = encrypt_secret(api_key)

    assert encrypted != api_key
    assert len(encrypted) > 20
    decrypted = decrypt_secret(encrypted)
    assert decrypted == api_key


def test_secret_masking():
    """Verify secret masking for logs and API responses."""
    assert mask_secret("sk_live_1234567890abcdef", 4) == "sk_l...cdef"
    assert mask_secret("short", 4) == "********"
    assert mask_secret("") == ""


def test_jwt_creation_and_decoding():
    """Verify JWT creation, claim decoding, and expiration validation."""
    data = {"sub": "42", "email": "test@apiforge.ai", "role": "admin"}
    token = create_access_token(data, expires_delta=timedelta(minutes=15))

    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["email"] == "test@apiforge.ai"
    assert payload["role"] == "admin"
    assert "exp" in payload


# ============================================================================
# Integration Tests: Auth Endpoints & RBAC
# ============================================================================

def test_user_registration_success():
    """Test successful user registration returns 201 Created."""
    unique_email = "reg_test_user@apiforge.ai"
    payload = {
        "email": unique_email,
        "password": "ValidPassword123!",
        "role": "user",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == unique_email
    assert data["role"] == "user"
    assert "password" not in data
    assert "hashed_password" not in data

    # Verify audit log created
    with SessionLocal() as db:
        log = db.query(AuditLog).filter_by(action="user_registered", resource_id=str(data["id"])).first()
        assert log is not None
        assert log.details["email"] == unique_email

        # Clean up
        u = db.query(User).filter_by(id=data["id"]).first()
        if u:
            db.delete(u)
            db.commit()


def test_user_registration_duplicate_email():
    """Test registering existing email returns 400 Bad Request."""
    email = "dup_user@apiforge.ai"
    payload = {"email": email, "password": "ValidPassword123!"}

    # First registration
    r1 = client.post("/auth/register", json=payload)
    assert r1.status_code == 201
    user_id = r1.json()["id"]

    # Duplicate registration
    r2 = client.post("/auth/register", json=payload)
    assert r2.status_code == 400
    assert "already registered" in r2.json()["detail"].lower()

    # Clean up
    with SessionLocal() as db:
        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()


def test_user_registration_short_password():
    """Test registration with password under 8 characters is rejected."""
    payload = {"email": "short_pw@apiforge.ai", "password": "123"}
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 422


def test_user_login_success():
    """Test login returns JWT access token and user metadata."""
    email = "login_success@apiforge.ai"
    password = "CorrectPassword123!"

    # Register
    r_reg = client.post("/auth/register", json={"email": email, "password": password})
    assert r_reg.status_code == 201
    user_id = r_reg.json()["id"]

    # Login
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    data = response.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == email
    token = data["access_token"]

    # Clean up
    with SessionLocal() as db:
        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()


def test_user_login_invalid_password():
    """Test login with wrong password returns 401 Unauthorized."""
    email = "wrong_pw_user@apiforge.ai"
    password = "CorrectPassword123!"

    r_reg = client.post("/auth/register", json={"email": email, "password": password})
    user_id = r_reg.json()["id"]

    response = client.post("/auth/login", json={"email": email, "password": "WrongPassword456!"})
    assert response.status_code == 401
    assert "invalid email or password" in response.json()["detail"].lower()

    with SessionLocal() as db:
        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()


def test_protected_route_me():
    """Test GET /auth/me returns profile when authenticated and 401 when not."""
    email = "me_user@apiforge.ai"
    password = "ValidPassword123!"

    # Register & Login
    r_reg = client.post("/auth/register", json={"email": email, "password": password})
    user_id = r_reg.json()["id"]
    r_login = client.post("/auth/login", json={"email": email, "password": password})
    token = r_login.json()["access_token"]

    # Call /auth/me with valid Bearer token
    headers = {"Authorization": f"Bearer {token}"}
    r_me = client.get("/auth/me", headers=headers)
    assert r_me.status_code == 200
    assert r_me.json()["email"] == email

    # Call /auth/me without token -> 401
    r_unauth = client.get("/auth/me")
    assert r_unauth.status_code == 401

    # Call with invalid token -> 401
    r_bad = client.get("/auth/me", headers={"Authorization": "Bearer invalid.fake.token"})
    assert r_bad.status_code == 401

    with SessionLocal() as db:
        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()


def test_rbac_admin_vs_regular_user():
    """Verify Role-Based Access Control: Admin is allowed, regular user is forbidden."""
    admin_email = "admin_rbac@apiforge.ai"
    user_email = "regular_rbac@apiforge.ai"
    password = "StrongPassword123!"

    # 1. Register admin
    r_admin_reg = client.post("/auth/register", json={"email": admin_email, "password": password, "role": "admin"})
    admin_id = r_admin_reg.json()["id"]
    r_admin_login = client.post("/auth/login", json={"email": admin_email, "password": password})
    admin_token = r_admin_login.json()["access_token"]

    # 2. Register regular user
    r_user_reg = client.post("/auth/register", json={"email": user_email, "password": password, "role": "user"})
    user_id = r_user_reg.json()["id"]
    r_user_login = client.post("/auth/login", json={"email": user_email, "password": password})
    user_token = r_user_login.json()["access_token"]

    # 3. Test Admin accessing /auth/admin-only -> 200 OK
    r_admin_check = client.get("/auth/admin-only", headers={"Authorization": f"Bearer {admin_token}"})
    assert r_admin_check.status_code == 200
    assert r_admin_check.json()["status"] == "authorized"

    # 4. Test Regular User accessing /auth/admin-only -> 403 Forbidden
    r_user_check = client.get("/auth/admin-only", headers={"Authorization": f"Bearer {user_token}"})
    assert r_user_check.status_code == 403
    assert "administrator privileges required" in r_user_check.json()["detail"].lower()

    # Clean up
    with SessionLocal() as db:
        for uid in [admin_id, user_id]:
            u = db.query(User).filter_by(id=uid).first()
            if u:
                db.delete(u)
                db.commit()
