"""Stage credential isolation — SECURITY S-4 / SPEC FR-6.

The ingestion entrypoint must fail fast if deploy or cloud credentials are present in its
environment. The threat (SECURITY T-5) is credential bleed between stages: an offline
corpus job inheriting the deploy role, so that a bug in a PDF parser is reachable from
credentials that can change infrastructure. Ingestion needs a database URL and outbound
HTTPS to two regulators. It never needs to deploy anything.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from app.ingest.errors import CredentialBleedError

#: Environment variables whose presence means a deploy or cloud identity is in scope.
#:
#: Only true secrets and credential *locations* are listed. Region and profile selectors
#: (`AWS_REGION`, `AWS_DEFAULT_REGION`, `AWS_PROFILE`) are deliberately absent: they carry
#: no authority on their own, and a guard that fires on harmless configuration gets
#: switched off rather than fixed.
#:
#: `GITHUB_TOKEN` is also deliberately absent. GitHub Actions injects it into every job
#: unconditionally, so including it would make this guard fail every CI run that touched
#: ingestion — and a guard that cries wolf is removed, not obeyed. Deploy authority on
#: GitHub is carried by the PATs and OIDC roles named in SECURITY.md S-14, not by the
#: ambient job token.
DEPLOY_CREDENTIAL_VARS: frozenset[str] = frozenset(
    {
        # AWS (the cloud chosen at §10.1)
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_SECURITY_TOKEN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        # Google Cloud
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GCLOUD_SERVICE_KEY",
        "GCP_SA_KEY",
        # Azure
        "AZURE_CLIENT_SECRET",
        "AZURE_CREDENTIALS",
        # PaaS and IaC
        "FLY_API_TOKEN",
        "FLY_ACCESS_TOKEN",
        "HEROKU_API_KEY",
        "RENDER_API_KEY",
        "VERCEL_TOKEN",
        "DIGITALOCEAN_ACCESS_TOKEN",
        "DIGITALOCEAN_TOKEN",
        "TF_API_TOKEN",
        # Cluster and registry access
        "KUBECONFIG",
        "DOCKER_PASSWORD",
        "REGISTRY_PASSWORD",
    }
)


def find_deploy_credentials(env: Mapping[str, str] | None = None) -> list[str]:
    """Return the sorted names of deploy credentials present in `env`.

    A variable set to the empty string does not count as present. CI systems routinely
    declare a variable with no value when a secret is unavailable to a given job, and
    treating that as a credential would make the guard fire where there is no authority
    at all. Names only are ever returned — never values (SECURITY S-2).
    """
    source: Mapping[str, str] = os.environ if env is None else env
    return sorted(name for name in DEPLOY_CREDENTIAL_VARS if source.get(name, "").strip())


def assert_no_deploy_credentials(env: Mapping[str, str] | None = None) -> None:
    """Raise `CredentialBleedError` if any deploy credential is in the environment.

    Called first by the CLI, before the database connection and before any network call,
    so that the process exits non-zero having touched nothing.
    """
    found = find_deploy_credentials(env)
    if found:
        raise CredentialBleedError(
            "refusing to ingest with deploy credentials in the environment "
            f"({', '.join(found)}). Ingestion is an offline stage and must not hold "
            "deploy authority (SECURITY.md S-4, SPEC.md FR-6). Unset these and re-run."
        )
