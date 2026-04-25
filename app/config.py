"""Secret contract for the application.

This file is the canonical list of environment variables the app expects.
Values are injected at runtime by `doppler run --` (via the Doppler CLI in
the container) from the Doppler project `managed-agents-x`, config `prd`.

Two tiers of secrets:

1. **Strict-startup, required at boot.** Loaded as `Settings.*_required`
   fields and validated immediately when this module is imported. Boot fails
   loudly if any are missing. These cover the inbound auth surface — there
   is no useful operating mode without them.

   - `MAGS_INTERNAL_BEARER_TOKEN` — static bearer for internal callers
     (e.g. `ops-engine-x` → `POST /internal/agents/{agent_id}/invoke`).
   - `AUX_JWKS_URL`, `AUX_ISSUER`, `AUX_AUDIENCE` — JWT verification config
     pointing at `auth-engine-x`.

2. **Lazy, tolerant.** Optional or feature-scoped secrets. Missing values
   only fail when the call site that needs them runs (`require()` below).
   These keep `/health` green when feature credentials are absent.

   - `ANTHROPIC_MANAGED_AGENTS_API_KEY` — Anthropic managed-agents key.
   - `MAGS_DB_URL_POOLED` / `MAGS_DB_URL_DIRECT` — Postgres DSNs.
   - `MAGS_SUPABASE_*` — reserved for future use.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # ----- Strict-startup, required ----------------------------------------
    # These are validated at module import (see the `Settings()` call below).
    # If any are missing, the process fails to boot.

    mags_internal_bearer_token: str = Field(..., alias="MAGS_INTERNAL_BEARER_TOKEN")
    auth_jwks_url: str = Field(..., alias="AUX_JWKS_URL")
    auth_issuer: str = Field(..., alias="AUX_ISSUER")
    auth_audience: str = Field(..., alias="AUX_AUDIENCE")

    # ----- Lazy, optional --------------------------------------------------

    anthropic_managed_agents_api_key: str | None = None

    mags_db_url_pooled: str | None = None
    mags_db_url_direct: str | None = None

    mags_supabase_url: str | None = None
    mags_supabase_service_role_key: str | None = None
    mags_supabase_anon_key: str | None = None
    mags_supabase_publishable_key: str | None = None
    mags_supabase_project_ref: str | None = None


# Strict-startup validation: pydantic raises ValidationError here if any of
# the required fields above are missing from the environment. We do NOT
# catch — the process should fail to boot with a clear traceback identifying
# the missing variable, rather than 503-ing every authenticated request.
settings = Settings()


class MissingSecretError(RuntimeError):
    """Raised when a lazy/optional secret required by a code path is unset."""


def require(name: str) -> str:
    """Fetch a lazy secret by attribute name, raising a clear error if unset.

    Use at the call site of any feature backed by a tier-2 (optional) secret,
    e.g. `key = require("anthropic_managed_agents_api_key")`. Tier-1 secrets
    (auth) are already guaranteed by startup validation and don't need this.
    """
    value = getattr(settings, name, None)
    if not value:
        raise MissingSecretError(
            f"Required secret '{name.upper()}' is not set. "
            "Confirm it exists in Doppler (project: managed-agents-x, "
            "config: prd) and that DOPPLER_TOKEN is valid."
        )
    return value
