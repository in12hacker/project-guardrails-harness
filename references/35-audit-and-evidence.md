# Audit And Evidence Protocol

Quality assurance separates development, verification, and release authority.
The same evidence may be reused, but each audit conclusion is independent.

## Audit Stages

1. `self`: the development agent runs deterministic controls and records raw evidence.
2. `cross`: an independent agent/context re-evaluates original evidence and searches for omitted controls or false claims.
3. `release_authority`: the project owner confirms scope, market, and release decision.
4. `third_party`: required for regulated delivery or when the selected commercial profile demands external assurance.

Open-source and solo projects may use an independent quality agent plus the
project owner for the first three stages. Commercial and regulated profiles can
require organizational or external signers.

## Independence Rules

- cross-audit reads source evidence, not only the self-audit summary;
- audit actor, tool/model version, prompt/rule-set version, commit, scope, and
  evidence digest are recorded;
- disagreement produces `DISPUTED`, never an automatic pass;
- a signer cannot override a deterministic failed mandatory control;
- evidence expires when affected code/config/artifacts change or its explicit
  validity window ends;
- secrets and sensitive output are redacted before evidence persistence.

## Authorization Boundary

Local non-privileged controls may run automatically. The following require
separate user authorization every time or an explicitly approved policy:

- paid services;
- use of secrets or credentials;
- production/staging mutations;
- remote repository, CI, registry, cloud, or deployment mutations;
- root, device, kernel, hardware, or other privileged execution;
- installation of new dependencies or system tools.

If authorization is absent, mark the control `BLOCKED` with the exact
prerequisite and rerun command. Do not downgrade it to `TODO` or `PASS`.

When GitHub workflows are detected, initialization adds a read-only remote
check-runs control bound to the assessed commit. It remains `BLOCKED` until the
user separately authorizes that control. Artifact registries and deployment
systems use project-configured `remote` or `privileged` argv controls because
the skill must not guess provider, account, artifact, or environment identity.

## Claim Enforcement

For a target maturity:

1. select controls whose `required_from_maturity` is at or below the target;
2. remove only human-confirmed `NOT_APPLICABLE` controls;
3. require every remaining control to be current `PASS`;
4. require the audit stages selected by the manifest;
5. bind the conclusion to commit and artifact digests;
6. refuse the claim if any evidence is missing, stale, blocked, failed, or disputed.
