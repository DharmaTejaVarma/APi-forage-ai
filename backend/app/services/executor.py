"""
APIForge AI DAG Execution Engine
Executes workflows in topological DAG frontier order using NetworkX:
- Supports parallel execution of independent branches
- Supports conditional branching ('condition' nodes & edge 'true'/'false' guards) with skip propagation
- Enforces centralized strict template resolution & data-mapping before HTTP calls
- Enforces Non-Negotiable Rule 8 per-step approval for every POST/PUT/PATCH/DELETE operation
- Executes outgoing HTTP requests through centralized SecureHttpClient + build_target_url
- Captures rich per-step telemetry (request, headers masked, transferred vars, response, status, elapsed_ms)
- Computes final_output cleanly and enforces 12-category error classification
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import networkx as nx
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import Workflow, WorkflowExecution, APIConnection, Endpoint
from app.services.http_client import (
    secure_http_client,
    build_target_url,
    mask_headers_for_log,
    mask_params_for_log,
)
from app.services.transforms import (
    TEMPLATE_PATTERN,
    DataMappingError,
    resolve_value_from_context,
    resolve_templates_strict,
    evaluate_transformation,
    evaluate_condition,
)
from app.security import decrypt_secret, mask_secret
from app.services.validator import classify_error, validate_api_response, ErrorCategory
from app.services.workflow_generator import (
    MUTATING_HTTP_METHODS,
    validate_react_flow_workflow,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowExecutionError(Exception):
    def __init__(self, step_id: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.step_id = step_id
        self.details = details or {}


def _build_context(workflow_nodes: List[Dict[str, Any]], step_results: Dict[str, Any]) -> Dict[str, Any]:
    """Build normalized data-mapping context supporting steps.<id>, vars.<alias>, and legacy <id>."""
    steps_ctx: Dict[str, Any] = {}
    vars_ctx: Dict[str, Any] = {}
    aliases: Dict[str, Any] = {}
    node_map = {n["id"]: n for n in workflow_nodes if "id" in n}

    for sid, res in step_results.items():
        if not isinstance(res, dict):
            continue
        steps_ctx[sid] = res
        aliases[sid] = res
        out_var = (node_map.get(sid, {}).get("data") or {}).get("output_var")
        if out_var and res.get("status") == "completed":
            vars_ctx[out_var] = res.get("output")

    return {"steps": steps_ctx, "vars": vars_ctx, **aliases}


def _collect_transferred_variables(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and resolve all {{...}} tokens used by a step for monitor transparency."""
    raw_items = [
        node_data.get("path"),
        node_data.get("parameters"),
        node_data.get("headers"),
        node_data.get("request_body"),
        node_data.get("transformation"),
        node_data.get("condition"),
    ]
    serialized = json.dumps(raw_items, default=str)
    tokens = sorted(set(m.group(0) for m in TEMPLATE_PATTERN.finditer(serialized)))
    transferred: Dict[str, Any] = {}
    for tok in tokens:
        expr = tok[2:-2].strip()
        found, val = resolve_value_from_context(expr, context)
        if found:
            key_lower = expr.lower()
            if any(s in key_lower for s in ("password", "secret", "api_key")):
                transferred[tok] = mask_secret(str(val))
            else:
                transferred[tok] = val
    return transferred


class DAGExecutor:
    """DAG workflow execution engine with parallel frontier execution, conditional routing, and Rule 8 gates."""

    def __init__(self, db: Session, execution_id: int):
        self.db = db
        self.execution_id = execution_id

    def _log(self, execution: WorkflowExecution, step_id: Optional[str], message: str, level: str = "INFO"):
        """Append log event to execution record cleanly."""
        logs = list(execution.execution_logs or [])
        logs.append({
            "timestamp": utc_now().isoformat(),
            "step_id": step_id,
            "level": level,
            "message": message,
        })
        execution.execution_logs = logs
        flag_modified(execution, "execution_logs")

    def _build_graph_and_edges(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> Tuple[nx.DiGraph, Dict[Tuple[str, str], Optional[str]]]:
        graph = nx.DiGraph()
        edge_conditions: Dict[Tuple[str, str], Optional[str]] = {}
        node_map = {n["id"]: n for n in nodes if "id" in n}

        for nid in node_map:
            graph.add_node(nid)

        for e in edges:
            src, tgt = e.get("source"), e.get("target")
            if src in node_map and tgt in node_map:
                graph.add_edge(src, tgt)
                cond = (e.get("data") or {}).get("condition") or e.get("label")
                if cond is None:
                    cond = (node_map[tgt].get("data") or {}).get("when")
                edge_conditions[(src, tgt)] = str(cond).lower() if cond in ("true", "false") else None

        return graph, edge_conditions

    def _prepare_api_request_spec(
        self,
        node_data: Dict[str, Any],
        context: Dict[str, Any],
        user_id: int,
    ) -> Dict[str, Any]:
        """Synchronously load connection/endpoint metadata from DB and resolve strict templates before async HTTP call."""
        conn_id = node_data.get("connection_id")
        ep_id = node_data.get("endpoint_id")
        method = (node_data.get("method") or "GET").upper()
        raw_path = node_data.get("path") or ""

        ep = None
        if ep_id:
            ep = (
                self.db.query(Endpoint)
                .join(APIConnection, Endpoint.connection_id == APIConnection.id)
                .filter(Endpoint.id == ep_id, APIConnection.user_id == user_id)
                .first()
            )
            if ep and not conn_id:
                conn_id = ep.connection_id
            if ep and not raw_path:
                raw_path = ep.path

        conn = None
        if conn_id:
            conn = self.db.query(APIConnection).filter_by(id=conn_id, user_id=user_id).first()

        base_url = conn.base_url if conn else "http://127.0.0.1:8000/mock/api/v1"
        auth_type = conn.auth_type if conn else "none"

        credentials = None
        if conn and conn.encrypted_credentials:
            try:
                decrypted = decrypt_secret(conn.encrypted_credentials)
                credentials = json.loads(decrypted)
            except Exception:
                credentials = None

        # Strict template resolution BEFORE any outgoing HTTP request
        resolved_path = resolve_templates_strict(raw_path, context)
        resolved_params = resolve_templates_strict(node_data.get("parameters") or {}, context)
        resolved_step_headers = resolve_templates_strict(node_data.get("headers") or {}, context)
        raw_body = node_data.get("request_body")
        resolved_body = resolve_templates_strict(raw_body, context) if raw_body is not None else None

        # Build centralized normalized URL + query parameters
        full_url, query_params = build_target_url(base_url, resolved_path, resolved_params)

        # Merge default connection headers with step-level headers
        headers = dict(conn.default_headers if conn and conn.default_headers else {})
        if isinstance(resolved_step_headers, dict):
            headers.update({str(k): str(v) for k, v in resolved_step_headers.items()})

        expected_schema = node_data.get("response_schema")
        if not expected_schema and ep and ep.response_schema:
            expected_schema = ep.response_schema

        error_handling = node_data.get("error_handling") or {}
        transferred = _collect_transferred_variables(node_data, context)

        return {
            "method": method,
            "full_url": full_url,
            "query_params": query_params,
            "headers": headers,
            "resolved_body": resolved_body,
            "auth_type": auth_type,
            "credentials": credentials,
            "expected_schema": expected_schema,
            "allow_unsafe_retry": bool(error_handling.get("allow_unsafe_retry", False)),
            "timeout": error_handling.get("timeout"),
            "transferred_variables": transferred,
        }

    async def _run_api_spec(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """Execute prepared HTTP request asynchronously via SecureHttpClient & validate response."""
        method = spec["method"]
        full_url = spec["full_url"]
        query_params = spec["query_params"]
        resolved_body = spec["resolved_body"]

        resp = await secure_http_client.execute_request(
            method=method,
            url=full_url,
            headers=spec["headers"],
            params=query_params if query_params else None,
            json_data=resolved_body if method not in {"GET", "HEAD", "OPTIONS"} else None,
            auth_type=spec["auth_type"],
            credentials=spec["credentials"],
            timeout=spec["timeout"],
            allow_unsafe_retry=spec["allow_unsafe_retry"],
        )

        if not resp["success"]:
            err = RuntimeError(
                f"API call to '{method} {full_url}' failed with status {resp['status_code']}: {resp['data']}"
            )
            setattr(err, "status_code", resp["status_code"])
            setattr(err, "response_body", resp["data"])
            setattr(err, "request_info", resp.get("request_masked"))
            raise err

        if spec["expected_schema"]:
            val_res = validate_api_response(
                status_code=resp["status_code"],
                data=resp["data"],
                expected_schema=spec["expected_schema"],
            )
            if not val_res["valid"]:
                err = ValueError(val_res.get("reason") or val_res.get("summary"))
                setattr(err, "status_code", resp["status_code"])
                setattr(err, "response_body", resp["data"])
                setattr(err, "request_info", resp.get("request_masked"))
                raise err

        return resp

    def _should_skip_step(
        self,
        step_id: str,
        node: Dict[str, Any],
        predecessors: List[str],
        step_results: Dict[str, Any],
        edge_conditions: Dict[Tuple[str, str], Optional[str]],
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Determine whether step must be skipped due to upstream skip or unmet branch condition."""
        node_data = node.get("data", {})
        if not predecessors:
            # Optional top-level condition guard on non-condition node
            step_type = node.get("type") or node_data.get("step_type", "api_call")
            if step_type != "condition" and node_data.get("condition") is not None:
                cond_ok = evaluate_condition(node_data["condition"], context)
                if not cond_ok:
                    return True, "Condition guard evaluated to false"
            return False, None

        for src in predecessors:
            src_res = step_results.get(src, {})
            src_status = src_res.get("status")
            if src_status == "skipped":
                return True, f"Prerequisite step '{src}' was skipped"

            # Check branch condition edge ONLY against 'condition' prerequisite steps
            src_out = src_res.get("output")
            src_is_cond = (
                src_res.get("step_type") == "condition"
                or (isinstance(src_out, dict) and "result" in src_out)
            )
            branch_req = edge_conditions.get((src, step_id)) or (node_data.get("when") if src_is_cond else None)
            if branch_req in ("true", "false") and src_is_cond:
                cond_val = src_out.get("result") if isinstance(src_out, dict) and "result" in src_out else bool(src_out)
                if str(bool(cond_val)).lower() != branch_req:
                    return True, f"Branch condition '{branch_req}' not met (evaluated to {str(bool(cond_val)).lower()})"

        # Guard on target node if step_type != 'condition'
        step_type = node.get("type") or node_data.get("step_type", "api_call")
        if step_type != "condition" and node_data.get("condition") is not None:
            cond_ok = evaluate_condition(node_data["condition"], context)
            if not cond_ok:
                return True, "Step condition predicate evaluated to false"

        return False, None

    async def run(self, resume_from_approval: bool = False) -> WorkflowExecution:
        """
        Execute workflow DAG in topological frontier order.
        Supports parallel GETs, conditional branching, strict template resolution,
        and mandatory per-step Rule 8 human approval before every mutating HTTP operation.
        """
        execution = self.db.query(WorkflowExecution).filter_by(id=self.execution_id).first()
        if not execution:
            raise ValueError(f"Execution {self.execution_id} not found")

        workflow = self.db.query(Workflow).filter_by(id=execution.workflow_id).first()
        if not workflow:
            raise ValueError(f"Workflow {execution.workflow_id} not found")

        nodes = workflow.nodes or []
        edges = workflow.edges or []
        node_map = {n["id"]: n for n in nodes if "id" in n}

        # Pre-execution static validation
        try:
            validate_react_flow_workflow(
                nodes=nodes,
                edges=edges,
                db=self.db,
                user_id=workflow.user_id,
                strict_endpoints=False,
            )
        except Exception as val_err:
            execution.status = "failed"
            classification = classify_error(exception=val_err, error_message=f"Workflow validation error: {val_err}")
            classification["category"] = ErrorCategory.VALIDATION_FAILURE
            execution.error_details = {
                "step_id": "validation",
                "category": ErrorCategory.VALIDATION_FAILURE,
                "summary": classification["summary"],
                "message": str(val_err),
            }
            execution.completed_at = utc_now()
            self._log(execution, None, f"Pre-execution validation failed: {val_err}", "ERROR")
            self.db.commit()
            return execution

        graph, edge_conditions = self._build_graph_and_edges(nodes, edges)
        topo_order = list(nx.topological_sort(graph))

        step_results = dict(execution.step_results or {})
        approved_steps = set(execution.approved_steps or [])
        # Legacy single-flag compatibility if test pre-set execution.approval_status == 'approved'
        if execution.approval_status == "approved" and not approved_steps and execution.pending_approval_step:
            approved_steps.add(execution.pending_approval_step)

        if not resume_from_approval:
            execution.status = "running"
            execution.started_at = utc_now()
            self._log(execution, None, f"Started execution of workflow '{workflow.title}'")
            self.db.commit()
        else:
            execution.status = "running"
            execution.pending_approval_step = None
            execution.pending_approval_details = None
            self.db.commit()

        # Frontier execution loop
        while True:
            context = _build_context(nodes, step_results)
            finished = set(step_results.keys())
            if len(finished) >= len(topo_order):
                break

            ready_ids = [
                sid
                for sid in topo_order
                if sid not in finished and all(pred in finished for pred in graph.predecessors(sid))
            ]
            if not ready_ids:
                break

            runnable_batch: List[str] = []
            for sid in ready_ids:
                node = node_map[sid]
                skip, reason = self._should_skip_step(
                    sid,
                    node,
                    list(graph.predecessors(sid)),
                    step_results,
                    edge_conditions,
                    context,
                )
                if skip:
                    step_results[sid] = {
                        "step_id": sid,
                        "label": (node.get("data") or {}).get("label"),
                        "step_type": node.get("type") or (node.get("data") or {}).get("step_type", "api_call"),
                        "status": "skipped",
                        "output": None,
                        "reason": reason,
                    }
                    self._log(execution, sid, f"Skipped step '{sid}': {reason}")
                    execution.step_results = dict(step_results)
                    flag_modified(execution, "step_results")
                    self.db.commit()
                else:
                    runnable_batch.append(sid)

            if not runnable_batch:
                continue

            # Check per-step Rule 8 Approval Gates sequentially BEFORE launching batch
            for sid in runnable_batch:
                node = node_map[sid]
                node_data = node.get("data", {})
                step_type = node.get("type") or node_data.get("step_type", "api_call")
                method = (node_data.get("method") or "").upper()
                requires_approval = bool(node_data.get("requires_approval", False)) or (
                    step_type == "api_call" and method in MUTATING_HTTP_METHODS
                )

                # Support legacy approval_status='approved' only for single-mutation backwards compatibility
                # unless multiple mutating steps require distinct per-step approval
                already_approved = sid in approved_steps
                if requires_approval and not already_approved:
                    # Prepare exact approval inspection payload before pausing
                    approval_preview: Dict[str, Any] = {
                        "step_id": sid,
                        "label": node_data.get("label"),
                        "method": method,
                        "endpoint": node_data.get("path"),
                        "data_being_modified": node_data.get("request_body"),
                        "workflow_plan": [
                            {
                                "step_id": n["id"],
                                "label": (n.get("data") or {}).get("label"),
                                "method": (n.get("data") or {}).get("method"),
                                "path": (n.get("data") or {}).get("path"),
                                "status": step_results.get(n["id"], {}).get(
                                    "status",
                                    "waiting_approval" if n["id"] == sid else "pending",
                                ),
                            }
                            for n in nodes
                        ],
                    }
                    if step_type == "api_call":
                        try:
                            spec = self._prepare_api_request_spec(node_data, context, workflow.user_id)
                            approval_preview.update({
                                "endpoint": spec["full_url"],
                                "headers": mask_headers_for_log(spec["headers"]),
                                "parameters": mask_params_for_log(spec["query_params"]),
                                "request_body": spec["resolved_body"],
                                "transferred_variables": spec["transferred_variables"],
                            })
                        except Exception as prep_err:
                            # If template mapping itself fails before approval, surface the error directly!
                            execution.status = "failed"
                            classification = classify_error(exception=prep_err, error_message=str(prep_err))
                            execution.error_details = {
                                "step_id": sid,
                                "category": classification["category"],
                                "summary": classification["summary"],
                                "message": str(prep_err),
                            }
                            step_results[sid] = {
                                "step_id": sid,
                                "label": node_data.get("label"),
                                "step_type": step_type,
                                "status": "failed",
                                "error": str(prep_err),
                                "error_category": classification["category"],
                            }
                            execution.step_results = dict(step_results)
                            flag_modified(execution, "step_results")
                            execution.completed_at = utc_now()
                            self._log(execution, sid, f"Failed resolving step before approval: {prep_err}", "ERROR")
                            self.db.commit()
                            return execution

                    execution.status = "waiting_approval"
                    execution.requires_approval = True
                    execution.pending_approval_step = sid
                    execution.pending_approval_details = approval_preview
                    execution.approval_status = "pending"
                    self._log(
                        execution,
                        sid,
                        f"Execution paused: Step '{sid}' ({node_data.get('label')}) requires user approval before {method or 'mutation'}.",
                        "WARNING",
                    )
                    self.db.commit()
                    return execution

            # Prepare runnable specs synchronously cleanly before dispatching async coroutines
            api_specs: Dict[str, Dict[str, Any]] = {}
            async_tasks: List[Tuple[str, Any]] = []

            for sid in runnable_batch:
                node = node_map[sid]
                node_data = node.get("data", {})
                step_type = node.get("type") or node_data.get("step_type", "api_call")
                self._log(execution, sid, f"Executing step '{sid}': {node_data.get('label')}")

                if step_type == "api_call":
                    try:
                        spec = self._prepare_api_request_spec(node_data, context, workflow.user_id)
                        api_specs[sid] = spec
                        async_tasks.append((sid, self._run_api_spec(spec)))
                    except Exception as prep_err:
                        async def _fail_immediately(e=prep_err):
                            raise e
                        async_tasks.append((sid, _fail_immediately()))
                elif step_type == "transform":
                    async def _run_trans(nd=node_data, ctx=context):
                        return evaluate_transformation(nd.get("transformation") or {}, ctx)
                    async_tasks.append((sid, _run_trans()))
                elif step_type == "condition":
                    async def _run_cond(nd=node_data, ctx=context):
                        cond_expr = nd.get("condition") or (nd.get("transformation") or {}).get("condition")
                        res_bool = evaluate_condition(cond_expr, ctx)
                        return {"result": res_bool}
                    async_tasks.append((sid, _run_cond()))
                else:
                    async def _run_noop():
                        return None
                    async_tasks.append((sid, _run_noop()))

            # Execute runnable frontier concurrently
            raw_outcomes = await asyncio.gather(*(coro for _, coro in async_tasks), return_exceptions=True)

            # Process frontier outcomes deterministically
            for (sid, _), outcome in zip(async_tasks, raw_outcomes):
                node = node_map[sid]
                node_data = node.get("data", {})
                step_type = node.get("type") or node_data.get("step_type", "api_call")
                transferred = (
                    api_specs[sid]["transferred_variables"]
                    if sid in api_specs
                    else _collect_transferred_variables(node_data, context)
                )

                if isinstance(outcome, Exception):
                    execution.status = "failed"
                    status_code = getattr(outcome, "status_code", None)
                    response_body = getattr(outcome, "response_body", None)
                    classification = classify_error(
                        status_code=status_code,
                        response_body=response_body,
                        exception=outcome,
                        error_message=str(outcome),
                    )
                    step_results[sid] = {
                        "step_id": sid,
                        "label": node_data.get("label"),
                        "step_type": step_type,
                        "status": "failed",
                        "method": node_data.get("method"),
                        "endpoint": api_specs[sid]["full_url"] if sid in api_specs else node_data.get("path"),
                        "request": {
                            "method": api_specs[sid]["method"],
                            "url": api_specs[sid]["full_url"],
                            "headers": mask_headers_for_log(api_specs[sid]["headers"]),
                            "params": mask_params_for_log(api_specs[sid]["query_params"]),
                            "body": api_specs[sid]["resolved_body"],
                        } if sid in api_specs else None,
                        "transferred_variables": transferred,
                        "status_code": classification.get("status_code"),
                        "output": response_body,
                        "error": str(outcome),
                        "error_category": classification.get("category"),
                    }
                    execution.error_details = {
                        "step_id": sid,
                        "category": classification.get("category"),
                        "summary": classification.get("summary"),
                        "message": str(outcome),
                        "status_code": classification.get("status_code"),
                        "response_body": response_body,
                    }
                    self._log(
                        execution,
                        sid,
                        f"Step execution failed ({classification.get('category')}): {str(outcome)}",
                        "ERROR",
                    )
                    execution.step_results = dict(step_results)
                    flag_modified(execution, "step_results")
                    execution.completed_at = utc_now()
                    self.db.commit()
                    return execution

                if step_type == "api_call":
                    spec = api_specs[sid]
                    step_results[sid] = {
                        "step_id": sid,
                        "label": node_data.get("label"),
                        "step_type": "api_call",
                        "status": "completed",
                        "method": spec["method"],
                        "endpoint": spec["full_url"],
                        "request": {
                            "method": spec["method"],
                            "url": spec["full_url"],
                            "headers": mask_headers_for_log(spec["headers"]),
                            "params": mask_params_for_log(spec["query_params"]),
                            "body": spec["resolved_body"],
                        },
                        "transferred_variables": transferred,
                        "status_code": outcome["status_code"],
                        "output": outcome["data"],
                        "elapsed_ms": outcome["elapsed_ms"],
                        "attempts": outcome.get("attempts", 1),
                    }
                    self._log(
                        execution,
                        sid,
                        f"API call completed with status {outcome['status_code']} ({outcome['elapsed_ms']}ms)",
                    )
                elif step_type == "transform":
                    step_results[sid] = {
                        "step_id": sid,
                        "label": node_data.get("label"),
                        "step_type": "transform",
                        "status": "completed",
                        "transferred_variables": transferred,
                        "transformation_result": outcome,
                        "output": outcome,
                    }
                    self._log(execution, sid, f"Transform completed with result: {outcome}")
                elif step_type == "condition":
                    step_results[sid] = {
                        "step_id": sid,
                        "label": node_data.get("label"),
                        "step_type": "condition",
                        "status": "completed",
                        "transferred_variables": transferred,
                        "condition_result": outcome["result"],
                        "output": outcome,
                    }
                    self._log(execution, sid, f"Condition evaluated to: {outcome['result']}")
                else:
                    step_results[sid] = {"step_id": sid, "status": "completed", "output": outcome}

            execution.step_results = dict(step_results)
            flag_modified(execution, "step_results")
            self.db.commit()

        # Compute final output from completed terminal nodes
        terminal_ids = [nid for nid in topo_order if graph.out_degree(nid) == 0]
        completed_terminals = [
            tid for tid in terminal_ids if step_results.get(tid, {}).get("status") == "completed"
        ]
        if len(completed_terminals) == 1:
            execution.final_output = step_results[completed_terminals[0]].get("output")
        elif len(completed_terminals) > 1:
            execution.final_output = {tid: step_results[tid].get("output") for tid in completed_terminals}
        else:
            # Fallback to last completed step if all terminals skipped
            completed_ordered = [
                sid for sid in reversed(topo_order) if step_results.get(sid, {}).get("status") == "completed"
            ]
            execution.final_output = step_results[completed_ordered[0]].get("output") if completed_ordered else None

        execution.status = "completed"
        execution.completed_at = utc_now()
        self._log(execution, None, "Workflow execution completed successfully.")
        self.db.commit()
        return execution
