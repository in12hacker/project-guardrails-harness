#!/usr/bin/env python3
"""Render a first-pass guardrails doc set from scan_project.py output.

Two output modes:

  --out-dir DIR  (preferred for agents)
      Emits a *progressive-disclosure* directory: a small INDEX.md that is
      always loaded, plus per-concern files an agent reads just-in-time by
      relevance. This avoids the cost of a single monolithic file, which
      buries critical rules mid-document ("lost in the middle") and re-costs
      tokens on every read. Mirrors the AGENTS.md nested-file convention.

  --out FILE / no flag  (legacy / human)
      Writes (or prints) one combined guardrails.md — good for humans and
      full-text search; agents should prefer --out-dir.

Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def yes(x) -> str:
    return "yes" if x else "no"


def fmt_paths(paths: list[str], limit: int = 5) -> str:
    return ", ".join(f"`{p}`" for p in paths[:limit]) if paths else "not found"


def _flatten_deps(deps: dict) -> list[str]:
    out: list[str] = []
    for values in deps.values():
        out.extend(str(v) for v in values)
    return out


def _contains_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(n in lowered for n in needles)


def _target_contains(targets: list[str], needles: list[str]) -> bool:
    return any(_contains_any(t, needles) for t in targets)


def _matching_values(values: list[str], needles: list[str]) -> list[str]:
    return [v for v in values if _contains_any(v, needles)]


def _evidence_cell(values: list[str], limit: int = 4) -> str:
    return fmt_paths(values, limit) if values else "scan signal only; validate manually"


def fmt_commands(items: list[dict], limit: int = 4) -> str:
    commands: list[str] = []
    for item in items[:limit]:
        argv = item.get("command", [])
        if isinstance(argv, list) and argv:
            commands.append(f"`{' '.join(str(part) for part in argv)}`")
    return ", ".join(commands) if commands else "_no mapped command_"


def candidate_rules(scan: dict) -> list[dict]:
    """Infer project-local rule drafts from scan evidence.

    These are intentionally conservative: the portable skill supplies generic
    patterns, while the generated file keeps project-specific names and paths.
    Nothing here is a hard rule until a maintainer validates it.
    """
    evidence = scan.get("evidence", {})
    deps = scan.get("manifest_deps", {})
    dep_names = _flatten_deps(deps)
    targets = scan.get("build_targets", [])
    instr = scan.get("instruction_files", [])
    instr_paths = [f.get("path", "") for f in instr if f.get("path")]
    boundary = scan.get("boundary_samples", [])
    boundary_tests = scan.get("boundary_test_samples", [])
    fitness = scan.get("fitness_samples", [])
    fitness_registry = scan.get("fitness_registry", [])
    module_indexes = scan.get("module_index_samples", [])
    baselines = scan.get("baseline_samples", [])
    tests = scan.get("test_files_sample", [])
    readme = scan.get("readme_excerpt", "")
    ci = scan.get("ci_files", [])

    candidates: list[dict] = []

    if instr_paths:
        candidates.append({
            "title": "Ingest existing project instructions before adding guardrails",
            "family": "Evidence integrity / rule lifecycle",
            "rule": "Before changing project guardrails, read the detected instruction files, link to authoritative rules, and only add gap-filling rules that have a source, owner, and verification path.",
            "evidence": instr_paths,
            "confidence": "high",
            "reject_if": "the candidate duplicates text already owned by an instruction file instead of linking to it",
            "verification_gap": "record which instruction files were read and which gap each new rule fills",
        })

    if targets:
        candidates.append({
            "title": "Verification gates must map to project-owned commands",
            "family": "Harness truthfulness",
            "rule": "Completion, mergeability, product-acceptance, and release claims must cite real project commands or CI jobs from the repository; missing commands are gaps, not inferred checks.",
            "evidence": targets,
            "confidence": "high",
            "reject_if": "the check name is generic, unavailable locally, or not wired to the project's CI/release path",
            "verification_gap": "choose the exact command for each gate in harness.md and mark unavailable gates as manual/blocked",
        })

    if boundary or boundary_tests:
        confidence = "high" if boundary and boundary_tests else "medium"
        candidates.append({
            "title": "Boundary-sensitive changes need explicit robustness coverage",
            "family": "BoundaryRobustness",
            "rule": "Changes touching protocol/runtime/agent/tool/security boundaries should test strong positive signals, weak hints, malformed or partial input, false positives, cross-source isolation, ID-domain separation, state precedence, recovery, and pre-effect timing.",
            "evidence": boundary + boundary_tests,
            "confidence": confidence,
            "reject_if": "tests only cover the happy path or prove behavior after the protected effect already happened",
            "verification_gap": "map each Boundary Robustness Harness row to real tests, fuzz/property checks, or manual evidence",
        })

    if fitness or fitness_registry:
        fitness_evidence = [entry.get("script", "") for entry in fitness_registry if entry.get("script")] + fitness
        candidates.append({
            "title": "Architecture checks need a fitness-function registry",
            "family": "Module readiness / fitness functions",
            "rule": "Every project-owned check script or architecture rule should be registered with its dimension, owner, gate level, scope, ratchet/baseline semantics, and command entry point; orphan checks should be wired into a gate or deleted.",
            "evidence": fitness_evidence,
            "confidence": "high",
            "reject_if": "the script is one-off migration tooling or a developer exploration command that is intentionally not a gate",
            "verification_gap": "create or update the project registry and prove each active check is invoked by a real command or CI job",
        })

    if module_indexes or fitness:
        candidates.append({
            "title": "Module readiness needs objective stop/refactor criteria",
            "family": "Module readiness / architecture stability",
            "rule": "A module should be declared stable only against explicit readiness dimensions such as single owner, dependency direction, typed interface boundary, documentation, tests, panic/error policy, dead-code/wrapper policy, and size/complexity gates. Reviewers should tie required refactors to a violated rule or fitness function.",
            "evidence": module_indexes + fitness,
            "confidence": "medium",
            "reject_if": "the project has no module boundary concept or no maintainers willing to own readiness states",
            "verification_gap": "define readiness states, allowed exceptions with review/delete dates, and the checks that prove each dimension",
        })

    if baselines or _target_contains(targets, ["baseline", "ratchet", "allow"]):
        candidates.append({
            "title": "Baselines must expose cleanup debt, not legalize violations",
            "family": "Rule lifecycle / ratchet",
            "rule": "Baseline or allowlist files should distinguish design-scope exemptions from cleanup debt. Known violations remain visible with owner and deletion path; updating a baseline should reduce or explain debt, not silently bless new violations.",
            "evidence": baselines + _matching_values(targets, ["baseline", "ratchet", "allow"]),
            "confidence": "medium",
            "reject_if": "the file is a generated coverage/test fixture baseline unrelated to quality or architecture governance",
            "verification_gap": "state the pass/fail behavior for known and new violations, and record how debt count is expected to shrink",
        })

    if tests:
        candidates.append({
            "title": "Gate tests need basis, risk, size, runner, and scenario origin",
            "family": "Test and harness truthfulness",
            "rule": "Tests used as gates should state the requirement, risk or regression they prove, test level/size, runner prerequisites, evidence artifacts, cleanup, residual risk, and whether the stimulus is real product, CLI-equivalent, sensor smoke, or mock/contract.",
            "evidence": tests,
            "confidence": "medium",
            "reject_if": "the test is a small local helper not used for completion, product, closeout, or release claims",
            "verification_gap": "add a TestGate or equivalent metadata block for gate-level tests and downgrade shortcuts to smoke/contract evidence",
        })

    product_targets = _matching_values(targets, ["e2e", "product", "real", "stack", "live"])
    readme_product_signal = _contains_any(readme, [
        "agent", "user", "protect", "security", "gateway", "runtime", "local", "policy", "product", "app", "cli",
    ])
    product_signals = (
        bool(product_targets)
        or (readme_product_signal and bool(targets + tests))
    )
    if product_signals:
        candidates.append({
            "title": "Product acceptance should use real user-visible stimulus",
            "family": "Product/profile fit",
            "rule": "User-facing or runtime behavior should be accepted through the product surface a user/operator actually exercises, not only direct unit calls, mocks, or internal contract fixtures.",
            "evidence": product_targets + tests,
            "confidence": "medium",
            "reject_if": "the project is a contract-only library or the cited test bypasses the product behavior being claimed",
            "verification_gap": "name the real stimulus, visible output/status, and command that exercises it",
        })

    api_dep_hits = _matching_values(dep_names, [
        "axum", "actix", "rocket", "tower", "hyper", "express", "fastify", "django", "flask", "spring",
        "grpc", "protobuf", "tonic",
    ])
    api_signals = evidence.get("openapi", []) or api_dep_hits
    if api_signals:
        api_evidence = list(evidence.get("openapi", [])) + api_dep_hits
        candidates.append({
            "title": "Public API and wire-contract changes need contract sync checks",
            "family": "Architecture / API contract",
            "rule": "When handlers, schemas, protocol messages, or public API surfaces change, update the contract source of truth and run the contract or compatibility check that consumers rely on.",
            "evidence": api_evidence,
            "confidence": "medium",
            "reject_if": "the changed path is purely internal and has no public or cross-process contract",
            "verification_gap": "identify the authoritative schema/proto/OpenAPI file or consumer compatibility gate",
        })

    interface_signals = module_indexes or evidence.get("openapi", []) or _matching_values(dep_names, [
        "async-trait", "serde", "protobuf", "tonic", "grpc", "zod", "openapi",
    ])
    if interface_signals:
        candidates.append({
            "title": "Public interfaces need typed, consumer-driven contracts",
            "family": "Interface / port contract",
            "rule": "Public traits, ports, SDK/API contracts, and cross-module signatures should be shaped by real consumers, use typed inputs/outcomes/errors, separate wire DTOs from domain types, and avoid long-lived compatibility wrappers.",
            "evidence": list(evidence.get("openapi", [])) + module_indexes + _matching_values(dep_names, ["async-trait", "serde", "protobuf", "tonic", "grpc", "zod", "openapi"]),
            "confidence": "medium",
            "reject_if": "the interface is private to one file or the project intentionally has no public/stable boundary",
            "verification_gap": "document the interface contract, owner, consumer, evolution policy, and compatibility test",
        })

    if module_indexes or scan.get("docs_sample", []):
        candidates.append({
            "title": "Live documentation needs an owner and freshness tier",
            "family": "Documentation deliverables",
            "rule": "Documentation should distinguish live source-of-truth files that change atomically with code from longer-form docs updated at milestone/release sync. Module indexes should identify responsibility, public API, dependencies, risk, tests, and key decisions without duplicating code comments.",
            "evidence": module_indexes + scan.get("docs_sample", []),
            "confidence": "medium",
            "reject_if": "the project is intentionally documentation-light and has no stable API/module surface",
            "verification_gap": "define which docs are live, which are sync-later, and what template each module/API doc must satisfy",
        })

    if tests and scan.get("cleanliness_signals", {}).get("neutral", {}).get("mock_markers", 0):
        candidates.append({
            "title": "Test code must not copy production semantics",
            "family": "Code cleanliness / test harness",
            "rule": "Gate-level tests should use owner APIs, semantic builders, and custom assertions instead of duplicating production parsers, policy matchers, normalizers, or fixture logic that can drift into false green results.",
            "evidence": tests,
            "confidence": "medium",
            "reject_if": "the duplicated data is a tiny literal fixture with no business or security semantics",
            "verification_gap": "identify repeated fixtures/assertions and route them through owner builders or domain-specific assertions",
        })

    release_target_hits = _matching_values(targets, [
        "release", "supply", "sbom", "provenance", "attestation", "audit", "deny",
    ])
    release_signals = evidence.get("release", []) or release_target_hits
    if release_signals:
        candidates.append({
            "title": "Release claims need an artifact-verification ladder",
            "family": "Supply chain / release",
            "rule": "Release readiness should distinguish dependency scans, produced SBOM/provenance, signed artifacts, and deploy-time verification; do not treat one lower rung as release-grade assurance.",
            "evidence": list(evidence.get("release", [])) + release_target_hits + ci,
            "confidence": "medium",
            "reject_if": "the claim is about local development only or no artifact is produced/distributed",
            "verification_gap": "record which release artifacts are signed, where provenance is produced, and how deployment verifies it",
        })

    secret_dep_hits = _matching_values(dep_names, ["secrecy", "aes-gcm", "rustls", "openssl", "ring", "jwt"])
    secret_signals = (
        evidence.get("security", [])
        or secret_dep_hits
        or _contains_any(readme, ["secret", "token", "credential", "api key", "private key"])
    )
    if secret_signals:
        candidates.append({
            "title": "Secret lifecycle must prove the plaintext boundary",
            "family": "Security / privacy / secrets",
            "rule": "Code that stores, proxies, logs, encrypts, or transforms credentials must identify where plaintext may exist, where it must not persist, and which test/logging check proves that boundary.",
            "evidence": list(evidence.get("security", [])) + secret_dep_hits,
            "confidence": "medium",
            "reject_if": "the dependency/path is security-adjacent but no credential, token, key, or plaintext flow is involved",
            "verification_gap": "map credential sources, redaction points, encryption boundaries, and negative log/storage checks",
        })

    return candidates


# --------------------------------------------------------------------------- #
# Section builders. Each returns a markdown string (no trailing newline).
# They are reused by both the single-file and the multi-file renderers so the
# two modes can never drift apart.
# --------------------------------------------------------------------------- #

def sec_profile(scan: dict) -> str:
    evidence = scan.get("evidence", {})
    languages = scan.get("languages", {})
    ci = scan.get("ci_files", [])
    deps = scan.get("manifest_deps", {})
    targets = scan.get("build_targets", [])
    boundary = scan.get("boundary_samples", [])
    boundary_tests = scan.get("boundary_test_samples", [])
    fitness = scan.get("fitness_samples", [])
    module_indexes = scan.get("module_index_samples", [])
    baselines = scan.get("baseline_samples", [])
    gate_inventory = scan.get("gate_inventory", [])
    package_scripts = scan.get("package_scripts", [])
    ci_commands = scan.get("ci_commands", [])
    fitness_registry = scan.get("fitness_registry", [])
    readme = scan.get("readme_excerpt", "")
    instr = scan.get("instruction_files", [])
    lines = [
        "# Profile & Evidence Inventory",
        "",
        "_The scanner deliberately does not classify the project — that is a judgment call for you. Read the README excerpt + dependencies, then state the profile in your own words before writing rules._",
        "",
        f"- Root: `{scan.get('root')}`",
        f"- Languages: {', '.join(languages) or 'unknown'}",
        f"- CI present: {yes(ci)}" + (f" (`{', '.join(ci[:5])}`)" if ci else ""),
        f"- Tests sampled: {len(scan.get('test_files_sample', []))}",
        f"- Docs sampled: {len(scan.get('docs_sample', []))}",
        f"- Release/build artifacts present: {yes(evidence.get('release'))}",
    ]
    if readme:
        lines += ["", "## README (self-description — classify from this)", "", "```", readme, "```"]
    if deps:
        lines += ["", "## Dependencies (domain signal)", ""]
        for k, v in deps.items():
            lines.append(f"- **{k}**: {', '.join(f'`{d}`' for d in v)}")
    if targets:
        lines += ["", "## Build / task targets (real commands)", "", f"`{'`, `'.join(targets)}`"]
    if gate_inventory:
        lines += [
            "",
            "## Detected gate entry points (unverified)",
            "",
            "| Target | Categories | Invocation | Source |",
            "|---|---|---|---|",
        ]
        for item in gate_inventory[:40]:
            lines.append(
                f"| `{item['name']}` | {', '.join(item.get('categories', []))} | "
                f"`{' '.join(item.get('command', []))}` | `{item.get('source', '')}` |"
            )
    if fitness_registry:
        lines += [
            "",
            f"## Fitness registry ({len(fitness_registry)} structured entries)",
            "",
            "| ID | Dimension | Gate | Script |",
            "|---|---|---|---|",
        ]
        for entry in fitness_registry[:40]:
            lines.append(
                f"| `{entry['id']}` | {entry['dimension']} | `{entry['gate']}` | `{entry['script']}` |"
            )
    if package_scripts:
        lines += ["", "## Package scripts", "", "| Package | Script | Invocation |", "|---|---|---|"]
        for item in package_scripts[:30]:
            lines.append(f"| `{item['package']}` | `{item['name']}` | `{' '.join(item['invocation'])}` |")
    if ci_commands:
        lines += [
            "", "## CI command evidence", "",
            f"{len(ci_commands)} `run`/`uses` entries detected. Review workflow/job semantics before treating them as gates.",
        ]
    if boundary or boundary_tests:
        lines += [
            "",
            "## Boundary-sensitive candidates (review, do not assume)",
            "",
            "These files look related to protocol/runtime/agent/tool/security boundaries. Use them as pointers for `BoundaryRobustness`, not as automatic classification.",
            "",
            "| Evidence | Sample |",
            "|---|---|",
            f"| Boundary implementation candidates | {fmt_paths(boundary)} |",
            f"| Boundary test candidates | {fmt_paths(boundary_tests)} |",
        ]
    if fitness or module_indexes or baselines:
        lines += [
            "",
            "## Governance maturity signals (review, do not assume)",
            "",
            "| Evidence | Sample |",
            "|---|---|",
            f"| Fitness/check scripts | {fmt_paths(fitness)} |",
            f"| Module index docs | {fmt_paths(module_indexes)} |",
            f"| Baseline / allowlist files | {fmt_paths(baselines)} |",
        ]
    if instr:
        lines += [
            "",
            "## Existing project rules — DOMAIN AUTHORITY (federate, do not overwrite)",
            "",
            "The project already keeps rule/instruction files. Treat them as the authority for project-specific domain semantics, owners, thresholds, and gates. The portable Skill owns claim, status, evidence, audit, authorization, and campaign meta-semantics. Link and gap-fill instead of copying rules; a conflict blocks the affected claim until it is reviewed.",
            "",
            "| File | Lines |",
            "|---|---|",
        ]
        for f in instr:
            lines.append(f"| `{f['path']}` | {f['lines']} |")
    rows = [(k, v) for k, v in evidence.items() if v]
    if rows:
        lines += ["", "## Other evidence groups", "", "| Group | Sample |", "|---|---|"]
        for k, v in rows:
            sample = ", ".join(f"`{p}`" for p in v[:5]) if v else "—"
            lines.append(f"| {k} | {sample} |")
    return "\n".join(lines)


def sec_owners(scan: dict) -> str:
    evidence = scan.get("evidence", {})
    source_samples = scan.get("production_source_samples", [])[:12]
    if not source_samples:
        language_samples = scan.get("language_file_samples", {})
        source_samples = [
            path
            for lang in sorted(language_samples)
            for path in language_samples.get(lang, [])[:3]
        ][:10]
    test_samples = scan.get("test_files_sample", [])[:10]
    docs = scan.get("docs_sample", [])[:10]
    ci = scan.get("ci_files", [])[:10]
    audit = scan.get("audit_samples", [])[:10]
    entry = scan.get("entry_samples", [])[:10]
    api_contracts = evidence.get("openapi", [])
    platform = evidence.get("docker", []) + evidence.get("kubernetes", [])
    release = evidence.get("release", [])
    security = evidence.get("security", [])
    # Each area maps to its OWN discriminative evidence. Where the static scan
    # has no signal, say so honestly instead of repeating the same source files
    # across rows (that would look evidence-backed but isn't).
    rows = [
        ("Domain identity / model", source_samples, "locate the core domain/model types"),
        ("Configuration", docs + ci + platform, "locate config files / env / IaC"),
        ("Policy / rules", security + docs, "locate the policy/rules engine + CODEOWNERS"),
        ("Audit / logs", audit, "locate logging / audit / telemetry code"),
        ("API / wire contract", api_contracts + source_samples, "locate openapi/proto/schema + handlers"),
        ("UI / product behavior", entry + test_samples, "locate UI entry points / views / e2e tests"),
        ("Platform / runtime I/O", platform, "locate docker / k8s / IaC + runtime adapters"),
        ("Release artifacts", release + ci, "locate the release / publish workflow"),
        ("Test harness", test_samples + ci, "locate test runners + CI"),
        ("Security / privacy / secrets", security + audit, "locate secret handling + security scans"),
    ]
    lines = [
        "# Owner Map (to build)",
        "",
        "Identify one semantic **owner** (team/domain preferred) for each area. Routes, controllers, UI, and daemon scripts are usually *adapters*, not owners — record them as such. The evidence below is a starting set from the static scan, not validated ownership.",
        "",
        "| Semantic area | Current evidence | Owner decision |",
        "|---|---|---|",
    ]
    for area, hits, hint in rows:
        cell = fmt_paths(hits) if hits else f"no static signal — {hint}"
        lines.append(f"| {area} | {cell} | TODO |")
    return "\n".join(lines)


def sec_rules_hard() -> str:
    return "\n".join([
        "# Hard Rules — gap-check, not a fabricated list",
        "",
        "Do **not** invent concrete rules here. For each standard category, answer three questions against the **project's existing rules** (read any AGENTS.md / `.claude`|`cursor`|`codex` rules / CONTRIBUTING first) and the catalog in the skill's `references/20-rule-catalog.md`:",
        "",
        "1. **Already enforced?** by what command/check, in which file?",
        "2. **Gap?** what is missing, advisory-only, or unowned?",
        "3. **If genuinely new:** state trigger · owner · required evidence · reject condition · verification — and only promote it from `memory.md` once it is grounded in a real code path + runnable check.",
        "",
        "An empty row is honest, not a hole. A rule written without a runnable check is a wish.",
        "",
        "| Category | Already enforced? (file / command) | Gap to close |",
        "|---|---|---|",
        "| Evidence integrity (completion / mergeability / release claims) | _check existing_ | _?_ |",
        "| Product/profile fit (acceptance uses the real stimulus) | _check existing_ | _?_ |",
        "| Architecture & owner boundaries (no silent adapter-owners) | _check existing_ | _?_ |",
        "| Module readiness / fitness functions (objective stability criteria) | _check existing_ | _?_ |",
        "| Interface / port contract (typed, consumer-driven public boundary) | _check existing_ | _?_ |",
        "| Documentation deliverables (live docs vs sync-later docs) | _check existing_ | _?_ |",
        "| Domain & parameter flow (no lossy type/name round-trips) | _check existing_ | _?_ |",
        "| Test truthfulness (mock/contract ≠ product acceptance) | _check existing_ | _?_ |",
        "| Policy source of truth (one owner, no parallel interpreters) | _check existing_ | _?_ |",
        "| Failure semantics (per-layer fail-open/closed, visible status) | _check existing_ | _?_ |",
        "| Security / privacy / secrets (no plaintext outside the runtime) | _check existing_ | _?_ |",
        "| Boundary robustness (weak hints, malformed input, isolation, pre-effect timing) | _check existing_ | _?_ |",
        "",
        "Supply-chain hard rules live in [supply-chain.md](../supply-chain.md) — load it when touching releases.",
    ])


def sec_rules_advisory() -> str:
    return "\n".join([
        "# Advisory Rules & Ratchet Plan — gap-check",
        "",
        "Same gap-check as hard rules, but these start **advisory** (inventory / warn only) and ratchet toward hard as automation matures. Each needs an owner + target date + deletion criterion, and must not *increase* measured debt beyond the current baseline.",
        "",
        "| Category | Already covered? | Ratchet plan |",
        "|---|---|---|",
        "| Code cleanliness / state ownership | _?_ | _?_ |",
        "| Runtime / protocol integrity (kernel/device/proxy/stream) | _?_ | _?_ |",
        "| Operations / version / coverage truth | _?_ | _?_ |",
        "| Fitness registry / orphan check cleanup | _?_ | _?_ |",
        "| Baseline cleanup debt (known violations visible, shrinking) | _?_ | _?_ |",
        "| Rule lifecycle (status, owner, harness, review date) | _?_ | _?_ |",
    ])


def sec_rules_candidates(scan: dict) -> str:
    candidates = candidate_rules(scan)
    lines = [
        "# Candidate Project-Specific Rules",
        "",
        "These are **drafts generated from repository evidence**. They are not hard rules and must not override existing project instructions. A maintainer should validate wording, owner, reject condition, and runnable verification before promoting any row to advisory, ratchet, or hard gate.",
        "",
    ]
    if not candidates:
        lines += [
            "_No strong candidate rules surfaced from the static scan. Add candidates here after real coding work reveals a repeated risk, owner decision, stale assumption, or missing harness._",
            "",
        ]
    else:
        lines += [
            "| Candidate | Family | Evidence | Confidence | Human validation |",
            "|---|---|---|---|---|",
        ]
        for c in candidates:
            lines.append(
                f"| {c['title']} | {c['family']} | {_evidence_cell(c.get('evidence', []))} | `{c['confidence']}` | required |"
            )
        lines += ["", "## Details", ""]
        for c in candidates:
            lines += [
                f"### {c['title']}",
                "",
                f"- Family: {c['family']}",
                f"- Confidence: `{c['confidence']}`",
                "- Human validation: required",
                f"- Candidate rule: {c['rule']}",
                f"- Evidence: {_evidence_cell(c.get('evidence', []), limit=8)}",
                f"- Reject if: {c['reject_if']}",
                f"- Verification gap: {c['verification_gap']}",
                "- Promotion path: `decisions.md` -> `memory.md` -> `rules/advisory.md` -> `rules/hard.md`",
                "",
            ]
    lines += [
        "## Promotion Checklist",
        "",
        "- The project profile and owner map are explicit.",
        "- Existing instruction files have been read and linked where authoritative.",
        "- The rule has a named owner and applies-when trigger.",
        "- The reject condition is concrete enough for review.",
        "- The verification command/check is real, or the gap is recorded as manual/blocked.",
        "- False-positive risk is acceptable for the proposed maturity level.",
    ]
    return "\n".join(lines)


def sec_cleanliness(scan: dict) -> str:
    cleanliness = scan.get("cleanliness_signals", {})
    neutral = cleanliness.get("neutral", {})
    lang_smells = cleanliness.get("language_smells", {})
    lines = [
        "### Language-neutral",
        "",
        "| Signal | Count |",
        "|---|---|",
    ]
    for key, label in [
        ("debt_markers", "Debt markers (TODO/FIXME/HACK/XXX)"),
        ("wrapper_markers", "Wrapper markers (compat/legacy/shim)"),
        ("mock_markers", "Mock markers"),
        ("policy_keyword_markers", "Policy keywords (allowlist/exclusion)"),
        ("secret_markers", "Secret keywords"),
        ("protocol_markers", "Protocol keywords"),
    ]:
        lines.append(f"| {label} | {neutral.get(key, 0)} |")
    lines += ["", "### Per-language smells (only languages present in the repo)", ""]
    if lang_smells:
        lines += ["| Language | Smell | Count |", "|---|---|---|"]
        for lang in sorted(lang_smells):
            for smell, count in sorted(lang_smells[lang].items()):
                lines.append(f"| {lang} | {smell} | {count} |")
    else:
        lines.append("_No recognized source languages with smell probes matched._")
    lines += [""]
    large_sample = ", ".join(
        f"`{item['path']}` ({item['lines']})" for item in cleanliness.get("large_files", [])[:5]
    )
    utility_sample = ", ".join(f"`{p}`" for p in cleanliness.get("utility_files", [])[:5])
    lines.append(f"| Large files (≥800 lines) | {large_sample or 'none sampled'} |")
    lines.append(f"| Utility/helper files | {utility_sample or 'none sampled'} |")
    return "\n".join(lines)


def sec_harness(scan: dict) -> str:
    targets = scan.get("build_targets", [])
    gate_inventory = scan.get("gate_inventory", [])
    boundary = scan.get("boundary_samples", [])
    boundary_tests = scan.get("boundary_test_samples", [])
    fitness = scan.get("fitness_samples", [])
    fitness_registry = scan.get("fitness_registry", [])
    module_indexes = scan.get("module_index_samples", [])
    baselines = scan.get("baseline_samples", [])
    lines = [
        "# Harness Matrix — map gates to the project's real commands",
        "",
        "Gates are tiered — do not collapse them: **PR** (fast) → **Closeout** (milestone) → **Product acceptance** (real stimulus) → **Release** (artifact integrity). For each gate, name the **actual command** the project already uses (see detected targets below) — not a generic guess. Ecosystem reference: the skill's `references/30-harness-catalog.md`.",
        "",
        "| Gate | Status | Real command (from the project) |",
        "|---|---|---|",
    ]
    gate_rows = (
        ("Format", {"format"}),
        ("Lint / static", {"lint_static"}),
        ("Unit / integration", {"unit_integration"}),
        ("Contract", {"contract"}),
        ("Security", {"security"}),
        ("Architecture drift", {"architecture"}),
        ("Code cleanliness", {"architecture", "lint_static"}),
        ("Policy source of truth", {"architecture"}),
        ("Module readiness", {"architecture"}),
        ("Fitness registry", {"architecture"}),
        ("Interface contract", {"contract", "architecture"}),
        ("Documentation deliverables", {"architecture"}),
        ("Failure semantics", {"unit_integration", "product_acceptance"}),
        ("Secret lifecycle", {"security"}),
        ("Runtime / protocol", {"operations", "product_acceptance"}),
        ("Boundary robustness", {"architecture", "product_acceptance"}),
        ("Version / coverage", {"coverage", "release"}),
        ("Product acceptance", {"product_acceptance"}),
        ("Release", {"release"}),
    )
    for label, categories in gate_rows:
        matches = [item for item in gate_inventory if categories.intersection(item.get("categories", []))]
        if matches:
            lines.append(f"| {label} | DETECTED_UNVERIFIED | {fmt_commands(matches)} |")
        else:
            lines.append(f"| {label} | TODO | _no repository-owned command detected_ |")
    if targets:
        lines += [
            "",
            "## Detected build / task targets",
            "",
            f"`{'`, `'.join(targets)}`",
            "",
            "_Prefer these over `infer from ecosystem`. If a gate has no target yet, that is a gap to create — record it, do not fake a command._",
        ]
    lines += [
        "",
        "## Test Basis / Scenario Origin",
        "",
        "Use this for any test cited in completion, closeout, product, or release claims. Tests without a basis can still be useful, but they should not become gates until their risk and evidence are explicit.",
        "",
        "```text",
        "TestGate:",
        "  product_or_requirement_ref:",
        "  risk_or_regression:",
        "  level: unit|integration|contract|static|real_stack|product_acceptance|release",
        "  size: small|medium|large|manual",
        "  runner:",
        "  scenario_origin: real_product|cli_equivalent|sensor_smoke|mock_contract",
        "  positive_cases:",
        "  negative_cases:",
        "  evidence_artifacts:",
        "  cleanup:",
        "  residual_risk:",
        "```",
        "",
        "Downgrade direct API calls, mock routes, synthetic events, and low-level sensor probes when they bypass the product path being claimed.",
        "",
        "## Module Readiness / Fitness Registry",
        "",
        "| Item | Project source | Status |",
        "|---|---|---|",
        f"| Fitness/check scripts registered with owner/gate/scope | {fmt_paths([entry.get('script', '') for entry in fitness_registry] or fitness)} | {'DETECTED_UNVERIFIED' if fitness_registry else 'TODO'} |",
        f"| Module readiness docs or indexes reviewed | {fmt_paths(module_indexes)} | TODO |",
        f"| Baseline/allowlist semantics audited | {fmt_paths(baselines)} | TODO |",
        "",
        "Readiness should be objective: owner, dependency direction, interface boundary, documentation, tests, error/panic policy, dead-code/wrapper policy, and size/complexity. Refactor requests should cite a violated rule or fitness function, not preference alone.",
        "",
        "Baseline/allowlist files should not silently turn detected debt into pass. Separate design-scope exemptions from cleanup debt; known violations need owner, review/delete path, and visible remaining count.",
        "",
        "## Interface Contract Harness",
        "",
        "Use this when changing public traits, ports, SDK/API contracts, cross-module signatures, or generated DTOs.",
        "",
        "```text",
        "InterfaceContract:",
        "  owner:",
        "  consumers:",
        "  methods_or_endpoints:",
        "  typed_inputs:",
        "  typed_outcomes:",
        "  typed_errors:",
        "  wire_domain_mapper:",
        "  sync_async_boundary:",
        "  compatibility_or_delete_by:",
        "  contract_tests:",
        "```",
        "",
        "## Documentation Deliverables",
        "",
        "Separate live source-of-truth docs that change atomically with code from longer-form docs updated at milestone/release sync. Module/API docs should name responsibility, public API, dependencies, modification risk, tests, and key decisions.",
    ]
    lines += [
        "",
        "## Boundary Robustness Harness",
        "",
        "Use this when touching protocol classifiers, streaming parsers, runtime observers, proxies, agent/tool bridges, kernel/user boundaries, policy classifiers, or security enforcement points. Map each item to real tests or mark the gap.",
        "",
        "| Check | Real test / command | Status |",
        "|---|---|---|",
        "| positive strong signal | TODO | TODO |",
        "| weak signal rejected | TODO | TODO |",
        "| non-target false positive case | TODO | TODO |",
        "| malformed / partial input degraded visibly | TODO | TODO |",
        "| cross-source isolation | TODO | TODO |",
        "| ID-domain separation | TODO | TODO |",
        "| effect target validation | TODO | TODO |",
        "| state precedence | TODO | TODO |",
        "| recovery after bad input | TODO | TODO |",
        "| pre-effect / commit-point assertion | TODO | TODO |",
    ]
    if boundary or boundary_tests:
        lines += [
            "",
            "### Boundary evidence candidates from scan",
            "",
            f"- Implementation candidates: {fmt_paths(boundary)}",
            f"- Test candidates: {fmt_paths(boundary_tests)}",
        ]
    return "\n".join(lines)


def sec_supply_chain() -> str:
    return "\n".join([
        "# Supply-Chain & Release Gates (draft)",
        "",
        "Calibrate against the approved **SLSA v1.2 Build and Source Tracks**. Provenance is worthless unless **verified at consumption/deploy** — producing it is not assurance.",
        "",
        "| Claim level | What it proves | What it does NOT |",
        "|---|---|---|",
        "| `dependency_scan_present` | no known CVE in the declared graph at scan time | trustworthiness, unknown vulns, transitive pinning |",
        "| `ci_supply_chain_gate_passed` | incoming dependencies scored | artifact trust |",
        "| `artifact_verifiable` | signed artifact + SBOM | build-path integrity |",
        "| `provenance_verified_at_deploy` | versioned SLSA Build provenance verified at deploy | absence of logic bugs |",
        "| `source_controls_verified` | versioned SLSA Source controls/attestations | build-system integrity |",
        "| `release_grade_supply_chain_assurance` | the full ladder above | — |",
        "",
        "**Produce:** Sigstore-signed build provenance (`gh attestation build`, npm `--provenance`, `cosign sign`).  ",
        "**Publish:** Trusted Publishing / OIDC — no long-lived registry tokens.  ",
        "**Verify at deploy:** `gh attestation verify` / `slsa-verifier` / OPA Gatekeeper for admitted images.  ",
        "**Gate incoming deps:** OpenSSF Scorecard / GitHub dependency-review.  ",
        "Reject any \"release-grade\" claim built on a dependency scan alone, or provenance that is produced but never verified.",
    ])


def sec_memory(scan: dict) -> str:
    evidence = scan.get("evidence", {})
    guardrails = evidence.get("guardrails", [])
    lines = [
        "# Project Memory",
        "",
        "Record durable, evidence-backed facts learned during coding work. Keep guesses in [decisions.md](decisions.md); keep rules in [rules/](rules/).",
        "",
        "## Fact Maturity",
        "",
        "| Status | Meaning | Next action |",
        "|---|---|---|",
        "| `observed_once` | seen in one task, path, PR, incident, or scan | wait for repeat evidence or owner confirmation |",
        "| `repeated` | seen across multiple changes or review findings | add owner, harness, or rule proposal |",
        "| `verified_by_tests` | backed by local/manual verification | make stable enough for CI |",
        "| `enforced_by_ci` | checked in normal development | promote related rule to ratchet or hard gate |",
        "| `hard_gate` | required for completion/merge/release claims | keep under stale-rule audit |",
        "| `stale` | path, command, owner, or assumption no longer matches reality | update, supersede, or delete |",
        "",
        "## Learned Facts",
        "",
        "| Fact | Evidence | Status | Applies when | Owner | Next action |",
        "|---|---|---|---|---|---|",
        "| Initial guardrails scaffold created | scan output + generated guardrails scaffold | `observed_once` | future guardrail updates | TODO | fill with task evidence after first real coding change |",
    ]
    if guardrails:
        lines.append(f"| Existing guardrails found | {fmt_paths(guardrails)} | `observed_once` | updating project rules | TODO | audit paths/commands before trusting them |")
    lines += [
        "",
        "## Task Closeout Learning Audit",
        "",
        "Before closing a meaningful coding task, decide whether it revealed a durable fact:",
        "",
        "- Which paths changed, and did they reveal a semantic owner?",
        "- Which command or harness actually proved the change?",
        "- Which acceptance surface was real product behavior vs mock/contract evidence?",
        "- Did the task touch a protocol/runtime/agent/tool/security boundary that needs BoundaryRobustness coverage?",
        "- Did a review comment, bug, CI failure, stale doc, or incident repeat?",
        "- Should a fact be added here, a hypothesis added to `decisions.md`, or a rule promoted/deleted?",
        "",
        "## Do Not Store",
        "",
        "- one-off command output;",
        "- temporary branch state;",
        "- guesses without code-path evidence;",
        "- old CI failures after the fix unless they define a recurring invariant.",
    ]
    return "\n".join(lines)


def sec_decisions(scan: dict) -> str:
    lines = ["# Unresolved Decisions", ""]
    qs = scan.get("guardrail_questions", [])
    if qs:
        lines += [f"- {q}" for q in qs]
    else:
        lines.append("- _(none surfaced by the scan; add the open product/owner/release questions here.)_")
    lines += [
        "",
        "## Next Actions",
        "",
        "1. Fill the owner map with code-path evidence.",
        "2. Validate or reject generated candidates in `rules/candidates.md`.",
        "3. Register active check scripts as fitness functions, or delete/orphan-label them.",
        "4. Audit baseline/allowlist files: design exemption or cleanup debt?",
        "5. Define module readiness only where the project has real module ownership boundaries.",
        "6. Downgrade impossible hard rules to advisory with target dates.",
        "7. Add static scripts for the highest-risk drift patterns.",
        "8. Run local gates, then check remote CI before any mergeability claim.",
        "9. Move durable learned facts into `memory.md`; keep unresolved hypotheses here.",
        "",
        "## Sources",
        "",
        "_List the code paths, CI files, and standards (SLSA, OWASP, …) each rule is anchored to. A rule without a source is a hypothesis._",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Assemblers
# --------------------------------------------------------------------------- #

def build_single(scan: dict) -> str:
    """Legacy monolithic doc — every section concatenated."""
    parts = [
        "# Project Guardrails Harness — Draft",
        "",
        sec_profile(scan),
        sec_owners(scan),
        "## Rules",
        "",
        sec_rules_hard(),
        "",
        sec_rules_candidates(scan),
        "",
        sec_rules_advisory(),
        "## Cleanliness Signals\n\n" + sec_cleanliness(scan),
        sec_harness(scan),
        sec_supply_chain(),
        sec_memory(scan),
        sec_decisions(scan),
    ]
    return "\n\n".join(p for p in parts if p != "")


def build_index(scan: dict) -> str:
    evidence = scan.get("evidence", {})
    languages = scan.get("languages", {})
    ci = scan.get("ci_files", [])
    instr = scan.get("instruction_files", [])
    root = scan.get("root", "")
    basename = Path(root).name or "project"
    lines = [f"# Project Guardrails — {basename}", ""]
    if instr:
        lines += [
            f"> ⚠ **{len(instr)} existing rule/instruction files detected** (AGENTS.md / `.claude`|`cursor`|`codex` rules / CONTRIBUTING …).",
            "> They own **project domain semantics**; the portable Skill owns claim/evidence meta-semantics. This `.guardrails/` set links and fills gaps instead of duplicating either owner. Conflicts block the affected claim. See *Existing project rules* in [profile.md](profile.md).",
            "",
        ]
    lines += [
        "> **Read this INDEX first; load other files just-in-time** by what the task touches:",
        "> - reviewing a PR → [`rules/hard.md`](rules/hard.md) + [`harness.md`](harness.md)",
        "> - drafting new project rules → [`rules/candidates.md`](rules/candidates.md) + [`decisions.md`](decisions.md)",
        "> - cutting a release → [`supply-chain.md`](supply-chain.md) + the release row of [`harness.md`](harness.md)",
        "> - an ownership question → [`owners.md`](owners.md)",
        "> - a refactor / cleanup → [`cleanliness.md`](cleanliness.md) + [`rules/advisory.md`](rules/advisory.md)",
        "> - learning from a coding task → [`memory.md`](memory.md) + [`decisions.md`](decisions.md)",
        "> A single monolithic file buries critical rules mid-document and re-costs tokens on every read; this split avoids that.",
        "",
        "## At a glance",
        f"- Languages: {', '.join(languages) or 'unknown'} · CI: {yes(ci)} · Tests sampled: {len(scan.get('test_files_sample', []))} · Release artifacts: {yes(evidence.get('release'))}",
        "- **Profile: classify yourself** from [profile.md](profile.md) (README excerpt + dependencies) — the scanner does not guess.",
        "",
        "## Non-negotiables (always hold)",
        "- **Evidence over claims** — no completion / mergeable / release-ready claim without code path + commit + CI/manual evidence.",
        "- **Ingest, don't overwrite** — if the project already states a rule, link it; never duplicate a fact that lives elsewhere.",
        "- **Candidate rules need validation** — generated project rules stay drafts until owner, reject condition, and runnable check are confirmed.",
        "- **Gate tests need basis/origin** — a gate test needs risk, level/size, runner, evidence, cleanup, and real vs shortcut stimulus classification.",
        "- **Fitness functions need ownership** — active check scripts should be registered, owned, invoked by real gates, or deleted.",
        "- **Baselines are not approval** — known violations remain cleanup debt unless they are true design-scope exemptions.",
        "- **Readiness beats preference** — force refactors by citing violated readiness criteria, rules, or fitness functions.",
        "- **Test truthfulness** — mock/contract tests ≠ product acceptance (unless contract-only product).",
        "- **Boundary robustness** — weak hints, malformed input, isolation, false positives/negatives, and pre-effect timing need explicit tests.",
        "- **Supply-chain honesty** — release-grade needs SBOM + signed provenance (SLSA L2/L3) + verify-at-deploy.",
        "",
        "## Files",
        "- [`profile.md`](profile.md) — evidence inventory + README/deps/targets + existing rules list",
        "- [`owners.md`](owners.md) — owner map (owners vs adapters)",
        "- [`rules/hard.md`](rules/hard.md) — hard-rule gap-check",
        "- [`rules/candidates.md`](rules/candidates.md) — evidence-backed project-specific draft rules",
        "- [`rules/advisory.md`](rules/advisory.md) — advisory + ratchet gap-check",
        "- [`cleanliness.md`](cleanliness.md) — debt / smell / large-file inventory (language-aware)",
        "- [`harness.md`](harness.md) — gate matrix → real commands",
        "- [`supply-chain.md`](supply-chain.md) — release / supply-chain gates",
        "- [`memory.md`](memory.md) — durable learned facts from coding work",
        "- [`decisions.md`](decisions.md) — unresolved decisions + migration plan + sources",
    ]
    return "\n".join(lines)


def build_multi(scan: dict) -> "dict[str, str]":
    """Progressive-disclosure file set. Order matters for stable output."""
    return {
        "INDEX.md": build_index(scan),
        "profile.md": sec_profile(scan),
        "owners.md": sec_owners(scan),
        "rules/hard.md": sec_rules_hard(),
        "rules/candidates.md": sec_rules_candidates(scan),
        "rules/advisory.md": sec_rules_advisory(),
        "cleanliness.md": "# Cleanliness Signals\n\n" + sec_cleanliness(scan),
        "harness.md": sec_harness(scan),
        "supply-chain.md": sec_supply_chain(),
        "memory.md": sec_memory(scan),
        "decisions.md": sec_decisions(scan),
    }


def write_multi(scan: dict, out_dir: str) -> list[str]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    files = build_multi(scan)
    written: list[str] = []
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content.rstrip() + "\n", encoding="utf-8")
        written.append(rel)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scan_json", help="JSON produced by scan_project.py")
    parser.add_argument("--out", help="legacy: write one combined guardrails.md to this path")
    parser.add_argument("--out-dir", help="preferred: write the progressive-disclosure file set to this directory")
    args = parser.parse_args()

    if not args.out and not args.out_dir:
        parser.error("specify --out (single file) or --out-dir (progressive-disclosure directory)")

    scan = json.loads(Path(args.scan_json).read_text(encoding="utf-8"))

    if args.out_dir:
        written = write_multi(scan, args.out_dir)
        print(f"wrote {len(written)} files to {args.out_dir}:")
        for rel in written:
            print(f"  - {rel}")
    else:
        text = build_single(scan) + "\n"
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote single doc to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
