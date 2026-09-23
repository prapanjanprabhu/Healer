from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import require_shared_secret
from app.services import nginx_manager
from app.services.nginx_manager import InvalidAppSlug

router = APIRouter(dependencies=[Depends(require_shared_secret)])


class DomainSpec(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    cert_path: str = Field(min_length=1)
    key_path: str = Field(min_length=1)


class UpstreamTarget(BaseModel):
    host: str = Field(min_length=1)
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
