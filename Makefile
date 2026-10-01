.DEFAULT_GOAL := help
SHELL := /bin/bash
TS := $(shell date -u +%Y%m%dT%H%M%SZ)

.PHONY: help setup dev test lint typecheck secret-scan eval load deploy destroy verify-setup down

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

setup: verify-setup  ## alias for verify-setup (installs nothing; verifies the environment)

dev:  ## start local services + the API with reload
	docker compose up -d
	uv run uvicorn app.main:app --reload --port 8000

down:  ## stop local services
	docker compose down

test:  ## run the test suite
	uv run pytest -q

lint:  ## ruff check + format check
	uv run ruff check .
	uv run ruff format --check .

typecheck:  ## mypy over app/
	uv run mypy app

secret-scan:  ## gitleaks over the FULL git history
	gitleaks git --redact --verbose .

eval:  ## full eval run -> evals/reports/<ts>/   [stub until the gold set exists]
	@echo "eval harness lands with the gold set (build phase). See skill rag-eval-protocol."
	@echo "Contract: every run writes evals/reports/<UTC-ts>/{results.json,report.md,raw-judge-outputs/}"
	uv run pytest tests/eval -q

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
