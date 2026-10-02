.DEFAULT_GOAL := help
SHELL := /bin/bash
TS := $(shell date -u +%Y%m%dT%H%M%SZ)

.PHONY: help setup dev test lint typecheck secret-scan eval load deploy destroy verify-setup down \
	gold-lint gold-pin gold-review gold-stats eval-quick eval-gate eval-baseline \
	serve bench \
        migrate migrate-status migrate-down ingest ingest-dry ingest-status ingest-verify

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

setup: verify-setup  ## alias for verify-setup (installs nothing; verifies the environment)

dev:  ## start local services + the API with reload
	docker compose up -d
	uv run uvicorn app.main:app --reload --port 8000

down:  ## stop local services
	docker compose down

migrate:  ## apply pending SQL migrations (uses MIGRATION_DATABASE_URL = owner role)
	uv run python scripts/migrate.py up

migrate-status:  ## show applied / pending / drifted migrations; changes nothing
	uv run python scripts/migrate.py status

migrate-down:  ## revert migrations above TO= (e.g. make migrate-down TO=0)
	@test -n "$(TO)" || { echo "refusing: set TO=<version>, e.g. make migrate-down TO=0"; exit 2; }
	uv run python scripts/migrate.py down --to $(TO)

ingest:  ## ingest the corpus into Postgres (idempotent; a re-run writes nothing)
	uv run python -m app.ingest run

ingest-dry:  ## extract, chunk and embed the corpus but write nothing
	uv run python -m app.ingest run --dry-run

ingest-status:  ## row counts for documents, versions and chunks
	uv run python -m app.ingest status

gold-lint:  ## validate the gold set against EVAL_PROTOCOL.md (no database required)
	uv run python -m app.evals.goldset lint

gold-pin:  ## re-resolve every gold item's citation IDs from its evidence quotes (E-7)
	uv run python -m app.evals.goldset pin

gold-review:  ## E-6 pass 2: check each item's key points are grounded in its own quotes
	uv run python -m app.evals.goldset review

gold-stats:  ## gold set composition, without touching the corpus or the model
	uv run python -m app.evals.goldset stats --no-resolve

ingest-verify:  ## re-check every stored chunk's offsets against its source document (FR-7)
	uv run python -m app.ingest verify

test:  ## run the test suite
	uv run pytest -q

lint:  ## ruff check + format check
	uv run ruff check .
	uv run ruff format --check .

typecheck:  ## mypy over app/
	uv run mypy app

secret-scan:  ## gitleaks over the FULL git history
	gitleaks git --redact --verbose .

eval:  ## retrieval eval over the gold set -> evals/reports/<UTC-ts>/{results.json,report.md}
	uv run python -m app.evals.runner

eval-quick:  ## same, but only the first 20 gold items (smoke test, not a baseline)
	uv run python -m app.evals.runner --limit 20 --report-dir /tmp/docscout-eval-quick

serve:  ## run the API on :8000 (loads the model once at startup)
	uv run uvicorn app.api.app:app --host 0.0.0.0 --port 8000 --workers 1

bench:  ## measure e2e latency, cache effect and cost per 1k against a running API
	uv run python scripts/bench_api.py --n 200 --concurrency 4

eval-gate:  ## fail if the newest run regressed >1pp vs the last three baselines (E-12)
	uv run python -m app.evals.gate

eval-baseline:  ## accept the newest run into evals/baselines/ as a comparison point
	uv run python -m app.evals.gate --accept

load:  ## k6 load test -> loadtests/reports/<ts>/
	@mkdir -p loadtests/reports/$(TS)
	k6 run --summary-export=loadtests/reports/$(TS)/summary.json loadtests/smoke.js \
	  | tee loadtests/reports/$(TS)/k6-stdout.txt
	@echo "report: loadtests/reports/$(TS)/"

deploy:  ## deploy to staging   [stub — deploy phase]
	@echo "STUB. Follow skill deploy-protocol before implementing:"
	@echo "  - dedicated account, cost cap + billing alarm configured FIRST"
	@echo "  - least-privilege runtime identity (no admin)"
	@echo "  - record image digest + IaC hash to docs/deploys/<ts>.md"
	@echo "  - make destroy must be tested before anything outlives a dev session"
	@exit 1

destroy:  ## tear down ALL cloud resources   [stub — deploy phase]
	@echo "STUB. Must remove: compute, registry images, log groups, secrets, roles, networking."
	@echo "Verify with provider list commands and record empty output as evidence."
	@exit 1

verify-setup:  ## run the V1-V17 environment verification matrix
	@bash scripts/verify_setup.sh
