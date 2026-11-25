"""
Stage 1 Discovery, Extended Mock Server, and OpenAPI Parser Tests.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.models import User, APIConnection, Endpoint
from app.services.openapi_parser import parse_openapi_spec
from app.services.embeddings import semantic_search_endpoints, build_endpoint_text

client = TestClient(app)
EXTENDED_SPEC_PATH = Path(__file__).resolve().parent.parent / "samples" / "extended_mock_openapi.json"


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield


def _create_user_and_token(email: str, password: str = "Password123!") -> tuple[int, str]:
    client.post("/auth/register", json={"email": email, "password": password})
    r_login = client.post("/auth/login", json={"email": email, "password": password})
    data = r_login.json()
    return data["user"]["id"], data["access_token"]


def test_openapi_yaml_and_security_scheme_parsing():
    """Verify OpenAPIParser parses YAML specs, securitySchemes, and synthesizes descriptions."""
    yaml_spec = """
openapi: "3.0.3"
info:
  title: "Partner Secure API"
  version: "2.0.0"
servers:
  - url: "https://api.partner.example/v2"
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
paths:
  /vault/secret:
    get:
      security:
        - bearerAuth: []
      parameters:
        - name: scope
          in: query
          required: true
          schema:
            type: string
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                type: object
                properties:
                  secret_value:
                    type: string
"""
    parsed = parse_openapi_spec(yaml_spec)
    assert parsed.title == "Partner Secure API"
    assert parsed.base_url == "https://api.partner.example/v2"
    assert "bearerAuth" in parsed.security_schemes
    assert len(parsed.endpoints) == 1

    ep = parsed.endpoints[0]
    assert ep.method == "GET"
    assert ep.path == "/vault/secret"
    # Synthesized description & summary when omitted
    assert "GET /vault/secret" in (ep.summary or "")
    assert "scope" in (ep.description or "")
    assert ep.security is not None
    assert ep.security[0]["scheme"] == "bearerAuth"

    ep_text = build_endpoint_text(ep)
    assert "Response Fields: secret_value" in ep_text
    assert "Authentication Required: bearerAuth" in ep_text


def test_extended_mock_api_endpoints():
    """Verify extended mock endpoints: products 9/10, nested customer, email notification, and secure Bearer auth."""
    client.post("/mock/api/v1/reset")

    # Product 10 & Product 9 (out-of-stock)
    p10 = client.get("/mock/api/v1/products/10")
    assert p10.status_code == 200
    assert p10.json()["price"] == 500.0

    p9 = client.get("/mock/api/v1/products/9")
    assert p9.status_code == 200
    assert p9.json()["stock"] == 0

    # Nested customer
    c2 = client.get("/mock/api/v1/customers/2")
    assert c2.status_code == 200
    assert c2.json()["contact"]["email"] == "alice.morgan@example.com"

    # Email notification POST & GET
    r_mail = client.post(
        "/mock/api/v1/notifications/email",
        json={"to": "alice.morgan@example.com", "subject": "Hello", "body": "World"},
    )
    assert r_mail.status_code == 201
    assert r_mail.json()["status"] == "sent"
    assert len(client.get("/mock/api/v1/notifications/email").json()) == 1

    # Secure endpoint: 401 without or wrong token, 200 with valid Bearer token
    r_no_auth = client.get("/mock/api/v1/secure/profile")
    assert r_no_auth.status_code == 401

    r_bad_auth = client.get("/mock/api/v1/secure/profile", headers={"Authorization": "Bearer wrong"})
    assert r_bad_auth.status_code == 401

    r_good_auth = client.get(
        "/mock/api/v1/secure/profile",
        headers={"Authorization": "Bearer valid-bearer-token-123"},
    )
    assert r_good_auth.status_code == 200
    assert r_good_auth.json()["authenticated"] is True


@pytest.mark.asyncio
async def test_discovery_skips_ollama_when_empty_and_supports_query_aliases():
    """Verify empty discovery avoids Ollama calls and query aliases work with unembedded fallback."""
    uid, token = _create_user_and_token("stage1_disc@apiforge.ai")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. With 0 endpoints, semantic_search_endpoints must not call Ollama
    with patch("app.services.embeddings.generate_embedding", new_callable=AsyncMock) as mock_emb:
        with SessionLocal() as db:
            res = await semantic_search_endpoints(db=db, user_id=uid, query="find products")
            assert res == []
            mock_emb.assert_not_called()

    # 2. Import extended spec into connection (no manual embedding yet)
    r_conn = client.post(
        "/connections",
        json={"name": "Extended Mock", "base_url": "http://127.0.0.1:8000/mock/api/v1"},
        headers=headers,
    )
    conn_id = r_conn.json()["id"]
    with open(EXTENDED_SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)
    r_imp = client.post(f"/connections/{conn_id}/import-openapi", json=spec, headers=headers)
    assert r_imp.status_code == 200
    assert len(r_imp.json()) == 8

    # Check lexical/intent fallback works even if embedding service errors
    with patch("app.services.embeddings.generate_embedding", side_effect=RuntimeError("mock offline")):
        r_search = client.get("/endpoints/search/semantic?query=send+email+notification&top_k=3", headers=headers)
        assert r_search.status_code == 200
        hits = r_search.json()
        assert len(hits) >= 1
        assert hits[0]["endpoint"]["path"] == "/notifications/email"
        assert hits[0]["endpoint"]["method"] == "POST"

    with SessionLocal() as db:
        u = db.query(User).filter_by(id=uid).first()
        if u:
            db.delete(u)
            db.commit()

