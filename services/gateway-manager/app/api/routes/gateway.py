import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.auth import require_shared_secret
from app.services import nginx_manager
from app.services.nginx_manager import InvalidAppSlug

router = APIRouter(dependencies=[Depends(require_shared_secret)])

# These three fields are rendered directly into Nginx config text
# (app.conf.j2, autoescape=False — Nginx has no generic escaping mechanism,
# so a strict character allow-list is the actual fix). Without this, a
# hostname/path/host containing `;`, `{`, `}`, `#` or a newline could inject
# arbitrary directives (a rogue `location`/`server` block, SSRF via
# `proxy_pass`, arbitrary file exposure via `alias`) into the one shared
# Nginx instance every application shares — exactly what the "deliberately
# restricted, no arbitrary config" design this service documents is meant
# to prevent. See docs/security-boundaries.md.
_HOSTNAME_RE = re.compile(r"^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
_UNIX_PATH_RE = re.compile(r"^/[A-Za-z0-9_./-]+$")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


def _no_traversal(path: str) -> str:
    if ".." in path.split("/"):
        raise ValueError("path must not contain '..' segments")
    return path


class DomainSpec(BaseModel):
    hostname: str = Field(min_length=1, max_length=255, pattern=_HOSTNAME_RE.pattern)
    cert_path: str = Field(min_length=1, max_length=1000, pattern=_UNIX_PATH_RE.pattern)
    key_path: str = Field(min_length=1, max_length=1000, pattern=_UNIX_PATH_RE.pattern)

    @field_validator("cert_path", "key_path")
    @classmethod
    def _no_traversal(cls, value: str) -> str:
        return _no_traversal(value)


class UpstreamTarget(BaseModel):
    host: str = Field(min_length=1, max_length=255, pattern=_HOST_RE.pattern)
    port: int = Field(ge=1, le=65535)


class ReloadRequest(BaseModel):
    app_slug: str = Field(min_length=1, max_length=63)
    domains: list[DomainSpec] = Field(default_factory=list)
    upstreams: list[UpstreamTarget] = Field(default_factory=list)


class ReloadResponse(BaseModel):
    ok: bool
    message: str


@router.post("/reload", response_model=ReloadResponse)
def reload_gateway(payload: ReloadRequest) -> ReloadResponse:
    """Render this application's Nginx server block from Control-Plane-
    supplied state (existing CRT/KEY paths, currently healthy instance
    addresses), validate it with `nginx -t`, and reload the one central
    Nginx if valid — restoring the previous working config on any failure.

    Only ever writes inside the dedicated managed directory and only ever
    runs the fixed `nginx -t` / `nginx -s reload` argument lists — never a
    shell command and never Control-Plane-supplied config text. See
    docs/security-boundaries.md.
    """
    try:
        outcome = nginx_manager.apply(
            payload.app_slug,
            [d.model_dump() for d in payload.domains],
            [u.model_dump() for u in payload.upstreams],
        )
    except InvalidAppSlug as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReloadResponse(ok=outcome.ok, message=outcome.message)
