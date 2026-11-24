"""
APIForge AI Pydantic Schemas
Defines request and response schemas.
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    status: str
    details: Optional[Dict[str, Any]] = None


class ModelInfo(BaseModel):
    name: str
    available: bool


class OllamaServiceStatus(BaseModel):
    status: str
    url: str
    connected: bool
    models: Dict[str, ModelInfo]
    available_models: list[str] = Field(default_factory=list)


class DatabaseServiceStatus(BaseModel):
    status: str
    dialect: str
    connected: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    services: Dict[str, Any]
