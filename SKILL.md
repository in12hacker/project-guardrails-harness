---
name: project-guardrails-harness
description: Use when asked to create, audit, migrate, evolve, or adapt engineering rules, architecture guardrails, CI quality gates, verification harnesses, release criteria, CODEOWNERS / ownership boundaries, supply-chain assurance (SLSA, build provenance, artifact signing), technical-debt ratchets, ADRs, project memory, or project-specific development standards for ANY software project — library, web app, backend service, infrastructure, security product, mobile, embedded, data platform, or AI agent system. Use this to turn a repository into evidence-backed rules (anchored to code paths, owners, CI/runtime evidence, and a verification plan) instead of trusting documentation or claims, and to keep those rules evolving from observed development work. Trigger it whenever someone wants guardrails, quality gates, release readiness, an owner map, durable coding lessons, or to check whether docs/ADRs still match the code — even if they never say the word "guardrails".
---

# Project Guardrails Harness

Create portable, project-specific engineering guardrails and verification harnesses from repository evidence.

## Core Rule

Use **Evidence over Claims**. Documentation, issue comments, and team assertions are inputs to verify, not proof. A generated rule is valid only when it is anchored to code paths, owner boundaries, CI/runtime evidence, and an explicit verification plan.

## Workflow

1. **Load existing project memory**
   - If `.guardrails/INDEX.md` exists, read it first. Then read only the files relevant to the task: `memory.md` for durable lessons, `rules/hard.md` for PR/review work, `harness.md` for verification, `supply-chain.md` for releases, and `decisions.md` for unresolved migrations.
   - Treat existing `.guardrails/` entries as versioned hypotheses unless they point to live code paths, owners, and verification evidence. Stale paths or commands must become update items, not inherited truth.

2. **Scan the repo**
   - The skill ships a scanner at `scripts/scan_project.py`, inside this skill's own folder. Run it from the target repo root so it works no matter where the skill is installed in Claude Code personal or project scope:
     ```bash
     SCAN="${CLAUDE_SKILL_DIR:-$HOME/.claude/skills/project-guardrails-harness}/scripts/scan_project.py"
     [ -f "$SCAN" ] || SCAN=".claude/skills/project-guardrails-harness/scripts/scan_project.py"
     python3 "$SCAN" --root . --out "/tmp/project-guardrails-scan-$(basename "$(pwd)")-$$.json"
     ```
     Claude Code sets `${CLAUDE_SKILL_DIR}` to this skill's directory at runtime. If a client does not export it, the first fallback resolves the personal-scope path and the second the project-scope path, so the command is portable across the supported install locations instead of pinned to one path. The output filename embeds the repo name and shell PID, so back-to-back runs on different repos (or concurrent sessions) don't overwrite each other's scan — pass the resulting path to the renderer. If the scanner still cannot be found, collect the evidence manually (next bullet).
   - If the script is unavailable, manually collect the same evidence: languages, package managers, CI files, tests, docs, release files, security files, deployment files, public contracts.

3. **Classify the project — your judgment, not a scanner label**
   - The scanner deliberately does not classify (that is a judgment call, not a deterministic one). Read its `readme_excerpt` + `manifest_deps` and the project's own AGENTS.md / README, then state the profile in your own words: product / users / runtime / release model / trust boundaries.
   - Read `references/10-project-profiles.md` when the type is unclear or mixed; classify by product/runtime/release model, never by language alone.

4. **Build the owner map**
   - Identify owners for domain identity, config, policy/rules, audit/logs, API/wire contract, UI/product behavior, platform/runtime I/O, release artifacts, and test harness.
   - Do not invent owners from desired architecture. Use code paths first; record uncertainty as a pre-decision item.

5. **Generate rules as a gap-check (ingest first, don't overwrite)**
   - If the scan's `instruction_files` is non-empty, read those AGENTS.md / `.claude`|`cursor`|`codex` rules / CONTRIBUTING first and treat them as the **single source of truth**. Your job is to **link to them and fill gaps — never duplicate** a fact that already lives there.
   - Then gap-check each family in `references/20-rule-catalog.md`: already enforced (by what command / file)? gap? if genuinely new, state trigger · owner · required evidence · reject condition · verification.
   - A hard rule without a runnable check is a wish, not a rule. Prefer promoting a rule from `memory.md` once it is observed in real work over inventing it up front.

6. **Generate harness against the project's real commands**
   - Use `references/30-harness-catalog.md`, but map each gate to the **actual command** the project already uses (from the scan's `build_targets`, e.g. `make gate`, `coverage-gate`, `verify-release`) — not a generic "infer from ecosystem" guess. If a gate has no real command yet, that is a gap to create, not a command to fabricate.
   - Separate PR gate, closeout gate, product acceptance gate, and release gate.
   - Mock/contract tests cannot prove product acceptance unless the product itself is a library or contract-only component.

7. **Validate against reality**
   - Run existing local gates where feasible.
   - Check remote CI for mergeability if the task involves PR readiness.
   - Mark unavailable root/device/cloud/manual checks as blocked/manual, not pass.

8. **Write adoption plan**
   - Start with advisory gates and inventory only when a hard gate would break the project.
   - Ratchet toward hard gates with owners, dates, and deletion criteria.
   - Read `references/40-rule-lifecycle.md` when the task asks how rules should keep evolving during development.

9. **Update durable project memory**
   - After each meaningful coding task, audit whether the work revealed a reusable fact: owner, risk area, command, acceptance surface, test gap, stale rule, repeated review finding, release assumption, or incident class.
   - Record only evidence-backed facts in `.guardrails/memory.md`; keep guesses in `decisions.md`. Promote facts through `observed_once → repeated → verified_by_tests → enforced_by_ci → hard_gate`; delete or supersede stale facts.

## Output Shape

Emit a **progressive-disclosure directory**, not one monolithic file. An agent loads `INDEX.md` every time and reads the other files just-in-time by relevance (a release reads `supply-chain.md` + the release row of `harness.md`; a PR review reads `rules/hard.md`). A single big file buries critical rules mid-document — where models recall worst ("lost in the middle") — and re-costs tokens on every read. Scaffold it from the scan with the renderer:

```bash
SCAN_R="${CLAUDE_SKILL_DIR:-$HOME/.claude/skills/project-guardrails-harness}/scripts/render_guardrails.py"
[ -f "$SCAN_R" ] || SCAN_R=".claude/skills/project-guardrails-harness/scripts/render_guardrails.py"
python3 "$SCAN_R" "<your-scan.json>" --out-dir .guardrails/
```

```text
.guardrails/
├── INDEX.md          # ALWAYS loaded: one-line profile, owner summary, hard-gate shortlist, links (keep <150 lines)
├── profile.md        # evidence: README excerpt + deps + build targets + existing rules
├── owners.md         # owner map (semantic owners vs adapters)
├── rules/
│   ├── hard.md       # hard-rule gap-check vs existing rules + catalog
│   └── advisory.md   # advisory + ratchet gap-check
├── cleanliness.md    # debt / smell / large-file inventory and ratchet candidates
├── harness.md        # gate matrix mapped to the project's real build targets
├── supply-chain.md   # release / supply-chain gates (load when touching releases)
├── memory.md         # durable learned facts from coding work (owners, risks, commands, acceptance surfaces)
└── decisions.md      # unresolved decisions + migration/ratchet plan + sources
```

Keep `INDEX.md` under ~150 lines and each file under ~300 lines; put the most safety-critical REJECT conditions near the **top** of a file, never the middle; use relative links so the set is portable. (`render_guardrails.py --out FILE` still emits a single combined doc for humans / full-text search.)

## When More Context Is Needed

- Read `references/00-system-model.md` for the rationale, source standards, and the conceptual model.
- Read `references/10-project-profiles.md` to adapt rules for libraries, web apps, infra, security products, AI agent systems, mobile apps, embedded systems, or data platforms.
- Read `references/20-rule-catalog.md` for categorized guardrail families, including cleanliness and parameter/variable flow.
- Read `references/30-harness-catalog.md` for CI/test/product/release gate patterns.
- Read `references/40-rule-lifecycle.md` for continuous rule iteration, project memory, fact maturity, ratchets, and stale-rule deletion.

## Non-Negotiables

- Do not claim “complete”, “mergeable”, “release-ready”, or “closed” without commit/CI/runtime evidence.
- Do not trust docs over code.
- Do not let route/controller/UI/daemon layers become silent business owners.
- Do not collapse product acceptance into unit, mock, or contract tests.
- Do not hide policy, defaults, exclusions, or fallback behavior in adapter code.
- Do not treat fail-open/fail-closed as a global default; require a layer matrix.
- Do not let plaintext secrets persist outside the approved runtime boundary.
- Do not declare release-grade supply-chain assurance without provenance and signed/verifiable artifacts.
- Do not classify the project by keyword or language alone — read its self-description (README / AGENTS.md) and dependencies, then state the profile.
- Do not duplicate a rule the project already states in its own files — link to it and gap-fill.
- Do not add project-specific rules until the project profile and owner map are explicit.
- Do not write durable project memory without code paths, task evidence, and a maturity/status label.
- Do not fabricate a verification command; if no real command exists, mark it a gap.
