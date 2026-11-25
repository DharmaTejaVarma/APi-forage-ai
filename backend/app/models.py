"""
APIForge AI SQLAlchemy Models
Defines all entities: Users, API Connections, Endpoints, Workflows, Executions, and Audit Logs.
Uses SQLAlchemy 2.0 mapped column syntax with SQLite WAL mode and CASCADE constraints.
"""
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy import (
    String,
    Integer,
    Boolean,
    Text,
    JSON,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class User(Base):
    """User account entity with role-based access control."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="user", nullable=False)  # "admin", "user"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships with CASCADE deletion
    connections: Mapped[List["APIConnection"]] = relationship(
        "APIConnection", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    workflows: Mapped[List["Workflow"]] = relationship(
        "Workflow", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    executions: Mapped[List["WorkflowExecution"]] = relationship(
        "WorkflowExecution", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"


class APIConnection(Base):
    """External API connection entity with encrypted credentials."""
    __tablename__ = "api_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(50), default="none", nullable=False)  # "none", "api_key", "bearer", "basic", "oauth2"
    encrypted_credentials: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Fernet encrypted token
    default_headers: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="connections")
    endpoints: Mapped[List["Endpoint"]] = relationship(
        "Endpoint", back_populates="connection", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<APIConnection id={self.id} name={self.name} base_url={self.base_url}>"


class Endpoint(Base):
    """Imported or discovered API endpoint with schemas and embeddings."""
    __tablename__ = "endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("api_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # GET, POST, PUT, DELETE, PATCH
    summary: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    operation_id: Mapped[Optional[str]] = mapped_column(String(150), nullable=True, index=True)
    parameters: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True, default=list)
    request_body_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    response_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    security: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSON, nullable=True)  # Vector from nomic-embed-text
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    connection: Mapped["APIConnection"] = relationship("APIConnection", back_populates="endpoints")

    __table_args__ = (
        Index("ix_endpoints_connection_method_path", "connection_id", "method", "path"),
    )

    @property
    def has_embedding(self) -> bool:
        return bool(self.embedding)

    def __repr__(self) -> str:
        return f"<Endpoint id={self.id} method={self.method} path={self.path}>"


class Workflow(Base):
    """Visual DAG workflow configuration generated by AI or edited by user."""
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Original user prompt
    nodes: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)  # React Flow nodes
    edges: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)  # React Flow edges
    dag_structure: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)  # Graph topology
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)  # "draft", "active", "archived"
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="workflows")
    executions: Mapped[List["WorkflowExecution"]] = relationship(
        "WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Workflow id={self.id} title={self.title} status={self.status}>"


class WorkflowExecution(Base):
    """Execution trace of a workflow run, with step outputs and approval status."""
    __tablename__ = "workflow_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False
    )  # "pending", "running", "waiting_approval", "completed", "failed", "cancelled"
    step_results: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=dict)
    execution_logs: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True, default=list)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pending_approval_step: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    approved_steps: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True, default=list)
    pending_approval_details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    approval_status: Mapped[str] = mapped_column(
        String(50), default="not_required", nullable=False
    )  # "not_required", "pending", "approved", "rejected"
    final_output: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    error_details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="executions")
    user: Mapped["User"] = relationship("User", back_populates="executions")

    def __repr__(self) -> str:
        return f"<WorkflowExecution id={self.id} workflow_id={self.workflow_id} status={self.status}>"


class AuditLog(Base):
    """Audit trail logging system actions and security events."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action} resource_type={self.resource_type}>"
