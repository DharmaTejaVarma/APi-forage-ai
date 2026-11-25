"""
APIForge AI DAG Execution Engine
Executes workflows in topological DAG order using NetworkX.
Features:
- Safe data passing with template substitution
- SimpleEval transformations
- Rule 8 Approval System: pauses before POST/PUT/DELETE for human approval
- Secure outgoing HTTP requests via SecureHttpClient
- Step logs and execution telemetry
"""
import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import networkx as nx
from sqlalchemy.orm import Session

from app.models import Workflow, WorkflowExecution, APIConnection, Endpoint, AuditLog
from app.services.http_client import secure_http_client, SSRFProtectionError
from app.services.transforms import resolve_templates, evaluate_transformation
from app.security import decrypt_secret, mask_secret
from app.services.validator import classify_error, validate_api_response, ErrorCategory


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowExecutionError(Exception):
    def __init__(self, step_id: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.step_id = step_id
        self.details = details or {}


class DAGExecutor:
    """Execution engine for executing workflow DAGs with approval gates."""

    def __init__(self, db: Session, execution_id: int):
        self.db = db
        self.execution_id = execution_id

    def _log(self, execution: WorkflowExecution, step_id: Optional[str], message: str, level: str = "INFO"):
        """Append log event to execution record."""
        logs = list(execution.execution_logs or [])
        entry = {
            "timestamp": utc_now().isoformat(),
            "step_id": step_id,
            "level": level,
            "message": message,
        }
        logs.append(entry)
        execution.execution_logs = logs

    async def run(self, resume_from_approval: bool = False) -> WorkflowExecution:
        """
        Execute DAG workflow.
        If a step requires approval and has not been approved, pauses execution.
        """
        execution = self.db.query(WorkflowExecution).filter_by(id=self.execution_id).first()
        if not execution:
            raise ValueError(f"Execution {self.execution_id} not found")

        workflow = self.db.query(Workflow).filter_by(id=execution.workflow_id).first()
        if not workflow:
            raise ValueError(f"Workflow {execution.workflow_id} not found")

        # Initialize or restore context
        step_results = dict(execution.step_results or {})
        context: Dict[str, Any] = {k: v for k, v in step_results.items()}

        # Build execution DAG
        nodes = workflow.nodes or []
        edges = workflow.edges or []
        node_map = {n["id"]: n for n in nodes}

        graph = nx.DiGraph()
        for n in nodes:
            graph.add_node(n["id"])
        for e in edges:
            graph.add_edge(e["source"], e["target"])

        # Topological execution order
        try:
            execution_order = list(nx.topological_sort(graph))
        except nx.NetworkXUnfeasible:
            execution.status = "failed"
            execution.error_details = {"message": "Workflow contains cyclic dependencies."}
            self.db.commit()
            return execution

        if not resume_from_approval:
            execution.status = "running"
            execution.started_at = utc_now()
            self._log(execution, None, f"Started execution of workflow '{workflow.title}'")
            self.db.commit()

        # Execute each step
        for step_id in execution_order:
            # If step is already completed from a previous paused run, skip it
            if step_id in step_results and step_results[step_id].get("status") == "completed":
                continue

            node = node_map.get(step_id)
            if not node:
                continue

            node_data = node.get("data", {})
            step_type = node.get("type") or node_data.get("step_type", "api_call")
            requires_approval = node_data.get("requires_approval", False)

            # Check Rule 8 Approval Gate
            if requires_approval and execution.approval_status != "approved":
                execution.status = "waiting_approval"
                execution.requires_approval = True
                execution.pending_approval_step = step_id
                execution.approval_status = "pending"
                self._log(
                    execution,
                    step_id,
                    f"Execution paused: Step '{step_id}' ({node_data.get('label')}) requires user approval.",
                    "WARNING",
                )
                self.db.commit()
                return execution

            # If resuming from approved state on this step, clear pending step while keeping approved status
            if execution.approval_status == "approved" and execution.pending_approval_step == step_id:
                execution.pending_approval_step = None

            self._log(execution, step_id, f"Executing step '{step_id}': {node_data.get('label')}")

            try:
                if step_type == "transform":
                    result = await self._execute_transform(node_data, context)
                    step_results[step_id] = {
                        "status": "completed",
                        "output": result,
                    }
                    context[step_id] = step_results[step_id]
                    self._log(execution, step_id, f"Transform completed with result: {result}")

                elif step_type == "api_call":
                    api_result = await self._execute_api_call(node_data, context, workflow.user_id)
                    step_results[step_id] = {
                        "status": "completed",
                        "status_code": api_result["status_code"],
                        "output": api_result["data"],
                        "elapsed_ms": api_result["elapsed_ms"],
                    }
                    context[step_id] = step_results[step_id]
                    self._log(
                        execution,
                        step_id,
                        f"API call completed with status {api_result['status_code']} ({api_result['elapsed_ms']}ms)",
                    )
                else:
                    step_results[step_id] = {"status": "completed", "output": None}
                    context[step_id] = step_results[step_id]

            except Exception as e:
                execution.status = "failed"
                status_code = getattr(e, "status_code", None)
                response_body = getattr(e, "response_body", None)
                classification = classify_error(
                    status_code=status_code,
                    response_body=response_body,
                    exception=e,
                    error_message=str(e),
                )
                execution.error_details = {
                    "step_id": step_id,
                    "category": classification.get("category"),
                    "summary": classification.get("summary"),
                    "message": str(e),
                    "status_code": classification.get("status_code"),
                    "response_body": response_body,
                }
                self._log(execution, step_id, f"Step execution failed ({classification.get('category')}): {str(e)}", "ERROR")
                execution.step_results = step_results
                execution.completed_at = utc_now()
                self.db.commit()
                return execution

            execution.step_results = step_results
            self.db.commit()

        # All steps completed successfully
        execution.status = "completed"
        execution.completed_at = utc_now()
        self._log(execution, None, "Workflow execution completed successfully.")
        self.db.commit()
        return execution

    async def _execute_transform(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """Execute safe formula calculation without eval()."""
        trans = node_data.get("transformation") or {}
        return evaluate_transformation(trans, context)

    async def _execute_api_call(
        self,
        node_data: Dict[str, Any],
        context: Dict[str, Any],
        user_id: int,
    ) -> Dict[str, Any]:
        """Resolve endpoint, templates, credentials, and execute HTTP request."""
        conn_id = node_data.get("connection_id")
        method = (node_data.get("method") or "GET").upper()
        raw_path = node_data.get("path") or ""

        # Fetch connection
        conn = None
        if conn_id:
            conn = self.db.query(APIConnection).filter_by(id=conn_id, user_id=user_id).first()

        base_url = conn.base_url if conn else "http://127.0.0.1:8000/mock/api/v1"
        auth_type = conn.auth_type if conn else "none"

        # Decrypt credentials
        credentials = None
        if conn and conn.encrypted_credentials:
            try:
                decrypted = decrypt_secret(conn.encrypted_credentials)
                credentials = json.loads(decrypted)
            except Exception:
                pass

        # Resolve path parameters (e.g. /products/{id} or {{step_1.output.id}})
        resolved_path = resolve_templates(raw_path, context)
        raw_params = resolve_templates(node_data.get("parameters") or {}, context)

        # Substitute any {param} in path, keep remainder as query parameters
        query_params = {}
        for p_name, p_val in raw_params.items():
            token = f"{{{p_name}}}"
            if token in resolved_path:
                resolved_path = resolved_path.replace(token, str(p_val))
            else:
                query_params[p_name] = p_val

        clean_path = resolved_path.lstrip('/')
        base_clean = base_url.rstrip('/')
        if '/mock/api/v1' in base_clean and clean_path.startswith('mock/api/v1/'):
            clean_path = clean_path[len('mock/api/v1/'):]
        full_url = f"{base_clean}/{clean_path}"

        # Resolve request body
        raw_body = node_data.get("request_body")
        resolved_body = resolve_templates(raw_body, context) if raw_body else None

        # Headers
        headers = dict(conn.default_headers if conn and conn.default_headers else {})

        # Execute outgoing request via secure client
        resp = await secure_http_client.execute_request(
            method=method,
            url=full_url,
            headers=headers,
            params=query_params if query_params else None,
            json_data=resolved_body if method != "GET" else None,
            auth_type=auth_type,
            credentials=credentials,
        )

        if not resp["success"]:
            err = RuntimeError(
                f"API call to '{method} {full_url}' failed with status {resp['status_code']}: {resp['data']}"
            )
            setattr(err, "status_code", resp["status_code"])
            setattr(err, "response_body", resp["data"])
            raise err

        # Optional schema validation if configured on node or endpoint
        expected_schema = node_data.get("response_schema")
        if not expected_schema and node_data.get("endpoint_id"):
            ep = self.db.query(Endpoint).filter_by(id=node_data.get("endpoint_id")).first()
            if ep and ep.response_schema:
                expected_schema = ep.response_schema

        if expected_schema:
            val_res = validate_api_response(
                status_code=resp["status_code"],
                data=resp["data"],
                expected_schema=expected_schema,
            )
            if not val_res["valid"]:
                err = ValueError(val_res.get("reason") or val_res.get("summary"))
                setattr(err, "status_code", resp["status_code"])
                setattr(err, "response_body", resp["data"])
                raise err

        return resp
