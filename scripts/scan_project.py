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
import re
from pathlib import Path
from typing import Iterable

try:  # Python 3.11+; optional -- manifest dep parsing degrades gracefully if absent
    import tomllib
except ModuleNotFoundError:
    tomllib = None


IGNORE_DIRS = {
    ".git",
    ".guardrails",
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
    ".runtime",
    ".cache",
    "artifacts",
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
    "gradle_wrapper": ["gradlew"],
    "maven_wrapper": ["mvnw"],
    "cmake": ["CMakeLists.txt"],
    "docker": ["Dockerfile", "docker-compose.yml", "compose.yml"],
    "kubernetes": ["Chart.yaml", "kustomization.yaml"],
    "openapi": ["openapi.yaml", "openapi.yml", "swagger.yaml"],
    "security": ["SECURITY.md", "deny.toml", ".github/dependabot.yml", "CODEOWNERS",
                 ".git-secrets"],
    "release": ["Makefile", "justfile", ".goreleaser.yml", "release.yml", "release.toml",
                "RELEASES.md", "RELEASE.md", "CHANGELOG.md", "SHA256SUMS",
                "SBOM.spdx.json", "SBOM.cyclonedx.json", "sbom.spdx.json", "sbom.cyclonedx.json",
                "PGP-KEY.asc", "cosign.pub"],
    # Raw governance evidence. Presence does not establish maturity or applicability.
    "governance": ["LICENSE", "SECURITY.md", "CONTRIBUTING.md", "CODEOWNERS", "GOVERNANCE.md",
                   "CHARTER.md", "MAINTAINERS.md", "SPECIFICATION.md", "VERSIONING.md",
                   "DEPRECATED.md"],
    "engineering_hygiene": ["rust-toolchain.toml", "rust-toolchain", ".gitlint",
                            ".git-blame-ignore-revs"],
    "operations": ["RUNBOOK.md", "OPERATIONS.md", "SLO.md", "SUPPORT.md"],
    "accessibility": ["ACCESSIBILITY.md", "VPAT.md"],
    # Raw policy evidence; content and applicability require owner review.
    "privacy_compliance": ["PRIVACY.md", "AI_POLICY.md", "GDPR.md", "DATA_RETENTION.md",
                           "DPA.md", "SUBPROCESSORS.md"],
    "ai_assurance": ["MODEL_CARD.md", "AI_RISK.md", "EVALS.md"],
    # License evidence is not a legal classification.
    "licensing": ["LICENSE-EE", "LICENSE-3rdparty.csv", "license-tool.toml",
                  "LICENSE-APACHE", "LICENSE-MIT", "LICENSE-MPL", "denied_words.txt",
                  "LICENSE.community", "LICENSE.enterprise", "THIRD-PARTY", "NOTICE"],
    # Contract artifacts are candidates; they do not prove a public contract or gate.
    "api_contract": ["buf.yaml", "buf.gen.yaml", "buf.lock", "public-api-snapshot.json",
                     "swagger.json", "swagger.yaml", ".openapi-generator.yaml"],
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

INSTRUCTION_FILE_NAMES = frozenset({
    "AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CLAUDE.local.md",
    "GEMINI.md", "GEMINI.local.md", "COPILOT.md", "CODEX.md",
    "CONTRIBUTING.md", "llms.txt", ".cursorrules",
    "copilot-instructions.md",
})
INSTRUCTION_FILE_DIRS = (
    ".cursor/rules", ".claude/rules", ".codex/rules", ".agents",
    ".claude/skills", ".agents/skills", ".github/instructions",
)


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
    for path in iter_files(root):
        if path.name not in INSTRUCTION_FILE_NAMES:
            continue
        relative = path.relative_to(root).as_posix()
        if relative in seen:
            continue
        found.append({"path": relative, "lines": _line_count(path)})
        seen.add(relative)
    for d in INSTRUCTION_FILE_DIRS:
        rdir = root / d
        if rdir.is_dir():
            for p in sorted(rdir.rglob("*")):
                if p.is_symlink():
                    continue
                if p.is_file() and (
                    p.suffix.lower() in {".md", ".mdc"} or p.name == "SKILL.md"
                ):
                    relp = p.relative_to(root).as_posix()
                    if relp not in seen:
                        found.append({"path": relp, "lines": _line_count(p)})
                        seen.add(relp)
    return sorted(found, key=lambda x: x["path"])


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


def build_target_details(root: Path) -> list[dict]:
    """Makefile/justfile targets with their actual invocation."""
    details: list[dict] = []
    for name in ("Makefile", "makefile", "GNUmakefile", "justfile", "Justfile"):
        p = root / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ln in text.splitlines():
            if ln.startswith(("\t", " ", "#")):
                continue
            head = ln.split("#", 1)[0].strip()
            if ":" not in head or "=" in head or head.startswith(("if", "for", "while", "!")):
                continue
            target_head = head.split(":", 1)[0].strip()
            if name.lower() == "justfile":
                targets = target_head.split()[:1]
            else:
                targets = target_head.split()
            for tgt in targets:
                if tgt and not tgt.startswith((".", "$", "%")):
                    command = ["just", tgt] if name.lower() == "justfile" else ["make", tgt]
                    details.append({"name": tgt, "source": name, "command": command})
    unique: dict[tuple[str, str], dict] = {}
    for item in details:
        unique[(item["source"], item["name"])] = item
    return sorted(unique.values(), key=lambda item: (item["source"], item["name"]))[:160]


def build_targets(root: Path) -> list[str]:
    return sorted({item["name"] for item in build_target_details(root)})[:160]


GATE_TARGET_PATTERNS = {
    "format": ("fmt", "format"),
    "lint_static": ("lint", "clippy", "static", "typecheck"),
    "unit_integration": ("test", "unit", "integration"),
    "contract": ("contract", "schema", "openapi", "api"),
    "architecture": ("fitness", "architecture", "quality", "boundary"),
    "coverage": ("coverage", "cov"),
    "security": ("sast", "dast", "security", "audit", "deny", "secret", "vuln"),
    "product_acceptance": ("e2e", "product", "real-stack", "real_stack", "acceptance", "live"),
    "release": ("release", "supply", "sbom", "provenance", "attestation", "reproducible", "sign-artifact"),
    "operations": ("slo", "load", "capacity", "smoke", "deploy", "rollback", "restore"),
}


def gate_inventory(target_details: list[dict]) -> list[dict]:
    inventory: list[dict] = []
    for item in target_details:
        lowered = item["name"].lower()
        categories = [
            category for category, patterns in GATE_TARGET_PATTERNS.items()
            if any(pattern in lowered for pattern in patterns)
        ]
        if categories:
            inventory.append({**item, "categories": categories, "status": "detected_unverified"})
    return inventory


def collect_package_scripts(root: Path) -> list[dict]:
    scripts: list[dict] = []
    for path in sorted(root.rglob("package.json")):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        block = data.get("scripts", {})
        if not isinstance(block, dict):
            continue
        package_dir = path.parent.relative_to(root).as_posix()
        for name, command in sorted(block.items()):
            scripts.append({
                "package": package_dir or ".",
                "name": name,
                "command": str(command),
                "invocation": ["npm", "run", name],
            })
    return scripts[:120]


def collect_ci_commands(root: Path) -> list[dict]:
    commands: list[dict] = []
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return commands
    for path in sorted(workflow_dir.glob("*")):
        if not path.is_file() or path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        current_job = "unknown"
        in_jobs = False
        for line in lines:
            if re.match(r"^jobs:\s*$", line):
                in_jobs = True
                continue
            job_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line) if in_jobs else None
            if job_match:
                current_job = job_match.group(1)
            run_match = re.match(r"^\s+-?\s*run:\s*(.+)$", line)
            uses_match = re.match(r"^\s+-?\s*uses:\s*(.+)$", line)
            if run_match:
                commands.append({"workflow": rel(root, path), "job": current_job, "type": "run", "value": run_match.group(1).strip()})
            elif uses_match:
                commands.append({"workflow": rel(root, path), "job": current_job, "type": "uses", "value": uses_match.group(1).strip()})
    return commands[:240]


def collect_fitness_registry(root: Path) -> list[dict]:
    """Read the common pipe-delimited shell registry shape when present."""
    runner = root / "scripts" / "fitness-runner.sh"
    if not runner.is_file():
        return []
    try:
        text = runner.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    entries: list[dict] = []
    pattern = re.compile(
        r'^\s*"([^|"\n]+)\|([^|"\n]+)\|([^|"\n]+)\|([^|"\n]+)\|([^|"\n]+)\|([^"\n]+)"\s*$',
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        ff_id, dimension, script, gate, skippable, description = match.groups()
        entries.append({
            "id": ff_id,
            "dimension": dimension,
            "script": f"scripts/{script}",
            "gate": gate,
            "skippable": skippable == "1",
            "description": description,
        })
    return entries[:240]


def iter_files(root: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        base = Path(current)
        for name in files:
            yield base / name


def rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def marker_exists(root: Path, marker: str, files_by_name: dict[str, list[Path]]) -> list[str]:
    path = root / marker
    if path.exists():
        return [marker]
    matches: list[str] = []
    if "/" not in marker:
        for found in files_by_name.get(marker, []):
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
    files_by_name: dict[str, list[Path]] = {}
    for path in files:
        files_by_name.setdefault(path.name, []).append(path)

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
            hits.extend(marker_exists(root, marker, files_by_name))
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

    production_source_samples = sorted(
        rel(root, p)
        for p in files
        if p.suffix.lower() in SOURCE_EXTS
        and not any(part.lower() in TEST_HINTS for part in p.parts)
        and not any(part in {"scripts", "script", "examples", "example", "fixtures", "fixture", "generated"} for part in p.parts)
        and not any(hint in p.name.lower() for hint in TEST_HINTS)
    )[:120]

    # Targeted probes for owner-map areas that raw source samples cannot
    # discriminate (logging/audit vs entry/UI). Conservative patterns to avoid
    # noise: audit uses substrings, entry uses exact stems.
    audit_samples = sorted(
        rel(root, p)
        for p in files
        if p.suffix.lower() in SOURCE_EXTS
        and any(tok in _AUDIT_TOKENS for tok in p.stem.lower().replace("-", "_").replace(".", "_").split("_"))
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
    fitness_samples = sorted(
        rel(root, p)
        for p in files
        if (
            p.name.startswith("check-")
            or "fitness" in p.name.lower()
            or p.name.lower() in {"architecture-rules.toml", "archunit.yml", "archunit.yaml"}
        )
    )[:60]
    module_index_samples = sorted(
        rel(root, p)
        for p in files
        if p.name == "INDEX.md" and p.parent != root
    )[:60]
    baseline_samples = sorted(
        rel(root, p)
        for p in files
        if any(tok in p.name.lower() for tok in ("baseline", "allowlist", "allow-list", "exceptions"))
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
    target_details = build_target_details(root)
    targets = sorted({item["name"] for item in target_details})
    gates = gate_inventory(target_details)
    package_scripts = collect_package_scripts(root)
    ci_commands = collect_ci_commands(root)
    fitness_registry = collect_fitness_registry(root)

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
        "production_source_samples": production_source_samples,
        "docs_sample": docs,
        "audit_samples": audit_samples,
        "entry_samples": entry_samples,
        "boundary_samples": boundary_samples,
        "boundary_test_samples": boundary_test_samples,
        "fitness_samples": fitness_samples,
        "module_index_samples": module_index_samples,
        "baseline_samples": baseline_samples,
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
        "build_target_details": target_details,
        "gate_inventory": gates,
        "package_scripts": package_scripts,
        "ci_commands": ci_commands,
        "fitness_registry": fitness_registry,
        "guardrail_questions": [
            "What is the project's real profile? Read readme_excerpt + manifest_deps + the project's own AGENTS.md and state it -- do not trust a scanner label.",
            "Which existing instruction files (AGENTS.md / .claude|cursor|codex/rules / CONTRIBUTING) already state rules? Read them as authoritative and gap-fill, never duplicate.",
            "Which code paths are semantic owners, and which are only adapters?",
            "Which tests are PR gates vs product acceptance gates?",
            "Which tests have explicit test basis, risk, size, runner, and scenario origin?",
            "Which release artifacts exist, and are they signed/verifiable (SLSA provenance)?",
            "Which check scripts are registered as fitness functions with owner, gate, scope, and baseline semantics?",
            "Which modules are production-ready, provisionally-ready, or not-ready by objective readiness criteria?",
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
