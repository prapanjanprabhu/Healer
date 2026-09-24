import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_permission, verify_csrf
from app.db.session import get_db
from app.schemas.users import CreateUserRequest, SetUserRolesRequest, UserSummaryOut
from app.services import audit_service, auth_service, user_service
from app.services.user_service import UserServiceError

router = APIRouter(prefix="/users", tags=["users"])


def _summary(user) -> UserSummaryOut:
    return UserSummaryOut(
        id=user.id,
        email=user.email,
        roles=auth_service.get_role_names(user),
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.get("", response_model=list[UserSummaryOut])
def list_users(
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("manage_users")),
) -> list[UserSummaryOut]:
    return [_summary(u) for u in user_service.list_users(db)]


@router.get("/roles", response_model=list[str])
def list_role_names(
    _current_user: CurrentUser = Depends(require_permission("manage_users")),
) -> list[str]:
    return user_service.list_role_names()


@router.post("", response_model=UserSummaryOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("manage_users")),
    _csrf: None = Depends(verify_csrf),
) -> UserSummaryOut:
    try:
        user = user_service.create_user(
            db, email=payload.email, password=payload.password, role_names=payload.roles
        )
    except UserServiceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    audit_service.record(
        db,
        actor_id=current_user.id,
        action="user.create",
        target_type="user",
        target_id=str(user.id),
        detail={"email": user.email, "roles": payload.roles},
    )
    return _summary(user)


@router.patch("/{user_id}/roles", response_model=UserSummaryOut)
def set_user_roles(
    user_id: uuid.UUID,
    payload: SetUserRolesRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("manage_users")),
    _csrf: None = Depends(verify_csrf),
) -> UserSummaryOut:
    user = user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    if user_id == current_user.id and "Administrator" not in payload.roles:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="you cannot remove your own Administrator role"
        )

    try:
        user_service.set_user_roles(db, user, payload.roles)
    except UserServiceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    audit_service.record(
        db,
        actor_id=current_user.id,
        action="user.roles_changed",
        target_type="user",
        target_id=str(user.id),
        detail={"roles": payload.roles},
    )
    return _summary(user)


@router.post("/{user_id}/deactivate", response_model=UserSummaryOut)
def deactivate_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("manage_users")),
    _csrf: None = Depends(verify_csrf),
) -> UserSummaryOut:
    if user_id == current_user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="you cannot deactivate your own account"
        )
    user = user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")

    user_service.set_user_active(db, user, False)
    audit_service.record(
        db,
        actor_id=current_user.id,
        action="user.deactivated",
        target_type="user",
        target_id=str(user.id),
    )
    return _summary(user)


@router.post("/{user_id}/activate", response_model=UserSummaryOut)
def activate_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("manage_users")),
    _csrf: None = Depends(verify_csrf),
) -> UserSummaryOut:
    user = user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")

    user_service.set_user_active(db, user, True)
    audit_service.record(
        db,
        actor_id=current_user.id,
        action="user.activated",
        target_type="user",
        target_id=str(user.id),
    )
    return _summary(user)
