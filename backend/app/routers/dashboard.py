"""
APIForge AI Dashboard & Metrics Router
Provides user-level summary statistics, execution metrics, and recent activity.
"""
from typing import Dict, Any, List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import get_db
from app.models import User, Workflow, WorkflowExecution, APIConnection, Endpoint
from app.security import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", summary="Get dashboard summary statistics")
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieve aggregate metrics for current user."""
    # Workflows count
    total_workflows = (
        db.query(func.count(Workflow.id))
        .filter(Workflow.user_id == current_user.id)
        .scalar() or 0
    )

    # Executions count & statuses
    total_executions = (
        db.query(func.count(WorkflowExecution.id))
        .filter(WorkflowExecution.user_id == current_user.id)
        .scalar() or 0
    )

    completed_executions = (
        db.query(func.count(WorkflowExecution.id))
        .filter(
            WorkflowExecution.user_id == current_user.id,
            WorkflowExecution.status == "completed",
        )
        .scalar() or 0
    )

    failed_executions = (
        db.query(func.count(WorkflowExecution.id))
        .filter(
            WorkflowExecution.user_id == current_user.id,
            WorkflowExecution.status == "failed",
        )
        .scalar() or 0
    )

    waiting_approval = (
        db.query(func.count(WorkflowExecution.id))
        .filter(
            WorkflowExecution.user_id == current_user.id,
            WorkflowExecution.status == "waiting_approval",
        )
        .scalar() or 0
    )

    success_rate = (
        round((completed_executions / total_executions) * 100, 1)
        if total_executions > 0 else 100.0
    )

    # Connections and endpoints
    connections = db.query(APIConnection).filter(APIConnection.user_id == current_user.id).all()
    conn_ids = [c.id for c in connections]
    total_connections = len(connections)

    total_endpoints = 0
    if conn_ids:
        total_endpoints = (
            db.query(func.count(Endpoint.id))
            .filter(Endpoint.connection_id.in_(conn_ids))
            .scalar() or 0
        )

    # Recent 5 executions
    recent_execs = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.user_id == current_user.id)
        .order_by(WorkflowExecution.created_at.desc())
        .limit(5)
        .all()
    )

    recent_list = []
    for ex in recent_execs:
        wf = db.query(Workflow).filter_by(id=ex.workflow_id).first()
        recent_list.append({
            "id": ex.id,
            "workflow_id": ex.workflow_id,
            "workflow_title": wf.title if wf else f"Workflow #{ex.workflow_id}",
            "status": ex.status,
            "requires_approval": ex.requires_approval,
            "approval_status": ex.approval_status,
            "created_at": ex.created_at.isoformat() if ex.created_at else None,
            "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
        })

    return {
        "total_workflows": total_workflows,
        "total_executions": total_executions,
        "completed_executions": completed_executions,
        "failed_executions": failed_executions,
        "waiting_approval": waiting_approval,
        "success_rate": success_rate,
        "total_connections": total_connections,
        "total_endpoints": total_endpoints,
        "recent_executions": recent_list,
    }
