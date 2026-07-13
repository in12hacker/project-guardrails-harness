#!/usr/bin/env python3
"""Migrate a v1 project quality framework to the v2 semantic contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quality_common import build_traceability_graph, load_json_yaml, write_json_yaml


FILES = {
    "manifest": "quality-manifest.yaml",
    "registry": "control-registry.yaml",
    "ledger": "evidence-ledger.json",
    "graph": "traceability-graph.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    return parser.parse_args()


def migrate_manifest(manifest: dict) -> dict:
    migrated = dict(manifest)
    required = list(manifest.get("audit_policy", {}).get("required_stages", []))
    migrated["schema_version"] = "2.0"
    migrated["development_policy"] = {"active_campaign": None}
    migrated["claim_policies"] = {
        "task": {"required_stages": ["self", "cross"]},
        "phase": {"required_stages": ["self", "cross"]},
        "project": {"required_stages": required},
        "release": {"required_stages": required},
    }
    return migrated


def migrate_registry(registry: dict) -> dict:
    migrated = dict(registry)
    migrated["schema_version"] = "2.0"
    controls = []
    for original in registry.get("controls", []):
        control = dict(original)
        control.setdefault("control_revision", "1")
        control.setdefault("rule_refs", [])
        control.setdefault("evaluation_mode", "absolute")
        control.setdefault("required_capability_refs", [])
        controls.append(control)
    migrated["controls"] = controls
    migrated.setdefault("capabilities", [])
    migrated.setdefault("baselines", [])
    migrated.setdefault("cleanup_debts", [])
    migrated.setdefault("design_scope_exemptions", [])
    migrated.setdefault("federated_rule_mappings", [])
    return migrated


def migrate_ledger(ledger: dict) -> dict:
    migrated = dict(ledger)
    migrated["schema_version"] = "2.0"
    migrated.setdefault("runs", [])
    migrated.setdefault("audits", [])
    migrated.setdefault("claims", [])
    return migrated


def main() -> int:
    args = parse_args()
    guardrails = Path(args.root).resolve() / args.guardrails_dir
    try:
        documents = {
            name: load_json_yaml(guardrails / filename)
            for name, filename in FILES.items()
        }
    except ValueError as exc:
        print(f"FAIL [QF-MIGRATION]: {exc}", file=sys.stderr)
        return 2

    versions = {document.get("schema_version") for document in documents.values()}
    if versions == {"2.0"}:
        print("quality framework is already at schema 2.0")
        return 0
    if versions != {"1.0"}:
        rendered = ", ".join(sorted(str(version) for version in versions))
        print(
            f"FAIL [QF-MIGRATION]: expected a complete v1 framework, found versions: {rendered}",
            file=sys.stderr,
        )
        return 2

    manifest = migrate_manifest(documents["manifest"])
    registry = migrate_registry(documents["registry"])
    ledger = migrate_ledger(documents["ledger"])
    graph = build_traceability_graph(registry)

    write_json_yaml(guardrails / FILES["manifest"], manifest)
    write_json_yaml(guardrails / FILES["registry"], registry)
    write_json_yaml(guardrails / FILES["ledger"], ledger)
    write_json_yaml(guardrails / FILES["graph"], graph)
    print("migrated quality framework schema 1.0 -> 2.0")
    print("prior evidence remains provenance but must be re-evaluated against v2 digests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
