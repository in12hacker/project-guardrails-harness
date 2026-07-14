#!/usr/bin/env python3
"""Derive machine-readable development, task, merge, and release readiness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate_quality import (
    campaign_claim_context,
    outcome_blockers,
    policy_blockers,
    stage_results,
)
from generation_common import bounded_diagnostics
from quality_common import (
    campaign_binding_errors,
    maturity_applies,
    framework_binding,
    load_json_yaml,
    project_subject_binding,
    safe_relative_path,
    validate_ledger,
    validate_manifest,
    validate_registry,
    validate_traceability,
)


READINESS_LEVELS = (
    "DEVELOPMENT_START_READY",
    "TASK_CLAIM_READY",
    "MERGE_READY",
    "RELEASE_READY",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    parser.add_argument("--control", action="append", default=[])
    parser.add_argument("--campaign-id")
    parser.add_argument("--campaign-revision", type=int)
    parser.add_argument("--phase-id")
    parser.add_argument("--task-id")
    parser.add_argument("--require-level", choices=READINESS_LEVELS)
    return parser.parse_args()


def blocked(blockers: list[str], controls: set[str] | None = None) -> dict:
    return {
        "status": "BLOCKED",
        "control_ids": sorted(controls or set()),
        "blockers": sorted(set(blockers)),
    }


def not_evaluated(reason: str) -> dict:
    return {"status": "NOT_EVALUATED", "control_ids": [], "blockers": [reason]}


def control_readiness(
    root: Path, registry: dict, ledger: dict, subject: dict, target: str,
    controls: list[dict], required_stages: set[str], absolute: bool,
    exit_policy: dict | None = None,
) -> dict:
    control_ids = {control["id"] for control in controls if control.get("applies", False)}
    if not control_ids:
        return blocked(["no applicable controls selected"])
    controls_by_id = {control["id"]: control for control in controls}
    framework_errors, policy_failures = policy_blockers(
        root, registry, control_ids, absolute,
    )
    blockers = [*framework_errors, *policy_failures]
    assessments = {
        stage: stage_results(
            ledger.get("runs", []), stage, subject, target, control_ids,
        )
        for stage in sorted(required_stages)
    }
    for stage, assessment in assessments.items():
        blockers.extend(
            f"{stage}:{item}"
            for item in outcome_blockers(
                root, assessment[0], controls_by_id, control_ids, exit_policy,
            )
        )
    authority_sets = {stage: value[1] for stage, value in assessments.items()}
    context_sets = {stage: value[2] for stage, value in assessments.items()}
    if any(len(authorities) != 1 for authorities in authority_sets.values()):
        blockers.append("audit stage authority is missing or ambiguous")
    if any(len(contexts) != 1 for contexts in context_sets.values()):
        blockers.append("audit stage execution context is missing or ambiguous")
    authorities = [next(iter(value)) for value in authority_sets.values() if len(value) == 1]
    contexts = [next(iter(value)) for value in context_sets.values() if len(value) == 1]
    if len(set(authorities)) != len(authorities):
        blockers.append("audit stage authorities are not independent")
    if len(set(contexts)) != len(contexts):
        blockers.append("audit stage execution contexts are not independent")
    if blockers:
        return blocked(blockers, control_ids)
    supporting = sorted({
        run["run_id"]
        for latest, _, _ in assessments.values()
        for _, run in latest.values()
    })
    return {
        "status": "READY",
        "control_ids": sorted(control_ids),
        "blockers": [],
        "supporting_run_ids": supporting,
    }


def task_context(
    args: argparse.Namespace, manifest: dict, controls_by_id: dict[str, dict],
) -> tuple[list[dict], dict | None, str | None]:
    mode = manifest["project"]["development_mode"]
    if mode != "ai_brownfield":
        if not args.control:
            return [], None, "affected --control values are required"
        unknown = sorted(set(args.control) - set(controls_by_id))
        if unknown:
            return [], None, f"unknown task controls: {', '.join(unknown)}"
        return [controls_by_id[item] for item in sorted(set(args.control))], None, None
    claim_args = argparse.Namespace(
        campaign_id=args.campaign_id,
        campaign_revision=args.campaign_revision,
        phase_id=args.phase_id,
        task_id=args.task_id,
        claim_scope="task",
    )
    try:
        _, task = campaign_claim_context(manifest, claim_args)
    except ValueError as exc:
        return [], None, str(exc)
    assert task is not None
    registered = set(task["affected_control_ids"])
    if args.control and set(args.control) != registered:
        return [], None, "selected controls do not match the registered campaign task"
    unknown = sorted(registered - set(controls_by_id))
    if unknown:
        return [], None, f"campaign controls are outside target maturity: {', '.join(unknown)}"
    return [controls_by_id[item] for item in sorted(registered)], task["exit_policy"], None


def main() -> int:
    args = parse_args()
    if not safe_relative_path(args.guardrails_dir):
        print(json.dumps({"status": "error", "errors": ["guardrails directory must be project-relative"]}))
        return 2
    root = Path(args.root).resolve()
    guardrails = root / args.guardrails_dir
    try:
        manifest = load_json_yaml(guardrails / "quality-manifest.yaml")
        registry = load_json_yaml(guardrails / "control-registry.yaml")
        ledger = load_json_yaml(guardrails / "evidence-ledger.json")
        traceability = load_json_yaml(guardrails / "traceability-graph.json")
    except (OSError, ValueError) as exc:
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
    current_framework = framework_binding(Path(__file__).resolve().parent.parent)
    if manifest.get("framework") != current_framework:
        errors.append("active Skill revision/content/trust differs from the manifest binding")
    try:
        guardrails_relative = guardrails.relative_to(root).as_posix()
    except ValueError:
        errors.append("guardrails directory must be inside the project root")
        guardrails_relative = args.guardrails_dir
    subject = project_subject_binding(
        root, guardrails_relative, manifest, registry, traceability, current_framework,
    )
    if subject["commit"] == "unavailable" or subject["tree_sha256"] == "unavailable":
        errors.append("Git subject commit and tree evidence are unavailable")
    if errors:
        diagnostics = bounded_diagnostics(errors)
        levels = {
            level: blocked([sample["message"] for sample in diagnostics["samples"]])
            for level in READINESS_LEVELS
        }
        report = {"schema_version": "1.0", "subject_binding": subject, "levels": levels}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    target = manifest["project"]["target_maturity"]
    applicable = [
        control for control in registry["controls"]
        if maturity_applies(control["required_from_maturity"], target)
    ]
    controls_by_id = {control["id"]: control for control in applicable}
    development_blockers: list[str] = []
    campaign_errors: list[str] = []
    if manifest["project"]["development_mode"] == "ai_brownfield":
        campaign = manifest["development_policy"].get("active_campaign")
        if campaign is None:
            development_blockers.append("AI brownfield development requires an active campaign")
        else:
            campaign_errors = campaign_binding_errors(
                campaign, subject["registry_sha256"], current_framework,
            )
            development_blockers.extend(campaign_errors)
    development = (
        blocked(development_blockers)
        if development_blockers
        else {"status": "READY", "control_ids": [], "blockers": []}
    )
    task_controls, exit_policy, task_error = task_context(args, manifest, controls_by_id)
    if task_error:
        task = not_evaluated(task_error)
        merge = not_evaluated(f"task context unavailable: {task_error}")
    elif campaign_errors:
        selected = {control["id"] for control in task_controls}
        task = blocked(campaign_errors, selected)
        merge = blocked(campaign_errors, selected)
    else:
        task_stages = set(manifest["claim_policies"]["task"]["required_stages"])
        task = control_readiness(
            root, registry, ledger, subject, target, task_controls,
            task_stages, False, exit_policy,
        )
        merge_controls = {control["id"]: control for control in task_controls}
        for control_id in ("QF.GATE.PR",):
            if control_id in controls_by_id:
                merge_controls[control_id] = controls_by_id[control_id]
        merge = control_readiness(
            root, registry, ledger, subject, target, list(merge_controls.values()),
            task_stages, False, exit_policy,
        )
    release = control_readiness(
        root, registry, ledger, subject, target, applicable,
        set(manifest["claim_policies"]["release"]["required_stages"]), True,
    )
    levels = {
        "DEVELOPMENT_START_READY": development,
        "TASK_CLAIM_READY": task,
        "MERGE_READY": merge,
        "RELEASE_READY": release,
    }
    report = {"schema_version": "1.0", "subject_binding": subject, "levels": levels}
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.require_level:
        return 0 if levels[args.require_level]["status"] == "READY" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
