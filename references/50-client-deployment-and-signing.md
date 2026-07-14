# Client Deployment, Revision Trust, and Evidence Sealing

## Deployment contract

Select and record one deployment mode during initialization:

- `environment_managed`: the client or execution environment provides the reviewed Skill path;
- `project_symlink`: client-specific project links point to one external checkout;
- `vendored`: the repository owns a reviewed copy and updates it through ordinary dependency review.

For a repository that explicitly selects `project_symlink` and uses both Codex and Claude, links may be:

```text
.agents/skills/project-guardrails-harness -> /absolute/path/project-guardrails-harness
.claude/skills/project-guardrails-harness -> /absolute/path/project-guardrails-harness
```

Ignore only project-local links. Commit `.guardrails/` because it is the project-specific expansion: profile, owners, controls, evidence, decisions, and product acceptance configuration are part of the project. Ignore only runtime lock files.

Keep `AGENTS.md` and `CLAUDE.md` as short generated adapters. `AGENTS.md` points to `.guardrails/INDEX.md` and states project identity plus immediate hard stops. `CLAUDE.md` imports or points to `AGENTS.md`. Do not copy the Skill body into either adapter.

Client discovery locations and symlink support are client-version capabilities, not universal project facts. Verify them before selecting `project_symlink`. Set `PROJECT_GUARDRAILS_SKILL_DIR` to the selected reviewed checkout for framework commands. A dual link is one deployment adapter, not a requirement of the generic Skill.

## Moving Skill and evidence freshness

Every generated manifest records:

- Git revision;
- normative/executable content SHA-256;
- dirty state;
- trust level;
- signed tag, when verifiable.

Every run, audit, claim, and AI brownfield campaign baseline carries the revision and content digest. A checkout update is allowed, but old active evidence cannot support a new claim. Re-register the reviewed campaign revision or regenerate the active control plane after reviewing the delta.

Development task claims may use a clean, bound, unsigned revision. `commercial_ready` project and release claims require `trust_level=signed_release`. A signed Git tag must verify locally and the Skill tree must be clean.

## Evidence retention

Every project explicitly selects an evidence profile, retention class, active-plane byte budget, and sealing profile. `commercial` and `regulated` evidence requires permanent retention and external-signature-capable `sigstore_bundle` sealing. `open_source` and `custom` projects may select a looser reviewed policy. Outputs are redacted before persistence and content-addressed by SHA-256.

When the active schema changes incompatibly:

1. stop active writers and acquire the ledger lock;
2. validate every ledger hash chain, ledger-referenced immutable evidence artifact, manifest, registry, and traceability binding;
3. package the ledger, traceability graph, manifest, registry, output inventory, and final chain heads;
4. compute a package digest;
5. sign that digest externally;
6. store the archive and verification bundle read-only;
7. initialize a new active plane with `--predecessor-archive-id`, which verifies and records the predecessor archive digest;
8. do not ship a compatibility reader in the new evaluator.

The byte budget applies only to the active control plane; immutable archives are measured and governed separately. If the active cap would be exceeded, block evidence-producing controls until a reviewed compaction or rotation preserves ledger entries, content digests, and signature material.

## External signing profile

For projects that selected `sigstore_bundle`, the portable design is a Sigstore blob signature over the canonical archive manifest:

```bash
cosign sign-blob archive-manifest.json --bundle archive-manifest.sigstore.json
cosign verify-blob archive-manifest.json \
  --bundle archive-manifest.sigstore.json \
  --certificate-identity <trusted-workflow-or-maintainer-identity> \
  --certificate-oidc-issuer <trusted-issuer>
```

Store the bundle beside the read-only archive, not inside it. A project release control must validate the expected identity and issuer; cryptographic validity alone is insufficient. Remote signing, key use, paid services, and publication remain explicit-authorization capabilities.

Primary references:

- Codex Skills: <https://learn.chatgpt.com/docs/build-skills>
- Claude memory and project instructions: <https://code.claude.com/docs/en/memory>
- Agent Skills specification: <https://agentskills.io/specification>
- Sigstore blob signing: <https://docs.sigstore.dev/cosign/signing/signing_with_blobs/>
- Sigstore blob verification: <https://docs.sigstore.dev/cosign/verifying/verify/>
- SLSA v1.2: <https://slsa.dev/spec/v1.2/>
