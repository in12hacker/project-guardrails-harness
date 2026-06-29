#!/usr/bin/env python3
"""Render a first-pass guardrails document from scan_project.py output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def yes(paths: list[str]) -> str:
    return "yes" if paths else "no"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scan_json", help="JSON produced by scan_project.py")
    parser.add_argument("--out", help="write Markdown to this path")
    args = parser.parse_args()

    scan = json.loads(Path(args.scan_json).read_text(encoding="utf-8"))
    evidence = scan.get("evidence", {})
    languages = scan.get("languages", {})

    lines: list[str] = []
    lines.append("# Project Guardrails Harness Draft")
    lines.append("")
    lines.append("## Evidence Inventory")
    lines.append("")
    lines.append(f"- Root: `{scan.get('root')}`")
    lines.append(f"- Languages: {', '.join(languages.keys()) or 'unknown'}")
    lines.append(f"- CI present: {yes(scan.get('ci_files', []))}")
    lines.append(f"- Tests sampled: {len(scan.get('test_files_sample', []))}")
    lines.append(f"- Docs sampled: {len(scan.get('docs_sample', []))}")
    cleanliness = scan.get("cleanliness_signals", {})
    neutral = cleanliness.get("neutral", {})
    lang_smells = cleanliness.get("language_smells", {})
    lines.append(f"- Large files sampled: {len(cleanliness.get('large_files', []))}")
    lines.append(f"- Utility/helper files sampled: {len(cleanliness.get('utility_files', []))}")
    lines.append("")
    lines.append("## Initial Project Profile")
    lines.append("")
    for profile in scan.get("likely_profiles", []):
        lines.append(f"- `{profile}`")
    if not scan.get("likely_profiles"):
        lines.append("- `unknown`: classify manually before writing hard rules")
    lines.append("")
    lines.append("## Owner Map To Build")
    lines.append("")
    lines.append("| Semantic area | Current evidence | Owner decision |")
    lines.append("|---|---|---|")
    for key in [
        "rust",
        "node",
        "python",
        "go",
        "java",
        "openapi",
        "docker",
        "kubernetes",
        "security",
        "release",
    ]:
        hits = evidence.get(key, [])
        sample = ", ".join(f"`{p}`" for p in hits[:5]) if hits else "not found"
        lines.append(f"| {key} | {sample} | TODO |")
    lines.append("")
    lines.append("## Rule Catalog Draft")
    lines.append("")
    lines.append("| Category | First candidate rule |")
    lines.append("|---|---|")
    lines.append("| Evidence integrity | Completion claims require code path + commit + local verification + remote CI or manual runner evidence. |")
    lines.append("| Product/profile fit | Acceptance must use the real product stimulus for this project type. |")
    lines.append("| Architecture/owner | Public contracts and domain concepts must have one owner and checked consumers. |")
    lines.append("| Domain/parameter flow | Cross-layer semantic values require ParameterFlow and must not lose type/name fidelity. |")
    lines.append("| Code cleanliness/state ownership | Utility/helper/compat paths, shared state, and constructors require owner, scope, and delete/review date. |")
    lines.append("| Test truthfulness | Mock/contract tests must not be counted as product acceptance unless the product profile is contract-only. |")
    lines.append("| Policy source of truth | Rules, defaults, exclusions, and overrides require one owner and no parallel adapter interpretation. |")
    lines.append("| Failure semantics | Fail-open/fail-closed/degraded behavior requires a per-layer matrix and visible status evidence. |")
    lines.append("| Security/privacy/secrets | Plaintext secrets must be bounded to approved runtime memory and absent from logs/files/fixtures/browser storage. |")
    lines.append("| Runtime/protocol integrity | Kernel/device/proxy/browser/stream constraints require profile-specific harnesses. |")
    lines.append("| Supply chain/release | Release-grade claims require SBOM + provenance + signed or verifiable artifacts. |")
    lines.append("| Operations/version/coverage | Runtime degraded states, version sync, log retention, and coverage exclusions need evidence. |")
    lines.append("| Rule lifecycle | Rules need status, owner, harness, review/delete date, and supersession path. |")
    lines.append("")
    lines.append("## Cleanliness Signals")
    lines.append("")
    lines.append("### Language-neutral")
    lines.append("")
    lines.append("| Signal | Count |")
    lines.append("|---|---|")
    for key, label in [
        ("debt_markers", "Debt markers (TODO/FIXME/HACK/XXX)"),
        ("wrapper_markers", "Wrapper markers (compat/legacy/shim)"),
        ("mock_markers", "Mock markers"),
        ("policy_keyword_markers", "Policy keywords (allowlist/exclusion)"),
        ("secret_markers", "Secret keywords"),
        ("protocol_markers", "Protocol keywords"),
    ]:
        lines.append(f"| {label} | {neutral.get(key, 0)} |")
    lines.append("")
    lines.append("### Per-language smells (only languages present in the repo)")
    lines.append("")
    if lang_smells:
        lines.append("| Language | Smell | Count |")
        lines.append("|---|---|---|")
        for lang in sorted(lang_smells):
            for smell, count in sorted(lang_smells[lang].items()):
                lines.append(f"| {lang} | {smell} | {count} |")
    else:
        lines.append("_No recognized source languages with smell probes matched._")
    lines.append("")
    large_sample = ", ".join(
        f"`{item['path']}` ({item['lines']})"
        for item in cleanliness.get("large_files", [])[:5]
    )
    utility_sample = ", ".join(f"`{p}`" for p in cleanliness.get("utility_files", [])[:5])
    lines.append(f"| Large files | {large_sample or 'none sampled'} |")
    lines.append(f"| Utility/helper files | {utility_sample or 'none sampled'} |")
    lines.append("")
    lines.append("## Harness Matrix Draft")
    lines.append("")
    lines.append("| Gate | Status | Candidate command |")
    lines.append("|---|---|---|")
    lines.append("| Format | TODO | infer from ecosystem |")
    lines.append("| Lint/static | TODO | infer from ecosystem |")
    lines.append("| Unit | TODO | infer from ecosystem |")
    lines.append("| Contract | TODO | OpenAPI/protobuf/SDK check if present |")
    lines.append("| Security dependency | TODO | cargo audit / npm audit / pip-audit / govulncheck / equivalent |")
    lines.append("| Architecture drift | TODO | repo-specific rg/static scripts |")
    lines.append("| Code cleanliness | TODO | large-file/helper/compat/ParameterFlow ratchet |")
    lines.append("| Policy source of truth | TODO | hardcoded default/parallel interpreter scan + owner tests |")
    lines.append("| Failure semantics | TODO | per-layer degraded/fallback/full-limit tests |")
    lines.append("| Secret lifecycle | TODO | static leak scan + runtime no-plaintext persistence tests |")
    lines.append("| Runtime/protocol | TODO | profile-specific ABI/device/proxy/encoding/flush tests |")
    lines.append("| Version/coverage | TODO | single version source + coverage exclusion inventory |")
    lines.append("| Product acceptance | TODO | real product stimulus, not mock |")
    lines.append("| Release | TODO | clean build + SBOM + provenance/signature |")
    lines.append("")
    lines.append("## Unresolved Decisions")
    lines.append("")
    for question in scan.get("guardrail_questions", []):
        lines.append(f"- {question}")
    lines.append("")
    lines.append("## Next Actions")
    lines.append("")
    lines.append("1. Fill owner map with code-path evidence.")
    lines.append("2. Downgrade impossible hard rules to advisory with target dates.")
    lines.append("3. Add static scripts for the highest-risk drift patterns.")
    lines.append("4. Run local gates, then check remote CI before mergeability claims.")

    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
