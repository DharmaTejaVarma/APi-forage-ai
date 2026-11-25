"""
APIForge AI Workflow Executions Router
Handles DAG workflow execution runs (sync or FastAPI BackgroundTasks),
history listing, status inspection, telemetry logs, per-step Rule 8 human approvals,
and Rule 9 AI error diagnosis & candidate fix application.
"""
import copy
from typing import List, Optional
import networkx as nx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import get_db, SessionLocal
from app.models import User, Workflow, WorkflowExecution, Endpoint, AuditLog, utc_now
from app.schemas import WorkflowExecutionResponse, ErrorDiagnosisResponse, ApplyFixRequest
from app.security import get_current_user
from app.services.executor import DAGExecutor
from app.services.error_agent import diagnose_step_failure

router = APIRouter(tags=["Executions"])


async def _run_execution_background(execution_id: int, resume: bool = False) -> None:
    """FastAPI background task runner with isolated DB session."""
    with SessionLocal() as bg_db:
        executor = DAGExecutor(bg_db, execution_id)
        await executor.run(resume_from_approval=resume)


@router.get(
    "/executions",
    response_model=List[WorkflowExecutionResponse],
    summary="List all executions for current user",
)
def list_all_executions(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve complete execution history belonging to the authenticated user."""
    query = db.query(WorkflowExecution).filter(WorkflowExecution.user_id == current_user.id)
    if status_filter:
        query = query.filter(WorkflowExecution.status == status_filter)
    return query.order_by(WorkflowExecution.created_at.desc()).offset(offset).limit(limit).all()


@router.post(
    "/workflows/{workflow_id}/execute",
    response_model=WorkflowExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start workflow execution",
)
async def execute_workflow(
    workflow_id: int,
    background_tasks: BackgroundTasks,
    background: bool = Query(False, description="Run asynchronously in background task for live polling"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Launch execution of a workflow DAG:
    - Runs steps in topological order.
    - If a step requires approval (Rule 8), pauses with status 'waiting_approval'.
    - Supports synchronous run (default) or FastAPI BackgroundTasks async run.
    """
    workflow = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.user_id == current_user.id)
        .first()
    )
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    execution = WorkflowExecution(
        workflow_id=workflow.id,
        user_id=current_user.id,
        status="pending",
        step_results={},
        execution_logs=[],
        approved_steps=[],
        requires_approval=False,
        approval_status="not_required",
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="workflow_execution_started",
        resource_type="workflow_execution",
        resource_id=str(execution.id),
        details={"workflow_id": workflow_id, "background": background},
    )
    db.add(audit)
    db.commit()

    if background:
        background_tasks.add_task(_run_execution_background, execution.id, False)
        return execution

    executor = DAGExecutor(db, execution.id)
    execution = await executor.run()
    return execution


@router.get(
    "/executions/{execution_id}",
    response_model=WorkflowExecutionResponse,
    summary="Get execution status, logs, and step outputs",
)
def get_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve full execution state, step results, and approval details."""
    execution = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.id == execution_id, WorkflowExecution.user_id == current_user.id)
        .first()
    )
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )
    return execution


@router.post(
    "/executions/{execution_id}/approve",
    response_model=WorkflowExecutionResponse,
    summary="Approve pending step and resume DAG execution",
)
async def approve_execution_step(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Approve the specific paused step (POST, PUT, PATCH, DELETE) and resume DAG execution.
    Subsequent mutating steps will pause independently for explicit approval.
    """
    execution = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.id == execution_id, WorkflowExecution.user_id == current_user.id)
        .first()
    )
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    if execution.status != "waiting_approval":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Execution is in '{execution.status}' state, not waiting for approval",
        )

    step_approved = execution.pending_approval_step
    approved_list = list(execution.approved_steps or [])
    if step_approved and step_approved not in approved_list:
        approved_list.append(step_approved)
    execution.approved_steps = approved_list
    flag_modified(execution, "approved_steps")
    execution.approval_status = "approved"
    db.commit()

    # Resume DAG execution
    executor = DAGExecutor(db, execution.id)
    execution = await executor.run(resume_from_approval=True)

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="step_approved",
        resource_type="workflow_execution",
        resource_id=str(execution.id),
        details={"step_id": step_approved, "final_status": execution.status},
    )
    db.add(audit)
    db.commit()

    return execution


@router.post(
    "/executions/{execution_id}/reject",
    response_model=WorkflowExecutionResponse,
    summary="Reject pending step and cancel workflow execution",
)
def reject_execution_step(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Reject paused step and cancel workflow run.
    """
    execution = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.id == execution_id, WorkflowExecution.user_id == current_user.id)
        .first()
    )
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    if execution.status != "waiting_approval":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Execution is in '{execution.status}' state, not waiting for approval",
        )

    execution.status = "cancelled"
    execution.approval_status = "rejected"
    execution.completed_at = utc_now()
    db.commit()

    audit = AuditLog(
        user_id=current_user.id,
        action="step_rejected",
        resource_type="workflow_execution",
        resource_id=str(execution.id),
        details={"step_id": execution.pending_approval_step},
    )
    db.add(audit)
    db.commit()

    return execution


@router.get(
    "/workflows/{workflow_id}/executions",
    response_model=List[WorkflowExecutionResponse],
    summary="List all executions for a specific workflow",
)
def list_workflow_executions(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve execution history for a workflow."""
    executions = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.workflow_id == workflow_id, WorkflowExecution.user_id == current_user.id)
        .order_by(WorkflowExecution.created_at.desc())
        .all()
    )
    return executions


@router.post(
    "/executions/{execution_id}/diagnose",
    response_model=ErrorDiagnosisResponse,
    summary="Diagnose step failure and propose candidate fixes (Rule 9)",
)
async def diagnose_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Invoke AI error recovery agent (qwen2.5:7b-instruct) on a failed step.
    NON-NEGOTIABLE RULE 9: Fixes are candidate proposals only.
    """
    execution = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.id == execution_id, WorkflowExecution.user_id == current_user.id)
        .first()
    )
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    if execution.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Execution is not in 'failed' status (current status: {execution.status})",
        )

    error_details = execution.error_details or {}
    failing_step_id = error_details.get("step_id")
    workflow = db.query(Workflow).filter_by(id=execution.workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    nodes = workflow.nodes or []
    failing_node = next((n for n in nodes if n.get("id") == failing_step_id), None)
    if not failing_node:
        failing_node = {"id": failing_step_id or "unknown", "data": {}}

    endpoint_schema = None
    ep_id = failing_node.get("data", {}).get("endpoint_id")
    if ep_id:
        ep = db.query(Endpoint).filter_by(id=ep_id).first()
        if ep:
            endpoint_schema = ep.response_schema

    diagnosis = await diagnose_step_failure(
        step_id=failing_step_id or "step_failed",
        node=failing_node,
        error_details=error_details,
        execution_context=execution.step_results or {},
        endpoint_schema=endpoint_schema,
    )

    updated_details = dict(error_details)
    updated_details["ai_diagnosis"] = diagnosis.model_dump()
    execution.error_details = updated_details
    flag_modified(execution, "error_details")
    db.commit()

    return diagnosis


@router.post(
    "/executions/{execution_id}/apply-fix",
    response_model=WorkflowExecutionResponse,
    summary="Apply user-approved candidate fix to workflow and resume execution",
)
async def apply_fix_and_resume(
    execution_id: int,
    payload: ApplyFixRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Apply a user-confirmed candidate fix to the workflow and optionally resume the DAG.
    Clears stale results for the modified node and its descendants cleanly.
    NON-NEGOTIABLE RULE 9: Fixes require explicit user confirmation.
    """
    execution = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.id == execution_id, WorkflowExecution.user_id == current_user.id)
        .first()
    )
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    workflow = db.query(Workflow).filter_by(id=execution.workflow_id, user_id=current_user.id).first()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    nodes = copy.deepcopy(workflow.nodes or [])
    updated = False
    for node in nodes:
        if node.get("id") == payload.target_node_id:
            node_data = node.setdefault("data", {})
            for k, v in payload.patch.items():
                if isinstance(v, dict) and isinstance(node_data.get(k), dict):
                    node_data[k].update(v)
                else:
                    node_data[k] = v
            updated = True
            break

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{payload.target_node_id}' not found in workflow",
        )

    workflow.nodes = nodes
    flag_modified(workflow, "nodes")
    db.commit()

    audit = AuditLog(
        user_id=current_user.id,
        action="ai_fix_applied",
        resource_type="workflow",
        resource_id=str(workflow.id),
        details={"execution_id": execution_id, "node_id": payload.target_node_id, "patch": payload.patch},
    )
    db.add(audit)
    db.commit()

    if payload.resume:
        # Clear failed node + all downstream descendants from step_results before resuming
        g = nx.DiGraph()
        for n in workflow.nodes or []:
            g.add_node(n["id"])
        for e in workflow.edges or []:
            g.add_edge(e["source"], e["target"])

        steps_to_reset = {payload.target_node_id}
        if payload.target_node_id in g:
            steps_to_reset |= nx.descendants(g, payload.target_node_id)

        cleaned_results = {
            k: v for k, v in (execution.step_results or {}).items()
            if k not in steps_to_reset and isinstance(v, dict) and v.get("status") == "completed"
        }
        execution.step_results = cleaned_results
        flag_modified(execution, "step_results")
        execution.status = "running"
        execution.error_details = None
        db.commit()

        executor = DAGExecutor(db, execution.id)
        execution = await executor.run(resume_from_approval=True)

    return execution
