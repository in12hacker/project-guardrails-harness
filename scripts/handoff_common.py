#!/usr/bin/env python3
"""Shared deterministic helpers for task handoff payloads and queries."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


HANDOFF_SCHEMA_VERSION = "1.2"
HUMAN_NOTES_BINDING_PREFIX = "<!-- PROJECT-GUARDRAILS:HUMAN-NOTES-BINDING "
HUMAN_NOTES_BINDING_PATTERN = re.compile(
    r"^<!-- PROJECT-GUARDRAILS:HUMAN-NOTES-BINDING (?P<payload>\{.*\}) -->$",
    re.MULTILINE,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def blocker_id(detail: dict) -> str:
    identity = {
        "code": detail["code"],
        "category": detail["category"],
        "message": detail["message"],
    }
    return f"BLK-{object_sha256(identity)[:16].upper()}"


def normalize_blockers(levels: dict, additional: list[dict]) -> tuple[dict, dict]:
    catalog: dict[str, dict] = {}

    def register(detail: dict) -> str:
        identifier = blocker_id(detail)
        normalized = {
            key: detail[key]
            for key in sorted(detail)
            if key != "id"
        }
        previous = catalog.get(identifier)
        if previous is not None and previous != normalized:
            raise ValueError(f"blocker ID collision: {identifier}")
        catalog[identifier] = normalized
        return identifier

    normalized_levels: dict[str, dict] = {}
    for name, level in sorted(levels.items()):
        details = level.get("blocker_details", [])
        identifiers = sorted({register(detail) for detail in details})
        normalized_levels[name] = {
            "status": level.get("status"),
            "control_ids": sorted(set(level.get("control_ids", []))),
            "blocker_ids": identifiers,
        }
        if level.get("supporting_run_ids"):
            normalized_levels[name]["supporting_run_ids"] = sorted(
                set(level["supporting_run_ids"]),
            )
    additional_ids = sorted({register(detail) for detail in additional})
    return normalized_levels, {
        "catalog": {key: catalog[key] for key in sorted(catalog)},
        "additional_ids": additional_ids,
    }


def human_notes_binding(payload: dict) -> dict:
    context = payload["task_context"]
    return {
        "subject_sha256": object_sha256(payload["subject_binding"]),
        "task_id": context["task_id"],
        "campaign_id": context.get("campaign_id"),
        "campaign_revision": context.get("campaign_revision"),
        "phase_id": context.get("phase_id"),
    }


def render_human_notes_binding(binding: dict) -> str:
    return f"{HUMAN_NOTES_BINDING_PREFIX}{canonical_json(binding)} -->"


def parse_human_notes_binding(body: str) -> dict | None:
    matches = list(HUMAN_NOTES_BINDING_PATTERN.finditer(body))
    if len(matches) > 1:
        raise ValueError("Implementation Notes contains duplicate binding markers")
    if not matches:
        return None
    try:
        value = json.loads(matches[0].group("payload"))
    except json.JSONDecodeError as exc:
        raise ValueError("Implementation Notes binding marker is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Implementation Notes binding marker must contain an object")
    return value


def substantive_human_notes(body: str) -> bool:
    without_marker = HUMAN_NOTES_BINDING_PATTERN.sub("", body)
    without_heading = re.sub(r"(?m)^## Implementation Notes\s*$", "", without_marker)
    return bool(without_heading.strip())


def human_notes_warnings(body: str, expected: dict) -> list[dict]:
    if not substantive_human_notes(body):
        return []
    actual = parse_human_notes_binding(body)
    if actual == expected:
        return []
    return [{
        "code": "STALE_HUMAN_NOTES",
        "category": "handoff",
        "message": "Implementation Notes are not bound to the current subject and task context",
        "expected_binding": expected,
        "actual_binding": actual,
    }]


def validate_handoff_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["task handoff payload must be an object"]
    required = {
        "handoff_schema_version", "subject_binding", "skill_binding", "task_context",
        "affected_control_ids", "assessed_scope", "readiness", "blocker_catalog",
        "capabilities", "authorization", "action_policy", "human_notes",
    }
    errors: list[str] = []
    if set(payload) != required:
        errors.append("task handoff payload fields do not match protocol 1.2")
    if payload.get("handoff_schema_version") != HANDOFF_SCHEMA_VERSION:
        errors.append("task handoff payload uses an unsupported schema version")
    for field in ("subject_binding", "skill_binding", "task_context", "capabilities"):
        if not isinstance(payload.get(field), dict):
            errors.append(f"task handoff {field} must be an object")
    context = payload.get("task_context")
    if isinstance(context, dict):
        kind = context.get("kind")
        mode = context.get("development_mode")
        if kind not in {"registered_campaign_task", "explicit_control_selection"}:
            errors.append("task handoff task_context kind is invalid")
        if mode not in {
            "ai_greenfield", "ai_brownfield", "human_greenfield", "human_brownfield",
        }:
            errors.append("task handoff task_context development_mode is invalid")
        if not isinstance(context.get("task_id"), str) or not context["task_id"]:
            errors.append("task handoff task_context task_id is required")
        if kind == "registered_campaign_task" and any(
            context.get(field) in (None, "")
            for field in ("campaign_id", "campaign_revision", "phase_id")
        ):
            errors.append("task handoff registered campaign context is incomplete")
        if kind == "registered_campaign_task" and (
            mode != "ai_brownfield"
            or isinstance(context.get("campaign_revision"), bool)
            or not isinstance(context.get("campaign_revision"), int)
            or context["campaign_revision"] < 1
        ):
            errors.append("task handoff registered campaign context mode or revision is invalid")
        if kind == "explicit_control_selection" and any(
            field in context for field in ("campaign_id", "campaign_revision", "phase_id")
        ):
            errors.append("task handoff explicit control context contains campaign fields")
        if kind == "explicit_control_selection" and mode == "ai_brownfield":
            errors.append("task handoff AI brownfield context cannot use explicit control selection")
    for field in ("affected_control_ids", "assessed_scope"):
        value = payload.get(field)
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item for item in value
        ):
            errors.append(f"task handoff {field} must be a non-empty string list")
        elif len(value) != len(set(value)):
            errors.append(f"task handoff {field} contains duplicates")
    catalog = payload.get("blocker_catalog")
    if not isinstance(catalog, dict):
        errors.append("task handoff blocker_catalog must be an object")
        catalog = {}
    else:
        for identifier, detail in catalog.items():
            if not isinstance(detail, dict) or any(
                not isinstance(detail.get(field), str) or not detail[field]
                for field in ("code", "category", "message")
            ):
                errors.append(f"task handoff blocker {identifier} is invalid")
            elif identifier != blocker_id(detail):
                errors.append(f"task handoff blocker {identifier} has an invalid stable ID")
    levels = payload.get("readiness")
    expected_levels = {
        "DEVELOPMENT_START_READY", "TASK_CLAIM_READY", "MERGE_READY", "RELEASE_READY",
    }
    if not isinstance(levels, dict) or set(levels) != expected_levels:
        errors.append("task handoff readiness levels are incomplete")
        levels = {}
    for name, level in levels.items():
        if not isinstance(level, dict):
            errors.append(f"task handoff readiness {name} must be an object")
            continue
        allowed_level_fields = {"status", "control_ids", "blocker_ids", "supporting_run_ids"}
        if not set(level) <= allowed_level_fields:
            errors.append(f"task handoff readiness {name} contains unknown fields")
        status = level.get("status")
        if status not in {"READY", "BLOCKED", "NOT_EVALUATED"}:
            errors.append(f"task handoff readiness {name} status is invalid")
        control_ids = level.get("control_ids")
        if not isinstance(control_ids, list) or not all(
            isinstance(item, str) and item for item in control_ids
        ):
            errors.append(f"task handoff readiness {name} control_ids is invalid")
        refs = level.get("blocker_ids")
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            errors.append(f"task handoff readiness {name} blocker_ids is invalid")
        elif not set(refs) <= set(catalog):
            errors.append(f"task handoff readiness {name} references unknown blockers")
        elif status == "READY" and refs:
            errors.append(f"task handoff readiness {name} is READY but references blockers")
        elif status in {"BLOCKED", "NOT_EVALUATED"} and not refs:
            errors.append(f"task handoff readiness {name} is non-ready without blockers")
    capabilities = payload.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    acquisition = capabilities.get("product_acquisition", {})
    acquisition_refs = acquisition.get("blocker_ids") if isinstance(acquisition, dict) else None
    if (
        not isinstance(acquisition_refs, list)
        or not acquisition_refs
        or not set(acquisition_refs) <= set(catalog)
    ):
        errors.append("task handoff product acquisition references unknown blockers")
    if isinstance(acquisition, dict) and (
        acquisition.get("status") != "UNMODELED"
        or acquisition.get("applicability") != "NOT_EVALUATED"
        or acquisition.get("execution") != "BLOCKED"
        or acquisition.get("required_capability_ids") is not None
    ):
        errors.append("task handoff v3 product acquisition state is invalid")
    notes = payload.get("human_notes")
    if not isinstance(notes, dict) or notes.get("status") not in {"CURRENT", "STALE"}:
        errors.append("task handoff human_notes status is invalid")
    elif (
        (notes["status"] == "STALE" and not notes.get("warnings"))
        or (notes["status"] == "CURRENT" and notes.get("warnings"))
    ):
        errors.append("task handoff human_notes status does not match its warnings")
    return errors
