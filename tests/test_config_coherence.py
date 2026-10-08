"""The three provisioning paths must agree on what they provision.

This repository provisions PostgreSQL three ways: `scripts/dev_db_native.sh` (the default,
no Docker), `docker-compose.yml` (where a daemon exists), and the `eval-gate` job in CI.
Every published number was measured on one specific pairing, so if the three disagree a
reviewer following the documented path gets a database the baselines were not measured on.

They did disagree. Until 2026-10-02 compose pinned `pgvector/pgvector:0.8.2-pg18` while the
native script and CI both installed 0.8.6 — the exact reproducibility failure this project
otherwise defends carefully. A comment cannot prevent that from happening again; a failing
build can.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The pairing every published number was measured on.
EXPECTED_PGVECTOR = "0.8.6"
EXPECTED_PG_MAJOR = "18"


def read(relative: str) -> str:
    path = REPO_ROOT / relative
    if not path.is_file():  # pragma: no cover - a missing file is another test's job
        pytest.skip(f"{relative} not present")
    return path.read_text(encoding="utf-8")


#: Deliberately a regex rather than a YAML parse. PyYAML is not a declared dependency of
#: this project -- it is present only transitively via huggingface_hub -- and importing it
#: here would be an undeclared dependency in the test suite. The `check-yaml` pre-commit
#: hook already guarantees both files are valid YAML, and the one field needed is a single
#: pinned image line, so a parser buys nothing a pattern does not.
_IMAGE = re.compile(r"^\s*image:\s*(pgvector/pgvector:\S+)", re.MULTILINE)


def images_in(relative: str) -> list[str]:
    return _IMAGE.findall(read(relative))


def compose_db_image() -> str:
    images = images_in("docker-compose.yml")
    assert len(images) == 1, f"expected one pgvector image in compose, found {images}"
    return images[0]


def ci_db_image() -> str:
    images = images_in(".github/workflows/ci.yml")
    assert len(images) == 1, f"expected one pgvector image in ci.yml, found {images}"
    return images[0]


@pytest.mark.parametrize("image_of", [compose_db_image, ci_db_image], ids=["compose", "ci"])
def test_images_pin_the_measured_pairing(image_of: object) -> None:
    image = image_of()  # type: ignore[operator]
    assert image.startswith("pgvector/pgvector:"), image
    tag = image.split(":", 1)[1]
    assert EXPECTED_PGVECTOR in tag, f"{image} does not pin pgvector {EXPECTED_PGVECTOR}"
    assert f"pg{EXPECTED_PG_MAJOR}" in tag, f"{image} does not pin PostgreSQL {EXPECTED_PG_MAJOR}"


def test_compose_and_ci_pin_the_same_image() -> None:
    """Not merely both valid — identical, so neither can drift alone."""
    assert compose_db_image() == ci_db_image()


def test_image_tag_is_fully_qualified() -> None:
    """A bare `pg18` tag moves the extension version without any file here changing."""
    tag = compose_db_image().split(":", 1)[1]
    assert re.match(r"^\d+\.\d+\.\d+-pg\d+", tag), (
        f"tag {tag!r} does not pin an exact pgvector version"
    )


def test_native_script_installs_the_same_postgres_major() -> None:
    """The script templates its package names off PG_VERSION, so assert on that."""
    script = read("scripts/dev_db_native.sh")
    assert re.search(rf"^PG_VERSION=[\"']?{EXPECTED_PG_MAJOR}[\"']?\s*$", script, re.MULTILINE), (
        f"dev_db_native.sh does not pin PG_VERSION={EXPECTED_PG_MAJOR}"
    )
    assert 'postgresql-$PG_VERSION"' in script or "postgresql-$PG_VERSION" in script
    assert "postgresql-$PG_VERSION-pgvector" in script


def test_both_paths_execute_the_same_initdb_scripts() -> None:
    """Compose mounts infra/initdb; the native script executes the same files.

    If one path grew its own bootstrap SQL the two databases would differ in roles or
    extensions while both appeared to work.
    """
    compose = read("docker-compose.yml")
    assert "./infra/initdb:/docker-entrypoint-initdb.d" in compose
    script = read("scripts/dev_db_native.sh")
    for initdb_file in sorted((REPO_ROOT / "infra" / "initdb").iterdir()):
        assert initdb_file.name in script, (
            f"{initdb_file.name} is mounted by compose but never executed by the native script"
        )


def test_compose_declares_no_service_the_application_cannot_use() -> None:
    """A container nothing connects to is scaffolding presented as architecture.

    Redis was declared here and never used: `REDIS_URL` is configured for a future
    multi-worker deployment, but the cache and rate limiter are in-process today.
    """
    compose = read("docker-compose.yml")
    # Scope to the `services:` block. A bare two-space-indent pattern also matches volume
    # names (`  pgdata:` under `volumes:`), which are not services and are not expected to
    # appear in application source.
    block = re.search(r"^services:\n(.*?)(?=^\S|\Z)", compose, re.MULTILINE | re.DOTALL)
    assert block is not None, "docker-compose.yml has no services: block"
    services = re.findall(r"^  ([a-z][a-z0-9_-]*):$", block.group(1), re.MULTILINE)
    assert services, "no services parsed out of docker-compose.yml"
    app_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (REPO_ROOT / "app").rglob("*.py")
    )
    for service in services:
        if service == "db":
            continue  # reached via DATABASE_URL, not by service name
        assert service in app_source, (
            f"compose starts a {service!r} service that nothing in app/ connects to"
        )


def test_compose_api_service_shares_the_db_contract() -> None:
    """The deploy artifact must not fork the datastore pairing (P0-4)."""
    compose = read("docker-compose.yml")
    assert "build:" in compose and "Dockerfile" in compose, (
        "compose has no api service built from Dockerfile"
    )
    assert "condition: service_healthy" in compose, (
        "api must wait for db healthy, not just db started"
    )
    assert "@db:5432/docscout" in compose, (
        "api DATABASE_URL must address the compose `db` host, not localhost"
    )
    for secret in ("DOCSCOUT_API_KEY=", "DB_PASSWORD=", "DB_APP_PASSWORD="):
        assert secret not in compose, (
            f"compose must interpolate {secret.rstrip('=')} from .env, not hardcode it"
        )


def test_dockerfile_pins_base_digest() -> None:
    """A bare tag lets the base move underneath the baselines without a diff here."""
    dockerfile = read("Dockerfile")
    m = re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE)
    assert m is not None, "Dockerfile has no FROM line"
    assert "@sha256:" in m.group(1), f"FROM {m.group(1)!r} is not digest-pinned"
    assert "python:3.12" in m.group(1), f"FROM {m.group(1)!r} is not Python 3.12"


def test_dockerfile_uses_frozen_sync_nonroot_healthcheck() -> None:
    """Deployability must not weaken reproducibility or runtime hygiene (P0-4 bar)."""
    dockerfile = read("Dockerfile")
    assert "uv sync --frozen" in dockerfile, "image must install from the frozen lock"
    assert "--no-dev" in dockerfile or "--no-group dev" in dockerfile, (
        "runtime image must exclude dev-only packages"
    )
    assert re.search(r"^USER\s+(?!root)", dockerfile, re.MULTILINE), (
        "image must drop to a non-root user"
    )
    assert "HEALTHCHECK" in dockerfile and "/healthz" in dockerfile, (
        "image must carry a HEALTHCHECK against /healthz"
    )
    assert "HF_HOME" in dockerfile and "hf-cache" in dockerfile, (
        "model cache must be an explicit path/volume, not a silent boot download"
    )
    for secret in ("DOCSCOUT_API_KEY", "DB_PASSWORD", "DB_APP_PASSWORD", "OPENAI_API_KEY"):
        assert secret not in dockerfile, f"Dockerfile must not mention {secret}"


def test_dockerignore_excludes_env_and_caches() -> None:
    """Secrets must not enter a layer; caches must not bloat the context."""
    dockerignore = read(".dockerignore")
    assert ".env" in dockerignore, ".dockerignore must exclude .env"
    assert ".git/" in dockerignore, ".dockerignore must exclude .git/"


def test_entrypoint_addresses_are_coherent() -> None:
    """One story: Makefile dev + AGENTS.md must name the runnable object (P1-4)."""
    makefile = read("Makefile")
    agents = read("AGENTS.md")
    assert "app.api.app:app" in makefile, "Makefile must reference app.api.app:app"
    assert "app.main:app" not in makefile, "Makefile must not reference dead app.main:app"
    assert "app.api.app:app" in agents, "AGENTS.md must reference app.api.app:app"
    assert "app.main:app" not in agents, "AGENTS.md must not reference dead app.main:app"
