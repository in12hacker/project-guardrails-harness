#!/usr/bin/env python3
"""Register or revise the single active AI brownfield convergence campaign."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quality_common import (
    canonical_digest,
    exclusive_file_lock,
    framework_binding,
    git_commit,
    git_workspace_digest,
    load_json_yaml,
    safe_relative_path,
    validate_campaign,
    validate_manifest,
    validate_registry,
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
        specification = json.loads(Path(args.campaign).read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL [QF-CAMPAIGN]: {exc}", file=sys.stderr)
        return 2
    registry_errors = validate_registry(registry)
    if registry_errors:
        for error in registry_errors:
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
    commit = git_commit(root)
    if commit == "unavailable":
        print("BLOCKED [QF-CAMPAIGN]: a Git commit is required", file=sys.stderr)
        return 1
    try:
        ledger_relative = (guardrails / "evidence-ledger.json").relative_to(root).as_posix()
        evidence_relative = (guardrails / "evidence").relative_to(root).as_posix()
        workspace_sha256 = git_workspace_digest(root, {ledger_relative, evidence_relative})
    except ValueError:
        workspace_sha256 = "unavailable"
    if workspace_sha256 == "unavailable":
        print("BLOCKED [QF-CAMPAIGN]: workspace evidence is required", file=sys.stderr)
        return 1
    current_framework = framework_binding(Path(__file__).resolve().parent.parent)
    campaign = {
        **specification,
        "baseline_commit": commit,
        "baseline_registry_sha256": canonical_digest(registry),
        "baseline_workspace_sha256": workspace_sha256,
        "baseline_framework_revision": current_framework["revision"],
        "baseline_framework_sha256": current_framework["content_sha256"],
    }
    control_ids = {control["id"] for control in registry["controls"]}
    errors = validate_campaign(campaign, control_ids)
    if campaign.get("target_maturity") != manifest.get("project", {}).get("target_maturity"):
        errors.append("campaign target_maturity must match the project target")
    if errors:
        for error in errors:
            print(f"FAIL [QF-CAMPAIGN]: {error}", file=sys.stderr)
        return 2
    manifest["framework"] = current_framework
    manifest["development_policy"]["active_campaign"] = campaign
    manifest_errors = validate_manifest(manifest, control_ids)
    if manifest_errors:
        for error in manifest_errors:
            print(f"FAIL [QF-FRAMEWORK]: {error}", file=sys.stderr)
        return 2
    write_json_yaml(guardrails / "quality-manifest.yaml", manifest)
    print(
        f"registered campaign {campaign['id']} revision {campaign['revision']} "
        f"at {campaign['baseline_commit']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
