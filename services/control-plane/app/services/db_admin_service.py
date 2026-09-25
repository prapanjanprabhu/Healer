"""Generic Postgres table browser/editor for the Administrator-only database
management dashboard page — phpMyAdmin-style: every table, every column,
full edit/delete, auto-derived from the real schema on `Base.metadata`
rather than hand-written per table. What stays redacted/non-editable (a
handful of hash/ciphertext columns) and why is entirely decided by
app/domain/db_admin_registry.py; this module enforces it plus does the
actual type-aware read/write. See app/api/routes/admin_db.py for the HTTP
layer.
"""

from __future__ import annotations

import datetime
import enum
import json
import uuid as uuid_mod
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.base import Base
from app.domain.db_admin_registry import (
    GLOBAL_SENSITIVE_COLUMNS,
    JSON_REDACT_COLUMNS,
    EditableColumn,
    redact_json,
    validator_for,
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

REDACTED = "[REDACTED]"

# alembic_version isn't a Healer table — it's Alembic's own bookkeeping row
# and has no primary key SQLAlchemy would recognize, so exclude it from the
# browsable set rather than special-casing it throughout.
_EXCLUDED_TABLES = frozenset({"alembic_version"})


class DBAdminError(ValueError):
    """A request this module refuses on validation grounds — routes
    translate this to a 400/404, never a 500.
    """


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    primary_key: bool
    sensitive: bool


@dataclass(frozen=True)
class TableInfo:
    name: str
    row_count: int
    editable: bool
    deletable: bool
    single_column_pk: str | None
    columns: list[ColumnInfo]
    editable_columns: list[EditableColumn]


def _table_names() -> list[str]:
    return sorted(name for name in Base.metadata.tables if name not in _EXCLUDED_TABLES)


def get_table(table_name: str) -> sa.Table:
    if table_name in _EXCLUDED_TABLES or table_name not in Base.metadata.tables:
        raise DBAdminError(f"unknown table {table_name!r}")
    return Base.metadata.tables[table_name]


def _is_json_column(column: sa.Column) -> bool:
    return isinstance(column.type, sa.JSON) or column.type.__class__.__name__.upper() in (
        "JSONB",
        "JSON",
    )


def _column_type_name(column: sa.Column) -> str:
    if isinstance(column.type, sa.Enum):
        return "enum"
    if _is_json_column(column):
        return "json"
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        python_type = None
    if python_type is bool:
        return "boolean"
    if python_type is int:
        return "integer"
    if python_type is float:
        return "float"
    if python_type is datetime.datetime:
        return "datetime"
    if python_type is uuid_mod.UUID:
        return "uuid"
    return "string"


def _single_column_pk(table: sa.Table) -> str | None:
    pk_columns = list(table.primary_key.columns)
    if len(pk_columns) != 1:
        return None
    return pk_columns[0].name


def _editable_columns(table: sa.Table, table_name: str) -> list[EditableColumn]:
    """Every column is editable except the primary key (editing it would
    silently break every FK reference to this row across a UUID-FK-heavy,
    CASCADE-heavy schema — a purely structural reason, not a policy one)
    and the always-redacted sensitive/JSON-redacted columns (there's no
    value that round-trips safely once we've shown the admin a redacted
    placeholder instead of the real one).
    """
    pk_name = _single_column_pk(table)
    redacted_json = JSON_REDACT_COLUMNS.get(table_name, frozenset())
    columns = []
    for col in table.columns:
        if col.name == pk_name:
            continue
        if col.name in GLOBAL_SENSITIVE_COLUMNS:
            continue
        if col.name in redacted_json:
            continue
        columns.append(_to_editable_column(col, table_name))
    return columns


def _to_editable_column(col: sa.Column, table_name: str) -> EditableColumn:
    validator = validator_for(table_name, col.name)
    if isinstance(col.type, sa.Enum):
        enum_class = getattr(col.type, "enum_class", None)
        choices = tuple(v.value for v in enum_class) if enum_class else tuple(col.type.enums)
        return EditableColumn(col.name, "select", choices=choices, validator=validator)
    if _is_json_column(col):
        return EditableColumn(col.name, "json", multiline=True, validator=validator)
    try:
        python_type = col.type.python_type
    except NotImplementedError:
        python_type = None
    if python_type is bool:
        return EditableColumn(col.name, "boolean", validator=validator)
    multiline = isinstance(col.type, sa.Text)
    kind = "optional_text" if col.nullable else "text"
    return EditableColumn(col.name, kind, multiline=multiline, validator=validator)


def list_tables(session: Session) -> list[TableInfo]:
    infos = []
    for name in _table_names():
        table = Base.metadata.tables[name]
        single_pk = _single_column_pk(table)
        row_count = session.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
        columns = [
            ColumnInfo(
                name=col.name,
                type=_column_type_name(col),
                nullable=col.nullable if col.nullable is not None else True,
                primary_key=col.primary_key,
                sensitive=col.name in GLOBAL_SENSITIVE_COLUMNS,
            )
            for col in table.columns
        ]
        # Addressing a row by id (edit/delete) requires a single-column
        # primary key — `user_roles` (composite PK) is the only table this
        # excludes; it's still fully listable/viewable above.
        can_address_rows = single_pk is not None
        infos.append(
            TableInfo(
                name=name,
                row_count=row_count,
                editable=can_address_rows,
                deletable=can_address_rows,
                single_column_pk=single_pk,
                columns=columns,
                editable_columns=_editable_columns(table, name) if can_address_rows else [],
            )
        )
    return infos


def _redact_row(table_name: str, row: dict[str, Any]) -> dict[str, Any]:
    json_columns = JSON_REDACT_COLUMNS.get(table_name, frozenset())
    redacted = dict(row)
    for key, value in redacted.items():
        if key in GLOBAL_SENSITIVE_COLUMNS and value is not None:
            redacted[key] = REDACTED
        elif key in json_columns and value is not None:
            redacted[key] = redact_json(value)
    return redacted


def _row_to_dict(table: sa.Table, row: sa.Row) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column, value in zip(table.columns, row, strict=True):
        if isinstance(value, enum.Enum):
            value = value.value
        result[column.name] = value
    return result


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_condition(table: sa.Table, search: str) -> sa.ColumnElement[bool]:
    """One ILIKE-across-every-column search, the way a DataTable's search
    box behaves — every text-castable, non-sensitive column is checked,
    OR'd together. Sensitive columns (GLOBAL_SENSITIVE_COLUMNS) are left
    out: matching against a redacted value could never mean anything to
    whoever typed the search term.
    """
    pattern = f"%{_escape_like(search)}%"
    conditions = [
        sa.cast(col, sa.Text).ilike(pattern, escape="\\")
        for col in table.columns
        if col.name not in GLOBAL_SENSITIVE_COLUMNS
    ]
    return sa.or_(*conditions)


def list_rows(
    session: Session,
    table_name: str,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    table = get_table(table_name)
    limit = max(1, min(limit or DEFAULT_LIMIT, MAX_LIMIT))
    offset = max(0, offset or 0)

    stmt = sa.select(table)
    count_stmt = sa.select(sa.func.count()).select_from(table)

    search = (search or "").strip()
    if search:
        condition = _search_condition(table, search)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    sort_column = table.columns.get(sort_by) if sort_by else None
    if sort_column is not None:
        stmt = stmt.order_by(sort_column.desc() if sort_dir == "desc" else sort_column.asc())
    else:
        order_column = table.columns.get("created_at")
        if order_column is None:
            order_column = list(table.primary_key.columns)[0] if table.primary_key.columns else None
        if order_column is not None:
            stmt = stmt.order_by(order_column.desc())

    stmt = stmt.limit(limit).offset(offset)

    rows = [_redact_row(table_name, _row_to_dict(table, row)) for row in session.execute(stmt)]
    total = session.execute(count_stmt).scalar_one()
    return rows, total


def _pk_column(table: sa.Table, table_name: str) -> sa.Column:
    pk_name = _single_column_pk(table)
    if pk_name is None:
        raise DBAdminError(
            f"{table_name!r} has a composite primary key and can't be fetched/edited/deleted by id"
        )
    return table.columns[pk_name]


def get_row(session: Session, table_name: str, row_id: str) -> dict[str, Any]:
    table = get_table(table_name)
    pk = _pk_column(table, table_name)
    stmt = sa.select(table).where(pk == row_id)
    row = session.execute(stmt).first()
    if row is None:
        raise DBAdminError(f"no row in {table_name!r} with {pk.name}={row_id!r}")
    return _redact_row(table_name, _row_to_dict(table, row))


def _coerce_value(col: sa.Column, col_spec: EditableColumn, raw_value: Any) -> Any:
    if raw_value is None:
        return None
    if col_spec.kind == "json":
        if isinstance(raw_value, (dict, list)):
            return raw_value
        try:
            return json.loads(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"must be valid JSON ({exc})") from exc
    if col_spec.kind == "boolean":
        if isinstance(raw_value, bool):
            return raw_value
        return str(raw_value).strip().lower() in ("1", "true", "yes", "on")

    try:
        python_type = col.type.python_type
    except NotImplementedError:
        python_type = None

    text_value = str(raw_value)
    if python_type is int:
        try:
            return int(text_value)
        except ValueError as exc:
            raise ValueError("must be a whole number") from exc
    if python_type is float:
        try:
            return float(text_value)
        except ValueError as exc:
            raise ValueError("must be a number") from exc
    if python_type is uuid_mod.UUID:
        try:
            return uuid_mod.UUID(text_value)
        except ValueError as exc:
            raise ValueError("must be a valid UUID") from exc
    if python_type is datetime.datetime:
        try:
            return datetime.datetime.fromisoformat(text_value)
        except ValueError as exc:
            raise ValueError("must be an ISO 8601 datetime, e.g. 2026-01-31T12:00:00Z") from exc
    return raw_value


def update_row(
    session: Session, table_name: str, row_id: str, changes: dict[str, Any]
) -> dict[str, Any]:
    table = get_table(table_name)
    pk = _pk_column(table, table_name)

    allowed = {col.name: col for col in _editable_columns(table, table_name)}
    unknown = set(changes) - set(allowed)
    if unknown:
        raise DBAdminError(f"these columns are not editable on {table_name!r}: {sorted(unknown)}")

    validated: dict[str, Any] = {}
    for key, raw_value in changes.items():
        col_spec = allowed[key]
        value = raw_value
        if col_spec.kind in ("optional_text", "json") and value == "":
            value = None
        if (
            value is not None
            and col_spec.validator is not None
            and col_spec.kind not in ("boolean", "json")
        ):
            try:
                value = col_spec.validator(value)
            except ValueError as exc:
                raise DBAdminError(f"{key}: {exc}") from exc
        if col_spec.kind == "select" and col_spec.choices is not None and value not in col_spec.choices:
            raise DBAdminError(f"{key}: must be one of {list(col_spec.choices)}")
        if value is not None:
            try:
                value = _coerce_value(table.columns[key], col_spec, value)
            except ValueError as exc:
                raise DBAdminError(f"{key}: {exc}") from exc
        validated[key] = value

    if not validated:
        return get_row(session, table_name, row_id)

    result = session.execute(
        sa.update(table).where(pk == row_id).values(**validated).returning(*table.columns)
    )
    row = result.first()
    if row is None:
        raise DBAdminError(f"no row in {table_name!r} with {pk.name}={row_id!r}")
    session.flush()
    return _redact_row(table_name, _row_to_dict(table, row))


def delete_row(session: Session, table_name: str, row_id: str) -> None:
    table = get_table(table_name)
    pk = _pk_column(table, table_name)
    result = session.execute(sa.delete(table).where(pk == row_id))
    if result.rowcount == 0:
        raise DBAdminError(f"no row in {table_name!r} with {pk.name}={row_id!r}")
    session.flush()
