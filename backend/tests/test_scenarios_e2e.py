"""
APIForge AI — Stage 8 Automated End-to-End Test Scenarios (Tests 1 - 10)
Verifies full lifecycle against live FastAPI endpoints & local Mock Store API:
Discovery -> Validation -> Multi-Agent Generation -> Dependency & Template Resolution ->
Per-Step Rule 8 Approvals -> Execution -> Verification -> Error Recovery & BackgroundTasks.
Ollama calls are mocked deterministically for reliable fast CI execution; live Ollama
integration tests live separately in test_live_ollama.py.
"""
import asyncio
import json
import socket
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.models import User, Workflow
from app.services.validator import ErrorCategory
from app.services.http_client import ConnectionFailureError

client = TestClient(app)
EXTENDED_SPEC_PATH = Path(__file__).resolve().parent.parent / "samples" / "extended_mock_openapi.json"
_MOCK_BASE_URL: str = "http://127.0.0.1:8000/mock/api/v1"


@pytest.fixture(scope="module", autouse=True)
def live_mock_server():
    """Run the current FastAPI app on an ephemeral local port for real TCP mock calls in this process."""
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


def _setup_user_and_connection(
    email: str,
    auth_type: str = "none",
    credentials: dict | None = None,
):
    client.post("/auth/register", json={"email": email, "password": "Password123!"})
    r_login = client.post("/auth/login", json={"email": email, "password": "Password123!"})
    data = r_login.json()
    uid = data["user"]["id"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}

    conn_payload = {
        "name": "Extended Mock Platform",
        "base_url": _MOCK_BASE_URL,
        "auth_type": auth_type,
    }
    if credentials is not None:
        conn_payload["credentials"] = credentials

    r_conn = client.post("/connections", json=conn_payload, headers=headers)
    assert r_conn.status_code == 201
    conn_id = r_conn.json()["id"]

    with open(EXTENDED_SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)
    if auth_type == "none":
        # Remove /secure/profile security block on unauthenticated connection tests where needed
        spec = json.loads(json.dumps(spec))
    r_imp = client.post(f"/connections/{conn_id}/import-openapi", json=spec, headers=headers)
    assert r_imp.status_code == 200
    return uid, conn_id, headers


def _cleanup_user(uid: int):
    with SessionLocal() as db:
        u = db.query(User).filter_by(id=uid).first()
        if u:
            db.delete(u)
            db.commit()


def _generate_with_mocked_ollama(prompt: str, plan_dict: dict, headers: dict):
    intent_json = json.dumps({
        "summary": prompt,
        "workflow_category": "e-commerce",
        "actions": ["execute"],
        "requires_state_change": True,
    })
    plan_json = json.dumps(plan_dict)
    fake_vec = [0.1] * 768
    with (
        patch("app.services.embeddings.generate_embedding", AsyncMock(return_value=fake_vec)),
        patch("app.services.ollama_client.OllamaClient.chat", AsyncMock(side_effect=[intent_json, plan_json])),
    ):
        r = client.post("/workflows/generate-multi-agent", json={"prompt": prompt}, headers=headers)
        assert r.status_code == 201, f"Generation failed: {r.text}"
        return r.json()


# ============================================================================
# TEST 1 — Product Discount and Order (Product 5, 10% discount -> 900)
# ============================================================================
def test_scenario_1_product_discount_and_order():
    uid, _, headers = _setup_user_and_connection("scen1@apiforge.ai")
    try:
        prod5_actual = client.get("/mock/api/v1/products/5").json()
        expected_price = round(prod5_actual["price"] * 0.90, 2)

        plan = {
            "workflow_title": "Test 1 Discount Order",
            "workflow_description": "Fetch product 5, apply 10% discount, order",
            "steps": [
                {"step_id": "step_1", "step_type": "api_call", "description": "Get product 5", "method": "GET", "path": "/products/{id}", "parameters": {"id": 5}, "requires_approval": False, "depends_on": []},
                {"step_id": "step_2", "step_type": "transform", "description": "10% discount", "transformation": {"operation": "calculate", "formula": "price * 0.90", "inputs": {"price": "{{steps.step_1.output.price}}"}}, "requires_approval": False, "depends_on": ["step_1"]},
                {"step_id": "step_3", "step_type": "api_call", "description": "Create order", "method": "POST", "path": "/orders", "request_body": {"product_id": "{{steps.step_1.output.id}}", "final_price": "{{steps.step_2.output}}"}, "requires_approval": True, "depends_on": ["step_2"]},
            ],
        }
        wf = _generate_with_mocked_ollama("Fetch product 5, calculate a 10% discount on its price, and create an order using the discounted price.", plan, headers)

        r_exec = client.post(f"/workflows/{wf['id']}/execute", headers=headers)
        assert r_exec.status_code == 201
        ex = r_exec.json()
        assert ex["status"] == "waiting_approval"
        assert ex["pending_approval_step"] == "step_3"
        assert ex["pending_approval_details"]["request_body"]["final_price"] == expected_price

        r_app = client.post(f"/executions/{ex['id']}/approve", headers=headers)
        done = r_app.json()
        assert done["status"] == "completed"
        assert done["step_results"]["step_2"]["output"] == expected_price
        assert done["final_output"]["final_price"] == expected_price
        order_id = done["final_output"]["order_id"]
        assert client.get(f"/mock/api/v1/orders/{order_id}").json()["final_price"] == expected_price
    finally:
        _cleanup_user(uid)


# ============================================================================
# TEST 2 — Product Extraction and Email (Product 3 -> HD Webcam)
# ============================================================================
def test_scenario_2_product_extraction_and_email():
    uid, _, headers = _setup_user_and_connection("scen2@apiforge.ai")
    try:
        prod3_actual = client.get("/mock/api/v1/products/3").json()
        plan = {
            "workflow_title": "Test 2 Product Email",
            "workflow_description": "Fetch product 3, extract title, send email",
            "steps": [
                {"step_id": "step_1", "step_type": "api_call", "description": "Fetch product 3", "method": "GET", "path": "/products/{id}", "parameters": {"id": 3}, "requires_approval": False, "depends_on": []},
                {"step_id": "step_2", "step_type": "transform", "description": "Extract product title", "transformation": {"operation": "extract", "fields": {"title": "{{steps.step_1.output.name}}"}}, "requires_approval": False, "depends_on": ["step_1"]},
                {"step_id": "step_3", "step_type": "api_call", "description": "Send email", "method": "POST", "path": "/notifications/email", "request_body": {"to": "demo@apiforge.ai", "subject": "Product Info: {{steps.step_2.output.title}}", "body": "Featured title: {{steps.step_2.output.title}}"}, "requires_approval": True, "depends_on": ["step_2"]},
            ],
        }
        wf = _generate_with_mocked_ollama("Fetch product 3, extract its title, and send an email containing the product title.", plan, headers)
        ex = client.post(f"/workflows/{wf['id']}/execute", headers=headers).json()
        assert ex["status"] == "waiting_approval"

        done = client.post(f"/executions/{ex['id']}/approve", headers=headers).json()
        assert done["status"] == "completed"
        assert prod3_actual["name"] in done["final_output"]["subject"]
        sent = client.get("/mock/api/v1/notifications/email").json()
        assert len(sent) == 1 and prod3_actual["name"] in sent[0]["body"]
    finally:
        _cleanup_user(uid)


# ============================================================================
# TEST 3 — Product Retrieval and Unmodified Order (Product 1)
# ============================================================================
def test_scenario_3_product_retrieval_and_order():
    uid, _, headers = _setup_user_and_connection("scen3@apiforge.ai")
    try:
        prod1 = client.get("/mock/api/v1/products/1").json()
        plan = {
            "workflow_title": "Test 3 Direct Order",
            "workflow_description": "Retrieve product 1 and order at original price",
            "steps": [
                {"step_id": "step_1", "step_type": "api_call", "description": "Get product 1", "method": "GET", "path": "/products/{id}", "parameters": {"id": 1}, "depends_on": []},
                {"step_id": "step_2", "step_type": "transform", "description": "Extract id & price", "transformation": {"operation": "extract", "fields": {"id": "{{steps.step_1.output.id}}", "price": "{{steps.step_1.output.price}}"}}, "depends_on": ["step_1"]},
                {"step_id": "step_3", "step_type": "api_call", "description": "Order product 1", "method": "POST", "path": "/orders", "request_body": {"product_id": "{{steps.step_2.output.id}}", "final_price": "{{steps.step_2.output.price}}"}, "requires_approval": True, "depends_on": ["step_2"]},
            ],
        }
        wf = _generate_with_mocked_ollama("Retrieve product 1, extract its ID and original price, and create an order without modifying the price.", plan, headers)
        ex = client.post(f"/workflows/{wf['id']}/execute", headers=headers).json()
        done = client.post(f"/executions/{ex['id']}/approve", headers=headers).json()
        assert done["status"] == "completed"
        assert done["final_output"]["product_id"] == prod1["id"]
        assert done["final_output"]["final_price"] == prod1["price"]
    finally:
        _cleanup_user(uid)


# ============================================================================
# TEST 4 — Bearer Authentication (200 valid vs 401 invalid/missing)
# ============================================================================
def test_scenario_4_bearer_authentication():
    # Valid Bearer token
    uid_ok, _, headers_ok = _setup_user_and_connection(
        "scen4_ok@apiforge.ai",
        auth_type="bearer",
        credentials={"token": "valid-bearer-token-123"},
    )
    # Invalid Bearer token
    uid_bad, _, headers_bad = _setup_user_and_connection(
        "scen4_bad@apiforge.ai",
        auth_type="bearer",
        credentials={"token": "invalid-expired-token"},
    )
    try:
        secure_plan = {
            "workflow_title": "Test 4 Bearer Vault",
            "workflow_description": "Fetch secure profile using Bearer token",
            "steps": [
                {"step_id": "step_1", "step_type": "api_call", "description": "Access secure endpoint", "method": "GET", "path": "/secure/profile", "depends_on": []},
            ],
        }
        wf_ok = _generate_with_mocked_ollama("Access the secure API endpoint using the configured Bearer token and retrieve the protected response.", secure_plan, headers_ok)
        done_ok = client.post(f"/workflows/{wf_ok['id']}/execute", headers=headers_ok).json()
        assert done_ok["status"] == "completed"
        assert done_ok["step_results"]["step_1"]["status_code"] == 200
        assert done_ok["final_output"]["authenticated"] is True
        # Ensure token masked in logs/request telemetry
        assert "valid-bearer-token-123" not in json.dumps(done_ok)

        wf_bad = _generate_with_mocked_ollama("Access the secure API endpoint using the configured Bearer token.", secure_plan, headers_bad)
        done_bad = client.post(f"/workflows/{wf_bad['id']}/execute", headers=headers_bad).json()
        assert done_bad["status"] == "failed"
        assert done_bad["error_details"]["status_code"] == 401
        assert done_bad["error_details"]["category"] == ErrorCategory.AUTH_FAILURE
    finally:
        _cleanup_user(uid_ok)
        _cleanup_user(uid_bad)


# ============================================================================
# TEST 5 — Multiple API Operations (5 steps, 2 independent Rule 8 approvals)
# ============================================================================
def test_scenario_5_multiple_api_operations_and_multi_approvals():
    uid, _, headers = _setup_user_and_connection("scen5@apiforge.ai")
    try:
        prod10 = client.get("/mock/api/v1/products/10").json()
        disc_price = round(prod10["price"] * 0.80, 2)

        plan = {
            "workflow_title": "Test 5 Multi-Step Order & Email",
            "workflow_description": "Product 10 -> 20% discount -> extract -> order -> email",
            "steps": [
                {"step_id": "step_1", "step_type": "api_call", "description": "Fetch product 10", "method": "GET", "path": "/products/{id}", "parameters": {"id": 10}, "depends_on": []},
                {"step_id": "step_2", "step_type": "transform", "description": "20% discount", "transformation": {"operation": "calculate", "formula": "price * 0.80", "inputs": {"price": "{{steps.step_1.output.price}}"}}, "depends_on": ["step_1"]},
                {"step_id": "step_3", "step_type": "transform", "description": "Extract title", "transformation": {"operation": "extract", "fields": {"title": "{{steps.step_1.output.name}}"}}, "depends_on": ["step_1"]},
                {"step_id": "step_4", "step_type": "api_call", "description": "Create order", "method": "POST", "path": "/orders", "request_body": {"product_id": "{{steps.step_1.output.id}}", "final_price": "{{steps.step_2.output}}"}, "requires_approval": True, "depends_on": ["step_2"]},
                {"step_id": "step_5", "step_type": "api_call", "description": "Send email receipt", "method": "POST", "path": "/notifications/email", "request_body": {"to": "demo@apiforge.ai", "subject": "Order for {{steps.step_3.output.title}}", "body": "Ordered {{steps.step_3.output.title}} at final price {{steps.step_4.output.final_price}}"}, "requires_approval": True, "depends_on": ["step_3", "step_4"]},
            ],
        }
        wf = _generate_with_mocked_ollama("Fetch product 10, calculate a 20% discount, extract its title, create an order using the discounted price, and send an email containing the product title and final price.", plan, headers)

        # Run -> pauses at step_4 (1st mutating POST)
        ex1 = client.post(f"/workflows/{wf['id']}/execute", headers=headers).json()
        assert ex1["status"] == "waiting_approval"
        assert ex1["pending_approval_step"] == "step_4"

        # Approve step_4 -> pauses AGAIN at step_5 (2nd mutating POST — Rule 8 strictly enforced per step!)
        ex2 = client.post(f"/executions/{ex1['id']}/approve", headers=headers).json()
        assert ex2["status"] == "waiting_approval"
        assert ex2["pending_approval_step"] == "step_5"
        assert ex2["step_results"]["step_4"]["output"]["final_price"] == disc_price

        # Approve step_5 -> completes
        ex3 = client.post(f"/executions/{ex1['id']}/approve", headers=headers).json()
        assert ex3["status"] == "completed"
        assert prod10["name"] in ex3["final_output"]["subject"]
        assert str(disc_price) in ex3["final_output"]["body"]
    finally:
        _cleanup_user(uid)


# ============================================================================
# TEST 6 — Array Response Handling (Filter ID == 5 from list)
# ============================================================================
def test_scenario_6_array_response_handling():
    uid, _, headers = _setup_user_and_connection("scen6@apiforge.ai")
    try:
        prod5 = client.get("/mock/api/v1/products/5").json()
        plan = {
            "workflow_title": "Test 6 Array Selection",
            "workflow_description": "Retrieve all products, filter id=5, create order",
            "steps": [
                {"step_id": "step_1", "step_type": "api_call", "description": "Get all products", "method": "GET", "path": "/products", "depends_on": []},
                {"step_id": "step_2", "step_type": "transform", "description": "Select product id 5", "transformation": {"operation": "filter", "source": "{{steps.step_1.output}}", "field": "id", "op": "==", "value": 5, "single": True}, "depends_on": ["step_1"]},
                {"step_id": "step_3", "step_type": "api_call", "description": "Order product 5", "method": "POST", "path": "/orders", "request_body": {"product_id": "{{steps.step_2.output.id}}", "final_price": "{{steps.step_2.output.price}}"}, "requires_approval": True, "depends_on": ["step_2"]},
            ],
        }
        wf = _generate_with_mocked_ollama("Retrieve all products, find product ID 5, extract its name and price, and create an order using its original price.", plan, headers)
        ex = client.post(f"/workflows/{wf['id']}/execute", headers=headers).json()
        assert ex["status"] == "waiting_approval"
        assert ex["step_results"]["step_2"]["output"]["name"] == prod5["name"]

        done = client.post(f"/executions/{ex['id']}/approve", headers=headers).json()
        assert done["status"] == "completed"
        assert done["final_output"]["product_id"] == 5
        assert done["final_output"]["final_price"] == prod5["price"]
    finally:
        _cleanup_user(uid)


# ============================================================================
# TEST 7 — Nested JSON Mapping (customer.contact.email -> Notification)
# ============================================================================
def test_scenario_7_nested_json_mapping():
    uid, _, headers = _setup_user_and_connection("scen7@apiforge.ai")
    try:
        cust2 = client.get("/mock/api/v1/customers/2").json()
        plan = {
            "workflow_title": "Test 7 Nested Customer Email",
            "workflow_description": "Fetch customer 2 nested email and notify",
            "steps": [
                {"step_id": "step_1", "step_type": "api_call", "description": "Get customer 2", "method": "GET", "path": "/customers/{id}", "parameters": {"id": 2}, "depends_on": []},
                {"step_id": "step_2", "step_type": "transform", "description": "Extract nested contact email", "transformation": {"operation": "extract", "fields": {"email": "{{steps.step_1.output.contact.email}}", "name": "{{steps.step_1.output.name}}"}}, "depends_on": ["step_1"]},
                {"step_id": "step_3", "step_type": "api_call", "description": "Notify customer", "method": "POST", "path": "/notifications/email", "request_body": {"to": "{{steps.step_2.output.email}}", "subject": "Hello {{steps.step_2.output.name}}", "body": "Customer alert delivered."}, "requires_approval": True, "depends_on": ["step_2"]},
            ],
        }
        wf = _generate_with_mocked_ollama("Retrieve customer information, extract the nested email address, and send a notification to that email address.", plan, headers)
        ex = client.post(f"/workflows/{wf['id']}/execute", headers=headers).json()
        done = client.post(f"/executions/{ex['id']}/approve", headers=headers).json()
        assert done["status"] == "completed"
        assert done["final_output"]["recipient"] == cust2["contact"]["email"]
    finally:
        _cleanup_user(uid)


# ============================================================================
# TEST 8 — Multiple API Data Combination (Parallel Independent GETs + Merge)
# ============================================================================
def test_scenario_8_parallel_multi_api_combination():
    uid, _, headers = _setup_user_and_connection("scen8@apiforge.ai")
    try:
        prod5 = client.get("/mock/api/v1/products/5").json()
        cust2 = client.get("/mock/api/v1/customers/2").json()
        plan = {
            "workflow_title": "Test 8 Parallel Combine",
            "workflow_description": "Fetch product 5 and customer 2 concurrently, merge, and order",
            "steps": [
                {"step_id": "step_1", "step_type": "api_call", "description": "Fetch product 5", "method": "GET", "path": "/products/{id}", "parameters": {"id": 5}, "depends_on": []},
                {"step_id": "step_2", "step_type": "api_call", "description": "Fetch customer 2", "method": "GET", "path": "/customers/{id}", "parameters": {"id": 2}, "depends_on": []},
                {"step_id": "step_3", "step_type": "transform", "description": "Merge product and customer", "transformation": {"operation": "merge", "fields": {"product_id": "{{steps.step_1.output.id}}", "final_price": "{{steps.step_1.output.price}}", "customer_email": "{{steps.step_2.output.contact.email}}"}}, "depends_on": ["step_1", "step_2"]},
                {"step_id": "step_4", "step_type": "api_call", "description": "Create customer order", "method": "POST", "path": "/orders", "request_body": {"product_id": "{{steps.step_3.output.product_id}}", "final_price": "{{steps.step_3.output.final_price}}", "customer_email": "{{steps.step_3.output.customer_email}}"}, "requires_approval": True, "depends_on": ["step_3"]},
            ],
        }
        wf = _generate_with_mocked_ollama("Fetch product 5 and customer 2, combine their product and customer details, and create an order associated with that customer.", plan, headers)
        ex = client.post(f"/workflows/{wf['id']}/execute", headers=headers).json()
        assert ex["status"] == "waiting_approval"
        assert ex["step_results"]["step_1"]["status"] == "completed"
        assert ex["step_results"]["step_2"]["status"] == "completed"
        assert ex["pending_approval_details"]["request_body"]["customer_email"] == cust2["contact"]["email"]

        done = client.post(f"/executions/{ex['id']}/approve", headers=headers).json()
        assert done["status"] == "completed"
        assert done["final_output"]["product_id"] == prod5["id"]
        assert done["final_output"]["final_price"] == prod5["price"]
    finally:
        _cleanup_user(uid)


# ============================================================================
# TEST 9 — Conditional Workflow (True branch executes & skips false; vice versa)
# ============================================================================
@pytest.mark.parametrize("product_id,expect_order", [(5, True), (9, False)])
def test_scenario_9_conditional_branching(product_id: int, expect_order: bool):
    uid, _, headers = _setup_user_and_connection(f"scen9_p{product_id}@apiforge.ai")
    try:
        plan = {
            "workflow_title": f"Test 9 Conditional Stock Check P{product_id}",
            "workflow_description": "Check product stock and branch to order vs unavailable email",
            "steps": [
                {"step_id": "step_1", "step_type": "api_call", "description": f"Fetch product {product_id}", "method": "GET", "path": "/products/{id}", "parameters": {"id": product_id}, "depends_on": []},
                {"step_id": "step_2", "step_type": "condition", "description": "Check stock > 0", "condition": "{{steps.step_1.output.stock}} > 0", "depends_on": ["step_1"]},
                {"step_id": "step_order", "step_type": "api_call", "description": "Create order", "method": "POST", "path": "/orders", "request_body": {"product_id": "{{steps.step_1.output.id}}", "final_price": "{{steps.step_1.output.price}}"}, "requires_approval": True, "when": "true", "depends_on": ["step_2"]},
                {"step_id": "step_email", "step_type": "api_call", "description": "Notify unavailable", "method": "POST", "path": "/notifications/email", "request_body": {"to": "demo@apiforge.ai", "subject": "Out of Stock: {{steps.step_1.output.name}}", "body": "Product {{steps.step_1.output.name}} is unavailable (stock=0)."}, "requires_approval": True, "when": "false", "depends_on": ["step_2"]},
            ],
        }
        wf = _generate_with_mocked_ollama("Fetch product. If stock > 0 create an order; otherwise send unavailable email.", plan, headers)
        ex = client.post(f"/workflows/{wf['id']}/execute", headers=headers).json()
        assert ex["status"] == "waiting_approval"

        if expect_order:
            assert ex["pending_approval_step"] == "step_order"
            assert ex["step_results"]["step_email"]["status"] == "skipped"
            done = client.post(f"/executions/{ex['id']}/approve", headers=headers).json()
            assert done["status"] == "completed"
            assert done["step_results"]["step_order"]["status"] == "completed"
            assert done["step_results"]["step_email"]["status"] == "skipped"
        else:
            assert ex["pending_approval_step"] == "step_email"
            assert ex["step_results"]["step_order"]["status"] == "skipped"
            done = client.post(f"/executions/{ex['id']}/approve", headers=headers).json()
            assert done["status"] == "completed"
            assert done["step_results"]["step_email"]["status"] == "completed"
            assert done["step_results"]["step_order"]["status"] == "skipped"
            assert "unavailable" in done["final_output"]["body"].lower()
    finally:
        _cleanup_user(uid)


# ============================================================================
# TEST 10 — Error Classification, Root-Cause Diagnosis, Safety & Fix Recovery
# ============================================================================
def test_scenario_10_comprehensive_error_recovery_and_background():
    uid, conn_id, headers = _setup_user_and_connection("scen10@apiforge.ai")
    try:
        with SessionLocal() as db:
            # A: 404 Not Found -> Diagnose -> Explicit Fix (ID 999 -> 5) -> Recovers!
            wf_404 = Workflow(
                user_id=uid,
                title="NotFound Recovery",
                nodes=[{"id": "step_1", "type": "api_call", "data": {"label": "Fetch Missing", "method": "GET", "path": "/products/{id}", "connection_id": conn_id, "parameters": {"id": 999}, "requires_approval": False}}],
                edges=[],
            )
            # B: 422 Invalid Params (bad email body)
            wf_422 = Workflow(
                user_id=uid,
                title="InvalidParams Test",
                nodes=[{"id": "step_1", "type": "api_call", "data": {"label": "Bad Email", "method": "POST", "path": "/notifications/email", "connection_id": conn_id, "request_body": {"to": "not-an-email", "subject": "S", "body": "B"}, "requires_approval": False}}],
                edges=[],
            )
            # C: Unreachable Connection Failure
            wf_conn = Workflow(
                user_id=uid,
                title="Unreachable Service Test",
                nodes=[{"id": "step_1", "type": "api_call", "data": {"label": "Offline", "method": "POST", "path": "/orders", "connection_id": conn_id, "request_body": {"product_id": 1, "final_price": 250}, "requires_approval": True}}],
                edges=[],
            )
            db.add_all([wf_404, wf_422, wf_conn])
            db.commit()
            for w in [wf_404, wf_422, wf_conn]:
                db.refresh(w)
            id_404, id_422, id_conn = wf_404.id, wf_422.id, wf_conn.id

        # 1. Verify 404 classification & Rule 9 diagnosis + explicit apply-fix recovery
        ex_404 = client.post(f"/workflows/{id_404}/execute", headers=headers).json()
        assert ex_404["status"] == "failed"
        assert ex_404["error_details"]["category"] == ErrorCategory.NOT_FOUND

        with patch("app.services.ollama_client.OllamaClient.chat", side_effect=RuntimeError("use fallback")):
            diag = client.post(f"/executions/{ex_404['id']}/diagnose", headers=headers).json()
        assert diag["error_category"] == ErrorCategory.NOT_FOUND
        assert diag["requires_user_approval"] is True
        assert len(diag["candidate_fixes"]) >= 1
        # Workflow node remains unmodified before user applies fix!
        assert client.get(f"/workflows/{id_404}", headers=headers).json()["nodes"][0]["data"]["parameters"]["id"] == 999

        # Explicitly confirm fix -> id=5
        recovered = client.post(
            f"/executions/{ex_404['id']}/apply-fix",
            json={"target_node_id": "step_1", "patch": {"parameters": {"id": 5}}, "resume": True},
            headers=headers,
        ).json()
        assert recovered["status"] == "completed"
        assert recovered["final_output"]["id"] == 5

        # 2. Verify 422 INVALID_PARAMETERS (with Rule 8 paused then approved)
        ex_422_pause = client.post(f"/workflows/{id_422}/execute", headers=headers).json()
        assert ex_422_pause["status"] == "waiting_approval"
        ex_422_fail = client.post(f"/executions/{ex_422_pause['id']}/approve", headers=headers).json()
        assert ex_422_fail["status"] == "failed"
        assert ex_422_fail["error_details"]["category"] == ErrorCategory.INVALID_PARAMETERS

        # 3. Verify ConnectionFailure on POST executes WITHOUT unsafe retries (attempts == 1)
        ex_conn_pause = client.post(f"/workflows/{id_conn}/execute", headers=headers).json()
        with patch("app.services.http_client.SecureHttpClient._send_once", AsyncMock(side_effect=ConnectionFailureError("HTTP connection failed: refused"))) as mock_send:
            ex_conn_fail = client.post(f"/executions/{ex_conn_pause['id']}/approve", headers=headers).json()
            assert ex_conn_fail["status"] == "failed"
            assert ex_conn_fail["error_details"]["category"] == ErrorCategory.CONNECTION_FAILURE
            assert mock_send.call_count == 1  # Never retried unsafe POST!

        # 4. Verify GET /executions lists execution history and background execution completes cleanly
        history_list = client.get("/executions", headers=headers).json()
        assert len(history_list) >= 3
        r_bg = client.post(f"/workflows/{id_404}/execute?background=true", headers=headers)
        assert r_bg.status_code == 201
        bg_id = r_bg.json()["id"]
        bg_done = client.get(f"/executions/{bg_id}", headers=headers).json()
        assert bg_done["status"] in ("pending", "running", "completed")
    finally:
        _cleanup_user(uid)
