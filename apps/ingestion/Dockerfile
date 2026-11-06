# Multi-stage build for the makhzan ingestion worker (Arq).
# Build context is the repo ROOT (see docker-compose*.yml) so the monorepo layout
# is preserved and the makhzan-schemas path dependency resolves.
#
#   dev  target -> source mounted by compose
#   prod target -> baked source, non-root
# This image also carries the Alembic migrations (packages/schemas), so the prod
# "migrate" one-shot service reuses it.

# --- base: poetry + dependencies -------------------------------------------- #
FROM python:3.12-slim AS base

ENV POETRY_VERSION=2.4.0 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_HOME=/opt/poetry \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Poetry gets its own interpreter, and the application keeps the system one.
#
# They must not share a site-packages. `POETRY_VIRTUALENVS_CREATE=false` puts the
# project's dependencies wherever Poetry itself is running, so resolving the lock
# rewrites Poetry's own dependency tree while Poetry is using it. Poetry 2.x
# pulls in anyio via httpx and does not pin it; the day that floated to 4.15.1
# while both locks pinned 4.14.2, `poetry install` downgraded the anyio it was
# running on, pip left a half-removed `~nyio-4.15.1.dist-info` behind, and the
# next uninstall died scanning it — with no change on our side at all.
# Isolating Poetry means the lock decides the app's environment and nothing else
# is in it. With `virtualenvs.create=false` Poetry installs into the *base*
# interpreter its own venv was built from — /usr/local here — not into that venv,
# so the app lands exactly where it did before and the CMDs are unaffected.
# Verified against Poetry 2.4.0; do not "fix" this by setting VIRTUAL_ENV, which
# would redirect the app's install into a venv the CMDs do not use.
# Only the `poetry` entry point is exposed, by symlink rather than by putting
# $POETRY_HOME/bin on PATH — that directory also holds a `python` and a `pip`,
# which would shadow the system ones for every later step.
RUN python -m venv "$POETRY_HOME" \
    && "$POETRY_HOME/bin/pip" install --no-cache-dir "poetry==${POETRY_VERSION}" \
    && ln -s "$POETRY_HOME/bin/poetry" /usr/local/bin/poetry

WORKDIR /workspace
COPY packages/schemas ./packages/schemas
COPY apps/ingestion/pyproject.toml apps/ingestion/poetry.lock* ./apps/ingestion/

WORKDIR /workspace/apps/ingestion
RUN poetry install --no-interaction --no-ansi --no-root

# The image carries only config/sources.example.toml, never real suppliers: this
# image is built from the public repository. A deployment mounts its private
# configuration and points MAKHZAN_SOURCES / MAKHZAN_CROSSWALKS at it (see
# docker-compose.prod.yml); unset, they fall back to the example.

# --- dev -------------------------------------------------------------------- #
FROM base AS dev
COPY config /workspace/config
COPY apps/ingestion /workspace/apps/ingestion
RUN poetry install --no-interaction --no-ansi
CMD ["arq", "worker.main.WorkerSettings"]

# --- prod ------------------------------------------------------------------- #
FROM base AS prod
COPY config /workspace/config
COPY apps/ingestion /workspace/apps/ingestion
RUN poetry install --no-interaction --no-ansi \
    && groupadd --system app && useradd --system --gid app --home /workspace app \
    && chown -R app:app /workspace
USER app
CMD ["arq", "worker.main.WorkerSettings"]
