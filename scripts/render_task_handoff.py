#!/usr/bin/env python3
"""Render or lint a deterministic, compact task handoff."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from evaluate_quality import CampaignContextError, campaign_claim_context
from handoff_common import (
    HANDOFF_SCHEMA_VERSION,
    HUMAN_NOTES_BINDING_PATTERN,
    canonical_json,
    human_notes_binding,
    human_notes_warnings,
    normalize_blockers,
    object_sha256,
    parse_human_notes_binding,
    render_human_notes_binding,
    substantive_human_notes,
    validate_handoff_payload,
)
from quality_common import (
    exclusive_file_lock,
    load_json_yaml,
    registry_control_ids,
    safe_relative_path,
    validate_manifest,
    validate_registry,
)


HEADER_BEGIN = "<!-- PROJECT-GUARDRAILS:TASK-HANDOFF:BEGIN -->"
HEADER_END = "<!-- PROJECT-GUARDRAILS:TASK-HANDOFF:END -->"
REQUIRED_READINESS_LEVEL = "TASK_CLAIM_READY"
READINESS_SCHEMA_VERSION = "1.1"
RESERVED_OVERRIDE_PATTERN = re.compile(
    r"(?mi)^\s*(campaign_id|campaign_revision|phase_id|task_id|task_context|"
    r"affected_control_ids|assessed_scope|subject_binding|skill_binding|readiness|"
    r"capabilities|authorization|blocker_catalog|action_policy)\s*:",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    parser.add_argument("--campaign-id")
    parser.add_argument("--campaign-revision", type=int)
    parser.add_argument("--phase-id")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--control", action="append", default=[])
    parser.add_argument("--output")
    parser.add_argument("--payload-output")
    parser.add_argument("--acknowledge-human-notes", action="store_true")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    return parser.parse_args()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(text.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_pair(first: tuple[Path, str], second: tuple[Path, str]) -> None:
    previous = {
        path: path.read_bytes() if path.is_file() else None
        for path, _ in (first, second)
    }
    try:
        atomic_write(*first)
        atomic_write(*second)
    except OSError:
        for path, content in previous.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, content.decode("utf-8"))
        raise


def manual_body(existing: str | None) -> str:
    if existing is None or HEADER_END not in existing:
        return "\n## Implementation Notes\n\n"
    body = existing.split(HEADER_END, 1)[1]
    return body[1:] if body.startswith("\n") else body


def manual_override_fields(body: str) -> list[str]:
    return sorted({match.group(1) for match in RESERVED_OVERRIDE_PATTERN.finditer(body)})


def bind_manual_body(body: str, binding: dict, acknowledge: bool) -> str:
    current = parse_human_notes_binding(body)
    marker = render_human_notes_binding(binding)
    if current is None:
        if substantive_human_notes(body) and not acknowledge:
            return body
        heading = "## Implementation Notes"
        return body.replace(heading, f"{heading}\n\n{marker}", 1)
    if current != binding and (acknowledge or not substantive_human_notes(body)):
        return HUMAN_NOTES_BINDING_PATTERN.sub(marker, body, count=1)
    return body


def readiness_command(args: argparse.Namespace, root: Path, mode: str) -> list[str]:
    command = [
        sys.executable, str(Path(__file__).resolve().parent / "assess_readiness.py"),
        "--root", str(root), "--guardrails-dir", args.guardrails_dir,
    ]
    if mode == "ai_brownfield":
        command.extend([
            "--campaign-id", args.campaign_id,
            "--campaign-revision", str(args.campaign_revision),
            "--phase-id", args.phase_id,
            "--task-id", args.task_id,
        ])
    else:
        for control_id in sorted(set(args.control)):
            command.extend(["--control", control_id])
    command.extend(["--require-level", REQUIRED_READINESS_LEVEL])
    return command


def validate_readiness_report(report: object, returncode: int) -> dict:
    if not isinstance(report, dict):
        raise ValueError("readiness command returned a non-object report")
    if report.get("schema_version") != READINESS_SCHEMA_VERSION:
        raise ValueError("readiness command returned an unsupported schema version")
    if not isinstance(report.get("subject_binding"), dict):
        raise ValueError("readiness command omitted subject_binding")
    levels = report.get("levels")
    if not isinstance(levels, dict) or not isinstance(levels.get(REQUIRED_READINESS_LEVEL), dict):
        raise ValueError(f"readiness command omitted {REQUIRED_READINESS_LEVEL}")
    required = levels[REQUIRED_READINESS_LEVEL]
    status = required.get("status")
    expected_statuses = {0: {"READY"}, 1: {"BLOCKED", "NOT_EVALUATED"}}
    if returncode not in expected_statuses:
        raise ValueError(f"readiness command failed with infrastructure exit {returncode}")
    if status not in expected_statuses[returncode]:
        raise ValueError(
            f"readiness exit {returncode} is inconsistent with {REQUIRED_READINESS_LEVEL}={status}",
        )
    if returncode == 1:
        details = required.get("blocker_details")
        if not isinstance(details, list) or not details:
            raise ValueError("non-ready task report requires typed blocker_details")
        for index, detail in enumerate(details):
            if not isinstance(detail, dict) or any(
                not isinstance(detail.get(field), str) or not detail[field].strip()
                for field in ("code", "category", "message")
            ):
                raise ValueError(
                    f"task blocker_details[{index}] must contain code, category, and message",
                )
    return report


def readiness_report(args: argparse.Namespace, root: Path, mode: str = "ai_brownfield") -> dict:
    command = readiness_command(args, root, mode)
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"readiness command did not return JSON: {result.stderr.strip()}") from exc
    return validate_readiness_report(report, result.returncode)


def task_selection(args: argparse.Namespace, manifest: dict, registry: dict) -> tuple[dict, list[dict], list[str]]:
    mode = manifest["project"]["development_mode"]
    controls_by_id = {control["id"]: control for control in registry["controls"]}
    campaign_values = (args.campaign_id, args.campaign_revision, args.phase_id)
    if mode == "ai_brownfield":
        if any(value is None for value in campaign_values):
            raise CampaignContextError(
                "TASK_CONTEXT_INCOMPLETE",
                "AI brownfield handoff requires campaign-id, campaign-revision, phase-id, and task-id",
            )
        if args.control:
            raise ValueError("AI brownfield handoff derives controls from the registered task")
        context_args = argparse.Namespace(
            campaign_id=args.campaign_id,
            campaign_revision=args.campaign_revision,
            phase_id=args.phase_id,
            task_id=args.task_id,
            claim_scope="task",
        )
        phase, task = campaign_claim_context(manifest, context_args)
        assert task is not None
        affected = sorted(set(task["affected_control_ids"]))
        context = {
            "kind": "registered_campaign_task",
            "development_mode": mode,
            "campaign_id": args.campaign_id,
            "campaign_revision": args.campaign_revision,
            "phase_id": phase["id"],
            "task_id": task["id"],
        }
        scope = task["assessed_scope"]
    else:
        if any(value is not None for value in campaign_values):
            raise ValueError("campaign context is reserved for AI brownfield handoff")
        if not args.control:
            raise ValueError("non-AI-brownfield handoff requires at least one --control")
        unknown = sorted(set(args.control) - set(controls_by_id))
        if unknown:
            raise ValueError(f"unknown task controls: {', '.join(unknown)}")
        affected = sorted(set(args.control))
        context = {
            "kind": "explicit_control_selection",
            "development_mode": mode,
            "task_id": args.task_id,
        }
        scope = sorted({path for control_id in affected for path in controls_by_id[control_id]["scope"]})
    controls = [controls_by_id[control_id] for control_id in affected if control_id in controls_by_id]
    if len(controls) != len(affected):
        raise ValueError("task references controls missing from the active registry")
    return context, controls, scope


def build_payload(args: argparse.Namespace, root: Path, guardrails: Path) -> dict:
    manifest = load_json_yaml(guardrails / "quality-manifest.yaml")
    registry = load_json_yaml(guardrails / "control-registry.yaml")
    framework_errors = validate_registry(registry) + validate_manifest(
        manifest, registry_control_ids(registry),
    )
    if framework_errors:
        raise ValueError("; ".join(sorted(set(framework_errors))))
    context, controls, scope = task_selection(args, manifest, registry)
    capability_ids = sorted({
        capability_id
        for control in controls
        for capability_id in control.get("required_capability_refs", [])
    })
    capabilities_by_id = {
        capability["id"]: capability for capability in registry.get("capabilities", [])
    }
    missing = sorted(set(capability_ids) - set(capabilities_by_id))
    if missing:
        raise ValueError("task control verification references missing capabilities: " + ", ".join(missing))
    required_capabilities = [
        {
            "id": identifier,
            "owner": capabilities_by_id[identifier]["owner"],
            "authorization_required": capabilities_by_id[identifier]["authorization_required"],
        }
        for identifier in capability_ids
    ]
    readiness = readiness_report(args, root, context["development_mode"])
    acquisition = {
        "code": "PRODUCT_ACQUISITION_CAPABILITIES_UNMODELED",
        "category": "authorization",
        "message": (
            "product acquisition capabilities are not modeled by the v3 control plane; "
            "external acquisition remains prohibited unless the project explicitly establishes applicability and authorization"
        ),
    }
    normalized_levels, blockers = normalize_blockers(readiness["levels"], [acquisition])
    return {
        "handoff_schema_version": HANDOFF_SCHEMA_VERSION,
        "subject_binding": readiness["subject_binding"],
        "skill_binding": manifest["framework"],
        "task_context": context,
        "affected_control_ids": [control["id"] for control in controls],
        "assessed_scope": scope,
        "readiness": normalized_levels,
        "blocker_catalog": blockers["catalog"],
        "capabilities": {
            "control_verification": {
                "status": "MODELED",
                "required_capability_ids": capability_ids,
                "required_capabilities": required_capabilities,
                "controls_requiring_authorization": sorted(
                    control["id"] for control in controls
                    if control.get("execution", {}).get("authorization_required") is True
                ),
            },
            "product_acquisition": {
                "status": "UNMODELED",
                "applicability": "NOT_EVALUATED",
                "execution": "BLOCKED",
                "required_capability_ids": None,
                "blocker_ids": blockers["additional_ids"],
            },
        },
        "authorization": {
            "general_policy": {
                "automatic_local_unprivileged": manifest["authority"]["local_unprivileged_controls"],
                "separate_authorization_required": manifest["authority"]["separate_authorization_required"],
            },
        },
        "action_policy": {
            "allowed": [
                "work within the task assessed_scope and affected_control_ids",
                "run local unprivileged controls allowed by the manifest",
            ],
            "prohibited_without_authorization": manifest["authority"]["separate_authorization_required"],
            "machine_fields_are_authoritative": True,
        },
    }


def machine_summary(payload: dict, payload_ref: str, payload_sha256: str) -> str:
    readiness = payload["readiness"]
    blocker_refs = sorted({
        identifier for level in readiness.values() for identifier in level["blocker_ids"]
    })
    context = payload["task_context"]
    lines = [
        "# Task Handoff", "", HEADER_BEGIN,
        f"- Protocol: `{HANDOFF_SCHEMA_VERSION}`",
        f"- Machine payload: `{payload_ref}`",
        f"- Payload SHA-256: `{payload_sha256}`",
        f"- Development mode: `{context['development_mode']}`",
        f"- Task: `{context['task_id']}`",
    ]
    if context["kind"] == "registered_campaign_task":
        lines.extend([
            f"- Campaign: `{context['campaign_id']}` revision `{context['campaign_revision']}`",
            f"- Phase: `{context['phase_id']}`",
        ])
    lines.extend([
        f"- Affected controls: {len(payload['affected_control_ids'])}",
        f"- Scope entries: {len(payload['assessed_scope'])}",
        f"- Referenced readiness blockers: {len(blocker_refs)}",
        "", "## Readiness", "",
        "| Level | Status | Controls | Blockers |",
        "|---|---|---:|---:|",
    ])
    for name, level in readiness.items():
        lines.append(
            f"| `{name}` | `{level['status']}` | {len(level['control_ids'])} | {len(level['blocker_ids'])} |",
        )
    lines.extend([HEADER_END, ""])
    return "\n".join(lines)


def report(status: str, args: argparse.Namespace, payload: dict, warnings: list[dict]) -> str:
    return json.dumps({
        "status": status,
        "output": args.output,
        "payload_output": args.payload_output,
        "task_context": payload["task_context"],
        "warnings": warnings,
    }, indent=2, sort_keys=True)


def locked_main(
    args: argparse.Namespace, root: Path, guardrails: Path,
    output: Path, payload_output: Path,
) -> int:
    existing = output.read_text(encoding="utf-8") if output.is_file() else None
    body = manual_body(existing)
    overrides = manual_override_fields(body)
    if overrides:
        print(json.dumps({
            "status": "MANUAL_OVERRIDE_REJECTED", "reserved_fields": overrides,
        }, indent=2, sort_keys=True))
        return 1
    try:
        payload = build_payload(args, root, guardrails)
        binding = human_notes_binding(payload)
        body = bind_manual_body(body, binding, args.acknowledge_human_notes)
        warnings = human_notes_warnings(body, binding)
        payload["human_notes"] = {
            "status": "STALE" if warnings else "CURRENT",
            "binding": parse_human_notes_binding(body),
            "warnings": warnings,
        }
        payload_errors = validate_handoff_payload(payload)
        if payload_errors:
            raise ValueError("; ".join(payload_errors))
    except CampaignContextError as exc:
        print(json.dumps({
            "status": "HANDOFF_CONTEXT_REJECTED", "blocker": exc.blocker_detail(),
        }, indent=2, sort_keys=True))
        return 1
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "HANDOFF_ERROR", "errors": [str(exc)]}, sort_keys=True))
        return 2
    payload_text = canonical_json(payload) + "\n"
    payload_ref = payload_output.relative_to(root).as_posix()
    expected = machine_summary(payload, payload_ref, object_sha256(payload)) + body
    if args.check:
        payload_current = payload_output.is_file() and payload_output.read_text(encoding="utf-8") == payload_text
        markdown_current = existing == expected
        if not payload_current or not markdown_current:
            print(report("STALE_HANDOFF", args, payload, warnings))
            return 1
        print(report("HANDOFF_CURRENT", args, payload, warnings))
        return 0
    atomic_write_pair((payload_output, payload_text), (output, expected))
    print(report("HANDOFF_RENDERED", args, payload, warnings))
    return 0


def main() -> int:
    args = parse_args()
    if args.acknowledge_human_notes and not args.write:
        print(json.dumps({"status": "HANDOFF_ERROR", "errors": ["--acknowledge-human-notes requires --write"]}))
        return 2
    if not safe_relative_path(args.guardrails_dir):
        print(json.dumps({"status": "HANDOFF_ERROR", "errors": ["paths must be project-relative"]}))
        return 2
    guardrails_relative = Path(args.guardrails_dir)
    args.output = args.output or (guardrails_relative / "evidence" / "task-handoff.md").as_posix()
    args.payload_output = args.payload_output or (
        guardrails_relative / "evidence" / "task-handoff.json"
    ).as_posix()
    if any(not safe_relative_path(path) for path in (args.output, args.payload_output)):
        print(json.dumps({"status": "HANDOFF_ERROR", "errors": ["paths must be project-relative"]}))
        return 2
    root = Path(args.root).resolve()
    guardrails = root / args.guardrails_dir
    output = root / args.output
    payload_output = root / args.payload_output
    evidence_root = (guardrails / "evidence").resolve()
    try:
        guardrails.resolve(strict=False).relative_to(root)
        output.resolve(strict=False).relative_to(evidence_root)
        payload_output.resolve(strict=False).relative_to(evidence_root)
    except ValueError:
        print(json.dumps({
            "status": "HANDOFF_ERROR",
            "errors": ["generated handoff files must be stored under the guardrails evidence directory"],
        }, sort_keys=True))
        return 2
    try:
        with exclusive_file_lock(evidence_root / ".task-handoff.lock"):
            return locked_main(args, root, guardrails, output, payload_output)
    except (OSError, TimeoutError) as exc:
        print(json.dumps({"status": "HANDOFF_ERROR", "errors": [str(exc)]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
