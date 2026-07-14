#!/usr/bin/env python3
"""Shared stdlib-only helpers for the project quality control plane."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import datetime as dt
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


MATURITY_LEVELS = (
    "prototype",
    "engineering_ready",
    "production_ready",
    "commercial_ready",
    "regulated_ready",
)

CONTROL_STATUSES = {
    "PASS", "FAIL", "BLOCKED", "TODO", "NOT_APPLICABLE", "DISPUTED", "STALE",
}

AUDIT_STAGES = {"self", "cross", "release_authority", "third_party"}
SCHEMA_VERSION = "3.0"
CLAIM_SCOPES = {"task", "phase", "project", "release"}
FEDERATION_STATUSES = {"current", "stale", "disputed", "unmapped"}
FEDERATION_DISPOSITIONS = {"federated", "migrated", "compiled", "retired"}
DEBT_STATUSES = {"open", "closed"}
EXEMPTION_STATUSES = {"active", "expired", "revoked"}
ARCHIVE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
MARKDOWN_FENCE_OPEN_PATTERN = re.compile(
    r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<info>.*)$",
)
MARKDOWN_FENCE_CLOSE_PATTERN = re.compile(
    r"^ {0,3}(?P<marker>`+|~+)[ \t]*$",
)
MARKDOWN_ATX_HEADING_PATTERN = re.compile(
    r"^ {0,3}(?P<marks>#{1,6})(?:[ \t]+.*)?$",
)

DEPENDENCY_MUTATION_PREFIXES = {
    ("npm", "install"), ("npm", "i"), ("pnpm", "install"),
    ("yarn", "install"), ("pip", "install"), ("pip3", "install"),
    ("cargo", "add"), ("cargo", "update"), ("go", "get"),
    ("apt", "install"), ("apt-get", "install"), ("brew", "install"),
}


def load_json_yaml(path: Path) -> dict[str, Any]:
    """Load the framework's JSON-compatible YAML subset."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"required framework file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} is not JSON-compatible YAML: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain an object at the root")
    return data


def write_json_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace a JSON-compatible YAML document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def exclusive_file_lock(path: Path, timeout_seconds: float = 30.0):
    """Serialize ledger readers/writers across local agent processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    deadline = time.monotonic() + timeout_seconds
    locked = False
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    if stream.read(1) == b"":
                        stream.write(b"0")
                        stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out acquiring control-plane lock: {path}")
                time.sleep(0.05)
        yield
    finally:
        try:
            if not locked:
                pass
            elif os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_archive_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value not in {".", ".."}
        and ARCHIVE_ID_PATTERN.fullmatch(value) is not None
    )


def markdown_heading_sections(text: str) -> list[dict[str, Any]]:
    """Return canonical ATX sections outside CommonMark-style code fences.

    Backtick and tilde fences require at least three markers. A close must use
    the opening character with at least the opening length; an unclosed fence
    suppresses headings through EOF. Sections end only at the next unfenced
    ATX heading of the same or a higher level.
    """
    lines = text.splitlines(keepends=True)
    headings: list[dict[str, Any]] = []
    occurrences: dict[str, int] = {}
    fence_character: str | None = None
    fence_length = 0

    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        if fence_character is not None:
            closing = MARKDOWN_FENCE_CLOSE_PATTERN.fullmatch(content)
            if closing is not None:
                marker = closing.group("marker")
                if marker[0] == fence_character and len(marker) >= fence_length:
                    fence_character = None
                    fence_length = 0
            continue

        opening = MARKDOWN_FENCE_OPEN_PATTERN.fullmatch(content)
        if opening is not None:
            marker = opening.group("marker")
            info = opening.group("info")
            if marker[0] != "`" or "`" not in info:
                fence_character = marker[0]
                fence_length = len(marker)
                continue

        heading = MARKDOWN_ATX_HEADING_PATTERN.fullmatch(content)
        if heading is None:
            continue
        value = content.strip()
        occurrences[value] = occurrences.get(value, 0) + 1
        headings.append({
            "value": value,
            "occurrence": occurrences[value],
            "level": len(heading.group("marks")),
            "start_line": index + 1,
            "_start_index": index,
        })

    for position, section in enumerate(headings):
        end = len(lines)
        for candidate in headings[position + 1:]:
            if candidate["level"] <= section["level"]:
                end = candidate["_start_index"]
                break
        section_text = "".join(lines[section["_start_index"]:end])
        section["end_line"] = end
        section["sha256"] = sha256_text(section_text)
        del section["_start_index"]
    return headings


def selected_source_sha256(path: Path, selector: dict[str, Any]) -> str | None:
    """Hash a whole file or one stable Markdown heading section."""
    kind = selector.get("kind")
    if kind == "whole_file":
        return file_sha256(path)
    if kind != "markdown_heading":
        return None
    heading = selector.get("value")
    occurrence = selector.get("occurrence", 1)
    if not isinstance(heading, str) or not heading.startswith("#"):
        return None
    if not isinstance(occurrence, int) or occurrence < 1:
        return None
    sections = markdown_heading_sections(path.read_text(encoding="utf-8"))
    match = next(
        (
            section for section in sections
            if section["value"] == heading and section["occurrence"] == occurrence
        ),
        None,
    )
    return match["sha256"] if match is not None else None


def canonical_digest(data: dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_text(payload)


def _git_output(root: Path, argv: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *argv], cwd=root, check=False, capture_output=True,
            text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return result.returncode, result.stdout.strip()


def skill_content_digest(skill_root: Path) -> str:
    """Hash every normative or executable Skill resource without following links."""
    digest = hashlib.sha256()
    roots = (
        skill_root / "SKILL.md", skill_root / "agents", skill_root / "references",
        skill_root / "schemas", skill_root / "scripts", skill_root / "templates",
    )
    files: list[Path] = []
    for candidate in roots:
        if candidate.is_file() or candidate.is_symlink():
            files.append(candidate)
        elif candidate.is_dir():
            files.extend(
                path for path in candidate.rglob("*")
                if (path.is_file() or path.is_symlink())
                and "__pycache__" not in path.parts and path.suffix != ".pyc"
            )
    for path in sorted(files, key=lambda item: item.relative_to(skill_root).as_posix()):
        relative = path.relative_to(skill_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"link\0")
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        else:
            digest.update(b"file\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def framework_binding(skill_root: Path) -> dict[str, Any]:
    """Return the current Skill identity, content digest, and verified trust level."""
    skill_root = skill_root.resolve()
    content_sha256 = skill_content_digest(skill_root)
    head_status, head = _git_output(skill_root, ["rev-parse", "HEAD"])
    status_code, status = _git_output(
        skill_root,
        [
            "status", "--porcelain", "--", "SKILL.md", "agents", "references",
            "schemas", "scripts", "templates",
        ],
    )
    dirty = head_status != 0 or status_code != 0 or bool(status)
    revision = head if head_status == 0 and head else f"sha256:{content_sha256}"
    trust_level = "unverified"
    signed_tag = None
    if not dirty and head_status == 0:
        tag_status, tags = _git_output(skill_root, ["tag", "--points-at", "HEAD"])
        if tag_status == 0:
            for tag in sorted(filter(None, tags.splitlines())):
                verified, _ = _git_output(skill_root, ["verify-tag", tag])
                if verified == 0:
                    signed_tag = tag
                    trust_level = "signed_release"
                    break
        if trust_level == "unverified":
            verified, _ = _git_output(skill_root, ["verify-commit", "HEAD"])
            if verified == 0:
                trust_level = "verified_commit"
    return {
        "name": "project-guardrails-harness",
        "revision": revision,
        "content_sha256": content_sha256,
        "dirty": dirty,
        "trust_level": trust_level,
        "signed_tag": signed_tag,
    }


def build_traceability_graph(registry: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_from_registry_sha256": canonical_digest(registry),
        "links": [
            {
                "requirement_ids": control.get("requirement_ids", []),
                "risk_ids": control.get("risk_ids", []),
                "control_id": control.get("id"),
                "verification_ids": control.get("verification_ids", []),
                "evidence_required": control.get("evidence_required", []),
            }
            for control in registry.get("controls", [])
        ],
    }


def git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def evidence_storage_paths(guardrails_relative: str) -> set[str]:
    """Paths whose persistence must not change the audited project subject."""
    prefix = guardrails_relative.rstrip("/")
    return {
        f"{prefix}/.ledger.lock",
        f"{prefix}/archive",
        f"{prefix}/evidence",
        f"{prefix}/evidence-ledger.json",
    }


def git_subject_commit(root: Path, ignored: set[str]) -> str:
    """Return the latest commit that changed non-evidence project content."""
    pathspec = ["."]
    for relative in sorted(ignored):
        pathspec.extend([
            f":(exclude){relative}",
            f":(exclude){relative}/**",
        ])
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", *pathspec],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else "unavailable"


def git_workspace_digest(root: Path, ignored: set[str] | None = None) -> str:
    """Hash all tracked and unignored untracked files without following symlinks."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    if result.returncode != 0:
        return "unavailable"
    ignored = ignored or set()
    digest = hashlib.sha256()
    paths = sorted({item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item})
    for relative in paths:
        normalized = Path(relative).as_posix()
        if any(normalized == item or normalized.startswith(f"{item}/") for item in ignored):
            continue
        path = root / relative
        digest.update(normalized.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        try:
            if path.is_symlink():
                digest.update(b"link\0")
                digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
            elif path.is_file():
                digest.update(
                    b"file-executable\0" if path.stat().st_mode & 0o111
                    else b"file-regular\0"
                )
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            else:
                digest.update(b"missing\0")
        except OSError:
            return "unavailable"
        digest.update(b"\0")
    return digest.hexdigest()


def project_subject_binding(
    root: Path,
    guardrails_relative: str,
    manifest: dict[str, Any],
    registry: dict[str, Any],
    traceability: dict[str, Any],
    framework: dict[str, Any],
) -> dict[str, str]:
    """Bind evidence to audited content independently from evidence persistence."""
    ignored = evidence_storage_paths(guardrails_relative)
    return {
        "commit": git_subject_commit(root, ignored),
        "tree_sha256": git_workspace_digest(root, ignored),
        "manifest_sha256": canonical_digest(manifest),
        "registry_sha256": canonical_digest(registry),
        "traceability_sha256": canonical_digest(traceability),
        "framework_revision": framework["revision"],
        "framework_sha256": framework["content_sha256"],
    }


def campaign_baseline_binding(
    root: Path,
    guardrails_relative: str,
    registry: dict[str, Any],
    framework: dict[str, Any],
) -> dict[str, str]:
    """Bind a campaign baseline without hashing the manifest that stores it."""
    ignored = evidence_storage_paths(guardrails_relative)
    ignored.add(f"{guardrails_relative.rstrip('/')}/quality-manifest.yaml")
    return {
        "commit": git_subject_commit(root, ignored),
        "tree_sha256": git_workspace_digest(root, ignored),
        "registry_sha256": canonical_digest(registry),
        "framework_revision": framework["revision"],
        "framework_sha256": framework["content_sha256"],
    }


def maturity_applies(required_from: str, target: str) -> bool:
    if required_from not in MATURITY_LEVELS or target not in MATURITY_LEVELS:
        return False
    return MATURITY_LEVELS.index(required_from) <= MATURITY_LEVELS.index(target)


def unknown_fields(value: dict[str, Any], allowed: set[str], path: str) -> list[str]:
    """Report unknown fields where silent schema extension could alter claims."""
    return [f"{path}.{field} is not allowed" for field in sorted(set(value) - allowed)]


def non_empty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value.lower()
    )


def validate_subject_binding(value: Any, path: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path} must be an object"]
    errors = unknown_fields(
        value,
        {
            "commit", "tree_sha256", "manifest_sha256", "registry_sha256",
            "traceability_sha256", "framework_revision", "framework_sha256",
        },
        path,
    )
    if not isinstance(value.get("commit"), str) or not value["commit"].strip():
        errors.append(f"{path}.commit is required")
    for field in (
        "tree_sha256", "manifest_sha256", "registry_sha256",
        "traceability_sha256", "framework_sha256",
    ):
        if not valid_sha256(value.get(field)):
            errors.append(f"{path}.{field} must be a SHA-256 digest")
    if not isinstance(value.get("framework_revision"), str) or not value["framework_revision"].strip():
        errors.append(f"{path}.framework_revision is required")
    return errors


def validate_campaign_baseline_binding(value: Any, path: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path} must be an object"]
    errors = unknown_fields(
        value,
        {
            "commit", "tree_sha256", "registry_sha256",
            "framework_revision", "framework_sha256",
        },
        path,
    )
    if not isinstance(value.get("commit"), str) or not value["commit"].strip():
        errors.append(f"{path}.commit is required")
    for field in ("tree_sha256", "registry_sha256", "framework_sha256"):
        if not valid_sha256(value.get(field)):
            errors.append(f"{path}.{field} must be a SHA-256 digest")
    if not isinstance(value.get("framework_revision"), str) or not value["framework_revision"].strip():
        errors.append(f"{path}.framework_revision is required")
    return errors


def campaign_binding_errors(
    campaign: dict[str, Any], registry_sha256: str, framework: dict[str, Any],
) -> list[str]:
    """Report drift that requires a new AI brownfield campaign revision."""
    baseline = campaign["baseline_binding"]
    errors: list[str] = []
    if baseline["registry_sha256"] != registry_sha256:
        errors.append("registry drift requires a campaign revision")
    if (
        baseline["framework_revision"] != framework["revision"]
        or baseline["framework_sha256"] != framework["content_sha256"]
    ):
        errors.append("Skill drift requires a campaign revision")
    return errors


def valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def path_inside_root(root: Path, relative: str) -> Path | None:
    if not safe_relative_path(relative):
        return None
    candidate = root / relative
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def validate_exit_policy(policy: Any, path: str) -> list[str]:
    if not isinstance(policy, dict):
        return [f"{path} must be an object"]
    errors = unknown_fields(
        policy,
        {"max_new_violations", "minimum_fixed_violations", "allow_open_cleanup_debt"},
        path,
    )
    for field in ("max_new_violations", "minimum_fixed_violations"):
        if not isinstance(policy.get(field), int) or policy[field] < 0:
            errors.append(f"{path}.{field} must be a non-negative integer")
    if not isinstance(policy.get("allow_open_cleanup_debt"), bool):
        errors.append(f"{path}.allow_open_cleanup_debt must be boolean")
    return errors


def validate_campaign(campaign: Any, control_ids: set[str] | None = None) -> list[str]:
    if not isinstance(campaign, dict):
        return ["development_policy.active_campaign must be an object or null"]
    errors = unknown_fields(
        campaign,
        {
            "id", "revision", "baseline_binding", "target_maturity", "assessed_scope",
            "owner", "phases",
        },
        "development_policy.active_campaign",
    )
    prefix = "development_policy.active_campaign"
    for field in ("id", "owner"):
        if not isinstance(campaign.get(field), str) or not campaign[field].strip():
            errors.append(f"{prefix}.{field} is required")
    if not isinstance(campaign.get("revision"), int) or campaign["revision"] < 1:
        errors.append(f"{prefix}.revision must be an integer >= 1")
    errors.extend(validate_campaign_baseline_binding(
        campaign.get("baseline_binding"), f"{prefix}.baseline_binding",
    ))
    if campaign.get("target_maturity") not in MATURITY_LEVELS:
        errors.append(f"{prefix}.target_maturity is invalid")
    if not non_empty_strings(campaign.get("assessed_scope")):
        errors.append(f"{prefix}.assessed_scope must be a non-empty string list")
    phases = campaign.get("phases")
    if not isinstance(phases, list) or not phases:
        return errors + [f"{prefix}.phases must be a non-empty array"]
    phase_ids: set[str] = set()
    task_ids: set[str] = set()
    for phase_index, phase in enumerate(phases):
        phase_path = f"{prefix}.phases[{phase_index}]"
        if not isinstance(phase, dict):
            errors.append(f"{phase_path} must be an object")
            continue
        errors.extend(unknown_fields(
            phase,
            {"id", "title", "affected_control_ids", "assessed_scope", "exit_policy", "tasks"},
            phase_path,
        ))
        phase_id = phase.get("id")
        if not isinstance(phase_id, str) or not phase_id:
            errors.append(f"{phase_path}.id is required")
        elif phase_id in phase_ids:
            errors.append(f"duplicate campaign phase id: {phase_id}")
        else:
            phase_ids.add(phase_id)
        if not isinstance(phase.get("title"), str) or not phase["title"].strip():
            errors.append(f"{phase_path}.title is required")
        phase_controls = phase.get("affected_control_ids")
        if not non_empty_strings(phase_controls):
            errors.append(f"{phase_path}.affected_control_ids must be a non-empty string list")
        elif control_ids is not None:
            unknown = sorted(set(phase_controls) - control_ids)
            if unknown:
                errors.append(f"{phase_path}.affected_control_ids contains unknown controls: {', '.join(unknown)}")
        if not non_empty_strings(phase.get("assessed_scope")):
            errors.append(f"{phase_path}.assessed_scope must be a non-empty string list")
        errors.extend(validate_exit_policy(phase.get("exit_policy"), f"{phase_path}.exit_policy"))
        tasks = phase.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            errors.append(f"{phase_path}.tasks must be a non-empty array")
            continue
        for task_index, task in enumerate(tasks):
            task_path = f"{phase_path}.tasks[{task_index}]"
            if not isinstance(task, dict):
                errors.append(f"{task_path} must be an object")
                continue
            errors.extend(unknown_fields(
                task,
                {"id", "kind", "affected_control_ids", "assessed_scope", "exit_policy"},
                task_path,
            ))
            task_id = task.get("id")
            if not isinstance(task_id, str) or not task_id:
                errors.append(f"{task_path}.id is required")
            elif task_id in task_ids:
                errors.append(f"duplicate campaign task id: {task_id}")
            else:
                task_ids.add(task_id)
            if task.get("kind") not in {"debt_reduction", "framework_adoption", "correctness_fix"}:
                errors.append(f"{task_path}.kind is invalid")
            task_controls = task.get("affected_control_ids")
            if not non_empty_strings(task_controls):
                errors.append(f"{task_path}.affected_control_ids must be a non-empty string list")
            else:
                if isinstance(phase_controls, list) and not set(task_controls) <= set(phase_controls):
                    errors.append(f"{task_path}.affected_control_ids must be within its phase")
                if control_ids is not None:
                    unknown = sorted(set(task_controls) - control_ids)
                    if unknown:
                        errors.append(f"{task_path}.affected_control_ids contains unknown controls: {', '.join(unknown)}")
            if not non_empty_strings(task.get("assessed_scope")):
                errors.append(f"{task_path}.assessed_scope must be a non-empty string list")
            errors.extend(validate_exit_policy(task.get("exit_policy"), f"{task_path}.exit_policy"))
    return errors


def validate_manifest(
    manifest: dict[str, Any], control_ids: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    errors.extend(unknown_fields(
        manifest,
        {
            "schema_version", "framework", "project", "profile", "scope", "authority",
            "audit_policy", "development_policy", "claim_policies", "evidence_policy",
        },
        "manifest",
    ))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"quality manifest schema_version must be {SCHEMA_VERSION}; seal the old plane and regenerate")
    framework = manifest.get("framework")
    project = manifest.get("project")
    profile = manifest.get("profile")
    scope = manifest.get("scope")
    authority = manifest.get("authority")
    audit = manifest.get("audit_policy")
    development_policy = manifest.get("development_policy")
    claim_policies = manifest.get("claim_policies")
    evidence_policy = manifest.get("evidence_policy")
    for name, value in (
        ("framework", framework), ("project", project), ("profile", profile), ("scope", scope),
        ("authority", authority), ("audit_policy", audit),
        ("development_policy", development_policy),
        ("claim_policies", claim_policies),
        ("evidence_policy", evidence_policy),
    ):
        if not isinstance(value, dict):
            errors.append(f"manifest.{name} must be an object")
    if errors:
        return errors
    errors.extend(unknown_fields(
        framework,
        {"name", "revision", "content_sha256", "dirty", "trust_level", "signed_tag"},
        "framework",
    ))
    if framework.get("name") != "project-guardrails-harness":
        errors.append("framework.name must be project-guardrails-harness")
    if not isinstance(framework.get("revision"), str) or not framework["revision"].strip():
        errors.append("framework.revision is required")
    if not valid_sha256(framework.get("content_sha256")):
        errors.append("framework.content_sha256 must be a SHA-256 digest")
    if not isinstance(framework.get("dirty"), bool):
        errors.append("framework.dirty must be boolean")
    if framework.get("trust_level") not in {"unverified", "verified_commit", "signed_release"}:
        errors.append("framework.trust_level is invalid")
    signed_tag = framework.get("signed_tag")
    if signed_tag is not None and (not isinstance(signed_tag, str) or not signed_tag.strip()):
        errors.append("framework.signed_tag must be null or a non-empty string")
    if framework.get("trust_level") == "signed_release" and signed_tag is None:
        errors.append("framework.signed_tag is required for signed_release")
    errors.extend(unknown_fields(
        evidence_policy,
        {
            "profile", "retention", "max_active_bytes", "redact_outputs",
            "sealing_profile", "predecessor_archive",
        },
        "evidence_policy",
    ))
    evidence_profile = evidence_policy.get("profile")
    retention = evidence_policy.get("retention")
    sealing_profile = evidence_policy.get("sealing_profile")
    if evidence_profile not in {"open_source", "commercial", "regulated", "custom"}:
        errors.append("evidence_policy.profile is invalid")
    if retention not in {"project_lifetime", "release_lifetime", "permanent"}:
        errors.append("evidence_policy.retention is invalid")
    if (
        not isinstance(evidence_policy.get("max_active_bytes"), int)
        or evidence_policy["max_active_bytes"] < 1048576
    ):
        errors.append("evidence_policy.max_active_bytes must be an integer >= 1048576")
    if evidence_policy.get("redact_outputs") is not True:
        errors.append("evidence_policy.redact_outputs must be true")
    if sealing_profile not in {"sha256_chain", "sigstore_bundle"}:
        errors.append("evidence_policy.sealing_profile is invalid")
    if evidence_profile in {"commercial", "regulated"}:
        if retention != "permanent":
            errors.append(f"{evidence_profile} evidence requires permanent retention")
        if sealing_profile != "sigstore_bundle":
            errors.append(f"{evidence_profile} evidence requires sigstore_bundle sealing")
    predecessor = evidence_policy.get("predecessor_archive")
    if predecessor is not None:
        if not isinstance(predecessor, dict):
            errors.append("evidence_policy.predecessor_archive must be null or an object")
        else:
            errors.extend(unknown_fields(
                predecessor,
                {"archive_id", "archive_sha256", "validation_status", "signature_status"},
                "evidence_policy.predecessor_archive",
            ))
            if not valid_archive_id(predecessor.get("archive_id")):
                errors.append("evidence_policy.predecessor_archive.archive_id is invalid")
            if not valid_sha256(predecessor.get("archive_sha256")):
                errors.append("evidence_policy.predecessor_archive.archive_sha256 is invalid")
            if predecessor.get("validation_status") not in {"validated", "legacy_unvalidated"}:
                errors.append("evidence_policy.predecessor_archive.validation_status is invalid")
            if predecessor.get("signature_status") not in {
                "digest_only", "pending_external_signature", "verified_external_signature",
                "untrusted",
            }:
                errors.append("evidence_policy.predecessor_archive.signature_status is invalid")
    errors.extend(unknown_fields(
        project, {"name", "root", "development_mode", "target_maturity"}, "project",
    ))
    errors.extend(unknown_fields(
        profile,
        {
            "product_types", "distribution_model", "target_markets", "criticality",
            "data_sensitivity", "deployment_models", "support_model", "primary_users",
            "public_contracts", "build_topology", "persistent_state",
            "external_contributions", "skill_deployment", "ai_system", "legal_profiles",
            "quality_dimensions",
        },
        "profile",
    ))
    errors.extend(unknown_fields(
        scope,
        {
            "mode", "included_paths", "excluded_paths", "unassessed_dependencies",
            "overall_project_claim_allowed",
        },
        "scope",
    ))
    required_strings = {
        "project.name": project.get("name"),
        "project.root": project.get("root"),
        "project.development_mode": project.get("development_mode"),
        "project.target_maturity": project.get("target_maturity"),
        "profile.distribution_model": profile.get("distribution_model"),
        "profile.criticality": profile.get("criticality"),
        "profile.data_sensitivity": profile.get("data_sensitivity"),
        "profile.support_model": profile.get("support_model"),
        "profile.build_topology": profile.get("build_topology"),
        "profile.persistent_state": profile.get("persistent_state"),
        "profile.external_contributions": profile.get("external_contributions"),
        "profile.skill_deployment": profile.get("skill_deployment"),
    }
    for name, value in required_strings.items():
        if not isinstance(value, str) or not value or value == "REQUIRED":
            errors.append(f"{name} must be explicitly selected")
    if project.get("target_maturity") not in MATURITY_LEVELS:
        errors.append("project.target_maturity is invalid")
    if project.get("development_mode") not in {
        "ai_greenfield", "ai_brownfield", "human_greenfield", "human_brownfield",
    }:
        errors.append("project.development_mode is invalid")
    enum_fields = {
        "distribution_model": {"open_source", "open_core", "private_commercial", "saas", "client_software", "embedded", "mixed"},
        "criticality": {"low", "medium", "high", "critical"},
        "data_sensitivity": {"public", "internal", "confidential", "restricted", "regulated"},
        "support_model": {"community", "best_effort", "contracted", "managed", "none"},
        "build_topology": {"single_form", "multi_form", "cross_target"},
        "persistent_state": {"none", "database", "indexed_store", "on_disk_format", "client_state", "mixed"},
        "external_contributions": {"accepted", "restricted", "closed"},
        "skill_deployment": {"environment_managed", "project_symlink", "vendored"},
    }
    for name, allowed in enum_fields.items():
        if profile.get(name) not in allowed:
            errors.append(f"profile.{name} is invalid")
    for name in (
        "product_types", "target_markets", "deployment_models", "primary_users",
        "legal_profiles", "quality_dimensions", "public_contracts",
    ):
        value = profile.get(name)
        if not isinstance(value, list) or not value or "REQUIRED" in value:
            errors.append(f"profile.{name} must be a non-empty explicit list")
    public_contracts = profile.get("public_contracts")
    allowed_public_contracts = {
        "none", "library_api", "service_api", "wire_protocol", "extension_api",
        "plugin_api", "file_format",
    }
    if isinstance(public_contracts, list):
        if any(not isinstance(item, str) for item in public_contracts):
            errors.append("profile.public_contracts must contain only strings")
        else:
            if len(set(public_contracts)) != len(public_contracts):
                errors.append("profile.public_contracts must not contain duplicates")
            if not set(public_contracts) <= allowed_public_contracts:
                errors.append("profile.public_contracts contains an invalid value")
            if "none" in public_contracts and len(public_contracts) != 1:
                errors.append("profile.public_contracts cannot combine none with another contract type")
    if not isinstance(profile.get("ai_system"), bool):
        errors.append("profile.ai_system must be boolean")
    if scope.get("mode") not in {"full_repo", "subproject"}:
        errors.append("scope.mode must be full_repo or subproject")
    if scope.get("mode") == "subproject" and scope.get("overall_project_claim_allowed") is not False:
        errors.append("subproject scope must set overall_project_claim_allowed=false")
    for name in ("included_paths", "excluded_paths", "unassessed_dependencies"):
        if not isinstance(scope.get(name), list) or any(
            not isinstance(item, str) for item in scope.get(name, [])
        ):
            errors.append(f"scope.{name} must be a string array")
    if authority.get("local_unprivileged_controls") is not True:
        errors.append("authority.local_unprivileged_controls must be true for automatic local evaluation")
    authorization_classes = authority.get("separate_authorization_required")
    allowed_authorizations = {
        "dependency_install", "paid_service", "secrets", "remote_mutation",
        "production_mutation", "privileged_execution",
    }
    if not non_empty_strings(authorization_classes) or not set(authorization_classes) <= allowed_authorizations:
        errors.append("authority.separate_authorization_required is invalid")
    errors.extend(unknown_fields(
        authority,
        {"local_unprivileged_controls", "separate_authorization_required"},
        "authority",
    ))
    errors.extend(unknown_fields(
        audit, {"required_stages", "independent_authorities", "authorities"}, "audit_policy",
    ))
    stages = audit.get("required_stages")
    if not isinstance(stages, list) or not stages or any(s not in AUDIT_STAGES for s in stages):
        errors.append("audit_policy.required_stages contains invalid or missing stages")
    if audit.get("independent_authorities") is not True:
        errors.append("audit_policy.independent_authorities must be true")
    authorities = audit.get("authorities")
    authority_ids: set[str] = set()
    covered_stages: set[str] = set()
    if not isinstance(authorities, list) or not authorities:
        errors.append("audit_policy.authorities must be a non-empty array")
    else:
        for index, authority_record in enumerate(authorities):
            path = f"audit_policy.authorities[{index}]"
            if not isinstance(authority_record, dict):
                errors.append(f"{path} must be an object")
                continue
            errors.extend(unknown_fields(
                authority_record,
                {"id", "kind", "identity_ref", "owner", "allowed_stages"},
                path,
            ))
            authority_id = authority_record.get("id")
            if not isinstance(authority_id, str) or not authority_id:
                errors.append(f"{path}.id is required")
            elif authority_id in authority_ids:
                errors.append(f"duplicate audit authority id: {authority_id}")
            else:
                authority_ids.add(authority_id)
            if authority_record.get("kind") not in {"virtual_role", "human", "ci", "external"}:
                errors.append(f"{path}.kind is invalid")
            for field in ("identity_ref", "owner"):
                if not isinstance(authority_record.get(field), str) or not authority_record[field].strip():
                    errors.append(f"{path}.{field} is required")
            allowed = authority_record.get("allowed_stages")
            if not non_empty_strings(allowed) or not set(allowed) <= AUDIT_STAGES:
                errors.append(f"{path}.allowed_stages is invalid")
            else:
                covered_stages.update(allowed)
    errors.extend(unknown_fields(
        development_policy, {"active_campaign"}, "development_policy",
    ))
    campaign = development_policy.get("active_campaign")
    if campaign is not None:
        errors.extend(validate_campaign(campaign, control_ids))
    elif project.get("development_mode") == "ai_brownfield":
        # Initialization may create an inactive framework, but no task/phase outcome
        # is reachable until a complete campaign is registered.
        pass
    for claim_kind in ("task", "phase", "project", "release"):
        policy = claim_policies.get(claim_kind)
        if not isinstance(policy, dict):
            errors.append(f"claim_policies.{claim_kind} must be an object")
            continue
        errors.extend(unknown_fields(
            policy, {"required_stages"}, f"claim_policies.{claim_kind}",
        ))
        claim_stages = policy.get("required_stages")
        if not isinstance(claim_stages, list) or not claim_stages or any(
            stage not in AUDIT_STAGES for stage in claim_stages
        ):
            errors.append(f"claim_policies.{claim_kind}.required_stages is invalid")
        elif not set(claim_stages) <= covered_stages:
            errors.append(f"claim_policies.{claim_kind} requires an unassigned audit stage")
    return errors


def validate_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend(unknown_fields(
        registry,
        {
            "schema_version", "controls", "capabilities", "baselines",
            "cleanup_debts", "design_scope_exemptions",
            "federated_rule_mappings",
        },
        "registry",
    ))
    if registry.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"control registry schema_version must be {SCHEMA_VERSION}; seal the old plane and regenerate")
    for collection in (
        "capabilities", "baselines", "cleanup_debts",
        "design_scope_exemptions", "federated_rule_mappings",
    ):
        if not isinstance(registry.get(collection), list):
            errors.append(f"control registry {collection} must be an array")
    controls = registry.get("controls")
    if not isinstance(controls, list) or not controls:
        return errors + ["control registry must contain at least one control"]
    capability_ids: set[str] = set()
    for index, capability in enumerate(registry.get("capabilities", [])):
        prefix = f"capabilities[{index}]"
        if not isinstance(capability, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(unknown_fields(
            capability, {"id", "owner", "authorization_required", "preflight"}, prefix,
        ))
        capability_id = capability.get("id")
        if not isinstance(capability_id, str) or not capability_id:
            errors.append(f"{prefix}.id is required")
        elif capability_id in capability_ids:
            errors.append(f"duplicate capability id: {capability_id}")
        else:
            capability_ids.add(capability_id)
        if not isinstance(capability.get("owner"), str) or not capability.get("owner"):
            errors.append(f"{prefix}.owner is required")
        preflight = capability.get("preflight")
        if not isinstance(preflight, dict):
            errors.append(f"{prefix}.preflight must be an object")
        else:
            errors.extend(unknown_fields(
                preflight, {"command", "cwd", "timeout_seconds"}, f"{prefix}.preflight",
            ))
            command = preflight.get("command")
            if not isinstance(command, list) or not command or not all(
                isinstance(part, str) and part for part in command
            ):
                errors.append(f"{prefix}.preflight.command must be a non-empty argv list")
            if not safe_relative_path(preflight.get("cwd", ".")):
                errors.append(f"{prefix}.preflight.cwd must be project-relative")
        if not isinstance(capability.get("authorization_required"), bool):
            errors.append(f"{prefix}.authorization_required must be boolean")
        if capability_id in {
            "root", "cap_bpf", "secret", "external_service", "remote_ci", "device", "gpu",
        } and capability.get("authorization_required") is not True:
            errors.append(f"{prefix} privileged/external capability must require authorization")

    seen: set[str] = set()
    for index, control in enumerate(controls):
        prefix = f"controls[{index}]"
        if not isinstance(control, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(unknown_fields(
            control,
            {
                "id", "control_revision", "rule_refs", "title", "dimension",
                "source_standard", "source_version", "project_requirement",
                "requirement_ids", "risk", "risk_ids", "verification_ids", "owner",
                "applies", "applicability_rationale", "applicability_confirmed_by",
                "applicability_exemption_ref", "required_from_maturity", "scope",
                "evaluation_mode", "ratchet_policy", "required_capability_refs",
                "execution", "evidence_required", "manual_evidence",
            },
            prefix,
        ))
        control_id = control.get("id")
        if not isinstance(control_id, str) or not control_id:
            errors.append(f"{prefix}.id is required")
        elif control_id in seen:
            errors.append(f"duplicate control id: {control_id}")
        else:
            seen.add(control_id)
        for field in ("title", "dimension", "project_requirement", "risk", "owner"):
            if not isinstance(control.get(field), str) or not control.get(field):
                errors.append(f"{prefix}.{field} is required")
        for field in ("requirement_ids", "risk_ids", "verification_ids"):
            values = control.get(field)
            if not isinstance(values, list) or not values or not all(
                isinstance(value, str) and value for value in values
            ):
                errors.append(f"{prefix}.{field} must be a non-empty string list")
        if not isinstance(control.get("control_revision"), str) or not control.get("control_revision"):
            errors.append(f"{prefix}.control_revision is required")
        if not isinstance(control.get("rule_refs"), list) or any(
            not isinstance(ref, str) or not ref for ref in control.get("rule_refs", [])
        ):
            errors.append(f"{prefix}.rule_refs must be a string array")
        if not non_empty_strings(control.get("scope")) or any(
            not safe_relative_path(path) for path in control.get("scope", [])
        ):
            errors.append(f"{prefix}.scope must contain project-relative paths")
        if control.get("evaluation_mode") not in {"absolute", "ratchet_delta"}:
            errors.append(f"{prefix}.evaluation_mode is invalid")
        ratchet_policy = control.get("ratchet_policy")
        if control.get("evaluation_mode") == "ratchet_delta":
            if not isinstance(ratchet_policy, dict):
                errors.append(f"{prefix}.ratchet_policy is required for ratchet_delta")
            else:
                errors.extend(unknown_fields(
                    ratchet_policy, {"baseline_ref", "observation_path"},
                    f"{prefix}.ratchet_policy",
                ))
                if not isinstance(ratchet_policy.get("baseline_ref"), str) or not ratchet_policy["baseline_ref"]:
                    errors.append(f"{prefix}.ratchet_policy.baseline_ref is required")
                if not safe_relative_path(ratchet_policy.get("observation_path")):
                    errors.append(f"{prefix}.ratchet_policy.observation_path must be project-relative")
        elif ratchet_policy is not None:
            errors.append(f"{prefix}.ratchet_policy is only valid for ratchet_delta")
        if not isinstance(control.get("required_capability_refs"), list):
            errors.append(f"{prefix}.required_capability_refs must be an array")
        else:
            unknown_capabilities = sorted(
                str(ref) for ref in control["required_capability_refs"]
                if not isinstance(ref, str) or ref not in capability_ids
            )
            if unknown_capabilities:
                errors.append(
                    f"{prefix}.required_capability_refs contains unknown capabilities: "
                    f"{', '.join(str(item) for item in unknown_capabilities)}"
                )
        if not isinstance(control.get("applies"), bool):
            errors.append(f"{prefix}.applies must be boolean")
        elif control.get("applies") is False:
            rationale = control.get("applicability_rationale")
            confirmer = control.get("applicability_confirmed_by")
            if not isinstance(rationale, str) or not rationale.strip():
                errors.append(f"{prefix}.applicability_rationale is required when applies=false")
            if not isinstance(confirmer, str) or not confirmer.strip():
                errors.append(f"{prefix}.applicability_confirmed_by is required when applies=false")
            if not isinstance(control.get("applicability_exemption_ref"), str) or not control["applicability_exemption_ref"]:
                errors.append(f"{prefix}.applicability_exemption_ref is required when applies=false")
        if control.get("required_from_maturity") not in MATURITY_LEVELS:
            errors.append(f"{prefix}.required_from_maturity is invalid")
        execution = control.get("execution")
        if not isinstance(execution, dict):
            errors.append(f"{prefix}.execution must be an object")
            continue
        errors.extend(unknown_fields(
            execution,
            {
                "type", "command", "path", "cwd", "timeout_seconds",
                "artifact_paths", "authorization_required",
            },
            f"{prefix}.execution",
        ))
        if execution.get("type") not in {"command", "file_exists", "file_absent", "manual", "remote", "privileged"}:
            errors.append(f"{prefix}.execution.type is invalid")
        if execution.get("type") == "command" and not isinstance(execution.get("command"), list):
            errors.append(f"{prefix}.execution.command must be an argv list")
        command = execution.get("command")
        if command is not None and (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            errors.append(f"{prefix}.execution.command must be a non-empty argv list")
        if isinstance(command, list) and tuple(command[:2]) in DEPENDENCY_MUTATION_PREFIXES:
            if execution.get("authorization_required") is not True:
                errors.append(f"{prefix} dependency mutation must require authorization")
        if execution.get("type") in {"remote", "privileged"} and execution.get("authorization_required") is not True:
            errors.append(f"{prefix} remote/privileged execution must require authorization")
        if not safe_relative_path(execution.get("cwd", ".")):
            errors.append(f"{prefix}.execution.cwd must be project-relative")
        if "path" in execution and not safe_relative_path(execution.get("path")):
            errors.append(f"{prefix}.execution.path must be project-relative")
        artifact_paths = execution.get("artifact_paths", [])
        if not isinstance(artifact_paths, list) or any(
            not safe_relative_path(path) for path in artifact_paths
        ):
            errors.append(f"{prefix}.execution.artifact_paths must be project-relative paths")
        timeout = execution.get("timeout_seconds")
        if timeout is not None and (
            not isinstance(timeout, int) or not 1 <= timeout <= 86400
        ):
            errors.append(f"{prefix}.execution.timeout_seconds is invalid")
        if not isinstance(control.get("evidence_required"), list) or not control.get("evidence_required"):
            errors.append(f"{prefix}.evidence_required must be non-empty")
        manual = control.get("manual_evidence")
        if manual is not None:
            manual_path = f"{prefix}.manual_evidence"
            if not isinstance(manual, dict):
                errors.append(f"{manual_path} must be an object")
            else:
                errors.extend(unknown_fields(
                    manual,
                    {
                        "status", "actor", "authority_id", "evidence_ref",
                        "evidence_sha256", "reviewed_at", "expires_at", "commit",
                    },
                    manual_path,
                ))
                if manual.get("status") != "PASS":
                    errors.append(f"{manual_path}.status must be PASS")
                for field in ("actor", "authority_id", "commit"):
                    if not isinstance(manual.get(field), str) or not manual[field].strip():
                        errors.append(f"{manual_path}.{field} is required")
                if not safe_relative_path(manual.get("evidence_ref")):
                    errors.append(f"{manual_path}.evidence_ref must be project-relative")
                if not valid_sha256(manual.get("evidence_sha256")):
                    errors.append(f"{manual_path}.evidence_sha256 must be a SHA-256 digest")
                for field in ("reviewed_at", "expires_at"):
                    if not valid_timestamp(manual.get(field)):
                        errors.append(f"{manual_path}.{field} must be a timezone-aware timestamp")

    baseline_ids: set[str] = set()
    for index, baseline in enumerate(registry.get("baselines", [])):
        prefix = f"baselines[{index}]"
        if not isinstance(baseline, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(unknown_fields(
            baseline,
            {"id", "control_id", "revision", "source_ref", "source_sha256", "violation_count"},
            prefix,
        ))
        baseline_id = baseline.get("id")
        if not isinstance(baseline_id, str) or not baseline_id:
            errors.append(f"{prefix}.id is required")
        elif baseline_id in baseline_ids:
            errors.append(f"duplicate baseline id: {baseline_id}")
        else:
            baseline_ids.add(baseline_id)
        if baseline.get("control_id") not in seen:
            errors.append(f"{prefix}.control_id references an unknown control")
        if not isinstance(baseline.get("revision"), int) or baseline["revision"] < 1:
            errors.append(f"{prefix}.revision must be an integer >= 1")
        if not safe_relative_path(baseline.get("source_ref")):
            errors.append(f"{prefix}.source_ref must be project-relative")
        if not valid_sha256(baseline.get("source_sha256")):
            errors.append(f"{prefix}.source_sha256 must be a SHA-256 digest")
        if not isinstance(baseline.get("violation_count"), int) or baseline["violation_count"] < 0:
            errors.append(f"{prefix}.violation_count must be a non-negative integer")

    debt_ids: set[str] = set()
    for index, debt in enumerate(registry.get("cleanup_debts", [])):
        prefix = f"cleanup_debts[{index}]"
        if not isinstance(debt, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(unknown_fields(
            debt,
            {"id", "control_id", "baseline_ref", "scope", "owner", "status", "delete_by", "rationale"},
            prefix,
        ))
        debt_id = debt.get("id")
        if not isinstance(debt_id, str) or not debt_id:
            errors.append(f"{prefix}.id is required")
        elif debt_id in debt_ids:
            errors.append(f"duplicate cleanup debt id: {debt_id}")
        else:
            debt_ids.add(debt_id)
        if debt.get("control_id") not in seen:
            errors.append(f"{prefix}.control_id references an unknown control")
        if debt.get("baseline_ref") not in baseline_ids:
            errors.append(f"{prefix}.baseline_ref references an unknown baseline")
        if not non_empty_strings(debt.get("scope")):
            errors.append(f"{prefix}.scope must be a non-empty string list")
        if not isinstance(debt.get("owner"), str) or not debt["owner"].strip():
            errors.append(f"{prefix}.owner is required")
        if debt.get("status") not in DEBT_STATUSES:
            errors.append(f"{prefix}.status is invalid")
        if not valid_timestamp(debt.get("delete_by")):
            errors.append(f"{prefix}.delete_by must be a timezone-aware timestamp")
        if not isinstance(debt.get("rationale"), str) or not debt["rationale"].strip():
            errors.append(f"{prefix}.rationale is required")

    exemption_ids: set[str] = set()
    for index, exemption in enumerate(registry.get("design_scope_exemptions", [])):
        prefix = f"design_scope_exemptions[{index}]"
        if not isinstance(exemption, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(unknown_fields(
            exemption,
            {
                "id", "control_id", "scope", "owner", "rationale",
                "alternative_control_refs", "status", "reviewed_at", "review_by",
            },
            prefix,
        ))
        exemption_id = exemption.get("id")
        if not isinstance(exemption_id, str) or not exemption_id:
            errors.append(f"{prefix}.id is required")
        elif exemption_id in exemption_ids:
            errors.append(f"duplicate design exemption id: {exemption_id}")
        else:
            exemption_ids.add(exemption_id)
        if exemption.get("control_id") not in seen:
            errors.append(f"{prefix}.control_id references an unknown control")
        if not non_empty_strings(exemption.get("scope")):
            errors.append(f"{prefix}.scope must be a non-empty string list")
        for field in ("owner", "rationale"):
            if not isinstance(exemption.get(field), str) or not exemption[field].strip():
                errors.append(f"{prefix}.{field} is required")
        alternatives = exemption.get("alternative_control_refs")
        if not non_empty_strings(alternatives):
            errors.append(f"{prefix}.alternative_control_refs must be a non-empty string list")
        elif not set(alternatives) <= seen:
            errors.append(f"{prefix}.alternative_control_refs contains unknown controls")
        if exemption.get("status") not in EXEMPTION_STATUSES:
            errors.append(f"{prefix}.status is invalid")
        for field in ("reviewed_at", "review_by"):
            if not valid_timestamp(exemption.get(field)):
                errors.append(f"{prefix}.{field} must be a timezone-aware timestamp")

    rule_ids: set[str] = set()
    for index, mapping in enumerate(registry.get("federated_rule_mappings", [])):
        prefix = f"federated_rule_mappings[{index}]"
        if not isinstance(mapping, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(unknown_fields(
            mapping,
            {
                "rule_id", "source_ref", "source_sha256", "semantic_owner",
                "source_selector", "disposition", "control_refs", "mandatory",
                "status", "observed_at", "reviewed_at",
            },
            prefix,
        ))
        rule_id = mapping.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            errors.append(f"{prefix}.rule_id is required")
        elif rule_id in rule_ids:
            errors.append(f"duplicate federated rule id: {rule_id}")
        else:
            rule_ids.add(rule_id)
        if not safe_relative_path(mapping.get("source_ref")):
            errors.append(f"{prefix}.source_ref must be project-relative")
        if not valid_sha256(mapping.get("source_sha256")):
            errors.append(f"{prefix}.source_sha256 must be a SHA-256 digest")
        selector = mapping.get("source_selector")
        if not isinstance(selector, dict):
            errors.append(f"{prefix}.source_selector must be an object")
        else:
            errors.extend(unknown_fields(selector, {"kind", "value", "occurrence"}, f"{prefix}.source_selector"))
            if selector.get("kind") not in {"whole_file", "markdown_heading"}:
                errors.append(f"{prefix}.source_selector.kind is invalid")
            if selector.get("kind") == "whole_file":
                if selector.get("value") is not None or selector.get("occurrence") is not None:
                    errors.append(f"{prefix}.source_selector whole_file values must be null")
            elif (
                not isinstance(selector.get("value"), str)
                or not selector["value"].startswith("#")
                or not isinstance(selector.get("occurrence"), int)
                or selector["occurrence"] < 1
            ):
                errors.append(f"{prefix}.source_selector markdown heading is invalid")
        if mapping.get("disposition") not in FEDERATION_DISPOSITIONS:
            errors.append(f"{prefix}.disposition is invalid")
        if not isinstance(mapping.get("semantic_owner"), str) or not mapping["semantic_owner"].strip():
            errors.append(f"{prefix}.semantic_owner is required")
        refs = mapping.get("control_refs")
        if mapping.get("status") == "unmapped":
            if refs not in ([], None):
                errors.append(f"{prefix}.control_refs must be empty when status=unmapped")
        elif not non_empty_strings(refs) or not set(refs) <= seen:
            errors.append(f"{prefix}.control_refs must reference known controls")
        if not isinstance(mapping.get("mandatory"), bool):
            errors.append(f"{prefix}.mandatory must be boolean")
        if mapping.get("status") not in FEDERATION_STATUSES:
            errors.append(f"{prefix}.status is invalid")
        if not valid_timestamp(mapping.get("observed_at")):
            errors.append(f"{prefix}.observed_at must be a timezone-aware timestamp")
        reviewed_at = mapping.get("reviewed_at")
        if mapping.get("status") == "unmapped":
            if reviewed_at is not None:
                errors.append(f"{prefix}.reviewed_at must be null when status=unmapped")
        elif not valid_timestamp(reviewed_at):
            errors.append(f"{prefix}.reviewed_at must be a timezone-aware timestamp")

    for index, control in enumerate(controls):
        if (
            control.get("applies") is False
            and control.get("applicability_exemption_ref") not in exemption_ids
        ):
            errors.append(f"controls[{index}].applicability_exemption_ref references an unknown exemption")
        if control.get("evaluation_mode") != "ratchet_delta":
            continue
        baseline_ref = control.get("ratchet_policy", {}).get("baseline_ref")
        if baseline_ref not in baseline_ids:
            errors.append(f"controls[{index}].ratchet_policy.baseline_ref references an unknown baseline")
    return errors


def validate_traceability(graph: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if graph.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"traceability graph schema_version must be {SCHEMA_VERSION}")
    if graph.get("generated_from_registry_sha256") != canonical_digest(registry):
        errors.append("traceability graph is stale; regenerate it from the control registry")
    links = graph.get("links")
    if not isinstance(links, list):
        return errors + ["traceability graph links must be an array"]
    linked = {link.get("control_id") for link in links if isinstance(link, dict)}
    expected = {control.get("id") for control in registry.get("controls", [])}
    missing = sorted(item for item in expected - linked if item)
    if missing:
        errors.append(f"traceability graph is missing controls: {', '.join(missing)}")
    for index, link in enumerate(links):
        if not isinstance(link, dict):
            errors.append(f"traceability links[{index}] must be an object")
            continue
        for field in ("requirement_ids", "risk_ids", "verification_ids", "evidence_required"):
            values = link.get(field)
            if not isinstance(values, list) or not values:
                errors.append(f"traceability links[{index}].{field} must be non-empty")
    return errors


def _validate_hash_chain(entries: Any, collection: str) -> list[str]:
    if not isinstance(entries, list):
        return [f"evidence ledger {collection} must be an array"]
    errors: list[str] = []
    previous = "GENESIS"
    seen: set[str] = set()
    identity_field = {
        "runs": "run_id", "audits": "audit_id", "claims": "claim_id",
    }[collection]
    for index, entry in enumerate(entries):
        prefix = f"{collection}[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        identity = entry.get(identity_field)
        if not isinstance(identity, str) or not identity:
            errors.append(f"{prefix}.{identity_field} is required")
        elif identity in seen:
            errors.append(f"duplicate {identity_field}: {identity}")
        else:
            seen.add(identity)
        if entry.get("previous_entry_sha256") != previous:
            errors.append(f"{prefix} breaks the evidence hash chain")
        claimed = entry.get("entry_sha256")
        payload = dict(entry)
        payload.pop("entry_sha256", None)
        if claimed != canonical_digest(payload):
            errors.append(f"{prefix}.entry_sha256 does not match its content")
        previous = claimed if isinstance(claimed, str) else "INVALID"
    return errors


def validate_ledger(ledger: dict[str, Any], root: Path | None = None) -> list[str]:
    errors: list[str] = []
    errors.extend(unknown_fields(
        ledger, {"schema_version", "runs", "audits", "claims"}, "ledger",
    ))
    if ledger.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"evidence ledger schema_version must be {SCHEMA_VERSION}; seal the old plane and regenerate")
    runs = ledger.get("runs")
    errors.extend(_validate_hash_chain(runs, "runs"))
    errors.extend(_validate_hash_chain(ledger.get("audits"), "audits"))
    errors.extend(_validate_hash_chain(ledger.get("claims"), "claims"))
    if not isinstance(runs, list):
        return errors
    for index, run in enumerate(runs):
        prefix = f"runs[{index}]"
        if not isinstance(run, dict):
            continue
        if run.get("conclusion") not in {"PASS", "FAIL", "BLOCKED", "DISPUTED"}:
            errors.append(f"{prefix}.conclusion is invalid")
        errors.extend(validate_subject_binding(run.get("subject_binding"), f"{prefix}.subject_binding"))
        storage = run.get("storage_binding")
        if not isinstance(storage, dict) or set(storage) != {"evidence_sha256"}:
            errors.append(f"{prefix}.storage_binding is invalid")
        elif storage["evidence_sha256"] != canonical_digest({"results": run.get("results", [])}):
            errors.append(f"{prefix}.storage_binding.evidence_sha256 does not match results")
        for field in ("actor", "authority_id", "execution_context"):
            if not isinstance(run.get(field), str) or not run[field].strip():
                errors.append(f"{prefix}.{field} is required")
        if run.get("audit_stage") not in AUDIT_STAGES:
            errors.append(f"{prefix}.audit_stage is invalid")
        reviewed = run.get("reviewed_run_ids")
        if not isinstance(reviewed, list) or any(not isinstance(item, str) or not item for item in reviewed):
            errors.append(f"{prefix}.reviewed_run_ids must be a string array")
        if run.get("audit_stage") != "self" and not reviewed:
            errors.append(f"{prefix}.reviewed_run_ids is required for independent audit")
        for result_index, result in enumerate(run.get("results", [])):
            if not isinstance(result, dict):
                errors.append(f"{prefix}.results[{result_index}] must be an object")
                continue
            output_ref = result.get("output_ref")
            output_digest = result.get("output_sha256")
            if output_ref is None and output_digest is None:
                continue
            if not safe_relative_path(output_ref) or not valid_sha256(output_digest):
                errors.append(f"{prefix}.results[{result_index}] has invalid output evidence binding")
                continue
            if root is not None:
                output_path = path_inside_root(root, output_ref)
                if output_path is None or not output_path.is_file():
                    errors.append(f"{prefix}.results[{result_index}] output evidence is missing")
                else:
                    digest = file_sha256(output_path)
                    if digest != output_digest:
                        errors.append(f"{prefix}.results[{result_index}] output evidence digest mismatch")
            debt_observation = result.get("debt_observation")
            if isinstance(debt_observation, dict):
                observation_ref = debt_observation.get("observation_ref")
                observation_digest = debt_observation.get("observation_sha256")
                if not safe_relative_path(observation_ref) or not valid_sha256(observation_digest):
                    errors.append(f"{prefix}.results[{result_index}] has invalid debt observation binding")
                elif root is not None:
                    observation_path = path_inside_root(root, observation_ref)
                    if observation_path is None or not observation_path.is_file():
                        errors.append(f"{prefix}.results[{result_index}] debt observation is missing")
                    elif file_sha256(observation_path) != observation_digest:
                        errors.append(f"{prefix}.results[{result_index}] debt observation digest mismatch")
            artifacts = result.get("artifacts", [])
            if not isinstance(artifacts, list):
                errors.append(f"{prefix}.results[{result_index}].artifacts must be an array")
            else:
                for artifact_index, artifact in enumerate(artifacts):
                    artifact_prefix = f"{prefix}.results[{result_index}].artifacts[{artifact_index}]"
                    if (
                        not isinstance(artifact, dict)
                        or not safe_relative_path(artifact.get("path"))
                        or not safe_relative_path(artifact.get("evidence_ref"))
                        or not valid_sha256(artifact.get("sha256"))
                        or not isinstance(artifact.get("bytes"), int)
                    ):
                        errors.append(f"{artifact_prefix} has an invalid evidence binding")
                    elif root is not None:
                        evidence_path = path_inside_root(root, artifact["evidence_ref"])
                        if evidence_path is None or not evidence_path.is_file():
                            errors.append(f"{artifact_prefix} immutable evidence is missing")
                        elif file_sha256(evidence_path) != artifact["sha256"]:
                            errors.append(f"{artifact_prefix} immutable evidence digest mismatch")
                        elif evidence_path.stat().st_size != artifact["bytes"]:
                            errors.append(f"{artifact_prefix} immutable evidence size mismatch")
    runs_by_id = {
        run.get("run_id"): run for run in runs
        if isinstance(run, dict) and isinstance(run.get("run_id"), str)
    }
    predecessor = {
        "cross": "self", "release_authority": "cross", "third_party": "release_authority",
    }
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or run.get("audit_stage") == "self":
            continue
        prefix = f"runs[{index}]"
        for reviewed_id in run.get("reviewed_run_ids", []):
            source = runs_by_id.get(reviewed_id)
            if source is None:
                errors.append(f"{prefix}.reviewed_run_ids references an unknown run")
                continue
            if source.get("audit_stage") != predecessor.get(run.get("audit_stage")):
                errors.append(f"{prefix} reviews the wrong predecessor stage")
            if source.get("authority_id") == run.get("authority_id"):
                errors.append(f"{prefix} reuses the reviewed authority identity")
            if source.get("execution_context") == run.get("execution_context"):
                errors.append(f"{prefix} reuses the reviewed execution context")
    for index, audit in enumerate(ledger.get("audits", [])):
        if not isinstance(audit, dict):
            continue
        prefix = f"audits[{index}]"
        if audit.get("audit_stage") not in AUDIT_STAGES - {"self"}:
            errors.append(f"{prefix}.audit_stage must be an independent stage")
        if audit.get("conclusion") not in {"PASS", "FAIL", "BLOCKED", "DISPUTED"}:
            errors.append(f"{prefix}.conclusion is invalid")
        errors.extend(validate_subject_binding(audit.get("subject_binding"), f"{prefix}.subject_binding"))
        if not non_empty_strings(audit.get("reviewed_run_ids")):
            errors.append(f"{prefix}.reviewed_run_ids must be non-empty")
        elif not set(audit["reviewed_run_ids"]) <= set(runs_by_id):
            errors.append(f"{prefix}.reviewed_run_ids references unknown runs")
        audited_run = runs_by_id.get(audit.get("run_id"))
        if audited_run is None:
            errors.append(f"{prefix}.run_id references an unknown run")
        elif any(
            audit.get(field) != audited_run.get(field)
            for field in (
                "audit_stage", "authority_id", "execution_context", "conclusion",
                "subject_binding",
            )
        ):
            errors.append(f"{prefix} does not match its audit run")
        storage = audit.get("storage_binding")
        if (
            not isinstance(storage, dict)
            or set(storage) != {"run_entry_sha256"}
            or audited_run is None
            or storage.get("run_entry_sha256") != audited_run.get("entry_sha256")
        ):
            errors.append(f"{prefix}.storage_binding does not match its audit run")
    for index, claim in enumerate(ledger.get("claims", [])):
        if not isinstance(claim, dict):
            continue
        prefix = f"claims[{index}]"
        if claim.get("claim_scope") not in CLAIM_SCOPES:
            errors.append(f"{prefix}.claim_scope is invalid")
        if claim.get("outcome") not in {"COMPLETED", "PASS"}:
            errors.append(f"{prefix}.outcome is invalid")
        errors.extend(validate_subject_binding(claim.get("subject_binding"), f"{prefix}.subject_binding"))
        if not non_empty_strings(claim.get("control_ids")):
            errors.append(f"{prefix}.control_ids must be non-empty")
        supporting = claim.get("supporting_run_ids")
        if not non_empty_strings(supporting) or not set(supporting) <= set(runs_by_id):
            errors.append(f"{prefix}.supporting_run_ids references unknown runs")
            continue
        for run_id in supporting:
            run = runs_by_id[run_id]
            if (
                claim.get("subject_binding") != run.get("subject_binding")
                or claim.get("target_maturity") != run.get("target_maturity")
            ):
                errors.append(f"{prefix} has stale supporting run {run_id}")
            if run.get("audit_stage") not in claim.get("audit_stages", []):
                errors.append(f"{prefix} includes a run from an undeclared audit stage")
        storage = claim.get("storage_binding")
        if not isinstance(storage, dict) or set(storage) != {
            "runs_chain_head_sha256", "audits_chain_head_sha256",
        }:
            errors.append(f"{prefix}.storage_binding is invalid")
        else:
            run_heads = {"GENESIS", *(run.get("entry_sha256") for run in runs if isinstance(run, dict))}
            audit_heads = {
                "GENESIS",
                *(audit.get("entry_sha256") for audit in ledger.get("audits", []) if isinstance(audit, dict)),
            }
            if storage.get("runs_chain_head_sha256") not in run_heads:
                errors.append(f"{prefix}.storage_binding references an unknown run chain head")
            if storage.get("audits_chain_head_sha256") not in audit_heads:
                errors.append(f"{prefix}.storage_binding references an unknown audit chain head")
    return errors
