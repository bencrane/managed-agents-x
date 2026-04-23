"""managed-agents-x — FastAPI entrypoint.

Product surface for managed agents. Wraps Anthropic's managed-agents API and
adds per-agent default config (environment_id + vault_ids + task_instruction)
plus a DB-backed mirror of agent state with version history.

The app must boot successfully with zero secrets configured. Any feature that
requires a secret reads it lazily via `app.config.require(...)` (or via the
relevant FastAPI `Depends()`), so `/health` stays green even when Doppler is
unreachable or individual secrets are unset.

Inbound auth is `MAG_AUTH_TOKEN` (bearer), checked via
`app.deps.require_mag_auth`. The `require_admin_token` alias on the same
module is used by handlers ported from ops-engine-x.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime  # noqa: F401  (imported per port spec; used by future handlers)

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import agent_defaults as agent_defaults_store
from app.anthropic_client import get_agent, list_agents
from app.config import settings
from app.deps import require_admin_token, require_mag_auth
from app.sync import sync_from_anthropic


# ----- Pydantic models ------------------------------------------------------

class AgentDefaultsPayload(BaseModel):
    environment_id: str = Field(..., min_length=1)
    vault_ids: list[str] = Field(default_factory=list)
    task_instruction: str | None = Field(
        default=None,
        description=(
            "Optional per-agent kickoff preamble prepended to the user.message "
            "sent when /sessions/from-event fires. Use this to give the agent "
            "a short, durable job description that sits above the event payload."
        ),
    )


class AgentDefaults(BaseModel):
    agent_id: str
    environment_id: str
    vault_ids: list[str]
    task_instruction: str | None = None


class AgentDefaultsList(BaseModel):
    data: list[AgentDefaults]
    count: int


class DeleteResult(BaseModel):
    deleted: bool


# ----- App ------------------------------------------------------------------

app = FastAPI(
    title="managed-agents-x",
    version="0.1.0",
    description=(
        "Managed-agents product surface. Wraps Anthropic's managed-agents API "
        "and stores per-agent defaults plus version history. Future home of "
        "CRUD, system-prompt versioning, drafts/templates, A/B tests, and "
        "analytics. All non-public routes require a bearer MAG_AUTH_TOKEN."
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

    Reports which configured secrets Doppler has successfully injected. Values
    are never returned, only presence booleans. Useful immediately after a
    deploy or DOPPLER_TOKEN rotation to verify the process actually loaded
    what you expect.
    """
    return {
        "service": "managed-agents-x",
        "status": "ok",
        "secrets_loaded": {
            "mag_auth_token": bool(settings.mag_auth_token),
            "anthropic_api_key": bool(settings.anthropic_api_key),
            "supabase_db_url": bool(settings.supabase_db_url),
        },
    }


# ----- Anthropic passthrough error helper -----------------------------------

def _passthrough_upstream_error(exc: httpx.HTTPStatusError) -> JSONResponse:
    try:
        body = exc.response.json()
    except ValueError:
        body = {"detail": exc.response.text or "Upstream Anthropic error"}
    return JSONResponse(status_code=exc.response.status_code, content=body)


# ----- Admin sync -----------------------------------------------------------

@app.post("/admin/sync/anthropic", dependencies=[Depends(require_admin_token)])
def admin_sync_anthropic() -> dict[str, object]:
    """Pull all managed agents from Anthropic and reconcile into the DB."""
    return sync_from_anthropic().as_dict()


# ----- Agent defaults (DB-backed) -------------------------------------------
#
# NOTE: `/agents/defaults` MUST be registered before `/agents/{agent_id}` so
# the literal-path route wins over the path-param route. Starlette matches in
# declaration order.

@app.get(
    "/agents/defaults",
    dependencies=[Depends(require_admin_token)],
    response_model=AgentDefaultsList,
)
def list_agent_defaults() -> AgentDefaultsList:
    """List every agent_defaults row (frontend merges with /agents client-side)."""
    rows = agent_defaults_store.list_all()
    return AgentDefaultsList(data=[AgentDefaults(**r) for r in rows], count=len(rows))


@app.get(
    "/agents/{agent_id}/defaults",
    dependencies=[Depends(require_admin_token)],
    response_model=AgentDefaults,
)
def get_agent_defaults(agent_id: str) -> AgentDefaults:
    row = agent_defaults_store.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No defaults configured for this agent")
    return AgentDefaults(**row)


@app.put(
    "/agents/{agent_id}/defaults",
    dependencies=[Depends(require_admin_token)],
    response_model=AgentDefaults,
)
def put_agent_defaults(agent_id: str, payload: AgentDefaultsPayload) -> AgentDefaults:
    row = agent_defaults_store.upsert(
        agent_id,
        payload.environment_id,
        payload.vault_ids,
        payload.task_instruction,
    )
    return AgentDefaults(**row)


@app.delete(
    "/agents/{agent_id}/defaults",
    dependencies=[Depends(require_admin_token)],
    response_model=DeleteResult,
)
def delete_agent_defaults(agent_id: str) -> DeleteResult:
    deleted = agent_defaults_store.delete(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No defaults configured for this agent")
    return DeleteResult(deleted=True)


# ----- Anthropic passthrough (live reads) -----------------------------------

@app.get("/agents", dependencies=[Depends(require_admin_token)], response_model=None)
def get_agents() -> JSONResponse | dict[str, object]:
    """List all managed agents (live passthrough to Anthropic, paginated server-side)."""
    try:
        agents = list(list_agents())
    except httpx.HTTPStatusError as exc:
        return _passthrough_upstream_error(exc)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc}") from exc
    return {"data": agents, "count": len(agents)}


@app.get("/agents/{agent_id}", dependencies=[Depends(require_admin_token)], response_model=None)
def get_agent_by_id(agent_id: str) -> JSONResponse | dict:
    """Single agent (live passthrough to Anthropic)."""
    try:
        return get_agent(agent_id)
    except httpx.HTTPStatusError as exc:
        return _passthrough_upstream_error(exc)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc}") from exc
