"""EdDSA JWT verification against the `auth-engine-x` JWKS endpoint.

Mirrors the outbound-engine-x pattern (`src/auth/jwt.py`): one shared
`PyJWKClient` with a 5-minute key cache, two decode helpers (session + M2M)
that share a private `_decode_token` core enforcing required claims and the
expected `type` claim.

JWKS URL, issuer, and audience come from `app.config.settings` and are
required at app boot — see `app.config` for the strict-startup contract.
"""

from __future__ import annotations

import jwt
from jwt import PyJWKClient

from app.config import settings

# Required claims on every token. `type` is checked separately by
# `_decode_token` because PyJWT's `require` only enforces presence of the
# standard registered claims.
_REQUIRED_CLAIMS = ["exp", "sub"]

# 5-minute JWKS cache (per directive). PyJWKClient handles refresh on miss.
_JWKS_CACHE_LIFESPAN_SECONDS = 300

_jwks_client = PyJWKClient(
    settings.auth_jwks_url,
    cache_jwk_set=True,
    lifespan=_JWKS_CACHE_LIFESPAN_SECONDS,
)


def _decode_token(token: str, expected_type: str) -> dict | None:
    """Verify `token` against JWKS and confirm the `type` claim matches.

    Returns the decoded payload on success, or `None` for any verification
    failure (expired, bad signature, wrong issuer/audience, missing required
    claim, wrong `type`). Callers translate `None` into a 401.
    """
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["EdDSA"],
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.PyJWTError:
        return None

    if payload.get("type") != expected_type:
        return None
    return payload


def decode_session_token(token: str) -> dict | None:
    """Decode an operator session JWT (`type=session`)."""
    return _decode_token(token, "session")


def decode_m2m_token(token: str) -> dict | None:
    """Decode a service-to-service M2M JWT (`type=m2m`)."""
    return _decode_token(token, "m2m")
