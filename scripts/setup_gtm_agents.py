"""Scaffold the GTM-pipeline managed agents.

Six agents in three actor+verdict pairs:

  gtm-sequence-definer       (actor)   — dex-mcp
  gtm-sequence-definer-verdict (verdict) — no MCPs
  gtm-master-strategist      (actor)   — exa, dex-mcp
  gtm-master-strategist-verdict (verdict) — no MCPs
  gtm-per-recipient-creative (actor)   — dex-mcp
  gtm-per-recipient-creative-verdict (verdict) — no MCPs

System prompts live at data/agents/<slug>/system_prompt.md and are read
at registration time. Re-running creates a new agent each time
(Anthropic doesn't dedupe by name); archive the old one on the platform
first if re-scaffolding.

Each registration prints:
  * agent_id (Anthropic-side)
  * a one-line copy/paste command for the operator to run on the hq-x
    side, populating business.gtm_agent_registry.

Usage:
  ./scripts/doppler run -- python -m scripts.setup_gtm_agents <slug>
  ./scripts/doppler run -- python -m scripts.setup_gtm_agents --all

(Project/config come from doppler.yaml at the repo root.)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from app.config import require

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROOT = REPO_ROOT / "data" / "agents"

VAULT_ID = "vlt_011CZtjQ5LjLrbAd4gX7xA6E"  # production-vault
ENVIRONMENT_ID = "env_01T3cywTrvvtZoUQYAzxMA1D"  # "all"

DEFAULT_MODEL = "claude-opus-4-7"

# Same MCP entry shape as setup_orchestrator.py — name MUST match the vault
# credential's mcp_server_url so bearer tokens inject correctly.
_MCP = {
    "exa": {"type": "url", "name": "exa", "url": "https://mcp.exa.ai/mcp"},
    "dex-mcp": {"type": "url", "name": "dex-mcp", "url": "https://dex-mcp.up.railway.app/mcp"},
}

# Autonomous: every tool call always-allowed. The verdict subagents
# don't get any MCPs at all; the actors get their listed MCPs.
_ALLOW = {"enabled": True, "permission_policy": {"type": "always_allow"}}


# slug -> (role, parent_actor_slug, mcps, model)
AGENTS: dict[str, dict] = {
    "gtm-sequence-definer": {
        "role": "actor",
        "parent_actor_slug": None,
        "mcps": ["dex-mcp"],
        "model": DEFAULT_MODEL,
        "description": (
            "Subagent #1 — economics-aware sequence definer. Reads partner "
            "contract + audience descriptor + acq-eng doctrine; outputs JSON "
            "channel mix, touch count, mailer types, delays, outlay."
        ),
    },
    "gtm-sequence-definer-verdict": {
        "role": "verdict",
        "parent_actor_slug": "gtm-sequence-definer",
        "mcps": [],
        "model": DEFAULT_MODEL,
        "description": (
            "Verdict subagent for the sequence definer — schema, mailer "
            "types, per-piece cost band, outlay cap, margin floor."
        ),
    },
    "gtm-master-strategist": {
        "role": "actor",
        "parent_actor_slug": None,
        "mcps": ["exa", "dex-mcp"],
        "model": DEFAULT_MODEL,
        "description": (
            "Subagent #7 — Master Strategy author. Synthesizes audience + "
            "partner research + brand content + doctrine into per-touch "
            "conceptual frames (NOT literal copy)."
        ),
    },
    "gtm-master-strategist-verdict": {
        "role": "verdict",
        "parent_actor_slug": "gtm-master-strategist",
        "mcps": [],
        "model": DEFAULT_MODEL,
        "description": (
            "Verdict subagent for the master strategist — schema, "
            "frame-vs-literal-copy distinction, voice loyalty, anti-fabrication."
        ),
    },
    "gtm-per-recipient-creative": {
        "role": "actor",
        "parent_actor_slug": None,
        "mcps": ["dex-mcp"],
        "model": DEFAULT_MODEL,
        "description": (
            "Subagent #11 — per-recipient creative author. Reads master "
            "strategy + recipient data + brand content; emits per-piece "
            "copy + design DSL JSON."
        ),
    },
    "gtm-per-recipient-creative-verdict": {
        "role": "verdict",
        "parent_actor_slug": "gtm-per-recipient-creative",
        "mcps": [],
        "model": DEFAULT_MODEL,
        "description": (
            "Verdict subagent for the per-recipient creative author — "
            "schema, length, zone validity, channel-tier compliance, "
            "voice loyalty, no fabrication."
        ),
    },
}


def _build_tools(mcp_names: list[str]) -> list[dict]:
    tools: list[dict] = [{"type": "agent_toolset_20260401", "default_config": _ALLOW}]
    for n in mcp_names:
        tools.append(
            {"type": "mcp_toolset", "mcp_server_name": n, "default_config": _ALLOW}
        )
    return tools


def _load_system_prompt(slug: str) -> str:
    path = AGENTS_ROOT / slug / "system_prompt.md"
    if not path.is_file():
        raise SystemExit(
            f"system_prompt.md missing for slug={slug!r} at {path}"
        )
    return path.read_text()


def create_agent(slug: str, cfg: dict) -> dict:
    system = _load_system_prompt(slug)
    body = {
        "name": slug,
        "model": cfg["model"],
        "system": system,
        "mcp_servers": [_MCP[n] for n in cfg["mcps"]],
        "tools": _build_tools(cfg["mcps"]),
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/agents",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "x-api-key": require("anthropic_managed_agents_api_key"),
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "managed-agents-2026-04-01",
            "content-type": "application/json",
        },
    )
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"create_agent({slug}) failed: {e.code} {e.read().decode()}")


def _print_register_command(slug: str, cfg: dict, agent_id: str) -> None:
    parent_arg = (
        f" --parent {cfg['parent_actor_slug']}"
        if cfg["parent_actor_slug"]
        else ""
    )
    print()
    print("hq-x register command (paste into the hq-x repo):")
    print()
    print(
        "  doppler --project hq-x --config dev run -- "
        "uv run python -m scripts.register_gtm_agent "
        f"{slug} {agent_id} {cfg['role']}{parent_arg} "
        f"--model {cfg['model']}"
    )
    print()


def _setup_one(slug: str) -> None:
    if slug not in AGENTS:
        raise SystemExit(
            f"unknown slug={slug!r}; one of: {', '.join(sorted(AGENTS))}"
        )
    cfg = AGENTS[slug]
    agent = create_agent(slug, cfg)
    print(f"agent_id:           {agent['id']}")
    print(f"name:               {agent['name']}")
    print(f"version:            {agent.get('version')}")
    print(f"model:              {agent.get('model')}")
    print(f"role:               {cfg['role']}")
    if cfg["parent_actor_slug"]:
        print(f"parent_actor_slug:  {cfg['parent_actor_slug']}")
    print(
        f"mcp_servers:        {[m['name'] for m in agent.get('mcp_servers', [])] or '(none)'}"
    )
    print(f"environment_id:     {ENVIRONMENT_ID}")
    print(f"vault_ids:          [{VAULT_ID}]")
    _print_register_command(slug, cfg, agent["id"])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("slug", nargs="?", help="agent slug to register")
    p.add_argument(
        "--all",
        action="store_true",
        help="register every agent in AGENTS (one after another)",
    )
    args = p.parse_args()

    if args.all:
        for slug in AGENTS:
            print(f"\n=== {slug} ===")
            _setup_one(slug)
        return
    if not args.slug:
        p.error("either --all or a slug is required")
    _setup_one(args.slug)


if __name__ == "__main__":
    sys.exit(main() or 0)
