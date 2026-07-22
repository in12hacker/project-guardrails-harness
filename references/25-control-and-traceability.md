# Control And Traceability Model

The quality framework has one portable meta-contract, federated project truth,
four machine-maintained project records, and derived guidance.

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

The Skill meta-contract owns status, claim, evidence, audit, authorization, and
campaign semantics. The project profile owns applicability. Federated project
rules own domain rule IDs, owners, thresholds, commands, and reject conditions.
Generated Markdown and the traceability graph are derived views and cannot
override those owners. An AI brownfield task or phase outcome requires a
registered campaign revision; a profile cannot redefine `PASS` or weaken claim
semantics.

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
  evaluation_mode: absolute|ratchet_delta
  ratchet_policy:                 # required only for ratchet_delta
    baseline_ref:
    observation_path:
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
- `NOT_APPLICABLE` requires an owner-approved applicability decision with exact
  scope and rationale; a bare `applies=false` is a framework error;
- one control may satisfy several requirements, but the mappings remain visible.

Capability requirements, federated mappings, cleanup debt, and design-scope
exemptions are distinct records. A mapping is
`current|stale|disputed|unmapped`: source digest drift makes it `stale`, while a
same-tier or semantic-owner conflict makes it `disputed`. A disputed mapping
emits `BLOCKED` with `blocker_kind=policy_conflict`; an unmapped mandatory
project rule is a framework failure.

Initialization inventories detected project instruction sources as mandatory
`unmapped` records with source digest and observation time. It does not parse or
copy their rules. A project owner maps each source to semantic owner and control
references, records review time, and changes status through a reviewed registry
edit. Until then, runs may collect evidence but claims remain blocked.

`ratchet_delta` commands write one JSON observation at `observation_path` with
`baseline_ref`, baseline revision/digest/count, `current_count`, `new_count`, and
`fixed_count`. The evaluator verifies `current = baseline - fixed + new`. Open
debt keeps the control `FAIL`; only a registered task/phase exit policy may use
the immutable delta to produce `COMPLETED`. Project/release evaluation never uses
the ratchet exception.

Current status and `last_verified` are derived from the evidence ledger for the
requested subject tree, scope, registry version, maturity, and audit stage.
They are never hand-maintained in the registry.

## Evidence Ledger

The ledger contains separate append-only, hash-chained run, audit, and claim
records. Each record separates:

- `subject_binding`: latest commit that changed non-evidence content, a digest
  of the tracked/unignored non-evidence tree, manifest, registry, traceability,
  and bound Skill digests;
- `storage_binding`: evidence/result digest or supporting ledger chain heads.

It also records environment, tool versions, command, exit code, timestamps,
output digest, artifact digest, status, and audit stage. Summaries are not evidence unless
they link to the underlying result. The hash chain is tamper-evident, not a
cryptographic signature; profiles that need non-repudiation must also sign or
store the ledger in an independently controlled system.

The Git commit that stores a ledger head is derived from repository history or
an external attestation; it is not embedded into the content it commits. A
storage-only descendant commit leaves evidence current when the subject digest
is unchanged. Source, manifest, registry, traceability, project-rule, or Skill
assurance changes make affected evidence stale.

Inherited evidence is provenance, not a control status. Treat it as
provisional until a current verifier confirms matching control, scope, input,
dependency, environment, and artifact digests. Cross-audit must be able to read
the original redacted output, not only its digest. Privileged, manual, or
external evidence must carry an explicit freshness policy and expiry.

Persisted output is content-addressed and verified again before every run or
claim. The ledger stores a full-stream digest/byte count plus a bounded redacted
review copy, its digest, and an explicit truncation flag. Missing or modified
review output is a framework integrity failure.

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

- schema validation and rejection of unsupported versions;
- registry/runner/CI synchronization;
- orphan and duplicate controls;
- stale paths, commands, owners, and standard versions;
- controls without evidence or requirements without controls;
- false-positive/false-negative fixtures for custom rules;
- golden repositories for every supported ecosystem;
- execution timeout, output-size, and secret-redaction behavior.
- source-ref deduplication and permanent exclusion of generated control planes;
- two-run canonical-digest idempotency;
- candidate validation before a rollback-capable transactional replacement;
- read-only help/check/plan behavior, expected-input binding, exact write-set
  closure, zero-write convergence, stale-plan rejection, protected-scope
  preservation, and injected-failure rollback for every control-plane mutator;
- bounded, aggregated diagnostics with count and representative samples.

## Semantic Closure

Any behavior that can change a claim needs all five representations: one named
semantic owner, a machine-readable field, deterministic validation/evaluation,
positive and adversarial drift tests, and generated guidance derived from the
machine model. If any representation is missing, treat the behavior as an
unenforced design intent; a project adapter may report observations but must not
invent the missing status or claim policy.

Generated control-plane state adds a sixth constraint: mutation authority is
separate from semantic authority. A generator may write only its declared
machine-owned paths and must prove that project-owned paths remain unchanged.
Byte-identical output alone is insufficient when a nominally read-only mode
performed transient writes, rewrote metadata, or left temporary files.
