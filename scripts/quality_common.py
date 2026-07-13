#!/usr/bin/env python3
"""Shared stdlib-only helpers for the project quality control plane."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
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
SCHEMA_VERSION = "2.0"

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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def canonical_digest(data: dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_text(payload)


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
        if normalized in ignored:
            continue
        path = root / relative
        digest.update(normalized.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        try:
            if path.is_symlink():
                digest.update(b"link\0")
                digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
            elif path.is_file():
                digest.update(b"file\0")
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            else:
                digest.update(b"missing\0")
        except OSError:
            return "unavailable"
        digest.update(b"\0")
    return digest.hexdigest()


def maturity_applies(required_from: str, target: str) -> bool:
    if required_from not in MATURITY_LEVELS or target not in MATURITY_LEVELS:
        return False
    return MATURITY_LEVELS.index(required_from) <= MATURITY_LEVELS.index(target)


def unknown_fields(value: dict[str, Any], allowed: set[str], path: str) -> list[str]:
    """Report unknown fields where silent schema extension could alter claims."""
    return [f"{path}.{field} is not allowed" for field in sorted(set(value) - allowed)]


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend(unknown_fields(
        manifest,
        {
            "schema_version", "project", "profile", "scope", "authority",
            "audit_policy", "development_policy", "claim_policies",
        },
        "manifest",
    ))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"quality manifest schema_version must be {SCHEMA_VERSION}; run the migration tool")
    project = manifest.get("project")
    profile = manifest.get("profile")
    scope = manifest.get("scope")
    authority = manifest.get("authority")
    audit = manifest.get("audit_policy")
    development_policy = manifest.get("development_policy")
    claim_policies = manifest.get("claim_policies")
    for name, value in (
        ("project", project), ("profile", profile), ("scope", scope),
        ("authority", authority), ("audit_policy", audit),
        ("development_policy", development_policy),
        ("claim_policies", claim_policies),
    ):
        if not isinstance(value, dict):
            errors.append(f"manifest.{name} must be an object")
    if errors:
        return errors
    required_strings = {
        "project.name": project.get("name"),
        "project.root": project.get("root"),
        "project.development_mode": project.get("development_mode"),
        "project.target_maturity": project.get("target_maturity"),
        "profile.distribution_model": profile.get("distribution_model"),
        "profile.criticality": profile.get("criticality"),
        "profile.data_sensitivity": profile.get("data_sensitivity"),
        "profile.support_model": profile.get("support_model"),
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
    for name in (
        "product_types", "target_markets", "deployment_models", "primary_users",
        "legal_profiles", "quality_dimensions",
    ):
        value = profile.get(name)
        if not isinstance(value, list) or not value or "REQUIRED" in value:
            errors.append(f"profile.{name} must be a non-empty explicit list")
    if not isinstance(profile.get("ai_system"), bool):
        errors.append("profile.ai_system must be boolean")
    if scope.get("mode") not in {"full_repo", "subproject"}:
        errors.append("scope.mode must be full_repo or subproject")
    if scope.get("mode") == "subproject" and scope.get("overall_project_claim_allowed") is not False:
        errors.append("subproject scope must set overall_project_claim_allowed=false")
    if authority.get("local_unprivileged_controls") is not True:
        errors.append("authority.local_unprivileged_controls must be true for automatic local evaluation")
    stages = audit.get("required_stages")
    if not isinstance(stages, list) or not stages or any(s not in AUDIT_STAGES for s in stages):
        errors.append("audit_policy.required_stages contains invalid or missing stages")
    if audit.get("independent_actors") is not True:
        errors.append("audit_policy.independent_actors must be true")
    if not isinstance(development_policy.get("active_campaign"), (dict, type(None))):
        errors.append("development_policy.active_campaign must be an object or null")
    for claim_kind in ("task", "phase", "project", "release"):
        policy = claim_policies.get(claim_kind)
        if not isinstance(policy, dict):
            errors.append(f"claim_policies.{claim_kind} must be an object")
            continue
        claim_stages = policy.get("required_stages")
        if not isinstance(claim_stages, list) or not claim_stages or any(
            stage not in AUDIT_STAGES for stage in claim_stages
        ):
            errors.append(f"claim_policies.{claim_kind}.required_stages is invalid")
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
        errors.append(f"control registry schema_version must be {SCHEMA_VERSION}; run the migration tool")
    for collection in (
        "capabilities", "baselines", "cleanup_debts",
        "design_scope_exemptions", "federated_rule_mappings",
    ):
        if not isinstance(registry.get(collection), list):
            errors.append(f"control registry {collection} must be an array")
    controls = registry.get("controls")
    if not isinstance(controls, list) or not controls:
        return errors + ["control registry must contain at least one control"]
    seen: set[str] = set()
    for index, control in enumerate(controls):
        prefix = f"controls[{index}]"
        if not isinstance(control, dict):
            errors.append(f"{prefix} must be an object")
            continue
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
        if not isinstance(control.get("rule_refs"), list):
            errors.append(f"{prefix}.rule_refs must be an array")
        if control.get("evaluation_mode") not in {"absolute", "ratchet_delta"}:
            errors.append(f"{prefix}.evaluation_mode is invalid")
        if not isinstance(control.get("required_capability_refs"), list):
            errors.append(f"{prefix}.required_capability_refs must be an array")
        if not isinstance(control.get("applies"), bool):
            errors.append(f"{prefix}.applies must be boolean")
        elif control.get("applies") is False:
            rationale = control.get("applicability_rationale")
            confirmer = control.get("applicability_confirmed_by")
            if not isinstance(rationale, str) or not rationale.strip():
                errors.append(f"{prefix}.applicability_rationale is required when applies=false")
            if not isinstance(confirmer, str) or not confirmer.strip():
                errors.append(f"{prefix}.applicability_confirmed_by is required when applies=false")
        if control.get("required_from_maturity") not in MATURITY_LEVELS:
            errors.append(f"{prefix}.required_from_maturity is invalid")
        execution = control.get("execution")
        if not isinstance(execution, dict):
            errors.append(f"{prefix}.execution must be an object")
            continue
        if execution.get("type") not in {"command", "file_exists", "file_absent", "manual", "remote", "privileged"}:
            errors.append(f"{prefix}.execution.type is invalid")
        if execution.get("type") == "command" and not isinstance(execution.get("command"), list):
            errors.append(f"{prefix}.execution.command must be an argv list")
        command = execution.get("command")
        if isinstance(command, list) and tuple(command[:2]) in DEPENDENCY_MUTATION_PREFIXES:
            if execution.get("authorization_required") is not True:
                errors.append(f"{prefix} dependency mutation must require authorization")
        if execution.get("type") in {"remote", "privileged"} and execution.get("authorization_required") is not True:
            errors.append(f"{prefix} remote/privileged execution must require authorization")
        if not isinstance(control.get("evidence_required"), list) or not control.get("evidence_required"):
            errors.append(f"{prefix}.evidence_required must be non-empty")
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


def validate_ledger(ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend(unknown_fields(
        ledger, {"schema_version", "runs", "audits", "claims"}, "ledger",
    ))
    if ledger.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"evidence ledger schema_version must be {SCHEMA_VERSION}; run the migration tool")
    runs = ledger.get("runs")
    if not isinstance(runs, list):
        return errors + ["evidence ledger runs must be an array"]
    if not isinstance(ledger.get("audits"), list):
        errors.append("evidence ledger audits must be an array")
    if not isinstance(ledger.get("claims"), list):
        errors.append("evidence ledger claims must be an array")
    previous = "GENESIS"
    seen: set[str] = set()
    for index, run in enumerate(runs):
        prefix = f"runs[{index}]"
        if not isinstance(run, dict):
            errors.append(f"{prefix} must be an object")
            continue
        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            errors.append(f"{prefix}.run_id is required")
        elif run_id in seen:
            errors.append(f"duplicate run_id: {run_id}")
        else:
            seen.add(run_id)
        if run.get("previous_entry_sha256") != previous:
            errors.append(f"{prefix} breaks the evidence hash chain")
        claimed = run.get("entry_sha256")
        payload = dict(run)
        payload.pop("entry_sha256", None)
        actual = canonical_digest(payload)
        if claimed != actual:
            errors.append(f"{prefix}.entry_sha256 does not match its content")
        previous = claimed if isinstance(claimed, str) else "INVALID"
        if run.get("conclusion") not in {"PASS", "FAIL", "BLOCKED", "DISPUTED"}:
            errors.append(f"{prefix}.conclusion is invalid")
        if not isinstance(run.get("workspace_sha256"), str) or len(run["workspace_sha256"]) != 64:
            errors.append(f"{prefix}.workspace_sha256 is invalid")
    return errors
