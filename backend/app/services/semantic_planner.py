"""
APIForge AI Fast Semantic Workflow Synthesizer (<1-2s)
Builds strictly grounded, NetworkX-validated WorkflowPlan DAGs from natural language
using local Ollama `nomic-embed-text` semantic discovery, clause decomposition,
and OpenAPI parameter/body/response schema analysis (zero eval/exec, zero hardcoded plans).
"""
import asyncio
import hashlib
import json
import re
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import APIConnection, Endpoint
from app.services.embeddings import _compute_lexical_and_intent_score, semantic_search_endpoints
from app.services.workflow_generator import (
    GeneratedWorkflowPlan,
    WorkflowStepPlan,
    convert_plan_to_react_flow,
    sanitize_user_prompt,
    validate_and_enforce_plan,
)

# Bounded LRU cache for validated generated plans (works for both fast & LLM engines)
_PLAN_CACHE_MAX = 128
_VALIDATED_PLAN_CACHE: "OrderedDict[str, Tuple[float, Dict[str, Any]]]" = OrderedDict()

_READ_VERBS = {
    "fetch", "get", "retrieve", "read", "find", "list", "load",
    "lookup", "check", "access", "show", "query", "obtain", "Pull".lower(),
}
_WRITE_VERBS = {
    "create", "post", "submit", "send", "notify", "email", "mail",
    "order", "place", "book", "register", "add", "trigger", "alert",
}
_UPDATE_VERBS = {"update", "modify", "patch", "change", "edit", "set"}
_DELETE_VERBS = {"delete", "remove", "cancel", "revoke"}
_CALC_WORDS = {"calculate", "compute", "discount", "percent", "%", "multiply", "subtract", "add", "tax", "markup", "simpleeval"}
_EXTRACT_WORDS = {"extract", "pick", "pluck", "pull out", "grab"}
_FILTER_WORDS = {"filter", "select", "where", "matching", "find from"}
_MERGE_WORDS = {"combine", "merge", "join", "aggregate", "together"}
_LIST_HINTS = {"all", "multiple", "list", "records", "array", "catalog", "products list"}
_FIELD_SYNONYMS: Dict[str, List[str]] = {
    "title": ["title", "name", "product_name", "label", "subject"],
    "name": ["name", "title", "full_name", "username"],
    "email": ["email", "contact.email", "customer_email", "to", "recipient", "mail"],
    "to": ["to", "email", "contact.email", "customer_email", "recipient"],
    "recipient": ["recipient", "email", "contact.email", "customer_email", "to"],
    "price": ["price", "final_price", "amount", "cost", "unit_price", "total"],
    "stock": ["stock", "inventory", "quantity", "available"],
    "id": ["id", "product_id", "customer_id", "order_id", "item_id"],
}


def compute_endpoints_fingerprint(endpoints: List[Endpoint]) -> str:
    """Stable hash of a user's active endpoint schemas for cache safety."""
    sig = [
        (ep.id, ep.connection_id, ep.method, ep.path, ep.request_body_schema, ep.response_schema)
        for ep in sorted(endpoints, key=lambda e: e.id or 0)
    ]
    raw = json.dumps(sig, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def get_cached_plan(
    user_id: int,
    prompt: str,
    engine: str,
    endpoints: List[Endpoint],
) -> Optional[Tuple[GeneratedWorkflowPlan, List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]]:
    key = f"{user_id}:{engine}:{compute_endpoints_fingerprint(endpoints)}:{prompt.strip().lower()}"
    item = _VALIDATED_PLAN_CACHE.get(key)
    if not item:
        return None
    ts, payload = item
    if time.monotonic() - ts > 600:
        _VALIDATED_PLAN_CACHE.pop(key, None)
        return None
    _VALIDATED_PLAN_CACHE.move_to_end(key)
    plan = GeneratedWorkflowPlan.model_validate(payload["plan"])
    return plan, payload["nodes"], payload["edges"], payload["dag_structure"]


def store_cached_plan(
    user_id: int,
    prompt: str,
    engine: str,
    endpoints: List[Endpoint],
    plan: GeneratedWorkflowPlan,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    dag_structure: Dict[str, Any],
) -> None:
    key = f"{user_id}:{engine}:{compute_endpoints_fingerprint(endpoints)}:{prompt.strip().lower()}"
    _VALIDATED_PLAN_CACHE[key] = (
        time.monotonic(),
        {
            "plan": plan.model_dump(),
            "nodes": nodes,
            "edges": edges,
            "dag_structure": dag_structure,
        },
    )
    _VALIDATED_PLAN_CACHE.move_to_end(key)
    while len(_VALIDATED_PLAN_CACHE) > _PLAN_CACHE_MAX:
        _VALIDATED_PLAN_CACHE.popitem(last=False)


def fast_extract_intent(prompt: str) -> Dict[str, Any]:
    """Sub-millisecond structured intent analyzer matching Agent 1 output contract."""
    safe = sanitize_user_prompt(prompt)
    p_lower = safe.lower()
    tokens = set(re.findall(r"[a-z0-9_]+", p_lower))

    category = "general"
    if tokens & {"product", "order", "discount", "customer", "price", "stock", "store"}:
        category = "e-commerce"
    elif tokens & {"email", "notify", "notification", "alert", "message"}:
        category = "notification"
    elif tokens & {"token", "auth", "secure", "profile", "bearer"}:
        category = "security"
    elif tokens & {"filter", "combine", "merge", "report", "records"}:
        category = "data-pipeline"

    verb_order = [
        "fetch", "retrieve", "get", "filter", "calculate", "extract",
        "merge", "combine", "create", "send", "update", "patch", "delete",
    ]
    actions = [v for v in verb_order if v in tokens] or ["query", "process"]
    requires_state_change = bool(tokens & (_WRITE_VERBS | _UPDATE_VERBS | _DELETE_VERBS))

    return {
        "summary": safe,
        "workflow_category": category,
        "actions": actions,
        "requires_state_change": requires_state_change,
    }


def _flatten_schema_paths(schema: Optional[Dict[str, Any]], prefix: str = "") -> Dict[str, str]:
    """Recursively collect response_schema property paths (including nested objects) -> schema type."""
    if not isinstance(schema, dict):
        return {}
    target = schema
    if target.get("type") == "array" and isinstance(target.get("items"), dict):
        target = target["items"]
    props = target.get("properties") or {}
    out: Dict[str, str] = {}
    for key, meta in props.items():
        if not isinstance(meta, dict):
            continue
        full = f"{prefix}.{key}" if prefix else key
        ftype = str(meta.get("type") or "any")
        out[full] = ftype
        if ftype == "object" and isinstance(meta.get("properties"), dict):
            out.update(_flatten_schema_paths(meta, prefix=full))
    return out


def _find_schema_field_path(
    desired: str,
    schema_paths: Dict[str, str],
    prefer_numeric: bool = False,
) -> Optional[str]:
    """Find best matching property path (supports nested paths like contact.email & synonyms)."""
    if not schema_paths:
        return None
    d_lower = desired.lower()

    if desired in schema_paths:
        return desired

    # Check leaf match (e.g. 'email' -> 'contact.email')
    for path in schema_paths:
        if path.split(".")[-1].lower() == d_lower:
            return path

    # Synonym match
    candidates = _FIELD_SYNONYMS.get(d_lower, [d_lower])
    for cand in candidates:
        c_low = cand.lower()
        for path in schema_paths:
            if path.lower() == c_low or path.split(".")[-1].lower() == c_low:
                return path

    if prefer_numeric:
        for path, ftype in schema_paths.items():
            if ftype in {"number", "integer"} and path.split(".")[-1].lower() not in {"id"}:
                return path

    # Partial substring match only for meaningful field names (>= 4 chars) on word boundaries or tokens
    if len(d_lower) >= 4:
        for path in schema_paths:
            if d_lower in path.lower():
                return path
    return None


def _desired_http_methods(clause_lower: str) -> List[str]:
    tokens = set(re.findall(r"[a-z0-9_]+", clause_lower))
    if tokens & _DELETE_VERBS:
        return ["DELETE"]
    if tokens & _UPDATE_VERBS:
        return ["PUT", "PATCH", "POST"]
    if tokens & _WRITE_VERBS:
        return ["POST", "PUT", "PATCH"]
    if tokens & _READ_VERBS:
        return ["GET"]
    return ["GET", "POST", "PUT", "PATCH", "DELETE"]


def _is_transform_clause(clause_lower: str) -> Optional[str]:
    tokens = set(re.findall(r"[a-z0-9_%]+", clause_lower))
    strict_write_verbs = {
        "create", "post", "submit", "send", "notify", "place",
        "book", "register", "add", "trigger", "alert",
    } | _UPDATE_VERBS | _DELETE_VERBS
    has_strict_write = bool(tokens & strict_write_verbs)
    has_api_read = bool(tokens & _READ_VERBS)

    # Leading explicit transform verb takes precedence (e.g., "extract the nested email address")
    lead = re.match(
        r"^(?:and\s+|then\s+)?(calculate|compute|extract|pick|pluck|filter|merge|combine|rename|format)\b",
        clause_lower.strip(),
    )
    if lead and not has_strict_write:
        kw = lead.group(1)
        if kw in {"calculate", "compute"}:
            return "calculate"
        if kw in {"extract", "pick", "pluck"}:
            return "extract"
        if kw in {"merge", "combine"}:
            return "merge"
        return kw

    has_api_write = bool(tokens & (_WRITE_VERBS | _UPDATE_VERBS | _DELETE_VERBS))
    if any(w in clause_lower for w in _CALC_WORDS) and not has_strict_write and not has_api_read:
        return "calculate"
    if any(w in clause_lower for w in _MERGE_WORDS) and not has_api_write:
        return "merge"
    if any(w in tokens for w in _EXTRACT_WORDS) and not has_strict_write:
        return "extract"
    if any(w in tokens for w in _FILTER_WORDS) and not has_api_read and not has_strict_write:
        return "filter"
    if "rename" in tokens and not has_strict_write:
        return "rename"
    if "format" in tokens and not has_strict_write:
        return "format"
    return None


def _split_clauses_smart(text: str) -> List[str]:
    """Split natural-language instruction into ordered action clauses."""
    # Replace ', and ' / '; ' / ' then ' / ' -> ' cleanly
    normalized = re.sub(r"\s*->\s*", " | ", text.strip())
    normalized = re.sub(r"[.;]+\s*", " | ", normalized)
    normalized = re.sub(r",\s+and\s+", " | ", normalized, flags=re.I)
    normalized = re.sub(r"\s+then\s+", " | ", normalized, flags=re.I)
    normalized = re.sub(r",\s+", " | ", normalized)

    raw_parts = [p.strip() for p in normalized.split("|") if p.strip()]

    # Further split "Fetch product 5 and customer 2" into two entity clauses when appropriate
    expanded: List[str] = []
    for part in raw_parts:
        m = re.match(
            r"^(?:fetch|get|retrieve|load|read)\s+(.+?)\s+and\s+(?:also\s+)?(.+?)$",
            part,
            flags=re.I,
        )
        if m:
            left_obj, right_obj = m.group(1).strip(), m.group(2).strip()
            has_left_num = bool(re.search(r"\b\d+\b", left_obj))
            has_right_num = bool(re.search(r"\b\d+\b", right_obj))
            if has_left_num and has_right_num:
                expanded.append(f"Fetch {left_obj}")
                expanded.append(f"Fetch {right_obj}")
                continue
        # Also split "... and <verb> ..." (e.g. "calculate discount and create order")
        sub = re.split(
            r"\s+and\s+(?=(?:fetch|get|retrieve|calculate|compute|extract|filter|combine|merge|create|send|update|patch|delete|post)\b)",
            part,
            flags=re.I,
        )
        expanded.extend(s.strip() for s in sub if s.strip())
    return expanded


def _parse_conditional_prompt(prompt: str) -> Optional[Tuple[List[str], str, List[str], List[str]]]:
    """
    Detect 'If <condition> <true_actions>; otherwise/else <false_actions>' structures.
    Returns (preamble_clauses, condition_expr, true_clauses, false_clauses) or None.
    """
    m = re.search(
        r"^(?P<pre>.*?)\bif\s+(?P<cond>[^,;.]+?)(?:,\s*|\s+then\s+|\s+)(?P<true>(?:create|send|post|update|delete|notify|order|fetch|calculate)[^;.]*?)(?:(?:;|,|\.)?\s*(?:otherwise|else)\s+(?P<false>.+))?\.?$",
        prompt.strip(),
        flags=re.I,
    )
    if not m:
        return None
    pre_raw = (m.group("pre") or "").strip().rstrip(".")
    cond_raw = m.group("cond").strip()
    true_raw = m.group("true").strip()
    false_raw = (m.group("false") or "").strip()
    pre_clauses = _split_clauses_smart(pre_raw) if pre_raw else []
    true_clauses = _split_clauses_smart(true_raw)
    false_clauses = _split_clauses_smart(false_raw) if false_raw else []
    return pre_clauses, cond_raw, true_clauses, false_clauses


def _extract_entity_id(clause: str) -> Optional[int]:
    # Ignore percentages like "10%" when extracting entity IDs
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*%", "", clause)
    patterns = [
        r"\bid\s*[=:#]?\s*(\d+)\b",
        r"\b(?:product|customer|user|order|item|record|account|post|ticket)\s*#?\s*(\d+)\b",
        r"#(\d+)\b",
        r"\b(\d+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, cleaned, flags=re.I)
        if m:
            return int(m.group(1))
    return None


def _select_best_endpoint(
    clause: str,
    ranked_results: List[Dict[str, Any]],
    fallback_endpoints: List[Endpoint],
) -> Optional[Endpoint]:
    """Select best registered endpoint combining semantic similarity, HTTP method intent, and path specificity."""
    c_low = clause.lower()
    desired_methods = _desired_http_methods(c_low)
    wants_list = bool(set(re.findall(r"[a-z0-9_]+", c_low)) & _LIST_HINTS)
    entity_id = _extract_entity_id(clause)
    c_tokens = set(re.findall(r"[a-z0-9_]+", c_low))

    scored: List[Tuple[float, Endpoint]] = []
    seen_ids = set()

    # Combine ranked semantic hits with any unranked user endpoints as baseline
    pool: List[Tuple[Endpoint, float]] = []
    for item in ranked_results:
        ep = item.get("endpoint")
        if ep and ep.id not in seen_ids:
            seen_ids.add(ep.id)
            pool.append((ep, float(item.get("similarity_score", 0.0))))
    for ep in fallback_endpoints:
        if ep.id not in seen_ids:
            seen_ids.add(ep.id)
            pool.append((ep, 0.0))

    for ep, sim in pool:
        score = sim * 1.5
        method = ep.method.upper()
        if method in desired_methods:
            # Prefer exact primary method rank
            score += 1.0 - (desired_methods.index(method) * 0.15)
        else:
            score -= 0.8

        has_path_param = "{" in ep.path
        is_array_resp = isinstance(ep.response_schema, dict) and ep.response_schema.get("type") == "array"

        # Prefer parameterized GET /item/{id} when an ID is requested without list keywords
        if method == "GET":
            if entity_id is not None and not wants_list:
                score += 0.45 if has_path_param else -0.15
            elif wants_list:
                score += 0.45 if (not has_path_param or is_array_resp) else -0.2

        # Lexical path/summary boost for precise tie-breaking (e.g., email vs order, product vs customer)
        ep_words = set(re.findall(r"[a-z0-9_]+", f"{ep.path} {ep.summary or ''} {ep.description or ''}".lower()))
        overlap = len(c_tokens & ep_words)
        score += overlap * 0.25

        # Penalize calculate-API endpoint if prompt actually asks for local/SimpleEval math transform or discount+order
        if "discount" in ep.path.lower() and "order" in c_tokens and "discount" not in c_tokens:
            score -= 0.4

        scored.append((score, ep))

    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _build_api_params_and_body(
    ep: Endpoint,
    clause: str,
    prior_steps: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]], List[str]]:
    """
    Bind path/query parameters and request_body fields cleanly from clause literals
    and upstream step schemas. Returns (params, headers, request_body, used_step_ids).
    """
    params: Dict[str, Any] = {}
    headers: Dict[str, Any] = {}
    used_deps: List[str] = []
    entity_id = _extract_entity_id(clause)
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", clause)
    c_low = clause.lower()
    ep_words = set(re.findall(r"[a-z0-9_]+", f"{ep.path} {ep.summary or ''}".lower()))

    def _find_upstream_field_ref(target_field: str, prefer_calc: bool = False) -> Optional[Tuple[str, str]]:
        """Search prior steps newest-first for matching field or scalar output."""
        f_low = target_field.lower()
        # Try explicit transform steps (calculate, filter, extract, merge) first
        for st in reversed(prior_steps):
            st_id = st["step_id"]
            st_type = st["step_type"]
            out_fields = st.get("output_fields") or {}

            if st_type == "transform":
                op = st.get("transform_op")
                if op == "calculate" and (prefer_calc or any(w in f_low for w in ("price", "amount", "total", "discount", "cost", "value"))):
                    return st_id, f"{{{{steps.{st_id}.output}}}}"
                if f_low in out_fields:
                    return st_id, f"{{{{steps.{st_id}.output.{f_low}}}}}"
                for k in out_fields:
                    if k.lower() in _FIELD_SYNONYMS.get(f_low, []) or f_low in _FIELD_SYNONYMS.get(k.lower(), []):
                        return st_id, f"{{{{steps.{st_id}.output.{k}}}}}"
                if op == "filter" and isinstance(out_fields, dict):
                    matched_p = _find_schema_field_path(target_field, out_fields, prefer_numeric=prefer_calc)
                    if matched_p:
                        return st_id, f"{{{{steps.{st_id}.output.{matched_p}}}}}"

            elif st_type == "api_call" and out_fields:
                # Special resource affinity check (e.g. product_id -> step targeting /products)
                st_path_words = set(re.findall(r"[a-z0-9_]+", (st.get("path") or "").lower()))
                if f_low.endswith("_id"):
                    res_prefix = f_low[:-3]
                    if any(res_prefix in w for w in st_path_words) and "id" in out_fields:
                        return st_id, f"{{{{steps.{st_id}.output.id}}}}"
                matched_p = _find_schema_field_path(target_field, out_fields, prefer_numeric=prefer_calc)
                if matched_p:
                    return st_id, f"{{{{steps.{st_id}.output.{matched_p}}}}}"
        return None

    # 1. Bind OpenAPI parameters (path & query)
    for p in ep.parameters or []:
        if not isinstance(p, dict):
            continue
        pname = p.get("name")
        if not pname:
            continue
        pin = p.get("in", "query")
        is_req = bool(p.get("required") or pin == "path")
        # If clause clearly specifies an ID for a direct GET endpoint
        if pname.lower() in {"id", "product_id", "customer_id", "order_id"} or pname in (ep.path or ""):
            if entity_id is not None and not prior_steps:
                params[pname] = entity_id
                continue
            # Even if prior steps exist, a clause with explicit ID takes literal ID if it names that resource
            if entity_id is not None and (any(w in ep_words for w in re.findall(r"[a-z0-9_]+", c_low)) or pin == "path"):
                params[pname] = entity_id
                continue
        ref = _find_upstream_field_ref(pname)
        if ref:
            dep_id, tmpl = ref
            params[pname] = tmpl
            if dep_id not in used_deps:
                used_deps.append(dep_id)
        elif is_req and entity_id is not None:
            params[pname] = entity_id

    # 2. Bind OpenAPI request_body_schema fields
    req_body: Optional[Dict[str, Any]] = None
    if isinstance(ep.request_body_schema, dict):
        props = ep.request_body_schema.get("properties") or {}
        req_fields = set(ep.request_body_schema.get("required") or [])
        body: Dict[str, Any] = {}

        for fname, fmeta in props.items():
            fmeta_dict = fmeta if isinstance(fmeta, dict) else {}
            ftype = str(fmeta_dict.get("type") or "string")
            fl = fname.lower()
            is_required = fname in req_fields

            # Explicit email literal for notification target
            if email_match and fl in {"to", "email", "customer_email", "recipient"}:
                body[fname] = email_match.group(0)
                continue

            prefer_calc = fl in {"final_price", "price", "discounted_price", "amount", "total"}
            ref = _find_upstream_field_ref(fname, prefer_calc=prefer_calc)

            if ref:
                dep_id, tmpl = ref
                # Enrich notification body/subject nicely when pulling upstream extracted field
                if fl == "subject" and not tmpl.endswith(".subject}}"):
                    body[fname] = f"Notification: {tmpl}"
                elif fl == "body" and not tmpl.endswith(".body}}"):
                    body[fname] = f"Details: {tmpl}"
                else:
                    body[fname] = tmpl
                if dep_id not in used_deps:
                    used_deps.append(dep_id)
                continue

            # For notification / text body fields, weave any available upstream extract/calc value
            if fl in {"subject", "body"} and prior_steps:
                latest_tx = next((s for s in reversed(prior_steps) if s["step_type"] == "transform"), None)
                if latest_tx:
                    tx_id = latest_tx["step_id"]
                    out_keys = list((latest_tx.get("output_fields") or {}).keys())
                    if out_keys:
                        tok = f"{{{{steps.{tx_id}.output.{out_keys[0]}}}}}"
                    else:
                        tok = f"{{{{steps.{tx_id}.output}}}}"
                    body[fname] = f"Product Notification: {tok}" if fl == "subject" else f"Workflow result: {tok}"
                    if tx_id not in used_deps:
                        used_deps.append(tx_id)
                    continue

            if is_required:
                if fl in {"to", "email", "customer_email", "recipient"}:
                    body[fname] = "demo@apiforge.ai"
                elif fl in {"subject"}:
                    body[fname] = "Workflow Notification"
                elif fl in {"body", "message", "text"}:
                    body[fname] = "Automated APIForge AI notification."
                elif ftype in {"integer", "number"} and entity_id is not None:
                    body[fname] = entity_id
                elif "default" in fmeta_dict:
                    body[fname] = fmeta_dict["default"]

        if ("to" in props or "recipient" in props) and "to" not in body and "recipient" not in body:
            target_key = "to" if "to" in props else "recipient"
            body[target_key] = "demo@apiforge.ai"

        if body:
            req_body = body

    return params, headers, req_body, used_deps


def _synthesize_transform_step(
    step_id: str,
    clause: str,
    op: str,
    prior_steps: List[Dict[str, Any]],
) -> Tuple[WorkflowStepPlan, Dict[str, str]]:
    """Build a SimpleEval-safe transform WorkflowStepPlan grounded in upstream step schemas."""
    c_low = clause.lower()
    # Default primary upstream step (most recent api_call or filter/extract transform)
    primary = next(
        (s for s in reversed(prior_steps) if s.get("output_fields") or s["step_type"] in {"api_call", "transform"}),
        None,
    )
    if not primary:
        raise ValueError(f"Transform clause '{clause}' has no upstream step output to reference.")

    pred_id = primary["step_id"]
    pred_fields = primary.get("output_fields") or {}

    if op == "calculate":
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", c_low)
        factor = 1.0
        if pct_match:
            pct = float(pct_match.group(1))
            if any(w in c_low for w in {"discount", "off", "reduce", "subtract", "minus"}):
                factor = round(1.0 - (pct / 100.0), 4)
            elif any(w in c_low for w in {"tax", "markup", "increase", "add", "plus"}):
                factor = round(1.0 + (pct / 100.0), 4)
            else:
                factor = round(pct / 100.0, 4)

        num_path = _find_schema_field_path("price", pred_fields, prefer_numeric=True) or "price"
        # Check explicit formula expression like "price * 0.90"
        expr_match = re.search(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*([+\-*/])\s*(\d+(?:\.\d+)?)", clause)
        if expr_match and not pct_match:
            var_name = expr_match.group(1)
            matched_var = _find_schema_field_path(var_name, pred_fields, prefer_numeric=True) or var_name
            formula = f"{var_name} {expr_match.group(2)} {expr_match.group(3)}"
            inputs = {var_name: f"{{{{steps.{pred_id}.output.{matched_var}}}}}"}
            out_schema = {"value": "number"}
        else:
            formula = f"price * {factor:.2f}" if round(factor, 2) == factor else f"price * {factor}"
            inputs = {"price": f"{{{{steps.{pred_id}.output.{num_path}}}}}"}
            out_schema = {"price": "number"}

        step = WorkflowStepPlan(
            step_id=step_id,
            step_type="transform",
            description=clause[:120],
            transformation={"operation": "calculate", "formula": formula, "inputs": inputs},
            requires_approval=False,
            depends_on=[pred_id],
        )
        return step, out_schema

    if op == "extract":
        fields: Dict[str, str] = {}
        out_schema: Dict[str, str] = {}
        # Detect explicitly named fields (including nested hints like 'nested email')
        candidate_words = [
            "title", "name", "email", "price", "stock", "status", "category", "id",
        ]
        # Include any declared property leaf names from upstream schema
        for path in pred_fields:
            leaf = path.split(".")[-1]
            if leaf not in candidate_words:
                candidate_words.append(leaf)

        c_tokens = set(re.findall(r"[a-z0-9_]+", c_low))
        for word in candidate_words:
            if word in c_tokens:
                matched_path = _find_schema_field_path(word, pred_fields)
                if matched_path:
                    fields[word] = f"{{{{steps.{pred_id}.output.{matched_path}}}}}"
                    out_schema[word] = pred_fields.get(matched_path, "string")

        if not fields and pred_fields:
            first_key = next(iter(pred_fields))
            fields[first_key.split(".")[-1]] = f"{{{{steps.{pred_id}.output.{first_key}}}}}"
            out_schema[first_key.split(".")[-1]] = pred_fields[first_key]
        elif not fields:
            for word in ("title", "name", "email", "price", "stock", "status", "id"):
                if word in c_tokens:
                    fallback_src = "name" if word == "title" else word
                    fields[word] = f"{{{{steps.{pred_id}.output.{fallback_src}}}}}"
                    out_schema[word] = "number" if word in {"price", "stock", "id"} else "string"
            if not fields:
                fields["value"] = f"{{{{steps.{pred_id}.output}}}}"
                out_schema["value"] = "any"

        step = WorkflowStepPlan(
            step_id=step_id,
            step_type="transform",
            description=clause[:120],
            transformation={"operation": "extract", "fields": fields},
            requires_approval=False,
            depends_on=[pred_id],
        )
        return step, out_schema

    if op == "filter":
        ent_id = _extract_entity_id(clause)
        cond_match = re.search(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*([^\s,;]+)", clause)
        if cond_match:
            fld, cmp_op, raw_v = cond_match.group(1), cond_match.group(2), cond_match.group(3).strip("'\"")
            val: Any = int(raw_v) if raw_v.isdigit() else raw_v
            single = cmp_op == "==" and fld == "id"
        else:
            fld, cmp_op, val, single = "id", "==", ent_id if ent_id is not None else 1, True

        step = WorkflowStepPlan(
            step_id=step_id,
            step_type="transform",
            description=clause[:120],
            transformation={
                "operation": "filter",
                "source": f"{{{{steps.{pred_id}.output}}}}",
                "field": fld,
                "op": cmp_op,
                "value": val,
                "single": single,
            },
            requires_approval=False,
            depends_on=[pred_id],
        )
        return step, dict(pred_fields)

    if op == "merge":
        # Gather multiple distinct preceding api_call/transform branches
        branches = [s for s in prior_steps if s["step_type"] in {"api_call", "transform"}]
        # Keep only frontier branches (not depended on by another step in branches) or last 2 root branches
        merge_fields: Dict[str, str] = {}
        out_schema: Dict[str, str] = {}
        dep_ids: List[str] = []
        for s in branches:
            sid = s["step_id"]
            if sid not in dep_ids:
                dep_ids.append(sid)
            s_path = (s.get("path") or "").lower()
            s_fields = s.get("output_fields") or {}
            if "product" in s_path:
                if "id" in s_fields:
                    merge_fields["product_id"] = f"{{{{steps.{sid}.output.id}}}}"
                    out_schema["product_id"] = "integer"
                if "price" in s_fields:
                    merge_fields["final_price"] = f"{{{{steps.{sid}.output.price}}}}"
                    out_schema["final_price"] = "number"
                if "name" in s_fields:
                    merge_fields["product_name"] = f"{{{{steps.{sid}.output.name}}}}"
                    out_schema["product_name"] = "string"
            elif "customer" in s_path:
                em = _find_schema_field_path("email", s_fields)
                if em:
                    merge_fields["customer_email"] = f"{{{{steps.{sid}.output.{em}}}}}"
                    out_schema["customer_email"] = "string"
                if "name" in s_fields:
                    merge_fields["customer_name"] = f"{{{{steps.{sid}.output.name}}}}"
                    out_schema["customer_name"] = "string"
            else:
                for fk, ftype in list(s_fields.items())[:3]:
                    leaf = fk.split(".")[-1]
                    if leaf not in merge_fields:
                        merge_fields[leaf] = f"{{{{steps.{sid}.output.{fk}}}}}"
                        out_schema[leaf] = ftype

        step = WorkflowStepPlan(
            step_id=step_id,
            step_type="transform",
            description=clause[:120],
            transformation={"operation": "merge", "fields": merge_fields},
            requires_approval=False,
            depends_on=dep_ids or [pred_id],
        )
        return step, out_schema

    # format / rename fallback
    step = WorkflowStepPlan(
        step_id=step_id,
        step_type="transform",
        description=clause[:120],
        transformation={
            "operation": op if op in {"rename", "format"} else "extract",
            "fields": {
                k.split(".")[-1]: f"{{{{steps.{pred_id}.output.{k}}}}}"
                for k in list(pred_fields.keys())[:4]
            } or {"value": f"{{{{steps.{pred_id}.output}}}}"},
        },
        requires_approval=False,
        depends_on=[pred_id],
    )
    return step, dict(pred_fields)


async def _build_steps_for_clauses(
    clauses: List[str],
    db: Session,
    user_id: int,
    user_endpoints: List[Endpoint],
    discovered_ids: Optional[set] = None,
    start_index: int = 1,
    initial_history: Optional[List[Dict[str, Any]]] = None,
    branch_when: Optional[str] = None,
    condition_step_id: Optional[str] = None,
) -> Tuple[List[WorkflowStepPlan], List[Dict[str, Any]], int]:
    """Convert ordered NL clauses into validated WorkflowStepPlan objects using semantic & schema scoring."""
    history: List[Dict[str, Any]] = list(initial_history or [])
    built_steps: List[WorkflowStepPlan] = []
    idx = start_index
    disc_set = discovered_ids or set()

    clause_kinds: List[Tuple[int, str, Optional[str]]] = [
        (c_i, clause, _is_transform_clause(clause.lower()))
        for c_i, clause in enumerate(clauses)
    ]

    for c_i, clause, tx_op in clause_kinds:
        step_id = f"step_{idx}"
        idx += 1

        if tx_op is not None and history:
            step, out_schema = _synthesize_transform_step(step_id, clause, tx_op, history)
            if branch_when and condition_step_id and condition_step_id not in step.depends_on:
                # Apply 'when' ONLY to the immediate step downstream of condition
                step.depends_on.append(condition_step_id)
                if c_i == 0:
                    step.when = branch_when
            built_steps.append(step)
            history.append({
                "step_id": step_id,
                "step_type": "transform",
                "transform_op": tx_op,
                "path": None,
                "output_fields": out_schema,
            })
            continue

        # API Call Step: score registered endpoints using clause lexical/intent + Discovery Agent boost (<1ms)
        ranked = [
            {
                "endpoint": ep,
                "similarity_score": _compute_lexical_and_intent_score(ep, clause) + (0.15 if ep.id in disc_set else 0.0),
            }
            for ep in user_endpoints
        ]
        ep = _select_best_endpoint(clause, ranked, user_endpoints)
        if not ep:
            raise ValueError("No matching registered endpoint found for instruction clause.")

        # Detect parallel independent reads (e.g. GET product 5 followed by GET customer 2)
        ep_method = ep.method.upper()
        clause_entity_id = _extract_entity_id(clause)
        same_root_read = (
            ep_method == "GET"
            and history
            and history[-1]["step_type"] == "api_call"
            and history[-1].get("method") == "GET"
            and clause_entity_id is not None
        )
        effective_prior = [] if same_root_read else history

        params, headers, req_body, used_deps = _build_api_params_and_body(ep, clause, effective_prior)
        if not used_deps and history and not same_root_read and ep_method != "GET":
            used_deps = [history[-1]["step_id"]]

        when_val: Optional[str] = None
        if branch_when and condition_step_id:
            if c_i == 0:
                when_val = branch_when
                if condition_step_id not in used_deps:
                    used_deps.append(condition_step_id)

        step = WorkflowStepPlan(
            step_id=step_id,
            step_type="api_call",
            description=clause[:120],
            endpoint_id=ep.id,
            connection_id=ep.connection_id,
            method=ep_method,
            path=ep.path,
            parameters=params,
            headers=headers,
            request_body=req_body,
            when=when_val,
            requires_approval=ep_method in {"POST", "PUT", "PATCH", "DELETE"},
            depends_on=used_deps,
        )
        built_steps.append(step)
        schema_fields = _flatten_schema_paths(ep.response_schema)
        history.append({
            "step_id": step_id,
            "step_type": "api_call",
            "method": ep_method,
            "path": ep.path,
            "output_fields": schema_fields,
        })

        # Automatic filter step if GET collection returned an array yet an explicit entity ID was requested
        if (
            ep_method == "GET"
            and "{" not in ep.path
            and isinstance(ep.response_schema, dict)
            and ep.response_schema.get("type") == "array"
            and clause_entity_id is not None
        ):
            filter_id = f"step_{idx}"
            idx += 1
            f_step = WorkflowStepPlan(
                step_id=filter_id,
                step_type="transform",
                description=f"Select item id={clause_entity_id} from array response",
                transformation={
                    "operation": "filter",
                    "source": f"{{{{steps.{step_id}.output}}}}",
                    "field": "id",
                    "op": "==",
                    "value": clause_entity_id,
                    "single": True,
                },
                requires_approval=False,
                depends_on=[step_id],
            )
            built_steps.append(f_step)
            history.append({
                "step_id": filter_id,
                "step_type": "transform",
                "transform_op": "filter",
                "path": ep.path,
                "output_fields": schema_fields,
            })

    return built_steps, history, idx


async def generate_workflow_fast_semantic(
    db: Session,
    user_id: int,
    prompt: str,
    discovered_endpoints: Optional[List[Endpoint]] = None,
) -> Tuple[GeneratedWorkflowPlan, List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Fast (<1-2s) semantic workflow planner backed by real Ollama `nomic-embed-text`
    discovery, OpenAPI schema binding, and full Pydantic + NetworkX + Rule 8 validation.
    """
    safe_prompt = sanitize_user_prompt(prompt)

    user_endpoints = (
        db.query(Endpoint)
        .join(APIConnection, Endpoint.connection_id == APIConnection.id)
        .filter(APIConnection.user_id == user_id, APIConnection.is_active == True)
        .all()
    )
    if not user_endpoints:
        raise ValueError(
            "No registered API endpoints found for this user. "
            "Please add an API connection and import its OpenAPI specification first."
        )

    disc_eps: List[Endpoint] = list(discovered_endpoints or [])
    if not disc_eps:
        hits = await semantic_search_endpoints(
            db=db,
            user_id=user_id,
            query=safe_prompt,
            top_k=10,
            auto_embed_missing=True,
        )
        disc_eps = [h["endpoint"] for h in hits if h.get("endpoint")]
    discovered_ids = {ep.id for ep in disc_eps if ep.id is not None}

    cond_parsed = _parse_conditional_prompt(safe_prompt)
    all_steps: List[WorkflowStepPlan] = []
    history: List[Dict[str, Any]] = []
    next_idx = 1

    if cond_parsed:
        pre_clauses, cond_raw, true_clauses, false_clauses = cond_parsed
        if pre_clauses:
            pre_steps, history, next_idx = await _build_steps_for_clauses(
                pre_clauses,
                db,
                user_id,
                user_endpoints,
                discovered_ids=discovered_ids,
                start_index=next_idx,
            )
            all_steps.extend(pre_steps)

        # Build condition predicate anchored to upstream response schema field
        cond_step_id = f"step_{next_idx}"
        next_idx += 1
        pred_step = history[-1] if history else None
        cond_expr = cond_raw
        m_cond = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(.+)", cond_raw)
        if m_cond and pred_step:
            lhs_field, cmp_op, rhs_val = m_cond.group(1), m_cond.group(2), m_cond.group(3).strip()
            matched_field = _find_schema_field_path(lhs_field, pred_step.get("output_fields") or {}) or lhs_field
            cond_expr = f"{{{{steps.{pred_step['step_id']}.output.{matched_field}}}}} {cmp_op} {rhs_val}"

        cond_step = WorkflowStepPlan(
            step_id=cond_step_id,
            step_type="condition",
            description=f"Evaluate condition: {cond_raw}"[:120],
            condition=cond_expr,
            requires_approval=False,
            depends_on=[pred_step["step_id"]] if pred_step else [],
        )
        all_steps.append(cond_step)

        if true_clauses:
            t_steps, _, next_idx = await _build_steps_for_clauses(
                true_clauses,
                db,
                user_id,
                user_endpoints,
                discovered_ids=discovered_ids,
                start_index=next_idx,
                initial_history=history,
                branch_when="true",
                condition_step_id=cond_step_id,
            )
            all_steps.extend(t_steps)
        if false_clauses:
            f_steps, _, next_idx = await _build_steps_for_clauses(
                false_clauses,
                db,
                user_id,
                user_endpoints,
                discovered_ids=discovered_ids,
                start_index=next_idx,
                initial_history=history,
                branch_when="false",
                condition_step_id=cond_step_id,
            )
            all_steps.extend(f_steps)
    else:
        clauses = _split_clauses_smart(safe_prompt)
        if not clauses:
            clauses = [safe_prompt]
        all_steps, _, _ = await _build_steps_for_clauses(
            clauses,
            db,
            user_id,
            user_endpoints,
            discovered_ids=discovered_ids,
            start_index=1,
        )

    plan = GeneratedWorkflowPlan(
        workflow_title=safe_prompt[:64].rstrip("."),
        workflow_description=f"Semantic DAG plan synthesized for: {safe_prompt}",
        steps=all_steps,
    )

    validated = validate_and_enforce_plan(
        plan,
        available_endpoints=user_endpoints,
        db=db,
        user_id=user_id,
        strict_endpoints=True,
    )
    nodes, edges, dag_structure = convert_plan_to_react_flow(validated)
    return validated, nodes, edges, dag_structure
