"""Administrator-only raw database browser/editor for the dashboard's
database management page. See app/domain/db_admin_registry.py for exactly
what's redacted and what's editable/deletable, and why.
"""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_permission, verify_csrf
from app.db.session import get_db
from app.services import audit_service, db_admin_service
from app.services.db_admin_service import DBAdminError

router = APIRouter(prefix="/admin/db", tags=["admin-db"])


class UpdateRowRequest(BaseModel):
    changes: dict[str, Any]


def _editable_column_out(col) -> dict:
    # Excludes `validator` (a Python function) — not JSON-serializable and
    # not meaningful to the frontend, which only needs these fields to
    # render the right input control.
    return {"name": col.name, "kind": col.kind, "multiline": col.multiline, "choices": col.choices}


@router.get("/tables")
def list_tables(
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("manage_db")),
) -> list[dict]:
    return [
        {
            **asdict(info),
            "columns": [asdict(c) for c in info.columns],
            "editable_columns": [_editable_column_out(c) for c in info.editable_columns],
        }
        for info in db_admin_service.list_tables(db)
    ]


@router.get("/tables/{table_name}/rows")
def list_rows(
    table_name: str,
    limit: int = Query(default=db_admin_service.DEFAULT_LIMIT, ge=1, le=db_admin_service.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=200),
    sort_by: str | None = Query(default=None, max_length=200),
    sort_dir: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("manage_db")),
) -> dict:
    try:
        rows, total = db_admin_service.list_rows(
            db,
            table_name,
            limit=limit,
            offset=offset,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except DBAdminError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"rows": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/tables/{table_name}/rows/{row_id}")
def get_row(
    table_name: str,
    row_id: str,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("manage_db")),
) -> dict:
    try:
        return db_admin_service.get_row(db, table_name, row_id)
    except DBAdminError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/tables/{table_name}/rows/{row_id}")
def update_row(
    table_name: str,
    row_id: str,
    payload: UpdateRowRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("manage_db")),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    try:
        row = db_admin_service.update_row(db, table_name, row_id, payload.changes)
    except DBAdminError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_service.record(
        db,
        actor_id=current_user.id,
        action="admin.db_row_updated",
        target_type=table_name,
        target_id=row_id,
        detail={"columns": sorted(payload.changes)},
    )
    return row


@router.delete("/tables/{table_name}/rows/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_row(
    table_name: str,
    row_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("manage_db")),
    _csrf: None = Depends(verify_csrf),
) -> None:
    try:
        db_admin_service.delete_row(db, table_name, row_id)
    except DBAdminError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_service.record(
        db,
        actor_id=current_user.id,
        action="admin.db_row_deleted",
        target_type=table_name,
        target_id=row_id,
    )
