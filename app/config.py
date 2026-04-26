"""Secret contract for managed-agents-x.

Auth foundation is inherited from `aux_m2m_server.BaseAuthSettings` —
backends do not redeclare AUX_* fields. Backend-specific secrets are
declared below as either tier-1 (boot-required) or tier-2 (lazy/optional).

Tier-1 secrets — boot-required (validated by Pydantic at module import):
    AUX_JWKS_URL, AUX_ISSUER, AUX_AUDIENCE
    AUX_M2M_API_KEY, AUX_API_BASE_URL  (this backend's own M2M identity)
        — all five inherited from BaseAuthSettings.

Tier-2 secrets — lazy, fail at call site if needed but unset:
    ANTHROPIC_MANAGED_AGENTS_API_KEY  (Anthropic managed-agents key)
    MAGS_DB_URL_POOLED / MAGS_DB_URL_DIRECT  (Postgres DSNs)
    MAGS_SUPABASE_*  (reserved for future use)

Doppler project: `managed-agents-x`, config `prd`. AUX_* values are also
syncable from `shared-services` for cross-service consistency.
"""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from aux_m2m_server import BaseAuthSettings


class Settings(BaseAuthSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )

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
# the inherited AUX_* fields are missing from the environment. We do NOT
# catch — the process should fail to boot with a clear traceback identifying
# the missing variable, rather than 503-ing every authenticated request.
settings = Settings()


class MissingSecretError(RuntimeError):
    """Raised when a lazy/optional secret required by a code path is unset."""


def require(name: str) -> str:
    """Fetch a lazy secret by attribute name, raising a clear error if unset.

    Use at the call site of any feature backed by a tier-2 (optional) secret,
    e.g. `key = require("anthropic_managed_agents_api_key")`. Tier-1 secrets
    (AUX_*) are guaranteed by BaseAuthSettings's strict-startup validation.
    """
    value = getattr(settings, name, None)
    if not value:
        raise MissingSecretError(
            f"Required secret '{name.upper()}' is not set. "
            "Confirm it exists in Doppler (project: managed-agents-x, "
            "config: prd) and that DOPPLER_TOKEN is valid."
        )
    return value
