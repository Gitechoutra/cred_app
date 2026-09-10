# ──────────────────────────────────────────────────────────────────────────────
# CashU — Flask backend
#
# Build:  docker build -t cashu-backend .
# Run:    docker run -p 5050:5050 --env-file .env cashu-backend
#
# Normally brought up via ../docker-compose.yml, which also starts MySQL.
# ──────────────────────────────────────────────────────────────────────────────

# ── Stage 1: build wheels ─────────────────────────────────────────────────────
# Compiling cryptography/PyMySQL needs a toolchain that the runtime image should
# not carry. Building wheels here keeps the final image slim and rootless-safe.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Kolkata

# curl is used by the HEALTHCHECK below; netcat lets the entrypoint wait on MySQL.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        netcat-openbsd \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user — a compromised Flask process should not be root.
RUN groupadd --gid 1000 cashu \
    && useradd --uid 1000 --gid cashu --create-home --shell /bin/bash cashu

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY --chown=cashu:cashu . .

# uploads/ and logs/ are written at runtime. Create them up front and hand them
# to the app user, because a bind-mounted volume otherwise lands owned by root.
RUN mkdir -p /app/portal/uploads /app/logs /app/flask_session \
    && chown -R cashu:cashu /app/portal/uploads /app/logs /app/flask_session

COPY --chown=cashu:cashu docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER cashu

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:5050/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]

# app.py runs db.create_all() + seeders at import time, so keep this to ONE
# worker on first boot to avoid concurrent CREATE TABLE races; scale with
# --workers once the schema is settled (or move seeding into the entrypoint).
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5050", \
     "--workers", "1", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
