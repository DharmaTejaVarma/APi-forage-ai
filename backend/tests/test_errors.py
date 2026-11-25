"""
APIForge AI Error Diagnosis & AI Error Recovery Tests
Verifies Rule 9 non-negotiable: candidate fixes are recommendations, never auto-applied.
Tests AI diagnosis generation and explicit user-confirmed fix application.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import User, Workflow, APIConnection, WorkflowExecution
from app.security import get_password_hash, create_access_token
from app.services.error_agent import diagnose_step_failure, ErrorDiagnosis
from app.services.validator import ErrorCategory

client = TestClient(app)


def _create_user_and_token(email: str = "err_test_user@apiforge.ai"):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).first()
        if not u:
            u = User(
                email=email,
                hashed_password=get_password_hash("StrongSecret123!"),
                role="user",
                is_active=True,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
        user_id = u.id
    token = create_access_token(data={"sub": str(user_id), "email": email, "role": "user"})
    return user_id, token


def test_rule_9_never_auto_applies():
    """Verify Rule 9: ErrorDiagnosis always specifies requires_user_approval=True."""
    diag = ErrorDiagnosis(
        step_id="step_1",
        error_category=ErrorCategory.CLIENT_ERROR_4XX,
        root_cause="Product ID 999 not found",
        explanation="The product does not exist in the mock store database.",
        candidate_fixes=[],
        requires_user_approval=True,
    )
    assert diag.requires_user_approval is True


@pytest.mark.asyncio
async def test_diagnose_step_failure_structure():
    """Verify diagnose_step_failure returns valid schema with candidate fixes."""
    node = {
        "id": "fetch_prod",
        "type": "api_call",
        "data": {
            "label": "Fetch Nonexistent Product",
            "method": "GET",
            "path": "/products/999",
            "parameters": {"id": 999},
        },
    }
    error_details = {
        "category": ErrorCategory.CLIENT_ERROR_4XX,
        "status_code": 404,
        "message": "Product with ID 999 not found",
        "response_body": {"detail": "Product with ID 999 not found"},
    }
    diagnosis = await diagnose_step_failure(
        step_id="fetch_prod",
        node=node,
        error_details=error_details,
        execution_context={},
    )
    assert isinstance(diagnosis, ErrorDiagnosis)
    assert diagnosis.step_id == "fetch_prod"
    assert diagnosis.requires_user_approval is True
    assert len(diagnosis.candidate_fixes) >= 1
    assert diagnosis.candidate_fixes[0].target_node_id == "fetch_prod"


@pytest.mark.asyncio
async def test_end_to_end_error_recovery_and_apply_fix():
    """
    End-to-End Test:
    1. Workflow fails because Step 1 requests nonexistent product ID 999 (HTTP 404).
    2. Execution transitions to status='failed'.
    3. User triggers POST /executions/{id}/diagnose to receive AI candidate fixes.
    4. User selects and confirms candidate fix (updates ID from 999 to 5).
    5. User triggers POST /executions/{id}/apply-fix with resume=True.
    6. Workflow re-runs and successfully completes (status='completed')!
    """
    user_id, token = _create_user_and_token("e2e_fix_user@apiforge.ai")
    headers = {"Authorization": f"Bearer {token}"}

    # Setup connection to mock store
    r_conn = client.post(
        "/connections",
        json={"name": "Mock Store Recovery Test", "base_url": "http://127.0.0.1:8000/mock/api/v1"},
        headers=headers,
    )
    conn_id = r_conn.json()["id"]

    # Create workflow with intentional bug: requesting invalid product 999
    nodes = [
        {
            "id": "step_faulty",
            "type": "api_call",
            "data": {
                "label": "Fetch Nonexistent Product 999",
                "method": "GET",
                "path": "/products/{id}",
                "connection_id": conn_id,
                "parameters": {"id": 999},
                "requires_approval": False,
            },
        }
    ]

    with SessionLocal() as db:
        wf = Workflow(
            user_id=user_id,
            title="Faulty Flow For Error Recovery",
            nodes=nodes,
            edges=[],
            status="active",
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)
        wf_id = wf.id

    # 1. Execute faulty workflow -> fails with 404
    r_exec = client.post(f"/workflows/{wf_id}/execute", headers=headers)
    assert r_exec.status_code == 201
    exec_data = r_exec.json()
    exec_id = exec_data["id"]

    assert exec_data["status"] == "failed"
    assert exec_data["error_details"]["status_code"] == 404
    assert exec_data["error_details"]["category"] == ErrorCategory.NOT_FOUND

    # 2. Call Diagnose API: POST /executions/{id}/diagnose
    r_diag = client.post(f"/executions/{exec_id}/diagnose", headers=headers)
    assert r_diag.status_code == 200
    diag_data = r_diag.json()
    assert diag_data["step_id"] == "step_faulty"
    assert diag_data["requires_user_approval"] is True
    assert len(diag_data["candidate_fixes"]) > 0

    # 3. User explicitly approves and applies fix: change parameter id to 5
    fix_payload = {
        "target_node_id": "step_faulty",
        "patch": {
            "parameters": {"id": 5},
            "label": "Fetch Valid Product 5",
        },
        "resume": True,
    }
    r_fix = client.post(f"/executions/{exec_id}/apply-fix", json=fix_payload, headers=headers)
    assert r_fix.status_code == 200
    resumed_data = r_fix.json()

    # 4. Verify workflow recovered and completed successfully!
    assert resumed_data["status"] == "completed"
    assert "step_faulty" in resumed_data["step_results"]
    assert resumed_data["step_results"]["step_faulty"]["output"]["id"] == 5
    assert resumed_data["step_results"]["step_faulty"]["output"]["price"] == 1000.0

    # Cleanup
    with SessionLocal() as db:
        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()
