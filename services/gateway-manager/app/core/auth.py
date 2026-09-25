"""Shared-secret auth for the Gateway Manager's API.

This service is restricted and internal-only (see
docs/security-boundaries.md) — the Control Plane is its only caller, and
every non-health endpoint requires this header to match
GATEWAY_MANAGER_SHARED_SECRET.
"""

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_shared_secret(x_gateway_secret: str = Header(default="")) -> None:
    # Constant-time: this is the only auth gate on this internal service,
    # so a plain `!=` (which short-circuits on the first differing byte)
    # would leak a timing side-channel an attacker could use to recover the
    # shared secret byte-by-byte.
    if not hmac.compare_digest(x_gateway_secret, settings.gateway_manager_shared_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid or missing gateway secret")
