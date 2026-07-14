#!/usr/bin/env python3
"""Seal the active project control plane into a read-only digest manifest archive."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import stat
import sys
from pathlib import Path

from quality_common import (
    canonical_digest,
    exclusive_file_lock,
    file_sha256,
    load_json_yaml,
    validate_ledger,
    write_json_yaml,
)


ACTIVE_ENTRIES = (
    "quality-manifest.yaml", "control-registry.yaml", "evidence-ledger.json",
    "traceability-graph.json", "evidence", "INDEX.md", "profile.md", "owners.md",
    "rules", "cleanliness.md", "harness.md", "supply-chain.md", "memory.md",
    "decisions.md", "DEVELOPMENT-HANDOFF.md", "RULE-CONSOLIDATION-AUDIT.md",
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
        mode = item.stat().st_mode
        item.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    guardrails = (root / args.guardrails_dir).resolve()
    try:
        guardrails.relative_to(root)
    except ValueError:
        print("archive guardrails directory must remain inside the project", file=sys.stderr)
        return 2
    archive = guardrails / "archive" / args.archive_id
    if archive.exists():
        print(f"archive already exists: {archive}", file=sys.stderr)
        return 2
    with exclusive_file_lock(guardrails / ".ledger.lock"):
        validation_errors: list[str] = []
        try:
            ledger = load_json_yaml(guardrails / "evidence-ledger.json")
            validation_errors = validate_ledger(ledger, root)
        except ValueError as exc:
            validation_errors = [str(exc)]
        if validation_errors and not args.legacy_unvalidated:
            for error in validation_errors:
                print(f"cannot seal invalid active ledger: {error}", file=sys.stderr)
            return 1
        archive.mkdir(parents=True)
        for name in ACTIVE_ENTRIES:
            source = guardrails / name
            if not source.exists():
                continue
            target = archive / name
            if source.is_dir():
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target, follow_symlinks=False)
        files = []
        for path in sorted(item for item in archive.rglob("*") if item.is_file()):
            files.append({
                "path": path.relative_to(archive).as_posix(),
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            })
        manifest = {
            "archive_id": args.archive_id,
            "sealed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "validation_status": "legacy_unvalidated" if validation_errors else "validated",
            "validation_errors": validation_errors,
            "signature_status": "pending_external_signature",
            "files": files,
        }
        manifest["archive_sha256"] = canonical_digest(manifest)
        write_json_yaml(archive / "archive-manifest.json", manifest)
        make_read_only(archive)
    print(f"sealed {len(files)} files at {archive}")
    print("external signature remains required for release-grade trust")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
