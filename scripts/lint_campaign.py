#!/usr/bin/env python3
"""Preflight an AI-brownfield campaign or one explicit task without writes.

This tool validates structural closure only.  It does not execute controls,
acquire product evidence, mutate the ledger, or support a readiness claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from quality_common import (
    campaign_baseline_binding,
    framework_binding,
    load_json_yaml,
    object_items,
    registry_control_ids,
    safe_relative_path,
    scope_entry_covers,
    string_items,
    validate_campaign,
    validate_manifest,
    validate_registry,
    validate_traceability,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--campaign", help="candidate JSON campaign specification")
    source.add_argument(
        "--active", action="store_true",
        help="lint the manifest's registered active campaign",
    )
    parser.add_argument("--phase-id")
    parser.add_argument("--task-id")
    parser.add_argument(
        "--require-path", action="append", default=[],
        help="project-relative path that the selected task must cover; repeatable",
    )
    parser.add_argument(
        "--require-control", action="append", default=[],
        help="control ID that the selected task must affect; repeatable",
    )
    parser.add_argument(
        "--require-product-acquisition", action="store_true",
        help="report the v3 product-acquisition modeling blocker for the selected task",
    )
    return parser.parse_args()


def blocker(code: str, category: str, message: str, path: str | None = None) -> dict[str, str]:
    item = {"code": code, "category": category, "message": message}
    if path is not None:
        item["path"] = path
    return item


def advisory(code: str, message: str, path: str | None = None) -> dict[str, str]:
    item = {"code": code, "message": message}
    if path is not None:
        item["path"] = path
    return item


def find_task(
    specification: dict[str, Any], phase_id: str, task_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    for phase in object_items(specification.get("phases")):
        if phase.get("id") == phase_id:
            for task in object_items(phase.get("tasks")):
                if task.get("id") == task_id:
                    return phase, task
            return phase, None
    return None, None


def task_covers_path(task_scope: list[str], required_path: str) -> tuple[bool, bool]:
    """Return ``(covered, indeterminate_glob)`` for one required path."""
    coverage = [scope_entry_covers(entry, required_path) for entry in task_scope]
    return True in coverage, None in coverage


def control_summary(registry: dict[str, Any], task: dict[str, Any]) -> list[dict[str, Any]]:
    controls = {
        control["id"]: control
        for control in object_items(registry.get("controls"))
        if isinstance(control.get("id"), str) and control["id"]
    }
    summary: list[dict[str, Any]] = []
    for control_id in sorted(string_items(task.get("affected_control_ids"))):
        control = controls.get(control_id, {})
        execution = control.get("execution", {})
        if not isinstance(execution, dict):
            execution = {}
        summary.append({
            "control_id": control_id,
            "execution_type": execution.get("type"),
            "authorization_required": execution.get("authorization_required") is True,
            "required_capability_ids": sorted(string_items(
                control.get("required_capability_refs"),
            )),
            "artifact_paths": sorted(string_items(execution.get("artifact_paths"))),
        })
    return summary


def scope_relation_advisories(specification: dict[str, Any]) -> list[dict[str, str]]:
    """Report hierarchy relationships that v3 glob syntax cannot prove."""
    items: list[dict[str, str]] = []

    def inspect(parent: list[str], child: list[str], location: str) -> None:
        for entry in child:
            coverage = [scope_entry_covers(parent_entry, entry) for parent_entry in parent]
            if True not in coverage and None in coverage:
                items.append(advisory(
                    "SCOPE_CONTAINMENT_NOT_PROVEN",
                    "glob syntax prevents literal scope-containment proof",
                    f"{location}:{entry}",
                ))

    campaign_scope = string_items(specification.get("assessed_scope"))
    for phase in object_items(specification.get("phases")):
        phase_scope = string_items(phase.get("assessed_scope"))
        inspect(campaign_scope, phase_scope, f"phase:{phase.get('id', '')}")
        for task in object_items(phase.get("tasks")):
            task_scope = string_items(task.get("assessed_scope"))
            inspect(phase_scope, task_scope, f"task:{task.get('id', '')}")
    return items


def emit(payload: dict[str, Any], exit_code: int) -> int:
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return exit_code


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    if not safe_relative_path(args.guardrails_dir):
        return emit({
            "status": "CAMPAIGN_LINT_ERROR",
            "blocker_details": [blocker(
                "INVALID_GUARDRAILS_PATH", "input",
                "--guardrails-dir must be project-relative",
            )],
        }, 2)
    if bool(args.phase_id) != bool(args.task_id):
        return emit({
            "status": "CAMPAIGN_LINT_ERROR",
            "blocker_details": [blocker(
                "INCOMPLETE_TASK_CONTEXT", "input",
                "--phase-id and --task-id must be supplied together",
            )],
        }, 2)
    if (args.require_path or args.require_control or args.require_product_acquisition) and not args.task_id:
        return emit({
            "status": "CAMPAIGN_LINT_ERROR",
            "blocker_details": [blocker(
                "TASK_CONTEXT_REQUIRED", "input",
                "task requirements need explicit --phase-id and --task-id",
            )],
        }, 2)

    guardrails = root / args.guardrails_dir
    try:
        manifest = load_json_yaml(guardrails / "quality-manifest.yaml")
        registry = load_json_yaml(guardrails / "control-registry.yaml")
        traceability = load_json_yaml(guardrails / "traceability-graph.json")
        if args.active:
            manifest_object = manifest if isinstance(manifest, dict) else {}
            development_policy = manifest_object.get("development_policy")
            active = (
                development_policy.get("active_campaign")
                if isinstance(development_policy, dict)
                else None
            )
            specification = json.loads(json.dumps(active)) if isinstance(active, dict) else {}
            specification.pop("baseline_binding", None)
        else:
            specification = json.loads(Path(args.campaign).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return emit({
            "status": "CAMPAIGN_LINT_ERROR",
            "blocker_details": [blocker("INPUT_UNAVAILABLE", "input", str(exc))],
        }, 2)

    blockers: list[dict[str, str]] = []
    advisories: list[dict[str, str]] = []
    manifest_object = manifest if isinstance(manifest, dict) else {}
    registry_object = registry if isinstance(registry, dict) else {}
    framework_errors = validate_registry(registry)
    framework_errors.extend(validate_traceability(traceability, registry))
    control_ids = registry_control_ids(registry)
    framework_errors.extend(validate_manifest(manifest, control_ids))
    blockers.extend(
        blocker("FRAMEWORK_INVALID", "framework", error)
        for error in framework_errors
    )
    project = manifest_object.get("project")
    if not isinstance(project, dict):
        project = {}
    if project.get("development_mode") != "ai_brownfield":
        blockers.append(blocker(
            "DEVELOPMENT_MODE_MISMATCH", "campaign",
            "campaigns are valid only for ai_brownfield projects",
        ))
    if args.active and not specification:
        blockers.append(blocker(
            "ACTIVE_CAMPAIGN_MISSING", "campaign",
            "the quality manifest has no registered active campaign",
        ))
    if not isinstance(specification, dict):
        blockers.append(blocker(
            "CAMPAIGN_SPEC_INVALID", "campaign",
            "campaign specification must be an object",
        ))
        specification = {}

    forbidden = {
        "baseline_commit", "baseline_registry_sha256", "baseline_workspace_sha256",
        "baseline_framework_revision", "baseline_framework_sha256",
        "baseline_subject_binding", "baseline_binding",
    } & set(specification)
    if forbidden:
        blockers.append(blocker(
            "CALLER_SUPPLIED_BASELINE", "campaign",
            "baseline bindings are generated, not supplied: " + ", ".join(sorted(forbidden)),
        ))

    current_framework = framework_binding(Path(__file__).resolve().parent.parent)
    try:
        guardrails_relative = guardrails.relative_to(root).as_posix()
        baseline = campaign_baseline_binding(
            root, guardrails_relative, registry, current_framework,
        )
    except (OSError, ValueError) as exc:
        blockers.append(blocker("SUBJECT_BINDING_UNAVAILABLE", "environment", str(exc)))
        baseline = {
            "commit": "unavailable", "tree_sha256": "unavailable",
            "registry_sha256": "0" * 64,
            "framework_revision": current_framework["revision"],
            "framework_sha256": current_framework["content_sha256"],
        }
    campaign = {**specification, "baseline_binding": baseline}
    blockers.extend(
        blocker("CAMPAIGN_STRUCTURE_INVALID", "campaign", error)
        for error in validate_campaign(campaign, control_ids)
    )
    advisories.extend(scope_relation_advisories(specification))
    target_maturity = project.get("target_maturity")
    if specification.get("target_maturity") != target_maturity:
        blockers.append(blocker(
            "TARGET_MATURITY_MISMATCH", "campaign",
            "campaign target_maturity must match the project target",
        ))

    selected_phase: dict[str, Any] | None = None
    selected_task: dict[str, Any] | None = None
    if args.task_id:
        selected_phase, selected_task = find_task(specification, args.phase_id, args.task_id)
        if selected_phase is None:
            blockers.append(blocker(
                "PHASE_NOT_FOUND", "campaign", f"phase not found: {args.phase_id}",
            ))
        elif selected_task is None:
            blockers.append(blocker(
                "TASK_NOT_FOUND", "campaign", f"task not found: {args.task_id}",
            ))

    if selected_task is not None:
        task_scope = string_items(selected_task.get("assessed_scope"))
        for required_path in sorted(set(args.require_path)):
            if not safe_relative_path(required_path):
                blockers.append(blocker(
                    "REQUIRED_PATH_INVALID", "scope",
                    "required path must be project-relative", required_path,
                ))
                continue
            covered, indeterminate = task_covers_path(task_scope, required_path)
            if covered:
                continue
            if indeterminate:
                blockers.append(blocker(
                    "REQUIRED_PATH_NOT_PROVEN", "scope",
                    "glob scope cannot prove that the task covers the required path",
                    required_path,
                ))
            else:
                blockers.append(blocker(
                    "REQUIRED_PATH_OUTSIDE_TASK_SCOPE", "scope",
                    "selected task does not cover the required path",
                    required_path,
                ))
        task_controls = set(string_items(selected_task.get("affected_control_ids")))
        for required_control in sorted(set(args.require_control)):
            if required_control not in task_controls:
                blockers.append(blocker(
                    "REQUIRED_CONTROL_OUTSIDE_TASK", "control",
                    f"selected task does not affect required control {required_control}",
                ))
        if args.require_product_acquisition:
            blockers.append(blocker(
                "PRODUCT_ACQUISITION_CAPABILITIES_UNMODELED", "authorization",
                "v3 does not model product-acquisition capabilities; a project-owned "
                "execution plan and per-run authorization are required",
            ))

    for phase in object_items(specification.get("phases")):
        assigned = {
            control_id
            for task in object_items(phase.get("tasks"))
            for control_id in string_items(task.get("affected_control_ids"))
        }
        phase_controls = set(string_items(phase.get("affected_control_ids")))
        for control_id in sorted(phase_controls - assigned):
            advisories.append(advisory(
                "PHASE_CONTROL_WITHOUT_TASK",
                f"phase control {control_id} is not assigned to a task; phase closeout still owns it",
                str(phase.get("id", "")),
            ))

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "CAMPAIGN_LINT_BLOCKED" if blockers else "CAMPAIGN_LINT_OK",
        "campaign": {
            "id": specification.get("id"),
            "revision": specification.get("revision"),
            "phase_id": args.phase_id,
            "task_id": args.task_id,
            "source": "active_manifest" if args.active else "candidate_file",
        },
        "blocker_details": blockers,
        "advisories": advisories,
        "writes_performed": False,
        "controls_executed": False,
        "claim_supported": False,
    }
    if selected_task is not None:
        payload["task_contract"] = {
            "affected_control_ids": sorted(string_items(
                selected_task.get("affected_control_ids"),
            )),
            "assessed_scope": string_items(selected_task.get("assessed_scope")),
            "required_paths": sorted(set(args.require_path)),
            "required_controls": sorted(set(args.require_control)),
            "product_acquisition_required": args.require_product_acquisition,
            "control_execution_summary": control_summary(registry_object, selected_task),
        }
    return emit(payload, 1 if blockers else 0)


if __name__ == "__main__":
    raise SystemExit(main())
