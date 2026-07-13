#!/usr/bin/env python3
"""Initialize an executable project quality framework from explicit choices."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from quality_common import MATURITY_LEVELS, build_traceability_graph, write_json_yaml


QUALITY_DIMENSIONS = [
    "functional_suitability", "performance_efficiency", "compatibility",
    "interaction_capability", "reliability", "security", "maintainability",
    "flexibility", "safety",
]

CHECKOUT_V7_SHA = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"


def recommended_gate_commands(scan: dict) -> list[list[str]]:
    targets = set(scan.get("build_targets", []))
    if "gate" in targets:
        return [["make", "gate"]]
    languages = set(scan.get("languages", {}))
    commands: list[list[str]] = []
    if "rust" in languages:
        commands.extend([
            ["cargo", "fmt", "--all", "--", "--check"],
            ["cargo", "clippy", "--workspace", "--all-targets", "--all-features", "--", "-D", "warnings"],
            ["cargo", "test", "--workspace"],
        ])
    if "go" in languages:
        commands.extend([["go", "vet", "./..."], ["go", "test", "./..."]])
    if "python" in languages and scan.get("test_files_sample"):
        commands.append(["python3", "-m", "pytest"])
    package_scripts = {item.get("name") for item in scan.get("package_scripts", [])}
    for name in ("lint", "typecheck", "test", "build"):
        if name in package_scripts:
            commands.append(["npm", "run", name])
    evidence = scan.get("evidence", {})
    if "java" in languages:
        if evidence.get("gradle_wrapper"):
            commands.append(["./gradlew", "check"])
        elif evidence.get("maven_wrapper"):
            commands.append(["./mvnw", "verify"])
    if "c_cpp" in languages and evidence.get("cmake"):
        commands.extend([
            ["cmake", "-S", ".", "-B", "build"],
            ["cmake", "--build", "build"],
            ["ctest", "--test-dir", "build", "--output-on-failure"],
        ])
    unique: list[list[str]] = []
    for command in commands:
        if command not in unique:
            unique.append(command)
    return unique


def scaffold_engineering(root: Path, out_dir: Path, commands: list[list[str]]) -> str | None:
    if not commands:
        print("no evidence-backed commands found; engineering scaffold remains TODO")
        return None
    runner = out_dir / "run-quality-gates.py"
    source = f'''#!/usr/bin/env python3
"""Generated project quality entry point. Edit commands through reviewed project changes."""

import subprocess
import sys

COMMANDS = {json.dumps(commands, indent=2)}

for command in COMMANDS:
    print("+", " ".join(command), flush=True)
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
raise SystemExit(0)
'''
    runner.write_text(source, encoding="utf-8")
    runner.chmod(0o755)

    workflow = root / ".github" / "workflows" / "quality-framework.yml"
    if not workflow.exists():
        workflow.parent.mkdir(parents=True, exist_ok=True)
        relative_runner = runner.relative_to(root).as_posix()
        workflow.write_text(
            "name: Quality Framework\n"
            "on:\n  pull_request:\n  push:\n    branches: [main]\n"
            "permissions:\n  contents: read\n"
            "jobs:\n  quality:\n    runs-on: ubuntu-latest\n    steps:\n"
            f"      - uses: actions/checkout@{CHECKOUT_V7_SHA} # v7.0.0\n"
            "        with:\n          persist-credentials: false\n"
            f"      - run: python3 {relative_runner}\n",
            encoding="utf-8",
        )
    else:
        print(f"kept existing CI workflow; wire {runner} into project CI manually")
    return runner.relative_to(root).as_posix()


def control(
    control_id: str,
    title: str,
    dimension: str,
    requirement: str,
    risk: str,
    maturity: str,
    execution: dict,
    evidence: list[str],
    *,
    owner: str = "quality",
    scope: list[str] | None = None,
    standard: str = "project-guardrails-harness",
    version: str = "1.0",
) -> dict:
    return {
        "id": control_id,
        "control_revision": "1",
        "rule_refs": [],
        "title": title,
        "dimension": dimension,
        "source_standard": standard,
        "source_version": version,
        "project_requirement": requirement,
        "requirement_ids": [f"REQ.{control_id}"],
        "risk": risk,
        "risk_ids": [f"RISK.{control_id}"],
        "owner": owner,
        "applies": True,
        "applicability_rationale": "Selected by explicit project profile or repository evidence.",
        "required_from_maturity": maturity,
        "scope": scope or ["."],
        "evaluation_mode": "absolute",
        "required_capability_refs": [],
        "execution": execution,
        "evidence_required": evidence,
        "verification_ids": [f"VERIFY.{control_id}"],
    }


def command_control(control_id: str, title: str, dimension: str, requirement: str,
                    risk: str, maturity: str, argv: list[str]) -> dict:
    return control(
        control_id, title, dimension, requirement, risk, maturity,
        {"type": "command", "command": argv, "cwd": ".", "timeout_seconds": 3600,
         "authorization_required": False},
        ["exit code", "command output digest", "repository commit"],
    )


def manual_control(control_id: str, title: str, dimension: str, requirement: str,
                   risk: str, maturity: str, *, owner: str = "quality") -> dict:
    return control(
        control_id, title, dimension, requirement, risk, maturity,
        {"type": "manual", "authorization_required": False},
        ["named owner", "reviewed evidence reference", "review timestamp"],
        owner=owner,
    )


def starter_controls(scan: dict, args: argparse.Namespace) -> list[dict]:
    targets = set(scan.get("build_targets", []))
    evidence = scan.get("evidence", {})
    languages = set(scan.get("languages", {}))
    controls = [
        control(
            "QF.FRAMEWORK.MANIFEST", "Quality profile decisions are complete",
            "framework_governance", "Project profile, market, scope, maturity, and authority are explicit.",
            "Quality could be assessed against an inferred or incomplete scope.", "prototype",
            {"type": "file_exists", "path": ".guardrails/quality-manifest.yaml", "authorization_required": False},
            ["current quality manifest"], scope=[".guardrails/quality-manifest.yaml"],
        ),
        control(
            "QF.FRAMEWORK.REGISTRY", "Control registry exists",
            "framework_governance", "Applicable project controls have one machine-readable source of truth.",
            "Rules can drift across prose, scripts, and CI.", "prototype",
            {"type": "file_exists", "path": ".guardrails/control-registry.yaml", "authorization_required": False},
            ["current control registry"], scope=[".guardrails/control-registry.yaml"],
        ),
        manual_control(
            "QF.REQUIREMENTS.ACCEPTANCE", "Business requirements have measurable acceptance",
            "functional_suitability", "Every in-scope business requirement has an owner and measurable outcome.",
            "Implementation can be complete while the intended business outcome is undefined.",
            "engineering_ready", owner="product",
        ),
        manual_control(
            "QF.RISK.REGISTRY", "Delivery and abuse risks are assessed", "risk_management",
            "Requirements and architecture changes map to current delivery, security, privacy, safety, and operational risks.",
            "Controls can omit important failure and abuse cases.", "engineering_ready", owner="risk",
        ),
        manual_control(
            "QF.TRACEABILITY", "Requirements are traceable to delivery evidence", "traceability",
            "Every business requirement maps to risk, owner/decision, control, test, and delivery evidence.",
            "Features can appear complete without proving business or safety outcomes.", "engineering_ready",
        ),
        manual_control(
            "QF.OWNERSHIP", "Semantic and operational owners are explicit", "ownership",
            "Domain, interface, test, release, security, and operations responsibilities have owners.",
            "Unowned failures and decisions cannot be resolved reliably.", "engineering_ready",
        ),
        manual_control(
            "QF.ARCHITECTURE.DECISIONS", "Material architecture decisions are controlled",
            "maintainability", "Material decisions record context, alternatives, owner, consequences, and fitness checks.",
            "Architecture can drift without a reviewable reason or executable invariant.",
            "engineering_ready", owner="architecture",
        ),
        manual_control(
            "QF.PRODUCT.ACCEPTANCE", "Real product acceptance is defined", "product_acceptance",
            "Acceptance uses the real user/operator stimulus and visible outcome.",
            "Lower-level tests can produce false confidence about the product.", "production_ready",
            owner="product",
        ),
        manual_control(
            "QF.OPERATIONS.SLO", "SLIs, SLOs, and error-budget policy are verified", "reliability",
            "User-relevant service or runtime outcomes have owned objectives and breach actions.",
            "Reliability can degrade without an objective operating boundary.", "production_ready", owner="operations",
        ),
        manual_control(
            "QF.OPERATIONS.CAPACITY", "Capacity and performance limits are verified", "performance_efficiency",
            "Expected load, resource, latency, throughput, and cost boundaries are measured.",
            "The product can fail under realistic demand despite functional tests.", "production_ready", owner="operations",
        ),
        manual_control(
            "QF.OPERATIONS.OBSERVABILITY", "Observability and actionable alerts are verified", "reliability",
            "Logs, metrics, traces, dashboards, health signals, and alerts expose actionable degraded states without leaking secrets.",
            "Operators can miss or misdiagnose production failure.", "production_ready", owner="operations",
        ),
        manual_control(
            "QF.OPERATIONS.RECOVERY", "Backup, restore, and disaster recovery are exercised", "reliability",
            "Applicable state has tested backup, restore, retention, RTO, and RPO behavior.",
            "Configured backups may be unusable during recovery.", "production_ready", owner="operations",
        ),
        manual_control(
            "QF.OPERATIONS.CHANGE", "Deployment, migration, and rollback are exercised", "reliability",
            "Deployment and data/schema changes have compatibility, rollback, and failed-change evidence.",
            "A release can leave users or data in an unrecoverable state.", "production_ready", owner="release",
        ),
        manual_control(
            "QF.OPERATIONS.INCIDENT", "Incident response and learning are exercised", "operations",
            "Detection, escalation, containment, communication, recovery, and corrective-control feedback are rehearsed.",
            "The project cannot respond consistently to escaped failures.", "production_ready", owner="operations",
        ),
        manual_control(
            "QF.SECURITY.VULNERABILITY", "Vulnerability prevention and response are verified", "security",
            "Threat modeling, vulnerability intake, remediation targets, disclosure, updates, and recurrence prevention are controlled.",
            "Security defects can remain unknown, unowned, or repeatedly escape.", "production_ready", owner="security",
        ),
        manual_control(
            "QF.OPERATIONS.DORA", "Delivery performance feedback is measured", "operations",
            "Applicable deployment flow tracks DORA delivery and instability trends with owner-selected targets.",
            "Delivery throughput and instability cannot drive quality improvement.", "production_ready", owner="operations",
        ),
        manual_control(
            "QF.EXPERIENCE.USABILITY", "Critical user journeys meet usability acceptance", "interaction_capability",
            "Representative users can complete critical journeys with safe defaults and actionable errors.",
            "A functionally correct product can remain commercially unusable.", "commercial_ready", owner="product",
        ),
        manual_control(
            "QF.EXPERIENCE.ACCESSIBILITY", "Accessibility target is verified", "interaction_capability",
            "Applicable interfaces meet the explicitly selected WCAG target with automated and human evidence.",
            "Users with disabilities can be excluded from critical workflows.", "commercial_ready", owner="product",
        ),
        manual_control(
            "QF.EXPERIENCE.I18N", "Locale and fallback behavior are verified", "interaction_capability",
            "Selected locales, formats, text expansion, encoding, and fallback behavior are tested.",
            "Target-market users can receive broken or misleading interfaces.", "commercial_ready", owner="product",
        ),
        manual_control(
            "QF.LIFECYCLE.INSTALL", "Installation and first-run are verified", "flexibility",
            "Supported environments can install, configure, diagnose, and start the product from released artifacts.",
            "Customers can receive an artifact they cannot deploy or operate.", "commercial_ready", owner="release",
        ),
        manual_control(
            "QF.LIFECYCLE.UPGRADE", "Upgrade and compatibility are verified", "compatibility",
            "Supported upgrade paths preserve configuration, contracts, and data with documented compatibility.",
            "Updates can break customers or strand state.", "commercial_ready", owner="release",
        ),
        manual_control(
            "QF.LIFECYCLE.UNINSTALL", "Uninstall and data disposition are verified", "flexibility",
            "Removal behavior, retained data, credentials, rollback, and customer obligations are explicit and tested.",
            "Uninstall can leak data, credentials, or unusable residual state.", "commercial_ready", owner="release",
        ),
        manual_control(
            "QF.PRIVACY.GOVERNANCE", "Privacy and data lifecycle are verified", "security",
            "Data classification, minimization, consent/legal basis, retention, export, deletion, and redaction match the selected market.",
            "The product can mishandle customer or personal data.", "commercial_ready", owner="privacy",
        ),
        manual_control(
            "QF.COMMERCIAL.LEGAL", "Legal and distribution obligations are confirmed", "commercial_delivery",
            "Selected markets, licenses, notices, contracts, and regulatory overlays have owner-approved applicability and evidence.",
            "A technically complete product may be unlawful or undistributable.", "commercial_ready", owner="legal",
        ),
        manual_control(
            "QF.COMMERCIAL.SUPPORT", "Support, maintenance, and end-of-life are defined", "commercial_delivery",
            "Support channels, service expectations, update policy, maintenance period, and end-of-life process are published.",
            "Customers can depend on a product with no operable support lifecycle.", "commercial_ready", owner="product",
        ),
        manual_control(
            "QF.RELEASE.ARTIFACT", "Release artifact identity and verification are complete", "supply_chain",
            "Released artifacts bind version, source, SBOM, checksums/signatures, provenance, retention, and consumption verification.",
            "Consumers cannot establish what was built or whether it is authentic.", "commercial_ready", owner="release",
        ),
    ]
    if scan.get("ci_files"):
        controls.append(control(
            "QF.CI.REMOTE", "Remote CI checks pass for the assessed commit",
            "generic_quality", "Remote check runs exist and are complete and successful for the assessed commit.",
            "Local evidence alone cannot establish remote merge or integration status.",
            "engineering_ready",
            {
                "type": "remote",
                "command": [
                    "gh", "api", "repos/{owner}/{repo}/commits/{commit}/check-runs",
                    "--jq",
                    "if (.total_count > 0 and ([.check_runs[] | select(.status != \"completed\" or .conclusion != \"success\")] | length == 0)) then empty else error(\"required check runs are incomplete or unsuccessful\") end",
                ],
                "cwd": ".",
                "timeout_seconds": 120,
                "authorization_required": True,
            },
            ["remote check-run results", "assessed repository commit", "GitHub API response digest"],
            owner="quality",
        ))
    if getattr(args, "scaffold_runner", None) and "gate" not in targets:
        controls.append(command_control(
            "QF.GATE.SCAFFOLD", "Generated cross-ecosystem quality gate",
            "generic_quality", "The explicitly scaffolded project quality entry point passes.",
            "The recommended engineering skeleton can drift or fail silently.",
            "engineering_ready", ["python3", args.scaffold_runner],
        ))

    target_map = [
        ("gate", "QF.GATE.PR", "PR quality gate", "engineering_ready", "quality_gate"),
        ("gate-fitness", "QF.GATE.FITNESS", "Architecture fitness gate", "engineering_ready", "architecture"),
        ("coverage-gate", "QF.GATE.COVERAGE", "Coverage gate", "engineering_ready", "test"),
        ("gate-full", "QF.GATE.CLOSEOUT", "Closeout quality gate", "production_ready", "quality_gate"),
        ("dast-gate", "QF.GATE.DAST", "Dynamic security gate", "production_ready", "security"),
        ("test-real-stack-full", "QF.GATE.PRODUCT", "Real-stack product acceptance", "production_ready", "product_acceptance"),
        ("supply-chain-gate", "QF.GATE.SUPPLY", "Supply-chain gate", "commercial_ready", "supply_chain"),
        ("verify-release", "QF.GATE.RELEASE", "Release artifact verification", "commercial_ready", "release"),
        ("verify-reproducible", "QF.GATE.REPRODUCIBLE", "Reproducible build verification", "commercial_ready", "release"),
    ]
    for target, control_id, title, maturity, dimension in target_map:
        if target in targets:
            controls.append(command_control(
                control_id, title, dimension,
                f"The repository-owned `{target}` command passes for the assessed revision.",
                f"The project declares a {title.lower()} but does not prove it.", maturity,
                ["make", target],
            ))

    if "gate" not in targets:
        if "rust" in languages:
            controls.extend([
                command_control("QF.RUST.FMT", "Rust formatting", "generic_quality",
                                "Rust formatting passes.", "Formatting drift reduces review quality.",
                                "engineering_ready", ["cargo", "fmt", "--all", "--", "--check"]),
                command_control("QF.RUST.TEST", "Rust tests", "test",
                                "Rust tests pass.", "Behavior can regress without an executable test gate.",
                                "engineering_ready", ["cargo", "test", "--workspace"]),
            ])
        if "go" in languages:
            controls.append(command_control("QF.GO.TEST", "Go tests", "test", "Go tests pass.",
                                            "Behavior can regress without an executable test gate.",
                                            "engineering_ready", ["go", "test", "./..."]))
        if "python" in languages and scan.get("test_files_sample"):
            controls.append(command_control("QF.PYTHON.TEST", "Python tests", "test", "Python tests pass.",
                                            "Behavior can regress without an executable test gate.",
                                            "engineering_ready", ["python3", "-m", "pytest"]))
        if ("typescript" in languages or "javascript" in languages) and evidence.get("node"):
            controls.append(manual_control(
                "QF.NODE.GATE", "Node/TypeScript project gate is selected", "test",
                "The project selects and records its repository-owned npm/pnpm/yarn quality command.",
                "Automatically guessing a package script can execute the wrong workflow.", "engineering_ready",
            ))
        if "java" in languages:
            controls.append(manual_control(
                "QF.JAVA.GATE", "Java project gate is selected", "test",
                "The project selects its Maven or Gradle wrapper quality command.",
                "Build-tool assumptions can make a generated gate false or unsafe.", "engineering_ready",
            ))
        if "c_cpp" in languages:
            controls.append(manual_control(
                "QF.CPP.GATE", "C/C++ project gate is selected", "test",
                "The project selects its actual configure/build/test command and sanitizer profile.",
                "C/C++ build layouts and safety requirements cannot be inferred from extensions alone.",
                "engineering_ready",
            ))

    if args.distribution_model == "open_source":
        for path, control_id, title, maturity in (
            ("LICENSE", "QF.OSPS.LICENSE", "Source license is published", "engineering_ready"),
            ("SECURITY.md", "QF.OSPS.SECURITY", "Security contact and disclosure policy exist", "commercial_ready"),
            ("CONTRIBUTING.md", "QF.OSPS.CONTRIBUTING", "Contribution process is documented", "commercial_ready"),
        ):
            controls.append(control(
                control_id, title, "open_source_governance", f"{path} exists in the repository.",
                f"Open-source users or contributors lack required project governance information.", maturity,
                {"type": "file_exists", "path": path, "authorization_required": False},
                [f"repository file {path}"], standard="OSPS Baseline", version="2026.02.19", scope=[path],
            ))

    if args.ai_system:
        controls.extend([
            manual_control(
                "QF.AI.INTENDED_USE", "AI intended and prohibited uses are controlled", "ai_assurance",
                "AI capabilities, limitations, affected users, prohibited uses, and impact tiers are explicit.",
                "The system can be deployed outside its evaluated and governed purpose.",
                "engineering_ready", owner="ai_assurance",
            ),
            manual_control(
                "QF.AI.EVALUATION", "AI system evaluations are reproducible and representative", "ai_assurance",
                "Versioned model, prompt, data, tool, and end-to-end evaluations cover representative and edge scenarios.",
                "Aggregate model scores can hide product-level regressions or untested populations.",
                "production_ready", owner="ai_assurance",
            ),
            manual_control(
                "QF.AI.ABUSE", "AI misuse and adversarial boundaries are verified", "ai_assurance",
                "Prompt injection, data leakage, unsafe content, tool abuse, privilege escalation, and denial scenarios are tested.",
                "AI-specific attacks can bypass ordinary application controls.",
                "production_ready", owner="security",
            ),
            manual_control(
                "QF.AI.OVERSIGHT", "Human oversight and recourse are verified", "ai_assurance",
                "High-impact actions require appropriate approval, transparency, contestability, and safe fallback.",
                "Users can be harmed by opaque or irreversible automated decisions.",
                "production_ready", owner="product",
            ),
            manual_control(
                "QF.AI.MONITORING", "AI drift, incidents, and shutdown are controlled", "ai_assurance",
                "Production monitoring triggers re-evaluation, rollback or kill switch, incident response, and user communication.",
                "Model, data, prompt, or environment drift can silently invalidate assurance.",
                "production_ready", owner="operations",
            ),
        ])
    return controls


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out-dir", default=".guardrails")
    parser.add_argument("--scan")
    parser.add_argument("--project-name")
    parser.add_argument("--development-mode", required=True,
                        choices=("ai_greenfield", "ai_brownfield", "human_greenfield", "human_brownfield"))
    parser.add_argument("--target-maturity", required=True, choices=MATURITY_LEVELS)
    parser.add_argument("--product-type", action="append", required=True)
    parser.add_argument("--distribution-model", required=True,
                        choices=("open_source", "private_commercial", "saas", "client_software", "embedded", "mixed"))
    parser.add_argument("--market", action="append", required=True)
    parser.add_argument("--criticality", required=True, choices=("low", "medium", "high", "critical"))
    parser.add_argument("--data-sensitivity", required=True,
                        choices=("public", "internal", "confidential", "restricted", "regulated"))
    parser.add_argument("--deployment-model", action="append", required=True)
    parser.add_argument("--support-model", required=True,
                        choices=("community", "best_effort", "contracted", "managed", "none"))
    parser.add_argument("--primary-user", action="append", required=True)
    ai_group = parser.add_mutually_exclusive_group(required=True)
    ai_group.add_argument("--ai-system", action="store_true")
    ai_group.add_argument("--no-ai-system", action="store_false", dest="ai_system")
    parser.add_argument("--scope-mode", choices=("full_repo", "subproject"), required=True)
    parser.add_argument("--include", action="append")
    parser.add_argument("--exclude", action="append")
    parser.add_argument("--legal-profile", action="append", required=True,
                        help="explicit legal/regulatory applicability; use none_identified only after review")
    parser.add_argument("--scaffold-engineering", action="store_true",
                        help="create an evidence-backed local gate and non-overwriting GitHub CI entry point")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    out_dir = (root / args.out_dir).resolve() if not Path(args.out_dir).is_absolute() else Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        print(f"refusing to overwrite non-empty {out_dir}; use --force after review", file=sys.stderr)
        return 2

    script_dir = Path(__file__).resolve().parent
    if args.scan:
        scan_path = Path(args.scan).resolve()
    else:
        temp = tempfile.NamedTemporaryFile(prefix="guardrails-scan-", suffix=".json", delete=False)
        temp.close()
        scan_path = Path(temp.name)
        result = subprocess.run(
            [sys.executable, str(script_dir / "scan_project.py"), "--root", str(root), "--out", str(scan_path)],
            check=False,
        )
        if result.returncode != 0:
            return result.returncode
    scan = json.loads(scan_path.read_text(encoding="utf-8"))

    out_dir.mkdir(parents=True, exist_ok=True)
    render = subprocess.run(
        [sys.executable, str(script_dir / "render_guardrails.py"), str(scan_path), "--out-dir", str(out_dir)],
        check=False,
    )
    if render.returncode != 0:
        return render.returncode

    args.scaffold_runner = None
    if args.scaffold_engineering:
        try:
            out_dir.relative_to(root)
        except ValueError:
            print("engineering scaffolding requires --out-dir inside the project root", file=sys.stderr)
            return 2
        args.scaffold_runner = scaffold_engineering(
            root, out_dir, recommended_gate_commands(scan),
        )

    required_audits = ["self", "cross", "release_authority"]
    if args.target_maturity == "regulated_ready":
        required_audits.append("third_party")
    scope_mode = args.scope_mode
    manifest = {
        "schema_version": "2.0",
        "project": {
            "name": args.project_name or root.name,
            "root": str(root),
            "development_mode": args.development_mode,
            "target_maturity": args.target_maturity,
        },
        "profile": {
            "product_types": args.product_type,
            "distribution_model": args.distribution_model,
            "target_markets": args.market,
            "criticality": args.criticality,
            "data_sensitivity": args.data_sensitivity,
            "deployment_models": args.deployment_model,
            "support_model": args.support_model,
            "primary_users": args.primary_user,
            "ai_system": args.ai_system,
            "legal_profiles": args.legal_profile,
            "quality_dimensions": QUALITY_DIMENSIONS,
        },
        "scope": {
            "mode": scope_mode,
            "included_paths": args.include or (["."] if scope_mode == "full_repo" else []),
            "excluded_paths": args.exclude or [],
            "unassessed_dependencies": [],
            "overall_project_claim_allowed": scope_mode == "full_repo",
        },
        "authority": {
            "local_unprivileged_controls": True,
            "separate_authorization_required": [
                "dependency_install", "paid_service", "secrets", "remote_mutation",
                "production_mutation", "privileged_execution",
            ],
        },
        "audit_policy": {
            "required_stages": required_audits,
            "independent_actors": True,
        },
        "development_policy": {
            "active_campaign": None,
        },
        "claim_policies": {
            "task": {"required_stages": ["self", "cross"]},
            "phase": {"required_stages": ["self", "cross"]},
            "project": {"required_stages": required_audits},
            "release": {"required_stages": required_audits},
        },
    }
    write_json_yaml(out_dir / "quality-manifest.yaml", manifest)
    registry = {
        "schema_version": "2.0",
        "controls": starter_controls(scan, args),
        "capabilities": [],
        "baselines": [],
        "cleanup_debts": [],
        "design_scope_exemptions": [],
        "federated_rule_mappings": [],
    }
    write_json_yaml(out_dir / "control-registry.yaml", registry)
    write_json_yaml(
        out_dir / "evidence-ledger.json",
        {"schema_version": "2.0", "runs": [], "audits": [], "claims": []},
    )
    write_json_yaml(out_dir / "traceability-graph.json", build_traceability_graph(registry))
    print(f"initialized executable quality framework in {out_dir}")
    print("next: review applicability/owners, then run evaluate_quality.py --run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
