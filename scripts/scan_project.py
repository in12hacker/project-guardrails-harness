#!/usr/bin/env python3
"""Scan a repository for guardrail-generation evidence.

This script intentionally uses only the Python standard library so it can run in
most projects without dependency installation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable


IGNORE_DIRS = {
    ".git",
    "target",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".vite",
    ".turbo",
    ".gradle",
    "coverage",
    "vendor",
    "playwright-report",
    "test-results",
    "logs",
}

LANG_EXTS = {
    "rust": {".rs"},
    "typescript": {".ts", ".tsx"},
    "javascript": {".js", ".jsx", ".mjs", ".cjs"},
    "python": {".py"},
    "go": {".go"},
    "java": {".java"},
    "kotlin": {".kt", ".kts"},
    "c_cpp": {".c", ".cc", ".cpp", ".h", ".hpp"},
    "shell": {".sh", ".bash", ".zsh"},
    "yaml": {".yml", ".yaml"},
}

MARKERS = {
    "rust": ["Cargo.toml"],
    "node": ["package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"],
    "python": ["pyproject.toml", "requirements.txt", "poetry.lock", "uv.lock"],
    "go": ["go.mod"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "docker": ["Dockerfile", "docker-compose.yml", "compose.yml"],
    "kubernetes": ["Chart.yaml", "kustomization.yaml"],
    "github_actions": [".github/workflows"],
    "openapi": ["openapi.yaml", "openapi.yml", "swagger.yaml", "api"],
    "security": ["SECURITY.md", "deny.toml", ".github/dependabot.yml"],
    "release": ["Makefile", "justfile", ".goreleaser.yml", "release.yml"],
}

TEST_HINTS = (
    "test",
    "tests",
    "__tests__",
    "spec",
    "e2e",
    "playwright",
    "cypress",
    "pytest",
)

TEXT_EXTS = {
    ".rs",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".py",
    ".go",
    ".java",
    ".kt",
    ".kts",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".sh",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".md",
}

SOURCE_EXTS = set().union(*LANG_EXTS.values()) - {".yaml", ".yml"}

DEBT_MARKERS = ("TODO", "FIXME", "HACK", "XXX")
WRAPPER_MARKERS = ("compat", "legacy", "deprecated", "backward", "shim")
MOCK_MARKERS = ("mock", "fake", "stub")


def iter_files(root: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        base = Path(current)
        for name in files:
            yield base / name


def rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def marker_exists(root: Path, marker: str) -> list[str]:
    path = root / marker
    if path.exists():
        return [marker]
    matches: list[str] = []
    if "/" not in marker:
        for found in root.rglob(marker):
            if any(part in IGNORE_DIRS for part in found.parts):
                continue
            matches.append(rel(root, found))
    return sorted(matches)[:20]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--out", help="write JSON to this path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    files = list(iter_files(root))

    languages: dict[str, int] = {key: 0 for key in LANG_EXTS}
    for path in files:
        for lang, exts in LANG_EXTS.items():
            if path.suffix in exts:
                languages[lang] += 1

    evidence: dict[str, list[str]] = {}
    for group, markers in MARKERS.items():
        hits: list[str] = []
        for marker in markers:
            hits.extend(marker_exists(root, marker))
        evidence[group] = sorted(set(hits))[:30]

    test_files = [
        rel(root, p)
        for p in files
        if any(part.lower() in TEST_HINTS for part in p.parts)
        or any(hint in p.name.lower() for hint in TEST_HINTS)
    ][:80]

    docs = [
        rel(root, p)
        for p in files
        if p.suffix.lower() in {".md", ".rst", ".adoc"}
    ][:80]

    ci_files = []
    workflows = root / ".github" / "workflows"
    if workflows.exists():
        ci_files = [rel(root, p) for p in workflows.glob("*") if p.is_file()]

    large_files: list[dict[str, int | str]] = []
    utility_files: list[str] = []
    marker_counts = {
        "debt_markers": 0,
        "wrapper_markers": 0,
        "mock_markers": 0,
        "raw_json_or_dict_markers": 0,
        "panic_or_assert_markers": 0,
        "policy_or_default_markers": 0,
        "secret_markers": 0,
        "global_state_markers": 0,
        "protocol_markers": 0,
    }

    for path in files:
        name = path.name.lower()
        stem = path.stem.lower()
        if stem in {"utils", "helper", "helpers", "common", "misc"}:
            utility_files.append(rel(root, path))

        if path.suffix.lower() not in SOURCE_EXTS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        line_count = text.count("\n") + 1
        if line_count >= 800:
            large_files.append({"path": rel(root, path), "lines": line_count})

        upper = text.upper()
        marker_counts["debt_markers"] += sum(upper.count(marker) for marker in DEBT_MARKERS)
        lower = text.lower()
        marker_counts["wrapper_markers"] += sum(lower.count(marker) for marker in WRAPPER_MARKERS)
        marker_counts["mock_markers"] += sum(lower.count(marker) for marker in MOCK_MARKERS)
        marker_counts["raw_json_or_dict_markers"] += lower.count("serde_json::value")
        marker_counts["raw_json_or_dict_markers"] += lower.count("json!")
        marker_counts["panic_or_assert_markers"] += lower.count("unwrap(")
        marker_counts["panic_or_assert_markers"] += lower.count("expect(")
        marker_counts["panic_or_assert_markers"] += lower.count("panic!")
        marker_counts["policy_or_default_markers"] += lower.count("allowlist")
        marker_counts["policy_or_default_markers"] += lower.count("whitelist")
        marker_counts["policy_or_default_markers"] += lower.count("blacklist")
        marker_counts["policy_or_default_markers"] += lower.count("exclusion")
        marker_counts["policy_or_default_markers"] += lower.count("unwrap_or_default")
        marker_counts["policy_or_default_markers"] += lower.count("default::default")
        marker_counts["secret_markers"] += lower.count("api_key")
        marker_counts["secret_markers"] += lower.count("secret")
        marker_counts["secret_markers"] += lower.count("token")
        marker_counts["secret_markers"] += lower.count("password")
        marker_counts["secret_markers"] += lower.count("private_key")
        marker_counts["global_state_markers"] += lower.count("static mut")
        marker_counts["global_state_markers"] += lower.count("lazy_static")
        marker_counts["global_state_markers"] += lower.count("once_cell")
        marker_counts["global_state_markers"] += lower.count("thread_local")
        marker_counts["protocol_markers"] += lower.count("content-length")
        marker_counts["protocol_markers"] += lower.count("transfer-encoding")
        marker_counts["protocol_markers"] += lower.count("chunked")
        marker_counts["protocol_markers"] += lower.count("flush(")
        marker_counts["protocol_markers"] += lower.count("timeout")

    likely_profiles = []
    if evidence["rust"] or languages["rust"]:
        likely_profiles.append("rust")
    if evidence["node"] or languages["typescript"] or languages["javascript"]:
        likely_profiles.append("web_or_node")
    if evidence["docker"] or evidence["kubernetes"]:
        likely_profiles.append("infra_or_service")
    if evidence["openapi"]:
        likely_profiles.append("api_service")
    if any("e2e" in p.lower() or "playwright" in p.lower() for p in test_files):
        likely_profiles.append("product_or_web_e2e")

    result = {
        "root": str(root),
        "languages": {k: v for k, v in languages.items() if v},
        "evidence": evidence,
        "ci_files": ci_files,
        "test_files_sample": test_files,
        "docs_sample": docs,
        "cleanliness_signals": {
            "large_files": sorted(large_files, key=lambda item: int(item["lines"]), reverse=True)[:30],
            "utility_files": sorted(utility_files)[:50],
            "marker_counts": marker_counts,
        },
        "likely_profiles": sorted(set(likely_profiles)),
        "guardrail_questions": [
            "Which code paths are semantic owners, and which are only adapters?",
            "Which tests are PR gates vs product acceptance gates?",
            "Which release artifacts exist, and are they signed/verifiable?",
            "Which completion claims require remote CI or manual runner evidence?",
            "Which policy/rule/default semantics have exactly one source of truth?",
            "Which layers fail open, fail closed, or degrade, and where is that visible?",
            "Where do plaintext secrets exist, and how are reload/rotation/delete paths verified?",
            "Which runtime or protocol constraints need profile-specific tests?",
            "Which coverage exclusions are replaced by stronger real-stack evidence?",
        ],
    }

    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
