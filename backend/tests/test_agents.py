"""
APIForge AI Multi-Agent System Tests
Verifies the LangGraph multi-agent pipeline:
- Intent Detection Agent
- Endpoint Discovery Agent
- Schema Analysis Agent
- Data Mapping & Rule 8 Approval Gate Enforcement
- DAG Validation Agent
- Orchestrator Execution and Fallback
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import User, APIConnection, Endpoint
from app.security import get_password_hash, create_access_token
from app.agents.graph import (
    WorkflowAgentState,
    detect_intent_node,
    discover_endpoints_node,
    analyze_schemas_node,
    map_data_and_rules_node,
    validate_dag_node,
    multi_agent_orchestrator,
)
from app.services.workflow_generator import GeneratedWorkflowPlan, WorkflowStepPlan

client = TestClient(app)


def _setup_user_and_endpoints():
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="agent_test_user@apiforge.ai").first()
        if not u:
            u = User(
                email="agent_test_user@apiforge.ai",
                hashed_password=get_password_hash("AgentPass123!"),
                role="user",
                is_active=True,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
        user_id = u.id

        conn = db.query(APIConnection).filter_by(user_id=user_id, name="Agent Store").first()
        if not conn:
            conn = APIConnection(
                user_id=user_id,
                name="Agent Store",
                base_url="http://127.0.0.1:8000/mock/api/v1",
                auth_type="none",
            )
            db.add(conn)
            db.commit()
            db.refresh(conn)

            # Add test endpoints
            ep1 = Endpoint(
                connection_id=conn.id,
                path="/products/{id}",
                method="GET",
                summary="Get product details",
                parameters=[{"name": "id", "in": "path", "required": True}],
            )
            ep2 = Endpoint(
                connection_id=conn.id,
                path="/orders",
                method="POST",
                summary="Create order",
                request_body_schema={"type": "object", "required": ["product_id", "final_price"]},
            )
            db.add_all([ep1, ep2])
            db.commit()

    token = create_access_token(data={"sub": str(user_id), "email": "agent_test_user@apiforge.ai", "role": "user"})
    return user_id, token


@pytest.mark.asyncio
async def test_intent_detection_agent():
    """Verify Intent Detection agent extracts actions and state-change flag."""
    state: WorkflowAgentState = {
        "user_prompt": "Fetch product 5, calculate a 10% discount, and create an order",
        "user_id": 1,
        "connection_ids": None,
        "intent": {},
        "candidate_endpoints": [],
        "schema_context": {},
        "plan": None,
        "react_flow": None,
        "agent_trace": [],
        "error": None,
        "used_fallback": False,
    }

    res = await detect_intent_node(state)
    intent = res["intent"]
    assert "summary" in intent
    assert intent.get("requires_state_change") is True
    assert len(res["agent_trace"]) >= 1
    assert res["agent_trace"][0]["agent"] == "IntentDetectionAgent"


def test_schema_analysis_and_rule_8_enforcement():
    """Verify Schema Analysis and Data Mapping strictly enforce Rule 8 approval gates."""
    candidates = [
        {
            "id": 1,
            "connection_id": 10,
            "method": "GET",
            "path": "/products/{id}",
            "parameters": [{"name": "id"}],
            "request_body_schema": None,
        },
        {
            "id": 2,
            "connection_id": 10,
            "method": "POST",
            "path": "/orders",
            "parameters": [],
            "request_body_schema": {"type": "object"},
        },
    ]

    state: WorkflowAgentState = {
        "user_prompt": "demo",
        "user_id": 1,
        "connection_ids": None,
        "intent": {},
        "candidate_endpoints": candidates,
        "schema_context": {},
        "plan": None,
        "react_flow": None,
        "agent_trace": [],
        "error": None,
        "used_fallback": False,
    }

    # 1. Schema analysis
    res_schema = analyze_schemas_node(state)
    assert "GET /products/{id}" in res_schema["schema_context"]
    assert "POST /orders" in res_schema["schema_context"]

    # 2. Test Rule 8 enforcement
    dummy_plan = GeneratedWorkflowPlan(
        workflow_title="Test Rule 8 Workflow",
        workflow_description="Verify POST is marked with requires_approval",
        steps=[
            WorkflowStepPlan(
                step_id="step_1",
                description="Fetch product 1",
                type="api_call",
                method="GET",
                path="/products/1",
                requires_approval=False,
            ),
            WorkflowStepPlan(
                step_id="step_2",
                description="Create order for product 1",
                type="api_call",
                method="POST",
                path="/orders",
                requires_approval=False,  # Unset initially
            ),
        ],
    )
    state["plan"] = dummy_plan
    res_map = map_data_and_rules_node(state)
    mapped_plan = res_map["plan"]

    # Rule 8 non-negotiable verification!
    assert mapped_plan.steps[0].requires_approval is False
    assert mapped_plan.steps[1].requires_approval is True

    # 3. Test DAG validation and React Flow conversion
    state["plan"] = mapped_plan
    res_val = validate_dag_node(state)
    assert "react_flow" in res_val
    flow = res_val["react_flow"]
    assert len(flow["nodes"]) == 2
    assert flow["requires_approval"] is True


@pytest.mark.asyncio
async def test_multi_agent_api_endpoint():
    """Verify POST /workflows/generate-multi-agent API executes successfully."""
    user_id, token = _setup_user_and_endpoints()
    headers = {"Authorization": f"Bearer {token}"}

    prompt = "Get product 1 and calculate price"
    r = client.post(
        "/workflows/generate-multi-agent",
        json={"prompt": prompt},
        headers=headers,
    )
    assert r.status_code == 201
    wf = r.json()
    assert wf["id"] > 0
    assert "nodes" in wf
    assert len(wf["nodes"]) >= 1
    assert "agent_trace" in wf.get("dag_structure", {})
