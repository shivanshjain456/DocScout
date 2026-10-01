---
name: deploy-protocol
description: Use this skill for ANY cloud or deployment action in DocScout - creating AWS or GCP resources, writing Terraform or Helm or Dockerfiles for deploy, configuring IAM roles or service accounts, pushing images to a registry, setting up Cloud Run or ECS or Fargate, wiring secrets managers, configuring billing alarms or cost caps, running make deploy or make destroy, exposing the demo endpoint, or granting any credential to a running service. Use it before the first deploy and before every subsequent one.
---

# Deploy protocol

Cloud is blast radius. Every rule here exists to keep an experiment from becoming an incident or a
bill.

## Preconditions (all must hold before the first deploy)

1. **Dedicated project/account only.** One AWS account or GCP project created for DocScout. Never
   deploy into a shared or personal-default project.
2. **Cost cap + billing alarm configured BEFORE the first resource exists.** AWS: budget + billing
   alarm. GCP: billing budget with a hard cap. Record the cap amount and the alert address.
3. **Least-privilege service identity.** No admin, no wildcard `*` actions, no owner role. The
   runtime identity gets exactly what it needs (pull image, read its own secrets, write its own
   logs) and nothing else. Deploy-time credentials are separate from runtime credentials.
4. **`make deploy` and `make destroy` both exist, and `destroy` has been tested** on a throwaway
   resource before anything is allowed to outlive a dev session.
5. **Staging is the only environment.** There is no prod. The demo is staging with an API key.

## Operating rules

- **Ingestion never runs with deploy credentials** in its environment (guardrail §1.2). Separate
  stage, separate identity, separate env file.
- **Secrets come from the provider's secret manager at runtime**, never baked into an image, never
  in Terraform state committed to git, never in an env literal in a committed YAML.
- **Every deploy records**: image digest (not just the tag), IaC plan hash, git SHA, timestamp,
  and the deployer. Write it to `docs/deploys/<timestamp>.md`.
- **Nothing is left running unattended.** At the end of a session, either the resource is torn down
  or there is an explicit, recorded human decision to leave it up with a cost cap.
- **The demo endpoint is API-key gated and rate-limited** from the first deploy, never "temporarily
  open".

## Teardown

`make destroy` must remove **everything** the deploy created, including the things that survive a
naive delete: registry images, log groups/buckets, secrets, service accounts/roles, and any
auto-created networking. After teardown, run the provider's list commands and record empty output
as evidence.

## Gotchas

- **`terraform destroy` leaves artifacts behind.** Registries, log retention, secret versions, and
  state buckets commonly survive. Verify with list commands, not with destroy's exit code.
- **A tag is not an identity.** `:latest` can point somewhere else tomorrow — pin and record the
  **digest**.
- **Cost caps are usually soft.** AWS budgets and GCP budget alerts *notify*; they do not reliably
  stop spend. Treat the cap as a tripwire and still check the bill.
- **Managed services bill when idle** (provisioned concurrency, min instances, NAT gateways,
  allocated IPs, idle load balancers). Set min instances to 0 where possible and check for NAT.
- **An egress-capable container with ingestion credentials is the trifecta.** Keep the deployed
  service's identity unable to reach anything it does not serve.
- **Vector indexes are expensive to rebuild.** Snapshot/export before destroying a database, or
  accept a full re-embed (which costs real money and time).
- Phase 0 creates **zero** cloud resources. If a step seems to require one, stop and report.
