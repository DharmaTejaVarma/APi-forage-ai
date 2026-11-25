"""
APIForge AI Workflow Generator Service
Converts natural-language user instructions into strictly validated JSON DAG plans.
Uses local Ollama models (qwen2.5) with Pydantic v2 schemas and NetworkX static DAG validation.
Rule: Generates JSON plans only, never executable code.
"""
import json
import re
from typing import List, Dict, Any, Optional
import networkx as nx
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.models import Endpoint, APIConnection
from app.services.ollama_client import ollama_client
from app.services.embeddings import semantic_search_endpoints


# ============================================================================
# Pydantic Schemas for AI Plan Validation
# ============================================================================

class WorkflowStepPlan(BaseModel):
    step_id: str = Field(..., description="Unique step identifier, e.g. step_1, step_2")
    step_type: str = Field(default="api_call", description="'api_call', 'transform', or 'condition'")
    description: str = Field(..., description="Human-readable summary of this step")
    method: Optional[str] = Field(None, description="HTTP method if api_call (GET, POST, PUT, DELETE, PATCH)")
    path: Optional[str] = Field(None, description="API path if api_call")
    endpoint_id: Optional[int] = Field(None, description="Matched database endpoint ID")
    connection_id: Optional[int] = Field(None, description="Matched database connection ID")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Path and query parameters")
    request_body: Optional[Dict[str, Any]] = Field(None, description="JSON request body payload or template")
    transformation: Optional[Dict[str, Any]] = Field(None, description="Data calculation or mapping rules")
    requires_approval: bool = Field(False, description="Whether execution must pause for explicit user confirmation")
    depends_on: List[str] = Field(default_factory=list, description="List of prerequisite step_ids")

    @field_validator("step_id", mode="before")
    def validate_step_id(cls, v: Any) -> str:
        s = str(v).strip().lower()
        if not s.startswith("step_") and s.isdigit():
            s = f"step_{s}"
        clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", s)
        return clean or "step_1"

    @field_validator("depends_on", mode="before")
    def validate_depends_on(cls, v: Any) -> List[str]:
        if not v:
            return []
        if isinstance(v, (str, int)):
            v = [v]
        res = []
        for item in v:
            s = str(item).strip().lower()
            if not s.startswith("step_") and s.isdigit():
                s = f"step_{s}"
            res.append(s)
        return res


class GeneratedWorkflowPlan(BaseModel):
    workflow_title: str = Field(..., description="Clear title for the generated workflow")
    workflow_description: str = Field(..., description="Summary of what the workflow achieves")
    steps: List[WorkflowStepPlan] = Field(..., min_length=1, description="Sequential or parallel DAG steps")


# ============================================================================
# Static Validation & DAG Integrity
# ============================================================================

def validate_and_enforce_plan(plan: GeneratedWorkflowPlan, available_endpoints: Optional[List[Endpoint]] = None) -> GeneratedWorkflowPlan:
    """
    Statically validate plan DAG acyclicity, dependency references, and enforce Rule 8:
    Require explicit approval before POST, PUT, PATCH, and DELETE operations.
    """
    graph = nx.DiGraph()
    step_ids = {s.step_id for s in plan.steps}

    # 1. Check duplicate step IDs
    if len(step_ids) != len(plan.steps):
        raise ValueError("Workflow contains duplicate step_ids")

    # 2. Build graph and check dependencies
    for step in plan.steps:
        graph.add_node(step.step_id)
        for dep in step.depends_on:
            if dep not in step_ids:
                raise ValueError(f"Step '{step.step_id}' references unknown dependency '{dep}'")
            if dep == step.step_id:
                raise ValueError(f"Step '{step.step_id}' cannot depend on itself")
            graph.add_edge(dep, step.step_id)

    # 3. Verify acyclicity
    if not nx.is_directed_acyclic_graph(graph):
        cycles = list(nx.simple_cycles(graph))
        raise ValueError(f"Workflow contains cyclic dependencies: {cycles}")

    # 4. Enforce Non-Negotiable Rule 8:
    # Explicit approval required before POST, PUT, PATCH, DELETE
    for step in plan.steps:
        if step.method and step.method.upper() in ["POST", "PUT", "PATCH", "DELETE"]:
            step.requires_approval = True

    # 5. Link endpoint_id and connection_id if available
    if available_endpoints:
        ep_map = {}
        for ep in available_endpoints:
            key = (ep.method.upper(), ep.path.rstrip("/"))
            ep_map[key] = ep
            path_pattern = re.sub(r"\{[a-zA-Z0-9_]+\}", r"[^/]+", ep.path)
            ep_map[f"regex:{ep.method.upper()}:{path_pattern}"] = ep

        for step in plan.steps:
            if step.method and step.path:
                norm_key = (step.method.upper(), step.path.rstrip("/"))
                if norm_key in ep_map:
                    matched = ep_map[norm_key]
                    step.endpoint_id = matched.id
                    step.connection_id = matched.connection_id
                else:
                    for k, ep in ep_map.items():
                        if isinstance(k, str) and k.startswith("regex:"):
                            _, m, pattern = k.split(":", 2)
                            if m == step.method.upper() and re.fullmatch(pattern, step.path):
                                step.endpoint_id = ep.id
                                step.connection_id = ep.connection_id
                                break

    return plan


def convert_plan_to_react_flow(plan: GeneratedWorkflowPlan) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Convert validated plan into React Flow nodes, edges, and structured DAG topology.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    for index, step in enumerate(plan.steps):
        pos_x = 80 + (index * 280)
        pos_y = 120 + ((index % 2) * 60)

        node = {
            "id": step.step_id,
            "type": step.step_type,
            "position": {"x": pos_x, "y": pos_y},
            "data": {
                "label": step.description,
                "step_id": step.step_id,
                "step_type": step.step_type,
                "method": step.method,
                "path": step.path,
                "endpoint_id": step.endpoint_id,
                "connection_id": step.connection_id,
                "parameters": step.parameters,
                "request_body": step.request_body,
                "transformation": step.transformation,
                "requires_approval": step.requires_approval,
            },
        }
        nodes.append(node)

        for dep in step.depends_on:
            edge = {
                "id": f"e-{dep}-{step.step_id}",
                "source": dep,
                "target": step.step_id,
                "animated": True,
                "style": {"stroke": "#22c55e", "strokeWidth": 2},
            }
            edges.append(edge)

    graph = nx.DiGraph()
    for s in plan.steps:
        graph.add_node(s.step_id)
        for dep in s.depends_on:
            graph.add_edge(dep, s.step_id)

    dag_structure = {
        "execution_order": list(nx.topological_sort(graph)),
        "total_steps": len(plan.steps),
    }

    return nodes, edges, dag_structure


# ============================================================================
# LLM Workflow Generation Engine
# ============================================================================

SYSTEM_PROMPT = """You are APIForge AI, an expert autonomous API workflow architect.
Your job is to convert natural-language user requests into structured executable JSON workflow plans.

CRITICAL RULES:
1. Output VALID JSON ONLY. Never output Markdown, code fences (```), Python code, or explanatory text.
2. Use ONLY the provided available API endpoints.
3. Every state-changing operation (POST, PUT, PATCH, DELETE) MUST have "requires_approval": true.
4. Pass data between steps using template syntax:
   - To reference another step's response: "{{step_1.output.field_name}}"
   - Example: "{{step_1.output.id}}" or "{{step_2.output.discounted_price}}"
5. If intermediate mathematical calculation or transformation is needed, create a "step_type": "transform" step with a "transformation" object (e.g. {"formula": "price * 0.9"}).

JSON Schema to follow:
{
  "workflow_title": "Descriptive Title",
  "workflow_description": "Detailed explanation of the workflow",
  "steps": [
    {
      "step_id": "step_1",
      "step_type": "api_call",
      "description": "Fetch product 5 details",
      "method": "GET",
      "path": "/products/5",
      "parameters": {"id": 5},
      "requires_approval": false,
      "depends_on": []
    },
    {
      "step_id": "step_2",
      "step_type": "transform",
      "description": "Calculate 10% discount on product price",
      "transformation": {
        "formula": "price * 0.9",
        "inputs": {"price": "{{step_1.output.price}}"}
      },
      "requires_approval": false,
      "depends_on": ["step_1"]
    },
    {
      "step_id": "step_3",
      "step_type": "api_call",
      "description": "Create order with discounted price",
      "method": "POST",
      "path": "/orders",
      "request_body": {
        "product_id": "{{step_1.output.id}}",
        "final_price": "{{step_2.output.discounted_price}}"
      },
      "requires_approval": true,
      "depends_on": ["step_2"]
    }
  ]
}
"""


async def generate_workflow_from_prompt(
    db: Session,
    user_id: int,
    prompt: str,
) -> tuple[GeneratedWorkflowPlan, List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Orchestrate workflow generation:
    1. Try ultra-fast pattern planner (< 50ms) for high-speed response.
    2. Fallback to local Ollama LLM with semantic retrieval and JSON format mode.
    3. Validate JSON with Pydantic and static DAG verification.
    4. Enforce approval constraints (Rule 8).
    5. Convert into visual React Flow nodes and edges.
    """
    # 0. Ultra-Fast Planner (< 50ms)
    try:
        from app.services.fast_planner import generate_fast_workflow_plan
        return generate_fast_workflow_plan(prompt=prompt, user_id=user_id, db=db)
    except Exception as exc:
        logger.info(f"Fast planner bypassed for prompt '{prompt[:40]}': {exc}")

    # 1. Discover relevant endpoints via semantic search
    search_results = await semantic_search_endpoints(
        db=db,
        user_id=user_id,
        query=prompt,
        top_k=6,
    )

    available_endpoints: List[Endpoint] = []
    endpoint_summaries = []

    if search_results:
        for res in search_results:
            ep = res["endpoint"]
            available_endpoints.append(ep)
            endpoint_summaries.append(
                f"- ID: {ep.id} | {ep.method} {ep.path} | Summary: {ep.summary} | "
                f"Params: {ep.parameters} | Body: {ep.request_body_schema}"
            )
    else:
        all_eps = (
            db.query(Endpoint)
            .join(APIConnection, Endpoint.connection_id == APIConnection.id)
            .filter(APIConnection.user_id == user_id)
            .limit(10)
            .all()
        )
        for ep in all_eps:
            available_endpoints.append(ep)
            endpoint_summaries.append(f"- ID: {ep.id} | {ep.method} {ep.path} | {ep.summary}")

    context_str = "\n".join(endpoint_summaries) if endpoint_summaries else "No pre-configured endpoints found."

    user_message = f"""USER INSTRUCTION:
"{prompt}"

AVAILABLE API ENDPOINTS:
{context_str}

Generate the workflow plan JSON now:"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    # 2. Invoke Local Ollama LLM
    raw_response = await ollama_client.chat(
        messages=messages,
        format="json",
        temperature=0.0,
    )

    # 3. Clean and parse JSON
    cleaned_json = raw_response.strip()
    if cleaned_json.startswith("```"):
        cleaned_json = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned_json)
        cleaned_json = re.sub(r"\n?```$", "", cleaned_json).strip()

    try:
        plan_dict = json.loads(cleaned_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM failed to return valid JSON: {str(e)}\nRaw Response:\n{raw_response}")

    # Robust wrapper extraction
    if "steps" not in plan_dict:
        for k in ["workflow", "plan", "data", "result"]:
            if k in plan_dict and isinstance(plan_dict[k], dict) and "steps" in plan_dict[k]:
                plan_dict = plan_dict[k]
                break

    if "workflow_title" not in plan_dict:
        plan_dict["workflow_title"] = plan_dict.get("title", "Generated Workflow")
    if "workflow_description" not in plan_dict:
        plan_dict["workflow_description"] = plan_dict.get("description", "Workflow generated from user instruction")

    # 4. Pydantic validation
    plan = GeneratedWorkflowPlan.model_validate(plan_dict)

    # Sanitize LLM dependencies to valid step IDs
    valid_step_ids = {s.step_id for s in plan.steps}
    for s in plan.steps:
        s.depends_on = [d for d in s.depends_on if d in valid_step_ids and d != s.step_id]

    # 5. Static DAG validation & Approval enforcement
    validated_plan = validate_and_enforce_plan(plan, available_endpoints)

    # 6. React Flow conversion
    nodes, edges, dag_structure = convert_plan_to_react_flow(validated_plan)

    return validated_plan, nodes, edges, dag_structure
