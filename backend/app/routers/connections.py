"""
APIForge AI API Connections Router
Handles connection CRUD, credential encryption with Fernet, and OpenAPI specification import.
Enforces user-level data isolation.
"""
import json
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, APIConnection, Endpoint, AuditLog
from app.schemas import (
    APIConnectionCreate,
    APIConnectionUpdate,
    APIConnectionResponse,
    EndpointResponse,
)
from app.security import (
    get_current_user,
    encrypt_secret,
    decrypt_secret,
    mask_secret,
)
from app.services.openapi_parser import parse_openapi_spec
from app.services.embeddings import batch_embed_endpoints

router = APIRouter(prefix="/connections", tags=["API Connections"])


@router.post(
    "/{connection_id}/embed-all",
    summary="Batch generate embeddings for all connection endpoints",
)
async def embed_all_connection_endpoints(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate dense embeddings for all endpoints belonging to this connection."""
    conn = (
        db.query(APIConnection)
        .filter(APIConnection.id == connection_id, APIConnection.user_id == current_user.id)
        .first()
    )
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection {connection_id} not found",
        )

    count = await batch_embed_endpoints(db, connection_id)
    return {
        "message": f"Successfully generated embeddings for {count} endpoints",
        "count": count,
        "embedded_count": count,
    }


def _to_response_model(conn: APIConnection, endpoints_count: Optional[int] = None) -> APIConnectionResponse:
    """Helper to convert model to response schema with credentials masked."""
    has_creds = bool(conn.encrypted_credentials)
    return APIConnectionResponse(
        id=conn.id,
        user_id=conn.user_id,
        name=conn.name,
        description=conn.description,
        base_url=conn.base_url,
        auth_type=conn.auth_type,
        default_headers=conn.default_headers or {},
        is_active=conn.is_active,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
        has_credentials=has_creds,
        endpoints_count=endpoints_count,
    )


@router.post(
    "",
    response_model=APIConnectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new API connection",
)
def create_connection(
    conn_in: APIConnectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new API connection with securely encrypted credentials."""
    encrypted_creds = None
    if conn_in.credentials:
        creds_json = json.dumps(conn_in.credentials)
        encrypted_creds = encrypt_secret(creds_json)

    connection = APIConnection(
        user_id=current_user.id,
        name=conn_in.name,
        description=conn_in.description,
        base_url=conn_in.base_url.rstrip("/"),
        auth_type=conn_in.auth_type,
        encrypted_credentials=encrypted_creds,
        default_headers=conn_in.default_headers or {},
        is_active=conn_in.is_active,
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="connection_created",
        resource_type="connection",
        resource_id=str(connection.id),
        details={"name": connection.name, "base_url": connection.base_url},
    )
    db.add(audit)
    db.commit()

    return _to_response_model(connection)


@router.get(
    "",
    response_model=List[APIConnectionResponse],
    summary="List all API connections for current user",
)
def list_connections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve all API connections belonging to the authenticated user."""
    from sqlalchemy import func
    connections = (
        db.query(APIConnection)
        .filter(APIConnection.user_id == current_user.id)
        .order_by(APIConnection.created_at.desc())
        .all()
    )
    ep_counts = dict(
        db.query(Endpoint.connection_id, func.count(Endpoint.id))
        .join(APIConnection, Endpoint.connection_id == APIConnection.id)
        .filter(APIConnection.user_id == current_user.id)
        .group_by(Endpoint.connection_id)
        .all()
    )
    return [_to_response_model(c, ep_counts.get(c.id, 0)) for c in connections]


@router.get(
    "/{connection_id}",
    response_model=APIConnectionResponse,
    summary="Get API connection details by ID",
)
def get_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a single API connection by ID enforcing user ownership."""
    connection = (
        db.query(APIConnection)
        .filter(APIConnection.id == connection_id, APIConnection.user_id == current_user.id)
        .first()
    )
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection {connection_id} not found",
        )
    return _to_response_model(connection)


@router.put(
    "/{connection_id}",
    response_model=APIConnectionResponse,
    summary="Update API connection",
)
def update_connection(
    connection_id: int,
    conn_update: APIConnectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update connection fields and re-encrypt credentials if modified."""
    connection = (
        db.query(APIConnection)
        .filter(APIConnection.id == connection_id, APIConnection.user_id == current_user.id)
        .first()
    )
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection {connection_id} not found",
        )

    if conn_update.name is not None:
        connection.name = conn_update.name
    if conn_update.description is not None:
        connection.description = conn_update.description
    if conn_update.base_url is not None:
        connection.base_url = conn_update.base_url.rstrip("/")
    if conn_update.auth_type is not None:
        connection.auth_type = conn_update.auth_type
    if conn_update.default_headers is not None:
        connection.default_headers = conn_update.default_headers
    if conn_update.is_active is not None:
        connection.is_active = conn_update.is_active
    if conn_update.credentials is not None:
        creds_json = json.dumps(conn_update.credentials)
        connection.encrypted_credentials = encrypt_secret(creds_json)

    db.commit()
    db.refresh(connection)
    return _to_response_model(connection)


@router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete API connection",
)
def delete_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an API connection and cascade-delete all its associated endpoints."""
    connection = (
        db.query(APIConnection)
        .filter(APIConnection.id == connection_id, APIConnection.user_id == current_user.id)
        .first()
    )
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection {connection_id} not found",
        )

    db.delete(connection)
    db.commit()
    return None


@router.post(
    "/{connection_id}/import-openapi",
    response_model=List[EndpointResponse],
    summary="Import OpenAPI specification into connection",
)
def import_openapi(
    connection_id: int,
    spec: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Parse an OpenAPI 3.0 / Swagger JSON specification, extract all operations,
    and persist them as Endpoints associated with this connection.
    """
    connection = (
        db.query(APIConnection)
        .filter(APIConnection.id == connection_id, APIConnection.user_id == current_user.id)
        .first()
    )
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection {connection_id} not found",
        )

    try:
        parsed = parse_openapi_spec(spec)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse OpenAPI specification: {str(e)}",
        )

    # Optional: update base_url if connection base_url is placeholder or empty
    if parsed.base_url and (not connection.base_url or connection.base_url in ["http://localhost", ""]):
        connection.base_url = parsed.base_url

    created_endpoints: List[Endpoint] = []
    for parsed_ep in parsed.endpoints:
        # Check if endpoint already exists for this connection + method + path
        existing_ep = (
            db.query(Endpoint)
            .filter(
                Endpoint.connection_id == connection.id,
                Endpoint.method == parsed_ep.method,
                Endpoint.path == parsed_ep.path,
            )
            .first()
        )

        if existing_ep:
            existing_ep.summary = parsed_ep.summary
            existing_ep.description = parsed_ep.description
            existing_ep.operation_id = parsed_ep.operation_id
            existing_ep.parameters = parsed_ep.parameters
            existing_ep.request_body_schema = parsed_ep.request_body_schema
            existing_ep.response_schema = parsed_ep.response_schema
            existing_ep.security = parsed_ep.security
            created_endpoints.append(existing_ep)
        else:
            ep = Endpoint(
                connection_id=connection.id,
                path=parsed_ep.path,
                method=parsed_ep.method,
                summary=parsed_ep.summary,
                description=parsed_ep.description,
                operation_id=parsed_ep.operation_id,
                parameters=parsed_ep.parameters,
                request_body_schema=parsed_ep.request_body_schema,
                response_schema=parsed_ep.response_schema,
                security=parsed_ep.security,
            )
            db.add(ep)
            created_endpoints.append(ep)

    db.commit()
    for ep in created_endpoints:
        db.refresh(ep)

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="openapi_imported",
        resource_type="connection",
        resource_id=str(connection.id),
        details={"endpoints_count": len(created_endpoints), "spec_title": parsed.title},
    )
    db.add(audit)
    db.commit()

    return created_endpoints
