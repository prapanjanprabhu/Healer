"""What the database management dashboard (Administrator-only, phpMyAdmin-
style) is allowed to do to each table.

Every table is fully browsable, editable and deletable by default — this is
a raw Postgres admin tool, not a curated view, and every column is
auto-derived from the real SQLAlchemy schema (type, nullability, enum
choices) rather than hand-listed per table. Two narrow, purely technical
exceptions, not policy restrictions:

1. A table needs a single-column primary key to be addressed by id at all
   (`GET/PATCH/DELETE .../rows/{id}`) — `user_roles` (composite PK) is the
   only one affected, and it's still fully browsable, just not editable by
   id here.
2. Four columns (`password_hash`, `credential_hash`, `token_hash`,
   `encrypted_value`) are always redacted and never editable, because
   there's no legitimate hand-edit of a bcrypt hash or a Fernet token —
   typing a new value in only breaks login/auth for that row, it never
   produces a working credential. This is the same treatment those columns
   already get everywhere else in the app (SecretKeyOut, CommandOut).
   agent_commands.payload/result get the same structural (env-key-only)
   redaction CommandOut applies for the same reason — and are excluded from
   editing because a value the UI showed you redacted can't be saved back
   without corrupting the real one.

Everything else — including `users`, `secret_records`, `deployments`,
`audit_logs` — is fully editable and deletable. Note in particular that
making `audit_logs` editable means it's no longer a tamper-evident record
once an Administrator chooses to use this page on it; that's a deliberate
trade for full phpMyAdmin-style control, not an oversight.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable

from app.schemas.commands import _redact as redact_json

# Reused for the two columns (domains.hostname/cert_path, servers.hostname)
# that flow into the Gateway Manager's Nginx config template
# (autoescape=False — see services/gateway-manager/app/services/
# nginx_manager.py and app/schemas/healer_yaml.py, which validate the same
# shape at the normal write path). This is the one place a free-text edit
# through this admin tool could otherwise reopen that injection.
_HOSTNAME_RE = re.compile(r"^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
_UNIX_PATH_RE = re.compile(r"^/[A-Za-z0-9_./-]+$")


def _validate_hostname(value: str) -> str:
    if not _HOSTNAME_RE.match(value):
        raise ValueError("must be a valid DNS hostname (e.g. app.example.com)")
    return value


def _validate_optional_unix_path(value: str) -> str:
    if value == "":
        return value
    if not _UNIX_PATH_RE.match(value):
        raise ValueError(
            "must be an absolute path using only letters, digits, '.', '_', '-', '/'"
        )
    if ".." in value.split("/"):
        raise ValueError("must not contain '..' segments")
    return value


# Column names that are always redacted and never editable, in every table,
# regardless of anything else — a blanket rule so a future table with e.g.
# its own "password_hash" column is safe by default.
GLOBAL_SENSITIVE_COLUMNS = frozenset(
    {"password_hash", "credential_hash", "token_hash", "encrypted_value"}
)

# Structural (key-aware) redaction for specific JSON/JSONB columns — only
# values under an "env" key are masked, everything else stays visible. See
# _build_start_instance_payload in app/services/deployment_service.py.
JSON_REDACT_COLUMNS: dict[str, frozenset[str]] = {
    "agent_commands": frozenset({"payload", "result"}),
}

# (table_name, column_name) -> extra string validator, applied on top of the
# normal type coercion. Only for the couple of columns where a bad value has
# a real security consequence outside this table (see module docstring).
COLUMN_VALIDATORS: dict[tuple[str, str], Callable[[str], str]] = {
    ("servers", "hostname"): _validate_hostname,
    ("domains", "hostname"): _validate_hostname,
    ("domains", "cert_path"): _validate_optional_unix_path,
    ("domains", "key_path"): _validate_optional_unix_path,
}


@dataclasses.dataclass(frozen=True)
class EditableColumn:
    name: str
    kind: str  # "text" | "optional_text" | "select" | "boolean" | "json"
    multiline: bool = False
    choices: tuple[str, ...] | None = None
    validator: Callable[[str], str] | None = None


def validator_for(table_name: str, column_name: str) -> Callable[[str], str] | None:
    return COLUMN_VALIDATORS.get((table_name, column_name))


__all__ = [
    "EditableColumn",
    "GLOBAL_SENSITIVE_COLUMNS",
    "JSON_REDACT_COLUMNS",
    "validator_for",
    "redact_json",
]
