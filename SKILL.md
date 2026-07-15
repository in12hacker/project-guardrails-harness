---
name: project-guardrails-harness
description: "Use when asked to create, execute, audit, regenerate, or evolve a whole-project quality framework, engineering rules, architecture guardrails, CI gates, product acceptance, production readiness, commercial release criteria, ownership, supply-chain assurance, technical-debt convergence, or project memory for ANY software project. This skill is a lifecycle quality control plane: it turns business requirements and repository evidence into machine-readable controls, runs local gates, records evidence, and blocks Codex completion/release claims when applicable controls are not current PASS. It supports greenfield scaffolding, brownfield convergence, subproject-scoped assurance, independent cross-audit, and AI-system overlays."
---

# Project Guardrails Harness

Create and continuously execute a portable, project-specific commercial delivery quality framework.

## Core Rule

Use **Evidence over Claims**. Only a current `PASS` satisfies an applicable control. `FAIL`, `BLOCKED`, `TODO`, `DISPUTED`, and `STALE` block the associated completion, maturity, or release claim.

## Workflow

1. **Load the quality control plane**
   - Read `.guardrails/quality-manifest.yaml`, `control-registry.yaml`, `evidence-ledger.json`, then `INDEX.md` and task-relevant files.
   - Validate scope, the bound Skill revision/content digest, and evidence freshness before inheriting any prior PASS. A Skill update makes prior active-plane evidence stale until a reviewed campaign revision or regeneration rebinds it.

2. **Require explicit profile decisions**
   - Before initialization, require product type, development mode, distribution model, target market, criticality, target maturity, assessed scope, public contracts, build topology, persistent-state model, external-contribution model, and whether this is an AI system.
   - Never infer legal/regulatory applicability or target market from repository keywords.

3. **Initialize the v3 framework**
   - Run the bundled initializer with explicit choices. It scans repository evidence, renders human guidance, and creates the three machine sources of truth.
   - Greenfield projects get the skeleton before feature development. Brownfield projects remain globally `not_ready` until debt is eliminated, but verified convergence tasks may complete.

   ```bash
   : "${PROJECT_GUARDRAILS_SKILL_DIR:?set the reviewed Skill checkout path}"
   SKILL_DIR="$PROJECT_GUARDRAILS_SKILL_DIR"
   python3 "$SKILL_DIR/scripts/init_quality_framework.py" --root . \
     --development-mode <explicit> --target-maturity <explicit> \
     --product-type <explicit> --distribution-model <explicit> \
     --market <explicit> --criticality <explicit> \
     --data-sensitivity <explicit> --deployment-model <explicit> \
     --support-model <explicit> --primary-user <explicit> \
     --public-contract <explicit> --build-topology <explicit> \
     --persistent-state <explicit> --external-contributions <explicit> \
     --skill-deployment <explicit> \
     --evidence-profile <explicit> --evidence-retention <explicit> \
     --evidence-max-active-bytes <explicit> \
     --evidence-sealing-profile <explicit> \
     --no-ai-system --scope-mode <explicit> \
     --legal-profile <explicit>
   ```
   - Replace `--no-ai-system` with `--ai-system` when the delivered product itself contains AI behavior.
   - A repository developed entirely by AI agents is an AI development mode, not automatically an AI system. Use `ai_greenfield`/`ai_brownfield` with `--no-ai-system` when the delivered product has no inference or model behavior.
   - This is a v3-only control plane. Seal an older plane with its bound Skill revision, then regenerate; do not add compatibility readers or branches.
   - For AI brownfield work, register the reviewed campaign specification before any task or phase claim:

   ```bash
   python3 "$SKILL_DIR/scripts/register_campaign.py" --root . \
     --campaign /path/to/reviewed-campaign.json
   ```

4. **Ingest existing truth before adding controls**
   - Read existing instruction files, CI, build targets, test registries, fitness runners, release workflows, contracts, and operations docs.
   - Link and gap-fill; do not duplicate an existing authoritative fact.
   - Initialization inventories every detected instruction source, including nested `SKILL.md` files, as mandatory `unmapped` federated records. Expand whole-file records into heading/rule selectors where ownership differs. Assign semantic owner, disposition, and control references, set digest-bound status, then sync traceability;
     an unmapped mandatory source blocks claims but not control execution.

5. **Build end-to-end traceability**
   - Every business requirement maps to risk, owner/ADR, control, test/fitness function, evidence, and delivery/runtime outcome.
   - Broken traceability blocks the maturity where the requirement applies.
   - After an approved registry edit, run `python3 "$SKILL_DIR/scripts/sync_traceability.py" --root .`; never hand-edit the derived graph.

6. **Develop under task-scoped quality controls**
   - Before editing, identify affected requirements, controls, owners, and gates.
   - During work, create missing scripts, CI, configs, tests, docs, dependencies, or scaffolding needed by applicable controls.
   - In AI brownfield mode, work only inside the registered convergence campaign revision and phase. Record task/phase `COMPLETED` outcomes separately from control statuses; do not use an ordinary feature task as a ratchet exception.
   - Installing dependencies, using secrets/paid services, remote or production mutation, and privileged execution require separate user authorization.

7. **Execute controls and record evidence**
   - Local unprivileged controls run automatically when relevant. Commands are project-owned argv arrays, not fabricated shell strings.
   - Use the evaluator; a non-zero result blocks completion claims.
   - The evaluator serializes concurrent agents with `.guardrails/.ledger.lock`. Every run/audit/claim has a `subject_binding` over the latest non-evidence commit, non-evidence project tree, manifest, registry, traceability, and Skill, plus a separate `storage_binding` over ledger/evidence chain material. Committing only ledger, evidence, or archives must not stale the audited subject.

   ```bash
   python3 "$SKILL_DIR/scripts/evaluate_quality.py" --root . --run \
     --audit-stage self --actor codex --authority-id virtual:developer \
     --execution-context session-or-runner-id
   ```

8. **Audit independently**
   - Self-audit produces raw evidence. Cross-audit uses an independent context and rereads original evidence. Release authority confirms scope/market/release. Regulated profiles add third-party audit.
   - Disagreement is `DISPUTED`; it cannot be waived into PASS.
   - `cross`, `release_authority`, and `third_party` runs must provide a distinct
     `--authority-id`, a distinct `--execution-context`, and `--review-run` for
     the immediately preceding stage. A renamed actor label is not independence.
   - Authority IDs must be registered for their stage in
     `audit_policy.authorities`. The generated one-person profile uses separate
     virtual developer, quality, and release-owner responsibilities.

9. **Make or refuse the claim**
   - `--claim` reads `claim_policies.<scope>` and succeeds only when the scope's
     deterministic outcome policy and audit stages are satisfied for the same bindings.
   - Human brownfield feature work uses `--claim-scope task --control <affected-id>...`.
     AI brownfield task/phase claims derive scope and ratchet policy from the active
     campaign and require matching campaign revision, phase, and task identifiers.
   - Successful outcomes are appended to the hash-chained `claims` ledger. Task or
     phase completion never changes a failed debt control or whole-project readiness.

   ```bash
   python3 "$SKILL_DIR/scripts/evaluate_quality.py" --root . --claim

   python3 "$SKILL_DIR/scripts/evaluate_quality.py" --root . --claim \
     --claim-scope task --campaign-id <id> --campaign-revision <n> \
     --phase-id <phase> --task-id <task>
   ```

   Before handing work to another role, derive the four non-mutating readiness
   levels. A readiness report is not a claim and never writes the ledger.
   Human projects select affected controls explicitly:

   ```bash
   python3 "$SKILL_DIR/scripts/assess_readiness.py" --root . \
     --control <affected-id> --require-level TASK_CLAIM_READY
   ```

   AI brownfield projects must provide the complete reviewed task context. Do
   not infer a task from the active campaign because one phase may contain
   multiple tasks. Missing or mismatched context returns `NOT_EVALUATED` with
   typed `blocker_details`.

   ```bash
   python3 "$SKILL_DIR/scripts/assess_readiness.py" --root . \
     --campaign-id <id> --campaign-revision <n> \
     --phase-id <phase> --task-id <task> \
     --require-level TASK_CLAIM_READY
   ```

   Generate the machine-owned handoff header under the evidence plane, then
   lint it immediately before transfer. Human notes cannot redefine campaign,
   scope, controls, readiness, subject, Skill, or authorization fields.

   ```bash
   python3 "$SKILL_DIR/scripts/render_task_handoff.py" --root . \
     --campaign-id <id> --campaign-revision <n> \
     --phase-id <phase> --task-id <task> --write
   python3 "$SKILL_DIR/scripts/render_task_handoff.py" --root . \
     --campaign-id <id> --campaign-revision <n> \
     --phase-id <phase> --task-id <task> --check
   ```

   The renderer must invoke readiness with
   `--require-level TASK_CLAIM_READY`. A typed `BLOCKED` or `NOT_EVALUATED`
   result may be rendered for an honest not-ready handoff; tool failure,
   malformed JSON, or an untyped blocker must fail generation. Keep control
   verification capabilities separate from product acquisition capabilities.
   Because v3 has no acquisition mapping, the generated handoff marks product
   acquisition applicability `NOT_EVALUATED` and execution `BLOCKED`; an empty
   verification capability list never authorizes product acquisition. Do not
   promote this conservative execution state to a task-level blocker unless the
   project explicitly declares that the task requires product acquisition.
   Portable execution Harness candidates remain proposals outside the v3
   ledger. Model `committed` and `prevented` effects separately: a prevented
   effect has a runtime attempt and outcome but no side-effect commit. Never
   reinterpret a deny decision record as the protected effect's commit.

10. **Learn and evolve**
   - Feed incidents, escaped defects, SLO breaches, customer outcomes, vulnerability response, and repeated review findings back into project controls and durable memory.
   - Record external-project observations with immutable revision, evidence paths, profile, applicability boundary, and counterexamples.
   - Promote portable lessons only after independent corroboration or a stable formal standard, explicit target applicability, owner review, runnable verification, and false-positive tests.
   - Keep `.guardrails` project-owned and versioned. Select `environment_managed`, `project_symlink`, or `vendored` Skill deployment explicitly. For `project_symlink`, keep client-specific links uncommitted and point every client to the same reviewed checkout.
   - When the active schema changes incompatibly, seal the old control plane as a read-only digest archive, add the external signature when its profile requires one, and regenerate the active plane. Do not add compatibility readers.
   - Review every Skill update before changing the active plane. `--check` is
     read-only; `--apply` accepts only a declared compatible same-schema update,
     increments an active campaign revision, preserves project-owned guidance,
     synchronizes traceability, and reports controls that must rerun.

   ```bash
   python3 "$SKILL_DIR/scripts/review_skill_update.py" --root . --check
   python3 "$SKILL_DIR/scripts/review_skill_update.py" --root . --apply
   ```

   ```bash
   python3 "$SKILL_DIR/scripts/seal_evidence.py" --root . --archive-id <immutable-id>
   ```

   Use `--legacy-unvalidated` only for a pre-current-schema control plane; the archive is then permanently marked untrusted and cannot support a claim. When regenerating, pass `--predecessor-archive-id <immutable-id>` so the new manifest binds the prior archive digest.

## Output Shape

Emit a **progressive-disclosure directory**, not one monolithic file. The three
machine-readable files are authoritative; Markdown explains their application
and never overrides them. Use the initializer in step 3 to scaffold the set.

```text
.guardrails/
├── quality-manifest.yaml   # selected profile, scope, maturity, audit and claim policy
├── control-registry.yaml   # applicable controls, owners, execution and evidence requirements
├── evidence-ledger.json    # subject-bound evidence + separate storage-chain bindings
├── traceability-graph.json # derived requirement → risk → control → test → evidence graph
├── evidence/
│   └── task-handoff.md     # generated task context/readiness header + human implementation notes
├── INDEX.md          # ALWAYS loaded: one-line profile, owner summary, hard-gate shortlist, links (keep <150 lines)
├── profile.md        # evidence: README excerpt + deps + build targets + existing rules
├── owners.md         # owner map (semantic owners vs adapters)
├── rules/
│   ├── hard.md       # hard-rule gap-check vs existing rules + catalog
│   ├── candidates.md # evidence-backed project-specific draft rules; human validation required
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
- Read `references/05-delivery-lifecycle.md` for maturity levels, claim semantics, debt treatment, and authorization boundaries.
- Read `references/10-project-profiles.md` to adapt rules for libraries, web apps, infra, security products, AI agent systems, mobile apps, embedded systems, or data platforms.
- Read `references/15-standards-and-quality-model.md` for stable standards, quality characteristics, and explicit market/profile choices.
- Read `references/20-rule-catalog.md` for categorized guardrail families, including cleanliness, parameter/variable flow, and boundary robustness.
- Read `references/25-control-and-traceability.md` for machine controls, evidence records, and end-to-end traceability.
- Read `references/30-harness-catalog.md` for CI/test/product/release gate patterns, including test-basis metadata, fitness registries, interface contracts, documentation deliverables, and boundary robustness matrices.
- Read `references/35-audit-and-evidence.md` for audit independence, evidence freshness, authorization, and claim enforcement.
- Read `references/40-rule-lifecycle.md` for continuous rule iteration, project memory, fact maturity, ratchets, baseline cleanup semantics, module readiness, and stale-rule deletion.
- Read `references/45-adoption-and-operations.md` for greenfield/brownfield adoption, production operation, commercial delivery, and feedback loops.
- Read `references/50-client-deployment-and-signing.md` for Codex/Claude dual-link deployment, generated adapters, signed Skill release policy, ledger sealing, retention, and external Sigstore verification.

## Non-Negotiables

- Do not record task or phase `COMPLETED` unless all affected non-debt controls
  are current `PASS` and its declared exit policy is satisfied. Never rewrite a
  failed debt control as `PASS` to complete a task.
- Do not claim a maturity level, project completion, mergeability, or release readiness unless every applicable control and required audit stage is current `PASS` for the same subject binding and scope. A later storage-only commit may contain that evidence without changing the subject.
- Do not convert `FAIL`, `BLOCKED`, `TODO`, `DISPUTED`, or `STALE` into a passing claim. Known debt remains blocking for project maturity even when verified human-project feature work may continue.
- Do not infer target market, legal obligations, regulatory applicability, or target maturity. Require explicit project selection.
- Do not use draft standards as mandatory baselines when a stable official release exists.
- Do not let a subproject-scoped assessment claim whole-project readiness.
- Do not mark a control `NOT_APPLICABLE` without an owner-approved rationale and scope record.
- Do not install dependencies, use secrets or paid services, mutate remote/production state, or run privileged operations without separate user authorization.
- Do not trust docs over code.
- Do not let route/controller/UI/daemon layers become silent business owners.
- Do not collapse product acceptance into unit, mock, or contract tests.
- Do not count a test as a gate if its basis, risk, runner, evidence, and scenario origin are unknown.
- Do not treat a baseline or allowlist as proof that a detected violation is acceptable; distinguish design-scope exemptions from cleanup debt.
- Do not force refactors from preference alone; cite a violated rule, owner boundary, readiness dimension, or fitness function.
- Do not hide policy, defaults, exclusions, or fallback behavior in adapter code.
- Do not treat fail-open/fail-closed as a global default; require a layer matrix.
- Do not let plaintext secrets persist outside the approved runtime boundary.
- Do not declare release-grade supply-chain assurance without provenance and signed/verifiable artifacts.
- Do not make a `commercial_ready` project/release claim from a moving or unsigned Skill checkout; development task claims may use an explicitly bound unverified revision.
- Do not classify the project by keyword or language alone — read its self-description (README / AGENTS.md) and dependencies, then state the profile.
- Do not duplicate a rule the project already states in its own files — link to it and gap-fill.
- Do not add project-specific rules until the project profile and owner map are explicit.
- Do not promote generated candidate rules without human validation and runnable verification.
- Do not write durable project memory without code paths, task evidence, and a maturity/status label.
- Do not fabricate a verification command; if no real command exists, mark it a gap.
