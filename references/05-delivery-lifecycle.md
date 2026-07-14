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
- AI-led brownfield: run one identified quality-convergence campaign in
  independently verified phases; one campaign is a governance envelope, not
  one run, commit, pull request, or big-bang change. While it is active, allow
  only registered convergence tasks. Admit an urgent security or correctness
  fix only through an owner-approved campaign revision; do not use it as a
  general feature escape hatch.
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

Keep observations, statuses, outcomes, and claims separate:

```text
Observation
  -> ControlStatus
  -> TaskOrPhaseOutcome
  -> ProjectOrReleaseClaim
```

A task or phase may be `COMPLETED` while an applicable debt control remains
`FAIL`. Completion never writes a different control status. Project and release
claims use absolute evaluation and require every applicable control to be a
current `PASS`. Do not introduce `RATCHET_PASS` or `INHERITED_PASS` statuses;
ratchets evaluate an observation delta, and inheritance records evidence
provenance. `applies=false` excludes a control only when it is bound to an
owner-approved applicability decision with exact scope and rationale.

```text
QualityClaim:
  claim:
  scope:
  target_maturity:
  subject_binding:
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
still `not_ready`. Record a task outcome, not a task maturity claim. The outcome
must identify its affected scope and controls and must not imply project or
release readiness. Debt removal requires no new violations and measurable
reduction (`fixed>0` or closure of named controls). Inventory or framework
adoption may complete without reducing debt only when its declared inventory or
coverage exit criterion is satisfied.

An AI brownfield task must belong to the current campaign revision and a named
phase. A material change to the baseline, assessed scope, target maturity,
registry, ordering, or exit criteria requires a campaign revision and
invalidates affected outcomes.

Each registered phase and task declares `affected_control_ids`, `assessed_scope`,
and an exit policy containing `max_new_violations`,
`minimum_fixed_violations`, and `allow_open_cleanup_debt`. The registration
script binds the campaign to a pre-registration baseline over source tree,
registry, and Skill. The manifest is excluded because it stores the binding;
callers cannot supply it. Task/phase claims derive scope from the
registration instead of accepting an ad hoc control subset.

Human brownfield feature work may use a task claim only when all affected
controls pass in every required audit stage and measured debt does not grow.
Project claims never accept a selected control subset.

## Handoff Readiness

Readiness is a non-mutating derived report, not another control status or an
automatic claim:

- `DEVELOPMENT_START_READY`: profile, control plane, Skill binding, and required
  AI brownfield campaign context are usable for development;
- `TASK_CLAIM_READY`: the selected task could produce its scoped claim now;
- `MERGE_READY`: task evidence plus the applicable project PR gate could merge;
- `RELEASE_READY`: every release-scope control and audit stage could support a
  release claim now.

Each level is `READY`, `BLOCKED`, or `NOT_EVALUATED` with control IDs, blockers,
and supporting run IDs. A lower level never implies a higher level.
