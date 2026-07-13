# Delivery Lifecycle

The skill is a quality control plane for the whole project lifecycle. It may
generate and run controls, create project scaffolding, and block completion or
release claims when evidence is insufficient.

## Maturity Levels

Maturity is cumulative. A project cannot skip a level, and a higher-level
claim requires every applicable control from all lower levels to pass.

| Level | Meaning | Minimum outcome |
|---|---|---|
| `prototype` | experimentation only | scope and risks are visible; no production claim |
| `engineering_ready` | normal development can be trusted | requirements, owners, CI, static checks, and tests are traceable |
| `production_ready` | users/operators can run it safely | product acceptance, SLOs, capacity, observability, recovery, install/upgrade/rollback |
| `commercial_ready` | it can be distributed and supported | legal, supply chain, signed/verifiable artifacts, support lifecycle, UX/a11y/i18n |
| `regulated_ready` | selected jurisdiction/industry obligations are met | regulatory overlay and required independent evidence |

## Development Modes

Product type and development mode are separate axes.

```text
DevelopmentMode:
  ai_greenfield:
  ai_brownfield:
  human_greenfield:
  human_brownfield:
```

- AI-led greenfield: generate the complete quality skeleton before feature work.
- AI-led brownfield: run one quality-convergence campaign in independently
  verified phases; do not use one unreviewable big-bang change.
- Human greenfield: establish the skeleton early, with owner-controlled
  sequencing and strict claim semantics.
- Human brownfield: migrate by module and quality dimension while the global
  readiness claim remains blocked. Feature work may continue only when its
  affected controls pass and it introduces no new debt.

Assessment scope is independent: any development mode may select `full_repo`
or `subproject`; subproject scope explicitly marks the rest unassessed.

Known debt remains a failure. Migration work may complete when it verifiably
reduces debt, but the project cannot claim the target maturity until all
applicable controls pass.

## Control Status

Only `PASS` satisfies a required control.

| Status | Meaning |
|---|---|
| `PASS` | executed against current evidence and satisfied |
| `FAIL` | executed and not satisfied |
| `BLOCKED` | applicable, but environment/authority/external dependency is unavailable |
| `TODO` | identified but not implemented or executed |
| `NOT_APPLICABLE` | profile decision says the control does not apply, with rationale |
| `DISPUTED` | independent audits disagree |
| `STALE` | evidence predates relevant code/config/artifact changes |

`BLOCKED`, `TODO`, `DISPUTED`, and `STALE` block the associated maturity claim.
`NOT_APPLICABLE` is allowed only after an explicit profile decision; it is not
an automatic fallback for missing infrastructure.

## Claim Policy

```text
QualityClaim:
  claim:
  scope:
  target_maturity:
  commit:
  artifact_digests:
  applicable_controls:
  passing_controls:
  blocking_controls:
  audit_stages:
  expires_at:
```

- Codex must refuse completion, release, or readiness claims when a required
  applicable control is not `PASS`.
- Progress pressure never changes a control result.
- No residual-risk waiver can convert a failed applicable control into pass.
- A subproject assessment cannot be promoted to a whole-project claim.
- Paid services, secrets, production systems, privileged/root execution, and
  remote mutations require separate user authorization.

## Task vs Project Completion

A debt-removal or framework-adoption task can be complete while the project is
still `not_ready`. The task claim must say what scope was improved and must not
imply project or release readiness.

Human brownfield feature work may use a task claim only when all affected
controls pass in every required audit stage and measured debt does not grow.
Project claims never accept a selected control subset.
