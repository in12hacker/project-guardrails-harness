# Rule Lifecycle

Rules must evolve with the project. Stale rules are architecture debt.

## Rule Maturity Levels

| Level | Meaning | Use |
|---|---|---|
| `proposal` | plausible rule, not validated | planning |
| `advisory` | warning and inventory only | legacy discovery |
| `ratchet` | new violations fail, old baseline allowed | debt reduction |
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

## Ratcheting And AI-Generated Code (2026)

- **Ratchet = "don't make it worse".** A PR may not increase measured debt (violation count, uncovered lines, hotspot code-health drop) beyond the current baseline; legacy is grandfathered until touched. Prefer this over flat thresholds, which reward gaming and block useful deletes.
- **Turn decisions into fitness functions.** An ADR or architecture rule should be enforced, not merely documented: render it as a runnable check (a test, a static-analysis rule, an OPA policy) that fails the PR when violated. A doc claim is a hypothesis; a runnable check is evidence.
- **Verification, not approval, for AI-generated code.** Human approval does not scale against AI-generated volume; the gate is that the change satisfies spec/tests/contracts/owners, not that a human rubber-stamped it. Code Health (complexity) can flag code too tangled for safe automated refactoring.

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
