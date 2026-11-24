"""
APIForge AI Main Application
FastAPI application with health check and system status monitoring.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import check_db_connectivity, init_db
from app.schemas import HealthResponse
from app.routers import auth, connections, endpoints, workflows, executions, dashboard, admin
from app.mock_server.mock_api import mock_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler to initialize database tables on startup."""
    init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI-powered platform converting natural-language instructions into executable API workflows.",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Register Routers
app.include_router(auth.router, prefix="/api")
app.include_router(auth.router)
app.include_router(connections.router, prefix="/api")
app.include_router(connections.router)
app.include_router(endpoints.router, prefix="/api")
app.include_router(endpoints.router)
app.include_router(workflows.router, prefix="/api")
app.include_router(workflows.router)
app.include_router(executions.router, prefix="/api")
app.include_router(executions.router)
app.include_router(dashboard.router, prefix="/api")
app.include_router(dashboard.router)
app.include_router(admin.router, prefix="/api")
app.include_router(admin.router)
app.include_router(mock_router)


async def check_ollama_status() -> Dict[str, Any]:
    """Check Ollama connectivity and verify configured models."""
    ollama_url = settings.OLLAMA_URL.rstrip("/")
    tags_url = f"{ollama_url}/api/tags"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(tags_url)
            if resp.status_code == 200:
                data = resp.json()
                raw_models = data.get("models", [])
                # Collect all model names (with and without :latest)
                model_names: List[str] = []
                for m in raw_models:
                    name = m.get("name", "")
                    model_names.append(name)
                    if ":" in name:
                        model_names.append(name.split(":")[0])

                # Helper to match model
                def is_model_present(target: str) -> bool:
                    target_lower = target.lower()
                    target_base = target.split(":")[0].lower()
                    for m in raw_models:
                        m_name = m.get("name", "").lower()
                        if target_lower == m_name or target_lower == m_name.replace(":latest", ""):
                            return True
                        if target_base in m_name:
                            return True
                    return False

                chat_available = is_model_present(settings.CHAT_MODEL)
                fallback_available = is_model_present(settings.FALLBACK_CHAT_MODEL)
                embed_available = is_model_present(settings.EMBED_MODEL)

                return {
                    "status": "ok" if (chat_available or fallback_available) and embed_available else "degraded",
                    "url": settings.OLLAMA_URL,
                    "connected": True,
                    "models": {
                        "chat_model": {
                            "name": settings.CHAT_MODEL,
                            "available": chat_available,
                            "fallback_available": fallback_available,
                            "fallback_name": settings.FALLBACK_CHAT_MODEL
                        },
                        "embed_model": {
                            "name": settings.EMBED_MODEL,
                            "available": embed_available
                        }
                    },
                    "available_models": [m.get("name") for m in raw_models]
                }
            else:
                return {
                    "status": "error",
                    "url": settings.OLLAMA_URL,
                    "connected": False,
                    "error": f"Ollama returned HTTP status {resp.status_code}",
                    "models": {
                        "chat_model": {"name": settings.CHAT_MODEL, "available": False},
                        "embed_model": {"name": settings.EMBED_MODEL, "available": False}
                    }
                }
    except Exception as e:
        return {
            "status": "error",
            "url": settings.OLLAMA_URL,
            "connected": False,
            "error": str(e),
            "models": {
                "chat_model": {"name": settings.CHAT_MODEL, "available": False},
                "embed_model": {"name": settings.EMBED_MODEL, "available": False}
            }
        }


@app.get("/", tags=["Root"])
def root():
    """Root welcome endpoint."""
    return {
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "online",
        "docs_url": "/docs"
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint:
    1. Backend application status.
    2. SQLite database connectivity (SELECT 1).
    3. Ollama connectivity.
    4. Availability of both configured AI models.
    """
    # 1. Backend application status
    backend_status = {"status": "ok"}

    # 2. Database connectivity
    db_connected = check_db_connectivity()
    db_status = {
        "status": "ok" if db_connected else "error",
        "dialect": "sqlite",
        "connected": db_connected
    }

    # 3 & 4. Ollama and model availability
    ollama_status = await check_ollama_status()

    # Overall system status
    is_healthy = (
        backend_status["status"] == "ok"
        and db_status["status"] == "ok"
        and ollama_status["connected"] is True
    )

    overall_status = "healthy" if is_healthy else "degraded"

    return HealthResponse(
        status=overall_status,
        version=settings.VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        services={
            "backend": backend_status,
            "database": db_status,
            "ollama": ollama_status
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
