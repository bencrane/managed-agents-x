"""Inbound auth for managed-agents-x.

Two distinct auth surfaces:

- `app.auth.jwt` verifies EdDSA JWTs issued by `auth-engine-x` against its
  JWKS endpoint. Used for operator-facing routes (frontend, admin tooling).
- `app.deps.require_internal_bearer` checks a static shared bearer token
  (`MAGS_INTERNAL_BEARER_TOKEN`). Used for server-to-server callers like
  `ops-engine-x` posting to `/internal/agents/{agent_id}/invoke`.
"""
