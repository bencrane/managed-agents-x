"""CRUD helpers for the agent_defaults table.

Stores per-agent default session config (environment_id + vault_ids) used when
external triggers (e.g. cal.com bookings) spin up a session for an agent.
No FK to upstream Anthropic agents — orphans are fine and simply never resolve.
"""

from __future__ import annotations

from typing import TypedDict

from app.db import connect


class AgentDefaults(TypedDict):
    agent_id: str
    environment_id: str
    vault_ids: list[str]
    task_instruction: str | None


_COLS = "agent_id, environment_id, vault_ids, task_instruction"


def _row_to_dict(row) -> AgentDefaults:
    return {
        "agent_id": row[0],
        "environment_id": row[1],
        "vault_ids": list(row[2] or []),
        "task_instruction": row[3],
    }


def get(agent_id: str) -> AgentDefaults | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"select {_COLS} from agent_defaults where agent_id = %s",
            (agent_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def list_all() -> list[AgentDefaults]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"select {_COLS} from agent_defaults order by agent_id")
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def upsert(
    agent_id: str,
    environment_id: str,
    vault_ids: list[str],
    task_instruction: str | None = None,
) -> AgentDefaults:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                insert into agent_defaults (agent_id, environment_id, vault_ids, task_instruction)
                values (%s, %s, %s, %s)
                on conflict (agent_id) do update set
                    environment_id = excluded.environment_id,
                    vault_ids = excluded.vault_ids,
                    task_instruction = excluded.task_instruction,
                    updated_at = now()
                returning {_COLS}
                """,
                (agent_id, environment_id, vault_ids, task_instruction),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


def delete(agent_id: str) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from agent_defaults where agent_id = %s", (agent_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted
