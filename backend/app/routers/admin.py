"""
APIForge AI Admin Router
Provides administrative system statistics, audit log inspection, and user management.
Protected by get_current_active_admin RBAC dependency.
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import get_db
from app.models import User, Workflow, WorkflowExecution, APIConnection, Endpoint, AuditLog
from app.security import get_current_active_admin
from app.schemas import UserResponse, AuditLogResponse

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/stats", summary="System-wide administration metrics")
def get_system_stats(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_active_admin),
) -> Dict[str, Any]:
    """Retrieve global system statistics (admin only)."""
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_workflows = db.query(func.count(Workflow.id)).scalar() or 0
    total_executions = db.query(func.count(WorkflowExecution.id)).scalar() or 0
    total_connections = db.query(func.count(APIConnection.id)).scalar() or 0
    total_endpoints = db.query(func.count(Endpoint.id)).scalar() or 0
    total_audit_logs = db.query(func.count(AuditLog.id)).scalar() or 0

    return {
        "total_users": total_users,
        "total_workflows": total_workflows,
        "total_executions": total_executions,
        "total_connections": total_connections,
        "total_endpoints": total_endpoints,
        "total_audit_logs": total_audit_logs,
        "admin_email": admin_user.email,
    }


@router.get("/audit-logs", response_model=List[AuditLogResponse], summary="List system audit logs")
def get_audit_logs(
    limit: int = 50,
    action: Optional[str] = None,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_active_admin),
):
    """Retrieve audit logs with optional action filtering (admin only)."""
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    return q.order_by(AuditLog.created_at.desc()).limit(limit).all()


@router.get("/users", response_model=List[UserResponse], summary="List all registered users")
def list_users(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_active_admin),
):
    """List all user accounts in the platform (admin only)."""
    return db.query(User).order_by(User.id.asc()).all()


@router.post("/users/{user_id}/toggle-active", response_model=UserResponse, summary="Toggle user active status")
def toggle_user_active(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_active_admin),
):
    """Activate or deactivate a user account (admin only)."""
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")
    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    return user
