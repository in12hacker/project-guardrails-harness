# Rule Lifecycle

Rules must evolve with the project. Stale rules are architecture debt.

## Contents

Rule and Fact Maturity; Candidate Rules; Ratcheting; Module Readiness;
Baseline Semantics; Control Status and Claims; Continuous Updates; Task
Learning; Update/Delete/Drift Audits; Project Memory; Skill Promotion and
Maintenance.

## Rule Maturity Levels

| Level | Meaning | Use |
|---|---|---|
| `proposal` | plausible rule, not validated | planning |
| `advisory` | warning and inventory only | legacy discovery |
| `ratchet` | all violations fail the relevant readiness claim; baseline measures whether known debt shrinks and prevents new debt | debt convergence |
| `hard_gate` | any violation fails PR/CI | mature invariant |
| `manual_signoff` | needs human/root/device/cloud evidence | closeout/release |
| `superseded` | replaced by stronger/newer rule | historical link |
| `deleted` | obsolete and removed | no enforcement |

## Fact Maturity Levels

Project memory is not a place for guesses. Record a fact only with evidence, and label how mature it is.

| Level | Meaning | Promotion condition |
|---|---|---|
| `observed_once` | seen in one task, path, PR, incident, or scan | repeat observation or owner confirmation |
| `repeated` | seen in multiple changes or review findings | add a harness, owner, or decision |
| `verified_by_tests` | backed by a local or manual verification path | make the check stable enough for CI |
| `enforced_by_ci` | checked automatically in normal development | promote related rule to ratchet or hard gate |
| `hard_gate` | required for completion/merge/release claims | keep under stale-rule audit |
| `stale` | path, command, owner, or assumption no longer matches reality | update, supersede, or delete |

Use `decisions.md` for unresolved hypotheses. Use `memory.md` only for durable facts with code paths, evidence, and a status.

## Candidate Project Rules

`rules/candidates.md` is the bridge between generic guardrail families and a project's eventual local rules. It is not an authority file. It is a queue of evidence-backed drafts that a maintainer can accept, rewrite, split, or reject.

Use candidates when the scan or recent work suggests a project-specific invariant, but the exact wording, owner, reject condition, or runnable check still needs human validation.

```text
CandidateProjectRule:
  title:
  rule_family:
  candidate_rule:
  evidence:
    self_description:
    paths:
    existing_instruction_files:
    build_or_ci_targets:
    test_or_harness_paths:
  confidence: low|medium|high
  human_validation_required: yes
  owner_to_confirm:
  reject_if:
  verification_gap:
  promotion_path: decisions.md -> memory.md -> rules/advisory.md -> rules/hard.md
```

Promotion requirements:

- `proposal`: static scan or one coding task suggests the rule.
- `advisory`: project owner accepts the invariant and false positives are still being calibrated.
- `ratchet`: the project can measure violations and prevent new debt.
- `hard_gate`: a stable command or CI job enforces the rule with acceptable false positives.

Reject or rewrite a candidate when:

- it restates an existing project instruction instead of linking to it;
- it was inferred from keywords alone, without code paths or build/test evidence;
- the profile or owner map is still ambiguous;
- the verification command is fabricated or only proves a mock/contract surface;
- the wording contains project-specific names that belong in the generated `.guardrails/` output, not in the portable skill.

## Ratcheting And AI-Generated Code (2026)

- **Ratchet = observation-delta evaluation, not a control status.** New debt
  always fails. `new=0` proves only no regression; it does not prove debt
  closure. Known debt also fails the project maturity/release claim until fixed.
  An AI brownfield task must belong to the active campaign; ordinary feature
  work is not a task-claim escape hatch. Human brownfield policy may allow a
  scoped feature outcome when all affected controls pass and measured debt does
  not grow, without changing known violations to `PASS` or making the project
  ready.
- **Baseline = cleanup inventory, not approval (mandatory).** A baseline or allowlist must make known debt visible and measurable. It must NOT turn a detected violation into proof of acceptability. Any violation (baselined or new) must FAIL the gate; the baseline only classifies known vs new for reporting clarity. The only way to PASS is to actually fix violations. Separate design-scope exemptions (the rule truly does not apply, declared in code with a reason) from cleanup debt (the rule applies and must be fixed).
- **Turn decisions into fitness functions.** An ADR or architecture rule should be enforced, not merely documented: render it as a runnable check (a test, a static-analysis rule, an OPA policy) that fails the PR when violated. A doc claim is a hypothesis; a runnable check is evidence.
- **Verification, not approval, for AI-generated code.** Human approval does not scale against AI-generated volume; the gate is that the change satisfies spec/tests/contracts/owners, not that a human rubber-stamped it. Code Health (complexity) can flag code too tangled for safe automated refactoring.

## Module Readiness Lifecycle

Use objective readiness states when a project has multiple modules, crates, packages, services, or ownership boundaries:

```text
ModuleReadinessState:
  module:
  owner:
  status: not_ready|provisionally_ready|production_ready|stale
  readiness_dimensions:
  fitness_functions:
  exceptions:
  delete_or_review_by:
  last_verified:
```

- `not_ready`: at least one required dimension is red or unowned.
- `provisionally_ready`: gaps are known, owned, and dated.
- `production_ready`: required dimensions are green and enforced by checks or accepted manual evidence.
- `stale`: paths, commands, owners, or assumptions no longer match the repo.

Refactor pressure should cite a violated readiness dimension, owner boundary, rule, or fitness function. If no rule covers the concern, record a candidate rule or missing fitness function instead of forcing subjective churn.

## Baseline And Allowlist Semantics

Keep three records separate: `DebtObservation` reports immutable counts and
baseline/rule digests; `CleanupDebt` records an applicable violation with owner,
shrink plan, and delete-by; `DesignScopeExemption` records approved
non-applicability for exact scope with an alternative safety control and review
lifecycle. Risk acceptance is a fourth business decision and never changes a
control status.

The executable `DebtObservation` contains baseline reference, revision, source
digest, baseline/current/new/fixed counts, and the observation artifact digest.
Counts must satisfy `current = baseline - fixed + new`. An overdue open debt
blocks further task/phase outcomes until its lifecycle is reviewed. An
`applies=false` control must reference an active, unexpired
`DesignScopeExemption`; rationale text alone is insufficient.

Guidance:

- design-scope exemptions live near the code or rule with a reason;
- cleanup debt lives in a visible inventory with owner and review/delete path;
- baseline updates should normally shrink the inventory or explicitly explain a profile change;
- a baseline revision that grows debt is a regression and cannot satisfy a
  convergence task;
- new violations must fail; baselined (known) violations must also fail (the baseline is a todo list, not permission);
- a green gate with hidden growing debt is stale evidence, not maturity;
- during human brownfield transition, a separate task-scope policy may permit
  work to continue while the global debt control remains `FAIL`; once the
  baseline clears, the project-level control becomes `PASS` and the check stays
  a hard gate against regression.

## Control Status And Claims

Rule maturity describes how a rule is enforced; control status describes the
current objective result. Keep them separate.

Observation, control status, task/phase outcome, and project/release claim are
different objects. Task completion cannot write a debt control to `PASS`, and
inherited evidence cannot create a new status. A project claim remains failed
while applicable cleanup debt remains.

- `PASS` and approved `NOT_APPLICABLE` are terminal observations, but only
  `PASS` satisfies an applicable control.
- `FAIL`, `BLOCKED`, `TODO`, `DISPUTED`, and `STALE` block the associated claim.
- evidence becomes stale when its commit, scope, environment, expiry, command,
  or control definition no longer matches.
- self-audit cannot provide the independent cross-audit or release-authority
  decision required by a maturity profile.
- a stable standard update triggers applicability review and controlled
  migration; drafts may inform planning but cannot silently become mandatory.

## Federated Rule Lifecycle

Track each project-rule mapping as `current|stale|disputed|unmapped`. A source
digest change makes it stale until review. A same-tier or semantic-owner
conflict makes it disputed and blocks the affected claim. An unmapped mandatory
project rule is a framework failure. Generated Markdown is a derived view and
must never resolve or overwrite a federation conflict.

## Continuous Update Loop

Run this loop after each meaningful coding task, PR, audit, incident, milestone closeout, or repeated review finding:

1. **Observe**: collect bug, failed test, review finding, stale doc, CI flake, repeated smell.
2. **Classify**: map to rule category from `20-rule-catalog.md`.
3. **Decide**: new rule, rule update, harness update, baseline ratchet, or rule deletion.
4. **Verify**: add automated check, manual checklist, or evidence template.
5. **Ratchet**: choose advisory/ratchet/hard status based on false positives and blast radius.
6. **Record**: update active rules and project memory in the same change as the fix.
7. **Audit**: periodically find obsolete or contradictory rules.

## Task Closeout Learning Audit

Before closing a coding task, ask whether the task revealed any reusable fact:

```text
TaskLearningAudit:
  task_or_change:
  affected_paths:
  observed_owner:
  observed_risk_area:
  command_or_harness_used:
  acceptance_surface:
  repeated_failure_or_review_finding:
  stale_rule_or_doc:
  new_fact_to_record:
  fact_maturity:
  evidence:
  follow_up_rule_or_harness:
```

Record a memory entry when the answer is durable across future tasks. Do not record one-off command output, temporary branch state, or speculation. If the fact is plausible but not proven, add it to `decisions.md` instead.

Example memory entry shape:

```text
Fact:
  summary:
  evidence:
    paths:
    task_or_pr:
    verification:
  status: observed_once|repeated|verified_by_tests|enforced_by_ci|hard_gate|stale
  applies_when:
  owner:
  next_action:
  supersedes:
```

## When To Update Rules

- same review comment appears twice;
- bug class escaped tests;
- developer misunderstood owner/architecture;
- mock test passed while product behavior failed;
- local/remote CI status was misreported;
- dependency, release, runtime, or supply-chain assumption changed;
- fallback or degraded behavior was invisible to users/operators;
- secret, policy, version, or coverage semantics had multiple sources of truth;
- rule points to archived path or stale command;
- hard gate has frequent false positives.

## When To Delete Or Supersede Rules

- path or command no longer exists;
- project profile changed;
- stronger automated gate covers the same invariant;
- rule encoded a one-off workaround;
- rule conflicts with current architecture;
- rule blocks useful work without reducing risk.

## Rule Drift Audit

```text
RuleDriftAudit:
  stale_paths:
  stale_commands:
  rules_without_owner:
  rules_without_harness:
  advisory_rules_older_than_threshold:
  exceptions_past_delete_by:
  claims_not_backed_by_ci:
  contradictory_rules:
  rules_to_delete:
  rules_to_harden:
```

## Project Memory Guidance

Store durable lessons:

- recurring defect class;
- owner decision;
- test/harness invariant;
- release or supply-chain boundary;
- product-specific acceptance rule;
- command or CI job that reliably verifies a risk;
- path-to-owner mapping observed repeatedly during coding work;
- stale assumption that caused wasted work or false confidence.

Do not store:

- one-off command output;
- temporary branch state;
- old CI failures after fix unless they define a new invariant;
- project-specific assumptions inside the portable skill.

## Promotion Back To The Skill

Promote a project lesson into this portable skill only when at least one is true:

- the same defect class appears in two unrelated modules or two projects;
- the lesson maps to a known rule family and can be expressed without project names;
- the lesson needs a reusable harness pattern, not just prose;
- the lesson changes how future projects should be classified.

Keep it project-local when it depends on a product brand, exact user flow, exact file path, exact CI job, exact threshold, or one release incident.

## Skill Maintenance

When this skill is used on a new project, feed reusable lessons back into:

- `10-project-profiles.md` for new profile variants;
- `20-rule-catalog.md` for new rule families;
- `30-harness-catalog.md` for new gate patterns;
- `40-rule-lifecycle.md` for rule lifecycle improvements;
- `00-system-model.md` only for durable rationale.

Keep `SKILL.md` short. Add detail to references, not the root skill body.
