"""
APIForge AI Ollama Client Service
Async HTTP client for local Ollama server (Chat, Completion, and Embeddings).
Zero cloud dependencies.
"""
import re
import ssl
from typing import List, Dict, Any, Optional
import certifi
import httpx
from app.config import get_settings

settings = get_settings()

# Pre-build SSLContext once at module load to avoid ~1.2-1.5s/call Windows CA store scanning in httpx.AsyncClient()
_SHARED_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _normalize_ollama_url(url: str) -> str:
    """Resolve localhost -> 127.0.0.1 to avoid Windows IPv6 [::1] connect backoff (~2s/req)."""
    clean = url.rstrip("/")
    return re.sub(r"^(https?://)localhost(?=:|$|/)", r"\g<1>127.0.0.1", clean, flags=re.IGNORECASE)


class OllamaClient:
    """Client for local Ollama API communication."""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[float] = None):
        self.base_url = _normalize_ollama_url(base_url or settings.OLLAMA_URL)
        self.timeout = timeout or settings.OLLAMA_REQUEST_TIMEOUT

    @property
    def current_timeout(self) -> float:
        return self.timeout or get_settings().OLLAMA_REQUEST_TIMEOUT

    def _client(self, timeout: Optional[float] = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=timeout or self.current_timeout,
            verify=_SHARED_SSL_CONTEXT,
            trust_env=False,
        )

    async def is_healthy(self) -> bool:
        """Verify Ollama server is reachable."""
        try:
            async with self._client(timeout=5.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> List[str]:
        """Return list of installed Ollama model names."""
        try:
            async with self._client(timeout=5.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                if r.status_code == 200:
                    data = r.json()
                    return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            pass
        return []

    async def embeddings(self, prompt: str, model: Optional[str] = None) -> List[float]:
        """
        Generate embedding vector for text using nomic-embed-text (or configured model).
        Returns a 768-dimensional float vector.
        """
        target_model = model or settings.EMBED_MODEL
        payload = {
            "model": target_model,
            "prompt": prompt,
            "keep_alive": "10m",
        }

        async with self._client() as client:
            resp = await client.post(f"{self.base_url}/api/embeddings", json=payload)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Ollama embedding error (HTTP {resp.status_code}): {resp.text}"
                )
            data = resp.json()
            embedding = data.get("embedding")
            if not embedding or not isinstance(embedding, list):
                raise ValueError(f"Unexpected embedding response structure: {data}")
            return embedding

    async def embed_batch(self, prompts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """Batch-generate embeddings in a single Ollama `/api/embed` call with fallback."""
        if not prompts:
            return []
        target_model = model or settings.EMBED_MODEL
        payload = {
            "model": target_model,
            "input": prompts,
            "keep_alive": "10m",
        }
        try:
            async with self._client() as client:
                resp = await client.post(f"{self.base_url}/api/embed", json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    vecs = data.get("embeddings")
                    if isinstance(vecs, list) and len(vecs) == len(prompts):
                        return vecs
        except Exception:
            pass
        return [await self.embeddings(p, model=target_model) for p in prompts]

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        format: Optional[str] = None,
        temperature: float = 0.0,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Execute chat completion with local LLM.
        Supports structured JSON mode (format='json') and automatic fallback.
        """
        target_model = model or settings.CHAT_MODEL
        opts = options or {}
        opts.setdefault("temperature", temperature)

        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "stream": False,
            "options": opts,
            "keep_alive": "10m",
        }
        if format:
            payload["format"] = format

        async with self._client() as client:
            try:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("message", {}).get("content", "")
                elif settings.FALLBACK_CHAT_MODEL and target_model != settings.FALLBACK_CHAT_MODEL:
                    # Fallback to secondary model if primary returned error
                    payload["model"] = settings.FALLBACK_CHAT_MODEL
                    fallback_resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                    if fallback_resp.status_code == 200:
                        return fallback_resp.json().get("message", {}).get("content", "")
                raise RuntimeError(f"Ollama chat error (HTTP {resp.status_code}): {resp.text}")
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                detail = str(e) or type(e).__name__
                raise RuntimeError(f"Ollama connection error ({type(e).__name__}): {detail}") from e

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        format: Optional[str] = None,
        temperature: float = 0.0,
    ) -> str:
        """Execute text generation using /api/generate."""
        target_model = model or settings.CHAT_MODEL
        payload: Dict[str, Any] = {
            "model": target_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
            "keep_alive": "10m",
        }
        if system:
            payload["system"] = system
        if format:
            payload["format"] = format

        async with self._client() as client:
            resp = await client.post(f"{self.base_url}/api/generate", json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama generate error (HTTP {resp.status_code}): {resp.text}")
            return resp.json().get("response", "")


# Global singleton instance
ollama_client = OllamaClient()
