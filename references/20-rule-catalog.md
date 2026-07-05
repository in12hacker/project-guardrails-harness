# Rule Catalog

Generate rules from these categories. Do not add uncategorized rules unless you first decide the category and owner.

## Contents

1. Evidence Integrity
2. Product/Profile Fit
3. Architecture and Owner Boundaries
4. Domain Model and Parameter Flow
5. Code Cleanliness, State Ownership, and Code Reduction
6. Test and Harness Truthfulness
7. Boundary Robustness
8. Policy, Rule, and Configuration Source of Truth
9. Resilience and Failure Semantics
10. Security, Privacy, and Secret Lifecycle
11. Runtime and Protocol Integrity
12. Supply Chain and Release
13. Operations, Version, and Coverage Truth
14. Rule Lifecycle

## 1. Evidence Integrity

Purpose: stop false completion, stale docs, and local-only claims.

```text
EvidenceGate:
  claim:
  required_evidence:
    code_paths:
    commit:
    local_verification:
    remote_ci:
    runtime_or_product_evidence:
  reject_if:
    - only documentation, issue status, or team assertion is cited
    - local pass is used as mergeability proof without remote CI
    - skipped/manual tests are counted as pass
```

## 2. Product/Profile Fit

Purpose: prevent rules from using the wrong product paradigm.

```text
ProductFitGate:
  project_profile:
  affected_user:
  real_acceptance_surface:
  forbidden_wrong_paradigm:
  usability_or_operability_risk:
  acceptance_evidence:
```

## 3. Architecture and Owner Boundaries

Purpose: make semantic ownership explicit before implementation.

```text
ArchitectureGate:
  stakeholder:
  concern:
  c4_level:
  affected_owner:
  dependency_direction:
  dynamic_view:
  deployment_view:
  data_contract:
  failure_mode:
  adr_lite:
  tests:
```

```text
OwnerRule:
  semantic_key:
  current_owner:                   # team/domain (preferred) or individual; derive from CODEOWNERS first
  ownership_model:                 # strong | weak | collective
  desired_owner:
  allowed_callers:
  forbidden_callers:
  owner_api:
  codeowners_entry:                # the CODEOWNERS line that enforces review (watch the 3 MB silent-failure cap)
  migration_plan:
  verification:
```

```text
ArchitectureDecision:
  context:
  forces:
  decision:
  status: proposed|accepted|superseded|rejected
  consequences:
  alternatives_considered:
  owner:
  verification:
  rollback:
```

## 4. Domain Model and Parameter Flow

Purpose: preserve meaning across layers.

```text
ParameterFlow:
  semantic_key:
  canonical_name:
  call_chain:
  before_aliases:
  before_types:
  before_temp_state:
  after_owner_type:
  mapper_boundary:
  direction: input|output|in_out|owned|borrowed|async_message
  temp_state_removed:
  lossy_roundtrip_removed:
  semantic_regression_tests:
```

Reject patterns:

- domain value becomes string/json/number outside wire/storage boundary;
- same semantic key changes names across layers without boundary reason;
- hidden output through mutable args, maps, globals, or side channels;
- repeated 3+ argument clumps without parameter object;
- bool flags cross module boundaries where enum/state would be clearer.

## 5. Code Cleanliness, State Ownership, and Code Reduction

Purpose: control code bloat and maintainability risk.

```text
CodeCleanlinessGate:
  affected_owner:
  smell_keys:
  files_touched:
  large_files:
  long_functions:
  new_utils_or_helpers:
  new_compat_wrappers:
  state_lifecycle_owner:
  construction_pattern:
  shared_state_injection:
  primitive_roundtrips:
  parameter_flow:
  semantic_regression_tests:
  deletion_or_ratcheting_plan:
```

Smell keys:

```text
duplicate_logic
long_function
large_file
primitive_obsession
data_clump
alias_drift
temporary_state
lossy_roundtrip
type_redefinition
owner_misclassification
shotgun_surgery
divergent_change
speculative_generality
dead_code_or_wrapper
hidden_fallback
test_fixture_duplication
two_step_initialization
orchestrator_god_field
hidden_shared_mutable_state
overengineered_primitive
test_convenience_design_compromise
```

Abstraction is allowed when it removes duplication, preserves a domain type, isolates a backend/runtime boundary, centralizes a state machine, reduces call-site complexity, or enables deleting old paths.

State ownership rules:

- every mutable or degraded state has exactly one lifecycle owner;
- cross-layer readers receive the same owned handle through explicit injection, not global lookup;
- constructors must create valid objects in one step, without post-construction field repair;
- orchestrators wire dependencies, but must not accumulate unrelated subsystem state;
- choose the smallest idiomatic primitive that satisfies lifecycle and concurrency needs.

## 6. Test and Harness Truthfulness

Purpose: ensure tests prove the stated risk.

```text
TestGate:
  product_ref:
  test_ref:
  test_basis:
  risk:
  level: unit|integration|contract|static|real_stack|product_acceptance|release
  size: small|medium|large|manual
  runner:
  positive_cases:
  negative_cases:
  evidence_artifacts:
  cleanup:
  residual_risk:
```

Reject if mock/contract tests are counted as product acceptance for non-contract products.

## 7. Boundary Robustness

Purpose: prevent false green tests around protocol parsers, runtime observers, proxies, agent/tool bridges, kernel/user boundaries, stream assemblers, policy classifiers, or other security-sensitive boundaries.

Use this rule family when a boundary must distinguish target from non-target traffic, parse partial or malformed input, preserve source/session isolation, or enforce before an irreversible side effect.

```text
BoundaryRobustness:
  boundary:
  owner:
  strong_signals:
  weak_signals_allowed_only_as_hints:
  isolation_keys:
  malformed_inputs:
  degraded_or_recovery_state:
  pre_effect_or_commit_point:
  false_positive_cases:
  false_negative_cases:
  known_limitations:
  verification:
```

Reject patterns:

- security behavior depends only on weak hints such as executable name, file name, route name, User-Agent, extension, or path fragment;
- malformed input is silently ignored when it should produce typed degraded/error state;
- one source/session/process/call fragment can contaminate another;
- protocol IDs from different domains are stringified and mixed;
- negative non-target traffic is not tested;
- denial, rollback, or policy enforcement is claimed after an irreversible side effect already happened;
- a mock event is used to claim product acceptance for a runtime boundary;
- a documented limitation is hidden behind a green test instead of recorded with an owner and removal path.

Minimum matrix for boundary tests:

```text
BoundaryTestMatrix:
  positive_strong_signal:
  negative_non_target:
  weak_signal_rejected:
  malformed_degraded:
  cross_source_isolation:
  id_domain_separation:
  effect_target_validation:
  state_precedence:
  recovery_after_bad_input:
  pre_effect_assertion:
```

## 8. Policy, Rule, and Configuration Source of Truth

Purpose: prevent parallel policy semantics and scattered defaults.

```text
PolicySourceOfTruthGate:
  semantic_policy:
  owner_module:
  authoritative_source:
  generated_or_derived_sources:
  forbidden_parallel_sources:
  default_value_owner:
  migration_or_reload_path:
  exclusion_or_override_model:
  performance_index:
  tests:
```

Reject patterns:

- code hardcodes rule skips, allowlists, defaults, or policy branches that should be data;
- route/UI/daemon layer interprets policy independently from the owner engine;
- two storage formats or files define the same semantic rule without an owner mapper;
- rule matching requires unbounded scans on hot paths without an index or budget;
- reload failure silently defaults instead of preserving prior valid state or reporting degraded state.

## 9. Resilience and Failure Semantics

Purpose: make fail-open, fail-closed, degraded, fallback, and recovery behavior explicit per layer.

```text
FailureSemanticsGate:
  layer:
  component:
  default_behavior:
  failure_trigger:
  fail_open_or_closed:
  user_or_system_impact:
  degraded_signal:
  audit_or_trace:
  readiness_or_health_effect:
  previous_valid_state_policy:
  tests:
```

Reject patterns:

- one global fail-open/fail-closed switch for unrelated layers;
- fallback that only logs a warning and does not expose typed state;
- skipped manual/root/device checks recorded as pass;
- degraded state coupled to readiness without a product decision;
- resource limits that stop writes or enforcement silently.

## 10. Security, Privacy, and Secret Lifecycle

Purpose: map trust boundaries and sensitive data handling.

```text
SecurityPrivacyGate:
  trust_boundary:
  assets:
  attacker_or_abuse_case:
  validation:
  authn_authz:
  secret_handling:
  privacy_classification:
  retention_redaction:
  negative_tests:
```

Secret lifecycle rules:

- plaintext secrets exist only at the minimum runtime boundary and lifetime;
- encrypted-at-rest data may persist, but decrypted values must not enter files, logs, audit details, fixtures, screenshots, or browser storage;
- key reload, rotation, and delete paths fail loud when the runtime cannot apply them;
- secret comparisons use constant-time equality when attacker-observable timing is relevant;
- audit records prove access or decrypt actions without leaking values.

## 11. Runtime and Protocol Integrity

Purpose: capture runtime-specific constraints that generic code quality checks miss.

```text
RuntimeProtocolGate:
  runtime_profile:
  platform_constraints:
  protocol_invariants:
  resource_limits:
  boundary_prerequisites:
  no_silent_mock_or_fallback:
  correlation_metadata:
  encoding_and_truncation:
  lifecycle_close_or_flush:
  tests:
```

Examples:

- kernel/eBPF/embedded code needs stack, ABI/layout, verifier, feature, and permission checks;
- proxy/gateway code needs header reconstruction, stream completion, flush/backpressure, timeout, and rate-limit tests;
- text preview or truncation must be encoding-safe;
- runtime capability failures must produce status evidence instead of silently switching to mock;
- event, request, and decision chains need correlation metadata at every adapter boundary.

## 12. Supply Chain and Release

Purpose: prevent overclaiming artifact trust. Calibrate against **SLSA v1.0 Build Track** (L0 none, L1 provenance exists, L2 signed provenance from a hosted builder, L3 hardened/isolated builder). Provenance is worthless unless it is **verified at consumption/deploy**, not only produced.

```text
SupplyChainGate:
  dependency_scan:                 # vuln scan: cargo audit / npm audit / pip-audit / govulncheck
  dependency_admission:            # OpenSSF Scorecard / dependency-review on INCOMING deps
  license_policy:
  lockfile_policy:
  sbom:                            # attestable SBOM predicate
  provenance_level:                # SLSA Build L1 | L2 | L3
  signing:                         # Sigstore/cosign, npm provenance, GitHub artifact attestation
  trusted_publishing:              # OIDC; no long-lived publish tokens
  artifact_verified_at_deploy:     # slsa-verifier / gh attestation verify BEFORE deploy
  workflow_token_permissions:      # least-privilege GITHUB_TOKEN
  action_or_tool_pinning:          # pinned by SHA, not floating tags
  release_claim_level:
```

Claim levels (each backed by evidence, not assertion):

```text
dependency_scan_present
ci_supply_chain_gate_passed
artifact_verifiable                 # signed artifact + SBOM
provenance_verified_at_deploy      # SLSA L2/L3 AND verified, not merely produced
release_grade_supply_chain_assurance
```

Reject if "release-grade" is claimed from a dependency scan alone, or if provenance is produced but never verified at deploy.

## 13. Operations, Version, and Coverage Truth

Purpose: make runtime degradation visible.

```text
OperationsGate:
  runtime_owner:
  readiness_or_health:
  logs:
  metrics:
  audit_or_trace:
  degraded_states:
  retention_cleanup:
  rollback:
  runbook_or_doctor:
```

```text
VersionCoverageGate:
  version_source_of_truth:
  generated_version_consumers:
  sync_check:
  coverage_threshold:
  exclusions:
  exclusion_replacement_evidence:
  pure_logic_exclusion_policy:
  badge_or_report_update:
```

Reject patterns:

- more than one mutable version source without a sync script;
- coverage exclusions without reason, owner, and replacement real-stack/contract coverage;
- pure business logic excluded from coverage because it is hard to test;
- runtime logs, ledgers, or audit files without rotation, retention, and degraded/full-disk behavior.

## 14. Rule Lifecycle

Purpose: prevent stale or unowned rules.

```text
RuleRecord:
  id:
  title:
  category:
  source:
  project_profile:
  risk:
  owner:
  status: proposal|advisory|ratchet|hard_gate|manual_signoff|superseded|deleted
  trigger:
  evidence_required:
  automated_check:
  manual_check:
  false_positive_policy:
  baseline:
  ratchet_plan:
  delete_or_review_by:
  supersedes:
  superseded_by:
  last_verified:
```
