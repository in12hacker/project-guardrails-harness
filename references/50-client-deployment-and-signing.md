# Client Deployment, Revision Trust, and Evidence Sealing

## Deployment contract

The shared Skill is external to the product repository. For repositories used by both Codex and Claude, create two project-local links to the same checkout:

```text
.agents/skills/project-guardrails-harness -> /absolute/path/project-guardrails-harness
.claude/skills/project-guardrails-harness -> /absolute/path/project-guardrails-harness
```

Ignore only these links. Commit `.guardrails/` because it is the project-specific expansion: profile, owners, controls, evidence, decisions, and product acceptance configuration are part of the project. Ignore only runtime lock files.

Keep `AGENTS.md` and `CLAUDE.md` as short generated adapters. `AGENTS.md` points to `.guardrails/INDEX.md` and states project identity plus immediate hard stops. `CLAUDE.md` imports or points to `AGENTS.md`. Do not copy the Skill body into either adapter.

Codex discovers repository skills under `.agents/skills`; Claude discovers them under `.claude/skills`. Both support symlinked Skill directories. The dual link prevents client-specific copies from drifting while leaving the Skill out of product CI and release artifacts.

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

The project ledger is append-only and permanent within a 1 GiB repository-specific budget. Outputs are redacted before persistence and content-addressed by SHA-256. Retention actions may compact duplicate output blobs, but must never rewrite ledger entries or discard the sealed chain head.

When the active schema changes incompatibly:

1. stop active writers and acquire the ledger lock;
2. validate every hash chain and referenced artifact;
3. package the ledger, traceability graph, manifest, registry, output inventory, and final chain heads;
4. compute a package digest;
5. sign that digest externally;
6. store the archive and verification bundle read-only;
7. initialize a new active plane with an explicit predecessor archive digest;
8. do not ship a compatibility reader in the new evaluator.

If the 1 GiB cap would be exceeded, block evidence-producing controls before execution unless a reviewed compaction or archive rotation plan preserves all ledger entries, content digests, and signature verification material.

## External signing profile

The preferred portable design is a Sigstore blob signature over the sealed archive or canonical archive manifest:

```bash
cosign sign-blob archive-manifest.json --bundle archive-manifest.sigstore.json
cosign verify-blob archive-manifest.json \
  --bundle archive-manifest.sigstore.json \
  --certificate-identity <trusted-workflow-or-maintainer-identity> \
  --certificate-oidc-issuer <trusted-issuer>
```

The bundle preserves the signature, signing certificate, and transparency-log verification material. A commercial/release claim must additionally validate the expected identity and issuer; cryptographic validity alone is insufficient. Remote signing, key use, paid services, and publication remain explicit-authorization capabilities.

Primary references:

- Codex Skills: <https://learn.chatgpt.com/docs/build-skills>
- Claude memory and project instructions: <https://code.claude.com/docs/en/memory>
- Agent Skills specification: <https://agentskills.io/specification>
- Sigstore blob signing: <https://docs.sigstore.dev/cosign/signing/signing_with_blobs/>
- Sigstore blob verification: <https://docs.sigstore.dev/cosign/verifying/verify/>
- SLSA v1.2: <https://slsa.dev/spec/v1.2/>
