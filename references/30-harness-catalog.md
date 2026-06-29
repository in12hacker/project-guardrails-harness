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
  code_cleanliness:
  policy_source_of_truth:
  failure_semantics:
  security:
  secret_lifecycle:
  runtime_protocol:
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
- **ADR / decision drift** — an accepted architecture decision with no runnable check enforcing it (promote it to a fitness function that fails the PR when violated).

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
