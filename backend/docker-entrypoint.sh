#!/usr/bin/env bash
# CashU backend container entrypoint.
#
# app.py calls db.create_all() and run_all_seeders() at import time, so the
# container must not start gunicorn until MySQL is actually accepting
# connections — otherwise the first boot dies on a refused socket. Compose's
# depends_on/healthcheck covers the common case; this is the belt-and-braces
# for `docker run` and for a MySQL that is slow to finish its own init.
set -euo pipefail

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-3306}"
WAIT_TIMEOUT="${DB_WAIT_TIMEOUT:-60}"

if command -v nc >/dev/null 2>&1; then
    echo "[entrypoint] waiting for MySQL at ${DB_HOST}:${DB_PORT} (timeout ${WAIT_TIMEOUT}s)..."
    waited=0
    until nc -z "${DB_HOST}" "${DB_PORT}" 2>/dev/null; do
        if [ "${waited}" -ge "${WAIT_TIMEOUT}" ]; then
            echo "[entrypoint] MySQL not reachable after ${WAIT_TIMEOUT}s — starting anyway." >&2
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done
    [ "${waited}" -lt "${WAIT_TIMEOUT}" ] && echo "[entrypoint] MySQL is up (waited ${waited}s)."
fi

echo "[entrypoint] starting: $*"
exec "$@"
