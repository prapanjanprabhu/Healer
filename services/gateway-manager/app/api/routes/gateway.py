from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import require_shared_secret

router = APIRouter(dependencies=[Depends(require_shared_secret)])


@router.post("/reload")
def reload_gateway() -> dict:
    """Render Nginx config from current state and reload it.

    Not implemented in Phase 1 — this endpoint is a placeholder that
    establishes the contract (the Control Plane is the only caller, over the
    internal network, authenticated by a shared secret). Real template
    rendering and `nginx -s reload` land with deployment behavior in a later
    phase.
    """
    raise HTTPException(
        status_code=501,
        detail="gateway reload is not implemented in Healer V1 Phase 1",
    )
