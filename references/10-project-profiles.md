# Project Profiles

Use this reference to classify a repository before writing rules.

## Contents

Profile Record; Development Modes; Assurance Responsibility; Project Types;
Profile Overlays; Product Paradigm Fit; Criticality; Classification Warnings.

## Profile Record

```text
ProjectProfile:
  project_type:
  development_mode:                # ai_greenfield | ai_brownfield | human_greenfield | human_brownfield
  distribution_model:              # open_source | private_commercial | saas | client_software | embedded
  target_market:                    # explicit; never inferred
  target_maturity:                  # prototype through regulated_ready
  assessed_scope:                   # whole_project or named subproject/path set
  ai_system:                        # true enables AI assurance overlay
  primary_users:
  runtime:
  criticality:
  data_sensitivity:
  trust_boundaries:
  release_model:
  deployment_model:
  existing_ci:
  acceptance_surface:
  ownership_model:                 # strong | weak | collective; team/domain-aligned CODEOWNERS (not folder-aligned)
```

Every field above is an explicit project decision. Repository scanning can
propose evidence, but it cannot choose market, legal applicability, maturity,
or assessment scope.

## Development Modes

| Mode | Adoption policy | Claim boundary |
|---|---|---|
| AI greenfield | create the recommended skeleton before feature work | applicable task and project controls must pass |
| AI brownfield | run one planned quality-convergence campaign in reviewable phases | no whole-project readiness until debt is cleared |
| Human greenfield | scaffold early; allow owner-led sequencing | applicable controls still determine claims |
| Human brownfield | migrate progressively while allowing scoped feature work | task may complete when scoped controls pass and debt does not grow; global readiness remains failed |

Scope is a separate axis. Any mode can assess a named subproject, but that
assessment never claims readiness for the containing product.

Known debt is never converted to `PASS`. Continued feature development in a
human brownfield project is a scope decision, not a waiver of project quality.

## Assurance Responsibility

- Open source: an independent quality agent performs cross-audit and a project
  owner acts as release authority; no fictitious external quality organization
  is required.
- Commercial: identify product, engineering, security/privacy, operations, and
  release authorities. A solo project may map these to a virtual team while
  preserving separate audit contexts.
- Regulated: add the explicitly required independent or third-party assurance.

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
