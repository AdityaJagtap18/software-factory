from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import enforce as enforce_rate_limit
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.session import Session as SessionModel
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserResponse
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _issue_tokens(db: DBSession, user: User) -> TokenResponse:
    refresh_token = generate_refresh_token()
    db.add(
        SessionModel(
            user_id=user.id,
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=refresh_token,
    )


def _register_rate_limit(request: Request) -> None:
    enforce_rate_limit(request, "auth_register", max_requests=8, window_seconds=60.0)


def _login_rate_limit(request: Request) -> None:
    enforce_rate_limit(request, "auth_login", max_requests=15, window_seconds=60.0)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_register_rate_limit)],
)
def register(payload: RegisterRequest, db: DBSession = Depends(get_db)) -> User:
    existing = db.query(User).filter_by(email=payload.email.lower()).first()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    db.flush()
    audit.record(db, action="user.register", target_type="user", target_id=str(user.id), actor_user_id=user.id)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(_login_rate_limit)])
def login(payload: LoginRequest, db: DBSession = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter_by(email=payload.email.lower()).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")

    tokens = _issue_tokens(db, user)
    audit.record(db, action="user.login", target_type="user", target_id=str(user.id), actor_user_id=user.id)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: DBSession = Depends(get_db)) -> TokenResponse:
    token_hash = hash_refresh_token(payload.refresh_token)
    session = db.query(SessionModel).filter_by(refresh_token_hash=token_hash).first()
    now = datetime.now(timezone.utc)
    if session is None or session.revoked or session.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")

    # Rotate: revoke the used refresh token and issue a new one.
    session.revoked = True
    tokens = _issue_tokens(db, user)
    db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: DBSession = Depends(get_db)) -> None:
    token_hash = hash_refresh_token(payload.refresh_token)
    session = db.query(SessionModel).filter_by(refresh_token_hash=token_hash).first()
    if session is not None:
        session.revoked = True
        db.commit()


def _dev_login_permitted() -> bool:
    # Hard guard: even if dev_quick_login_enabled is mistakenly set in a
    # non-local .env, this stays off unless SF_ENVIRONMENT is also local.
    return (
        settings.is_local_dev
        and settings.dev_quick_login_enabled
        and bool(settings.dev_quick_login_email)
    )


@router.get("/dev-login")
def dev_login_status(db: DBSession = Depends(get_db)) -> dict:
    """Tells the login screen whether to show the local-dev "Quick sign in"
    button, without revealing the configured email unless it's enabled."""
    if not _dev_login_permitted():
        return {"available": False}
    user = db.query(User).filter_by(email=settings.dev_quick_login_email.lower()).first()
    if user is None or not user.is_active:
        return {"available": False}
    return {"available": True, "display_name": user.full_name}


@router.post("/dev-login", response_model=TokenResponse, dependencies=[Depends(_login_rate_limit)])
def dev_login(db: DBSession = Depends(get_db)) -> TokenResponse:
    """Issues tokens for the configured local-dev account with no password
    check. Only ever active when dev_quick_login_enabled is set in a
    gitignored .env -- never in a real deployment."""
    if not _dev_login_permitted():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quick sign in is not enabled")

    user = db.query(User).filter_by(email=settings.dev_quick_login_email.lower()).first()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quick sign in is not enabled")

    tokens = _issue_tokens(db, user)
    audit.record(db, action="user.dev_login", target_type="user", target_id=str(user.id), actor_user_id=user.id)
    db.commit()
    return tokens


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user
