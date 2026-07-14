#!/usr/bin/env python3
"""Review or apply a declared Skill update without guessing compatibility."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from generation_common import transactional_replace_entries
from quality_common import (
    SCHEMA_VERSION,
    build_traceability_graph,
    campaign_baseline_binding,
    exclusive_file_lock,
    framework_binding,
    load_json_yaml,
    safe_relative_path,
    validate_ledger,
    validate_manifest,
    validate_registry,
    validate_traceability,
    write_json_yaml,
)


CHANGE_PRIORITY = {
    "none": 0,
    "presentation": 1,
    "control_logic": 2,
    "incompatible_semantics": 3,
    "schema": 4,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    parser.add_argument("--declaration")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser.parse_args()


def changed_skill_files(skill_root: Path, old_revision: str) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", old_revision, "HEAD", "--",
             "SKILL.md", "agents", "references", "schemas", "scripts", "templates"],
            cwd=skill_root, check=False, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    changed = {line for line in result.stdout.splitlines() if line}
    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "SKILL.md", "agents", "references",
             "schemas", "scripts", "templates"],
            cwd=skill_root, check=False, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if dirty.returncode != 0:
        return None
    changed.update(line[3:] for line in dirty.stdout.splitlines() if len(line) > 3)
    return sorted(changed)


def inferred_change_class(paths: list[str] | None) -> str:
    if paths is None:
        return "incompatible_semantics"
    classification = "presentation"
    for path in paths:
        if path == "schemas/update-declaration.json":
            continue
        if path.startswith("schemas/"):
            return "schema"
        if path == "SKILL.md" or path.startswith("references/"):
            classification = max(
                (classification, "incompatible_semantics"),
                key=CHANGE_PRIORITY.__getitem__,
            )
        elif path.startswith("scripts/") or path.startswith("templates/"):
            classification = max(
                (classification, "control_logic"), key=CHANGE_PRIORITY.__getitem__,
            )
    return classification


def load_declaration(path: Path) -> dict:
    declaration = load_json_yaml(path)
    allowed = {"schema_version", "change_class", "compatible", "affected_control_ids", "summary"}
    if set(declaration) - allowed:
        raise ValueError("update declaration contains unknown fields")
    if declaration.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("update declaration schema does not match the active Skill schema")
    if declaration.get("change_class") not in set(CHANGE_PRIORITY) - {"none"}:
        raise ValueError("update declaration change_class is invalid")
    if not isinstance(declaration.get("compatible"), bool):
        raise ValueError("update declaration compatible must be boolean")
    affected = declaration.get("affected_control_ids")
    if not isinstance(affected, list) or not affected or any(
        not isinstance(item, str) or not item for item in affected
    ):
        raise ValueError("update declaration affected_control_ids must be non-empty")
    if not isinstance(declaration.get("summary"), str) or not declaration["summary"].strip():
        raise ValueError("update declaration summary is required")
    return declaration


def report_for(
    manifest: dict, registry: dict, current: dict, declaration: dict,
    changed: list[str] | None, enforce_path_floor: bool,
) -> dict:
    old_framework = manifest.get("framework", {})
    schema_matches = manifest.get("schema_version") == SCHEMA_VERSION
    if old_framework == current and schema_matches:
        return {
            "status": "up_to_date", "change_class": "none", "compatible": True,
            "requires_seal": False, "requires_regenerate": False,
            "rerun_control_ids": [], "changed_files": [],
        }
    if not schema_matches:
        change_class = "schema"
        compatible = False
    else:
        inferred = inferred_change_class(changed)
        change_class = (
            max((declaration["change_class"], inferred), key=CHANGE_PRIORITY.__getitem__)
            if enforce_path_floor else declaration["change_class"]
        )
        compatible = declaration["compatible"] and change_class not in {
            "schema", "incompatible_semantics",
        }
    affected = declaration["affected_control_ids"]
    known = sorted(
        control["id"] for control in registry.get("controls", [])
        if isinstance(control, dict) and isinstance(control.get("id"), str)
    )
    rerun = known if "*" in affected else sorted(set(affected) & set(known))
    return {
        "status": "update_available" if compatible else "incompatible_update",
        "change_class": change_class,
        "path_change_class": inferred_change_class(changed),
        "reviewed_declaration_override": not enforce_path_floor,
        "compatible": compatible,
        "requires_seal": not compatible,
        "requires_regenerate": not compatible,
        "rerun_control_ids": rerun,
        "changed_files": changed if changed is not None else ["<unavailable>"],
        "summary": declaration["summary"],
        "preserved_project_paths": [
            "INDEX.md", "memory.md", "decisions.md", "DEVELOPMENT-HANDOFF.md",
            "RULE-CONSOLIDATION-AUDIT.md", "rules/candidates.md",
        ],
    }


def apply_compatible_update(
    root: Path, guardrails: Path, manifest: dict, registry: dict,
    ledger: dict, current: dict,
) -> None:
    traceability = build_traceability_graph(registry)
    candidate = json.loads(json.dumps(manifest))
    candidate["framework"] = current
    campaign = candidate.get("development_policy", {}).get("active_campaign")
    if isinstance(campaign, dict):
        campaign["revision"] += 1
        relative = guardrails.relative_to(root).as_posix()
        campaign["baseline_binding"] = campaign_baseline_binding(
            root, relative, registry, current,
        )
    control_ids = {
        control["id"] for control in registry.get("controls", [])
        if isinstance(control, dict) and isinstance(control.get("id"), str)
    }
    errors = (
        validate_registry(registry)
        + validate_manifest(candidate, control_ids)
        + validate_traceability(traceability, registry)
        + validate_ledger(ledger, root)
    )
    if errors:
        raise ValueError("; ".join(sorted(set(errors))))
    with tempfile.TemporaryDirectory(
        prefix=f".{guardrails.name}.update-", dir=guardrails.parent,
    ) as staging_raw:
        staging = Path(staging_raw)
        write_json_yaml(staging / "traceability-graph.json", traceability)
        write_json_yaml(staging / "quality-manifest.yaml", candidate)
        transactional_replace_entries(
            staging, guardrails,
            ("quality-manifest.yaml", "traceability-graph.json"),
        )


def main() -> int:
    args = parse_args()
    if not safe_relative_path(args.guardrails_dir):
        print(json.dumps({"status": "error", "errors": ["guardrails directory must be project-relative"]}))
        return 2
    root = Path(args.root).resolve()
    guardrails = root / args.guardrails_dir
    skill_root = Path(__file__).resolve().parent.parent
    declaration_path = Path(args.declaration).resolve() if args.declaration else skill_root / "schemas" / "update-declaration.json"
    try:
        manifest = load_json_yaml(guardrails / "quality-manifest.yaml")
        registry = load_json_yaml(guardrails / "control-registry.yaml")
        declaration = load_declaration(declaration_path)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "errors": [str(exc)]}, sort_keys=True))
        return 2
    if manifest.get("schema_version") == SCHEMA_VERSION:
        try:
            ledger = load_json_yaml(guardrails / "evidence-ledger.json")
            traceability = load_json_yaml(guardrails / "traceability-graph.json")
        except ValueError as exc:
            print(json.dumps({"status": "error", "errors": [str(exc)]}, sort_keys=True))
            return 2
        control_ids = {
            control.get("id") for control in registry.get("controls", [])
            if isinstance(control, dict) and isinstance(control.get("id"), str)
        }
        errors = (
            validate_registry(registry)
            + validate_manifest(manifest, control_ids)
            + validate_traceability(traceability, registry)
            + validate_ledger(ledger, root)
        )
        if errors:
            print(json.dumps({
                "status": "error", "errors": sorted(set(errors)),
            }, indent=2, sort_keys=True))
            return 2
    current = framework_binding(skill_root)
    changed = changed_skill_files(skill_root, manifest.get("framework", {}).get("revision", ""))
    report = report_for(
        manifest, registry, current, declaration, changed,
        enforce_path_floor=args.declaration is None,
    )
    if args.check or report["status"] == "up_to_date":
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "up_to_date" else 1
    if not report["compatible"]:
        report["required_action"] = (
            "checkout the Skill revision bound in the manifest, seal the active plane, "
            "then regenerate with the new Skill; no compatibility reader is available"
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    try:
        with exclusive_file_lock(guardrails / ".ledger.lock"):
            ledger = load_json_yaml(guardrails / "evidence-ledger.json")
            apply_compatible_update(root, guardrails, manifest, registry, ledger, current)
    except (OSError, TimeoutError, ValueError) as exc:
        print(json.dumps({"status": "error", "errors": [str(exc)]}, sort_keys=True))
        return 2
    report["status"] = "applied"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
