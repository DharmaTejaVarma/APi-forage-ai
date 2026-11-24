"""
APIForge AI Endpoints Router
Query, inspect, and manage parsed API endpoints across connections.
Enforces user-level data isolation.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, APIConnection, Endpoint
from app.schemas import EndpointCreate, EndpointResponse, SemanticSearchResult
from app.security import get_current_user
from app.services.embeddings import embed_endpoint, semantic_search_endpoints

router = APIRouter(prefix="/endpoints", tags=["API Endpoints"])


@router.get(
    "/search/semantic",
    response_model=List[SemanticSearchResult],
    summary="Semantic search across user endpoints using natural language",
)
async def search_endpoints_semantically(
    q: str = Query(..., description="Natural language search query (e.g. 'find user orders')"),
    top_k: int = Query(5, ge=1, le=20, description="Max number of ranked endpoints to return"),
    connection_id: Optional[int] = Query(None, description="Optional connection filter"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Search and rank endpoints using nomic-embed-text vector embeddings and cosine similarity.
    Enforces user isolation.
    """
    results = await semantic_search_endpoints(
        db=db,
        user_id=current_user.id,
        query=q,
        top_k=top_k,
        connection_id=connection_id,
    )
    return results


@router.post(
    "/{endpoint_id}/embed",
    response_model=EndpointResponse,
    summary="Generate or refresh embedding for a single endpoint",
)
async def generate_endpoint_embedding(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate dense vector embedding using nomic-embed-text for this endpoint."""
    endpoint = (
        db.query(Endpoint)
        .join(APIConnection, Endpoint.connection_id == APIConnection.id)
        .filter(Endpoint.id == endpoint_id, APIConnection.user_id == current_user.id)
        .first()
    )
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Endpoint {endpoint_id} not found",
        )

    await embed_endpoint(db, endpoint)
    return endpoint


@router.get(
    "",
    response_model=List[EndpointResponse],
    summary="List all endpoints for current user",
)
def list_endpoints(
    connection_id: Optional[int] = Query(None, description="Filter by API connection ID"),
    method: Optional[str] = Query(None, description="Filter by HTTP method (e.g. GET, POST)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve endpoints belonging to connections owned by the authenticated user."""
    query = (
        db.query(Endpoint)
        .join(APIConnection, Endpoint.connection_id == APIConnection.id)
        .filter(APIConnection.user_id == current_user.id)
    )

    if connection_id is not None:
        query = query.filter(Endpoint.connection_id == connection_id)

    if method is not None:
        query = query.filter(Endpoint.method == method.upper())

    return query.order_by(Endpoint.path.asc(), Endpoint.method.asc()).all()


@router.get(
    "/{endpoint_id}",
    response_model=EndpointResponse,
    summary="Get endpoint details by ID",
)
def get_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve detailed specification and schemas for a specific endpoint."""
    endpoint = (
        db.query(Endpoint)
        .join(APIConnection, Endpoint.connection_id == APIConnection.id)
        .filter(Endpoint.id == endpoint_id, APIConnection.user_id == current_user.id)
        .first()
    )
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Endpoint {endpoint_id} not found",
        )
    return endpoint


@router.post(
    "",
    response_model=EndpointResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manually add an endpoint",
)
def create_endpoint(
    ep_in: EndpointCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a single endpoint to an owned connection."""
    conn = (
        db.query(APIConnection)
        .filter(APIConnection.id == ep_in.connection_id, APIConnection.user_id == current_user.id)
        .first()
    )
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection {ep_in.connection_id} not found",
        )

    endpoint = Endpoint(
        connection_id=ep_in.connection_id,
        path=ep_in.path,
        method=ep_in.method.upper(),
        summary=ep_in.summary,
        description=ep_in.description,
        operation_id=ep_in.operation_id,
        parameters=ep_in.parameters or [],
        request_body_schema=ep_in.request_body_schema,
        response_schema=ep_in.response_schema,
        embedding=ep_in.embedding,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return endpoint


@router.delete(
    "/{endpoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an endpoint",
)
def delete_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a single endpoint."""
    endpoint = (
        db.query(Endpoint)
        .join(APIConnection, Endpoint.connection_id == APIConnection.id)
        .filter(Endpoint.id == endpoint_id, APIConnection.user_id == current_user.id)
        .first()
    )
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Endpoint {endpoint_id} not found",
        )
    db.delete(endpoint)
    db.commit()
    return None
