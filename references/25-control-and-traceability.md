# Control And Traceability Model

The quality framework has three machine-maintained sources of truth and one
derived graph.

## Contents

Quality Manifest; Control Registry; Evidence Ledger; Traceability Graph;
Quality Framework Self-Governance.

```text
.guardrails/
  quality-manifest.yaml
  control-registry.yaml
  evidence-ledger.json
  traceability-graph.json       # derived, never independently edited
```

The YAML files use a JSON-compatible YAML subset so the bundled stdlib-only
tools can parse them deterministically. Projects may use full YAML after adding
and governing a YAML parser dependency.

## Quality Manifest

The manifest defines project identity, selected profile, assessed scope,
maturity target, authority boundaries, audit requirements, and applicable
overlays. Missing mandatory decisions block initialization.

## Control Registry

```text
Control:
  id:
  title:
  dimension:
  source_standard:
  source_version:
  project_requirement:
  risk:
  owner:
  applies:
  rationale:
  required_from_maturity:
  scope:
  execution:
    type: command|file_exists|manual|remote|privileged
    command:
    cwd:
    timeout_seconds:
    authorization_required:
  evidence_required:
```

Rules:

- controls express project requirements, not copied standard prose;
- every requirement must have an owner, applicability decision, execution or
  manual evidence path, and maturity level;
- standard IDs include versions when the upstream identifier can move;
- deterministic controls and model judgment are separate;
- `NOT_APPLICABLE` requires a recorded rationale and human confirmation;
- one control may satisfy several requirements, but the mappings remain visible.

Current status and `last_verified` are derived from the evidence ledger for the
requested commit, workspace, scope, registry version, maturity, and audit stage.
They are never hand-maintained in the registry.

## Evidence Ledger

The ledger contains append-only, hash-chained evidence records. It records the
repository revision, full tracked/unignored workspace digest, registry digest,
environment, tool versions, command, exit code, timestamps, output digest,
artifact digest, status, and audit stage. Summaries are not evidence unless
they link to the underlying result. The hash chain is tamper-evident, not a
cryptographic signature; profiles that need non-repudiation must also sign or
store the ledger in an independently controlled system.

## Traceability Graph

```text
business objective
  -> requirement
  -> risk / abuse case
  -> architecture decision and owner
  -> control
  -> test or fitness function
  -> evidence
  -> artifact or deployment
  -> runtime metric / incident feedback
```

Every business requirement must reach at least one risk, control, verification
path, and delivery evidence node. Broken links block `engineering_ready` or the
higher maturity where the requirement applies.

## Quality Framework Self-Governance

The generated framework must test itself:

- schema validation and version migration;
- registry/runner/CI synchronization;
- orphan and duplicate controls;
- stale paths, commands, owners, and standard versions;
- controls without evidence or requirements without controls;
- false-positive/false-negative fixtures for custom rules;
- golden repositories for every supported ecosystem;
- execution timeout, output-size, and secret-redaction behavior.
