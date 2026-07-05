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

try:  # Python 3.11+; optional -- manifest dep parsing degrades gracefully if absent
    import tomllib
except ModuleNotFoundError:
    tomllib = None


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

_BOUNDARY_TOKENS = frozenset({
    "agent", "assembler", "boundary", "bridge", "classifier", "decoder",
    "ebpf", "enforce", "enforcement", "filter", "gateway", "hook",
    "intercept", "kernel", "mcp", "observer", "parser", "policy",
    "protocol", "proxy", "runtime", "sandbox", "stream", "tool",
})

_BOUNDARY_TEST_TOKENS = frozenset({
    "boundary", "fragment", "fuzz", "isolation", "malformed",
    "negative", "partial", "property", "recovery", "regression",
    "robust", "timeout",
})


# --- Domain-neutral evidence collectors -------------------------------------
# The scanner does NOT classify the project (no keyword profiles). It surfaces
# raw evidence -- the project's own self-description, its dependencies, its
# build commands, and any rules it already keeps -- so the MODEL classifies and
# gap-fills. ("Data-backed, not guessed"; classification is the model's job.)

INSTRUCTION_FILE_NAMES = (
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "COPILOT.md", "CODEX.md",
    "CONTRIBUTING.md", "llms.txt", ".cursorrules",
)
INSTRUCTION_FILE_DIRS = (".cursor/rules", ".claude/rules", ".codex/rules", ".agents")


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def collect_instruction_files(root: Path) -> list[dict]:
    """Rule/instruction docs the project ALREADY keeps. Presence + size only;
    content is the model's to read as authoritative (ingest, don't overwrite)."""
    found: list[dict] = []
    seen: set[str] = set()
    for name in INSTRUCTION_FILE_NAMES:
        if (root / name).is_file():
            found.append({"path": name, "lines": _line_count(root / name)})
            seen.add(name)
    for d in INSTRUCTION_FILE_DIRS:
        rdir = root / d
        if rdir.is_dir():
            for p in sorted(rdir.rglob("*")):
                if p.is_file() and p.suffix.lower() in {".md", ".mdc"}:
                    relp = p.relative_to(root).as_posix()
                    if relp not in seen:
                        found.append({"path": relp, "lines": _line_count(p)})
                        seen.add(relp)
    return sorted(found, key=lambda x: x["path"])[:40]


def readme_excerpt(root: Path) -> str:
    """First non-empty lines of the README -- the project's own one-liner, so
    the model classifies from self-description instead of keyword matching."""
    for name in ("README.md", "README.rst", "README.txt", "README", "readme.md"):
        p = root / name
        if p.is_file():
            try:
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                return ""
            return "\n".join(ln.rstrip() for ln in lines if ln.strip())[:1200]
    return ""


def _toml_dict_deps(path: Path, sections) -> list[str]:
    if tomllib is None:
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    deps: list[str] = []
    for sec in sections:
        block = data
        for part in sec.split("."):
            block = block.get(part, {}) if isinstance(block, dict) else {}
        if isinstance(block, dict):
            deps.extend(block.keys())
    return sorted(set(deps))[:40]


def manifest_deps(root: Path) -> dict[str, list[str]]:
    """Top-level dependency names. Domain-neutral: the model reads
    'aya-ebpf, rcgen, aes-gcm' and infers eBPF + crypto itself."""
    deps: dict[str, list[str]] = {}
    cargo = root / "Cargo.toml"
    if cargo.is_file():
        d = _toml_dict_deps(cargo, ("dependencies", "dev-dependencies", "workspace.dependencies"))
        if d:
            deps["cargo"] = d
    pyproj = root / "pyproject.toml"
    if pyproj.is_file() and tomllib is not None:
        try:
            data = tomllib.loads(pyproj.read_text(encoding="utf-8"))
            reqs = data.get("project", {}).get("dependencies", [])
            names = sorted(set(str(r).split()[0].split("[")[0] for r in reqs if str(r).strip()))[:40]
            if names:
                deps["python"] = names
        except (OSError, tomllib.TOMLDecodeError):
            pass
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            names: list[str] = []
            for k in ("dependencies", "devDependencies"):
                block = data.get(k, {})
                if isinstance(block, dict):
                    names.extend(block.keys())
            if names:
                deps["npm"] = sorted(set(names))[:40]
        except (OSError, json.JSONDecodeError):
            pass
    gomod = root / "go.mod"
    if gomod.is_file():
        try:
            got = [
                ln.strip().split(" v")[0]
                for ln in gomod.read_text(encoding="utf-8", errors="ignore").splitlines()
                if ln.strip().startswith(("github.com/", "golang.org/", "gopkg.in/")) and " v" in ln
            ]
            got = sorted(set(x for x in got if x))[:40]
            if got:
                deps["go"] = got
        except OSError:
            pass
    return deps


def build_targets(root: Path) -> list[str]:
    """Makefile/justfile target names, so the model maps gates to real commands
    instead of the generic 'infer from ecosystem'."""
    for name in ("Makefile", "makefile", "GNUmakefile", "justfile", "Justfile"):
        p = root / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []
        targets: list[str] = []
        for ln in text.splitlines():
            if ln.startswith(("\t", " ", "#")):
                continue
            head = ln.split("#", 1)[0].strip()
            if ":" not in head or "=" in head or head.startswith(("if", "for", "while", "!")):
                continue
            tgt = head.split(":", 1)[0].strip()
            if tgt and not tgt.startswith((".", "$", "%")):
                targets.append(tgt)
        return sorted(set(targets))[:40]
    return []


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
    boundary_samples = sorted(
        rel(root, p)
        for p in files
        if p.suffix.lower() in SOURCE_EXTS
        and any(tok in _BOUNDARY_TOKENS for tok in p.stem.lower().replace("-", "_").replace(".", "_").split("_"))
    )[:40]
    boundary_test_samples = sorted(
        rel(root, p)
        for p in files
        if (
            any(part.lower() in TEST_HINTS for part in p.parts)
            or any(hint in p.name.lower() for hint in TEST_HINTS)
        )
        and any(tok in _BOUNDARY_TEST_TOKENS for tok in p.stem.lower().replace("-", "_").replace(".", "_").split("_"))
    )[:40]

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

    # The scanner deliberately does NOT classify the project (no keyword
    # profiles -- that is the model's judgment call). It surfaces domain-neutral
    # evidence: the project's self-description, its dependencies, its build
    # commands, and any rules it already keeps.
    instruction_files = collect_instruction_files(root)
    readme = readme_excerpt(root)
    deps = manifest_deps(root)
    targets = build_targets(root)

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
        "boundary_samples": boundary_samples,
        "boundary_test_samples": boundary_test_samples,
        "cleanliness_signals": {
            "neutral": neutral_counts,
            "language_smells": lang_smell_counts,
            "large_files": sorted(large_files, key=lambda item: int(item["lines"]), reverse=True)[:30],
            "utility_files": sorted(utility_files)[:50],
        },
        "instruction_files": instruction_files,
        "readme_excerpt": readme,
        "manifest_deps": deps,
        "build_targets": targets,
        "guardrail_questions": [
            "What is the project's real profile? Read readme_excerpt + manifest_deps + the project's own AGENTS.md and state it -- do not trust a scanner label.",
            "Which existing instruction files (AGENTS.md / .claude|cursor|codex/rules / CONTRIBUTING) already state rules? Read them as authoritative and gap-fill, never duplicate.",
            "Which code paths are semantic owners, and which are only adapters?",
            "Which tests are PR gates vs product acceptance gates?",
            "Which release artifacts exist, and are they signed/verifiable (SLSA provenance)?",
            "Which completion claims require remote CI or manual runner evidence?",
            "Which policy/rule/default semantics have exactly one source of truth?",
            "Which layers fail open, fail closed, or degrade, and where is that visible?",
            "Where do plaintext secrets exist, and how are reload/rotation/delete paths verified?",
            "Which runtime or protocol constraints need profile-specific tests?",
            "Which boundaries need BoundaryRobustness tests for weak hints, malformed input, isolation, ID-domain separation, state precedence, false positives/negatives, and pre-effect timing?",
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
