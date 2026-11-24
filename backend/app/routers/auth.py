"""
APIForge AI Authentication Router
Endpoints for user registration, login, token generation, and profile retrieval.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, AuditLog
from app.schemas import (
    UserCreate,
    UserResponse,
    LoginRequest,
    TokenResponse,
)
from app.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
    get_current_active_admin,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
def register(
    user_in: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Register a new user account with hashed password and audit logging."""
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # First user or specified role
    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role if user_in.role in ["admin", "user"] else "user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Log audit event
    client_ip = request.client.host if request.client else None
    audit = AuditLog(
        user_id=user.id,
        action="user_registered",
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email, "role": user.role},
        ip_address=client_ip,
    )
    db.add(audit)
    db.commit()

    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="User login with JSON credentials",
)
def login_json(
    credentials: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Authenticate with email and password, returning JWT access token."""
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role}
    )

    # Audit log
    client_ip = request.client.host if request.client else None
    audit = AuditLog(
        user_id=user.id,
        action="user_login",
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email},
        ip_address=client_ip,
    )
    db.add(audit)
    db.commit()

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="OAuth2 compatible token login for Swagger UI",
)
def login_oauth2(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """OAuth2 standard form login endpoint powering Swagger documentation."""
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role}
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user profile",
)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """Return profile details for the currently authenticated user."""
    return current_user


@router.get(
    "/admin-only",
    summary="Admin-only RBAC verification endpoint",
)
def admin_only_check(
    admin_user: User = Depends(get_current_active_admin),
):
    """Protected endpoint restricted strictly to users with the 'admin' role."""
    return {
        "status": "authorized",
        "message": f"Welcome Administrator {admin_user.email}",
        "role": admin_user.role,
    }
