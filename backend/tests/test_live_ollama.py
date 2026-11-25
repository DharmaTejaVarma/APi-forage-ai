"""
Live Local Ollama Integration Verification (`qwen2.5:7b-instruct` + `nomic-embed-text`).
Runs end-to-end without LLM mocks against an in-process ephemeral mock store server:
OpenAPI Import -> nomic-embed-text Embeddings -> Semantic Search ->
LangGraph 7-Agent Plan Generation -> DAG Validation -> Execution -> Rule 8 Approval -> Order Verification.
"""
import json
import socket
import threading
import time
from pathlib import Path
import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import User

settings = get_settings()
client = TestClient(app)
EXTENDED_SPEC_PATH = Path(__file__).resolve().parent.parent / "samples" / "extended_mock_openapi.json"
_MOCK_BASE_URL: str = "http://127.0.0.1:8000/mock/api/v1"


def _require_live_ollama():
    try:
        resp = httpx.get(f"{settings.OLLAMA_URL}/api/tags", timeout=3.0)
        if resp.status_code != 200:
            pytest.skip(f"Local Ollama unavailable: HTTP {resp.status_code}")
        models = {m.get("name", "") for m in resp.json().get("models", [])}
        has_chat = any(settings.CHAT_MODEL in m for m in models)
        has_embed = any(settings.EMBED_MODEL in m for m in models)
        if not (has_chat and has_embed):
            pytest.skip(f"Required Ollama models missing: need {settings.CHAT_MODEL} & {settings.EMBED_MODEL}, got {models}")
    except Exception as exc:
        pytest.skip(f"Local Ollama not reachable at {settings.OLLAMA_URL}: {exc}")


@pytest.fixture(scope="module", autouse=True)
def live_mock_server():
    global _MOCK_BASE_URL
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    health_url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + 10.0
    while time.time() < deadline:
        try:
            if httpx.get(health_url, timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)

    _MOCK_BASE_URL = f"http://127.0.0.1:{port}/mock/api/v1"
    try:
        yield _MOCK_BASE_URL
    finally:
        server.should_exit = True
        thread.join(timeout=3.0)


@pytest.fixture(autouse=True)
def setup_db(live_mock_server):
    init_db()
    client.post("/mock/api/v1/reset")
    yield


def test_live_ollama_end_to_end_product_discount_order():
    _require_live_ollama()

    email = "live_ollama_e2e@apiforge.ai"
    client.post("/auth/register", json={"email": email, "password": "Password123!"})
    login = client.post("/auth/login", json={"email": email, "password": "Password123!"})
    assert login.status_code == 200
    uid = login.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    try:
        # 1. Create connection and import OpenAPI spec
        r_conn = client.post(
            "/connections",
            json={"name": "Live E2E Mock Store", "base_url": _MOCK_BASE_URL, "auth_type": "none"},
            headers=headers,
        )
        assert r_conn.status_code == 201
        conn_id = r_conn.json()["id"]

        with open(EXTENDED_SPEC_PATH, "r", encoding="utf-8") as f:
            spec = json.load(f)
        r_imp = client.post(f"/connections/{conn_id}/import-openapi", json=spec, headers=headers)
        assert r_imp.status_code == 200
        assert len(r_imp.json()) >= 8

        # 2. Generate live nomic-embed-text embeddings
        r_emb = client.post(f"/connections/{conn_id}/embed-all", headers=headers)
        assert r_emb.status_code == 200
        assert r_emb.json().get("embedded_count", 0) >= 8

        # 3. Verify semantic discovery returns relevant product & order endpoints
        r_search = client.get(
            "/endpoints/search/semantic",
            params={"q": "fetch product price and create order"},
            headers=headers,
        )
        assert r_search.status_code == 200
        paths = {
            ((item.get("endpoint") or item)["method"], (item.get("endpoint") or item)["path"])
            for item in r_search.json()
        }
        assert ("GET", "/products/{id}") in paths or ("GET", "/products") in paths
        assert ("POST", "/orders") in paths

        # 4. Generate real workflow via LangGraph 7-agent orchestration (qwen2.5:7b-instruct)
        prod5 = client.get("/mock/api/v1/products/5").json()
        expected_discounted = round(prod5["price"] * 0.90, 2)

        prompt = "Fetch product 5, calculate a 10% discount on its price, and create an order using the discounted price."
        r_wf = client.post("/workflows/generate-multi-agent", json={"prompt": prompt}, headers=headers)
        assert r_wf.status_code == 201, f"Live multi-agent generation failed: {r_wf.text}"
        wf = r_wf.json()

        nodes = wf["nodes"]
        assert len(nodes) >= 2
        order_nodes = [
            n for n in nodes
            if n.get("type") == "api_call"
            and (n.get("data", {}).get("method") or "").upper() == "POST"
            and "/orders" in (n.get("data", {}).get("path") or "")
        ]
        assert order_nodes, f"Expected POST /orders node in live generated plan: {nodes}"
        assert order_nodes[0]["data"]["requires_approval"] is True

        # 5. Execute live workflow and verify Rule 8 approval pause + completion
        r_exec = client.post(f"/workflows/{wf['id']}/execute", headers=headers)
        assert r_exec.status_code == 201
        ex = r_exec.json()
        assert ex["status"] == "waiting_approval", f"Expected Rule 8 pause, got {ex}"

        # Approve (loop in case an extra mutating node exists, though typically 1 POST /orders)
        current = ex
        safety = 0
        while current.get("status") == "waiting_approval" and safety < 5:
            safety += 1
            r_app = client.post(f"/executions/{current['id']}/approve", headers=headers)
            assert r_app.status_code == 200, r_app.text
            current = r_app.json()

        assert current["status"] == "completed", f"Live workflow execution failed: {current}"
        final_out = current.get("final_output") or {}
        order_id = final_out.get("order_id")
        assert order_id, f"Expected order_id in final_output, got {final_out}"
        created = client.get(f"/mock/api/v1/orders/{order_id}").json()
        assert created["product_id"] == 5
        assert created["final_price"] == expected_discounted
    finally:
        with SessionLocal() as db:
            u = db.query(User).filter_by(id=uid).first()
            if u:
                db.delete(u)
                db.commit()
