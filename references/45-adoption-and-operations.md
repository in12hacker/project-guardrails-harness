# Adoption And Operations

## Greenfield Bootstrap

Before feature development, create the manifest, control registry, ownership
map, requirement/risk model, CI entry points, test skeleton, release workflow,
and operational placeholders. A placeholder is `TODO` and blocks the maturity
where it becomes mandatory.

## Brownfield Convergence

Inventory all debt before claiming readiness. Known debt is not permitted, but
human-led projects may continue feature work while convergence proceeds when:

- the global project remains explicitly `not_ready`;
- release at the blocked maturity remains prohibited;
- touched scope does not add debt;
- the feature's own requirements, controls, and tests pass;
- debt and dependency interactions are visible in the ledger.

AI-led brownfield projects should use a dedicated convergence campaign with
small verified phases. Human-led projects should migrate by module and quality
dimension to control coordination cost.

## Production Readiness

Production-ready controls should cover, when applicable:

- SLI/SLO definitions and error-budget policy;
- capacity, load, latency, resource, and cost budgets;
- logs, metrics, traces, dashboards, alerts, and redaction;
- health/readiness and degraded-state semantics;
- backup, restore, retention, disaster recovery, RTO, and RPO;
- install, configuration, upgrade, downgrade, rollback, and uninstall;
- deployment strategy, compatibility, data migration, and rollback tests;
- runbooks, on-call/incident ownership, post-incident learning, and support;
- fault injection or explicit reason it is not applicable.

## Commercial Readiness

Commercial-ready controls add:

- legal notices, source and artifact licensing, dependency license policy;
- SBOM, vulnerability scan, signed artifacts, provenance, and consumption-side verification;
- release notes, checksums, reproducibility target, and artifact retention;
- vulnerability disclosure, response targets, security updates, support period, and EOL;
- user documentation, secure defaults, accessibility, internationalization, and privacy;
- product acceptance using the real user/operator stimulus.

## Delivery Feedback

Where deployment data exists, track DORA's current five delivery metrics:
change lead time, deployment frequency, failed deployment recovery time,
change fail rate, and deployment rework rate. These are trend signals, not
universal pass thresholds; project owners select targets from business needs.

Runtime incidents, escaped defects, vulnerability response, support burden,
SLO breaches, and customer outcomes feed the rule lifecycle. A repeated escape
must create or strengthen a control and its verification harness.
