# managed-agents-x

**Managed-agents product surface** — the designated home for CRUD on agent definitions, system-prompt versioning, drafts/templates, A/B tests, analytics, and Anthropic sync. Sibling service to [`ops-engine-x`](https://github.com/benjamincrane/ops-engine-x) (the routing/orchestration layer).

Currently a **deployable skeleton**: Dockerfile + Doppler secret injection + Railway config + the minimum FastAPI surface needed to prove the deploy path green. No managed-agents business logic yet — that lands after Railway comes up clean.

Deployed to Railway. Secrets come from Doppler (project `managed-agents-x`).

## What this service is

- **Health + diagnostics** — `GET /health` (public liveness), `GET /admin/status` (authenticated secret-load probe).
- **Service identity** — `GET /` returns `{"service":"managed-agents-x","status":"ok"}`.
- **Future scope (not yet implemented)** — `/agents*` CRUD, `/agents/*/defaults`, `/admin/sync/anthropic`, system-prompt versioning, drafts/templates, A/B tests, analytics. These will be moved in from `ops-engine-x`'s preserved-for-extraction block.

## What this service is NOT

- Not an event-routing service. Event routing, the `event_routes` table, and `/sessions/from-event` all live in `ops-engine-x`.
- Not the inbound webhook surface for any domain service.

## Architecture

- **Runtime**: Python 3.12, FastAPI, uvicorn
- **Secrets**: Doppler (project `managed-agents-x`, config `prd`) is the single source of truth
- **Deployment**: Railway builds the `Dockerfile`; the only Railway env var is `DOPPLER_TOKEN`
- **Secret injection**: the container runs `doppler run -- uvicorn ...`, which fetches and injects all Doppler secrets at process start

The app is designed to boot successfully even with zero secrets configured. Any feature that needs a secret reads it lazily via `app.config.require("...")` and fails clearly at call time if the secret is missing.

## Secret contract

The canonical list of secrets lives in [`app/config.py`](app/config.py). No `.env` or `.env.example` is maintained in this repo — Doppler is the source of truth.

Secrets this project **does** expect:

| Name | Required | Notes |
| ---- | -------- | ----- |
| `MAGS_INTERNAL_BEARER_TOKEN` | required (boot) | Static shared bearer for **internal server-to-server** callers. Gates `POST /internal/agents/{agent_id}/invoke` (`ops-engine-x` posts here once it has resolved an event to an agent). The **same value must exist in `ops-engine-x`'s Doppler `prd` config** (also as `MAGS_INTERNAL_BEARER_TOKEN`) so its outbound call authenticates. Validated at process startup — the app will refuse to boot if missing. |
| `AUX_JWKS_URL` | required (boot) | JWKS endpoint of `auth-engine-x`. Used by `app/auth/jwt.py` to verify EdDSA JWTs presented by operator-facing callers (HQ frontend, admin tooling). Inherited from the `shared-services` Doppler base. |
| `AUX_ISSUER` | required (boot) | Expected `iss` claim on inbound operator JWTs. Inherited from `shared-services`. |
| `AUX_AUDIENCE` | required (boot) | Expected `aud` claim on inbound operator JWTs. |
| `ANTHROPIC_MANAGED_AGENTS_API_KEY` | required (when Anthropic code paths land) | Anthropic API key scoped to the managed-agents product. **Lives here**, not in `ops-engine-x`. `managed-agents-x` is the designated holder of Anthropic credentials for the platform. |
| `MAGS_DB_URL_POOLED` | required (when DB code paths run) | Postgres DSN using Supabase's transaction pooler. This is what the app uses at runtime. |
| `MAGS_DB_URL_DIRECT` | optional (reserved) | Direct Postgres connection string. Reserved for future migration scripts; not read by the app at runtime. |
| `MAGS_SUPABASE_URL` | optional (reserved) | Reserved. |
| `MAGS_SUPABASE_SERVICE_ROLE_KEY` | optional (reserved) | Reserved. |
| `MAGS_SUPABASE_ANON_KEY` | optional (reserved) | Reserved. |
| `MAGS_SUPABASE_PUBLISHABLE_KEY` | optional (reserved) | Reserved. |
| `MAGS_SUPABASE_PROJECT_REF` | optional (reserved) | Supabase project ref slug. |

Secrets this project **does NOT expect** (deliberate):

- `OPEX_AUTH_TOKEN` — lives in the `ops-engine-x` Doppler config. If `managed-agents-x` ever needs to call `ops-engine-x`, a dedicated outbound credential will be added here then.

## Local development

Install the Doppler CLI once:

```bash
brew install dopplerhq/cli/doppler
doppler login
```

Scope this directory to the `managed-agents-x` project, `prd` config:

```bash
cd /path/to/managed-agents-x
doppler setup   # select project: managed-agents-x, config: prd
```

Doppler project scope is stored in `~/.doppler/.doppler.yaml` keyed by directory — it is **not** tracked in the repo. Run `doppler setup` once per clone.

Your shell may, however, inherit `DOPPLER_TOKEN` / `DOPPLER_PROJECT` / `DOPPLER_CONFIG` / `DOPPLER_ENVIRONMENT` from a home-directory default. Those env vars override the per-directory scope, so a naive `doppler run` from this repo would silently hit the wrong project. Two ways to deal with it — pick one:

**Option A — use the wrapper (zero install, recommended):**

```bash
./scripts/doppler run -- uvicorn app.main:app --reload --port 8080
./scripts/doppler secrets
```

The wrapper strips the four shadowing env vars before exec'ing `doppler`.

**Option B — use direnv (auto-strips on `cd`):**

```bash
brew install direnv
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc  # or bash/fish equivalent
direnv allow .
# Now `doppler run -- ...` works directly inside this directory.
```

`.envrc` is already in the repo; it's inert if direnv isn't installed.

Install Python deps and run:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./scripts/doppler run -- uvicorn app.main:app --reload --port 8080
```

Smoke test:

```bash
curl localhost:8080/health    # {"status":"ok"}
curl localhost:8080/          # {"service":"managed-agents-x","status":"ok"}
curl -H "Authorization: Bearer $OPERATOR_JWT" localhost:8080/admin/status
# → {"service":"managed-agents-x","status":"ok","secrets_loaded":{...}}
#
# /admin/status requires an operator JWT (auth-engine-x session token).
# The `/internal/*` surface uses MAGS_INTERNAL_BEARER_TOKEN instead.
```

You can also smoke the container locally without Doppler (the entrypoint falls back to plain uvicorn):

```bash
docker build -t managed-agents-x .
docker run --rm -p 8080:8080 managed-agents-x
# [entrypoint] DOPPLER_TOKEN not set; starting uvicorn without secret injection.
curl localhost:8080/health    # {"status":"ok"}
```

## Railway deployment

1. Connect the GitHub repo to a new Railway service.
2. In Doppler, generate a service token scoped to the `managed-agents-x` project, `prd` config.
3. In Railway → Variables, set a single variable: `DOPPLER_TOKEN` = (that token).
4. Deploy. Railway builds the Dockerfile and runs the entrypoint.

`railway.toml` configures the Dockerfile build, `/health` healthcheck, and `on_failure` restart policy (max 3 retries, 30s healthcheck timeout).

## Adding a new secret

1. Add it to the Doppler `prd` config of the `managed-agents-x` project.
2. Add a typed field to `Settings` in `app/config.py`.
3. At the call site that needs it, use `require("new_secret_name")` (or a FastAPI `Depends()` factory — see `app/deps.py` for the pattern).
4. Add a row to the secrets table above.
5. Redeploy (Railway will pick up the new value on next boot via `doppler run --`).
