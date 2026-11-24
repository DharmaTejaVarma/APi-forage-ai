"""
APIForge AI Pydantic Schemas
Defines request and response schemas for all entities with Pydantic v2 validation.
"""
from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, EmailStr, ConfigDict


# ============================================================================
# System & Health Schemas
# ============================================================================

class ServiceStatus(BaseModel):
    status: str
    details: Optional[Dict[str, Any]] = None


class ModelInfo(BaseModel):
    name: str
    available: bool
    fallback_available: Optional[bool] = None
    fallback_name: Optional[str] = None


class OllamaServiceStatus(BaseModel):
    status: str
    url: str
    connected: bool
    models: Dict[str, ModelInfo]
    available_models: List[str] = Field(default_factory=list)


class DatabaseServiceStatus(BaseModel):
    status: str
    dialect: str
    connected: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    services: Dict[str, Any]


# ============================================================================
# User Schemas
# ============================================================================

class UserBase(BaseModel):
    email: EmailStr
    role: str = "user"
    is_active: bool = True


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: str = "user"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ============================================================================
# API Connection Schemas
# ============================================================================

class APIConnectionBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    base_url: str = Field(..., max_length=500)
    auth_type: str = "none"  # "none", "api_key", "bearer", "basic", "oauth2"
    default_headers: Optional[Dict[str, Any]] = Field(default_factory=dict)
    is_active: bool = True


class APIConnectionCreate(APIConnectionBase):
    credentials: Optional[Dict[str, Any]] = None  # Raw credentials to be encrypted with Fernet


class APIConnectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    base_url: Optional[str] = None
    auth_type: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None
    default_headers: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class APIConnectionResponse(APIConnectionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    has_credentials: bool = False


# ============================================================================
# Endpoint Schemas
# ============================================================================

class EndpointBase(BaseModel):
    path: str
    method: str
    summary: Optional[str] = None
    description: Optional[str] = None
    operation_id: Optional[str] = None
    parameters: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    request_body_schema: Optional[Dict[str, Any]] = None
    response_schema: Optional[Dict[str, Any]] = None


class EndpointCreate(EndpointBase):
    connection_id: int
    embedding: Optional[List[float]] = None


class EndpointResponse(EndpointBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    connection_id: int
    created_at: datetime
    updated_at: datetime


# ============================================================================
# Workflow Schemas
# ============================================================================

class WorkflowBase(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    raw_prompt: Optional[str] = None
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    dag_structure: Optional[Dict[str, Any]] = None
    status: str = "draft"
    is_shared: bool = False


class WorkflowCreate(WorkflowBase):
    pass


class WorkflowUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    dag_structure: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    is_shared: Optional[bool] = None


class WorkflowResponse(WorkflowBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


# ============================================================================
# Workflow Execution Schemas
# ============================================================================

class WorkflowExecutionCreate(BaseModel):
    workflow_id: int


class WorkflowExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    user_id: int
    status: str
    step_results: Optional[Dict[str, Any]] = None
    execution_logs: Optional[List[Dict[str, Any]]] = None
    requires_approval: bool
    pending_approval_step: Optional[str] = None
    approval_status: str
    error_details: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


# ============================================================================
# Audit Log Schemas
# ============================================================================

class AuditLogCreate(BaseModel):
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime
