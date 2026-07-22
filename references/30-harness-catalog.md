# Harness Catalog

Harnesses prove guardrails. A rule without a harness is advisory until a reliable automated check or manual signoff path exists.

## Contents

Gate Levels; Harness Matrix; Ecosystem Hints; Architecture and Fitness Checks;
Test/Contract/Documentation Checks; Execution Closure Candidates;
Policy/Cleanliness/Failure/Secret Checks; Runtime and Boundary Robustness;
Version/Coverage/Product Acceptance;
Runner and Performance Policy; Control Evidence; Claims; Production and
Commercial Harnesses.

## Gate Levels

| Gate | Purpose | Typical examples |
|---|---|---|
| PR Gate | fast feedback and new-regression prevention | format, lint, typecheck, unit, small integration, contract |
| Closeout Gate | milestone signoff | coverage, e2e, root/device/cloud runner, deferred audit |
| Product Acceptance Gate | proves user/business/security behavior | real user workflow, agent scenario, device flow, enforcement/degraded path |
| Production Readiness Gate | proves operability and recovery | SLO, capacity, alert, restore, rollback, incident exercise |
| Commercial Delivery Gate | proves distributability and supportability | UX/a11y/i18n, install lifecycle, notices, support and release authority |
| Release Gate | proves artifact integrity | clean build, SBOM, provenance, signing, install/upgrade/rollback |

## Harness Matrix

```text
HarnessMatrix:
  format:
  lint:
  typecheck_or_compile:
  unit:
  integration:
  contract:
  static_architecture:
  module_readiness:
  fitness_registry:
  interface_contract:
  documentation_deliverables:
  code_cleanliness:
  policy_source_of_truth:
  failure_semantics:
  security:
  secret_lifecycle:
  runtime_protocol:
  boundary_robustness:
  version_coverage:
  coverage:
  performance:
  e2e:
  product_acceptance:
  requirement_traceability:
  production_readiness:
  commercial_delivery:
  ai_assurance:
  audit_independence:
  release:
```

## Ecosystem Hints

| Ecosystem | Common PR gates | Security/supply-chain gates |
|---|---|---|
| Rust | `cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test` | `cargo audit`, `cargo deny`, `cargo llvm-cov`, fuzz targets |
| Node/TS | `npm run lint`, `npm test`, `npm run build`, Playwright/Vitest | `npm audit`, lockfile diff, dependency review |
| Python | `ruff`, `mypy/pyright`, `pytest` | `pip-audit`, `bandit`, lockfile/uv/poetry checks |
| Go | `gofmt`, `go vet`, `go test ./...` | `govulncheck`, `gosec`, module checksum |
| Java/Kotlin | Gradle/Maven test/check | OWASP Dependency-Check, SpotBugs, Snyk/OSV |
| Containers/IaC | image build, policy tests | Trivy/Grype, Checkov/tfsec, cosign-signed images |

Release-grade supply-chain tooling (2026): produce **Sigstore-signed build provenance** (`gh attestation build`, npm `--provenance`, `cosign sign`), publish via **Trusted Publishing / OIDC** (no long-lived registry tokens), and **verify at deploy** (`gh attestation verify`, `slsa-verifier`, OPA Gatekeeper for admitted images). Gate incoming dependencies with **OpenSSF Scorecard** / GitHub dependency-review. Provenance that is produced but not verified at consumption is not assurance.

## Static Architecture Checks

- forbidden dependency direction;
- route/controller/UI layer becoming semantic owner;
- missing owner for config/rule/audit/domain identity;
- raw JSON/primitive domain round-trip;
- ABI/wire changes without compatibility tests;
- stale path or command in rules;
- unregistered or orphaned check scripts;
- module declared stable without readiness evidence;
- **ADR / decision drift** — an accepted architecture decision with no runnable check enforcing it (promote it to a fitness function that fails the PR when violated).

## Declarative Rule Engine (Three-Layer Fitness Architecture)

When a project accumulates many per-milestone or per-concern check scripts, consolidate them into a **declarative rule engine** rather than writing N scripts. Pattern observed in AgentShield:

| Layer | Tool | Scope | Gate? |
|-------|------|-------|-------|
| 1. Generic quality | clippy restriction lints (`workspace.lints`) | unwrap/panic/dbg/print (stable, zero-cost) | yes (compiler deny) |
| 2. Semantic invariants | declarative TOML rules + single generic engine | sole_producer / no_pattern / invariant_lock / location / forbidden_edge | yes (CI) |
| 3. Structure exploration | cargo-modules / cargo-depgraph | module tree visualization | no (diagnostic) |

Key principles:
- **Layer 1 first**: if clippy or a native lint covers it, do not write a custom script.
- **Layer 2 for project-specific semantics**: rules live in a TOML/YAML data file; a single generic engine executes them. Adding a new invariant = adding a data block, not writing a new script.
- **Layer 3 is never a gate**: exploration tools have false positives (e.g., cargo-modules `--acyclic` false-positives on inherent impls); use them for developer insight only.
- **Occam's razor**: before creating a new check script, verify no existing tool (clippy, cargo-deny, cargo-audit, readelf, curl) already covers the need.

## Module Readiness and Fitness Registry

```text
ModuleReadinessHarness:
  module:
  readiness_dimensions:
    owner:
    dependency_direction:
    interface_boundary:
    documentation:
    tests:
    error_or_panic_policy:
    dead_code_or_wrapper_policy:
    size_or_complexity:
  checks:
  exceptions:
  delete_or_review_by:
```

```text
FitnessRegistry:
  checks:
    - id:
      dimension:
      script_or_policy:
      command:
      gate:
      scope:
      owner:
      baseline_or_ratchet:
      pass_fail_semantics:
  orphan_checks:
  checks_to_delete:
```

Refactor requests should cite a violated readiness dimension, owner boundary, rule, or fitness function. If the project keeps baselines or allowlists, separate design-scope exemptions from cleanup debt. Known violations must remain visible with owner and deletion/review path; a baseline is not proof that the issue is acceptable.

## Test Basis and Scenario Origin

```text
TestBasisHarness:
  product_or_requirement_ref:
  risk_or_regression:
  level:
  size:
  runner:
  scenario_origin: real_product|cli_equivalent|sensor_smoke|mock_contract
  evidence_artifacts:
  cleanup:
  residual_risk:
```

Tests used in completion, closeout, product, or release claims need traceability to a requirement, risk, bug, or regression. Downgrade direct API shortcuts, synthetic events, low-level probes, and mocks when they bypass the product behavior being claimed.

## Execution Closure Harness Candidates

Use these models when an effect crosses an execution boundary such as a
container, browser, device, remote runner, cloud environment, or GPU worker.
They remain `proposal` candidates until owner review, compatibility analysis,
positive fixtures, and false-positive fixtures are complete. Candidate
validation returns `CANDIDATE_VALID`, never a control `PASS`, and does not read
or write the v3 evidence ledger.

```text
ExecutionObservation:
  observation_id:
  hop_id:
  capability_id:
  depends_on:                 # temporal/prerequisite DAG edges
  flow_depends_on:            # execution/data-flow DAG edges
  effect_id:                  # required for effect lifecycle + product assertion
  effect_result:              # committed|prevented on outcome/assertion; null otherwise
  required_capability_ids:    # non-empty only for effect_attempt
  run_id:
  execution_state: executed|failed|not_executed
  phase: pre_effect|effect|post_effect
  vantage_point: host|container|browser|device|remote_runner|cloud|gpu
  target:
  command_digest:
  started_at:
  finished_at:
  result_digest:
  status:
  subject_sha256:
  authorization_id:
  assertion_kind: capability_preflight|target_context_readiness|effect_attempt|effect_execution_step|effect_commit|effect_outcome|product_assertion|cleanup
  artifact_ref:
  evidence_kind: runtime|static_reachability
```

```text
EntrypointClosureHarness:
  entrypoint:
  preconditions:
  authorization_boundary:
  effect_attempts:             # exact effect_attempt observation IDs
  effect_execution_steps:      # exact intermediate execution/data-flow observation IDs
  effect_commit_points:        # exact commit IDs; empty for prevented-only runs
  effect_outcomes:             # exact effect_outcome observation IDs
  runtime_assertions:          # exact product_assertion observation IDs
  required_artifacts:
  offline_verifier:
  cleanup_observations:        # exact cleanup observation IDs
  cleanup_owners:              # exact owners derived from cleanup observations
  failure_paths:               # structured path ID + exact cleanup IDs/owners
  static_evidence:             # artifact_ref + SHA-256 + static_reachability
```

```text
ExternalAcquisitionEnvelope:
  capabilities:
    - capability_id:
      hop_id:
      owner:
      target:
      vantage_point:
      authorization_required:
  authorization:
    authorization_id:
    required:
    granted:
  artifact_set:                  # exact, not a minimum subset
```

```text
ExecutionHop:
  hop_id:
  owner:
  target:
  vantage_point:
  depends_on:                    # hop DAG edges
```

```text
ProtectionEdge:
  capability_id:
  effect_id:
  preflight_observation_id:
  readiness_observation_id:
```

The closure contract requires both evidence classes:

- digest-bound static composition artifacts support review that the production
  entrypoint can reach the authorization boundary, effect lifecycle,
  assertions, and cleanup path; the proposal validator checks their closure,
  not their project-specific semantic truth;
- runtime observations prove those paths actually executed from each declared
  vantage point against the selected target.

Static reachability never substitutes for runtime execution. Every required
observation must be `executed` and `PASS`, bind the same run, subject, and
authorization, reference a declared capability and hop, and close exactly the
declared artifact set. Each capability owns its target and vantage point; a
container capability and a host capability are separate declarations rather
than a false shared context. Multiple observations may use the same assertion
kind.

The contract deliberately separates two relations:

- the hop graph plus `flow_depends_on` records execution/data flow, such as
  browser to container to host to assertion;
- `depends_on` plus protection edges records prerequisite order, allowing host
  or device readiness to precede an effect initiated from an upstream hop.

All graphs must be acyclic and timestamps must agree with temporal edges. Every
flow edge must also have temporal order, follow the hop DAG, and witness each
direct hop dependency. Each effect has exactly one attempt and outcome, plus
zero or more intermediate execution steps. A `committed` outcome requires
exactly one commit; a `prevented` outcome forbids a commit. The attempt declares
its complete `required_capability_ids`; these must exactly match protection
edges whose preflight precedes readiness and whose readiness precedes the
attempt and any commit. This prevents a post-attempt preflight from being
presented as protection and lets deny/no-side-effect paths remain honest.

Closure fields are references, not descriptions: attempt, execution-step,
commit, outcome, assertion, and cleanup ID sets must exactly match runtime
observations. Failure paths bind exact cleanup IDs and owners; static evidence
binds project-relative artifacts and digests. Every declared hop and capability
must be used by runtime observation; omit non-participants from the run
candidate. Product assertions bind one effect and repeat its observed
`committed|prevented` result, require that effect's outcome in both temporal and
flow ancestry, and never turn a prevented effect into a fabricated commit.
Cleanup requires temporal outcome ancestry, and every effect requires assertion
and cleanup descendants.
`not_executed`, unused declarations, arbitrary closure text,
capability/hop mismatch, post-attempt preflight, absent flow or protection
edges, run mismatch, failed cleanup, missing artifact, or unknown extra
artifact rejects the candidate.

Candidate format `2.0` replaces the rejected single-hop proposal. It is not a
v3 evidence schema and has no compatibility reader. Promotion into the active
control plane remains forbidden until owner and compatibility review complete.

The portable validator and fixtures are runnable without project-specific
dependencies:

```bash
python3 "$SKILL_DIR/scripts/validate_harness_candidate.py" candidate.json
python3 -m unittest -v \
  tests.test_quality_framework.QualityFrameworkTest.test_portable_execution_harness_candidate_accepts_only_closed_runtime_chain
```

Promotion into active controls requires a separate owner decision and schema
compatibility review. If future integration needs new ledger fields, treat it
as a next-schema design; do not extend v3 silently and do not add a compatibility
reader.

## Control-Plane Mutation Harness Candidates

Use this proposal model for project adapters, regenerators, migrations,
formatters, and configuration tools that can rewrite normative or derived
state. It is deliberately separate from execution-closure evidence: the proof
subject is a state transition, not a product effect. Candidate validation is
offline structure/closure validation and never executes the declared command.

```text
MutationContract:
  operation_id:
  owner:
  command_sha256:
  mutable_paths:                  # exact canonical write boundary
  protected_paths:                # project-owned preservation boundary
  protection_rationale:           # required, including when protected_paths is empty
  planned_output_sha256:

MutationObservation:
  observation_id:
  kind: help|invalid_invocation|check_clean|check_drift|plan|apply|repeat_apply|stale_plan|injected_failure
  sequence:
  run_id:
  command_sha256:
  environment_sha256:
  execution_state: executed
  outcome:
  exit_code:
  input_tree_sha256:
  expected_input_sha256:
  output_tree_sha256:
  protected_tree_sha256:
  plan_sha256:
  planned_write_set:
  attempted_write_set:
  committed_write_set:
  residual_paths:
  artifact_ref:
  artifact_sha256:
```

The candidate requires exactly one observation of every kind. Help, invalid
invocation, clean/drift check, and plan are read-only. Plan declares the exact
write set. Apply binds the same plan and expected input, writes exactly the
declared paths, preserves the protected digest, and reaches the declared output
digest. Repeating apply against that output performs no attempted or committed
writes. A stale-plan fixture starts from an independent conflicting digest and
must reject before writing. An injected failure must attempt a non-empty subset
of the allowed paths, restore the original digest, commit nothing, and leave no
residual path. Every observation binds one command and environment identity.
An empty protected path set is allowed only as an explicit reviewed boundary;
the rationale remains mandatory so greenfield/full-ownership tools do not force
invented paths and brownfield tools cannot silently erase preservation scope.

This is stricter than comparing final bytes twice: a tool that rewrites the
same bytes, mutates timestamps, touches undeclared paths, accepts a stale plan,
or cleans up only on its success path is not a conforming mutator. Project
harnesses own how filesystem observations are collected and how command modes
map to these semantic kinds.

```bash
python3 "$SKILL_DIR/scripts/validate_mutator_candidate.py" candidate.json
python3 -m unittest -v \
  tests.test_quality_framework.QualityFrameworkTest.test_mutator_candidate_requires_read_only_checks_and_transactional_convergence
```

Format `1.0` is a proposal outside the v3 evidence ledger. A structurally valid
candidate still needs project-owner review, real command execution, positive
and adversarial fixtures, and an explicit control integration decision.

## Interface Contract Checks

```text
InterfaceContractHarness:
  owner:
  consumers:
  public_surface:
  typed_inputs:
  typed_outcomes:
  typed_errors:
  wire_domain_mapper:
  sync_async_boundary:
  compatibility_or_delete_by:
  contract_tests:
```

Check that public interfaces are shaped by real consumers, use typed domain boundaries, separate wire DTOs from domain types, and avoid long-lived compatibility wrappers.

The verifier must consume the producer's real, versioned outcome contract. Bind
producer and verifier to the same contract digest and test success, typed
failure, empty/minimal success bodies, unknown fields, and postcondition truth.
A verifier-created response shape or a static call-reachability check cannot
substitute for producer behavior.

## API Stability Checks

Make semantic versioning falsifiable instead of asserted. A library or service
that claims semver without an executable check is relying on reviewer memory.

```text
APIStabilityHarness:
  selected_public_contracts:       # explicit profile decision
  public_api_snapshot:              # rustdoc-json + public-api diff (library); equivalent per ecosystem
  api_equals_version:               # API version bound to binary/artifact version (service/VMM mode)
  openapi_breaking_check:           # oasdiff / buf breaking:FILE for HTTP/gRPC contracts
  semver_enforcement:               # cargo-smart-release / semantic-release / release-please
  consumer_contract_test:           # downstream-consumer-driven contract test
  per_crate_changelog:              # each publishable crate has its own CHANGELOG when independently versioned
```

Design rules:

- pick the form that matches the product: a library uses a public-API snapshot
  diff; a versioned service binds API version to artifact version; an
  HTTP/gRPC API uses a breaking-change detector on the spec;
- a snapshot gate fails the PR when the public surface changes without a
  matching version bump or an explicit `bless`;
- per-crate changelogs are required when crates are independently versioned and
  published, not optional documentation;
- a breaking change that ships without the gate catching it is a harness gap,
  not just a release incident.

## Workspace Build Boundary Checks

For workspaces that mix build forms (userspace + `#![no_std]`/kernel, host +
cross target, std + `alloc`-only), encode the boundary so the default build and
CI matrix are self-describing.

```text
WorkspaceBoundaryHarness:
  selected_build_topology:         # explicit profile decision
  default_members_declaration:      # default-members / exclude in the workspace manifest
  per_target_build_matrix:          # CI builds every declared target/form, not just the default
  shared_abi_crate:                 # single -common crate owning repr(C)/wire types both sides consume
  cross_form_dependency_rule:       # static check forbidding userspace→kernel/no_std reverse deps
  build_form_isolation_test:        # building one form does not silently compile the other
```

## Documentation Deliverable Checks

```text
DocumentationDeliverableHarness:
  live_docs:
  sync_later_docs:
  required_sections:
  public_api_index:
  dependency_or_owner_index:
  modification_risk:
  tests_or_commands:
  duplicate_sources:
```

Live source-of-truth docs should change atomically with code. Longer design/tutorial/report docs can sync later only when that stale window is explicit.

## Policy Source-of-Truth Checks

```text
PolicyHarness:
  owner_engine_path:
  config_or_rule_sources:
  forbidden_hardcoded_defaults:
  forbidden_parallel_interpreters:
  reload_or_migration_tests:
  hot_path_index_or_budget_tests:
```

Look for duplicated policy semantics in routes, UI, daemon wiring, migrations, scripts, and test fixtures. A UI can present or edit policy only through the owner API; it must not define its own rule meaning.

## Code Cleanliness Checks

```text
CleanlinessHarness:
  large_file_threshold:
  long_function_threshold:
  forbidden_new_file_names: [utils, helpers, common, misc]
  wrapper_markers: [compat, legacy, deprecated]
  debt_markers: [TODO, FIXME, HACK]
  primitive_roundtrip_patterns:
  parameter_alias_patterns:
  owner_boundary_patterns:
  baseline_file:
  ratchet_mode: advisory|new_violations_fail|hard_fail
```

Additional checks:

- post-construction assignments that repair invalid constructor state;
- orchestrator structs accumulating unrelated subsystem state;
- hidden globals or shared mutable state that bypass constructor injection;
- repeated argument clumps that need parameter objects;
- test fixture duplication of business semantics instead of owner builders.
- custom assertions or builders for repeated gate fixtures instead of copied parser/policy/normalizer logic.

## Failure Semantics Checks

```text
FailureHarness:
  layer_matrix:
  fail_open_closed_cases:
  degraded_status_checks:
  previous_valid_state_tests:
  full_disk_or_limit_tests:
  missing_runner_policy:
```

Each fallback path must assert user/system impact and visible status. Root/device/cloud/manual missing checks are `blocked_by_env` or `manual_signoff`, never pass.

## Secret Lifecycle Checks

```text
SecretLifecycleHarness:
  secret_sources:
  encrypted_at_rest_paths:
  plaintext_runtime_boundaries:
  forbidden_log_or_file_patterns:
  browser_storage_checks:
  reload_rotation_delete_tests:
  constant_time_compare_tests:
```

Use both static scans and negative runtime tests. The goal is not only "no obvious key in repo", but proving decrypted values do not persist outside the approved runtime boundary.

## Runtime and Protocol Checks

```text
RuntimeProtocolHarness:
  runtime_profile:
  platform_preflight:
  resource_limit_tests:
  abi_or_wire_layout_tests:
  protocol_completion_tests:
  flush_backpressure_timeout_tests:
  encoding_safety_tests:
  correlation_chain_tests:
```

Examples: eBPF verifier/build checks, mobile device permissions, browser CDP workflows, proxy streaming completion, API pagination, UTF-8-safe previews, and shutdown/flush contracts.

## Boundary Robustness Harness

Use this harness for protocol classifiers, streaming parsers, runtime observers, proxies, agent/tool bridges, kernel/user boundaries, and security enforcement points. It catches false positives, false negatives, broken isolation, silent degradation, and post-effect enforcement claims that ordinary unit/integration/e2e gates often miss.

```text
BoundaryRobustnessHarness:
  boundary_name:
  owner_module:
  product_risk:
  strong_signal_positive_tests:
  weak_signal_negative_tests:
  non_target_false_positive_tests:
  malformed_or_partial_input_tests:
  cross_source_isolation_tests:
  id_domain_separation_tests:
  effect_target_validation_tests:
  state_precedence_tests:
  recovery_after_bad_input_tests:
  pre_effect_or_commit_point_tests:
  observability_or_degraded_tests:
  cleanup:
```

Design rules:

- Start with the real boundary contract, not convenient fixture names.
- Separate recognition, parsing, state transition, enforcement timing, and product acceptance tests.
- Test weak hints as negative cases unless the product explicitly accepts hint-only degraded behavior.
- Use table tests for classifier permutations, but stateful tests for fragmentation, batching, retries, timeout, and recovery.
- Assert the commit point. For security products, prove the file write, process start, network send, data export, or policy commit did not happen before allow; if that is impossible, record observe-only/degraded residual risk.
- Add at least one non-target traffic case that looks similar to the target protocol.
- Add at least one malformed input that must be visible through typed error, degraded status, or audit evidence.
- Do not let a downstream failure hide an upstream success. When testing observer timing, it is valid to force the downstream dependency to fail if the test asserts observer state before the failure point.

## Version and Coverage Checks

```text
VersionCoverageHarness:
  version_sync_command:
  generated_consumer_check:
  coverage_command:
  exclusion_inventory:
  exclusion_replacement_evidence:
  pure_logic_exclusion_fail:
```

Coverage exclusions are allowed only when they are generated, platform-impossible in PR, or replaced by stronger real-stack/product evidence. They need owners and review dates.

## Schema and Protocol Evolution Checks

For products with persistent state (databases, indexed stores, on-disk formats)
or versioned wire contracts (protobuf, OpenAPI, gRPC), a schema change is a
release risk that a unit test cannot catch. Add an evolution harness so
forward/backward compatibility is proven, not asserted.

```text
SchemaEvolutionHarness:
  selected_persistent_state:       # explicit profile decision
  breaking_change_detection:        # buf breaking:FILE / oasdiff / sqlx migrate check / custom format-diff
  forward_backward_compat_test:     # declarative cross-version upgrade + downgrade against fixtures
  data_migration_safety:            # N-1→N forward migration + N→N-1 rollback, with content checksums
  persistence_change_classification:# change classified: forward-compat / breaking / data-correcting
  fixture_checksum_verification:    # SHA-256 of canonical fixtures to detect silent format drift
```

Design rules:

- the breaking-change detector runs on the schema/contract source, not only on
  generated code;
- a cross-version upgrade test boots the old version's persisted state, upgrades,
  and asserts behavior; a downgrade test proves rollback is possible (or records
  the irreversible residual risk);
- a data-correcting migration (not just schema-additive) needs a separate,
  replayable test because it transforms existing rows/documents;
- a breaking change that lands without the detector catching it is a harness gap.

## Product Acceptance Rules

Use the real product stimulus:

- Web app: browser workflow against real backend or staged service.
- Library: downstream sample integration or contract consumer test.
- CLI: real command invocation with filesystem/stdin/stdout/stderr assertions.
- Security product: real enforcement/allow/deny/degraded path.
- AI agent system: real agent tool call/session, not direct API shortcut.
- Mobile/embedded: real device/simulator/hardware-in-loop where risk requires it.

## Missing Runner Policy

If root, device, GPU, cloud, paid service, or secret-backed runner is missing:

- mark `blocked_by_env`;
- record exact prerequisite;
- provide rerun command;
- do not mark pass;
- decide whether PR can merge with residual risk or must wait for closeout.

## Performance Harness Policy

Wall-time-only benchmark output is a signal, not always a hard gate. Hot-path rules should prefer:

- query/iteration counters;
- allocation counts;
- complexity-specific test fixtures;
- benchmark threshold with stable baseline;
- trace evidence for real runtime paths.

## Control Execution And Evidence

Every gate maps to one or more controls in `control-registry.yaml`. A control
execution must record:

```text
ControlRun:
  control_id:
  commit_and_scope:
  command_or_manual_procedure:
  environment_and_tool_versions:
  started_at_and_duration:
  exit_status_and_result:
  output_digest_and_artifacts:
  actor_and_audit_stage:
  freshness_or_expiry:
```

Commands are argv arrays owned by the project. Missing root, device, cloud,
secret, paid, remote, production, dependency-install, or privileged access is
`BLOCKED` pending separate authorization; it is never silently attempted or
reported as PASS.

## Claim Gate

The claim gate is independent from individual test commands. It checks that:

- every applicable control for the requested task, maturity, scope, and market
  is current `PASS` on the assessed commit;
- required self, cross, release-authority, and third-party audit stages have
  passed independently;
- traceability has no broken or orphaned required links;
- the evidence ledger has no contradictory current result;
- a subproject assessment is not presented as whole-product assurance.

Human brownfield policy may permit feature development when all affected
task-scoped controls pass and debt does not increase. The global debt control
stays failed, so production/commercial readiness claims remain blocked.

## Production And Commercial Harnesses

Production evidence includes executed capacity/load tests, SLO calculations,
alert delivery and response, backup restore, rollback, incident exercises,
security response, and DORA trend collection. Commercial evidence includes real
user journeys, WCAG-targeted accessibility testing, locale/fallback behavior,
install/upgrade/rollback/uninstall, licensing/notices, support lifecycle, and
artifact verification.

Use real environments where the risk requires them. Synthetic, mock, or
document-only evidence must identify the residual gap and cannot satisfy a
control that explicitly requires product or production execution.

## AI-Assisted Contribution Harness

Distinct from product AI-assurance evidence: this harness verifies that a
project which explicitly accepts or restricts external contributions has codified how AI-assisted
(copilot, agentic, generated) contributions are disclosed, reviewed, and
licensed. Applicability comes from `external_contributions`, not distribution or
`ai_system`. Foundation and project policies are comparative evidence, not a
universal mandatory stance.

```text
AIContributionHarness:
  selected_policy:                  # allowed | restricted | prohibited
  contribution_policy_location:     # CONTRIBUTING.md / AI_POLICY.md / DCO / CLA referencing AI
  disclosure_requirement:           # none | encouraged | required (with tag/keyword)
  review_standard_parity_check:     # CI/label rule: AI-tagged PRs are not exempted from any gate
  licensing_attestation:            # DCO/CLA covers AI output; contributor attests rights
  documented_or_not_applicable:     # explicit "no special policy" is valid; silence is not
```

Evidence is the policy document plus the CI/label configuration that enforces
parity. A policy that exists only in prose, with no gate treating AI-tagged PRs
identically to human PRs, is advisory, not a harness.
