# Project Profiles

Use this reference to classify a repository before writing rules.

## Profile Record

```text
ProjectProfile:
  project_type:
  primary_users:
  runtime:
  criticality:
  data_sensitivity:
  trust_boundaries:
  release_model:
  deployment_model:
  existing_ci:
  acceptance_surface:
```

## Project Types

| Type | Primary risk | Guardrail emphasis | Product acceptance |
|---|---|---|---|
| Library / SDK | API stability, compatibility, examples, fuzzable input | semver, public API, docs, downstream tests | consumer integration |
| Web app | auth, privacy, UX, data consistency | OWASP, a11y, contracts, migrations, E2E | browser workflow |
| CLI / developer tool | filesystem safety, flags, exit codes, reproducibility | golden tests, config, install/update | real command workflow |
| Backend service | reliability, API contract, observability, migrations | SLO, contract, authz, rate limit, rollback | staging/integration scenario |
| Infrastructure / platform | rollback, idempotency, secrets, cloud permissions | IaC policy, drift, least privilege, incident readiness | deploy/rollback verification |
| Security product | fail-open/fail-closed, negative tests, tamper evidence | threat model, enforcement, audit, real-stack | allow/deny/degraded product path |
| AI agent system | tool boundary, data leakage, human approval, auditability | tool contract, policy, evals, scenario origin | real agent session/tool call |
| Data platform | lineage, schema evolution, retention, cost/perf | schema contracts, quality checks, backfill safety | data freshness/accuracy |
| Mobile app | permissions, offline behavior, store release | device matrix, privacy, crash-free, signing | device user journey |
| Embedded / edge | ABI, hardware, OTA, resource budgets | HIL, rollback, signed firmware, resource tests | device-level scenario |

## Profile Overlays

Apply overlays when a project has the feature, even if it is not the primary project type.

| Overlay | Add these rule families | Typical hard evidence |
|---|---|---|
| Policy/rules engine | Policy source of truth, parameter flow, performance budget | owner engine tests, no parallel interpreters, indexed matching |
| Secrets/credentials | Secret lifecycle, security/privacy, audit integrity | encrypted-at-rest proof, no plaintext persistence, reload/rotation tests |
| Proxy/gateway/protocol adapter | Runtime/protocol integrity, resilience, product acceptance | protocol completion, flush/backpressure, timeout, negative tests |
| Kernel/device/privileged runtime | Runtime constraints, failure semantics, manual signoff | build/verifier/HIL/root runner evidence, no silent mock fallback |
| Consumer security product | Product/profile fit, failure semantics, real-stack acceptance | allow/deny/degraded user workflow, audit chain, safe fallback matrix |
| AI agent boundary | Tool boundary, policy source of truth, scenario origin fidelity | real agent session, approval path, tool-call audit |
| Release artifact producer | Supply chain/release, version truth, rollback | SBOM, provenance/checksum/signature, install/upgrade verification |
| Regulated or privacy-sensitive data | Privacy, retention, deletion/export, threat model | data classification, retention tests, redaction checks |

## Product Paradigm Fit

Before adding rules, define the actual user and product interaction model:

- consumer/local products prioritize understandable prompts, safe defaults, degraded visibility, and low learning cost;
- enterprise/SOC products can prioritize alert triage, fleet policy, and investigation workflows;
- libraries prioritize public contract stability and downstream behavior over UI acceptance;
- infrastructure prioritizes idempotent deploy/rollback and least-privilege cloud permissions;
- AI agent systems prioritize tool-boundary fidelity and scenario origin.

Do not transfer a rule across paradigms unless the acceptance surface is also transferred.

## Criticality Scale

| Level | Meaning | Minimum gates |
|---|---|---|
| Low | internal utility, no sensitive data | format, lint, unit, dependency inventory |
| Medium | user-facing or business workflow | required CI, contract/e2e, migration checks |
| High | money, privacy, security, infrastructure | threat model, negative tests, supply-chain gate, rollback |
| Critical | safety/security boundary, kernel/device/regulated | real-stack/product acceptance, signed/verifiable artifacts, manual signoff |

## Classification Warnings

- Do not apply enterprise SOC/EDR assumptions to a consumer/local product unless the product profile requires it.
- Do not apply web-app UX gates to a library except docs/examples.
- Do not claim release signing for source-only packages unless artifacts are produced.
- Do not count mock tests as product acceptance for security, mobile, embedded, infrastructure, or AI agent products.
