# Contributing to DocScout

Thank you for your interest in contributing to DocScout. We welcome contributions from developers, compliance professionals, and regulatory systems engineers.

DocScout is built around core architectural invariants:
1. **Citations are the product, not a feature:** An answer without an authoritative, resolvable citation is a failure.
2. **Corpus text is untrusted data:** Third-party PDFs must never modify system instructions. Strict delimiter discipline and canary defenses apply repository-wide.
3. **Measured, not asserted:** Every quality and performance claim must be substantiated by committed evaluation artifacts.
4. **Clean typography and content standards:** All contributions must strictly avoid forbidden promotional vocabulary and adhere to repository quality gates.

---

## Code of Conduct

All contributors and participants are expected to uphold our [Code of Conduct](CODE_OF_CONDUCT.md). Please report any unacceptable behavior to compliance-alerts@docscout.gov.in.

---

## Getting Started

### Prerequisites

- **Python:** 3.12.14 (pinned in `pyproject.toml`)
- **Package Manager:** `uv` (version >= 0.12)
- **Container Engine:** Docker and Docker Compose (or native PostgreSQL 18.6 with pgvector 0.8.6)
- **Git & Pre-commit:** Git version control with `pre-commit` installed

### Initial Repository Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/shivanshjain456/DocScout.git
   cd DocScout
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   ```

3. **Install dependencies:**
   ```bash
   uv sync --frozen
   ```

4. **Install pre-commit hooks:**
   ```bash
   uv run pre-commit install
   ```

5. **Start local backing services:**
   ```bash
   docker compose up -d db
   ```

6. **Apply database migrations:**
   ```bash
   make migrate
   ```

7. **Run local ingestion (idempotent):**
   ```bash
   make ingest
   ```

8. **Start development API server:**
   ```bash
   make dev
   ```
   The API will be available at `http://localhost:8000`, with interactive docs at `http://localhost:8000/docs`.

---

## Development Workflow & Quality Gates

Every code change must pass all repository quality gates before being merged.

### 1. Code Formatting and Linting

We enforce strict formatting and linting via Ruff:

```bash
# Check formatting
make lint
# Or run individually:
uv run ruff check .
uv run ruff format --check .
```

### 2. Strict Type Checking

Mypy is configured in strict mode over both application code and test suites:

```bash
make typecheck
# Strict checking over app and tests:
uv run mypy app tests
```

### 3. Automated Test Suite

Run the full automated test suite using pytest:

```bash
make test
```

### 4. Differential Patch Coverage Gate

DocScout enforces **100% test coverage on newly introduced or modified lines** in `app/`:

```bash
make diff-coverage
```

### 5. Mutation Score Ratcheting

Ensure test assertions are robust against AST code mutations:

```bash
make test-mutation
```

### 6. Evaluation Regression Gate

Verify that retrieval accuracy (Recall@5, MRR, nDCG@5) does not regress against the committed gold set v2.0.0:

```bash
make eval-gate
```

### 7. Content Quality Assurance Gate

Repository gates strictly enforce:
- Zero forbidden promotional vocabulary across all files.

Verify compliance:
```bash
uv run python scripts/qa_content_gate.py
```

### 8. Secret Scanning

Ensure no credentials or sensitive tokens are committed:

```bash
make secret-scan
```

---

## Architectural Decision Records (ADRs)

If your contribution introduces an architectural change, new dependency, data model alteration, or modifies a public interface, an Architecture Decision Record (ADR) must be created in `docs/decisions/` following the established numbering convention and template:
- Template: `docs/decisions/0000-template.md`
- Sequential naming: `docs/decisions/XXXX-short-title.md`

---

## Submitting Pull Requests

1. **Create a topic branch:**
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. **Make focused, atomic commits:** Follow conventional commit format (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`).
3. **Run local pre-commit checks:** Confirm all hooks pass without `--no-verify`.
4. **Push your branch and open a PR:** Use the provided [Pull Request Template](.github/pull_request_template.md).
5. **CI Verification:** Ensure all 5 GitHub Actions workflows (`quality`, `secrets`, `supply-chain`, `deploy-smoke`, `eval-gate`) pass green.

---

## Security Disclosures

Please do NOT report security vulnerabilities via public GitHub issues. See our [Security Policy](SECURITY.md) for confidential reporting procedures.
