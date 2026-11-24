"""
Phase 6 DAG Execution, Transforms, and Approval System Test Suite
Tests:
1. SimpleEval transformations (sandboxed math, no eval/exec)
2. Template substitutions and JSONPath resolution
3. Step data passing between DAG nodes
4. Rule 8 Approval System: pauses before POST/PUT/DELETE, resumes on approval
5. Workflow rejection flow
"""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.models import User, Workflow, WorkflowExecution, APIConnection, Endpoint
from app.services.transforms import (
    resolve_templates,
    evaluate_transformation,
    get_value_from_context,
)
from app.services.executor import DAGExecutor

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
# Safe Transformations Unit Tests
# ============================================================================

def test_safe_math_transformations():
    """Verify SimpleEval computes mathematical expressions safely without eval()."""
    context = {
        "step_1": {
            "output": {"id": 5, "name": "Mechanical Keyboard", "price": 1000.0}
        }
    }
    # Formula 1: price * 0.9 (10% discount)
    trans_1 = {
        "formula": "price * 0.9",
        "inputs": {"price": "{{step_1.output.price}}"},
    }
    result_1 = evaluate_transformation(trans_1, context)
    assert result_1 == 900.0

    # Formula 2: price * (1 - discount / 100)
    trans_2 = {
        "formula": "round(price * (1 - discount / 100), 2)",
        "inputs": {"price": "{{step_1.output.price}}", "discount": 15},
    }
    result_2 = evaluate_transformation(trans_2, context)
    assert result_2 == 850.0


def test_malicious_code_blocked_in_transform():
    """Verify malicious code injection is strictly blocked by SimpleEval."""
    context = {"val": 10}
    malicious_trans = {
        "formula": "__import__('os').system('echo pwned')",
        "inputs": {},
    }
    with pytest.raises(ValueError, match="evaluation failed"):
        evaluate_transformation(malicious_trans, context)


def test_template_resolution_types():
    """Verify template substitution preserves native data types."""
    context = {
        "step_1": {"output": {"product_id": 5, "price": 1000.0, "active": True}}
    }
    # Single token preservation
    assert resolve_templates("{{step_1.output.product_id}}", context) == 5
    assert resolve_templates("{{step_1.output.price}}", context) == 1000.0
    assert resolve_templates("{{step_1.output.active}}", context) is True

    # Embedded string
    assert resolve_templates("Order for item #{{step_1.output.product_id}}", context) == "Order for item #5"

    # Nested dictionary
    payload = {
        "id": "{{step_1.output.product_id}}",
        "amount": "{{step_1.output.price}}",
    }
    resolved = resolve_templates(payload, context)
    assert resolved["id"] == 5
    assert resolved["amount"] == 1000.0


# ============================================================================
# End-to-End DAG Execution & Human-in-the-Loop Approval Tests
# ============================================================================

@pytest.mark.asyncio
async def test_dag_execution_with_approval_flow():
    """
    Demonstration Workflow execution:
    1. GET product 5 (price = 1000).
    2. Transform (price * 0.9 = 900).
    3. POST order (requires_approval=True) -> pauses in 'waiting_approval' state.
    4. Approve step via API -> resumes DAG and confirms order ORD-xxxx with final_price = 900.
    """
    user_id, token = _create_user_and_token("exec_user_test@apiforge.ai")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Setup mock store connection
    r_conn = client.post(
        "/connections",
        json={"name": "Mock Store", "base_url": "http://127.0.0.1:8000/mock/api/v1"},
        headers=headers,
    )
    conn_id = r_conn.json()["id"]

    # 2. Create the demonstration DAG workflow
    nodes = [
        {
            "id": "step_1",
            "type": "api_call",
            "data": {
                "label": "Fetch Product 5",
                "method": "GET",
                "path": "/products/{id}",
                "connection_id": conn_id,
                "parameters": {"id": 5},
                "requires_approval": False,
            },
        },
        {
            "id": "step_2",
            "type": "transform",
            "data": {
                "label": "Calculate 10% Discount",
                "transformation": {
                    "formula": "price * 0.9",
                    "inputs": {"price": "{{step_1.output.price}}"},
                },
                "requires_approval": False,
            },
        },
        {
            "id": "step_3",
            "type": "api_call",
            "data": {
                "label": "Create Order with Discounted Price",
                "method": "POST",
                "path": "/orders",
                "connection_id": conn_id,
                "request_body": {
                    "product_id": "{{step_1.output.id}}",
                    "final_price": "{{step_2.output}}",
                    "quantity": 1,
                    "customer_email": "demo_shopper@apiforge.ai",
                },
                "requires_approval": True,  # Non-Negotiable Rule 8!
            },
        },
    ]

    edges = [
        {"id": "e1-2", "source": "step_1", "target": "step_2"},
        {"id": "e2-3", "source": "step_2", "target": "step_3"},
    ]

    with SessionLocal() as db:
        wf = Workflow(
            user_id=user_id,
            title="Demonstration E-Commerce Discount Flow",
            nodes=nodes,
            edges=edges,
            status="active",
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)
        workflow_id = wf.id

    # 3. Launch execution: POST /workflows/{id}/execute
    r_exec = client.post(f"/workflows/{workflow_id}/execute", headers=headers)
    assert r_exec.status_code == 201
    exec_data = r_exec.json()
    exec_id = exec_data["id"]

    # 4. Verify DAG paused at Step 3 awaiting approval!
    assert exec_data["status"] == "waiting_approval"
    assert exec_data["requires_approval"] is True
    assert exec_data["pending_approval_step"] == "step_3"

    # Verify Step 1 and Step 2 completed and produced correct outputs
    step_results = exec_data["step_results"]
    assert "step_1" in step_results
    assert step_results["step_1"]["output"]["id"] == 5
    assert step_results["step_1"]["output"]["price"] == 1000.0

    assert "step_2" in step_results
    assert step_results["step_2"]["output"] == 900.0

    # Verify Step 3 has NOT executed yet
    assert "step_3" not in step_results

    # 5. User explicitly approves Step 3: POST /executions/{id}/approve
    r_approve = client.post(f"/executions/{exec_id}/approve", headers=headers)
    assert r_approve.status_code == 200
    resumed_data = r_approve.json()

    # 6. Verify DAG resumed and finished with 'completed'
    assert resumed_data["status"] == "completed"
    assert resumed_data["approval_status"] == "approved"
    assert "step_3" in resumed_data["step_results"]

    step_3_output = resumed_data["step_results"]["step_3"]["output"]
    assert step_3_output["status"] == "confirmed"
    assert step_3_output["final_price"] == 900.0
    assert step_3_output["product_id"] == 5
    assert step_3_output["order_id"].startswith("ORD-")

    # 7. Query execution by ID
    r_inspect = client.get(f"/executions/{exec_id}", headers=headers)
    assert r_inspect.status_code == 200
    assert r_inspect.json()["status"] == "completed"

    # Clean up
    with SessionLocal() as db:
        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()


@pytest.mark.asyncio
async def test_dag_execution_rejection_flow():
    """Verify that rejecting a paused step sets status to 'cancelled' and halts execution."""
    user_id, token = _create_user_and_token("reject_flow_user@apiforge.ai")
    headers = {"Authorization": f"Bearer {token}"}

    r_conn = client.post(
        "/connections",
        json={"name": "Store", "base_url": "http://127.0.0.1:8000/mock/api/v1"},
        headers=headers,
    )
    conn_id = r_conn.json()["id"]

    nodes = [
        {
            "id": "step_del",
            "type": "api_call",
            "data": {
                "label": "Delete Item",
                "method": "DELETE",
                "path": "/products/1",
                "connection_id": conn_id,
                "requires_approval": True,
            },
        }
    ]

    with SessionLocal() as db:
        wf = Workflow(user_id=user_id, title="Delete Flow", nodes=nodes, edges=[])
        db.add(wf)
        db.commit()
        db.refresh(wf)
        wf_id = wf.id

    # Execute -> pauses
    r_exec = client.post(f"/workflows/{wf_id}/execute", headers=headers)
    exec_id = r_exec.json()["id"]
    assert r_exec.json()["status"] == "waiting_approval"

    # Reject -> cancels
    r_reject = client.post(f"/executions/{exec_id}/reject", headers=headers)
    assert r_reject.status_code == 200
    assert r_reject.json()["status"] == "cancelled"
    assert r_reject.json()["approval_status"] == "rejected"

    # Clean up
    with SessionLocal() as db:
        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()
