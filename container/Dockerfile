# The refresh container: the Python pipeline plus Node + wrangler for the publish stage.
# Build context is the repo root (orchestrator/wrangler.toml sets image_build_context = "..").
# Config (config/*.yml, seed/) is baked in at build time, so a config change takes effect
# when the orchestrator is next deployed.
FROM python:3.12-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g wrangler@4 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY pipeline ./pipeline
RUN uv sync --frozen --no-dev --no-cache
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

COPY site/package.json site/package-lock.json ./site/
RUN cd site && npm ci
COPY . .

EXPOSE 8080
CMD ["python", "-u", "container/server.py"]
