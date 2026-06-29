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

## Continuous Update Loop

Run this loop after each meaningful PR, audit, incident, milestone closeout, or repeated review finding:

1. **Observe**: collect bug, failed test, review finding, stale doc, CI flake, repeated smell.
2. **Classify**: map to rule category from `20-rule-catalog.md`.
3. **Decide**: new rule, rule update, harness update, baseline ratchet, or rule deletion.
4. **Verify**: add automated check, manual checklist, or evidence template.
5. **Ratchet**: choose advisory/ratchet/hard status based on false positives and blast radius.
6. **Record**: update active rules and project memory in the same change as the fix.
7. **Audit**: periodically find obsolete or contradictory rules.

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
- product-specific acceptance rule.

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
