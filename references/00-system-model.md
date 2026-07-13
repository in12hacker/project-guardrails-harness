# System Model

This is the durable readme-equivalent for the skill. It explains the transferable model behind generated project guardrails and harnesses.

## Contents

Objective; External Calibration; Core Concepts; Transferable Lessons;
Portable vs Project-Specific; Standard Output.

## Objective

Generate and operate an **evidence-backed delivery quality control plane** for a
specific repository. It must govern work from requirements through commercial
delivery and production feedback without copying one project's rules into
another. Instead:

1. scan repository evidence;
2. classify the product/runtime/release profile;
3. identify semantic owners;
4. choose rule families that match risk;
5. attach harnesses to rules;
6. trace requirements to risks, controls, tests, evidence, and outcomes;
7. execute controls and preserve commit-bound evidence;
8. separate self-audit, cross-audit, and release authority;
9. converge legacy debt without overstating readiness;
10. update controls when audits, incidents, or customer outcomes reveal new invariant classes.

## External Calibration

Use current official or authoritative standards as anchors, then adapt to repository reality:

| Source | Portable lesson |
|---|---|
| NIST SSDF SP 800-218 | Secure development practices must be embedded across the SDLC and used to reduce vulnerabilities and recurrence. |
| ISO/IEC 25010:2023 + 25019:2023 | Product quality and quality-in-use require more than code correctness: suitability, reliability, security, usability, compatibility, maintainability, portability, safety, effectiveness, efficiency, satisfaction, and freedom from risk. |
| OWASP ASVS 5.0.0 | Web application security requirements need explicit verification levels and objective evidence. |
| OpenSSF OSPS Baseline 2026.02.19 | Open-source governance and security controls must be calibrated to project maturity and distribution reality. |
| SLSA v1.2 Build and Source Tracks | Supply-chain claims require source/build attestations appropriate to the selected level, and provenance must be verified at consumption or deploy. |
| CycloneDX 1.7 / SPDX 3.0 | SBOM and software identity evidence should be machine-readable and tied to released artifacts. |
| WCAG 2.2 / ISO/IEC 40500:2025 | User-facing commercial software needs explicit accessibility acceptance. |
| NIST AI RMF 1.0 + Generative AI Profile | AI systems need an assurance overlay for validity, safety, security, transparency, privacy, and human oversight. |
| DORA | Delivery performance and operational learning should use deployment frequency, lead time, change fail rate, failed deployment recovery time, and rework rate. |
| OpenSSF Scorecard | Repository security can be checked through CI, review, branch protection, pinned dependencies, token permissions, packaging, signed releases, fuzzing, SAST, and dependency health. |
| OWASP SAMM | Assurance work fits Governance, Design, Implementation, Verification, and Operations. |
| C4 + ADR | Architecture must be explainable by context/container/component/code views and durable decisions. |
| CODEOWNERS / service catalog (Backstage) | Ownership is a team/domain concept, not a file path; it gates changes, routes incidents, and feeds policy-as-code. |
| Ratcheting & Code Health (testdouble, CodeScene) | Debt is paid down with "don't make it worse" gates (ratchets) and shall-not requirements, prioritized where change is expensive (hotspots). |
| Google Engineering Practices | Reviews should evaluate design, functionality, complexity, tests, naming, comments, and context. |
| Rust API Guidelines | Naming, conversions, type safety, dependability, and debuggability are API quality controls. |
| C++ Core Guidelines F.15-F.21 | Parameter passing must make input/output direction, ownership, mutation, and return values explicit. |
| Fowler Refactoring | Code smells should be resolved with behavior-preserving refactorings. |

## Core Concepts

### Evidence Over Claims

Documents, issue labels, and team statements are hypotheses. Completion requires evidence:

```text
Evidence:
  commit:
  code_paths:
  local_verification:
  remote_ci:
  runtime_or_product_evidence:
  residual_risk:
```

Evidence is stored in an append-only ledger and bound to control, commit,
scope, environment, actor, audit stage, and freshness. Only current `PASS`
satisfies an applicable control.

### Three Machine Sources Of Truth

- `quality-manifest.yaml`: selected profile, maturity, market, scope, audit and claim policy;
- `control-registry.yaml`: applicability, owners, execution, thresholds, and required evidence;
- `evidence-ledger.json`: immutable execution and audit observations.

The traceability graph is derived from these sources and project requirements;
Markdown is explanatory and cannot override machine state.

### Project Profile Before Rules

Rules must fit product type. A library, web app, infrastructure tool, security product, mobile app, and AI agent system need different acceptance surfaces.

### Owner Map Before Implementation

Every semantic concept needs one owner. If current owner and desired owner differ, create a migration task instead of pretending the target architecture already exists.

### Rule Families, Not Random Rules

Rules are grouped by concern:

- evidence and claim integrity;
- product/profile fit;
- architecture and owner boundaries;
- domain model and parameter flow;
- code cleanliness and code reduction;
- policy, rule, and configuration source of truth;
- testing and harness truthfulness;
- boundary robustness for protocol/runtime/tool/security edges;
- resilience and failure semantics;
- security, privacy, and secret lifecycle;
- runtime and protocol integrity;
- supply chain and release;
- operations, version, and coverage truth;
- rule lifecycle.

### Harness Before Hard Gate

A rule without a verification path is advisory. Hard gates require reliable automation or explicit manual signoff.

## Transferable Lessons

1. **Do not trust docs over code.** Use `rg`, build files, CI logs, and runtime evidence.
2. **Do not treat language as product type.** Rust can be a CLI, kernel tool, SaaS backend, or SDK.
3. **Do not let adapters become owners.** Routes/controllers/UI/daemon scripts are usually adapters, not semantic owners.
4. **Do not collapse acceptance levels.** Unit, mock, contract, real-stack, product acceptance, and release evidence prove different things.
5. **Do not overclaim supply-chain maturity.** A dependency scan is not provenance, and produced provenance is not assurance unless it is verified at consumption or deploy under the selected SLSA v1.2 Build/Source requirements.
6. **Do not add abstractions without deletion (Occam's razor).** Abstractions should remove duplication, drift, or platform coupling. Prefer zero-dependency solutions when a native tool (curl/readelf/clippy) already covers the need. Every new script, file, or tool must justify its existence over reusing what is already present.
7. **Do not store stale rules.** Rules need owners, status, review dates, and deletion/supersession paths.
8. **Do not turn fallback into silence.** Fail-open/fail-closed is a layer decision with typed degraded evidence.
9. **Do not persist plaintext secrets.** Secret rules must describe the full lifecycle from source to runtime use to deletion.
10. **Do not ignore runtime physics.** Kernel, device, browser, proxy, stream, and protocol code need profile-specific harnesses.
11. **Do not hide policy in code.** Rules, defaults, exclusions, and overrides need one owner and one interpretation path.

## What Is Portable vs Project-Specific

Portable:

- owner map before hard rules;
- evidence over claims;
- rule family selection by project profile and overlays;
- hard gates require harnesses;
- stale rules need deletion or supersession.

Project-specific:

- exact product paradigm, UI copy, and user workflow;
- exact command names, crate/package names, and CI jobs;
- exact fail-open/fail-closed defaults;
- exact coverage thresholds and performance budgets;
- exact secret storage backend and runtime platform constraints.

## Standard Output

```text
ProjectGuardrails:
  quality_manifest:
  control_registry:
  evidence_ledger:
  traceability_graph:
  project_profile:
  evidence_inventory:
  owner_map:
  rule_catalog:
  harness_matrix:
  adoption_plan:
  lifecycle_plan:
  project_memory:
  unresolved_decisions:
  sources:
```
