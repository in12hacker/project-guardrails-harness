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
15. Module Readiness and Fitness Functions
16. Interface and Port Contracts
17. Documentation Deliverables
18. Requirement, Risk, and Control Traceability
19. Product Experience and Lifecycle
20. Production Readiness and Operations
21. Commercial Delivery and Governance
22. AI Assurance Overlay

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

```text
WorkspaceBoundaryGate:
  selected_build_topology:          # explicit profile decision
  build_boundary:                   # default-members / exclude / per-target build matrix
  mixed_form_crates:                # no_std/kernel/firmware vs userspace/std physical isolation
  shared_abi_owner:                 # single crate owning the cross-form ABI / repr(C) types
  forbidden_cross_form_dependency:  # e.g. userspace reverse-depending on a kernel/no_std crate
  verification:
```

Use this rule when the profile explicitly selects `multi_form` or `cross_target`;
repository paths may support the decision but cannot make it. Examples include
userspace + `#![no_std]`/kernel, host + cross-compiled target, and std +
`alloc`-only. Reject patterns:

- a build form that silently fails the default `cargo build` because it needs a
  non-default target or linker, with no `default-members` or documented matrix;
- shared wire/ABI types duplicated on both sides of a form boundary instead of
  owned by one `-common` crate consumed by both;
- a userspace/std crate depending on a `#![no_std]`/kernel crate (or vice versa)
  without an explicit, owned cross-form contract;
- a per-target build matrix that is folklore, not encoded in CI or a build tool.

The boundary is owned by the workspace, not by individual crates: the single
source of truth is the `default-members`/exclude declaration plus the shared-ABI
crate, both enforced by CI.

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

Test code is not a governance exception. Gate-level tests should use owner APIs, semantic builders, and custom assertions instead of copying production parsers, policy matchers, normalizers, or state-machine logic into fixtures.

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
  scenario_origin: real_product|cli_equivalent|sensor_smoke|mock_contract
  positive_cases:
  negative_cases:
  evidence_artifacts:
  cleanup:
  residual_risk:
```

Reject if mock/contract tests are counted as product acceptance for non-contract products.

Reject gate tests that have no requirement/test basis, risk or regression link, runner prerequisites, cleanup policy, or scenario origin. Direct API calls, synthetic events, low-level sensor probes, and mocks may be useful lower-layer evidence, but must be downgraded when they bypass the product behavior being claimed.

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

Purpose: prevent overclaiming artifact trust. Calibrate against the stable
**SLSA v1.2 Build and Source Tracks** and the selected project profile.
Provenance is worthless unless it is verified at consumption/deploy, not only
produced.

```text
SupplyChainGate:
  dependency_scan:                 # vuln scan: cargo audit / npm audit / pip-audit / govulncheck
  dependency_admission:            # OpenSSF Scorecard / dependency-review on INCOMING deps
  license_policy:
  lockfile_policy:
  sbom:                            # attestable SBOM predicate
  source_and_build_level:          # selected SLSA v1.2 Source/Build requirements
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
provenance_verified_at_deploy      # selected SLSA requirements AND verified
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

## 15. Module Readiness and Fitness Functions

Purpose: make "stable", "ready", and "stop refactoring" objective instead of preference-driven.

```text
ModuleReadiness:
  module:
  owner:
  status: production_ready|provisionally_ready|not_ready
  dimensions:
    single_owner:
    dependency_direction:
    typed_interface_boundary:
    documentation:
    tests:
    error_or_panic_policy:
    dead_code_or_wrapper_policy:
    size_or_complexity:
  exceptions:
  delete_or_review_by:
  verification:
```

```text
FitnessFunction:
  id:
  dimension:
  script_or_policy:
  gate: pr|closeout|product_acceptance|release|manual
  scope:
  owner:
  command:
  baseline_or_ratchet:
  pass_fail_semantics:
  last_verified:
```

Reject patterns:

- a module is declared stable without explicit readiness dimensions and evidence;
- a reviewer forces refactoring from taste rather than a violated rule or fitness function;
- a check script exists but is not registered, owned, called by a gate, or intentionally deleted;
- dependency direction or architecture rules are hardcoded in scripts when a declarative rule source is practical;
- "stable" is claimed while known violations remain unowned or hidden in allowlists.

## 16. Interface and Port Contracts

Purpose: keep public interfaces, ports, traits, SDK/API contracts, and cross-module signatures typed, consumer-driven, and evolvable.

```text
InterfaceContract:
  owner:
  consumers:
  capability_or_contract:
  methods_or_endpoints:
  typed_inputs:
  typed_outcomes:
  typed_errors:
  wire_domain_mapper:
  sync_async_boundary:
  object_or_dynamic_dispatch_policy:
  compatibility_or_delete_by:
  contract_tests:
```

Reject patterns:

- interface shape is invented for future use instead of real consumers;
- business meaning crosses module boundaries as string/json/number/bool when a domain type or enum exists;
- wire DTOs and domain types are conflated without an explicit mapper;
- sync interfaces become async for style, or async I/O is hidden behind sync calls;
- long-lived compatibility wrappers replace same-change migration or a dated delete path;
- public errors collapse typed failure, degraded, timeout, and unavailable outcomes into strings or generic errors.

## 17. Documentation Deliverables

Purpose: make documentation freshness and ownership explicit.

```text
DocumentationDeliverable:
  doc:
  tier: live_source_of_truth|milestone_or_release_sync|archival
  owner:
  update_trigger:
  code_paths_or_contracts:
  required_sections:
  freshness_check:
  duplicate_source_to_delete:
```

Rules:

- live source-of-truth docs change atomically with code when they describe current module responsibility, public API, contracts, commands, or safety rules;
- longer-form design, tutorial, report, or milestone docs can sync later only when their stale window is explicit;
- module/API docs should identify responsibility, public API, dependencies, modification risk, tests, and key decisions;
- docs must not duplicate facts owned by code, generated contracts, or active instruction files.

## 18. Requirement, Risk, and Control Traceability

Purpose: prove that delivered behavior and quality work derive from an approved
need and have objective acceptance evidence.

```text
TraceabilityGate:
  requirement_id:
  business_owner:
  acceptance_outcome:
  risks:
  controls:
  tests_or_fitness_functions:
  evidence_records:
  release_or_runtime_outcome:
  broken_link_rejects_claim: true
```

Every in-scope business requirement must reach at least one risk, control,
verification path, and evidence record. Every control must trace back to a risk
or binding delivery obligation. Orphan requirements and orphan controls fail
the maturity where they apply.

## 19. Product Experience and Lifecycle

Purpose: make commercial usability and the full customer lifecycle testable.

```text
ProductLifecycleGate:
  primary_user_journeys:
  accessibility_target:
  supported_locales_and_fallback:
  installation:
  first_run_and_configuration:
  upgrade_and_data_migration:
  rollback_or_recovery:
  uninstall_and_data_retention:
  compatibility_matrix:
  user_support_and_diagnostics:
```

Commercial user-facing delivery requires real-workflow evidence for applicable
journeys, accessibility, internationalization, installation, upgrade,
rollback/recovery, and uninstall. An owner-approved `NOT_APPLICABLE` rationale
is required for any omitted lifecycle stage.

## 20. Production Readiness and Operations

Purpose: require evidence that the product can be operated, recovered, and
improved after release.

```text
ProductionReadinessGate:
  service_or_runtime_owner:
  slis_slos_and_error_budget:
  capacity_and_load_model:
  observability_and_alert_actionability:
  backup_restore_and_recovery_test:
  deployment_rollback_and_change_safety:
  incident_response_and_learning:
  vulnerability_response:
  business_continuity:
  dora_metrics:
```

Do not treat a backup configuration as restore evidence, an alert definition as
an actionable alert, or a runbook as a rehearsed recovery. Production readiness
requires executed scenarios at the profile's required freshness.

## 21. Commercial Delivery and Governance

Purpose: bind distribution, support, legal, security, and release authority to
the explicitly selected market and product model.

```text
CommercialDeliveryGate:
  target_market:
  distribution_model:
  explicit_legal_and_regulatory_profile:
  licensing_and_third_party_notices:
  privacy_and_data_governance:
  vulnerability_disclosure_and_support_policy:
  release_artifact_identity_and_verification:
  support_maintenance_and_end_of_life:
  release_authority:
```

When `distribution_model` is `open_core`, add:

```text
OpenCoreLicenseGate:
  component_inventory:
  repository_service_and_package_boundary:
  license_expression_by_component:
  feature_gating_and_fallback:         # when applicable
  file_level_license_identifiers:      # when selected by the legal owner
  license_conversion_terms:            # when the selected license defines them
  first_and_third_party_notices:
```

Do not infer laws from repository content. Missing expertise or business
process remains `TODO` or `BLOCKED`, never implicit `PASS`. Open-source projects
may map independent cross-audit to a separate quality agent and release
authority to a project owner. An open-core boundary inferred from a path,
filename, feature flag, or one reference repository is a hypothesis, not a
`PASS`. The owner must confirm which conditional fields apply.

## 22. AI Assurance Overlay

Purpose: add system-level assurance when the delivered product contains an AI
model, agent, generated decision, or autonomous tool action.

```text
AIAssuranceGate:
  intended_use_and_prohibited_use:
  data_model_and_tool_inventory:
  evaluation_dataset_and_scenario_origin:
  quality_safety_security_privacy_metrics:
  prompt_injection_and_tool_abuse_tests:
  human_oversight_and_high_impact_approval:
  transparency_and_user_recourse:
  drift_monitoring_and_re_evaluation_trigger:
  incident_and_kill_switch:
```

AI-assisted development of ordinary software does not by itself make the
product an AI system. When this overlay applies, model-only scores cannot replace
end-to-end product, tool-boundary, misuse, and human-oversight evidence.

### AI-Assisted Contribution Governance

A separate concern from product AI behavior: how the project governs code and
content contributed *with the assistance of* AI tools (copilots, agentic PRs,
generated patches). This applies only when the explicit
`external_contributions` profile is `accepted` or `restricted`, regardless of
`ai_system`. It is contribution governance, not product assurance. Foundation
guidance and individual project policies are useful inputs, but they do not
establish one mandatory cross-ecosystem position.

```text
AIContributionGate:
  selected_policy:                  # allowed | restricted | prohibited
  ai_disclosure_policy:             # whether agentic/AI-assisted PRs must disclose AI usage
  contributor_accountability:       # contributor bears same responsibility for AI output as hand-written code
  review_standard_parity:           # AI-generated PRs meet the same review bar; no rubber-stamp fast lane
  licensing_rights_verification:    # contributor attests they hold rights to contribute the AI output
  model_attribution_when_required:  # commit/PR notes the model when policy requires it
```

Reject patterns:

- agentic PRs are merged under a looser review standard than human PRs for the
  same risk class;
- the selected policy contradicts contribution instructions, the DCO/CLA, or
  actual review automation;
- the project accepts or restricts external contributions but has no recorded
  decision for AI-assisted submissions;
- disclosure policy is undocumented, so "AI-authored" tagging is inconsistent
  across contributors.

A project may legitimately choose "no special AI policy, all contributions meet
the same bar" — but that decision must be explicit, not silent.
