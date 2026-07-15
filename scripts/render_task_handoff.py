#!/usr/bin/env python3
"""Render or lint a deterministic AI brownfield task handoff header."""

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
from quality_common import load_json_yaml, safe_relative_path


HEADER_BEGIN = "<!-- PROJECT-GUARDRAILS:TASK-HANDOFF:BEGIN -->"
HEADER_END = "<!-- PROJECT-GUARDRAILS:TASK-HANDOFF:END -->"
DEFAULT_OUTPUT = ".guardrails/evidence/task-handoff.md"
REQUIRED_READINESS_LEVEL = "TASK_CLAIM_READY"
READINESS_SCHEMA_VERSION = "1.1"
RESERVED_OVERRIDE_PATTERN = re.compile(
    r"(?mi)^\s*(campaign_id|campaign_revision|phase_id|task_id|affected_control_ids|"
    r"assessed_scope|subject_binding|skill_binding|readiness|capabilities|authorization|"
    r"handoff_blocker_details|action_policy)\s*:",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--campaign-revision", required=True, type=int)
    parser.add_argument("--phase-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
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


def machine_header(payload: dict) -> str:
    return (
        "# Task Handoff\n\n"
        f"{HEADER_BEGIN}\n"
        "```json\n"
        f"{json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)}\n"
        "```\n"
        f"{HEADER_END}\n"
    )


def manual_body(existing: str | None) -> str:
    if existing is None or HEADER_END not in existing:
        return "\n## Implementation Notes\n\n"
    body = existing.split(HEADER_END, 1)[1]
    return body[1:] if body.startswith("\n") else body


def manual_override_fields(body: str) -> list[str]:
    return sorted({match.group(1) for match in RESERVED_OVERRIDE_PATTERN.finditer(body)})


def readiness_command(args: argparse.Namespace, root: Path) -> list[str]:
    return [
        sys.executable, str(Path(__file__).resolve().parent / "assess_readiness.py"),
        "--root", str(root), "--guardrails-dir", args.guardrails_dir,
        "--campaign-id", args.campaign_id,
        "--campaign-revision", str(args.campaign_revision),
        "--phase-id", args.phase_id, "--task-id", args.task_id,
        "--require-level", REQUIRED_READINESS_LEVEL,
    ]


def validate_readiness_report(report: object, returncode: int) -> dict:
    if not isinstance(report, dict):
        raise ValueError("readiness command returned a non-object report")
    if report.get("schema_version") != READINESS_SCHEMA_VERSION:
        raise ValueError("readiness command returned an unsupported schema version")
    if not isinstance(report.get("subject_binding"), dict):
        raise ValueError("readiness command omitted subject_binding")
    levels = report.get("levels")
    if not isinstance(levels, dict) or not isinstance(
        levels.get(REQUIRED_READINESS_LEVEL), dict,
    ):
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


def readiness_report(args: argparse.Namespace, root: Path) -> dict:
    command = readiness_command(args, root)
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"readiness command did not return JSON: {result.stderr.strip()}") from exc
    return validate_readiness_report(report, result.returncode)


def build_payload(args: argparse.Namespace, root: Path, guardrails: Path) -> dict:
    manifest = load_json_yaml(guardrails / "quality-manifest.yaml")
    registry = load_json_yaml(guardrails / "control-registry.yaml")
    context = argparse.Namespace(
        campaign_id=args.campaign_id,
        campaign_revision=args.campaign_revision,
        phase_id=args.phase_id,
        task_id=args.task_id,
        claim_scope="task",
    )
    phase, task = campaign_claim_context(manifest, context)
    assert task is not None
    affected = set(task["affected_control_ids"])
    controls = [control for control in registry["controls"] if control["id"] in affected]
    if {control["id"] for control in controls} != affected:
        raise ValueError("task references controls missing from the active registry")
    capability_ids = sorted({
        capability_id
        for control in controls
        for capability_id in control.get("required_capability_refs", [])
    })
    capabilities_by_id = {
        capability["id"]: capability for capability in registry.get("capabilities", [])
    }
    missing_capabilities = sorted(set(capability_ids) - set(capabilities_by_id))
    if missing_capabilities:
        raise ValueError(
            "task control verification references missing capabilities: "
            + ", ".join(missing_capabilities),
        )
    required_capabilities = [
        {
            "id": capability_id,
            "owner": capabilities_by_id[capability_id]["owner"],
            "authorization_required": capabilities_by_id[capability_id][
                "authorization_required"
            ],
        }
        for capability_id in capability_ids
    ]
    authorized_controls = sorted(
        control["id"] for control in controls
        if control.get("execution", {}).get("authorization_required") is True
    )
    readiness = readiness_report(args, root)
    acquisition_blocker = {
        "code": "PRODUCT_ACQUISITION_CAPABILITIES_UNMODELED",
        "category": "authorization",
        "message": (
            "product acquisition capabilities are not modeled by the v3 control plane; "
            "project-owned acquisition authorization is required before execution"
        ),
    }
    return {
        "handoff_schema_version": "1.1",
        "subject_binding": readiness["subject_binding"],
        "skill_binding": manifest["framework"],
        "campaign": {
            "id": args.campaign_id,
            "revision": args.campaign_revision,
            "phase_id": phase["id"],
            "task_id": task["id"],
        },
        "affected_control_ids": sorted(affected),
        "assessed_scope": task["assessed_scope"],
        "readiness": readiness["levels"],
        "capabilities": {
            "control_verification": {
                "status": "MODELED",
                "required_capability_ids": capability_ids,
                "required_capabilities": required_capabilities,
                "controls_requiring_authorization": authorized_controls,
            },
            "product_acquisition": {
                "status": "UNMODELED",
                "applicability": "NOT_EVALUATED",
                "execution": "BLOCKED",
                "required_capability_ids": None,
                "blocker_details": [acquisition_blocker],
            },
        },
        "authorization": {
            "general_policy": {
                "automatic_local_unprivileged": manifest["authority"][
                    "local_unprivileged_controls"
                ],
                "separate_authorization_required": manifest["authority"][
                    "separate_authorization_required"
                ],
            },
        },
        "action_policy": {
            "allowed": [
                "work within the registered task assessed_scope and affected_control_ids",
                "run local unprivileged controls allowed by the manifest",
            ],
            "prohibited_without_authorization": manifest["authority"]["separate_authorization_required"],
            "machine_fields_are_authoritative": True,
        },
    }


def main() -> int:
    args = parse_args()
    if not safe_relative_path(args.guardrails_dir) or not safe_relative_path(args.output):
        print(json.dumps({"status": "HANDOFF_ERROR", "errors": ["paths must be project-relative"]}))
        return 2
    root = Path(args.root).resolve()
    guardrails = root / args.guardrails_dir
    output = root / args.output
    evidence_root = (guardrails / "evidence").resolve()
    try:
        output.resolve(strict=False).relative_to(evidence_root)
    except ValueError:
        print(json.dumps({
            "status": "HANDOFF_ERROR",
            "errors": ["generated handoff must be stored under the guardrails evidence directory"],
        }, sort_keys=True))
        return 2
    existing = output.read_text(encoding="utf-8") if output.is_file() else None
    body = manual_body(existing)
    overrides = manual_override_fields(body)
    if overrides:
        print(json.dumps({
            "status": "MANUAL_OVERRIDE_REJECTED",
            "reserved_fields": overrides,
        }, indent=2, sort_keys=True))
        return 1
    try:
        payload = build_payload(args, root, guardrails)
    except CampaignContextError as exc:
        print(json.dumps({
            "status": "HANDOFF_CONTEXT_REJECTED",
            "blocker": exc.blocker_detail(),
        }, indent=2, sort_keys=True))
        return 1
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "HANDOFF_ERROR", "errors": [str(exc)]}, sort_keys=True))
        return 2
    expected_header = machine_header(payload)
    if args.check:
        if existing is None or not existing.startswith(expected_header):
            print(json.dumps({
                "status": "STALE_HANDOFF",
                "output": args.output,
                "campaign": payload["campaign"],
            }, indent=2, sort_keys=True))
            return 1
        print(json.dumps({"status": "HANDOFF_CURRENT", "output": args.output}, sort_keys=True))
        return 0
    atomic_write(output, expected_header + body)
    print(json.dumps({"status": "HANDOFF_RENDERED", "output": args.output}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
