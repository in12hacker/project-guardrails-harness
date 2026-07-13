# Standards And Quality Model

Use stable, officially published standards only. Drafts may be recorded as
future-watch items but must not create mandatory controls.

## Stable Calibration Baseline

| Standard | Use |
|---|---|
| ISO/IEC 25010:2023 | product quality requirements and evaluation |
| ISO/IEC 25019:2023 | quality-in-use and user outcomes |
| NIST SP 800-218 SSDF v1.1 | secure software development lifecycle |
| OWASP SAMM v2 | security-program maturity across governance through operations |
| OWASP ASVS v5.0.0 | web/application security verification overlay |
| OpenSSF OSPS Baseline 2026.02.19 | open-source project security and governance baseline |
| OpenSSF Scorecard | observable repository security checks |
| SLSA v1.2 | Build and Source supply-chain tracks and attestations |
| SPDX 3.0 / CycloneDX 1.7 | machine-readable software transparency and SBOM |
| WCAG 2.2 / ISO/IEC 40500:2025 | web accessibility overlay |
| NIST AI RMF 1.0 + GenAI Profile | AI-system assurance overlay |
| DORA five delivery metrics | delivery throughput and instability feedback |

Every imported standard reference must record an exact version, publication
status, applicability, mapping, and review date. Never claim certification from
self-assessment unless the standard explicitly permits that claim.

Official sources: [ISO/IEC 25010](https://www.iso.org/standard/78176.html),
[NIST SSDF](https://csrc.nist.gov/pubs/sp/800/218/final),
[OWASP ASVS](https://github.com/OWASP/ASVS/releases),
[OpenSSF OSPS Baseline](https://baseline.openssf.org/),
[SLSA v1.2](https://slsa.dev/spec/v1.2/),
[CycloneDX](https://cyclonedx.org/specification/overview/),
[SPDX](https://spdx.dev/specifications/),
[WCAG 2.2](https://www.w3.org/TR/WCAG22/),
[NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework), and
[DORA metrics](https://dora.dev/guides/dora-metrics/).

## Product Quality Dimensions

At profile time, decide which measurable outcomes apply across:

- functional suitability;
- performance efficiency and capacity;
- compatibility/interoperability;
- interaction capability, usability, accessibility, and internationalization;
- reliability, availability, recoverability, and fault tolerance;
- security, privacy, abuse resistance, and secure defaults;
- maintainability, modularity, analysability, modifiability, and testability;
- flexibility, portability, installability, replaceability, and scalability;
- safety and prevention of unacceptable harm.

The dimensions are not checklists by themselves. Each selected dimension needs
a project-specific requirement, measure, threshold, control, and evidence path.

## Mandatory Profile Decisions

```text
QualityProfile:
  product_type:
  development_mode:
  distribution_model: open_source|private_commercial|saas|client_software|embedded
  target_markets:
  target_maturity:
  criticality:
  data_sensitivity:
  users:
  runtime_and_deployment:
  release_artifacts:
  support_model:
  assessed_scope:
  excluded_scope:
  regulatory_overlays:
  ai_system: true|false
```

Target market and regulatory overlays are mandatory human decisions. The skill
must not infer legal applicability from source code or geography keywords.

## Profile Overlays

Apply overlays only when selected or evidenced and confirmed:

- web/application security: ASVS 5.0.0;
- open-source governance: OSPS Baseline maturity level;
- AI assurance: NIST AI RMF/GenAI Profile plus project evals;
- accessibility: WCAG 2.2 target level;
- supply-chain producer: SLSA Build/Source and SBOM/provenance;
- regulated market: jurisdiction and industry-specific control pack;
- privileged/device/kernel: real environment, safety, and manual signoff;
- data/privacy: classification, minimization, retention, export, deletion.
