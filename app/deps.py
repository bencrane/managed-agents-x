"""FastAPI inbound auth dependencies.

Two distinct gates:

- `require_internal_bearer` — static shared bearer (`MAGS_INTERNAL_BEARER_TOKEN`)
  for server-to-server callers (`ops-engine-x` invoking agents). No JWT,
  no DB.
- `get_current_auth` — EdDSA JWT verified against `auth-engine-x`'s JWKS,
  for operator-facing routes (HQ frontend, admin tooling).

Both fail closed: missing or malformed `Authorization` header → 401. The
strict-startup contract in `app.config` guarantees the underlying secrets
are present, so request-time 503s for unconfigured auth are not possible.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.auth.context import AuthContext, InternalContext
from app.auth.jwt import decode_session_token
from app.config import settings


def _extract_bearer(authorization: str | None) -> str | None:
    """Pull the token out of `Authorization: Bearer <token>`. None if malformed."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def require_internal_bearer(
    authorization: str | None = Header(default=None),
) -> InternalContext:
    """Static-bearer gate for internal server-to-server callers.

    Validates the `Authorization` header against `MAGS_INTERNAL_BEARER_TOKEN`
    using a constant-time comparison. Returns an `InternalContext` marker;
    no identity is attached because the shared-secret model can't tell
    callers apart.
    """
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    if not secrets.compare_digest(token, settings.mags_internal_bearer_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal bearer token",
        )
    return InternalContext()


def get_current_auth(
    authorization: str | None = Header(default=None),
) -> AuthContext:
    """JWT gate for operator-facing routes.

    Verifies an EdDSA session JWT issued by `auth-engine-x` and returns an
    `AuthContext` populated from the token's claims. No DB enrichment —
    managed-agents-x has no users table of its own.
    """
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    payload = decode_session_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
        )

    raw_scope = payload.get("scope", [])
    if isinstance(raw_scope, str):
        scopes = tuple(s for s in raw_scope.split() if s)
    else:
        scopes = tuple(raw_scope)

    return AuthContext(
        subject=payload["sub"],
        token_type=payload["type"],
        org_id=payload.get("org_id"),
        role=payload.get("role"),
        scopes=scopes,
    )
