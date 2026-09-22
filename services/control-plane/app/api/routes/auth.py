from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, verify_csrf
from app.core.config import settings
from app.core.cookies import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, REFRESH_COOKIE_NAME
from app.core.security import create_access_token, generate_token
from app.db.session import get_db
from app.schemas.auth import LoginRequest, MessageResponse, UserOut
from app.services import audit_service, auth_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        max_age=settings.access_token_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        # Scoped to /auth so it's only ever sent to the refresh/logout
        # endpoints that need it, not to every API call.
        path="/auth",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        generate_token(),
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/auth")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> UserOut:
    normalized_email = payload.email.strip().lower()
    try:
        user = auth_service.authenticate(db, payload.email, payload.password)
    except AuthError:
        audit_service.record(
            db,
            actor_id=None,
            action="auth.login_failed",
            target_type="user",
            target_id=normalized_email,
            detail={"reason": "invalid_credentials"},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")

    roles = auth_service.get_role_names(user)
    access_token = create_access_token(str(user.id), roles)
    refresh_token, _ = auth_service.create_refresh_session(db, user)
    _set_session_cookies(response, access_token, refresh_token)

    audit_service.record(
        db,
        actor_id=user.id,
        action="auth.login_succeeded",
        target_type="user",
        target_id=str(user.id),
    )
    return UserOut(id=user.id, email=user.email, roles=roles)


@router.post("/refresh", response_model=UserOut, dependencies=[Depends(verify_csrf)])
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> UserOut:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="no refresh session")

    try:
        new_raw_token, _, user = auth_service.rotate_refresh_session(db, raw_token)
    except AuthError:
        _clear_session_cookies(response)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="invalid or expired refresh session"
        )

    roles = auth_service.get_role_names(user)
    access_token = create_access_token(str(user.id), roles)
    _set_session_cookies(response, access_token, new_raw_token)
    return UserOut(id=user.id, email=user.email, roles=roles)


@router.post("/logout", response_model=MessageResponse, dependencies=[Depends(verify_csrf)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> MessageResponse:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    actor_id = auth_service.revoke_refresh_session(db, raw_token) if raw_token else None
    _clear_session_cookies(response)

    audit_service.record(
        db,
        actor_id=actor_id,
        action="auth.logout",
        target_type="user",
        target_id=str(actor_id) if actor_id else "unknown",
    )
    return MessageResponse(message="logged out")


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser = Depends(get_current_user)) -> UserOut:
    return UserOut(id=current_user.id, email=current_user.email, roles=sorted(current_user.roles))
