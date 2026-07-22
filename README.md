# Project Guardrails Harness

A lifecycle quality-control skill that builds and continuously executes
**portable, project-specific delivery controls from business requirements and
repository evidence**. It can scaffold controls, run gates, record audit
evidence, and refuse completion or release claims that are not proven.

> Core rule: **Evidence over Claims.** Documentation, issue comments, and team
> assertions are inputs to verify, not proof. Only a current `PASS` satisfies an
> applicable control.

Use it when asked to:

- initialize or regenerate a v3 project-wide quality framework,
- create and execute engineering, product, operations, and release controls,
- trace requirements through risks, tests, controls, evidence, and outcomes,
- perform self-audit, independent cross-audit, and release authorization,
- evolve durable project memory from observed coding work,
- converge brownfield debt without falsely claiming whole-project readiness.

## Structure

```text
.
├── SKILL.md                 # skill entry point (workflow, output shape, non-negotiables)
├── references/              # progressive-disclosure context
│   ├── 00-system-model.md
│   ├── 05-delivery-lifecycle.md
│   ├── 10-project-profiles.md
│   ├── 15-standards-and-quality-model.md
│   ├── 20-rule-catalog.md
│   ├── 25-control-and-traceability.md
│   ├── 30-harness-catalog.md
│   ├── 35-audit-and-evidence.md
│   ├── 40-rule-lifecycle.md
│   └── 45-adoption-and-operations.md
├── schemas/                 # machine-readable quality source schemas
├── templates/               # starter manifest, registry, and ledger
└── scripts/
    ├── scan_project.py      # collect repo evidence → JSON
    ├── render_guardrails.py # render human guidance
    ├── init_quality_framework.py # create a v3 .guardrails control plane
    ├── register_campaign.py # bind an AI brownfield campaign to current v3 evidence
    ├── sync_traceability.py # regenerate the derived traceability graph
    ├── evaluate_quality.py  # execute controls and enforce claims
    ├── render_task_handoff.py # derive the current task handoff
    └── query_quality_state.py # return bounded, verified state projections
```

## Install

This repo's root **is** the skill folder. Prefer one central clone and a
user-level symlink so every project reads the current Skill without committing
it or coupling project CI/release to it:

```bash
git clone https://github.com/in12hacker/project-guardrails-harness.git \
  ~/work/project-guardrails-harness
mkdir -p ~/.claude/skills
ln -s ~/work/project-guardrails-harness \
  ~/.claude/skills/project-guardrails-harness
```

For an intentionally project-pinned copy, clone it into the project and manage
that version explicitly. Do not commit an absolute machine-local symlink:

```bash
git clone https://github.com/in12hacker/project-guardrails-harness.git \
  <project>/.claude/skills/project-guardrails-harness
```

Once in place, Claude Code loads it automatically. At runtime, `SKILL.md`
prefers the `CLAUDE_SKILL_DIR` path when Claude exposes it, then falls back to
the personal and project `.claude/skills/project-guardrails-harness/` locations.
If you keep the skill somewhere else, run the scripts by explicit path or set
`CLAUDE_SKILL_DIR` before invoking the snippets.

## Quick Start

Initialization requires explicit product, market, criticality, development,
distribution, maturity, contract, build, state, and contribution choices:

```bash
python3 scripts/init_quality_framework.py --root /path/to/project \
  --development-mode human_brownfield \
  --target-maturity production_ready \
  --product-type backend_service \
  --distribution-model open_source \
  --market global_unspecified \
  --criticality medium \
  --data-sensitivity public \
  --deployment-model self_hosted \
  --support-model community \
  --primary-user developer \
  --public-contract service_api \
  --build-topology single_form \
  --persistent-state database \
  --external-contributions accepted \
  --skill-deployment environment_managed \
  --evidence-profile open_source \
  --evidence-retention project_lifetime \
  --evidence-max-active-bytes 1073741824 \
  --evidence-sealing-profile sha256_chain \
  --no-ai-system \
  --scope-mode full_repo \
  --legal-profile none_identified \
  --scaffold-engineering
```

`--scaffold-engineering` is explicit and optional. It creates a local,
stdlib-only runner only when the scanner finds an unambiguous repository-root
target named `gate`, plus a pinned, least-privilege GitHub Actions entry point.
Language markers, package script names, and candidate gate names never become
executable commands without owner selection. Scaffolding installs no
dependencies and does not overwrite an existing workflow of the same name.

Run local controls with stable authority/context identities, bind each independent
stage to the evidence it reviewed, then evaluate a claim:

```bash
python3 scripts/evaluate_quality.py --root /path/to/project --run \
  --audit-stage self --actor codex --authority-id virtual:developer \
  --execution-context local-session-id
python3 scripts/evaluate_quality.py --root /path/to/project --claim
```

The second command must fail while any applicable control or required audit
stage is not current `PASS` for the assessed commit and scope.
For human brownfield work, a scoped task claim uses `--claim-scope task` plus
every affected `--control`; it never changes whole-project readiness.

AI brownfield work first registers a reviewed campaign JSON specification with
`register_campaign.py`. Task and phase claims then identify the exact campaign
revision and phase/task. Ratchet observations may support scoped completion while
the underlying debt control remains `FAIL`; project and release claims remain
absolute. This repository intentionally implements v3 only and carries no v1/v2
reader or compatibility branch.

## License

MIT — see [LICENSE](LICENSE).
