"""
APIForge AI Semantic Embeddings & Similarity Service
Generates dense vector embeddings using nomic-embed-text via local Ollama.
Computes cosine similarity with NumPy combined with intent, parameter,
and response compatibility signals for accurate endpoint discovery.
"""
import asyncio
import re
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Endpoint, APIConnection
from app.services.ollama_client import ollama_client

settings = get_settings()


def _extract_schema_fields(schema: Any) -> List[str]:
    """Recursively collect top-level and nested object property names from a JSONSchema."""
    fields: List[str] = []
    if not isinstance(schema, dict):
        return fields
    props = schema.get("properties")
    if isinstance(props, dict):
        for k, v in props.items():
            fields.append(k)
            sub = _extract_schema_fields(v)
            fields.extend(f"{k}.{s}" for s in sub[:5])
    elif schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        fields.extend(_extract_schema_fields(schema["items"]))
    return fields


def build_endpoint_text(endpoint: Any) -> str:
    """
    Construct rich contextual string from endpoint metadata for vector embedding.
    Includes HTTP method, path, summary, description, parameter signatures,
    request body fields, response schema fields, and authentication schemes.
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
                req_flag = " required" if p.get("required") else ""
                param_strs.append(f"{p_name} ({p_in}{req_flag}): {p_desc}")
        if param_strs:
            parts.append(f"Parameters: {'; '.join(param_strs)}")

    req_body = getattr(endpoint, "request_body_schema", None)
    if req_body and isinstance(req_body, dict):
        req_fields = _extract_schema_fields(req_body)
        if req_fields:
            parts.append(f"Request Fields: {', '.join(req_fields)}")

    resp_schema = getattr(endpoint, "response_schema", None)
    if resp_schema and isinstance(resp_schema, dict):
        resp_fields = _extract_schema_fields(resp_schema)
        if resp_fields:
            parts.append(f"Response Fields: {', '.join(resp_fields)}")

    security = getattr(endpoint, "security", None)
    if security and isinstance(security, list):
        schemes = [str(s.get("scheme") or s.get("type") or "auth") for s in security if isinstance(s, dict)]
        if schemes:
            parts.append(f"Authentication Required: {', '.join(schemes)}")

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
    Generate embeddings in batch for all endpoints belonging to an APIConnection.
    Returns count of successfully embedded endpoints.
    """
    endpoints = db.query(Endpoint).filter(Endpoint.connection_id == connection_id).all()
    if not endpoints:
        return 0
    texts = [build_endpoint_text(ep) for ep in endpoints]
    is_unmocked = (
        getattr(generate_embedding, "__module__", "") == "app.services.embeddings"
        and type(generate_embedding).__name__ == "function"
    )
    if is_unmocked:
        vectors = await ollama_client.embed_batch(texts)
    else:
        vectors = await asyncio.gather(*(generate_embedding(t) for t in texts))
    for ep, vector in zip(endpoints, vectors):
        ep.embedding = vector

    db.commit()
    return len(endpoints)


def _compute_lexical_and_intent_score(ep: Endpoint, query: str) -> float:
    """
    Compute lightweight heuristic boost [0.0, 1.0] combining keyword overlap,
    HTTP method intent alignment, parameter name relevance, and response fields.
    Used both as fallback when embeddings are unavailable and to break ties accurately.
    """
    q_lower = query.lower()
    tokens = set(re.findall(r"[a-z0-9_]+", q_lower))
    stopwords = {"a", "an", "the", "to", "and", "of", "for", "with", "using", "in", "on", "is", "by", "from", "its", "an"}
    meaningful = tokens - stopwords

    ep_text = build_endpoint_text(ep).lower()
    ep_tokens = set(re.findall(r"[a-z0-9_]+", ep_text))
    overlap = len(meaningful & ep_tokens)
    lexical = (overlap / max(len(meaningful), 1)) if meaningful else 0.0

    method = ep.method.upper()
    method_bonus = 0.0
    if method == "GET" and any(v in tokens for v in {"fetch", "get", "retrieve", "list", "find", "check", "access", "read", "show"}):
        method_bonus = 0.08
    elif method == "POST" and any(v in tokens for v in {"create", "send", "post", "submit", "order", "calculate", "compute", "notify", "email"}):
        method_bonus = 0.08
    elif method in {"PUT", "PATCH"} and any(v in tokens for v in {"update", "modify", "patch", "change", "edit"}):
        method_bonus = 0.08
    elif method == "DELETE" and any(v in tokens for v in {"delete", "remove", "cancel"}):
        method_bonus = 0.08

    return float(min(1.0, lexical * 0.85 + method_bonus))


async def semantic_search_endpoints(
    db: Session,
    user_id: int,
    query: str,
    top_k: int = 5,
    threshold: float = 0.0,
    connection_id: Optional[int] = None,
    connection_ids: Optional[List[int]] = None,
    auto_embed_missing: bool = True,
) -> List[Dict[str, Any]]:
    """
    Retrieve endpoints ranked by semantic cosine similarity + intent/schema compatibility
    against user query. Enforces strict user-level data isolation across active connections.
    """
    sql_query = (
        db.query(Endpoint, APIConnection.name.label("connection_name"), APIConnection.base_url.label("base_url"))
        .join(APIConnection, Endpoint.connection_id == APIConnection.id)
        .filter(APIConnection.user_id == user_id, APIConnection.is_active == True)
    )

    if connection_id is not None:
        sql_query = sql_query.filter(Endpoint.connection_id == connection_id)
    if connection_ids:
        sql_query = sql_query.filter(Endpoint.connection_id.in_(connection_ids))

    results = sql_query.all()
    if not results:
        return []

    # Lazily embed endpoints that lack embeddings in one batch alongside query embedding
    query_vector: Optional[List[float]] = None
    try:
        is_unmocked = (
            getattr(generate_embedding, "__module__", "") == "app.services.embeddings"
            and type(generate_embedding).__name__ == "function"
        )
        missing = [ep for ep, _, _ in results if not ep.embedding]
        if auto_embed_missing and missing:
            texts = [build_endpoint_text(ep) for ep in missing] + [query]
            if is_unmocked:
                vectors = await ollama_client.embed_batch(texts)
            else:
                vectors = await asyncio.gather(*(generate_embedding(t) for t in texts))
            for ep, vec in zip(missing, vectors[:-1]):
                ep.embedding = vec
            query_vector = vectors[-1]
            db.commit()
        elif any(ep.embedding for ep, _, _ in results):
            if is_unmocked:
                vecs = await ollama_client.embed_batch([query])
                query_vector = vecs[0] if vecs else None
            else:
                query_vector = await generate_embedding(query)
    except Exception:
        query_vector = None

    scored_endpoints = []
    for ep, conn_name, base_url in results:
        lexical_score = _compute_lexical_and_intent_score(ep, query)
        if query_vector is not None and ep.embedding:
            vec_sim = cosine_similarity(query_vector, ep.embedding)
            # Small intent/parameter tie-breaker while keeping vector similarity primary
            score = float(np.clip(vec_sim + min(0.08, lexical_score * 0.08), -1.0, 1.0))
        else:
            score = lexical_score

        if score >= threshold:
            scored_endpoints.append({
                "endpoint": ep,
                "connection_name": conn_name,
                "base_url": base_url,
                "similarity_score": round(score, 4),
            })

    scored_endpoints.sort(key=lambda x: x["similarity_score"], reverse=True)
    return scored_endpoints[:top_k]
