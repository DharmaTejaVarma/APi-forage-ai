"""
APIForge AI Security Module
Handles password hashing (bcrypt), credential encryption (Fernet),
JWT token generation/verification, and RBAC dependency injection.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import bcrypt
from cryptography.fernet import Fernet
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


# ============================================================================
# Password Hashing & Verification
# ============================================================================

def get_password_hash(password: str) -> str:
    """Hash plain text password using bcrypt with salt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain text password against bcrypt hashed password."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


# ============================================================================
# Credential Encryption (Fernet) & Secret Masking
# ============================================================================

def _get_fernet() -> Fernet:
    """Return Fernet cipher initialized with configured 32-byte key."""
    key = settings.FERNET_KEY.encode()
    return Fernet(key)


def encrypt_secret(secret_text: str) -> str:
    """Encrypt sensitive string (e.g. API keys, tokens) using Fernet."""
    if not secret_text:
        return ""
    cipher = _get_fernet()
    token = cipher.encrypt(secret_text.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(encrypted_token: str) -> str:
    """Decrypt Fernet encrypted token back into plaintext string."""
    if not encrypted_token:
        return ""
    cipher = _get_fernet()
    decrypted = cipher.decrypt(encrypted_token.encode("utf-8"))
    return decrypted.decode("utf-8")


def mask_secret(secret: str, visible_chars: int = 4) -> str:
    """
    Mask sensitive secrets for safe display in logs and responses.
    Example: 'sk_live_1234567890abcdef' -> 'sk_l...cdef'
    """
    if not secret:
        return ""
    length = len(secret)
    if length <= (visible_chars * 2):
        return "********"
    return f"{secret[:visible_chars]}...{secret[-visible_chars:]}"


# ============================================================================
# JWT Token Generation & Decoding
# ============================================================================

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create signed JWT access token containing subject, email, and role."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate JWT access token."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


# ============================================================================
# FastAPI Auth & RBAC Dependencies
# ============================================================================

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency that extracts and validates user from Bearer JWT.
    Enforces user existence and active status.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid subject in token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    return user


async def get_current_active_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    FastAPI dependency that ensures the authenticated user possesses the 'admin' role.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required",
        )
    return current_user
