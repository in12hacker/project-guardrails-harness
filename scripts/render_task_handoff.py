#!/usr/bin/env python3
"""Render or lint a deterministic, compact task handoff."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from evaluate_quality import CampaignContextError
from handoff_common import (
    HUMAN_NOTES_BINDING_PATTERN,
    canonical_json,
    human_notes_binding,
    human_notes_warnings,
    object_sha256,
    parse_human_notes_binding,
    render_human_notes_binding,
    substantive_human_notes,
    validate_handoff_payload,
)
from handoff_state import (
    build_payload,
    machine_summary,
    manual_body,
)
from quality_common import (
    exclusive_file_lock,
    safe_relative_path,
)


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
    lock_path = evidence_root / ".task-handoff.lock"
    try:
        guardrails.resolve(strict=False).relative_to(root)
        canonical_output = output.resolve(strict=False)
        canonical_payload = payload_output.resolve(strict=False)
        canonical_lock = lock_path.resolve(strict=False)
        canonical_output.relative_to(evidence_root)
        canonical_payload.relative_to(evidence_root)
        canonical_lock.relative_to(evidence_root)
        paths = (output, payload_output, lock_path)
        existing_alias = any(
            left.exists() and right.exists() and left.samefile(right)
            for index, left in enumerate(paths)
            for right in paths[index + 1:]
        )
        lock_has_extra_links = lock_path.exists() and lock_path.stat().st_nlink != 1
    except (OSError, ValueError):
        print(json.dumps({
            "status": "HANDOFF_ERROR",
            "errors": ["generated handoff files must be stored under the guardrails evidence directory"],
        }, sort_keys=True))
        return 2
    if canonical_lock != lock_path or lock_has_extra_links:
        print(json.dumps({
            "status": "HANDOFF_ERROR",
            "errors": ["the reserved handoff lock path must not be redirected"],
        }, sort_keys=True))
        return 2
    if existing_alias or len({canonical_output, canonical_payload, canonical_lock}) != 3:
        print(json.dumps({
            "status": "HANDOFF_ERROR",
            "errors": ["handoff summary, payload, and lock paths must be distinct"],
        }, sort_keys=True))
        return 2
    try:
        with exclusive_file_lock(lock_path):
            return locked_main(args, root, guardrails, output, payload_output)
    except (OSError, TimeoutError) as exc:
        print(json.dumps({"status": "HANDOFF_ERROR", "errors": [str(exc)]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
