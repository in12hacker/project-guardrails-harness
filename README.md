# Project Guardrails Harness

A [Claude Code](https://docs.claude.com/en/docs/claude-code) skill that builds
**portable, project-specific engineering guardrails and verification harnesses
from repository evidence**.

> Core rule: **Evidence over Claims.** Documentation, issue comments, and team
> assertions are inputs to verify, not proof. A generated rule is valid only
> when it is anchored to code paths, owner boundaries, CI/runtime evidence, and
> an explicit verification plan.

Use it when asked to:

- create, audit, migrate, or adapt engineering rules / architecture guardrails,
- design CI quality gates, verification harnesses, release criteria,
- turn a repository's claims into evidence-backed, project-specific development
  standards.

## Structure

```text
.
├── SKILL.md                 # skill entry point (workflow, output shape, non-negotiables)
├── references/              # progressive-disclosure context
│   ├── 00-system-model.md
│   ├── 10-project-profiles.md
│   ├── 20-rule-catalog.md
│   ├── 30-harness-catalog.md
│   └── 40-rule-lifecycle.md
└── scripts/
    ├── scan_project.py      # collect repo evidence → JSON
    └── render_guardrails.py # render the guardrails output
```

## Install

This repo's root **is** the skill folder. Install it into a project's skills
directory:

```bash
# from the target project root
git clone https://github.com/in12hacker/project-guardrails-harness.git \
  .claude/skills/project-guardrails-harness
```

…or keep it as a central clone and symlink:

```bash
ln -s /path/to/project-guardrails-harness \
  <project>/.claude/skills/project-guardrails-harness
```

Once in place, Claude Code loads it automatically. The skill expects to live at
`.claude/skills/project-guardrails-harness/` (the scan script is invoked from
there).

## License

MIT — see [LICENSE](LICENSE).
