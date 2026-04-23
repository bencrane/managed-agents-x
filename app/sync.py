"""Initial-backfill + idempotent resync of Anthropic Managed Agents into our DB.

Run as CLI:
    doppler run -- python -m app.sync

Or trigger via authenticated endpoint: POST /admin/sync/anthropic
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, asdict
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app import anthropic_client
from app.db import connect

log = logging.getLogger("app.sync")


@dataclass
class SyncSummary:
    seen: int = 0
    created: int = 0
    updated: int = 0       # new version inserted (content changed)
    unchanged: int = 0     # same content_hash, only last_synced_at bumped
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ----- Hashing --------------------------------------------------------------

# Fields that define the "content" of an agent version. If any of these change,
# we insert a new agent_versions row. Timestamps and the `version` counter are
# intentionally excluded — Anthropic bumps version/updated_at on every write,
# even if the payload is byte-identical (it isn't, in practice, but be safe).
_HASHED_FIELDS = (
    "name",
    "description",
    "system",
    "model",
    "tools",
    "skills",
    "mcp_servers",
    "metadata",
    "archived_at",
)


def content_hash(agent: dict) -> str:
    subset = {k: agent.get(k) for k in _HASHED_FIELDS}
    canonical = json.dumps(subset, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ----- Upsert helpers -------------------------------------------------------

def _model_fields(agent: dict) -> tuple[str, str]:
    model = agent.get("model") or {}
    if isinstance(model, str):
        return model, "standard"
    return model.get("id", ""), model.get("speed", "standard") or "standard"


def _upsert_agent(cur: psycopg.Cursor, agent: dict) -> bool:
    """Insert or update the agents row. Returns True if this is a brand-new agent."""
    model_id, model_speed = _model_fields(agent)
    cur.execute(
        """
        insert into agents (
            id, name, description, model_id, model_speed,
            anthropic_version, anthropic_created_at, anthropic_updated_at,
            archived_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (id) do update set
            name = excluded.name,
            description = excluded.description,
            model_id = excluded.model_id,
            model_speed = excluded.model_speed,
            anthropic_version = excluded.anthropic_version,
            anthropic_updated_at = excluded.anthropic_updated_at,
            archived_at = excluded.archived_at,
            updated_at = now()
        returning (xmax = 0) as inserted
        """,
        (
            agent["id"],
            agent["name"],
            agent.get("description"),
            model_id,
            model_speed,
            agent["version"],
            agent["created_at"],
            agent["updated_at"],
            agent.get("archived_at"),
        ),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def _latest_pulled_hash(cur: psycopg.Cursor, agent_id: str) -> str | None:
    cur.execute(
        """
        select content_hash
        from agent_versions
        where agent_id = %s and source = 'anthropic_pull'
        order by created_at desc
        limit 1
        """,
        (agent_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _insert_version(cur: psycopg.Cursor, agent: dict, c_hash: str) -> str:
    model_id, model_speed = _model_fields(agent)
    cur.execute(
        """
        insert into agent_versions (
            agent_id, anthropic_version, source,
            name, description, model_id, model_speed, system_prompt,
            tools, skills, mcp_servers, metadata,
            raw, content_hash,
            anthropic_created_at, anthropic_updated_at, archived_at,
            created_by
        )
        values (%s, %s, 'anthropic_pull',
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                'system')
        on conflict (agent_id, anthropic_version, source) do update set
            content_hash = excluded.content_hash,
            raw = excluded.raw
        returning id
        """,
        (
            agent["id"],
            agent["version"],
            agent["name"],
            agent.get("description"),
            model_id,
            model_speed,
            agent.get("system"),
            Jsonb(agent.get("tools", [])),
            Jsonb(agent.get("skills", [])),
            Jsonb(agent.get("mcp_servers", [])),
            Jsonb(agent.get("metadata", {})),
            Jsonb(agent),
            c_hash,
            agent["created_at"],
            agent["updated_at"],
            agent.get("archived_at"),
        ),
    )
    return cur.fetchone()[0]


def _set_active_version(cur: psycopg.Cursor, agent_id: str, version_id: str, content_hash_: str) -> None:
    cur.execute(
        """
        update agents
           set active_version_id = %s,
               last_synced_at = now(),
               last_anthropic_pull_hash = %s
         where id = %s
        """,
        (version_id, content_hash_, agent_id),
    )


def _touch_synced(cur: psycopg.Cursor, agent_id: str, c_hash: str) -> None:
    cur.execute(
        "update agents set last_synced_at = now(), last_anthropic_pull_hash = %s where id = %s",
        (c_hash, agent_id),
    )


# ----- Public entrypoint ----------------------------------------------------

def sync_from_anthropic(include_archived: bool = True) -> SyncSummary:
    """Pull every agent from Anthropic and reconcile into the DB."""
    summary = SyncSummary()

    with connect() as conn:
        for agent in anthropic_client.list_agents(include_archived=include_archived):
            summary.seen += 1
            try:
                with conn.transaction():
                    with conn.cursor() as cur:
                        is_new = _upsert_agent(cur, agent)
                        c_hash = content_hash(agent)
                        prev_hash = _latest_pulled_hash(cur, agent["id"])

                        if prev_hash == c_hash and not is_new:
                            _touch_synced(cur, agent["id"], c_hash)
                            summary.unchanged += 1
                        else:
                            version_id = _insert_version(cur, agent, c_hash)
                            _set_active_version(cur, agent["id"], version_id, c_hash)
                            if is_new:
                                summary.created += 1
                            else:
                                summary.updated += 1
            except Exception as exc:  # noqa: BLE001
                msg = f"{agent.get('id')}: {exc}"
                log.exception("sync failure: %s", msg)
                summary.errors.append(msg)

    log.info("sync complete: %s", summary.as_dict())
    return summary


# ----- CLI ------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    summary = sync_from_anthropic()
    print(json.dumps(summary.as_dict(), indent=2))


if __name__ == "__main__":
    main()
