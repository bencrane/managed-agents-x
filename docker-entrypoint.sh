#!/bin/sh
# Entrypoint for managed-agents-x.
#
# In production (Railway), DOPPLER_TOKEN is set and secrets are injected
# via `doppler run --` from the `managed-agents-x` Doppler project. If
# DOPPLER_TOKEN is not set (e.g. local `docker run` without a token), the
# container still boots — the app tolerates missing secrets at startup.
# This keeps the "app launches without knowing what is in Doppler"
# guarantee intact even at the container layer.

set -e

PORT="${PORT:-8080}"

if [ -n "${DOPPLER_TOKEN:-}" ]; then
  exec doppler run -- uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
else
  echo "[entrypoint] DOPPLER_TOKEN not set; starting uvicorn without secret injection." >&2
  exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
fi
