"""
APIForge AI Semantic Embeddings & Similarity Service
Generates dense vector embeddings using nomic-embed-text via local Ollama.
Computes cosine similarity with NumPy for semantic endpoint retrieval.
"""
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Endpoint, APIConnection
from app.services.ollama_client import ollama_client

settings = get_settings()


def build_endpoint_text(endpoint: Any) -> str:
    """
    Construct rich contextual string from endpoint metadata for vector embedding.
    Includes HTTP method, path, operation summary, description, and parameter signatures.
    """
    method = getattr(endpoint, "method", "")
    path = getattr(endpoint, "path", "")
    summary = getattr(endpoint, "summary", "") or ""
    description = getattr(endpoint, "description", "") or ""
    op_id = getattr(endpoint, "operation_id", "") or ""

    parts = [f"{method} {path}"]
    if summary:
        parts.append(f"Summary: {summary}")
    if description and description != summary:
        parts.append(f"Description: {description}")
    if op_id:
        parts.append(f"Operation ID: {op_id}")

    params = getattr(endpoint, "parameters", []) or []
    if params and isinstance(params, list):
        param_strs = []
        for p in params:
            if isinstance(p, dict):
                p_name = p.get("name", "")
                p_in = p.get("in", "")
                p_desc = p.get("description", "")
                param_strs.append(f"{p_name} ({p_in}): {p_desc}")
        if param_strs:
            parts.append(f"Parameters: {'; '.join(param_strs)}")

    req_body = getattr(endpoint, "request_body_schema", None)
    if req_body and isinstance(req_body, dict):
        props = req_body.get("properties", {})
        if props:
            parts.append(f"Request Fields: {', '.join(props.keys())}")

    return ". ".join(parts)


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """
    Compute cosine similarity between two float vectors using NumPy.
    Returns float score between -1.0 and 1.0.
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    similarity = float(np.dot(a, b) / (norm_a * norm_b))
    return float(np.clip(similarity, -1.0, 1.0))


async def generate_embedding(text: str) -> List[float]:
    """Generate dense vector embedding using nomic-embed-text via Ollama."""
    return await ollama_client.embeddings(text)


async def embed_endpoint(db: Session, endpoint: Endpoint) -> Endpoint:
    """Generate and store embedding for a single endpoint entity."""
    endpoint_text = build_endpoint_text(endpoint)
    vector = await generate_embedding(endpoint_text)
    endpoint.embedding = vector
    db.commit()
    db.refresh(endpoint)
    return endpoint


async def batch_embed_endpoints(db: Session, connection_id: int) -> int:
    """
    Generate embeddings for all endpoints belonging to an APIConnection.
    Returns count of successfully embedded endpoints.
    """
    endpoints = db.query(Endpoint).filter(Endpoint.connection_id == connection_id).all()
    count = 0
    for ep in endpoints:
        text_repr = build_endpoint_text(ep)
        vector = await generate_embedding(text_repr)
        ep.embedding = vector
        count += 1

    db.commit()
    return count


async def semantic_search_endpoints(
    db: Session,
    user_id: int,
    query: str,
    top_k: int = 5,
    threshold: float = 0.0,
    connection_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve endpoints ranked by semantic cosine similarity against user query.
    Enforces user-level data isolation.
    """
    query_vector = await generate_embedding(query)

    # Fetch user's endpoints that have embeddings
    sql_query = (
        db.query(Endpoint, APIConnection.name.label("connection_name"), APIConnection.base_url.label("base_url"))
        .join(APIConnection, Endpoint.connection_id == APIConnection.id)
        .filter(APIConnection.user_id == user_id, Endpoint.embedding.isnot(None))
    )

    if connection_id is not None:
        sql_query = sql_query.filter(Endpoint.connection_id == connection_id)

    results = sql_query.all()

    scored_endpoints = []
    for ep, conn_name, base_url in results:
        if ep.embedding:
            score = cosine_similarity(query_vector, ep.embedding)
            if score >= threshold:
                scored_endpoints.append({
                    "endpoint": ep,
                    "connection_name": conn_name,
                    "base_url": base_url,
                    "similarity_score": round(score, 4),
                })

    # Sort descending by similarity score
    scored_endpoints.sort(key=lambda x: x["similarity_score"], reverse=True)
    return scored_endpoints[:top_k]
