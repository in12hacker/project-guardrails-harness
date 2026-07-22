#!/usr/bin/env python3
"""Return bounded, selector-based projections of structured quality state."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from handoff_common import (
    HANDOFF_SCHEMA_VERSION,
    canonical_json,
    human_notes_binding,
    human_notes_warnings,
    object_sha256,
    parse_human_notes_binding,
    validate_handoff_payload,
)
from quality_common import (
    load_json_yaml,
    registry_control_ids,
    safe_relative_path,
    validate_ledger,
    validate_manifest,
    validate_registry,
    validate_traceability,
)


DEFAULT_MAX_BYTES = 16_384
HARD_MAX_BYTES = 65_536
DEFAULT_LIMIT = 20
HARD_LIMIT = 100
HANDOFF_DIGEST_PATTERN = re.compile(r"(?m)^- Payload SHA-256: `(?P<digest>[0-9a-f]{64})`$")


class QuerySelectorError(ValueError):
    def __init__(self, status: str, identifiers: list[str], message: str) -> None:
        super().__init__(message)
        self.status = status
        self.identifiers = sorted(set(identifiers))


class QueryResultTooLarge(ValueError):
    def __init__(self, item_count: int, limit: int) -> None:
        super().__init__("selected results exceed the item limit")
        self.item_count = item_count
        self.limit = limit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    parser.add_argument("--handoff-output")
    parser.add_argument("--handoff-payload")
    parser.add_argument(
        "--view", required=True,
        choices=("summary", "control", "trace", "evidence", "readiness", "blocker", "binding", "human-notes"),
    )
    parser.add_argument("--id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    return parser.parse_args()


def selected(items: list[dict], identifiers: list[str], fields: tuple[str, ...], limit: int) -> list[dict]:
    if identifiers:
        wanted = set(identifiers)
        matches = [
            item for item in items
            if any(item.get(field) in wanted for field in fields)
        ]
        resolved = {
            item.get(field)
            for item in matches
            for field in fields
            if item.get(field) in wanted
        }
        require_resolved(identifiers, resolved)
        return bounded_selection(matches, limit)
    return items[:limit]


def require_resolved(identifiers: list[str], resolved: set[str]) -> None:
    unresolved = sorted(set(identifiers) - resolved)
    if unresolved:
        raise QuerySelectorError(
            "QUERY_SELECTOR_NOT_FOUND", unresolved,
            "one or more requested identifiers do not exist in this view",
        )


def reject_unsupported_selectors(view: str, identifiers: list[str]) -> None:
    if identifiers:
        raise QuerySelectorError(
            "QUERY_SELECTOR_UNSUPPORTED", identifiers,
            f"the {view} view does not accept --id selectors",
        )


def bounded_selection(items: list, limit: int) -> list:
    if len(items) > limit:
        raise QueryResultTooLarge(len(items), limit)
    return items


def load_handoff(payload_path: Path, summary_path: Path) -> dict | None:
    if not payload_path.is_file() and not summary_path.is_file():
        return None
    if not payload_path.is_file() or not summary_path.is_file():
        raise ValueError("task handoff payload and summary must either both exist or both be absent")
    payload_text = payload_path.read_text(encoding="utf-8")
    handoff = load_json_yaml(payload_path)
    if handoff.get("handoff_schema_version") != HANDOFF_SCHEMA_VERSION:
        raise ValueError("task handoff uses an unsupported schema version")
    if payload_text != canonical_json(handoff) + "\n":
        raise ValueError("task handoff payload is not canonical JSON")
    digest_match = HANDOFF_DIGEST_PATTERN.search(summary_path.read_text(encoding="utf-8"))
    if digest_match is None or digest_match.group("digest") != object_sha256(handoff):
        raise ValueError("task handoff payload digest does not match its summary")
    errors = validate_handoff_payload(handoff)
    if errors:
        raise ValueError("; ".join(errors))
    return handoff


def validate_current_handoff(
    handoff: dict, root: Path, guardrails: Path, guardrails_dir: str,
    payload_path: Path, summary_path: Path,
) -> None:
    """Re-derive machine state; pair digests alone do not establish truth."""
    from render_task_handoff import build_payload, machine_summary, manual_body

    context = handoff["task_context"]
    registered = context["kind"] == "registered_campaign_task"
    derivation_args = argparse.Namespace(
        guardrails_dir=guardrails_dir,
        campaign_id=context.get("campaign_id") if registered else None,
        campaign_revision=context.get("campaign_revision") if registered else None,
        phase_id=context.get("phase_id") if registered else None,
        task_id=context["task_id"],
        control=[] if registered else handoff["affected_control_ids"],
    )
    current = build_payload(derivation_args, root, guardrails)
    body = manual_body(summary_path.read_text(encoding="utf-8"))
    binding = human_notes_binding(current)
    warnings = human_notes_warnings(body, binding)
    current["human_notes"] = {
        "status": "STALE" if warnings else "CURRENT",
        "binding": parse_human_notes_binding(body),
        "warnings": warnings,
    }
    mismatches = sorted(
        field for field, value in current.items()
        if handoff.get(field) != value
    )
    if mismatches:
        raise ValueError(
            "task handoff is stale or inconsistent with current project state: "
            + ", ".join(mismatches),
        )
    payload_ref = payload_path.relative_to(root).as_posix()
    expected_summary = machine_summary(
        current, payload_ref, object_sha256(current),
    ) + body
    if summary_path.read_text(encoding="utf-8") != expected_summary:
        raise ValueError("task handoff summary is stale or inconsistent with its payload")


def project_evidence_results(run: dict, results: list[dict]) -> dict:
    """Return a clearly labeled projection, never a forged ledger entry."""
    projection = {
        key: value
        for key, value in run.items()
        if key not in {"results", "previous_entry_sha256", "entry_sha256"}
    }
    projection["results"] = results
    projection["projection"] = {
        "kind": "ledger_run_results",
        "source_entry_sha256": run.get("entry_sha256"),
        "source_previous_entry_sha256": run.get("previous_entry_sha256"),
        "source_result_count": len(run.get("results", [])),
        "selected_result_count": len(results),
    }
    return projection


def build_result(
    args: argparse.Namespace, root: Path, guardrails: Path,
    payload_path: Path, summary_path: Path,
) -> dict:
    manifest = load_json_yaml(guardrails / "quality-manifest.yaml")
    registry = load_json_yaml(guardrails / "control-registry.yaml")
    framework_errors = validate_registry(registry) + validate_manifest(
        manifest, registry_control_ids(registry),
    )
    if framework_errors:
        raise ValueError("; ".join(framework_errors))
    handoff_views = {"summary", "readiness", "blocker", "binding", "human-notes"}
    handoff = load_handoff(payload_path, summary_path) if args.view in handoff_views else None
    if handoff is not None:
        validate_current_handoff(
            handoff, root, guardrails, args.guardrails_dir, payload_path, summary_path,
        )

    if args.view == "summary":
        reject_unsupported_selectors(args.view, args.id)
        ledger = load_json_yaml(guardrails / "evidence-ledger.json")
        ledger_errors = validate_ledger(ledger, root)
        if ledger_errors:
            raise ValueError("; ".join(ledger_errors))
        return {
            "project": manifest["project"],
            "framework": manifest["framework"],
            "control_count": len(registry["controls"]),
            "run_count": len(ledger.get("runs", [])),
            "active_campaign": None if manifest["development_policy"].get("active_campaign") is None else {
                key: manifest["development_policy"]["active_campaign"].get(key)
                for key in ("id", "revision", "target_maturity", "owner")
            },
            "handoff": None if handoff is None else {
                "task_context": handoff["task_context"],
                "readiness": {
                    key: value["status"] for key, value in handoff["readiness"].items()
                },
                "human_notes": handoff["human_notes"],
            },
        }
    if args.view == "control":
        return {"controls": selected(registry["controls"], args.id, ("id",), args.limit)}
    if args.view == "trace":
        trace = load_json_yaml(guardrails / "traceability-graph.json")
        trace_errors = validate_traceability(trace, registry)
        if trace_errors:
            raise ValueError("; ".join(trace_errors))
        links = trace.get("links", [])
        if args.id:
            identifiers = set(args.id)
            resolved = {
                value
                for link in links
                for value in (
                    [link.get("control_id")]
                    + [
                        item
                        for field in ("requirement_ids", "risk_ids", "verification_ids")
                        for item in link.get(field, [])
                    ]
                )
                if value in identifiers
            }
            require_resolved(args.id, resolved)
            links = [
                link for link in links
                if link.get("control_id") in identifiers
                or any(
                    identifiers.intersection(link.get(field, []))
                    for field in ("requirement_ids", "risk_ids", "verification_ids")
                )
            ]
        return {"trace": bounded_selection(links, args.limit) if args.id else links[:args.limit]}
    if args.view == "evidence":
        ledger = load_json_yaml(guardrails / "evidence-ledger.json")
        ledger_errors = validate_ledger(ledger, root)
        if ledger_errors:
            raise ValueError("; ".join(ledger_errors))
        runs = ledger.get("runs", [])
        if args.id:
            identifiers = set(args.id)
            resolved = {
                identifier
                for run in runs
                for identifier in (
                    [run.get("run_id")]
                    + [result.get("control_id") for result in run.get("results", [])]
                )
                if identifier in identifiers
            }
            require_resolved(args.id, resolved)
            projected = []
            for run in runs:
                if run.get("run_id") in identifiers:
                    projected.append(run)
                    continue
                results = [
                    result for result in run.get("results", [])
                    if result.get("control_id") in identifiers
                ]
                if results:
                    projected.append(project_evidence_results(run, results))
            runs = projected
        return {"runs": bounded_selection(runs, args.limit) if args.id else runs[:args.limit]}
    if handoff is None:
        raise ValueError("task handoff has not been generated")
    if args.view == "readiness":
        values = handoff["readiness"]
        keys = args.id or list(values)
        require_resolved(args.id, set(values))
        if args.id:
            bounded_selection(keys, args.limit)
        return {"readiness": {key: values[key] for key in keys[:args.limit]}}
    if args.view == "blocker":
        values = handoff["blocker_catalog"]
        keys = args.id or list(values)
        require_resolved(args.id, set(values))
        if args.id:
            bounded_selection(keys, args.limit)
        return {"blockers": {key: values[key] for key in keys[:args.limit]}}
    if args.view == "binding":
        reject_unsupported_selectors(args.view, args.id)
        return {
            "subject_binding": handoff["subject_binding"],
            "skill_binding": handoff["skill_binding"],
            "task_context": handoff["task_context"],
        }
    reject_unsupported_selectors(args.view, args.id)
    return {"human_notes": handoff["human_notes"]}


def main() -> int:
    args = parse_args()
    args.id = list(dict.fromkeys(args.id))
    if not safe_relative_path(args.guardrails_dir):
        print(json.dumps({"status": "QUERY_ERROR", "errors": ["guardrails directory must be project-relative"]}))
        return 2
    guardrails_relative = Path(args.guardrails_dir)
    args.handoff_output = args.handoff_output or (
        guardrails_relative / "evidence" / "task-handoff.md"
    ).as_posix()
    args.handoff_payload = args.handoff_payload or (
        guardrails_relative / "evidence" / "task-handoff.json"
    ).as_posix()
    if any(
        not safe_relative_path(path)
        for path in (args.handoff_output, args.handoff_payload)
    ):
        print(json.dumps({"status": "QUERY_ERROR", "errors": ["paths must be project-relative"]}))
        return 2
    if not 1 <= args.limit <= HARD_LIMIT or not 256 <= args.max_bytes <= HARD_MAX_BYTES:
        print(json.dumps({"status": "QUERY_ERROR", "errors": ["limit or max-bytes is outside the supported range"]}))
        return 2
    try:
        root = Path(args.root).resolve()
        guardrails = root / args.guardrails_dir
        guardrails.resolve(strict=False).relative_to(root)
        evidence_root = (guardrails / "evidence").resolve()
        payload_path = root / args.handoff_payload
        summary_path = root / args.handoff_output
        payload_path.resolve(strict=False).relative_to(evidence_root)
        summary_path.resolve(strict=False).relative_to(evidence_root)
        result = build_result(
            args, root, guardrails, payload_path, summary_path,
        )
    except QuerySelectorError as exc:
        print(canonical_json({
            "status": exc.status,
            "view": args.view,
            "identifiers": exc.identifiers,
            "errors": [str(exc)],
        }))
        return 1
    except QueryResultTooLarge as exc:
        print(canonical_json({
            "status": "QUERY_RESULT_TOO_LARGE",
            "view": args.view,
            "limit": exc.limit,
            "item_count": exc.item_count,
            "hint": "increase --limit or request fewer identifiers",
        }))
        return 1
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "QUERY_ERROR", "errors": [str(exc)]}, sort_keys=True))
        return 2
    envelope = {"status": "QUERY_OK", "view": args.view, "result": result}
    output = canonical_json(envelope) + "\n"
    if len(output.encode("utf-8")) > args.max_bytes:
        print(canonical_json({
            "status": "QUERY_RESULT_TOO_LARGE",
            "view": args.view,
            "max_bytes": args.max_bytes,
            "hint": "use --id, reduce --limit, or request a narrower view",
        }))
        return 1
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
