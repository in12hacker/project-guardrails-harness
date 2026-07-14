#!/usr/bin/env python3
"""Reusable deterministic and transactional generation primitives."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterable


DEFAULT_DIAGNOSTIC_BYTES = 8192
DEFAULT_DIAGNOSTIC_SAMPLES = 20


def deduplicate_source_records(
    records: Iterable[dict], generated_adapters: set[str] | None = None,
) -> list[dict]:
    """Return one source record per project-owned source_ref."""
    generated_adapters = generated_adapters or set()
    unique: dict[str, dict] = {}
    for record in records:
        source = record.get("source_ref") or record.get("path")
        if not isinstance(source, str) or not source:
            continue
        normalized = Path(source).as_posix()
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if (
            normalized == ".guardrails"
            or normalized.startswith(".guardrails/")
            or normalized in generated_adapters
            or record.get("generated_archive") is True
            or record.get("generated_adapter") is True
        ):
            continue
        unique.setdefault(normalized, record)
    return [unique[source] for source in sorted(unique)]


def canonical_tree_digest(root: Path) -> str:
    """Hash a generated tree by relative path, kind, mode, and bytes."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"link\0")
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif path.is_file():
            digest.update(b"file\0")
            digest.update(b"executable\0" if path.stat().st_mode & 0o111 else b"regular\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"dir\0")
        digest.update(b"\0")
    return digest.hexdigest()


def bounded_diagnostics(
    errors: Iterable[str], max_bytes: int = DEFAULT_DIAGNOSTIC_BYTES,
    max_samples: int = DEFAULT_DIAGNOSTIC_SAMPLES,
) -> dict:
    """Aggregate duplicate diagnostics and cap serialized output size."""
    counts = Counter(str(error) for error in errors)
    samples: list[dict] = []
    used = 0
    for message, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        candidate = {"count": count, "message": message}
        size = len(json.dumps(candidate, ensure_ascii=True).encode("utf-8"))
        if len(samples) >= max_samples or used + size > max_bytes:
            break
        samples.append(candidate)
        used += size
    return {
        "unique_count": len(counts),
        "total_count": sum(counts.values()),
        "samples": samples,
        "truncated": len(samples) < len(counts),
    }


def transactional_replace_entries(
    candidate: Path, target: Path, entries: Iterable[str],
) -> None:
    """Replace a generated file set with rollback if any replacement fails."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{target.name}.backup-", dir=target.parent,
    ) as backup_raw:
        backup = Path(backup_raw)
        moved_old: list[str] = []
        installed: list[str] = []
        try:
            for name in entries:
                destination = target / name
                staged = candidate / name
                if destination.exists() or destination.is_symlink():
                    backup_path = backup / name
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, backup_path)
                    moved_old.append(name)
                if staged.exists() or staged.is_symlink():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, destination)
                    installed.append(name)
        except OSError:
            for name in reversed(installed):
                destination = target / name
                if destination.is_dir() and not destination.is_symlink():
                    shutil.rmtree(destination)
                else:
                    destination.unlink(missing_ok=True)
            for name in reversed(moved_old):
                backup_path = backup / name
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup_path, destination)
            raise
