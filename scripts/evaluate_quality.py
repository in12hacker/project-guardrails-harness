#!/usr/bin/env python3
"""Execute quality controls, append evidence, and block unsupported claims."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from quality_common import (
    AUDIT_STAGES,
    CLAIM_SCOPES,
    MATURITY_LEVELS,
    campaign_binding_errors,
    canonical_digest,
    exclusive_file_lock,
    framework_binding,
    load_json_yaml,
    maturity_applies,
    project_subject_binding,
    registry_control_ids,
    safe_relative_path,
    selected_source_sha256,
    valid_integer,
    validate_manifest,
    validate_ledger,
    validate_registry,
    validate_traceability,
    write_json_yaml,
)


OUTPUT_LIMIT_BYTES = 64 * 1024
BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+")
OSC_ESCAPE_PATTERN = re.compile(
    r"(?:\x1b\]|\x9d).*?(?:\x07|\x1b\\|\x9c|$)", re.DOTALL,
)
STRING_ESCAPE_PATTERN = re.compile(
    r"(?:\x1b[PX^_]|[\x90\x98\x9e\x9f]).*?(?:\x1b\\|\x9c|$)", re.DOTALL,
)
CSI_ESCAPE_PATTERN = re.compile(r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]")
SINGLE_ESCAPE_PATTERN = re.compile(r"\x1b[@-Z\\-_]")
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
TRUNCATION_MARKER_TEMPLATE = (
    "\n--- OUTPUT TRUNCATED; OMITTED_BYTES={omitted:020d}; TAIL_FOLLOWS ---\n"
)
REDACTION_TRUNCATION_MARKER_TEMPLATE = (
    "\n--- OUTPUT TRUNCATED; RAW_OMITTED_BYTES={raw_omitted:020d}; "
    "REDACTION_OMITTED_BYTES={omitted:020d}; TAIL_FOLLOWS ---\n"
)
RAW_TRUNCATION_PATTERN = re.compile(
    r"OUTPUT TRUNCATED; OMITTED_BYTES=(\d{20}); TAIL_FOLLOWS"
)


class EvidenceBudgetExceeded(OSError):
    """Raised before publishing evidence that would exceed the active budget."""


def digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def artifact_evidence(
    root: Path, execution: dict, evidence_dir: Path, max_active_bytes: int,
) -> tuple[list[dict], list[str], str | None]:
    artifacts: list[dict] = []
    missing: list[str] = []
    for raw in execution.get("artifact_paths", []):
        path = project_file(root, raw)
        if not path.is_file():
            missing.append(raw)
            continue
        try:
            evidence_ref, digest, size = persist_evidence_file(
                root,
                evidence_dir,
                path,
                f".artifact{path.suffix}",
                guardrails=evidence_dir.parents[1],
                max_active_bytes=max_active_bytes,
            )
        except EvidenceBudgetExceeded:
            return artifacts, missing, f"artifact exceeds active evidence budget: {raw}"
        artifacts.append({
            "path": raw,
            "evidence_ref": evidence_ref,
            "sha256": digest,
            "bytes": size,
        })
    return artifacts, missing, None


def normalize_terminal_text(text: str) -> str:
    """Canonicalize terminal output while preserving readable diagnostic text."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = OSC_ESCAPE_PATTERN.sub("", text)
    text = STRING_ESCAPE_PATTERN.sub("", text)
    text = CSI_ESCAPE_PATTERN.sub("", text)
    text = SINGLE_ESCAPE_PATTERN.sub("", text)
    text = CONTROL_CHARACTER_PATTERN.sub("", text)
    return "\n".join(line.rstrip(" \t") for line in text.split("\n"))


def redact_text(text: str, root: Path) -> str:
    """Remove credentials before replacing checkout-specific path text."""
    sensitive_values = {
        value
        for name, value in os.environ.items()
        if value and len(value) >= 4 and any(
            marker in name.upper() for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")
        )
    }
    for value in sorted(sensitive_values, key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    text = BEARER_PATTERN.sub(r"\1[REDACTED]", text)
    checkout = root.resolve()
    checkout_forms = {str(checkout), checkout.as_posix()}
    for value in sorted(checkout_forms, key=len, reverse=True):
        if value and value != checkout.anchor:
            text = text.replace(value, "[PROJECT_ROOT]")
    return text


def redact_output(raw: bytes, root: Path) -> str:
    """Return bounded evidence output with terminal controls and secrets removed."""
    text = normalize_terminal_text(raw.decode("utf-8", errors="replace"))
    return redact_text(text, root)


def ensure_evidence_directory(root: Path, evidence_dir: Path) -> None:
    """Create an in-project evidence directory with deterministic new-path modes."""
    resolved_root = root.resolve()
    try:
        evidence_dir.resolve(strict=False).relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"evidence directory escapes project root: {evidence_dir}") from exc

    missing: list[Path] = []
    candidate = evidence_dir
    while not candidate.exists():
        if candidate.is_symlink():
            raise OSError(f"evidence directory contains a dangling symlink: {candidate}")
        missing.append(candidate)
        if candidate == root or candidate.parent == candidate:
            break
        candidate = candidate.parent
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        for created in reversed(missing):
            created.chmod(0o755)


def content_addressed_path(
    root: Path, evidence_dir: Path, filename: str, expected_digest: str,
) -> tuple[Path, bool]:
    """Return a safe evidence destination and whether valid content exists."""
    ensure_evidence_directory(root, evidence_dir)
    path = evidence_dir / filename
    if path.is_symlink():
        raise OSError(f"content-addressed evidence cannot be a symlink: {path}")
    try:
        path.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"evidence path escapes project root: {path}") from exc
    if not path.exists():
        return path, False
    if not path.is_file() or digest_file(path)[0] != expected_digest:
        raise OSError(f"content-addressed evidence was modified: {path}")
    return path, True


def publish_temporary(
    temporary: Path, destination: Path, expected_digest: str, expected_size: int,
) -> None:
    """Publish complete evidence exactly once and clean up on failure."""
    try:
        actual_digest, actual_size = digest_file(temporary)
        if actual_digest != expected_digest or actual_size != expected_size:
            raise OSError(f"temporary evidence binding mismatch: {temporary}")
        if os.name == "posix":
            temporary.chmod(0o644)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if (
                destination.is_symlink()
                or not destination.is_file()
                or digest_file(destination)[0] != expected_digest
            ):
                raise OSError(
                    f"content-addressed evidence was modified: {destination}"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)


def publish_content_addressed_bytes(
    root: Path, evidence_dir: Path, filename: str, payload: bytes,
) -> Path:
    """Atomically publish immutable evidence without following an output symlink."""
    expected_digest = filename.split(".", 1)[0]
    actual_digest = hashlib.sha256(payload).hexdigest()
    if actual_digest != expected_digest:
        raise ValueError("content-addressed filename does not match payload digest")
    path, exists = content_addressed_path(
        root, evidence_dir, filename, expected_digest,
    )
    if exists:
        return path
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{filename}.", suffix=".tmp", dir=evidence_dir, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        publish_temporary(temporary, path, expected_digest, len(payload))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def publish_content_addressed_file(
    root: Path,
    evidence_dir: Path,
    source: Path,
    suffix: str,
    *,
    guardrails: Path | None = None,
    max_active_bytes: int | None = None,
) -> tuple[Path, str, int]:
    """Snapshot, bind, and atomically publish immutable file evidence."""
    ensure_evidence_directory(root, evidence_dir)
    temporary: Path | None = None
    try:
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(
            prefix=".evidence-", suffix=".tmp", dir=evidence_dir, delete=False,
        ) as output:
            temporary = Path(output.name)
            with source.open("rb") as input_stream:
                for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        expected_digest = digest.hexdigest()
        destination, exists = content_addressed_path(
            root, evidence_dir, f"{expected_digest}{suffix}", expected_digest,
        )
        if guardrails is not None and max_active_bytes is not None:
            current_bytes = control_plane_bytes(guardrails) - temporary.stat().st_size
            additional_bytes = 0 if exists else size
            if current_bytes + additional_bytes > max_active_bytes:
                raise EvidenceBudgetExceeded("active evidence budget exceeded")
        if not exists:
            publish_temporary(temporary, destination, expected_digest, size)
            temporary = None
        return destination, expected_digest, size
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def persist_output(root: Path, evidence_dir: Path, text: str) -> tuple[str, str, int]:
    """Persist canonical redacted output and return its project-relative reference."""
    payload = text.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    path = publish_content_addressed_bytes(
        root, evidence_dir, f"{digest}.log", payload,
    )
    reference = path.relative_to(root).as_posix()
    return reference, digest, len(payload)


def control_plane_bytes(guardrails: Path) -> int:
    """Return active control-plane bytes, excluding immutable archive history."""
    total = 0
    for path in guardrails.rglob("*"):
        try:
            relative = path.relative_to(guardrails)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] == "archive":
            continue
        if path.name == ".ledger.lock" or path.is_symlink() or not path.is_file():
            continue
        total += path.stat().st_size
    return total


def bounded_output(path: Path) -> tuple[bytes, bool]:
    """Keep a bounded diagnostic head and tail while the raw digest covers all bytes."""
    raw_size = path.stat().st_size
    if raw_size <= OUTPUT_LIMIT_BYTES:
        return path.read_bytes(), False

    marker_budget = len(TRUNCATION_MARKER_TEMPLATE.format(omitted=0).encode("utf-8"))
    payload_budget = OUTPUT_LIMIT_BYTES - marker_budget
    head_bytes = payload_budget // 2
    tail_bytes = payload_budget - head_bytes
    omitted_bytes = raw_size - head_bytes - tail_bytes
    marker = TRUNCATION_MARKER_TEMPLATE.format(omitted=omitted_bytes).encode("utf-8")

    with path.open("rb") as stream:
        head = stream.read(head_bytes)
        stream.seek(-tail_bytes, os.SEEK_END)
        tail = stream.read(tail_bytes)
    return head + marker + tail, True


def bounded_redacted_output(text: str) -> tuple[str, bool]:
    """Re-apply the byte limit after credential replacement may expand output."""
    payload = text.encode("utf-8")
    if len(payload) <= OUTPUT_LIMIT_BYTES:
        return text, False

    raw_match = RAW_TRUNCATION_PATTERN.search(text)
    raw_omitted = int(raw_match.group(1)) if raw_match else 0
    marker_budget = len(REDACTION_TRUNCATION_MARKER_TEMPLATE.format(
        raw_omitted=raw_omitted, omitted=0,
    ).encode("utf-8"))
    payload_budget = OUTPUT_LIMIT_BYTES - marker_budget
    head_bytes = payload_budget // 2
    tail_bytes = payload_budget - head_bytes
    omitted_bytes = len(payload) - head_bytes - tail_bytes
    marker = REDACTION_TRUNCATION_MARKER_TEMPLATE.format(
        raw_omitted=raw_omitted, omitted=omitted_bytes,
    )
    head = payload[:head_bytes].decode("utf-8", errors="ignore")
    tail = payload[-tail_bytes:].decode("utf-8", errors="ignore")
    return head + marker + tail, True


def persist_evidence_file(
    root: Path,
    evidence_dir: Path,
    source: Path,
    suffix: str,
    *,
    guardrails: Path | None = None,
    max_active_bytes: int | None = None,
) -> tuple[str, str, int]:
    destination, digest, size = publish_content_addressed_file(
        root,
        evidence_dir,
        source,
        suffix,
        guardrails=guardrails,
        max_active_bytes=max_active_bytes,
    )
    return destination.relative_to(root).as_posix(), digest, size


def project_file(root: Path, relative: str) -> Path:
    if not safe_relative_path(relative):
        raise ValueError(f"path must be project-relative: {relative}")
    candidate = root / relative
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes project through a symlink: {relative}") from exc
    return candidate


def capability_preflight(
    root: Path,
    control: dict,
    capabilities: dict[str, dict],
    authorized: set[str],
) -> tuple[list[dict], str | None, str | None]:
    """Evaluate declared environment capabilities before a product command."""
    observations: list[dict] = []
    for capability_id in control.get("required_capability_refs", []):
        capability = capabilities[capability_id]
        if capability.get("authorization_required") and not (
            capability_id in authorized or control["id"] in authorized
        ):
            return observations, "authorization", f"capability {capability_id} requires authorization"
        preflight = capability["preflight"]
        command = preflight["command"]
        cwd = project_file(root, preflight.get("cwd", "."))
        timeout = int(preflight.get("timeout_seconds", 30))
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            observations.append({
                "capability_id": capability_id,
                "status": "UNAVAILABLE",
                "detail": str(exc),
            })
            return observations, "environment", f"capability {capability_id} is unavailable"
        observation = {
            "capability_id": capability_id,
            "status": "AVAILABLE" if completed.returncode == 0 else "UNAVAILABLE",
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
        observations.append(observation)
        if completed.returncode != 0:
            return observations, "environment", f"capability {capability_id} preflight failed"
    return observations, None, None


def load_debt_observation(
    root: Path, control: dict, baselines: dict[str, dict], evidence_dir: Path,
) -> tuple[dict | None, str | None]:
    policy = control.get("ratchet_policy", {})
    baseline_ref = policy.get("baseline_ref")
    baseline = baselines.get(baseline_ref)
    if baseline is None:
        return None, f"ratchet baseline is missing: {baseline_ref}"
    try:
        path = project_file(root, policy.get("observation_path", ""))
        observation = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, f"ratchet observation is unavailable: {exc}"
    required = {
        "baseline_ref", "baseline_revision", "baseline_source_sha256",
        "baseline_count", "current_count", "new_count", "fixed_count",
    }
    if not isinstance(observation, dict) or set(observation) != required:
        return None, "ratchet observation fields do not match the active contract"
    if observation["baseline_ref"] != baseline_ref:
        return None, "ratchet observation references a different baseline"
    if observation["baseline_revision"] != baseline["revision"]:
        return None, "ratchet observation baseline revision is stale"
    if observation["baseline_source_sha256"] != baseline["source_sha256"]:
        return None, "ratchet observation baseline digest is stale"
    counts = [
        observation.get(name) for name in
        ("baseline_count", "current_count", "new_count", "fixed_count")
    ]
    if any(not valid_integer(value, minimum=0) for value in counts):
        return None, "ratchet observation counts must be non-negative integers"
    if observation["baseline_count"] != baseline["violation_count"]:
        return None, "ratchet observation baseline count does not match the registry"
    expected_current = (
        observation["baseline_count"] - observation["fixed_count"]
        + observation["new_count"]
    )
    if expected_current != observation["current_count"]:
        return None, "ratchet observation count equation is inconsistent"
    reference, digest, size = persist_evidence_file(
        root, evidence_dir, path, ".json",
    )
    observation["observation_ref"] = reference
    observation["observation_sha256"] = digest
    observation["observation_bytes"] = size
    return observation, None


def execute_control(
    root: Path,
    control: dict,
    subject_commit: str,
    authorized: set[str],
    capabilities: dict[str, dict],
    baselines: dict[str, dict],
    evidence_dir: Path,
    evidence_limit: int,
) -> dict:
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

    preflight, blocker_kind, blocker_detail = capability_preflight(
        root, control, capabilities, authorized,
    )
    result["environment"] = {
        "requirements": control.get("required_capability_refs", []),
        "preflight": preflight,
    }
    if blocker_kind:
        result.update({
            "status": "BLOCKED",
            "blocker_kind": blocker_kind,
            "detail": blocker_detail,
        })
        return result

    if execution.get("authorization_required") and control_id not in authorized:
        result["status"] = "BLOCKED"
        result["blocker_kind"] = "authorization"
        result["detail"] = f"separate authorization required; rerun with --authorize {control_id}"
        return result

    kind = execution["type"]
    if kind in {"manual", "remote", "privileged"} and not execution.get("command"):
        manual = control.get("manual_evidence")
        evidence_valid = False
        if isinstance(manual, dict):
            expires_at = dt.datetime.fromisoformat(
                manual["expires_at"].replace("Z", "+00:00")
            )
            try:
                evidence_path = project_file(root, manual["evidence_ref"])
                evidence_digest, _ = digest_file(evidence_path)
            except (OSError, ValueError):
                evidence_digest = "missing"
            evidence_valid = (
                manual.get("status") == "PASS"
                and evidence_digest == manual.get("evidence_sha256")
                and expires_at > dt.datetime.now(dt.timezone.utc)
            )
        if (
            isinstance(manual, dict)
            and manual.get("actor")
            and manual.get("authority_id")
            and manual.get("commit") == subject_commit
            and evidence_valid
        ):
            result.update({"status": "PASS", "manual_evidence": manual})
        else:
            result["status"] = "BLOCKED" if kind in {"remote", "privileged"} else "TODO"
            result["detail"] = "manual evidence is missing, stale, expired, modified, or bound to another commit"
        return result

    if kind in {"file_exists", "file_absent"}:
        path = project_file(root, execution.get("path", ""))
        exists = path.exists()
        passed = exists if kind == "file_exists" else not exists
        result.update({
            "status": "PASS" if passed else "FAIL",
            "path": path.relative_to(root).as_posix(),
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
    argv = [part.replace("{commit}", subject_commit) for part in argv]
    cwd = project_file(root, execution.get("cwd", "."))
    timeout = int(execution.get("timeout_seconds", 3600))
    start = time.monotonic()
    try:
        if control.get("evaluation_mode") == "ratchet_delta":
            observation_path = project_file(
                root, control["ratchet_policy"]["observation_path"],
            )
            observation_path.unlink(missing_ok=True)
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
            raw_output_sha256, raw_output_bytes = digest_file(Path(output.name))
            raw_output, output_truncated = bounded_output(Path(output.name))
        redacted_output, redaction_truncated = bounded_redacted_output(
            redact_output(raw_output, root),
        )
        output_ref, output_digest, output_bytes = persist_output(
            root, evidence_dir, redacted_output,
        )
        artifacts, missing_artifacts, artifact_budget_error = artifact_evidence(
            root, execution, evidence_dir, evidence_limit,
        )
        passed = exit_code == 0 and not timed_out and not missing_artifacts
        debt_observation = None
        ratchet_error = None
        if control.get("evaluation_mode") == "ratchet_delta" and not timed_out:
            debt_observation, ratchet_error = load_debt_observation(
                root, control, baselines, evidence_dir.parent / "observations",
            )
            passed = bool(
                debt_observation
                and debt_observation["current_count"] == 0
                and exit_code == 0
                and not missing_artifacts
            )
        result.update({
            "status": "PASS" if passed else "FAIL",
            "command": [redact_text(part, root) for part in argv],
            "command_sha256": canonical_digest({"argv": argv}),
            "cwd": cwd.relative_to(root).as_posix(),
            "exit_code": exit_code,
            "duration_seconds": round(time.monotonic() - start, 3),
            "output_sha256": output_digest,
            "output_bytes": output_bytes,
            "output_ref": output_ref,
            "raw_output_sha256": raw_output_sha256,
            "raw_output_bytes": raw_output_bytes,
            "output_truncated": output_truncated or redaction_truncated,
            "artifacts": artifacts,
        })
        if artifact_budget_error:
            result.update({
                "status": "BLOCKED",
                "blocker_kind": "evidence",
                "detail": artifact_budget_error,
            })
            return result
        if debt_observation is not None:
            result["debt_observation"] = debt_observation
        if timed_out:
            result["detail"] = f"timed out after {timeout}s"
        elif ratchet_error:
            result["detail"] = ratchet_error
        elif debt_observation is not None and debt_observation["current_count"] > 0:
            result["detail"] = "cleanup debt remains; task/phase ratchet policy may still be evaluated"
        elif missing_artifacts:
            result["detail"] = f"required artifacts missing: {', '.join(missing_artifacts)}"
    except OSError as exc:
        result.update({
            "status": "BLOCKED",
            "blocker_kind": "environment",
            "detail": f"cannot execute command: {exc}",
        })
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


def stage_results(
    runs: list[dict], stage: str, subject_binding: dict, target: str,
    required_control_ids: set[str],
) -> tuple[dict[str, tuple[dict, dict]], set[str], set[str]]:
    matching = [
        run for run in runs
        if run.get("subject_binding") == subject_binding
        and run.get("target_maturity") == target
        and run.get("audit_stage") == stage
    ]
    latest: dict[str, tuple[dict, dict]] = {}
    for run in matching:
        for result in run.get("results", []):
            control_id = result.get("control_id")
            if control_id in required_control_ids:
                latest[control_id] = (result, run)
    authorities = {
        run.get("authority_id", "") for _, run in latest.values()
        if run.get("authority_id")
    }
    contexts = {
        run.get("execution_context", "") for _, run in latest.values()
        if run.get("execution_context")
    }
    return latest, authorities, contexts


class CampaignContextError(ValueError):
    """Typed campaign selection failure shared by claims and readiness."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.details = details

    def blocker_detail(self) -> dict[str, object]:
        return {
            "code": self.code,
            "category": "task_context",
            "message": str(self),
            **self.details,
        }


def campaign_claim_context(manifest: dict, args: argparse.Namespace) -> tuple[dict, dict | None]:
    campaign = manifest["development_policy"].get("active_campaign")
    if not isinstance(campaign, dict):
        raise CampaignContextError(
            "ACTIVE_CAMPAIGN_MISSING",
            "AI brownfield task/phase outcomes require an active campaign",
        )
    required = ["campaign_id", "campaign_revision", "phase_id"]
    if args.claim_scope == "task":
        required.append("task_id")
    missing = [field for field in required if getattr(args, field, None) is None]
    if missing:
        raise CampaignContextError(
            "TASK_CONTEXT_MISSING",
            f"claim context is missing required fields: {', '.join(missing)}",
            missing_fields=missing,
        )
    if args.campaign_id != campaign["id"]:
        raise CampaignContextError(
            "CAMPAIGN_ID_MISMATCH",
            "claim campaign id does not match the active campaign",
            field="campaign_id", expected=campaign["id"], actual=args.campaign_id,
        )
    if args.campaign_revision != campaign["revision"]:
        raise CampaignContextError(
            "CAMPAIGN_REVISION_MISMATCH",
            "claim campaign revision does not match the active campaign",
            field="campaign_revision", expected=campaign["revision"],
            actual=args.campaign_revision,
        )
    phase = next((item for item in campaign["phases"] if item["id"] == args.phase_id), None)
    if phase is None:
        raise CampaignContextError(
            "CAMPAIGN_PHASE_UNKNOWN",
            "claim phase is not registered in the active campaign",
            field="phase_id", actual=args.phase_id,
        )
    if args.claim_scope == "phase":
        if args.task_id:
            raise CampaignContextError(
                "PHASE_CONTEXT_HAS_TASK",
                "phase claims cannot select a task",
                field="task_id", actual=args.task_id,
            )
        return phase, None
    task = next((item for item in phase["tasks"] if item["id"] == args.task_id), None)
    if task is None:
        raise CampaignContextError(
            "CAMPAIGN_TASK_UNKNOWN",
            "claim task is not registered in the selected phase",
            field="task_id", actual=args.task_id,
        )
    return phase, task


def policy_blockers(
    root: Path, registry: dict, selected_control_ids: set[str], absolute: bool,
) -> tuple[list[str], list[str]]:
    framework_errors: list[str] = []
    blockers: list[str] = []
    for mapping in registry.get("federated_rule_mappings", []):
        refs = set(mapping.get("control_refs", []))
        affected = not refs or bool(refs & selected_control_ids)
        if not affected:
            continue
        if mapping.get("mandatory") and mapping.get("status") == "unmapped":
            framework_errors.append(f"mandatory project rule is unmapped: {mapping.get('rule_id')}")
            continue
        if mapping.get("status") == "disputed":
            blockers.append(f"policy_conflict:{mapping.get('rule_id')}")
            continue
        if mapping.get("disposition") == "retired":
            continue
        try:
            source = project_file(root, mapping["source_ref"])
            source_digest = selected_source_sha256(source, mapping["source_selector"])
        except (OSError, ValueError):
            source_digest = "missing"
        if mapping.get("status") == "stale" or source_digest != mapping.get("source_sha256"):
            blockers.append(f"stale_project_rule:{mapping.get('rule_id')}")
    now = dt.datetime.now(dt.timezone.utc)
    for exemption in registry.get("design_scope_exemptions", []):
        if exemption.get("control_id") not in selected_control_ids:
            continue
        review_by = dt.datetime.fromisoformat(exemption["review_by"].replace("Z", "+00:00"))
        if exemption.get("status") != "active" or review_by <= now:
            blockers.append(f"expired_design_exemption:{exemption.get('id')}")
    for baseline in registry.get("baselines", []):
        if baseline.get("control_id") not in selected_control_ids:
            continue
        try:
            source_digest, _ = digest_file(project_file(root, baseline["source_ref"]))
        except (OSError, ValueError):
            source_digest = "missing"
        if source_digest != baseline.get("source_sha256"):
            blockers.append(f"stale_baseline:{baseline.get('id')}")
    if absolute:
        blockers.extend(
            f"open_cleanup_debt:{debt['id']}"
            for debt in registry.get("cleanup_debts", [])
            if debt.get("status") == "open" and debt.get("control_id") in selected_control_ids
        )
    else:
        for debt in registry.get("cleanup_debts", []):
            if debt.get("status") != "open" or debt.get("control_id") not in selected_control_ids:
                continue
            delete_by = dt.datetime.fromisoformat(debt["delete_by"].replace("Z", "+00:00"))
            if delete_by <= now:
                blockers.append(f"overdue_cleanup_debt:{debt['id']}")
    return framework_errors, sorted(set(blockers))


def outcome_blockers(
    root: Path, latest: dict[str, tuple[dict, dict]], controls: dict[str, dict],
    required_ids: set[str], exit_policy: dict | None,
) -> list[str]:
    blockers: list[str] = []
    fixed_total = 0
    policy = exit_policy or {
        "max_new_violations": 0,
        "minimum_fixed_violations": 0,
        "allow_open_cleanup_debt": False,
    }
    for control_id in sorted(required_ids):
        pair = latest.get(control_id)
        if pair is None:
            blockers.append(f"{control_id}:STALE")
            continue
        result, run = pair
        if run.get("conclusion") == "DISPUTED":
            blockers.append(f"{control_id}:DISPUTED")
            continue
        artifacts_current = True
        for artifact in result.get("artifacts", []):
            try:
                digest, size = digest_file(project_file(root, artifact["path"]))
            except (OSError, ValueError):
                artifacts_current = False
                break
            if digest != artifact.get("sha256") or size != artifact.get("bytes"):
                artifacts_current = False
                break
        if not artifacts_current:
            blockers.append(f"{control_id}:STALE_ARTIFACT")
            continue
        if result.get("status") == "PASS":
            observation = result.get("debt_observation")
            if isinstance(observation, dict):
                fixed_total += observation.get("fixed_count", 0)
            continue
        control = controls[control_id]
        observation = result.get("debt_observation")
        ratchet_allowed = (
            control.get("evaluation_mode") == "ratchet_delta"
            and policy.get("allow_open_cleanup_debt") is True
            and isinstance(observation, dict)
            and observation.get("new_count", sys.maxsize) <= policy["max_new_violations"]
        )
        if ratchet_allowed:
            fixed_total += observation.get("fixed_count", 0)
        else:
            blockers.append(f"{control_id}:{result.get('status', 'STALE')}")
    if fixed_total < policy["minimum_fixed_violations"]:
        blockers.append(
            f"ratchet_reduction:{fixed_total}<{policy['minimum_fixed_violations']}"
        )
    return blockers


def reviewed_run_error(
    ledger: dict, args: argparse.Namespace, subject_binding: dict,
    selected_control_ids: set[str],
) -> str | None:
    if args.audit_stage == "self":
        return "self audit cannot use --review-run" if args.review_run else None
    expected_stage = {
        "cross": "self", "release_authority": "cross", "third_party": "release_authority",
    }[args.audit_stage]
    if not args.review_run:
        return f"{args.audit_stage} requires --review-run from {expected_stage}"
    runs = {run.get("run_id"): run for run in ledger.get("runs", [])}
    for run_id in args.review_run:
        source = runs.get(run_id)
        if source is None:
            return f"reviewed run does not exist: {run_id}"
        if source.get("audit_stage") != expected_stage:
            return f"reviewed run {run_id} is not a {expected_stage} run"
        if source.get("subject_binding") != subject_binding:
            return f"reviewed run {run_id} has stale evidence bindings"
        if not selected_control_ids <= set(source.get("selected_control_ids", [])):
            return f"reviewed run {run_id} does not cover the selected controls"
        if source.get("authority_id") == args.authority_id:
            return f"reviewed run {run_id} has the same authority identity"
        if source.get("execution_context") == args.execution_context:
            return f"reviewed run {run_id} has the same execution context"
    return None


def append_chained(collection: list[dict], entry: dict) -> None:
    entry["previous_entry_sha256"] = (
        collection[-1].get("entry_sha256", "INVALID") if collection else "GENESIS"
    )
    entry["entry_sha256"] = canonical_digest(entry)
    collection.append(entry)


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
    parser.add_argument("--authority-id", help="stable authority identity; display labels are insufficient")
    parser.add_argument("--execution-context", help="independent session, runner, or organization context")
    parser.add_argument("--review-run", action="append", default=[],
                        help="prior run id whose original evidence this audit reviewed")
    parser.add_argument("--authorize", action="append", default=[])
    parser.add_argument("--control", action="append", default=[])
    parser.add_argument("--claim-scope", choices=sorted(CLAIM_SCOPES), default="project")
    parser.add_argument("--campaign-id")
    parser.add_argument("--campaign-revision", type=int)
    parser.add_argument("--phase-id")
    parser.add_argument("--task-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.actor.strip():
        print("FAIL [QF-FRAMEWORK]: actor must be non-empty", file=sys.stderr)
        return 2
    root = Path(args.root).resolve()
    try:
        guardrails = project_file(root, args.guardrails_dir)
    except ValueError as exc:
        print(f"FAIL [QF-FRAMEWORK]: {exc}", file=sys.stderr)
        return 2
    try:
        with exclusive_file_lock(guardrails / ".ledger.lock"):
            return locked_main(args, root, guardrails)
    except (OSError, TimeoutError) as exc:
        print(f"BLOCKED [QF-ENVIRONMENT]: {exc}", file=sys.stderr)
        return 1


def locked_main(args: argparse.Namespace, root: Path, guardrails: Path) -> int:
    """Evaluate while holding the project-local evidence ledger lock."""
    try:
        manifest = load_json_yaml(guardrails / "quality-manifest.yaml")
        registry = load_json_yaml(guardrails / "control-registry.yaml")
        ledger = load_json_yaml(guardrails / "evidence-ledger.json")
        traceability = load_json_yaml(guardrails / "traceability-graph.json")
    except ValueError as exc:
        print(f"FAIL [QF-FRAMEWORK]: {exc}", file=sys.stderr)
        return 2
    registry_errors = validate_registry(registry)
    control_ids = registry_control_ids(registry)
    errors = (
        registry_errors
        + validate_manifest(manifest, control_ids)
        + validate_traceability(traceability, registry)
        + validate_ledger(ledger, root)
    )
    if errors:
        for error in errors:
            print(f"FAIL [QF-FRAMEWORK]: {error}", file=sys.stderr)
        return 2

    current_framework = framework_binding(Path(__file__).resolve().parent.parent)
    if manifest["framework"] != current_framework:
        print(
            "BLOCKED [QF-FRAMEWORK]: active Skill revision/content/trust differs from "
            "the manifest binding; register a reviewed campaign revision or regenerate",
            file=sys.stderr,
        )
        return 1

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

    projected_reserve = OUTPUT_LIMIT_BYTES * max(1, len(controls)) + OUTPUT_LIMIT_BYTES
    evidence_limit = manifest["evidence_policy"]["max_active_bytes"]
    try:
        evidence_usage = control_plane_bytes(guardrails)
    except OSError as exc:
        print(f"BLOCKED [QF-EVIDENCE]: cannot measure evidence retention budget: {exc}", file=sys.stderr)
        return 1
    if evidence_usage + projected_reserve > evidence_limit:
        print(
            f"BLOCKED [QF-EVIDENCE]: active evidence budget would exceed "
            f"{evidence_limit} bytes; compact or rotate the active plane after sealing",
            file=sys.stderr,
        )
        return 1

    try:
        guardrails_relative = guardrails.relative_to(root).as_posix()
    except ValueError:
        print("FAIL [QF-FRAMEWORK]: guardrails directory must be inside the project root", file=sys.stderr)
        return 2
    subject_binding = project_subject_binding(
        root, guardrails_relative, manifest, registry, traceability, current_framework,
    )
    commit = subject_binding["commit"]
    registry_sha256 = subject_binding["registry_sha256"]
    if args.claim:
        if commit == "unavailable" or subject_binding["tree_sha256"] == "unavailable":
            print("BLOCKED [QF-CLAIM]: Git subject commit and tree evidence are required", file=sys.stderr)
            return 1
        if args.claim_scope in {"project", "release", "phase"} and args.control:
            print(f"FAIL [QF-CLAIM]: {args.claim_scope} claims cannot select a control subset", file=sys.stderr)
            return 2
        if (
            args.claim_scope in {"project", "release"}
            and MATURITY_LEVELS.index(target) >= MATURITY_LEVELS.index("commercial_ready")
            and current_framework["trust_level"] != "signed_release"
        ):
            print(
                "BLOCKED [QF-CLAIM]: commercial project/release claims require a "
                "clean, cryptographically verified signed Skill tag",
                file=sys.stderr,
            )
            return 1
        development_mode = manifest["project"]["development_mode"]
        campaign_binding = None
        exit_policy = None
        if args.claim_scope in {"task", "phase"} and (
            development_mode == "ai_brownfield" or args.claim_scope == "phase"
        ):
            try:
                phase, task = campaign_claim_context(manifest, args)
            except ValueError as exc:
                print(f"BLOCKED [QF-{args.claim_scope.upper()}]: {exc}", file=sys.stderr)
                return 1
            campaign = manifest["development_policy"]["active_campaign"]
            campaign_errors = campaign_binding_errors(
                campaign, registry_sha256, current_framework,
            )
            if campaign_errors:
                for error in campaign_errors:
                    print(f"BLOCKED [QF-CAMPAIGN]: {error}", file=sys.stderr)
                return 1
            if campaign["target_maturity"] != target:
                print("BLOCKED [QF-CAMPAIGN]: campaign target maturity does not match the claim", file=sys.stderr)
                return 1
            registration = task if args.claim_scope == "task" else phase
            requested = set(args.control)
            registered = set(registration["affected_control_ids"])
            if requested and requested != registered:
                print("FAIL [QF-CLAIM]: selected controls do not match the campaign registration", file=sys.stderr)
                return 2
            controls = [control for control in all_controls if control["id"] in registered]
            if len(controls) != len(registered):
                print("FAIL [QF-CLAIM]: campaign references controls outside target maturity", file=sys.stderr)
                return 2
            exit_policy = registration["exit_policy"]
            campaign_binding = {
                "campaign_id": campaign["id"],
                "campaign_revision": campaign["revision"],
                "phase_id": phase["id"],
                "task_id": task["id"] if task else None,
            }
        elif args.claim_scope == "task":
            if not args.control:
                print("FAIL [QF-CLAIM]: human task claims require explicit --control values", file=sys.stderr)
                return 2
        elif any((args.campaign_id, args.campaign_revision, args.phase_id, args.task_id)):
            print("FAIL [QF-CLAIM]: campaign context is only valid for task/phase claims", file=sys.stderr)
            return 2
        if args.claim_scope in {"project", "release"}:
            controls = all_controls
        required = set(manifest["claim_policies"][args.claim_scope]["required_stages"])
        applicable_ids = {
            control["id"] for control in controls if control.get("applies", False)
        }
        controls_by_id = {control["id"]: control for control in controls}
        framework_errors, policy_failures = policy_blockers(
            root, registry, set(controls_by_id), args.claim_scope in {"project", "release"},
        )
        if framework_errors:
            for error in framework_errors:
                print(f"FAIL [QF-FRAMEWORK]: {error}", file=sys.stderr)
            return 2
        if policy_failures:
            print(
                f"BLOCKED [QF-CLAIM]: policy/debt blockers: {', '.join(policy_failures)}",
                file=sys.stderr,
            )
            return 1
        scope = manifest["scope"]
        if scope["mode"] == "subproject" and scope.get("overall_project_claim_allowed") is not False:
            print("FAIL [QF-CLAIM]: invalid subproject claim policy", file=sys.stderr)
            return 1
        if scope["mode"] == "subproject" and args.claim_scope in {"project", "release"}:
            print(
                "BLOCKED [QF-SCOPE]: subproject evidence cannot support a project or release claim",
                file=sys.stderr,
            )
            return 1
        assessments = {
            stage: stage_results(
                ledger.get("runs", []), stage, subject_binding, target, applicable_ids,
            )
            for stage in sorted(required)
        }
        blocked_stages = {
            stage: outcome_blockers(root, value[0], controls_by_id, applicable_ids, exit_policy)
            for stage, value in assessments.items()
        }
        blocked_stages = {stage: value for stage, value in blocked_stages.items() if value}
        if blocked_stages:
            details = "; ".join(
                f"{stage}: {', '.join(ids)}" for stage, ids in blocked_stages.items()
            )
            print(f"BLOCKED [QF-CLAIM]: controls without current PASS for {commit}: {details}", file=sys.stderr)
            return 1
        authority_sets = {stage: value[1] for stage, value in assessments.items()}
        context_sets = {stage: value[2] for stage, value in assessments.items()}
        inconsistent = {
            stage: authorities for stage, authorities in authority_sets.items()
            if len(authorities) != 1 or len(context_sets[stage]) != 1
        }
        if inconsistent:
            details = "; ".join(
                f"{stage}: {', '.join(sorted(authorities)) or 'missing'}"
                for stage, authorities in inconsistent.items()
            )
            print(f"BLOCKED [QF-CLAIM]: each stage needs one authority and execution context: {details}", file=sys.stderr)
            return 1
        stage_authorities = {
            stage: next(iter(authorities)) for stage, authorities in authority_sets.items()
        }
        stage_contexts = {
            stage: next(iter(contexts)) for stage, contexts in context_sets.items()
        }
        if (
            len(set(stage_authorities.values())) != len(stage_authorities)
            or len(set(stage_contexts.values())) != len(stage_contexts)
        ):
            print("BLOCKED [QF-CLAIM]: audit stages must use independent authorities and contexts", file=sys.stderr)
            return 1
        supporting_run_ids = sorted({
            run["run_id"]
            for latest, _, _ in assessments.values()
            for _, run in latest.values()
        })
        claim = {
            "claim_id": str(uuid.uuid4()),
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "claim_scope": args.claim_scope,
            "outcome": "COMPLETED" if args.claim_scope in {"task", "phase"} else "PASS",
            "subject_binding": subject_binding,
            "target_maturity": target,
            "control_ids": sorted(applicable_ids),
            "audit_stages": sorted(required),
            "stage_authorities": stage_authorities,
            "stage_contexts": stage_contexts,
            "supporting_run_ids": supporting_run_ids,
            "campaign": campaign_binding,
            "storage_binding": {
                "runs_chain_head_sha256": (
                    ledger["runs"][-1]["entry_sha256"] if ledger.get("runs") else "GENESIS"
                ),
                "audits_chain_head_sha256": (
                    ledger["audits"][-1]["entry_sha256"] if ledger.get("audits") else "GENESIS"
                ),
            },
        }
        append_chained(ledger.setdefault("claims", []), claim)
        write_json_yaml(guardrails / "evidence-ledger.json", ledger)
        if args.claim_scope in {"task", "phase"}:
            scope_label = f"{args.claim_scope} controls {', '.join(sorted(applicable_ids))}"
            print(
                f"COMPLETED [QF-{args.claim_scope.upper()}]: controls support {scope_label} at commit "
                f"{commit} by {', '.join(sorted(required))}; project maturity is unchanged"
            )
            return 0
        else:
            scope_label = "whole project" if scope["mode"] == "full_repo" else "assessed subproject only"
        print(f"PASS [QF-{args.claim_scope.upper()}]: {target} is supported for {scope_label} at commit {commit} by {', '.join(sorted(required))}")
        return 0

    if not args.authority_id or not args.execution_context:
        print("FAIL [QF-FRAMEWORK]: --authority-id and --execution-context are required for runs", file=sys.stderr)
        return 2
    authority = next(
        (
            item for item in manifest["audit_policy"]["authorities"]
            if item["id"] == args.authority_id
        ),
        None,
    )
    if authority is None or args.audit_stage not in authority["allowed_stages"]:
        print(
            f"FAIL [QF-AUDIT]: authority {args.authority_id} is not registered for {args.audit_stage}",
            file=sys.stderr,
        )
        return 2
    selected_control_ids = {control["id"] for control in controls}
    review_error = reviewed_run_error(
        ledger, args, subject_binding, selected_control_ids,
    )
    if review_error:
        print(f"BLOCKED [QF-AUDIT]: {review_error}", file=sys.stderr)
        return 1
    authorized = set(args.authorize)
    capabilities = {
        capability["id"]: capability for capability in registry.get("capabilities", [])
    }
    baselines = {baseline["id"]: baseline for baseline in registry.get("baselines", [])}
    results = [
        execute_control(
            root, control, commit, authorized, capabilities, baselines,
            guardrails / "evidence" / "outputs",
            evidence_limit,
        )
        for control in controls
    ]
    final = conclusion(results)
    reviewed_runs = {
        run["run_id"]: run for run in ledger.get("runs", [])
        if run.get("run_id") in set(args.review_run)
    }
    if reviewed_runs:
        prior_status = {
            result["control_id"]: result.get("status")
            for run in reviewed_runs.values() for result in run.get("results", [])
            if result.get("control_id") in selected_control_ids
        }
        current_status = {result["control_id"]: result.get("status") for result in results}
        if prior_status != current_status:
            final = "DISPUTED"
    run = {
        "run_id": str(uuid.uuid4()),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "subject_binding": subject_binding,
        "target_maturity": target,
        "selected_control_ids": [control["id"] for control in controls],
        "audit_stage": args.audit_stage,
        "actor": args.actor,
        "authority_id": args.authority_id,
        "execution_context": args.execution_context,
        "reviewed_run_ids": sorted(args.review_run),
        "reviewed_evidence_sha256": canonical_digest({"runs": list(reviewed_runs.values())}),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "results": results,
        "conclusion": final,
        "storage_binding": {
            "evidence_sha256": canonical_digest({"results": results}),
        },
    }
    append_chained(ledger.setdefault("runs", []), run)
    if args.audit_stage != "self":
        audit = {
            "audit_id": str(uuid.uuid4()),
            "timestamp": run["timestamp"],
            "audit_stage": args.audit_stage,
            "run_id": run["run_id"],
            "reviewed_run_ids": sorted(args.review_run),
            "authority_id": args.authority_id,
            "execution_context": args.execution_context,
            "reviewed_evidence_sha256": run["reviewed_evidence_sha256"],
            "subject_binding": subject_binding,
            "storage_binding": {
                "run_entry_sha256": run["entry_sha256"],
            },
            "conclusion": final,
        }
        append_chained(ledger.setdefault("audits", []), audit)
    write_json_yaml(guardrails / "evidence-ledger.json", ledger)
    for result in results:
        print(f"{result['status']:>14}  {result['control_id']}")
    print(f"{final} [QF-ASSESSMENT]: {len(results)} controls for {target} at {commit}")
    return 0 if final == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
