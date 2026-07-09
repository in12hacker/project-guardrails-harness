# Harness Catalog

Harnesses prove guardrails. A rule without a harness is advisory until a reliable automated check or manual signoff path exists.

## Gate Levels

| Gate | Purpose | Typical examples |
|---|---|---|
| PR Gate | fast feedback and new-regression prevention | format, lint, typecheck, unit, small integration, contract |
| Closeout Gate | milestone signoff | coverage, e2e, root/device/cloud runner, deferred audit |
| Product Acceptance Gate | proves user/business/security behavior | real user workflow, agent scenario, device flow, enforcement/degraded path |
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
