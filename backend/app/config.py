"""
APIForge AI Configuration Module
Loads settings from environment variables and .env file with validation.
"""
from functools import lru_cache
from typing import List
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Backend root directory
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Project metadata
    PROJECT_NAME: str = "APIForge AI"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "sqlite:///./apiforge.db"

    @property
    def resolved_database_url(self) -> str:
        """Resolve SQLite database path to absolute path anchored to BACKEND_DIR."""
        if self.DATABASE_URL.startswith("sqlite:///./"):
            rel_name = self.DATABASE_URL[len("sqlite:///./") :]
            db_path = (BACKEND_DIR / rel_name).resolve()
            return f"sqlite:///{db_path.as_posix()}"
        return self.DATABASE_URL

    # Ollama Local AI
    OLLAMA_URL: str = "http://localhost:11434"
    CHAT_MODEL: str = "qwen2.5:7b-instruct"
    FALLBACK_CHAT_MODEL: str = "qwen2.5:3b"
    EMBED_MODEL: str = "nomic-embed-text"
    OLLAMA_REQUEST_TIMEOUT: float = 300.0

    @property
    def OLLAMA_BASE_URL(self) -> str:
        """Alias for backward compatibility."""
        return self.OLLAMA_URL

    # Security & Encryption
    JWT_SECRET: str = "apiforge-super-secret-jwt-key-change-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    FERNET_KEY: str = "8s_Z3l0m0QZkX8aB7W2kQ_8k1j0gR9v3lZ5xY7bA4uE="

    @property
    def SECRET_KEY(self) -> str:
        """Alias for JWT_SECRET."""
        return self.JWT_SECRET

    # Network & SSRF allowlists
    ALLOWED_DOMAINS: str = ""
    DEV_ALLOWED_HOSTS: str = "localhost,127.0.0.1"

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def dev_allowed_hosts_list(self) -> List[str]:
        return [host.strip() for host in self.DEV_ALLOWED_HOSTS.split(",") if host.strip()]

    @property
    def allowed_domains_list(self) -> List[str]:
        return [domain.strip() for domain in self.ALLOWED_DOMAINS.split(",") if domain.strip()]


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
