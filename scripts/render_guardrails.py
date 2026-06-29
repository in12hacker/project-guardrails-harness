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


# --------------------------------------------------------------------------- #
# Section builders. Each returns a markdown string (no trailing newline).
# They are reused by both the single-file and the multi-file renderers so the
# two modes can never drift apart.
# --------------------------------------------------------------------------- #

def sec_profile(scan: dict) -> str:
    evidence = scan.get("evidence", {})
    languages = scan.get("languages", {})
    hints = scan.get("profile_hints", [])
    ci = scan.get("ci_files", [])
    profiles = scan.get("likely_profiles", [])
    lines = [
        "# Profile & Evidence Inventory",
        "",
        f"- Root: `{scan.get('root')}`",
        f"- Languages: {', '.join(languages) or 'unknown'}",
        f"- Likely profile: {', '.join(f'`{p}`' for p in profiles) or '`unknown` — classify manually before writing hard rules'}",
        f"- Profile hints: {', '.join(f'`{p}`' for p in hints) or 'none'}",
        f"- CI present: {yes(ci)}" + (f" (`{', '.join(ci[:5])}`)" if ci else ""),
        f"- Tests sampled: {len(scan.get('test_files_sample', []))}",
        f"- Docs sampled: {len(scan.get('docs_sample', []))}",
        f"- Release/build artifacts present: {yes(evidence.get('release'))}",
    ]
    rows = [(k, v) for k, v in evidence.items() if v]
    if rows:
        lines += ["", "## Evidence groups found", "", "| Group | Sample |", "|---|---|"]
        for k, v in rows:
            sample = ", ".join(f"`{p}`" for p in v[:5]) if v else "—"
            lines.append(f"| {k} | {sample} |")
    return "\n".join(lines)


def sec_owners(scan: dict) -> str:
    evidence = scan.get("evidence", {})
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


_HARD_RULES = [
    (
        "Evidence integrity",
        "Any completion, mergeability, release-readiness, or closeout claim",
        "Claim owner",
        "code paths + commit + local verification + remote CI or manual-runner evidence",
        "only documentation/status/assertion is cited, or skipped/manual checks are counted as pass",
        "EvidenceGate in harness.md",
    ),
    (
        "Product/profile fit",
        "Adding or changing product acceptance criteria",
        "Product owner",
        "explicit project profile + real acceptance surface",
        "a rule imports another paradigm's acceptance test",
        "Product acceptance row in harness.md",
    ),
    (
        "Architecture / owner",
        "Changing public contracts, domain concepts, or ownership boundaries",
        "Semantic owner",
        "owner map + checked consumers + code paths",
        "routes/controllers/UI/daemon scripts become silent owners",
        "static architecture check + owner review",
    ),
    (
        "Domain / parameter flow",
        "Passing cross-layer semantic values",
        "Domain owner",
        "ParameterFlow record + semantic regression tests",
        "type/name fidelity is lost outside a wire/storage boundary",
        "ParameterFlow regression harness",
    ),
    (
        "Test truthfulness",
        "Claiming behavior is accepted or complete",
        "Test harness owner",
        "test level + basis + real stimulus where required",
        "mock/contract tests are counted as product acceptance for non-contract products",
        "tiered TestGate in harness.md",
    ),
    (
        "Policy source of truth",
        "Changing rules, defaults, exclusions, or overrides",
        "Policy owner",
        "authoritative policy source + forbidden parallel interpreters",
        "adapter code reinterprets policy or hardcodes semantic defaults",
        "policy source-of-truth harness",
    ),
    (
        "Failure semantics",
        "Adding fallback, degraded mode, or resource-limit behavior",
        "Runtime owner",
        "per-layer fail-open/fail-closed matrix + visible status evidence",
        "a global default is used for unrelated layers",
        "FailureSemanticsGate",
    ),
    (
        "Security / privacy / secrets",
        "Handling plaintext secrets or sensitive data",
        "Security owner",
        "runtime boundary + negative persistence checks",
        "plaintext secrets persist in logs/files/fixtures/browser storage",
        "SecretLifecycleHarness",
    ),
]


def sec_rules_hard() -> str:
    lines = [
        "# Hard Rules (draft)",
        "",
        "Each hard rule needs: **trigger · owner · required evidence · reject condition · verification command/harness**. Put the most safety-critical REJECT conditions near the *top* of this file, not the middle — long files are recalled worst in the middle.",
        "",
        "| Category | Trigger | Owner | Required evidence | Reject if | Verify |",
        "|---|---|---|---|---|---|",
    ]
    lines += [f"| {c} | {t} | {o} | {e} | {r} | {v} |" for c, t, o, e, r, v in _HARD_RULES]
    lines += ["", "Supply-chain hard rules live in [supply-chain.md](../supply-chain.md) — load it when touching releases."]
    return "\n".join(lines)


_ADVISORY_RULES = [
    ("Code cleanliness / state ownership", "Utility/helper/compat paths, shared state, and constructors need an owner, scope, and a delete/review date."),
    ("Runtime / protocol integrity", "Kernel/device/proxy/browser/stream constraints need profile-specific harnesses (often manual signoff)."),
    ("Operations / version / coverage", "Runtime degraded states, version sync, log retention, and coverage exclusions need evidence and owners."),
    ("Rule lifecycle", "Every rule needs status, owner, harness, review/delete date, and a supersession path."),
]


def sec_rules_advisory() -> str:
    lines = [
        "# Advisory Rules & Ratchet Plan (draft)",
        "",
        "Advisory until a reliable automated check or explicit manual signoff exists. Ratchet toward hard over time — each one needs an **owner + target date + deletion criterion**, and must not *increase* measured debt beyond the current baseline.",
        "",
        "| Category | Candidate advisory rule |",
        "|---|---|",
    ]
    lines += [f"| {c} | {r} |" for c, r in _ADVISORY_RULES]
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


def sec_harness() -> str:
    rows = [
        ("Format", "infer from ecosystem"),
        ("Lint / static", "infer from ecosystem"),
        ("Unit", "infer from ecosystem"),
        ("Contract", "OpenAPI/protobuf/SDK check if present"),
        ("Security dependency", "cargo audit / npm audit / pip-audit / govulncheck / equivalent"),
        ("Architecture drift", "repo-specific rg/static scripts"),
        ("Code cleanliness", "large-file/helper/compat/ParameterFlow ratchet"),
        ("Policy source of truth", "hardcoded-default / parallel-interpreter scan + owner tests"),
        ("Failure semantics", "per-layer degraded / fallback / full-limit tests"),
        ("Secret lifecycle", "static leak scan + runtime no-plaintext-persistence tests"),
        ("Runtime / protocol", "profile-specific ABI / device / proxy / encoding / flush tests"),
        ("Version / coverage", "single version source + coverage exclusion inventory"),
        ("Product acceptance", "real product stimulus, not mock"),
        ("Release", "clean build + SBOM + provenance/signature (see supply-chain.md)"),
    ]
    lines = [
        "# Harness Matrix (draft)",
        "",
        "Gates are tiered — do not collapse them. **PR** (fast, new-regression prevention) → **Closeout** (milestone signoff) → **Product acceptance** (real stimulus) → **Release** (artifact integrity). For ecosystem-specific commands, see the skill's `references/30-harness-catalog.md`.",
        "",
        "| Gate | Status | Candidate command |",
        "|---|---|---|",
    ]
    lines += [f"| {g} | TODO | {c} |" for g, c in rows]
    return "\n".join(lines)


def sec_supply_chain() -> str:
    return "\n".join([
        "# Supply-Chain & Release Gates (draft)",
        "",
        "Calibrate against **SLSA v1.0 Build Track** (L1 provenance exists · L2 signed provenance from a hosted builder · L3 hardened/isolated builder). Provenance is worthless unless **verified at deploy** — producing it is not assurance.",
        "",
        "| Claim level | What it proves | What it does NOT |",
        "|---|---|---|",
        "| `dependency_scan_present` | no known CVE in the declared graph at scan time | trustworthiness, unknown vulns, transitive pinning |",
        "| `ci_supply_chain_gate_passed` | incoming dependencies scored | artifact trust |",
        "| `artifact_verifiable` | signed artifact + SBOM | build-path integrity |",
        "| `provenance_verified_at_deploy` | SLSA L2/L3 provenance AND verified at deploy | absence of logic bugs |",
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
        "2. Downgrade impossible hard rules to advisory with target dates.",
        "3. Add static scripts for the highest-risk drift patterns.",
        "4. Run local gates, then check remote CI before any mergeability claim.",
        "5. Move durable learned facts into `memory.md`; keep unresolved hypotheses here.",
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
        sec_rules_advisory(),
        "## Cleanliness Signals\n\n" + sec_cleanliness(scan),
        sec_harness(),
        sec_supply_chain(),
        sec_memory(scan),
        sec_decisions(scan),
    ]
    return "\n\n".join(p for p in parts if p != "")


def build_index(scan: dict) -> str:
    evidence = scan.get("evidence", {})
    languages = scan.get("languages", {})
    ci = scan.get("ci_files", [])
    profiles = scan.get("likely_profiles", [])
    hints = scan.get("profile_hints", [])
    root = scan.get("root", "")
    basename = Path(root).name or "project"
    lines = [
        f"# Project Guardrails — {basename}",
        "",
        "> **Read this INDEX first; load the other files just-in-time** by what the current task touches:",
        "> - reviewing a PR → [`rules/hard.md`](rules/hard.md) + [`harness.md`](harness.md)",
        "> - cutting a release → [`supply-chain.md`](supply-chain.md) + the release row of [`harness.md`](harness.md)",
        "> - an ownership question → [`owners.md`](owners.md)",
        "> - a refactor / cleanup → [`cleanliness.md`](cleanliness.md) + [`rules/advisory.md`](rules/advisory.md)",
        "> - learning from a coding task → [`memory.md`](memory.md) + [`decisions.md`](decisions.md)",
        "> A single monolithic guardrails file buries critical rules mid-document and re-costs tokens on every read; this split avoids that.",
        "",
        "## Profile (one-liner)",
        f"- Languages: {', '.join(languages) or 'unknown'} · Profile: {', '.join(f'`{p}`' for p in profiles) or '`unknown`'} · Hints: {', '.join(f'`{p}`' for p in hints) or 'none'}",
        f"- CI: {yes(ci)} · Tests sampled: {len(scan.get('test_files_sample', []))} · Release artifacts: {yes(evidence.get('release'))}",
        "",
        "## Hard-gate shortlist (non-negotiables)",
        "- **Evidence integrity** — completion claims need code path + commit + local + remote-CI/manual evidence.",
        "- **Owner boundary** — public contracts & domain concepts have one owner + checked consumers.",
        "- **Test truthfulness** — mock/contract tests ≠ product acceptance (unless contract-only product).",
        "- **Supply-chain honesty** — release-grade needs SBOM + signed provenance (SLSA L2/L3) + verify-at-deploy.",
        "",
        "## Files",
        "- [`profile.md`](profile.md) — full profile + evidence inventory",
        "- [`owners.md`](owners.md) — owner map (owners vs adapters)",
        "- [`rules/hard.md`](rules/hard.md) — hard gates (trigger/owner/evidence/reject/verify)",
        "- [`rules/advisory.md`](rules/advisory.md) — advisory rules + ratchet plan",
        "- [`cleanliness.md`](cleanliness.md) — debt / smell / large-file inventory (language-aware)",
        "- [`harness.md`](harness.md) — tiered gate matrix + commands",
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
        "rules/advisory.md": sec_rules_advisory(),
        "cleanliness.md": "# Cleanliness Signals\n\n" + sec_cleanliness(scan),
        "harness.md": sec_harness(),
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
