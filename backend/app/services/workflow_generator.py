"""
APIForge AI Workflow Generator & Static Validator Service
Converts natural-language user instructions into strictly validated JSON DAG plans.
Uses local Ollama (qwen2.5:7b-instruct + nomic-embed-text) with Pydantic v2 schemas,
NetworkX DAG verification, template ancestor & schema validation, and Rule 8 enforcement.
Generates JSON plans only — never executable Python or JavaScript code.
"""
import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
import networkx as nx
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from sqlalchemy.orm import Session

from app.models import Endpoint, APIConnection
from app.services.ollama_client import ollama_client
from app.services.embeddings import semantic_search_endpoints
from app.services.transforms import (
    TEMPLATE_PATTERN,
    find_unresolved_templates,
    prevalidate_expression,
)

logger = logging.getLogger(__name__)

ALLOWED_STEP_TYPES = {"api_call", "transform", "condition"}
SUPPORTED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
MUTATING_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ALLOWED_TRANSFORM_OPS = {"", "calculate", "extract", "filter", "rename", "merge", "format"}

INJECTION_PATTERNS = [
    re.compile(r"\bignore\s+(all\s+)?previous\s+instructions\b", re.I),
    re.compile(r"\boutput\s+python\s+code\b", re.I),
    re.compile(r"\b__import__\s*\(", re.I),
    re.compile(r"\bos\.system\s*\(", re.I),
    re.compile(r"\bsubprocess\.", re.I),
    re.compile(r"\brm\s+-rf\b", re.I),
    re.compile(r"\bDROP\s+TABLE\b", re.I),
    re.compile(r"<\s*script\b", re.I),
]


def sanitize_user_prompt(prompt: str) -> str:
    """Reject prompt injection and code-execution instructions before LLM planning."""
    clean = (prompt or "").strip()
    if len(clean) < 5:
        raise ValueError("Workflow prompt must be at least 5 characters long")
    for pattern in INJECTION_PATTERNS:
        if pattern.search(clean):
            raise ValueError("Prompt rejected by security policy: suspected prompt injection or code-execution attempt")
    return clean


# ============================================================================
# Pydantic Schemas for AI Plan Validation
# ============================================================================

class WorkflowStepPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step_id: str = Field(..., description="Unique step identifier, e.g. step_1, step_2")
    step_type: str = Field(default="api_call", description="'api_call', 'transform', or 'condition'")
    description: str = Field(..., description="Human-readable summary of this step")
    method: Optional[str] = Field(None, description="HTTP method if api_call (GET, POST, PUT, DELETE, PATCH)")
    path: Optional[str] = Field(None, description="API path matching a registered endpoint if api_call")
    endpoint_id: Optional[int] = Field(None, description="Matched database endpoint ID")
    connection_id: Optional[int] = Field(None, description="Matched database connection ID")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Path and query parameters")
    headers: Dict[str, Any] = Field(default_factory=dict, description="Custom dynamic step headers")
    request_body: Optional[Dict[str, Any]] = Field(None, description="JSON request body payload or template")
    transformation: Optional[Dict[str, Any]] = Field(None, description="Data calculation or mapping specification")
    condition: Optional[Any] = Field(None, description="Predicate expression or comparison dict for condition/guard")
    when: Optional[str] = Field(None, description="Conditional branch route: 'true', 'false', or null")
    output_var: Optional[str] = Field(None, description="Optional alias variable stored under vars.<output_var>")
    error_handling: Optional[Dict[str, Any]] = Field(None, description="Retry/failure policy e.g. {'retry_count': 2}")
    requires_approval: bool = Field(False, description="Whether execution must pause for explicit user confirmation")
    depends_on: List[str] = Field(default_factory=list, description="List of prerequisite step_ids")

    @model_validator(mode="before")
    @classmethod
    def map_legacy_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "step_type" not in data and "type" in data:
                data["step_type"] = data["type"]

            # Normalize LLM request_body aliases (`body`, `payload`, `requestBody`, `json_body`)
            if not data.get("request_body"):
                for body_alias in ("body", "payload", "requestBody", "json_body"):
                    if isinstance(data.get(body_alias), dict):
                        data["request_body"] = data[body_alias]
                        break

            # Normalize LLM transform field aliases into canonical `transformation` dict
            trans = data.get("transformation")
            if not trans:
                for alias in ("transform", "transform_expression", "transform_expressions"):
                    if data.get(alias):
                        trans = data[alias]
                        break
                if isinstance(trans, str):
                    trans = {"operation": "calculate", "formula": trans}
                elif not trans and str(data.get("step_type") or "").strip().lower() == "transform":
                    if data.get("formula") or data.get("expression"):
                        trans = {
                            "operation": "calculate",
                            "formula": data.get("formula") or data.get("expression"),
                            **({"inputs": data["inputs"]} if isinstance(data.get("inputs"), dict) else {}),
                        }
                    elif data.get("fields") or data.get("mapping"):
                        trans = {
                            "operation": "extract",
                            **({"fields": data["fields"]} if data.get("fields") else {"mapping": data.get("mapping")}),
                        }

            if isinstance(trans, dict):
                trans = dict(trans)
                if "expr" in trans and "formula" not in trans and "expression" not in trans:
                    trans["formula"] = trans["expr"]
                if not trans.get("operation"):
                    if trans.get("formula") or trans.get("expression"):
                        trans["operation"] = "calculate"
                    elif trans.get("fields"):
                        trans["operation"] = "extract"
                data["transformation"] = trans
        return data

    @field_validator("step_id", mode="before")
    def validate_step_id(cls, v: Any) -> str:
        s = str(v).strip().lower()
        if not s.startswith("step_") and s.isdigit():
            s = f"step_{s}"
        clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", s)
        return clean or "step_1"

    @field_validator("step_type", mode="before")
    def normalize_step_type(cls, v: Any) -> str:
        s = str(v or "api_call").strip().lower()
        return s

    @field_validator("method", mode="before")
    def normalize_method(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().upper()
        return s or None

    @field_validator("when", mode="before")
    def normalize_when(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in {"true", "false"}:
            return s
        return None

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
# Static Validation, Endpoint Grounding & DAG Integrity
# ============================================================================

def _normalize_endpoint_path(path: str, base_url: Optional[str] = None) -> str:
    """Normalize endpoint path and strip overlapping base_url path prefix if present."""
    clean = "/" + (path or "").strip().lstrip("/")
    if clean != "/":
        clean = clean.rstrip("/")
    if base_url:
        from urllib.parse import urlparse
        prefix = urlparse(base_url).path.rstrip("/")
        if prefix and (clean == prefix or clean.startswith(prefix + "/")):
            stripped = clean[len(prefix):]
            clean = stripped or "/"
    return clean


def _match_step_to_endpoint(
    step: WorkflowStepPlan,
    available_endpoints: List[Endpoint],
    conn_map: Dict[int, APIConnection],
) -> Tuple[Optional[Endpoint], Dict[str, Any]]:
    """
    Match an api_call step strictly against registered endpoints owned by user.
    Extracts path parameter bindings when concrete path (e.g. '/products/5') matches template ('/products/{id}').
    """
    extracted_params: Dict[str, Any] = {}
    ep_by_id = {ep.id: ep for ep in available_endpoints if ep.id is not None}

    if step.endpoint_id is not None:
        if step.endpoint_id in ep_by_id:
            ep = ep_by_id[step.endpoint_id]
            if step.method and step.method.upper() != ep.method.upper():
                raise ValueError(
                    f"Step '{step.step_id}' uses method {step.method}, but endpoint {ep.id} requires {ep.method}"
                )
            if not step.path:
                step.path = ep.path
            base_url = conn_map[ep.connection_id].base_url if ep.connection_id in conn_map else None
            norm_step_path = _normalize_endpoint_path(step.path, base_url)
            norm_ep_path = _normalize_endpoint_path(ep.path, base_url)
            extracted_params = _match_path_pattern(norm_ep_path, norm_step_path) or {}
            return ep, extracted_params
        # If LLM supplied an out-of-range endpoint_id alongside explicit method+path, allow matching only user's registered endpoints
        if not (step.method and step.path):
            raise ValueError(
                f"Step '{step.step_id}' references unknown or unauthorized endpoint_id={step.endpoint_id}"
            )

    if not step.method or not step.path:
        return None, {}

    step_m = step.method.upper()
    norm_step_direct = _normalize_endpoint_path(step.path)

    # 1. Exact path match (also strip connection base_url prefix if LLM included it)
    for ep in available_endpoints:
        if ep.method.upper() != step_m:
            continue
        base_url = conn_map[ep.connection_id].base_url if ep.connection_id in conn_map else None
        norm_ep = _normalize_endpoint_path(ep.path, base_url)
        norm_step = _normalize_endpoint_path(step.path, base_url)
        if norm_ep == norm_step or _normalize_endpoint_path(ep.path) == norm_step_direct:
            return ep, {}

    # 2. Parameterized template match e.g. /products/{id} vs /products/5
    for ep in available_endpoints:
        if ep.method.upper() != step_m:
            continue
        base_url = conn_map[ep.connection_id].base_url if ep.connection_id in conn_map else None
        norm_ep = _normalize_endpoint_path(ep.path, base_url)
        norm_step = _normalize_endpoint_path(step.path, base_url)
        matched = _match_path_pattern(norm_ep, norm_step)
        if matched is not None:
            return ep, matched

    return None, {}


def _match_path_pattern(template_path: str, candidate_path: str) -> Optional[Dict[str, Any]]:
    """If candidate_path matches OpenAPI template_path (with {param}), return captured params dict."""
    param_names: List[str] = []
    regex_parts: List[str] = []
    pos = 0
    for m in re.finditer(r"\{([a-zA-Z0-9_]+)\}", template_path):
        regex_parts.append(re.escape(template_path[pos:m.start()]))
        param_names.append(m.group(1))
        regex_parts.append(r"([^/]+)")
        pos = m.end()
    regex_parts.append(re.escape(template_path[pos:]))
    full_re = "^" + "".join(regex_parts) + "$"
    match = re.match(full_re, candidate_path)
    if not match:
        return None
    captured: Dict[str, Any] = {}
    for name, raw_val in zip(param_names, match.groups()):
        # Ignore unsubstituted single-brace placeholder like '{id}'
        if raw_val.startswith("{") and raw_val.endswith("}") and not raw_val.startswith("{{"):
            continue
        if raw_val.isdigit():
            captured[name] = int(raw_val)
        else:
            captured[name] = raw_val
    return captured


def _extract_referenced_tokens(step: WorkflowStepPlan) -> List[str]:
    """Collect all template expression strings referenced anywhere in a step's fields."""
    texts: List[str] = []
    for field_val in [
        step.path,
        step.parameters,
        step.headers,
        step.request_body,
        step.transformation,
        step.condition,
    ]:
        texts.extend(find_unresolved_templates(field_val))
    return texts


def _validate_step_data_references(
    step: WorkflowStepPlan,
    ancestors: set[str],
    ancestor_outputs_by_var: Dict[str, str],
    step_endpoints: Dict[str, Optional[Endpoint]],
) -> None:
    """
    Validate all template references in step point strictly to ancestor steps
    (preventing forward/unknown/self references) and verify response_schema compatibility
    when schema properties are explicitly known.
    """
    raw_tokens = _extract_referenced_tokens(step)
    for token in raw_tokens:
        inner = token[2:-2].strip()
        if inner.startswith("$"):
            # JSONPath syntax - verify referenced step ID if starts with $.steps.<id> or $.<id>
            jp_parts = inner.lstrip("$.").split(".")
            if jp_parts:
                target = jp_parts[1] if jp_parts[0] == "steps" and len(jp_parts) > 1 else jp_parts[0]
                target = target.split("[", 1)[0]
                if target not in ancestors and target not in ancestor_outputs_by_var:
                    raise ValueError(
                        f"Step '{step.step_id}' references unavailable or non-ancestor step '{target}' in '{token}'"
                    )
            continue

        # Standard dot path
        parts = inner.split(".")
        first = parts[0].split("[", 1)[0]

        if first == "vars":
            if len(parts) < 2:
                raise ValueError(f"Step '{step.step_id}' has malformed variable reference '{token}'")
            var_name = parts[1].split("[", 1)[0]
            if var_name not in ancestor_outputs_by_var:
                raise ValueError(
                    f"Step '{step.step_id}' references unknown or non-ancestor variable '{var_name}' in '{token}'"
                )
            continue

        if first == "steps":
            if len(parts) < 2:
                raise ValueError(f"Step '{step.step_id}' has malformed step reference '{token}'")
            ref_step_id = parts[1].split("[", 1)[0]
            field_path_parts = parts[2:]
        else:
            ref_step_id = first
            field_path_parts = parts[1:]

        if ref_step_id not in ancestors and ref_step_id not in ancestor_outputs_by_var:
            raise ValueError(
                f"Step '{step.step_id}' references unknown or non-ancestor step '{ref_step_id}' in '{token}'"
            )

        # Check top-level output field compatibility against endpoint response_schema if declared
        actual_step_id = ancestor_outputs_by_var.get(ref_step_id, ref_step_id)
        ref_ep = step_endpoints.get(actual_step_id)
        if ref_ep and ref_ep.response_schema and isinstance(ref_ep.response_schema, dict):
            if field_path_parts and field_path_parts[0].split("[", 1)[0] == "output":
                after_output = field_path_parts[1:]
                # If array schema with predicate selector on output e.g. output[id=5].price
                output_seg = field_path_parts[0]
                schema = ref_ep.response_schema
                props = None
                if "[" in output_seg and schema.get("type") == "array" and isinstance(schema.get("items"), dict):
                    props = schema["items"].get("properties")
                elif "[" not in output_seg and schema.get("type") == "object":
                    props = schema.get("properties")

                if props and after_output:
                    top_field = after_output[0].split("[", 1)[0]
                    if top_field not in props:
                        raise ValueError(
                            f"Step '{step.step_id}' references field '{top_field}' not present in response schema of "
                            f"step '{actual_step_id}' ({ref_ep.method} {ref_ep.path}); available fields: {sorted(props.keys())}"
                        )


def _validate_type_literal(val: Any, schema_type: Optional[str], field_name: str, step_id: str) -> None:
    """Validate literal non-template values against expected JSONSchema field type."""
    if val is None or (isinstance(val, str) and "{{" in val) or not schema_type:
        return
    if schema_type == "integer" and (isinstance(val, bool) or not isinstance(val, int)):
        if isinstance(val, str) and val.isdigit():
            return
        raise ValueError(f"Step '{step_id}' field '{field_name}' expects integer, got {type(val).__name__}")
    elif schema_type == "number" and (isinstance(val, bool) or not isinstance(val, (int, float))):
        raise ValueError(f"Step '{step_id}' field '{field_name}' expects number, got {type(val).__name__}")
    elif schema_type == "string" and not isinstance(val, str):
        raise ValueError(f"Step '{step_id}' field '{field_name}' expects string, got {type(val).__name__}")
    elif schema_type == "boolean" and not isinstance(val, bool):
        raise ValueError(f"Step '{step_id}' field '{field_name}' expects boolean, got {type(val).__name__}")


def validate_and_enforce_plan(
    plan: GeneratedWorkflowPlan,
    available_endpoints: Optional[List[Endpoint]] = None,
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
    strict_endpoints: bool = False,
) -> GeneratedWorkflowPlan:
    """
    Comprehensively validate workflow DAG:
    1. Unique step IDs & valid step types / HTTP methods.
    2. Dependency existence, self-loop check & NetworkX cycle detection.
    3. Rule 8 enforcement: require approval on POST/PUT/PATCH/DELETE.
    4. Registered endpoint ownership verification & required param/body/auth validation.
    5. Strict ancestor data-reference validation & output schema compatibility.
    6. Safe transformation / condition expression AST prevalidation.
    """
    graph = nx.DiGraph()
    step_ids = [s.step_id for s in plan.steps]
    unique_ids = set(step_ids)

    # 1. Duplicate step IDs
    if len(unique_ids) != len(plan.steps):
        raise ValueError("Workflow contains duplicate step_ids")

    # 2. Step types & dependency graph build
    step_map = {s.step_id: s for s in plan.steps}
    for step in plan.steps:
        if step.step_type not in ALLOWED_STEP_TYPES:
            raise ValueError(f"Step '{step.step_id}' has unsupported step_type '{step.step_type}'")
        graph.add_node(step.step_id)
        for dep in step.depends_on:
            if dep not in unique_ids:
                raise ValueError(f"Step '{step.step_id}' references unknown dependency '{dep}'")
            if dep == step.step_id:
                raise ValueError(f"Step '{step.step_id}' cannot depend on itself")
            graph.add_edge(dep, step.step_id)

    # 3. Verify acyclicity with NetworkX
    if not nx.is_directed_acyclic_graph(graph):
        cycles = list(nx.simple_cycles(graph))
        raise ValueError(f"Workflow contains cyclic dependencies: {cycles}")

    # Load connections for auth/base_url validation if DB is available
    conn_map: Dict[int, APIConnection] = {}
    if db is not None and user_id is not None:
        conns = db.query(APIConnection).filter(APIConnection.user_id == user_id).all()
        conn_map = {c.id: c for c in conns}

    # Resolve available endpoints from DB if db+user_id passed and available_endpoints omitted
    endpoints_pool: List[Endpoint] = list(available_endpoints or [])
    if not endpoints_pool and db is not None and user_id is not None and strict_endpoints:
        endpoints_pool = (
            db.query(Endpoint)
            .join(APIConnection, Endpoint.connection_id == APIConnection.id)
            .filter(APIConnection.user_id == user_id)
            .all()
        )

    # 4. Enforce Rule 8 & validate each step against registered specs & schemas
    step_endpoints: Dict[str, Optional[Endpoint]] = {}
    for step in plan.steps:
        if step.step_type == "api_call":
            method_upper = (step.method or "GET").upper()
            step.method = method_upper
            if method_upper not in SUPPORTED_HTTP_METHODS:
                raise ValueError(f"Step '{step.step_id}' uses unsupported HTTP method '{method_upper}'")

            if method_upper in MUTATING_HTTP_METHODS:
                step.requires_approval = True

            if not step.path and not step.endpoint_id:
                raise ValueError(f"Step '{step.step_id}' of type 'api_call' must specify endpoint_id or path")

            if endpoints_pool or strict_endpoints:
                matched_ep, captured_params = _match_step_to_endpoint(step, endpoints_pool, conn_map)
                if not matched_ep and strict_endpoints:
                    raise ValueError(
                        f"Step '{step.step_id}' calls unregistered endpoint '{method_upper} {step.path}'. "
                        "Workflow steps must only reference endpoints registered in your API connections."
                    )
                if matched_ep:
                    step.endpoint_id = matched_ep.id
                    step.connection_id = matched_ep.connection_id
                    # Keep path template clean when endpoint matched
                    for k, v in captured_params.items():
                        step.parameters.setdefault(k, v)
                    step_endpoints[step.step_id] = matched_ep

                    # Validate required parameters
                    if matched_ep.parameters:
                        for p in matched_ep.parameters:
                            if isinstance(p, dict) and p.get("required"):
                                p_name = p.get("name")
                                p_in = p.get("in", "query")
                                if p_name and p_name not in step.parameters and p_name not in captured_params:
                                    raise ValueError(
                                        f"Step '{step.step_id}' missing required {p_in} parameter '{p_name}'"
                                    )

                    # Validate request body schema requirements
                    if matched_ep.request_body_schema and isinstance(matched_ep.request_body_schema, dict):
                        body_schema = matched_ep.request_body_schema
                        req_fields = body_schema.get("required") or []
                        if (
                            req_fields
                            and not isinstance(step.request_body, dict)
                            and not matched_ep.parameters
                            and isinstance(step.parameters, dict)
                            and all(rf in step.parameters for rf in req_fields)
                        ):
                            step.request_body = dict(step.parameters)
                            step.parameters = {}
                        if req_fields and not isinstance(step.request_body, dict):
                            raise ValueError(
                                f"Step '{step.step_id}' requires JSON request_body with fields {req_fields}"
                            )
                        if isinstance(step.request_body, dict):
                            props = body_schema.get("properties") or {}
                            for rf in req_fields:
                                if rf not in step.request_body:
                                    raise ValueError(
                                        f"Step '{step.step_id}' request_body missing required field '{rf}'"
                                    )
                            for k, v in step.request_body.items():
                                if k in props and isinstance(props[k], dict):
                                    _validate_type_literal(v, props[k].get("type"), k, step.step_id)

                    # Validate auth configuration on referenced connection
                    if matched_ep.connection_id in conn_map:
                        conn = conn_map[matched_ep.connection_id]
                        if not conn.is_active:
                            raise ValueError(f"Step '{step.step_id}' targets inactive API connection '{conn.name}'")
                        if matched_ep.security and conn.auth_type == "none" and "Authorization" not in (step.headers or {}):
                            raise ValueError(
                                f"Step '{step.step_id}' targets authenticated endpoint '{matched_ep.path}' "
                                f"but connection '{conn.name}' has auth_type='none'"
                            )
                        if conn.auth_type in {"bearer", "api_key", "basic"} and not conn.encrypted_credentials:
                            raise ValueError(
                                f"Step '{step.step_id}' connection '{conn.name}' specifies auth_type='{conn.auth_type}' "
                                "without configured credentials"
                            )
            else:
                step_endpoints[step.step_id] = None

        elif step.step_type == "transform":
            step_endpoints[step.step_id] = None
            trans = step.transformation or {}
            if not isinstance(trans, dict) or not trans:
                raise ValueError(
                    f"Transform step '{step.step_id}' requires a non-empty 'transformation' object "
                    "(e.g. {'operation': 'calculate', 'formula': '...', 'inputs': {...}})."
                )
            op = str(trans.get("operation") or "").strip().lower()
            if op not in ALLOWED_TRANSFORM_OPS:
                raise ValueError(f"Step '{step.step_id}' uses unsupported transform operation '{op}'")
            if op == "" and not any(trans.get(k) is not None for k in ("formula", "expression", "mapping", "inputs", "fields")):
                raise ValueError(
                    f"Transform step '{step.step_id}' must specify 'operation' and formula/fields/mapping."
                )
            if op == "calculate" and not (trans.get("formula") or trans.get("expression")):
                raise ValueError(
                    f"Calculate transform step '{step.step_id}' requires 'formula' or 'expression'."
                )
            formula = trans.get("formula") or trans.get("expression")
            if formula:
                prevalidate_expression(str(formula))
            pred = trans.get("predicate") or trans.get("condition")
            if pred:
                prevalidate_expression(str(pred))

        elif step.step_type == "condition":
            step_endpoints[step.step_id] = None
            cond = step.condition or (step.transformation or {}).get("condition") or (step.transformation or {}).get("expression")
            if cond is None:
                raise ValueError(f"Condition step '{step.step_id}' requires a 'condition' predicate")
            if isinstance(cond, str):
                prevalidate_expression(cond)
            elif isinstance(cond, dict) and ("expression" in cond or "formula" in cond):
                prevalidate_expression(str(cond.get("expression") or cond.get("formula")))

        if step.condition and step.step_type != "condition":
            if isinstance(step.condition, str):
                prevalidate_expression(step.condition)

    # 5. Validate template references strictly against DAG ancestors
    for step in plan.steps:
        ancestors = nx.ancestors(graph, step.step_id)
        ancestor_vars = {
            step_map[anc].output_var: anc
            for anc in ancestors
            if step_map[anc].output_var
        }
        _validate_step_data_references(step, ancestors, ancestor_vars, step_endpoints)

    return plan


def convert_plan_to_react_flow(
    plan: GeneratedWorkflowPlan,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Convert validated plan into React Flow nodes, edges, and structured DAG topology.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    graph = nx.DiGraph()
    step_type_by_id = {s.step_id: s.step_type for s in plan.steps}
    for s in plan.steps:
        graph.add_node(s.step_id)
        for dep in s.depends_on:
            graph.add_edge(dep, s.step_id)
    execution_order = list(nx.topological_sort(graph))

    for index, step in enumerate(plan.steps):
        pos_x = 80 + (index * 280)
        pos_y = 120 + ((index % 2) * 80)

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
                "headers": step.headers,
                "request_body": step.request_body,
                "transformation": step.transformation,
                "condition": step.condition,
                "when": step.when,
                "output_var": step.output_var,
                "error_handling": step.error_handling,
                "requires_approval": step.requires_approval,
            },
        }
        nodes.append(node)

        for dep in step.depends_on:
            edge_color = "#22c55e"
            edge_label = None
            if step_type_by_id.get(dep) == "condition":
                if step.when == "true":
                    edge_color = "#10b981"
                    edge_label = "true"
                elif step.when == "false":
                    edge_color = "#f59e0b"
                    edge_label = "false"

            edge: Dict[str, Any] = {
                "id": f"e-{dep}-{step.step_id}",
                "source": dep,
                "target": step.step_id,
                "animated": True,
                "style": {"stroke": edge_color, "strokeWidth": 2},
            }
            if edge_label:
                edge["label"] = edge_label
                edge["data"] = {"condition": edge_label}
            edges.append(edge)

    dag_structure = {
        "execution_order": execution_order,
        "total_steps": len(plan.steps),
    }

    return nodes, edges, dag_structure


def validate_react_flow_workflow(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
    strict_endpoints: bool = False,
) -> Dict[str, Any]:
    """
    Validate React Flow nodes & edges before persisting edits or running DAGExecutor.
    Also enforces Rule 8 approval flags on nodes in-place and returns topological dag_structure.
    """
    if not nodes:
        return {"execution_order": [], "total_steps": 0}

    deps_by_target: Dict[str, List[str]] = {n["id"]: [] for n in nodes if "id" in n}
    edge_when_by_target: Dict[str, Optional[str]] = {}
    for e in edges or []:
        src = e.get("source")
        tgt = e.get("target")
        if src and tgt and tgt in deps_by_target:
            deps_by_target[tgt].append(src)
            cond = (e.get("data") or {}).get("condition") or e.get("label")
            if cond in {"true", "false"}:
                edge_when_by_target[tgt] = cond

    steps: List[WorkflowStepPlan] = []
    for n in nodes:
        nid = n.get("id")
        if not nid:
            raise ValueError("Workflow node is missing required 'id'")
        data = n.get("data") or {}
        st = n.get("type") or data.get("step_type") or "api_call"
        step = WorkflowStepPlan(
            step_id=nid,
            step_type=st,
            description=data.get("label") or f"Step {nid}",
            method=data.get("method"),
            path=data.get("path"),
            endpoint_id=data.get("endpoint_id"),
            connection_id=data.get("connection_id"),
            parameters=data.get("parameters") or {},
            headers=data.get("headers") or {},
            request_body=data.get("request_body"),
            transformation=data.get("transformation"),
            condition=data.get("condition"),
            when=data.get("when") or edge_when_by_target.get(nid),
            output_var=data.get("output_var"),
            error_handling=data.get("error_handling"),
            requires_approval=bool(data.get("requires_approval", False)),
            depends_on=deps_by_target.get(nid, []),
        )
        steps.append(step)

    plan = GeneratedWorkflowPlan(
        workflow_title="Validated Workflow",
        workflow_description="Static validation",
        steps=steps,
    )
    validated = validate_and_enforce_plan(
        plan,
        db=db,
        user_id=user_id,
        strict_endpoints=strict_endpoints,
    )

    # Sync normalized fields & Rule 8 back into nodes
    val_map = {s.step_id: s for s in validated.steps}
    for n in nodes:
        nid = str(n["id"]).strip().lower()
        if nid in val_map:
            n.setdefault("data", {})["requires_approval"] = val_map[nid].requires_approval

    g = nx.DiGraph()
    for s in validated.steps:
        g.add_node(s.step_id)
        for dep in s.depends_on:
            g.add_edge(dep, s.step_id)

    return {
        "execution_order": list(nx.topological_sort(g)),
        "total_steps": len(validated.steps),
    }


# ============================================================================
# LLM Workflow Generation Engine
# ============================================================================

SYSTEM_PROMPT = """You are APIForge AI, an expert autonomous API workflow architect.
Your job is to convert natural-language user instructions into strictly valid JSON DAG workflow plans.

CRITICAL RULES:
1. Output VALID JSON ONLY. Never output Markdown fences (```), Python code, JavaScript code, or explanatory text.
2. NEVER invent endpoints. Every "api_call" step MUST strictly use one of the endpoints provided under AVAILABLE API ENDPOINTS (exact endpoint_id, method, and path template).
3. Every state-changing operation (POST, PUT, PATCH, DELETE) MUST have "requires_approval": true.
4. Reference outputs from prerequisite steps using ONLY the canonical syntax:
   - Object field: "{{steps.step_1.output.price}}" or nested "{{steps.step_1.output.contact.email}}"
   - Array item by predicate: "{{steps.step_1.output[id=5].price}}"
   - Scalar transform result: "{{steps.step_2.output}}"
   - Optional output_var alias: "{{vars.my_alias.price}}"
5. Use "step_type": "transform" for data calculations/mappings with SimpleEval (NO eval/exec):
   - Calculate: {"operation": "calculate", "formula": "price * 0.90", "inputs": {"price": "{{steps.step_1.output.price}}"}}
   - Filter array: {"operation": "filter", "source": "{{steps.step_1.output}}", "field": "id", "op": "==", "value": 5, "single": true}
   - Extract/Merge/Rename/Format: {"operation": "extract" | "merge" | "rename" | "format", ...}
6. Use "step_type": "condition" with "condition" expression and downstream steps using "when": "true" or "when": "false" depending on the condition step_id.
7. Include all required path/query parameters and required request_body fields matching the provided schemas.

Output Schema:
{
  "workflow_title": "Descriptive Title",
  "workflow_description": "Summary of what the workflow accomplishes",
  "steps": [
    {
      "step_id": "step_1",
      "step_type": "api_call",
      "description": "Fetch product details",
      "endpoint_id": 1,
      "connection_id": 1,
      "method": "GET",
      "path": "/products/{id}",
      "parameters": {"id": 5},
      "headers": {},
      "requires_approval": false,
      "depends_on": []
    },
    {
      "step_id": "step_2",
      "step_type": "transform",
      "description": "Calculate 10% discount",
      "transformation": {"operation": "calculate", "formula": "price * 0.90", "inputs": {"price": "{{steps.step_1.output.price}}"}},
      "requires_approval": false,
      "depends_on": ["step_1"]
    },
    {
      "step_id": "step_3",
      "step_type": "api_call",
      "description": "Create order with discounted price",
      "endpoint_id": 2,
      "connection_id": 1,
      "method": "POST",
      "path": "/orders",
      "request_body": {"product_id": "{{steps.step_1.output.id}}", "final_price": "{{steps.step_2.output}}"},
      "requires_approval": true,
      "depends_on": ["step_2"]
    }
  ]
}
"""


def _format_endpoint_context(endpoints: List[Endpoint]) -> str:
    """Build compact, token-efficient schema summary for discovered endpoints only."""
    lines: List[str] = []
    for ep in endpoints:
        params_desc = []
        for p in ep.parameters or []:
            if isinstance(p, dict):
                req_tag = "required" if p.get("required") else "optional"
                params_desc.append(f"{p.get('name')}({p.get('in')},{req_tag})")

        req_body_fields = []
        if ep.request_body_schema and isinstance(ep.request_body_schema, dict):
            req_list = set(ep.request_body_schema.get("required") or [])
            props = ep.request_body_schema.get("properties") or {}
            for k, v in props.items():
                t = v.get("type", "any") if isinstance(v, dict) else "any"
                mark = "*" if k in req_list else ""
                req_body_fields.append(f"{k}{mark}:{t}")

        resp_fields = []
        if ep.response_schema and isinstance(ep.response_schema, dict):
            target = ep.response_schema
            is_arr = target.get("type") == "array"
            if is_arr and isinstance(target.get("items"), dict):
                target = target["items"]
            props = target.get("properties") or {}
            for k, v in props.items():
                if isinstance(v, dict) and v.get("type") == "object" and isinstance(v.get("properties"), dict):
                    sub_keys = ",".join(v["properties"].keys())
                    resp_fields.append(f"{k}{{{sub_keys}}}")
                else:
                    resp_fields.append(k)
            if is_arr and resp_fields:
                resp_fields = [f"array[{', '.join(resp_fields)}]"]

        sec_note = f" | Auth: required" if ep.security else ""
        lines.append(
            f"- endpoint_id={ep.id} | connection_id={ep.connection_id} | {ep.method} {ep.path} "
            f"| Summary: {ep.summary or ep.description or ''} "
            f"| Params: [{', '.join(params_desc)}] "
            f"| Body(*=required): [{', '.join(req_body_fields)}] "
            f"| ResponseFields: [{', '.join(resp_fields)}]{sec_note}"
        )
    return "\n".join(lines)


def _extract_json_object(raw_response: str) -> Dict[str, Any]:
    """Clean Markdown fences if any and extract top-level JSON object."""
    cleaned = (raw_response or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        s = cleaned.find("{")
        e = cleaned.rfind("}")
        if s != -1 and e != -1 and e > s:
            try:
                return json.loads(cleaned[s : e + 1])
            except json.JSONDecodeError as err:
                raise ValueError(f"LLM failed to return valid JSON: {str(err)}\nRaw Response:\n{raw_response}") from err
        raise ValueError(f"LLM failed to return valid JSON\nRaw Response:\n{raw_response}")


async def generate_workflow_from_prompt(
    db: Session,
    user_id: int,
    prompt: str,
    discovered_endpoints: Optional[List[Endpoint]] = None,
    validation_feedback: Optional[str] = None,
    model: Optional[str] = None,
) -> tuple[GeneratedWorkflowPlan, List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Orchestrate authentic AI workflow generation using local Ollama:
    1. Validate prompt against injection attacks.
    2. Discover top-K relevant registered endpoints via nomic-embed-text semantic search.
    3. Pass ONLY relevant endpoint metadata to Ollama qwen2.5:7b-instruct (JSON format mode).
    4. Parse and validate JSON with Pydantic, NetworkX DAG checks, strict endpoint grounding,
       ancestor reference validation, and Rule 8 approval enforcement.
    5. Convert into React Flow visual nodes and edges.
    """
    safe_prompt = sanitize_user_prompt(prompt)

    # Full pool of user's registered endpoints for strict grounding
    all_user_endpoints = (
        db.query(Endpoint)
        .join(APIConnection, Endpoint.connection_id == APIConnection.id)
        .filter(APIConnection.user_id == user_id, APIConnection.is_active == True)
        .all()
    )
    if not all_user_endpoints:
        raise ValueError(
            "No registered API endpoints found for this user. "
            "Please add an API connection and import its OpenAPI specification first."
        )

    from app.services.semantic_planner import get_cached_plan, store_cached_plan
    cache_engine = f"llm:{model or 'default'}"
    if not validation_feedback:
        cached = get_cached_plan(user_id, safe_prompt, cache_engine, all_user_endpoints)
        if cached:
            return cached

    # 1. Relevant endpoint selection via semantic search (unless already passed by Discovery Agent)
    context_endpoints: List[Endpoint] = list(discovered_endpoints or [])
    if not context_endpoints:
        search_results = await semantic_search_endpoints(
            db=db,
            user_id=user_id,
            query=safe_prompt,
            top_k=8,
        )
        context_endpoints = [res["endpoint"] for res in search_results if res.get("endpoint")]

    if not context_endpoints:
        context_endpoints = all_user_endpoints[:8]

    context_str = _format_endpoint_context(context_endpoints)
    feedback_section = (
        f"\nPREVIOUS VALIDATION ERROR TO FIX:\n{validation_feedback}\nEnsure the corrected JSON resolves this issue.\n"
        if validation_feedback
        else ""
    )

    user_message = f"""USER INSTRUCTION:
"{safe_prompt}"

AVAILABLE API ENDPOINTS (Use ONLY these registered endpoints):
{context_str}
{feedback_section}
Generate the validated workflow plan JSON now:"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    # 2. Invoke local Ollama LLM
    raw_response = await ollama_client.chat(
        messages=messages,
        model=model,
        format="json",
        temperature=0.0,
    )

    # 3. Parse JSON plan cleanly (never execute code)
    plan_dict = _extract_json_object(raw_response)

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

    # Sanitize accidental self-dependency before strict check if omitted by weak prompt
    valid_step_ids = {s.step_id for s in plan.steps}
    for s in plan.steps:
        s.depends_on = [d for d in s.depends_on if d in valid_step_ids and d != s.step_id]

    # 5. Strict validation against user's registered API specifications + DAG + Rule 8
    validated_plan = validate_and_enforce_plan(
        plan,
        available_endpoints=all_user_endpoints,
        db=db,
        user_id=user_id,
        strict_endpoints=True,
    )

    # 6. React Flow conversion
    nodes, edges, dag_structure = convert_plan_to_react_flow(validated_plan)
    store_cached_plan(user_id, safe_prompt, cache_engine, all_user_endpoints, validated_plan, nodes, edges, dag_structure)

    return validated_plan, nodes, edges, dag_structure
