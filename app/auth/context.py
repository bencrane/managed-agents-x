"""Identity context dataclasses returned by inbound auth dependencies.

Kept deliberately thin compared to outbound-engine-x: managed-agents-x has no
users / orgs tables of its own, so contexts are populated from JWT claims
without a follow-up DB lookup.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuthContext:
    """Identity context built from an `auth-engine-x` JWT.

    Populated entirely from token claims — no DB enrichment. `org_id` is
    optional because some token types (e.g. operator session tokens issued
    before tenanting lands in MAGS, or future super-admin tokens) may carry
    no org scope.
    """

    subject: str                              # `sub` claim
    token_type: str                           # `type` claim ("session", "m2m", ...)
    org_id: str | None = None                 # `org_id` claim, if present
    role: str | None = None                   # `role` claim, if present
    scopes: tuple[str, ...] = ()              # `scope` claim (space- or list-form)


@dataclass(frozen=True)
class InternalContext:
    """Marker context for the static-bearer internal-caller surface.

    Returned by `require_internal_bearer`. Carries no identity beyond "the
    caller knows the shared secret"; concrete caller attribution lives in
    request logs / Doppler ownership of `MAGS_INTERNAL_BEARER_TOKEN`.
    """

    caller: str = "internal"
