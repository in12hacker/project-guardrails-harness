#!/usr/bin/env python3
"""Register or revise the single active AI brownfield convergence campaign."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quality_common import (
    campaign_baseline_binding,
    exclusive_file_lock,
    framework_binding,
    load_json_yaml,
    safe_relative_path,
    validate_campaign,
    validate_manifest,
    validate_registry,
    validate_traceability,
    write_json_yaml,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    parser.add_argument("--campaign", required=True, help="JSON campaign specification")
    parser.add_argument("--replace-active", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    if not safe_relative_path(args.guardrails_dir):
        print("FAIL [QF-CAMPAIGN]: --guardrails-dir must be project-relative", file=sys.stderr)
        return 2
    guardrails = root / args.guardrails_dir
    try:
        with exclusive_file_lock(guardrails / ".ledger.lock"):
            return locked_main(args, root, guardrails)
    except (OSError, TimeoutError) as exc:
        print(f"BLOCKED [QF-ENVIRONMENT]: {exc}", file=sys.stderr)
        return 1


def locked_main(
    args: argparse.Namespace, root: Path, guardrails: Path,
) -> int:
    """Register a campaign while excluding evaluators and evidence sealing."""
    try:
        manifest = load_json_yaml(guardrails / "quality-manifest.yaml")
        registry = load_json_yaml(guardrails / "control-registry.yaml")
        traceability = load_json_yaml(guardrails / "traceability-graph.json")
        specification = json.loads(Path(args.campaign).read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL [QF-CAMPAIGN]: {exc}", file=sys.stderr)
        return 2
    framework_errors = validate_registry(registry) + validate_traceability(
        traceability, registry,
    )
    if framework_errors:
        for error in framework_errors:
            print(f"FAIL [QF-FRAMEWORK]: {error}", file=sys.stderr)
        return 2
    if manifest.get("project", {}).get("development_mode") != "ai_brownfield":
        print("FAIL [QF-CAMPAIGN]: campaigns are only valid for ai_brownfield", file=sys.stderr)
        return 2
    if not isinstance(specification, dict):
        print("FAIL [QF-CAMPAIGN]: campaign specification must be an object", file=sys.stderr)
        return 2
    forbidden = {
        "baseline_commit", "baseline_registry_sha256", "baseline_workspace_sha256",
        "baseline_framework_revision", "baseline_framework_sha256",
        "baseline_subject_binding", "baseline_binding",
    } & set(specification)
    if forbidden:
        print("FAIL [QF-CAMPAIGN]: baseline bindings are generated, not supplied", file=sys.stderr)
        return 2
    current = manifest.get("development_policy", {}).get("active_campaign")
    if current is not None and not args.replace_active:
        print("FAIL [QF-CAMPAIGN]: an active campaign exists; use --replace-active after review", file=sys.stderr)
        return 2
    if current is not None and specification.get("revision", 0) <= current.get("revision", 0):
        print("FAIL [QF-CAMPAIGN]: replacement revision must increase", file=sys.stderr)
        return 2
    current_framework = framework_binding(Path(__file__).resolve().parent.parent)
    manifest["framework"] = current_framework
    try:
        guardrails_relative = guardrails.relative_to(root).as_posix()
    except ValueError:
        print("FAIL [QF-CAMPAIGN]: guardrails directory must be inside project root", file=sys.stderr)
        return 2
    baseline_binding = campaign_baseline_binding(
        root, guardrails_relative, registry, current_framework,
    )
    if baseline_binding["commit"] == "unavailable" or baseline_binding["tree_sha256"] == "unavailable":
        print("BLOCKED [QF-CAMPAIGN]: subject evidence is required", file=sys.stderr)
        return 1
    campaign = {
        **specification,
        "baseline_binding": baseline_binding,
    }
    control_ids = {control["id"] for control in registry["controls"]}
    errors = validate_campaign(campaign, control_ids)
    if campaign.get("target_maturity") != manifest.get("project", {}).get("target_maturity"):
        errors.append("campaign target_maturity must match the project target")
    if errors:
        for error in errors:
            print(f"FAIL [QF-CAMPAIGN]: {error}", file=sys.stderr)
        return 2
    manifest["development_policy"]["active_campaign"] = campaign
    manifest_errors = validate_manifest(manifest, control_ids)
    if manifest_errors:
        for error in manifest_errors:
            print(f"FAIL [QF-FRAMEWORK]: {error}", file=sys.stderr)
        return 2
    write_json_yaml(guardrails / "quality-manifest.yaml", manifest)
    print(
        f"registered campaign {campaign['id']} revision {campaign['revision']} "
        f"at {campaign['baseline_binding']['commit']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
