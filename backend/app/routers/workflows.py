"""
APIForge AI Workflows Router
Endpoints for AI workflow generation, visual editing, and DAG lifecycle management.
Enforces user-level data isolation.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.db import get_db
from app.models import User, Workflow, AuditLog
from app.schemas import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
)
from app.security import get_current_user
from app.services.workflow_generator import generate_workflow_from_prompt

router = APIRouter(prefix="/workflows", tags=["Workflows"])


class GenerateWorkflowRequest(BaseModel):
    prompt: str = Field(..., min_length=5, description="Natural language prompt describing the desired API workflow")


@router.post(
    "/generate",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate workflow from natural language instruction",
)
async def generate_workflow(
    req: GenerateWorkflowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Convert a natural-language prompt into an executable workflow DAG using local Ollama AI:
    1. Discovers relevant endpoints via semantic search.
    2. Generates structured JSON plan.
    3. Validates DAG acyclicity and enforces approval requirements.
    4. Converts plan into React Flow nodes and edges.
    5. Persists workflow in database.
    """
    try:
        plan, nodes, edges, dag_structure = await generate_workflow_from_prompt(
            db=db,
            user_id=current_user.id,
            prompt=req.prompt,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Workflow generation failed: {str(e)}",
        )

    workflow = Workflow(
        user_id=current_user.id,
        title=plan.workflow_title,
        description=plan.workflow_description,
        raw_prompt=req.prompt,
        nodes=nodes,
        edges=edges,
        dag_structure=dag_structure,
        status="draft",
        is_shared=False,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="workflow_generated",
        resource_type="workflow",
        resource_id=str(workflow.id),
        details={"title": workflow.title, "steps_count": len(nodes)},
    )
    db.add(audit)
    db.commit()

    return workflow


@router.get(
    "",
    response_model=List[WorkflowResponse],
    summary="List all workflows for current user",
)
def list_workflows(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve all visual workflows created by the authenticated user."""
    query = db.query(Workflow).filter(Workflow.user_id == current_user.id)
    if status_filter:
        query = query.filter(Workflow.status == status_filter)
    return query.order_by(Workflow.updated_at.desc()).all()


@router.get(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    summary="Get workflow details and visual graph by ID",
)
def get_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a single visual workflow ensuring user ownership."""
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
    return workflow


@router.put(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    summary="Update visual workflow nodes, edges, or metadata",
)
def update_workflow(
    workflow_id: int,
    wf_update: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update workflow graph nodes, edges, or status."""
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

    if wf_update.title is not None:
        workflow.title = wf_update.title
    if wf_update.description is not None:
        workflow.description = wf_update.description
    if wf_update.nodes is not None:
        workflow.nodes = wf_update.nodes
    if wf_update.edges is not None:
        workflow.edges = wf_update.edges
    if wf_update.dag_structure is not None:
        workflow.dag_structure = wf_update.dag_structure
    if wf_update.status is not None:
        workflow.status = wf_update.status
    if wf_update.is_shared is not None:
        workflow.is_shared = wf_update.is_shared

    db.commit()
    db.refresh(workflow)
    return workflow


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a workflow",
)
def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a workflow and cascade delete all its execution records."""
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

    db.delete(workflow)
    db.commit()
    return None


@router.post(
    "/{workflow_id}/duplicate",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate an existing workflow",
)
def duplicate_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clone an existing workflow into a new draft."""
    original = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.user_id == current_user.id)
        .first()
    )
    if not original:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    cloned = Workflow(
        user_id=current_user.id,
        title=f"{original.title} (Copy)",
        description=original.description,
        raw_prompt=original.raw_prompt,
        nodes=original.nodes,
        edges=original.edges,
        dag_structure=original.dag_structure,
        status="draft",
        is_shared=False,
    )
    db.add(cloned)
    db.commit()
    db.refresh(cloned)
    return cloned
