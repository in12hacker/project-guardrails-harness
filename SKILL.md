---
name: project-guardrails-harness
description: Use when asked to create, audit, migrate, or adapt engineering rules, architecture guardrails, CI quality gates, verification harnesses, release criteria, CODEOWNERS / ownership boundaries, supply-chain assurance (SLSA, build provenance, artifact signing), technical-debt ratchets, ADRs, or project-specific development standards for ANY software project — library, web app, backend service, infrastructure, security product, mobile, embedded, data platform, or AI agent system. Use this to turn a repository into evidence-backed rules (anchored to code paths, owners, CI/runtime evidence, and a verification plan) instead of trusting documentation or claims. Trigger it whenever someone wants guardrails, quality gates, release readiness, an owner map, or to check whether docs/ADRs still match the code — even if they never say the word "guardrails".
---

# Project Guardrails Harness

Create portable, project-specific engineering guardrails and verification harnesses from repository evidence.

## Core Rule

Use **Evidence over Claims**. Documentation, issue comments, and team assertions are inputs to verify, not proof. A generated rule is valid only when it is anchored to code paths, owner boundaries, CI/runtime evidence, and an explicit verification plan.

## Workflow

1. **Scan the repo**
   - The skill ships a scanner at `scripts/scan_project.py`, inside this skill's own folder. Run it from the target repo root so it works no matter where the skill is installed (personal, project, or plugin scope):
     ```bash
     SCAN="${CLAUDE_SKILL_DIR:-$HOME/.claude/skills/project-guardrails-harness}/scripts/scan_project.py"
     [ -f "$SCAN" ] || SCAN=".claude/skills/project-guardrails-harness/scripts/scan_project.py"
     python3 "$SCAN" --root . --out "/tmp/project-guardrails-scan-$(basename "$(pwd)")-$$.json"
     ```
     Claude Code sets `${CLAUDE_SKILL_DIR}` to this skill's directory at runtime. If a client does not export it, the first fallback resolves the personal-scope path and the second the project-scope path, so the command is portable instead of pinned to one install location. The output filename embeds the repo name and shell PID, so back-to-back runs on different repos (or concurrent sessions) don't overwrite each other's scan — pass the resulting path to the renderer. If the scanner still cannot be found, collect the evidence manually (next bullet).
   - If the script is unavailable, manually collect the same evidence: languages, package managers, CI files, tests, docs, release files, security files, deployment files, public contracts.

2. **Classify the project**
   - Read `references/10-project-profiles.md` when the project type is unclear or mixed.
   - Classify by product/user/runtime/release model, not by language alone.

3. **Build the owner map**
   - Identify owners for domain identity, config, policy/rules, audit/logs, API/wire contract, UI/product behavior, platform/runtime I/O, release artifacts, and test harness.
   - Do not invent owners from desired architecture. Use code paths first; record uncertainty as a pre-decision item.

4. **Generate rules**
   - Use `references/20-rule-catalog.md`.
   - Every hard rule must have: trigger, owner, required evidence, reject condition, and verification command or harness.

5. **Generate harness**
   - Use `references/30-harness-catalog.md`.
   - Separate PR gate, closeout gate, product acceptance gate, and release gate.
   - Mock/contract tests cannot prove product acceptance unless the product itself is a library or contract-only component.

6. **Validate against reality**
   - Run existing local gates where feasible.
   - Check remote CI for mergeability if the task involves PR readiness.
   - Mark unavailable root/device/cloud/manual checks as blocked/manual, not pass.

7. **Write adoption plan**
   - Start with advisory gates and inventory only when a hard gate would break the project.
   - Ratchet toward hard gates with owners, dates, and deletion criteria.
   - Read `references/40-rule-lifecycle.md` when the task asks how rules should keep evolving during development.

## Output Shape

Prefer this structure:

```text
ProjectGuardrails:
  project_profile:
  evidence_inventory:
  owner_map:
  hard_rules:
  advisory_rules:
  harness_matrix:
  ci_delta:
  migration_plan:
  unresolved_decisions:
  sources:
```

## When More Context Is Needed

- Read `references/00-system-model.md` for the rationale, source standards, and the conceptual model.
- Read `references/10-project-profiles.md` to adapt rules for libraries, web apps, infra, security products, AI agent systems, mobile apps, embedded systems, or data platforms.
- Read `references/20-rule-catalog.md` for categorized guardrail families, including cleanliness and parameter/variable flow.
- Read `references/30-harness-catalog.md` for CI/test/product/release gate patterns.
- Read `references/40-rule-lifecycle.md` for continuous rule iteration, rule memory, ratchets, and stale-rule deletion.

## Non-Negotiables

- Do not claim “complete”, “mergeable”, “release-ready”, or “closed” without commit/CI/runtime evidence.
- Do not trust docs over code.
- Do not let route/controller/UI/daemon layers become silent business owners.
- Do not collapse product acceptance into unit, mock, or contract tests.
- Do not hide policy, defaults, exclusions, or fallback behavior in adapter code.
- Do not treat fail-open/fail-closed as a global default; require a layer matrix.
- Do not let plaintext secrets persist outside the approved runtime boundary.
- Do not declare release-grade supply-chain assurance without provenance and signed/verifiable artifacts.
- Do not add project-specific rules until the project profile and owner map are explicit.
