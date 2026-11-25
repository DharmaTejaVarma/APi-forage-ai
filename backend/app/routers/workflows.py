"""
APIForge AI Workflows Router
Endpoints for AI workflow generation, visual editing, and DAG lifecycle management.
Enforces user-level data isolation.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import get_db
from app.models import User, Workflow, AuditLog
from app.schemas import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
)
from app.security import get_current_user
from app.services.semantic_planner import generate_workflow_fast_semantic
from app.services.workflow_generator import (
    generate_workflow_from_prompt,
    validate_react_flow_workflow,
)
from app.agents.graph import multi_agent_orchestrator

router = APIRouter(prefix="/workflows", tags=["Workflows"])


class GenerateWorkflowRequest(BaseModel):
    prompt: str = Field(..., min_length=5, description="Natural language prompt describing the desired API workflow")
    engine: Optional[str] = Field(
        default=None,
        description="Optional generation engine: 'fast' (<1-2s semantic AI + nomic-embed-text), 'ollama_3b', or 'ollama' (qwen2.5:7b-instruct)",
    )


def _resolve_engine(requested: Optional[str], default: str = "ollama") -> str:
    eng = (requested or default).strip().lower()
    if eng not in {"fast", "ollama_3b", "ollama"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported generation engine '{eng}'. Choose 'fast', 'ollama_3b', or 'ollama'.",
        )
    return eng


@router.post(
    "/generate-multi-agent",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate workflow using LangGraph multi-agent orchestration",
)
async def generate_workflow_multi_agent(
    req: GenerateWorkflowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run multi-agent workflow generation (Intent Detection, Discovery, Schema, Planning, Mapping, DAG Validation)
    using the requested local AI engine (`fast`, `ollama_3b`, or `ollama`).
    """
    engine = _resolve_engine(req.engine, default="ollama")
    try:
        result = await multi_agent_orchestrator.run(
            prompt=req.prompt,
            db=db,
            user_id=current_user.id,
            engine=engine,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Multi-agent generation failed: {str(e)}",
        )

    base_dag = result.get("dag_structure") or {}
    merged_dag = {
        **base_dag,
        "engine": engine,
        "agent_trace": result.get("agent_trace", []),
        "intent": result.get("intent"),
    }
    workflow = Workflow(
        user_id=current_user.id,
        title=result.get("title") or "Multi-Agent Generated Workflow",
        description=result.get("description") or f"Generated via multi-agent orchestration from: {req.prompt}",
        raw_prompt=req.prompt,
        nodes=result.get("nodes") or [],
        edges=result.get("edges") or [],
        dag_structure=merged_dag,
        status="draft",
        is_shared=False,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


@router.post(
    "/generate-fast",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Fast semantic AI workflow generation (1-2s)",
)
async def generate_workflow_fast(
    req: GenerateWorkflowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate validated workflow DAG in ~1-2s using local Ollama `nomic-embed-text`
    semantic endpoint discovery and schema-driven DAG synthesis.
    """
    engine = _resolve_engine(req.engine, default="fast")
    try:
        if engine == "fast":
            plan, nodes, edges, dag_structure = await generate_workflow_fast_semantic(
                db=db,
                user_id=current_user.id,
                prompt=req.prompt,
            )
        else:
            model_name = get_settings().FALLBACK_CHAT_MODEL if engine == "ollama_3b" else None
            plan, nodes, edges, dag_structure = await generate_workflow_from_prompt(
                db=db,
                user_id=current_user.id,
                prompt=req.prompt,
                model=model_name,
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
        dag_structure={**dag_structure, "engine": engine},
        status="draft",
        is_shared=False,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


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
    Convert a natural-language prompt into an executable workflow DAG using local AI:
    1. Discovers relevant endpoints via semantic search.
    2. Generates structured JSON plan.
    3. Validates DAG acyclicity and enforces approval requirements.
    4. Converts plan into React Flow nodes and edges.
    5. Persists workflow in database.
    """
    engine = _resolve_engine(req.engine, default="ollama")
    try:
        if engine == "fast":
            plan, nodes, edges, dag_structure = await generate_workflow_fast_semantic(
                db=db,
                user_id=current_user.id,
                prompt=req.prompt,
            )
        else:
            model_name = get_settings().FALLBACK_CHAT_MODEL if engine == "ollama_3b" else None
            plan, nodes, edges, dag_structure = await generate_workflow_from_prompt(
                db=db,
                user_id=current_user.id,
                prompt=req.prompt,
                model=model_name,
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
        dag_structure={**dag_structure, "engine": engine},
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


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create and validate a visual workflow",
)
def create_workflow(
    wf_in: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a custom or edited DAG workflow with static validation and Rule 8 enforcement."""
    dag_struct = wf_in.dag_structure
    if wf_in.nodes:
        try:
            validated_dag = validate_react_flow_workflow(
                nodes=wf_in.nodes,
                edges=wf_in.edges or [],
                db=db,
                user_id=current_user.id,
                strict_endpoints=False,
            )
            if dag_struct is None:
                dag_struct = validated_dag
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Workflow validation failed: {str(e)}",
            )

    workflow = Workflow(
        user_id=current_user.id,
        title=wf_in.title,
        description=wf_in.description,
        raw_prompt=wf_in.raw_prompt,
        nodes=wf_in.nodes,
        edges=wf_in.edges,
        dag_structure=dag_struct,
        status=wf_in.status or "draft",
        is_shared=wf_in.is_shared,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


@router.post(
    "/validate",
    summary="Validate workflow nodes and edges without persisting",
)
def validate_workflow_endpoint(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run static NetworkX DAG, reference, transform, and Rule 8 validation."""
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    strict = bool(payload.get("strict_endpoints", False))
    try:
        dag_struct = validate_react_flow_workflow(
            nodes=nodes,
            edges=edges,
            db=db,
            user_id=current_user.id,
            strict_endpoints=strict,
        )
        return {"valid": True, "dag_structure": dag_struct, "nodes": nodes}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Workflow validation failed: {str(e)}",
        )


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
    """Update workflow graph nodes, edges, or status with static DAG & Rule 8 validation."""
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

    next_nodes = wf_update.nodes if wf_update.nodes is not None else workflow.nodes
    next_edges = wf_update.edges if wf_update.edges is not None else workflow.edges
    if next_nodes:
        try:
            validated_dag = validate_react_flow_workflow(
                nodes=next_nodes,
                edges=next_edges or [],
                db=db,
                user_id=current_user.id,
                strict_endpoints=False,
            )
            if wf_update.dag_structure is None:
                workflow.dag_structure = validated_dag
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Workflow validation failed: {str(e)}",
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
