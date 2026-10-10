# DocScout API image: local deploy artifact (P0-4).
#
# Reproducibility contract (must stay coherent with the measured pairing):
# - Base is Debian trixie Python 3.12, pinned by digest (retrieved 2026-10-08 from
#   Docker Hub `library/python:3.12-slim-trixie`, manifest-list digest below).
#   Re-verify with: `docker buildx imagetools inspect python:3.12-slim-trixie`.
# - Python deps come from `uv sync --frozen` against the committed 169-lock, with the
#   CPU-only torch index from `pyproject.toml` (`tool.uv.index pytorch-cpu`).
# - The datastore pairing (PostgreSQL 18.6 + pgvector 0.8.6) lives in `db`, not here;
#   this image never bundles Postgres. Triple-pin guarded by
#   `tests/test_config_coherence.py`.
# - No secret enters the image: `.env` is excluded via `.dockerignore`, no
#   `ARG`/`ENV` carries a credential, and compose supplies config at run time.
# - Model weights are handled explicitly: BGE-small (129 MB) is pre-warmed at build
#   time into `/opt/hf-cache` so first boot does not silently download; the same path
#   is a named volume at run time (`hf-cache`) so restarts reuse it. The optional
#   cross-encoder stays lazy (serving runs with `rerank=False` per ADR-0009).
# - Runtime is non-root (`app`), with a `HEALTHCHECK` against `/healthz`.
#
# Build:  docker build -t docscout:<git-sha> .
# Run:    see `docker-compose.yml` (`api` service) and `make deploy`.

FROM python:3.12-slim-trixie@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f

LABEL org.opencontainers.image.source=https://github.com/shivanshjain456/DocScout

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=0 \
    HF_HOME=/opt/hf-cache \
    HF_HUB_OFFLINE=0

# curl exists for the HEALTHCHECK only; everything else is Python. Unversioned
# deliberately: the digest-pinned base above already freezes the trixie
# snapshot, and a version pin here breaks the build when the snapshot moves
# (observed: curl=8.14.1-2 not found). Reproducibility comes from the base
# digest + `uv sync --frozen`, not from an apt version string.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app \
    && useradd -r -g app -d /app -s /usr/sbin/nologin app \
    && mkdir -p /app /opt/hf-cache \
    && chown -R app:app /app /opt/hf-cache

WORKDIR /app

# Dependency layer first for cache reuse. `.python-version` pins the interpreter;
# `uv.lock` is the frozen set `make verify-setup` V5 checks.
COPY --chown=app:app pyproject.toml uv.lock .python-version ./
RUN pip install --no-cache-dir "uv==0.12.21" \
    && uv sync --frozen --no-dev \
    && chown -R app:app /app

# Application + data needed at runtime. Corpus payloads are tracked (ADR-0001) so
# `make ingest` inside the container is offline and re-hashes against the manifest.
# `.dockerignore` excludes `.env`, `.venv`, `.git`, caches, `ui/node_modules`, reports.
COPY --chown=app:app app/ ./app/
COPY --chown=app:app config/ ./config/
COPY --chown=app:app corpus/ ./corpus/
COPY --chown=app:app migrations/ ./migrations/
COPY --chown=app:app infra/ ./infra/
COPY --chown=app:app scripts/ ./scripts/

# Pre-warm the serving embedder so model load (~13 s, ~129 MB) is a build cost,
# not a first-request latency surprise. Failure here fails the build, not the boot.
USER app
RUN uv run python -c "from app.ingest.embed import Embedder; Embedder().encode_query('warmup')" \
    && uv run python -c "from app.ingest.embed import MODEL_ID; print('warmed', MODEL_ID)"

EXPOSE 8000

# Liveness probe against the unauthenticated endpoint the balancer uses.
# Start-period covers embedder + BM25 warmup inside the lifespan handler.
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uv", "run", "uvicorn", "app.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
