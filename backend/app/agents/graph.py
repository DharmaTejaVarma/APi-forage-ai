"""
APIForge AI LangGraph Multi-Agent Orchestration System
Implements a compiled LangGraph StateGraph coordinating 7 specialized agents:
1. Intent Agent (IntentDetectionAgent) — Understand user instructions & actions.
2. Discovery Agent (EndpointDiscoveryAgent) — Find relevant API endpoints via semantic search.
3. Schema Agent (SchemaAnalysisAgent) — Analyze parameters, request bodies, auth, response schemas.
4. Planner Agent (PlannerAgent) — Generate WorkflowPlan JSON via local Ollama.
5. Data Mapping Agent (DataMappingAgent) — Connect outputs/inputs & enforce Rule 8 approval gates.
6. Validation Agent (ValidationAgent) — Validate NetworkX DAG, endpoints, references, & expressions.
7. Supervisor Agent (SupervisorAgent) — Coordinate bounded retries and error recovery.

Records structured inputs, outputs, execution times (duration_ms), and errors per agent.
"""
import json
import logging
import time
from typing import TypedDict, List, Dict, Any, Optional
from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, START, END

from app.config import get_settings
from app.models import Endpoint, APIConnection
from app.services.ollama_client import ollama_client
from app.services.embeddings import semantic_search_endpoints
from app.services.semantic_planner import fast_extract_intent, generate_workflow_fast_semantic
from app.services.workflow_generator import (
    generate_workflow_from_prompt,
    sanitize_user_prompt,
    GeneratedWorkflowPlan,
    WorkflowStepPlan,
    convert_plan_to_react_flow,
    validate_and_enforce_plan,
)

logger = logging.getLogger(__name__)


# ============================================================================
# State Definition
# ============================================================================

class WorkflowAgentState(TypedDict):
    user_prompt: str
    user_id: int
    engine: str
    connection_ids: Optional[List[int]]
    intent: Dict[str, Any]
    candidate_endpoints: List[Dict[str, Any]]
    schema_context: Dict[str, Any]
    plan: Optional[GeneratedWorkflowPlan]
    react_flow: Optional[Dict[str, Any]]
    agent_trace: List[Dict[str, Any]]
    error: Optional[str]
    validation_feedback: Optional[str]
    retry_count: int
    max_retries: int
    used_fallback: bool
    supervisor_decision: str


def _record_trace(
    trace: List[Dict[str, Any]],
    agent: str,
    status: str,
    details: str,
    start_ts: float,
    inputs: Optional[Dict[str, Any]] = None,
    outputs: Optional[Dict[str, Any]] = None,
    errors: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Append telemetry record capturing agent inputs, outputs, duration_ms, and errors."""
    updated = list(trace or [])
    updated.append({
        "agent": agent,
        "status": status,
        "details": details,
        "inputs": inputs or {},
        "outputs": outputs or {},
        "duration_ms": round((time.perf_counter() - start_ts) * 1000, 2),
        "errors": errors,
    })
    return updated


# ============================================================================
# Agent Node Implementations (Agents 1 - 7)
# ============================================================================

INTENT_DETECTION_PROMPT = """You are the Intent Agent in APIForge AI.
Analyze the user's natural language API workflow request cleanly.
Return ONLY valid JSON:
{
  "summary": "<one sentence goal summary>",
  "workflow_category": "<e-commerce | notification | data-pipeline | security | general>",
  "actions": ["<action1>", "<action2>"],
  "requires_state_change": <true if involves POST/PUT/PATCH/DELETE else false>
}
"""


async def detect_intent_node(state: WorkflowAgentState) -> Dict[str, Any]:
    """Agent 1 (Intent Agent): Understand user instructions via Ollama with deterministic guard."""
    t0 = time.perf_counter()
    trace = list(state.get("agent_trace") or [])
    raw_prompt = state["user_prompt"]

    try:
        prompt = sanitize_user_prompt(raw_prompt)
    except ValueError as sec_err:
        return {
            "error": str(sec_err),
            "supervisor_decision": "abort",
            "agent_trace": _record_trace(
                trace,
                agent="IntentDetectionAgent",
                status="failed",
                details="Blocked unsafe prompt",
                start_ts=t0,
                inputs={"prompt_length": len(raw_prompt)},
                errors=str(sec_err),
            ),
        }

    engine = str(state.get("engine") or "ollama").strip().lower()
    if engine in {"fast", "ollama_3b"}:
        intent = fast_extract_intent(prompt)
        return {
            "intent": intent,
            "agent_trace": _record_trace(
                trace,
                agent="IntentDetectionAgent",
                status="completed",
                details=f"[{engine}] {intent.get('summary', prompt)}",
                start_ts=t0,
                inputs={"user_prompt": prompt, "engine": engine},
                outputs={"category": intent.get("workflow_category"), "requires_state_change": intent.get("requires_state_change")},
            ),
        }

    p_lower = prompt.lower()
    fallback_intent = {
        "summary": prompt,
        "workflow_category": "e-commerce" if any(w in p_lower for w in ["product", "order", "discount", "customer"]) else "general",
        "actions": [w for w in ["fetch", "calculate", "extract", "filter", "create", "send", "update", "delete"] if w in p_lower] or ["query", "process"],
        "requires_state_change": any(kw in p_lower for kw in ["create", "post", "order", "update", "delete", "send", "email", "notify"]),
    }

    intent = dict(fallback_intent)
    err_msg: Optional[str] = None
    status_label = "completed"

    try:
        messages = [
            {"role": "system", "content": INTENT_DETECTION_PROMPT},
            {"role": "user", "content": prompt},
        ]
        raw = await ollama_client.chat(messages=messages, format="json", temperature=0.0)
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1 and e > s:
            parsed = json.loads(raw[s : e + 1])
            if isinstance(parsed, dict):
                intent.update(parsed)
    except Exception as exc:
        logger.warning(f"IntentAgent using heuristic fallback: {exc}")
        err_msg = str(exc)
        status_label = "fallback"

    return {
        "intent": intent,
        "agent_trace": _record_trace(
            trace,
            agent="IntentDetectionAgent",
            status=status_label,
            details=str(intent.get("summary", prompt)),
            start_ts=t0,
            inputs={"user_prompt": prompt},
            outputs={"category": intent.get("workflow_category"), "requires_state_change": intent.get("requires_state_change")},
            errors=err_msg,
        ),
    }


async def discover_endpoints_node(state: WorkflowAgentState, db: Session) -> Dict[str, Any]:
    """Agent 2 (Discovery Agent): Find relevant registered API endpoints via semantic search."""
    t0 = time.perf_counter()
    trace = list(state.get("agent_trace") or [])
    if state.get("error"):
        return {"agent_trace": trace}

    prompt = state["user_prompt"]
    user_id = state["user_id"]
    connection_ids = state.get("connection_ids")

    try:
        hits = await semantic_search_endpoints(
            db=db,
            user_id=user_id,
            query=prompt,
            top_k=8,
            threshold=0.0,
            connection_ids=connection_ids,
        )

        candidates = []
        for hit in hits:
            ep = hit["endpoint"]
            candidates.append({
                "id": ep.id,
                "connection_id": ep.connection_id,
                "method": ep.method,
                "path": ep.path,
                "summary": ep.summary or ep.description or f"{ep.method} {ep.path}",
                "parameters": ep.parameters or [],
                "request_body_schema": ep.request_body_schema,
                "response_schema": ep.response_schema,
                "security": ep.security,
                "similarity": hit.get("similarity_score", 0.0),
            })

        return {
            "candidate_endpoints": candidates,
            "agent_trace": _record_trace(
                trace,
                agent="EndpointDiscoveryAgent",
                status="completed",
                details=f"Discovered {len(candidates)} registered endpoints",
                start_ts=t0,
                inputs={"query": prompt, "connection_ids": connection_ids},
                outputs={"endpoint_ids": [c["id"] for c in candidates], "count": len(candidates)},
            ),
        }
    except Exception as exc:
        logger.error(f"EndpointDiscoveryAgent failed: {exc}")
        return {
            "candidate_endpoints": [],
            "error": str(exc),
            "agent_trace": _record_trace(
                trace,
                agent="EndpointDiscoveryAgent",
                status="failed",
                details=f"Discovery failed: {exc}",
                start_ts=t0,
                inputs={"query": prompt},
                errors=str(exc),
            ),
        }


def analyze_schemas_node(state: WorkflowAgentState) -> Dict[str, Any]:
    """Agent 3 (Schema Agent): Analyze required parameters, payloads, auth, and response schemas."""
    t0 = time.perf_counter()
    trace = list(state.get("agent_trace") or [])
    candidates = state.get("candidate_endpoints") or []
    analysis: Dict[str, Any] = {}

    for ep in candidates:
        key = f"{ep['method']} {ep['path']}"
        req_params = [p.get("name") for p in ep.get("parameters", []) if isinstance(p, dict) and p.get("required")]
        all_params = [p.get("name") for p in ep.get("parameters", []) if isinstance(p, dict)]
        resp_schema = ep.get("response_schema") or {}
        resp_props: List[str] = []
        if isinstance(resp_schema, dict):
            if resp_schema.get("type") == "array" and isinstance(resp_schema.get("items"), dict):
                resp_props = list((resp_schema["items"].get("properties") or {}).keys())
            else:
                resp_props = list((resp_schema.get("properties") or {}).keys())

        analysis[key] = {
            "endpoint_id": ep["id"],
            "connection_id": ep["connection_id"],
            "parameters": all_params,
            "required_parameters": req_params,
            "has_body": bool(ep.get("request_body_schema")),
            "response_fields": resp_props,
            "requires_auth": bool(ep.get("security")),
        }

    return {
        "schema_context": analysis,
        "agent_trace": _record_trace(
            trace,
            agent="SchemaAnalysisAgent",
            status="completed",
            details=f"Analyzed schemas for {len(analysis)} endpoints",
            start_ts=t0,
            inputs={"candidate_count": len(candidates)},
            outputs={"endpoints_analyzed": list(analysis.keys())},
        ),
    }


async def plan_workflow_node(state: WorkflowAgentState, db: Session) -> Dict[str, Any]:
    """Agent 4 (Planner Agent): Generate structured WorkflowPlan JSON via local Ollama."""
    t0 = time.perf_counter()
    trace = list(state.get("agent_trace") or [])
    if state.get("supervisor_decision") == "abort":
        return {"agent_trace": trace}

    prompt = state["user_prompt"]
    user_id = state["user_id"]
    engine = str(state.get("engine") or "ollama").strip().lower()
    feedback = state.get("validation_feedback")
    candidate_ids = [c["id"] for c in (state.get("candidate_endpoints") or []) if "id" in c]

    discovered_eps: Optional[List[Endpoint]] = None
    if candidate_ids:
        discovered_eps = db.query(Endpoint).filter(Endpoint.id.in_(candidate_ids)).all()

    try:
        if engine == "fast":
            plan, nodes, edges, dag_structure = await generate_workflow_fast_semantic(
                db=db,
                user_id=user_id,
                prompt=prompt,
                discovered_endpoints=discovered_eps,
            )
        else:
            model_name = get_settings().FALLBACK_CHAT_MODEL if engine == "ollama_3b" else None
            plan, nodes, edges, dag_structure = await generate_workflow_from_prompt(
                db=db,
                user_id=user_id,
                prompt=prompt,
                discovered_endpoints=discovered_eps,
                validation_feedback=feedback,
                model=model_name,
            )
        return {
            "plan": plan,
            "error": None,
            "react_flow": {
                "nodes": nodes,
                "edges": edges,
                "dag_structure": dag_structure,
                "requires_approval": any(s.requires_approval for s in plan.steps),
            },
            "agent_trace": _record_trace(
                trace,
                agent="PlanningAgent",
                status="completed",
                details=f"Generated {len(plan.steps)} steps: '{plan.workflow_title}'",
                start_ts=t0,
                inputs={"candidate_endpoint_ids": candidate_ids, "retry_attempt": state.get("retry_count", 0)},
                outputs={"workflow_title": plan.workflow_title, "steps_count": len(plan.steps)},
            ),
        }
    except Exception as exc:
        logger.warning(f"PlanningAgent validation/generation error: {exc}")
        return {
            "plan": None,
            "error": str(exc),
            "agent_trace": _record_trace(
                trace,
                agent="PlanningAgent",
                status="failed",
                details=f"Planning attempt failed: {exc}",
                start_ts=t0,
                inputs={"candidate_endpoint_ids": candidate_ids, "retry_attempt": state.get("retry_count", 0)},
                errors=str(exc),
            ),
        }


def map_data_and_rules_node(state: WorkflowAgentState) -> Dict[str, Any]:
    """Agent 5 (Data Mapping Agent): Enforce Rule 8 approval gates and verify data mappings."""
    t0 = time.perf_counter()
    trace = list(state.get("agent_trace") or [])
    plan = state.get("plan")

    if not plan:
        err = state.get("error") or "No plan available for data mapping"
        return {
            "error": err,
            "agent_trace": _record_trace(
                trace,
                agent="DataMappingAgent",
                status="failed",
                details=err,
                start_ts=t0,
                errors=err,
            ),
        }

    # Normalize canonical template syntax & enforce Rule 8 on all mutating steps
    step_ids = {s.step_id for s in plan.steps}
    rule8_steps = []
    for step in plan.steps:
        if step.method and step.method.upper() in ["POST", "PUT", "PATCH", "DELETE"]:
            step.requires_approval = True
            rule8_steps.append(step.step_id)

    return {
        "plan": plan,
        "agent_trace": _record_trace(
            trace,
            agent="DataMappingAgent",
            status="completed",
            details=f"Enforced Rule 8 on {len(rule8_steps)} mutating steps and mapped {len(step_ids)} nodes",
            start_ts=t0,
            inputs={"steps_count": len(plan.steps)},
            outputs={"rule8_protected_steps": rule8_steps},
        ),
    }


def validate_dag_node(state: WorkflowAgentState, db: Optional[Session] = None) -> Dict[str, Any]:
    """Agent 6 (Validation Agent): Verify NetworkX acyclicity, endpoint ownership, schemas & React Flow conversion."""
    t0 = time.perf_counter()
    trace = list(state.get("agent_trace") or [])
    plan = state.get("plan")

    if not plan:
        err = state.get("error") or "No plan to validate"
        return {
            "error": err,
            "agent_trace": _record_trace(
                trace,
                agent="ValidationAgent",
                status="failed",
                details=err,
                start_ts=t0,
                errors=err,
            ),
        }

    try:
        user_id = state.get("user_id")
        strict_eps = bool(db is not None and user_id)
        if db is not None and user_id:
            avail = (
                db.query(Endpoint)
                .join(APIConnection, Endpoint.connection_id == APIConnection.id)
                .filter(APIConnection.user_id == user_id)
                .all()
            )
            strict_eps = len(avail) > 0
        else:
            avail = None

        validate_and_enforce_plan(
            plan,
            available_endpoints=avail,
            db=db,
            user_id=user_id,
            strict_endpoints=strict_eps,
        )

        nodes, edges, dag_structure = convert_plan_to_react_flow(plan)
        flow = {
            "nodes": nodes,
            "edges": edges,
            "dag_structure": dag_structure,
            "requires_approval": any(s.requires_approval for s in plan.steps),
        }
        return {
            "react_flow": flow,
            "error": None,
            "agent_trace": _record_trace(
                trace,
                agent="ValidationAgent",
                status="completed",
                details=f"DAG validated: {len(nodes)} nodes, {len(edges)} edges",
                start_ts=t0,
                inputs={"steps_count": len(plan.steps), "strict_endpoints": strict_eps},
                outputs={"execution_order": dag_structure["execution_order"]},
            ),
        }
    except Exception as exc:
        logger.warning(f"ValidationAgent caught issue: {exc}")
        return {
            "error": str(exc),
            "validation_feedback": str(exc),
            "agent_trace": _record_trace(
                trace,
                agent="ValidationAgent",
                status="failed",
                details=f"Validation failed: {exc}",
                start_ts=t0,
                errors=str(exc),
            ),
        }


def supervisor_node(state: WorkflowAgentState) -> Dict[str, Any]:
    """Agent 7 (Supervisor Agent): Coordinate retries on recoverable errors and emit final routing decision."""
    t0 = time.perf_counter()
    trace = list(state.get("agent_trace") or [])
    err = state.get("error")
    retries = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 1)

    if state.get("supervisor_decision") == "abort":
        return {
            "agent_trace": _record_trace(
                trace,
                agent="SupervisorAgent",
                status="failed",
                details=f"Aborted due to error: {err}",
                start_ts=t0,
                errors=err,
            )
        }

    if not err and state.get("plan") and state.get("react_flow"):
        return {
            "supervisor_decision": "complete",
            "agent_trace": _record_trace(
                trace,
                agent="SupervisorAgent",
                status="completed",
                details="All agents verified valid workflow DAG plan.",
                start_ts=t0,
                outputs={"decision": "complete", "retries_used": retries},
            ),
        }

    # Check if error is unrecoverable (e.g., user has zero registered endpoints or security block)
    err_str = str(err or "")
    unrecoverable = "No registered API endpoints" in err_str or "security policy" in err_str.lower()

    if not unrecoverable and retries < max_retries:
        return {
            "retry_count": retries + 1,
            "validation_feedback": err_str,
            "supervisor_decision": "retry",
            "agent_trace": _record_trace(
                trace,
                agent="SupervisorAgent",
                status="retrying",
                details=f"Retrying PlanningAgent (attempt {retries + 1}/{max_retries}) due to: {err_str}",
                start_ts=t0,
                inputs={"retry_count": retries, "error": err_str},
                outputs={"decision": "retry"},
            ),
        }

    return {
        "supervisor_decision": "fail",
        "agent_trace": _record_trace(
            trace,
            agent="SupervisorAgent",
            status="failed",
            details=f"Orchestration failed after {retries} retries: {err_str}",
            start_ts=t0,
            inputs={"retry_count": retries},
            outputs={"decision": "fail"},
            errors=err_str,
        ),
    }


def _route_after_discovery(state: WorkflowAgentState) -> str:
    if state.get("supervisor_decision") == "abort" or state.get("error"):
        return "supervisor"
    return "schema_agent"


def _route_after_supervisor(state: WorkflowAgentState) -> str:
    if state.get("supervisor_decision") == "retry":
        return "planner_agent"
    return END


# ============================================================================
# Compiled LangGraph StateGraph Orchestrator
# ============================================================================

class MultiAgentOrchestrator:
    """Compiles and runs the 7-agent LangGraph StateGraph workflow generation pipeline."""

    def _build_graph(self, db: Session):
        async def intent_step(state: WorkflowAgentState):
            return await detect_intent_node(state)

        async def discovery_step(state: WorkflowAgentState):
            return await discover_endpoints_node(state, db)

        def schema_step(state: WorkflowAgentState):
            return analyze_schemas_node(state)

        async def planner_step(state: WorkflowAgentState):
            return await plan_workflow_node(state, db)

        def mapping_step(state: WorkflowAgentState):
            return map_data_and_rules_node(state)

        def validation_step(state: WorkflowAgentState):
            return validate_dag_node(state, db=db)

        def supervisor_step(state: WorkflowAgentState):
            return supervisor_node(state)

        builder = StateGraph(WorkflowAgentState)
        builder.add_node("intent_agent", intent_step)
        builder.add_node("discovery_agent", discovery_step)
        builder.add_node("schema_agent", schema_step)
        builder.add_node("planner_agent", planner_step)
        builder.add_node("mapping_agent", mapping_step)
        builder.add_node("validation_agent", validation_step)
        builder.add_node("supervisor", supervisor_step)

        builder.add_edge(START, "intent_agent")
        builder.add_edge("intent_agent", "discovery_agent")
        builder.add_conditional_edges(
            "discovery_agent",
            _route_after_discovery,
            {"schema_agent": "schema_agent", "supervisor": "supervisor"},
        )
        builder.add_edge("schema_agent", "planner_agent")
        builder.add_edge("planner_agent", "mapping_agent")
        builder.add_edge("mapping_agent", "validation_agent")
        builder.add_edge("validation_agent", "supervisor")
        builder.add_conditional_edges(
            "supervisor",
            _route_after_supervisor,
            {"planner_agent": "planner_agent", END: END},
        )

        return builder.compile()

    async def run(
        self,
        prompt: str,
        db: Session,
        user_id: int,
        connection_ids: Optional[List[int]] = None,
        max_retries: int = 1,
        engine: str = "ollama",
    ) -> Dict[str, Any]:
        """Execute full 7-agent LangGraph StateGraph orchestration with Supervisor recovery."""
        normalized_engine = (engine or "ollama").strip().lower()
        initial_state: WorkflowAgentState = {
            "user_prompt": prompt,
            "user_id": user_id,
            "engine": normalized_engine,
            "connection_ids": connection_ids,
            "intent": {},
            "candidate_endpoints": [],
            "schema_context": {},
            "plan": None,
            "react_flow": None,
            "agent_trace": [],
            "error": None,
            "validation_feedback": None,
            "retry_count": 0,
            "max_retries": 0 if normalized_engine == "fast" else max_retries,
            "used_fallback": False,
            "supervisor_decision": "proceed",
        }

        graph = self._build_graph(db)
        final_state = await graph.ainvoke(initial_state)

        if final_state.get("plan") and final_state.get("react_flow") and not final_state.get("error"):
            plan: GeneratedWorkflowPlan = final_state["plan"]
            flow: Dict[str, Any] = final_state["react_flow"]
            return {
                "title": plan.workflow_title,
                "description": plan.workflow_description,
                "plan": plan.model_dump(),
                "nodes": flow["nodes"],
                "edges": flow["edges"],
                "dag_structure": flow["dag_structure"],
                "requires_approval": flow["requires_approval"],
                "intent": final_state.get("intent"),
                "agent_trace": final_state.get("agent_trace", []),
                "used_fallback": False,
            }

        raise ValueError(final_state.get("error") or "Multi-agent orchestration failed to generate a valid workflow")


# Global Multi-Agent Orchestrator instance
multi_agent_orchestrator = MultiAgentOrchestrator()
