"""
Phase 5 Workflow Generator Test Suite
Tests Pydantic plan validation, NetworkX static DAG verification, cycle detection,
Rule 8 approval requirement enforcement (POST/PUT/DELETE), and AI workflow generation with local Ollama.
"""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.models import User, Workflow, APIConnection, Endpoint
from app.services.workflow_generator import (
    WorkflowStepPlan,
    GeneratedWorkflowPlan,
    validate_and_enforce_plan,
    convert_plan_to_react_flow,
)
from app.services.embeddings import batch_embed_endpoints

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
# Static Plan & DAG Validation Tests
# ============================================================================

def test_plan_pydantic_schema_validation():
    """Verify GeneratedWorkflowPlan validates correct structure and step IDs."""
    valid_plan_data = {
        "workflow_title": "Order Discount Flow",
        "workflow_description": "Fetch product and apply discount",
        "steps": [
            {
                "step_id": "step_1",
                "step_type": "api_call",
                "description": "Fetch product 5",
                "method": "GET",
                "path": "/products/5",
                "parameters": {"id": 5},
                "requires_approval": False,
                "depends_on": [],
            },
            {
                "step_id": "step_2",
                "step_type": "transform",
                "description": "Calculate 10% discount",
                "transformation": {"formula": "price * 0.9"},
                "requires_approval": False,
                "depends_on": ["step_1"],
            },
        ],
    }
    plan = GeneratedWorkflowPlan.model_validate(valid_plan_data)
    assert len(plan.steps) == 2
    assert plan.steps[0].step_id == "step_1"
    assert plan.steps[1].depends_on == ["step_1"]


def test_dag_validation_cycle_rejection():
    """Verify NetworkX static validation detects and rejects cyclic plans."""
    cyclic_plan = GeneratedWorkflowPlan(
        workflow_title="Cyclic Workflow",
        workflow_description="Invalid cycle",
        steps=[
            WorkflowStepPlan(
                step_id="step_a",
                description="Step A",
                depends_on=["step_b"],  # A depends on B
            ),
            WorkflowStepPlan(
                step_id="step_b",
                description="Step B",
                depends_on=["step_a"],  # B depends on A -> Cycle!
            ),
        ],
    )
    with pytest.raises(ValueError, match="cyclic dependencies"):
        validate_and_enforce_plan(cyclic_plan)


def test_dag_validation_missing_dependency():
    """Verify plan referencing a non-existent step dependency is rejected."""
    invalid_plan = GeneratedWorkflowPlan(
        workflow_title="Missing Dep",
        workflow_description="Invalid",
        steps=[
            WorkflowStepPlan(
                step_id="step_1",
                description="Step 1",
                depends_on=["step_999"],  # Unknown!
            )
        ],
    )
    with pytest.raises(ValueError, match="unknown dependency"):
        validate_and_enforce_plan(invalid_plan)


def test_rule_8_enforcement_approval_required():
    """
    Non-Negotiable Rule 8:
    Verify that any step with POST, PUT, PATCH, or DELETE is automatically enforced
    to have requires_approval=True, even if the LLM provided False.
    """
    plan = GeneratedWorkflowPlan(
        workflow_title="Approval Test",
        workflow_description="Enforce Rule 8",
        steps=[
            WorkflowStepPlan(
                step_id="step_read",
                step_type="api_call",
                description="Read item",
                method="GET",
                path="/items",
                requires_approval=False,
            ),
            WorkflowStepPlan(
                step_id="step_write",
                step_type="api_call",
                description="Create item",
                method="POST",
                path="/items",
                requires_approval=False,  # Should be overridden to True!
                depends_on=["step_read"],
            ),
            WorkflowStepPlan(
                step_id="step_delete",
                step_type="api_call",
                description="Delete item",
                method="DELETE",
                path="/items/1",
                requires_approval=False,  # Should be overridden to True!
                depends_on=["step_write"],
            ),
        ],
    )
    validated = validate_and_enforce_plan(plan)
    assert validated.steps[0].requires_approval is False  # GET remains False
    assert validated.steps[1].requires_approval is True   # POST forced to True
    assert validated.steps[2].requires_approval is True   # DELETE forced to True


def test_react_flow_conversion():
    """Verify conversion of validated plan to React Flow visual nodes and edges."""
    plan = GeneratedWorkflowPlan(
        workflow_title="UI Test",
        workflow_description="React Flow test",
        steps=[
            WorkflowStepPlan(
                step_id="step_1",
                step_type="api_call",
                description="Fetch",
                method="GET",
                path="/products",
            ),
            WorkflowStepPlan(
                step_id="step_2",
                step_type="transform",
                description="Discount",
                depends_on=["step_1"],
            ),
        ],
    )
    nodes, edges, dag = convert_plan_to_react_flow(plan)
    assert len(nodes) == 2
    assert len(edges) == 1
    assert edges[0]["source"] == "step_1"
    assert edges[0]["target"] == "step_2"
    assert "position" in nodes[0]
    assert nodes[0]["data"]["step_id"] == "step_1"


# ============================================================================
# End-to-End AI Workflow Generation API Tests
# ============================================================================

@pytest.mark.asyncio
async def test_generate_workflow_api_e2e():
    """
    Test natural-language workflow generation through the API endpoint using local Ollama.
    Prompt: 'Fetch product 5, apply a 10% discount and create an order using the discounted price.'
    """
    user_id, token = _create_user_and_token("gen_user_e2e@apiforge.ai")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Setup mock store connection and import OpenAPI
    r_conn = client.post(
        "/connections",
        json={"name": "Store API", "base_url": "http://127.0.0.1:8000/mock/api/v1"},
        headers=headers,
    )
    conn_id = r_conn.json()["id"]

    with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)
    client.post(f"/connections/{conn_id}/import-openapi", json=spec, headers=headers)

    with SessionLocal() as db:
        await batch_embed_endpoints(db, conn_id)

    # 2. Invoke workflow generator API
    user_instruction = "Fetch product 5, apply a 10% discount and create an order using the discounted price."
    response = client.post(
        "/workflows/generate",
        json={"prompt": user_instruction},
        headers=headers,
    )
    assert response.status_code == 201, f"Failed with: {response.text}"
    workflow = response.json()

    assert workflow["id"] is not None
    assert workflow["raw_prompt"] == user_instruction
    assert len(workflow["nodes"]) >= 2
    assert len(workflow["edges"]) >= 1

    # Verify at least one state-changing node requires approval (Rule 8)
    has_approval_step = any(n["data"].get("requires_approval") is True for n in workflow["nodes"])
    assert has_approval_step is True

    # 3. Retrieve workflow by ID
    wf_id = workflow["id"]
    r_get = client.get(f"/workflows/{wf_id}", headers=headers)
    assert r_get.status_code == 200
    assert r_get.json()["id"] == wf_id

    # 4. Duplicate workflow
    r_dup = client.post(f"/workflows/{wf_id}/duplicate", headers=headers)
    assert r_dup.status_code == 201
    assert "Copy" in r_dup.json()["title"]

    # Clean up
    with SessionLocal() as db:
        u = db.query(User).filter_by(id=user_id).first()
        if u:
            db.delete(u)
            db.commit()
