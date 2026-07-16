#!/usr/bin/env python3
"""Seal the active project control plane into a read-only digest manifest archive."""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import stat
import sys
from pathlib import Path

from quality_common import (
    canonical_digest,
    exclusive_file_lock,
    file_sha256,
    load_json_yaml,
    registry_control_ids,
    validate_manifest,
    validate_ledger,
    validate_registry,
    validate_traceability,
    valid_archive_id,
    write_json_yaml,
)


ACTIVE_ENTRIES = (
    "quality-manifest.yaml", "control-registry.yaml", "evidence-ledger.json",
    "traceability-graph.json", "evidence", "INDEX.md", "profile.md", "owners.md",
    "rules", "cleanliness.md", "harness.md", "supply-chain.md", "memory.md",
    "decisions.md", "DEVELOPMENT-HANDOFF.md", "RULE-CONSOLIDATION-AUDIT.md",
    "preflight.py", "run-quality-gates.py",
)
CORE_FILES = (
    "quality-manifest.yaml", "control-registry.yaml", "evidence-ledger.json",
    "traceability-graph.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    parser.add_argument("--archive-id", required=True)
    parser.add_argument(
        "--legacy-unvalidated", action="store_true",
        help="archive a pre-current-schema plane as explicitly untrusted",
    )
    return parser.parse_args()


def make_read_only(path: Path) -> None:
    for item in [*path.rglob("*"), path]:
        if item.is_symlink():
            raise ValueError(f"archive contains a forbidden symbolic link: {item}")
        mode = item.stat().st_mode
        item.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def remove_staging(path: Path) -> None:
    for item in [path, *path.rglob("*")]:
        if not item.is_symlink():
            item.chmod(item.stat().st_mode | stat.S_IWUSR)
    shutil.rmtree(path)


def active_symlinks(guardrails: Path) -> list[Path]:
    links: list[Path] = []
    for name in ACTIVE_ENTRIES:
        source = guardrails / name
        if source.is_symlink():
            links.append(source)
            continue
        if source.is_dir():
            links.extend(item for item in source.rglob("*") if item.is_symlink())
    return links


def referenced_artifacts(
    ledger: dict, root: Path, guardrails: Path,
) -> tuple[list[str], list[dict]]:
    errors: list[str] = []
    records: dict[tuple[str, str], dict] = {}
    for run_index, run in enumerate(ledger.get("runs", [])):
        if not isinstance(run, dict):
            continue
        for result_index, result in enumerate(run.get("results", [])):
            if not isinstance(result, dict):
                continue
            for artifact_index, artifact in enumerate(result.get("artifacts", [])):
                prefix = (
                    f"runs[{run_index}].results[{result_index}]"
                    f".artifacts[{artifact_index}]"
                )
                if not isinstance(artifact, dict):
                    continue
                relative = artifact.get("path")
                evidence_ref = artifact.get("evidence_ref")
                digest = artifact.get("sha256")
                size = artifact.get("bytes")
                if (
                    not isinstance(relative, str)
                    or not isinstance(evidence_ref, str)
                    or not isinstance(digest, str)
                ):
                    continue
                source = root / evidence_ref
                try:
                    archive_path = source.resolve(strict=True).relative_to(guardrails)
                except (OSError, ValueError):
                    errors.append(f"{prefix} immutable evidence is outside guardrails or missing")
                    continue
                if source.is_symlink() or not source.is_file():
                    errors.append(f"{prefix} immutable evidence is missing or linked")
                    continue
                actual_digest = file_sha256(source)
                actual_size = source.stat().st_size
                if actual_digest != digest or actual_size != size:
                    errors.append(f"{prefix} immutable evidence is stale")
                    continue
                records[(relative, digest)] = {
                    "source_path": relative,
                    "archive_path": archive_path.as_posix(),
                    "sha256": digest,
                    "bytes": size,
                }
    return errors, sorted(records.values(), key=lambda item: item["source_path"])


def validate_active_plane(
    guardrails: Path, root: Path,
) -> tuple[list[str], dict, list[dict]]:
    errors: list[str] = []
    documents: dict[str, dict] = {}
    for name in CORE_FILES:
        try:
            documents[name] = load_json_yaml(guardrails / name)
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        return errors, documents, []

    registry = documents["control-registry.yaml"]
    registry_errors = validate_registry(registry)
    control_ids = registry_control_ids(registry)
    errors.extend(registry_errors)
    errors.extend(validate_manifest(documents["quality-manifest.yaml"], control_ids))
    if registry_errors:
        errors.append("traceability graph cannot be validated against an invalid registry")
    else:
        errors.extend(validate_traceability(documents["traceability-graph.json"], registry))
    ledger = documents["evidence-ledger.json"]
    errors.extend(validate_ledger(ledger, root))
    artifact_errors, artifact_records = (
        referenced_artifacts(ledger, root, guardrails)
        if isinstance(ledger, dict) else ([], [])
    )
    errors.extend(artifact_errors)
    return errors, documents, artifact_records


def ledger_chain_heads(ledger: dict) -> dict[str, str]:
    heads: dict[str, str] = {}
    for collection in ("runs", "audits", "claims"):
        entries = ledger.get(collection, [])
        if not entries:
            heads[collection] = "GENESIS"
        elif isinstance(entries, list) and isinstance(entries[-1], dict):
            heads[collection] = entries[-1].get("entry_sha256", "UNVALIDATED")
        else:
            heads[collection] = "UNVALIDATED"
    return heads


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    guardrails = (root / args.guardrails_dir).resolve()
    try:
        guardrails.relative_to(root)
    except ValueError:
        print("archive guardrails directory must remain inside the project", file=sys.stderr)
        return 2
    if not valid_archive_id(args.archive_id):
        print(
            "archive id must be 1-128 ASCII letters, digits, dots, underscores, or hyphens "
            "and cannot contain a path",
            file=sys.stderr,
        )
        return 2
    archive_root = guardrails / "archive"
    if archive_root.is_symlink():
        print("archive directory cannot be a symbolic link", file=sys.stderr)
        return 2
    try:
        archive_root.resolve(strict=False).relative_to(guardrails)
    except ValueError:
        print("archive directory must remain inside the guardrails directory", file=sys.stderr)
        return 2
    archive = archive_root / args.archive_id
    if archive.exists():
        print(f"archive already exists: {archive}", file=sys.stderr)
        return 2
    with exclusive_file_lock(guardrails / ".ledger.lock"):
        links = active_symlinks(guardrails)
        if links:
            for link in links:
                print(
                    f"cannot seal control plane containing symbolic link: "
                    f"{link.relative_to(guardrails)}",
                    file=sys.stderr,
                )
            return 1
        validation_errors, documents, artifact_records = validate_active_plane(
            guardrails, root,
        )
        if validation_errors and not args.legacy_unvalidated:
            for error in validation_errors:
                print(f"cannot seal invalid active control plane: {error}", file=sys.stderr)
            return 1
        archive_root.mkdir(parents=True, exist_ok=True)
        staging = archive_root / f".{args.archive_id}.staging"
        if staging.exists():
            print(f"stale archive staging directory exists: {staging}", file=sys.stderr)
            return 2
        try:
            staging.mkdir()
            for name in ACTIVE_ENTRIES:
                source = guardrails / name
                if not source.exists():
                    continue
                target = staging / name
                if source.is_dir():
                    shutil.copytree(source, target, symlinks=True)
                else:
                    shutil.copy2(source, target, follow_symlinks=False)
            files = []
            for path in sorted(item for item in staging.rglob("*") if item.is_file()):
                if path.is_symlink():
                    raise ValueError(f"archive contains a forbidden symbolic link: {path}")
                files.append({
                    "path": path.relative_to(staging).as_posix(),
                    "sha256": file_sha256(path),
                    "bytes": path.stat().st_size,
                })
            evidence_policy = documents.get("quality-manifest.yaml", {}).get(
                "evidence_policy", {},
            )
            sealing_profile = evidence_policy.get("sealing_profile", "unverified")
            manifest = {
                "archive_id": args.archive_id,
                "sealed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "validation_status": "legacy_unvalidated" if validation_errors else "validated",
                "validation_errors": validation_errors,
                "sealing_profile": sealing_profile,
                "signature_status": (
                    "untrusted" if validation_errors else (
                        "pending_external_signature"
                        if sealing_profile == "sigstore_bundle" else "digest_only"
                    )
                ),
                "referenced_artifacts": artifact_records,
                "ledger_chain_heads": ledger_chain_heads(
                    documents.get("evidence-ledger.json", {}),
                ),
                "files": files,
            }
            manifest["archive_sha256"] = canonical_digest(manifest)
            write_json_yaml(staging / "archive-manifest.json", manifest)
            make_read_only(staging)
            staging.replace(archive)
        except (OSError, ValueError) as exc:
            if staging.exists():
                remove_staging(staging)
            print(f"cannot seal active control plane: {exc}", file=sys.stderr)
            return 1
    print(f"sealed {len(files)} files at {archive}")
    if manifest["signature_status"] == "pending_external_signature":
        print("external signature remains required for release-grade trust")
    elif manifest["signature_status"] == "untrusted":
        print("legacy archive is permanently untrusted and cannot support a claim")
    else:
        print("archive uses digest-only integrity; no external signature was selected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
