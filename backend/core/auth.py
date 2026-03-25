"""
Authentication module – JWT-based lightweight auth for the platform.

Provides:
- Password hashing (bcrypt directly)
- JWT token creation & verification
- FastAPI dependency for extracting the current user
- Auth routes (register, login, me)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel
from sqlalchemy import select

from backend.config import auth_settings
from backend.core.database import User, async_session

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Bearer token extraction
bearer_scheme = HTTPBearer(auto_error=False)


# ─────────────────────────────────────────────────
# Password hashing (using bcrypt directly)
# ─────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ─────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# ─────────────────────────────────────────────────
# JWT helpers
# ─────────────────────────────────────────────────

def _create_token(user_id: str, username: str, is_admin: bool) -> str:
    """Create a JWT access token."""
    expire = datetime.utcnow() + timedelta(minutes=auth_settings.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "username": username,
        "is_admin": is_admin,
        "exp": expire,
    }
    return jwt.encode(payload, auth_settings.secret_key, algorithm=auth_settings.algorithm)


def _verify_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT token. Returns payload or None."""
    try:
        payload = jwt.decode(token, auth_settings.secret_key, algorithms=[auth_settings.algorithm])
        return payload
    except JWTError:
        return None


# ─────────────────────────────────────────────────
# FastAPI dependencies
# ─────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """
    Extract and validate the current user from the Authorization header.
    Raises 401 if not authenticated.
    """
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = _verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    # Fetch the user from DB to ensure they still exist
    async with async_session() as session:
        user = await session.get(User, payload["sub"])
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user.to_dict()


async def get_current_user_from_token_or_header(
    token: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """
    Extract and validate the current user from either:
    1. A query parameter `?token=xxx` (for web page access in new tabs)
    2. The Authorization header (standard API calls)
    Raises 401 if not authenticated.
    """
    raw_token = None
    if token:
        raw_token = token
    elif credentials:
        raw_token = credentials.credentials

    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = _verify_token(raw_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    async with async_session() as session:
        user = await session.get(User, payload["sub"])
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user.to_dict()


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[dict]:
    """
    Same as get_current_user but returns None instead of raising if not authenticated.
    Useful for endpoints that work differently for logged-in vs anonymous users.
    """
    if not credentials:
        return None
    payload = _verify_token(credentials.credentials)
    if not payload:
        return None
    async with async_session() as session:
        user = await session.get(User, payload["sub"])
        return user.to_dict() if user else None


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency that requires the current user to be an admin."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# ─────────────────────────────────────────────────
# Admin user bootstrap
# ─────────────────────────────────────────────────

async def ensure_default_admin():
    """Create the default admin user if it doesn't exist."""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.username == auth_settings.default_admin_username)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return

        admin = User(
            id=str(uuid.uuid4()),
            username=auth_settings.default_admin_username,
            display_name="Admin",
            password_hash=_hash_password(auth_settings.default_admin_password),
            is_admin=True,
        )
        session.add(admin)
        await session.commit()


# ─────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    """Register a new user account."""
    if not req.username or len(req.username) < 2:
        raise HTTPException(400, "Username must be at least 2 characters")
    if not req.password or len(req.password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")

    async with async_session() as session:
        # Check if username is taken
        result = await session.execute(select(User).where(User.username == req.username))
        if result.scalar_one_or_none():
            raise HTTPException(409, "Username already taken")

        user = User(
            id=str(uuid.uuid4()),
            username=req.username,
            display_name=req.display_name or req.username,
            password_hash=_hash_password(req.password),
            is_admin=False,
        )
        session.add(user)
        await session.commit()

        token = _create_token(user.id, user.username, user.is_admin)
        return TokenResponse(access_token=token, user=user.to_dict())


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Login with username and password."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.username == req.username))
        user = result.scalar_one_or_none()

        if not user or not _verify_password(req.password, user.password_hash):
            raise HTTPException(401, "Invalid username or password")

        token = _create_token(user.id, user.username, user.is_admin)
        return TokenResponse(access_token=token, user=user.to_dict())


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get the current authenticated user."""
    return user
