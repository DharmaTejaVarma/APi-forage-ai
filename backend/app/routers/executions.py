"""
APIForge AI Workflow Executions Router
Handles DAG workflow execution runs, status inspection, telemetry logs,
and human-in-the-loop approval actions (Approve / Reject).
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, Workflow, WorkflowExecution, AuditLog, utc_now
from app.schemas import WorkflowExecutionResponse
from app.security import get_current_user
from app.services.executor import DAGExecutor

router = APIRouter(tags=["Executions"])


@router.post(
    "/workflows/{workflow_id}/execute",
    response_model=WorkflowExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start workflow execution",
)
async def execute_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Launch execution of a workflow DAG:
    - Runs steps in topological order.
    - If a step requires approval (Rule 8), pauses with status 'waiting_approval'.
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
        requires_approval=False,
        approval_status="not_required",
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    # Execute DAG
    executor = DAGExecutor(db, execution.id)
    execution = await executor.run()

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="workflow_execution_started",
        resource_type="workflow_execution",
        resource_id=str(execution.id),
        details={"workflow_id": workflow_id, "status": execution.status},
    )
    db.add(audit)
    db.commit()

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
    Approve paused step (POST, PUT, DELETE) and resume DAG execution.
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

    # Audit log
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
