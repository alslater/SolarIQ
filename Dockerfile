FROM python:3.11-slim

# ── System dependencies ────────────────────────────────────────────────────────
# Node.js 20 LTS   – Reflex builds / serves the Next.js frontend
# coinor-cbc        – CBC MILP solver used by PuLP
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gnupg2 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends \
        nodejs \
        coinor-cbc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies ────────────────────────────────────────────────────────
# Install from the lock file so the image is reproducible.
COPY Pipfile Pipfile.lock ./
RUN pip install --no-cache-dir pipenv \
    && pipenv sync --system \
    && pip uninstall -y pipenv

# ── Application code ───────────────────────────────────────────────────────────
COPY rxconfig.py ./
COPY assets/  ./assets/
COPY solariq/ ./solariq/

# ── Reflex frontend initialisation ────────────────────────────────────────────
# `reflex init` downloads the Node.js project template and runs `npm install`.
# Doing this at image-build time avoids a slow first container startup.
RUN reflex init

# ── Runtime directories ────────────────────────────────────────────────────────
# These are overridden by volume mounts declared in docker-compose.yaml.
RUN mkdir -p /app/cache /app/logs

# Reflex: frontend on 3002, backend websocket on 8002 (matches rxconfig.py)
EXPOSE 3002 8002

# ── Entrypoint ─────────────────────────────────────────────────────────────────
# On first start Reflex compiles the Next.js frontend (~60–90 s on a Pi 4).
# Subsequent restarts reuse the compiled output and start in a few seconds.
# API_URL must be set in docker-compose so the browser JS knows where to
# reach the backend websocket (see docker-compose.yaml).
CMD ["reflex", "run", "--env", "prod", "--loglevel", "warning"]
