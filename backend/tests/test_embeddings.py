"""
Phase 4 Ollama Integration & Semantic Search Test Suite
Verifies vector embeddings generation via nomic-embed-text, cosine similarity calculation,
batch endpoint embedding, semantic natural language search accuracy, and user isolation.
"""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.models import User, APIConnection, Endpoint
from app.services.ollama_client import ollama_client
from app.services.embeddings import (
    cosine_similarity,
    build_endpoint_text,
    batch_embed_endpoints,
    semantic_search_endpoints,
)

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
# Math & Utility Unit Tests
# ============================================================================

def test_cosine_similarity_math():
    """Verify vector cosine similarity computation properties."""
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    v4 = [-1.0, 0.0, 0.0]

    # Identical -> 1.0
    assert pytest.approx(cosine_similarity(v1, v2), 0.001) == 1.0
    # Orthogonal -> 0.0
    assert pytest.approx(cosine_similarity(v1, v3), 0.001) == 0.0
    # Opposite -> -1.0
    assert pytest.approx(cosine_similarity(v1, v4), 0.001) == -1.0
    # Zero vector guard
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_build_endpoint_text():
    """Verify textual representation generator captures all critical semantic information."""
    ep = Endpoint(
        method="POST",
        path="/discounts/calculate",
        summary="Calculate discounted price",
        description="Applies percentage discount to product price",
        operation_id="calculateDiscount",
        parameters=[{"name": "currency", "in": "query", "description": "Currency code"}],
        request_body_schema={"properties": {"price": {}, "discount_percentage": {}}},
    )
    text = build_endpoint_text(ep)
    assert "POST /discounts/calculate" in text
    assert "Calculate discounted price" in text
    assert "currency (query)" in text
    assert "price, discount_percentage" in text


# ============================================================================
# Local Ollama Live Embeddings Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ollama_client_embeddings():
    """Verify that Ollama nomic-embed-text returns 768-dimensional float embedding."""
    vector = await ollama_client.embeddings("Search products in catalog")
    assert isinstance(vector, list)
    assert len(vector) == 768
    assert all(isinstance(val, float) for val in vector)


@pytest.mark.asyncio
async def test_ollama_client_chat():
    """Verify local Ollama chat inference."""
    messages = [{"role": "user", "content": "Respond with the single word: READY"}]
    reply = await ollama_client.chat(messages=messages)
    assert len(reply.strip()) > 0


# ============================================================================
# Semantic Endpoint Search & User Isolation
# ============================================================================

@pytest.mark.asyncio
async def test_semantic_search_accuracy():
    """
    Test semantic endpoint retrieval accuracy:
    - Natural language queries should match their respective endpoints with highest cosine similarity.
    """
    user_id, token = _create_user_and_token("semantic_search_user@apiforge.ai")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create connection and import mock OpenAPI spec
    r_conn = client.post(
        "/connections",
        json={"name": "Store API", "base_url": "http://127.0.0.1:8000/mock/api/v1"},
        headers=headers,
    )
    conn_id = r_conn.json()["id"]

    with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    r_import = client.post(f"/connections/{conn_id}/import-openapi", json=spec, headers=headers)
    assert r_import.status_code == 200

    # 2. Batch embed connection endpoints
    with SessionLocal() as db:
        count = await batch_embed_endpoints(db, conn_id)
        assert count == 5

    # 3. Test Query 1: "fetch product details by ID"
    r_search1 = client.get(
        "/endpoints/search/semantic?q=fetch+product+details+by+ID&top_k=3",
        headers=headers,
    )
    assert r_search1.status_code == 200
    results1 = r_search1.json()
    assert len(results1) > 0
    top_hit_1 = results1[0]["endpoint"]
    assert top_hit_1["path"] == "/products/{id}"
    assert top_hit_1["method"] == "GET"
    assert results1[0]["similarity_score"] > 0.5

    # 4. Test Query 2: "calculate percentage discount"
    r_search2 = client.get(
        "/endpoints/search/semantic?q=calculate+percentage+discount+on+price&top_k=3",
        headers=headers,
    )
    assert r_search2.status_code == 200
    results2 = r_search2.json()
    top_hit_2 = results2[0]["endpoint"]
    assert top_hit_2["path"] == "/discounts/calculate"
    assert top_hit_2["method"] == "POST"

    # 5. Test Query 3: "place a new customer purchase order"
    r_search3 = client.get(
        "/endpoints/search/semantic?q=place+a+new+customer+purchase+order&top_k=3",
        headers=headers,
    )
    assert r_search3.status_code == 200
    results3 = r_search3.json()
    top_hit_3 = results3[0]["endpoint"]
    assert top_hit_3["path"] == "/orders"
    assert top_hit_3["method"] == "POST"

    # Clean up
    with SessionLocal() as db:
        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()


@pytest.mark.asyncio
async def test_semantic_search_user_isolation():
    """Verify User B cannot retrieve User A's endpoints in semantic search."""
    user_a_id, token_a = _create_user_and_token("search_iso_a@apiforge.ai")
    user_b_id, token_b = _create_user_and_token("search_iso_b@apiforge.ai")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A imports mock endpoints
    r_conn = client.post("/connections", json={"name": "A API", "base_url": "http://a.com"}, headers=headers_a)
    conn_a_id = r_conn.json()["id"]

    with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)
    client.post(f"/connections/{conn_a_id}/import-openapi", json=spec, headers=headers_a)

    with SessionLocal() as db:
        await batch_embed_endpoints(db, conn_a_id)

    # User B searches -> must return 0 results
    r_search_b = client.get(
        "/endpoints/search/semantic?q=fetch+product+details",
        headers=headers_b,
    )
    assert r_search_b.status_code == 200
    assert len(r_search_b.json()) == 0

    # Clean up
    with SessionLocal() as db:
        for uid in [user_a_id, user_b_id]:
            u = db.query(User).filter_by(id=uid).first()
            if u:
                db.delete(u)
                db.commit()
