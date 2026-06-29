#!/usr/bin/env python3
"""Scan a repository for guardrail-generation evidence.

Stdlib-only so it runs in most projects without installing dependencies.

Smell detection is split into:
  * language-neutral signals — counted across all source files (debt markers,
    wrapper/mock/policy/secret/protocol keywords); and
  * per-language probes — counted only for languages actually present, so a
    Python or TypeScript project no longer gets misleading counts invented
    from Rust-specific idioms (unwrap/panic/once_cell/...).
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
}

MARKERS = {
    "rust": ["Cargo.toml"],
    "node": ["package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"],
    "python": ["pyproject.toml", "requirements.txt", "poetry.lock", "uv.lock"],
    "go": ["go.mod"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "docker": ["Dockerfile", "docker-compose.yml", "compose.yml"],
    "kubernetes": ["Chart.yaml", "kustomization.yaml"],
    "openapi": ["openapi.yaml", "openapi.yml", "swagger.yaml"],
    "security": ["SECURITY.md", "deny.toml", ".github/dependabot.yml", "CODEOWNERS"],
    "release": ["Makefile", "justfile", ".goreleaser.yml", "release.yml"],
    "guardrails": [
        ".guardrails/INDEX.md",
        ".guardrails/memory.md",
        ".guardrails/rules/hard.md",
        ".guardrails/harness.md",
        ".guardrails/decisions.md",
    ],
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

# Language-neutral signals: meaningful across ecosystems, counted over all source files.
# debt_markers are upper-case acronyms; the rest are matched case-insensitively.
NEUTRAL_SMELLS = {
    "debt_markers": (("TODO", "FIXME", "HACK", "XXX"), True),
    "wrapper_markers": (("compat", "legacy", "deprecated", "backward", "shim"), False),
    "mock_markers": (("mock", "fake", "stub"), False),
    "policy_keyword_markers": (
        ("allowlist", "whitelist", "blacklist", "blocklist", "exclusion"),
        False,
    ),
    "secret_markers": (
        ("api_key", "secret", "token", "password", "private_key", "passwd"),
        False,
    ),
    "protocol_markers": (
        ("content-length", "transfer-encoding", "chunked"),
        False,
    ),
}

# Per-language probes. Counted only for languages actually present in the repo.
# Add a language here only when its probes express a real, recurring risk class.
LANG_SMELLS = {
    "rust": {
        "unwrap_or_panic": ("unwrap(", "expect(", "panic!", "unreachable!", "todo!(", "unimplemented!"),
        "raw_json_value": ("serde_json::value", "serde_json::json!", "json!(", "serde_json::Value"),
        "global_mutable_state": ("static mut ", "lazy_static!", "once_cell", "thread_local!"),
    },
    "python": {
        "bare_assert": ("assert ",),
        "broad_except": ("except:", "except Exception", "except  Exception"),
        "not_implemented": ("NotImplementedError",),
        "global_state": ("\nglobal ", "globals()["),
    },
    "typescript": {
        "escape_any": (": any", "as any", "<any>", "@ts-ignore", "@ts-expect-error"),
        "non_null_assertion": ("!.", "!["),
        "console_log": ("console.log",),
    },
    "javascript": {
        "console_log": ("console.log",),
        "ts_ignore": ("@ts-ignore",),
    },
    "go": {
        "panic_or_fatal": ("panic(", "log.Fatal", "log.Fatalf"),
        "ignored_error": ("_, _ =", "_ = err"),
    },
    "java": {
        "print_stacktrace": ("printStackTrace",),
        "generic_catch": ("catch (Exception", "catch (Throwable"),
    },
    "kotlin": {
        "forced_null": ("!!",),
    },
    "c_cpp": {
        "raw_alloc": ("malloc(", "calloc(", "realloc("),
        "unsafe_cast": ("(void *)", "reinterpret_cast", "static_cast"),
    },
}

SOURCE_EXTS = set().union(*LANG_EXTS.values())

# Stems (split on _ - .) that signal logging/audit/telemetry code, for the
# owner-map "Audit / logs" area. Token-level so "metric" does not match
# "asymmetric" / "symmetric" the way a naive substring would.
_AUDIT_TOKENS = frozenset({
    "audit", "audits", "logger", "logging", "log", "logs",
    "trace", "traces", "tracer", "tracing", "telemetry",
    "metric", "metrics", "observ", "observer", "observability",
})


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


def count_tokens(text: str, tokens: tuple[str, ...], case_sensitive: bool) -> int:
    hay = text if case_sensitive else text.lower()
    total = 0
    for tok in tokens:
        needle = tok if case_sensitive else tok.lower()
        total += hay.count(needle)
    return total


def lang_of(path: Path) -> str | None:
    for lang, exts in LANG_EXTS.items():
        if path.suffix in exts:
            return lang
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--out", help="write JSON to this path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    files = list(iter_files(root))

    languages: dict[str, int] = {key: 0 for key in LANG_EXTS}
    language_file_samples: dict[str, list[str]] = {key: [] for key in LANG_EXTS}
    for path in files:
        lang = lang_of(path)
        if lang:
            languages[lang] += 1
            if len(language_file_samples[lang]) < 20:
                language_file_samples[lang].append(rel(root, path))

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

    # Targeted probes for owner-map areas that raw source samples cannot
    # discriminate (logging/audit vs entry/UI). Conservative patterns to avoid
    # noise: audit uses substrings, entry uses exact stems.
    audit_samples = sorted(
        rel(root, p)
        for p in files
        if any(tok in _AUDIT_TOKENS for tok in p.stem.lower().replace("-", "_").replace(".", "_").split("_"))
    )[:20]
    entry_samples = sorted(
        rel(root, p)
        for p in files
        if p.stem.lower() in {"main", "app", "cli", "server", "index", "wsgi", "asgi", "manage", "handler", "route"}
    )[:20]

    ci_files = []
    workflows = root / ".github" / "workflows"
    if workflows.exists():
        ci_files = [rel(root, p) for p in workflows.glob("*") if p.is_file()]

    large_files: list[dict[str, int | str]] = []
    utility_files: list[str] = []
    neutral_counts = {key: 0 for key in NEUTRAL_SMELLS}
    # Only track smell counts for languages that have BOTH source files and probes.
    lang_smell_counts: dict[str, dict[str, int]] = {
        lang: {smell: 0 for smell in probes}
        for lang, probes in LANG_SMELLS.items()
        if languages.get(lang, 0) > 0
    }

    for path in files:
        stem = path.stem.lower()
        if stem in {"utils", "helper", "helpers", "common", "misc"}:
            utility_files.append(rel(root, path))

        if path.suffix.lower() not in SOURCE_EXTS:
            continue
        try:
            if ".min." in path.name.lower() or path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        line_count = len(text.splitlines())
        if line_count >= 800:
            large_files.append({"path": rel(root, path), "lines": line_count})

        for key, (tokens, case_sensitive) in NEUTRAL_SMELLS.items():
            neutral_counts[key] += count_tokens(text, tokens, case_sensitive)

        lang = lang_of(path)
        if lang and lang in lang_smell_counts:
            lower = text.lower()
            for smell, tokens in LANG_SMELLS[lang].items():
                lang_smell_counts[lang][smell] += sum(lower.count(tok.lower()) for tok in tokens)

    profile_hints = []
    likely_profiles = []
    if evidence["rust"] or languages["rust"]:
        profile_hints.append("rust")
    if evidence["python"] or languages["python"]:
        profile_hints.append("python")
    if languages["shell"]:
        profile_hints.append("shell")
    if evidence["node"] or languages["typescript"] or languages["javascript"]:
        profile_hints.append("web_or_node")
    if languages["go"]:
        profile_hints.append("go")
    if languages["java"] or languages["kotlin"]:
        profile_hints.append("jvm")
    if languages["c_cpp"]:
        profile_hints.append("native")
    if evidence["docker"] or evidence["kubernetes"]:
        likely_profiles.append("infra_or_service")
    if evidence["openapi"]:
        likely_profiles.append("api_service")
    if evidence["release"]:
        profile_hints.append("release_artifact_producer")
    if evidence["guardrails"]:
        profile_hints.append("existing_guardrails")
    if any("e2e" in p.lower() or "playwright" in p.lower() for p in test_files):
        likely_profiles.append("product_or_web_e2e")

    result = {
        "root": str(root),
        "languages": {k: v for k, v in languages.items() if v},
        "language_file_samples": {
            k: sorted(v)
            for k, v in language_file_samples.items()
            if v
        },
        "evidence": evidence,
        "ci_files": ci_files,
        "test_files_sample": test_files,
        "docs_sample": docs,
        "audit_samples": audit_samples,
        "entry_samples": entry_samples,
        "cleanliness_signals": {
            "neutral": neutral_counts,
            "language_smells": lang_smell_counts,
            "large_files": sorted(large_files, key=lambda item: int(item["lines"]), reverse=True)[:30],
            "utility_files": sorted(utility_files)[:50],
        },
        "likely_profiles": sorted(set(likely_profiles)),
        "profile_hints": sorted(set(profile_hints)),
        "guardrail_questions": [
            "Which code paths are semantic owners, and which are only adapters?",
            "Which tests are PR gates vs product acceptance gates?",
            "Which release artifacts exist, and are they signed/verifiable (SLSA provenance)?",
            "Which completion claims require remote CI or manual runner evidence?",
            "Which policy/rule/default semantics have exactly one source of truth?",
            "Which layers fail open, fail closed, or degrade, and where is that visible?",
            "Where do plaintext secrets exist, and how are reload/rotation/delete paths verified?",
            "Which runtime or protocol constraints need profile-specific tests?",
            "Which coverage exclusions are replaced by stronger real-stack evidence?",
            "Which learned facts belong in memory.md, and which are still unresolved decisions?",
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
