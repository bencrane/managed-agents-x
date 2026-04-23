"""managed-agents-x — FastAPI entrypoint.

Skeleton service. Boots with zero secrets configured; authenticated routes
fail clearly at call time if their required secret is missing. Future home
of the managed-agents product surface (/agents CRUD, system-prompt
versioning, drafts/templates, A/B tests, Anthropic sync).
"""

from __future__ import annotations

from fastapi import Depends, FastAPI

from app.config import settings
from app.deps import require_mag_auth

app = FastAPI(
    title="managed-agents-x",
    version="0.1.0",
    description=(
        "Managed-agents product surface. Future home of /agents CRUD, "
        "system-prompt versioning, drafts/templates, A/B tests, analytics, "
        "and Anthropic sync. Currently a deployable skeleton — no business "
        "logic yet."
    ),
)


@app.get("/health")
def health() -> dict[str, str]:
    """Public liveness probe. No deps, no secrets, always 200."""
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    """Service identity probe."""
    return {"service": "managed-agents-x", "status": "ok"}


@app.get("/admin/status", dependencies=[Depends(require_mag_auth)])
def admin_status() -> dict[str, object]:
    """Authenticated secret-load probe.

    Reports which of the secrets relevant to the current skeleton surface
    are populated. Does not leak values.
    """
    return {
        "service": "managed-agents-x",
        "status": "ok",
        "secrets_loaded": {
            "mag_auth_token": bool(settings.mag_auth_token),
            "anthropic_api_key": bool(settings.anthropic_api_key),
        },
    }
