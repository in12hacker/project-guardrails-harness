#!/usr/bin/env python3
"""Execute quality controls, append evidence, and block unsupported claims."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from quality_common import (
    AUDIT_STAGES,
    MATURITY_LEVELS,
    canonical_digest,
    git_commit,
    git_workspace_digest,
    load_json_yaml,
    maturity_applies,
    validate_manifest,
    validate_ledger,
    validate_registry,
    validate_traceability,
    write_json_yaml,
)


def digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def artifact_evidence(root: Path, execution: dict) -> tuple[list[dict], list[str]]:
    artifacts: list[dict] = []
    missing: list[str] = []
    for raw in execution.get("artifact_paths", []):
        path = root / raw
        if not path.is_file():
            missing.append(raw)
            continue
        digest, size = digest_file(path)
        artifacts.append({"path": raw, "sha256": digest, "bytes": size})
    return artifacts, missing


def execute_control(root: Path, control: dict, authorized: set[str]) -> dict:
    control_id = control["id"]
    execution = control["execution"]
    result = {
        "control_id": control_id,
        "status": "TODO",
        "execution_type": execution["type"],
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if not control.get("applies", False):
        rationale = control.get("applicability_rationale", "")
        confirmer = control.get("applicability_confirmed_by", "")
        result["status"] = "NOT_APPLICABLE" if rationale and confirmer else "FAIL"
        result["detail"] = "confirmed not applicable" if result["status"] == "NOT_APPLICABLE" else "N/A lacks rationale or confirmation"
        return result

    if execution.get("authorization_required") and control_id not in authorized:
        result["status"] = "BLOCKED"
        result["detail"] = f"separate authorization required; rerun with --authorize {control_id}"
        return result

    kind = execution["type"]
    if kind in {"manual", "remote", "privileged"} and not execution.get("command"):
        manual = control.get("manual_evidence")
        current_commit = git_commit(root)
        if (
            isinstance(manual, dict)
            and manual.get("status") == "PASS"
            and manual.get("actor")
            and manual.get("evidence_ref")
            and manual.get("reviewed_at")
            and manual.get("commit") == current_commit
        ):
            result.update({"status": "PASS", "manual_evidence": manual})
        else:
            result["status"] = "BLOCKED" if kind in {"remote", "privileged"} else "TODO"
            result["detail"] = "manual evidence is missing actor, reference, review time, or current commit"
        return result

    if kind in {"file_exists", "file_absent"}:
        path = root / execution.get("path", "")
        exists = path.exists()
        passed = exists if kind == "file_exists" else not exists
        result.update({
            "status": "PASS" if passed else "FAIL",
            "path": str(path),
            "detail": "path condition satisfied" if passed else "path condition failed",
        })
        return result

    if kind not in {"command", "remote", "privileged"}:
        result.update({"status": "FAIL", "detail": f"unsupported execution type: {kind}"})
        return result

    argv = execution.get("command")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        result.update({"status": "FAIL", "detail": "command must be a non-empty argv list"})
        return result
    argv = [part.replace("{commit}", git_commit(root)) for part in argv]
    cwd = root / execution.get("cwd", ".")
    timeout = int(execution.get("timeout_seconds", 3600))
    start = time.monotonic()
    try:
        with tempfile.NamedTemporaryFile(prefix="quality-control-output-") as output:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=output,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PROJECT_GUARDRAILS_CONTROL_ID": control_id},
            )
            timed_out = False
            try:
                exit_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                exit_code = process.wait()
            output.flush()
            output_digest, output_bytes = digest_file(Path(output.name))
        artifacts, missing_artifacts = artifact_evidence(root, execution)
        passed = exit_code == 0 and not timed_out and not missing_artifacts
        result.update({
            "status": "PASS" if passed else "FAIL",
            "command": argv,
            "cwd": str(cwd),
            "exit_code": exit_code,
            "duration_seconds": round(time.monotonic() - start, 3),
            "output_sha256": output_digest,
            "output_bytes": output_bytes,
            "artifacts": artifacts,
        })
        if timed_out:
            result["detail"] = f"timed out after {timeout}s"
        elif missing_artifacts:
            result["detail"] = f"required artifacts missing: {', '.join(missing_artifacts)}"
    except OSError as exc:
        result.update({"status": "BLOCKED", "detail": f"cannot execute command: {exc}"})
    return result


def conclusion(results: list[dict]) -> str:
    statuses = {r["status"] for r in results}
    if "DISPUTED" in statuses:
        return "DISPUTED"
    if "FAIL" in statuses:
        return "FAIL"
    if statuses - {"PASS", "NOT_APPLICABLE"}:
        return "BLOCKED"
    return "PASS"


def stage_assessment(
    runs: list[dict], stage: str, commit: str, target: str,
    registry_sha256: str, workspace_sha256: str, required_control_ids: set[str],
) -> tuple[list[str], set[str]]:
    matching = [
        run for run in runs
        if run.get("commit") == commit
        and run.get("target_maturity") == target
        and run.get("audit_stage") == stage
        and run.get("registry_sha256") == registry_sha256
        and run.get("workspace_sha256") == workspace_sha256
    ]
    latest: dict[str, tuple[str, str]] = {}
    for run in matching:
        for result in run.get("results", []):
            control_id = result.get("control_id")
            if control_id in required_control_ids:
                latest[control_id] = (
                    result.get("status", "STALE"), run.get("actor", ""),
                )
    blockers = sorted(
        control_id for control_id in required_control_ids
        if latest.get(control_id, ("STALE", ""))[0] != "PASS"
    )
    actors = {actor for _, actor in latest.values() if actor}
    return blockers, actors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true", help="execute controls and append a run")
    mode.add_argument("--dry-run", action="store_true", help="list controls without execution")
    mode.add_argument("--claim", action="store_true", help="evaluate audit-stage evidence for a maturity claim")
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    parser.add_argument("--target-maturity", choices=MATURITY_LEVELS)
    parser.add_argument("--audit-stage", choices=sorted(AUDIT_STAGES), default="self")
    parser.add_argument("--actor", default="codex")
    parser.add_argument("--authorize", action="append", default=[])
    parser.add_argument("--control", action="append", default=[])
    parser.add_argument("--claim-scope", choices=("project", "task"), default="project",
                        help="project requires all controls; task requires explicit --control values")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.actor.strip():
        print("FAIL [QF-FRAMEWORK]: actor must be non-empty", file=sys.stderr)
        return 2
    root = Path(args.root).resolve()
    guardrails = root / args.guardrails_dir
    try:
        manifest = load_json_yaml(guardrails / "quality-manifest.yaml")
        registry = load_json_yaml(guardrails / "control-registry.yaml")
        ledger = load_json_yaml(guardrails / "evidence-ledger.json")
        traceability = load_json_yaml(guardrails / "traceability-graph.json")
    except ValueError as exc:
        print(f"FAIL [QF-FRAMEWORK]: {exc}", file=sys.stderr)
        return 2
    errors = (
        validate_manifest(manifest)
        + validate_registry(registry)
        + validate_traceability(traceability, registry)
        + validate_ledger(ledger)
    )
    if errors:
        for error in errors:
            print(f"FAIL [QF-FRAMEWORK]: {error}", file=sys.stderr)
        return 2

    target = args.target_maturity or manifest["project"]["target_maturity"]
    all_controls = [
        c for c in registry["controls"]
        if maturity_applies(c["required_from_maturity"], target)
    ]
    known_ids = {control["id"] for control in all_controls}
    unknown_ids = sorted(set(args.control) - known_ids)
    if unknown_ids:
        print(f"FAIL [QF-FRAMEWORK]: unknown or out-of-maturity controls: {', '.join(unknown_ids)}", file=sys.stderr)
        return 2
    controls = [
        control for control in all_controls
        if not args.control or control["id"] in set(args.control)
    ]
    if args.dry_run:
        for c in controls:
            print(f"{c['id']}: {c['execution']['type']} [{c['required_from_maturity']}] {c['title']}")
        print(f"{len(controls)} controls selected for {target}")
        return 0

    commit = git_commit(root)
    try:
        ledger_relative = (guardrails / "evidence-ledger.json").relative_to(root).as_posix()
        ignored_workspace_paths = {ledger_relative}
    except ValueError:
        ignored_workspace_paths = set()
    workspace_sha256 = git_workspace_digest(root, ignored_workspace_paths)
    registry_sha256 = canonical_digest(registry)
    if args.claim:
        if commit == "unavailable" or workspace_sha256 == "unavailable":
            print("BLOCKED [QF-CLAIM]: Git commit and workspace evidence are required", file=sys.stderr)
            return 1
        if args.claim_scope == "project" and args.control:
            print("FAIL [QF-CLAIM]: project claims cannot select a control subset", file=sys.stderr)
            return 2
        if args.claim_scope == "task" and not args.control:
            print("FAIL [QF-CLAIM]: task claims require explicit --control values", file=sys.stderr)
            return 2
        if args.claim_scope == "project":
            controls = all_controls
        required = set(manifest["audit_policy"]["required_stages"])
        applicable_ids = {
            control["id"] for control in controls if control.get("applies", False)
        }
        scope = manifest["scope"]
        if scope["mode"] == "subproject" and scope.get("overall_project_claim_allowed") is not False:
            print("FAIL [QF-CLAIM]: invalid subproject claim policy", file=sys.stderr)
            return 1
        assessments = {
            stage: stage_assessment(
                ledger.get("runs", []), stage, commit, target,
                registry_sha256, workspace_sha256, applicable_ids,
            )
            for stage in sorted(required)
        }
        blocked_stages = {stage: value[0] for stage, value in assessments.items() if value[0]}
        if blocked_stages:
            details = "; ".join(
                f"{stage}: {', '.join(ids)}" for stage, ids in blocked_stages.items()
            )
            print(f"BLOCKED [QF-CLAIM]: controls without current PASS for {commit}: {details}", file=sys.stderr)
            return 1
        actor_sets = {stage: value[1] for stage, value in assessments.items()}
        inconsistent = {stage: actors for stage, actors in actor_sets.items() if len(actors) != 1}
        if inconsistent:
            details = "; ".join(
                f"{stage}: {', '.join(sorted(actors)) or 'missing'}"
                for stage, actors in inconsistent.items()
            )
            print(f"BLOCKED [QF-CLAIM]: each audit stage needs one identified actor: {details}", file=sys.stderr)
            return 1
        stage_actors = {stage: next(iter(actors)) for stage, actors in actor_sets.items()}
        if len(set(stage_actors.values())) != len(stage_actors):
            print("BLOCKED [QF-CLAIM]: audit stages must use independent actors", file=sys.stderr)
            return 1
        if args.claim_scope == "task":
            scope_label = f"task controls {', '.join(sorted(applicable_ids))}"
        else:
            scope_label = "whole project" if scope["mode"] == "full_repo" else "assessed subproject only"
        print(f"PASS [QF-CLAIM]: {target} is supported for {scope_label} at commit {commit} by {', '.join(sorted(required))}")
        return 0

    authorized = set(args.authorize)
    results = [execute_control(root, c, authorized) for c in controls]
    final = conclusion(results)
    run = {
        "run_id": str(uuid.uuid4()),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "commit": commit,
        "workspace_sha256": workspace_sha256,
        "target_maturity": target,
        "registry_sha256": registry_sha256,
        "selected_control_ids": [control["id"] for control in controls],
        "audit_stage": args.audit_stage,
        "actor": args.actor,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "results": results,
        "conclusion": final,
    }
    run["previous_entry_sha256"] = (
        ledger.get("runs", [])[-1].get("entry_sha256", "INVALID")
        if ledger.get("runs") else "GENESIS"
    )
    run["entry_sha256"] = canonical_digest(run)
    ledger.setdefault("runs", []).append(run)
    ledger.setdefault("audits", [])
    write_json_yaml(guardrails / "evidence-ledger.json", ledger)
    for result in results:
        print(f"{result['status']:>14}  {result['control_id']}")
    print(f"{final} [QF-ASSESSMENT]: {len(results)} controls for {target} at {commit}")
    return 0 if final == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
