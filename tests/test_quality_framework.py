from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "scripts" / "init_quality_framework.py"
EVALUATE = ROOT / "scripts" / "evaluate_quality.py"
SCAN = ROOT / "scripts" / "scan_project.py"
SYNC = ROOT / "scripts" / "sync_traceability.py"
REGISTER = ROOT / "scripts" / "register_campaign.py"


class QualityFrameworkTest(unittest.TestCase):
    def make_project(
        self, extra_files: dict[str, str] | None = None,
        init_args: tuple[str, ...] = (),
        development_mode: str = "human_brownfield",
        distribution_model: str = "open_source",
        public_contracts: tuple[str, ...] = ("none",),
        build_topology: str = "single_form",
        persistent_state: str = "none",
        external_contributions: str = "accepted",
        ai_system: bool = False,
    ) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="quality-framework-test-"))
        (temp / "README.md").write_text("# Fixture\n", encoding="utf-8")
        for name, content in (extra_files or {}).items():
            path = temp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=temp, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=temp, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=temp, check=True)
        subprocess.run(["git", "add", "."], cwd=temp, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=temp, check=True)
        result = subprocess.run(
            [
                sys.executable, str(INIT), "--root", str(temp),
                "--development-mode", development_mode,
                "--target-maturity", "prototype",
                "--product-type", "cli",
                "--distribution-model", distribution_model,
                "--market", "global_unspecified",
                "--criticality", "low",
                "--data-sensitivity", "public",
                "--deployment-model", "local",
                "--support-model", "community",
                "--primary-user", "developer",
                *[
                    item
                    for contract in public_contracts
                    for item in ("--public-contract", contract)
                ],
                "--build-topology", build_topology,
                "--persistent-state", persistent_state,
                "--external-contributions", external_contributions,
                "--ai-system" if ai_system else "--no-ai-system",
                "--scope-mode", "full_repo",
                "--legal-profile", "none_identified",
                *init_args,
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return temp

    def run_evaluator(self, project: Path, *args: str) -> subprocess.CompletedProcess[str]:
        arguments = list(args)
        if "--run" in arguments:
            stage = arguments[arguments.index("--audit-stage") + 1] if "--audit-stage" in arguments else "self"
            actor = arguments[arguments.index("--actor") + 1] if "--actor" in arguments else "codex"
            if "--authority-id" not in arguments:
                authority = {
                    "self": "virtual:developer",
                    "cross": "virtual:quality",
                    "release_authority": "virtual:release-owner",
                    "third_party": "external:third-party",
                }[stage]
                arguments.extend(["--authority-id", authority])
            if "--execution-context" not in arguments:
                arguments.extend(["--execution-context", f"context:{actor}"])
            if stage != "self" and "--review-run" not in arguments:
                expected = {
                    "cross": "self", "release_authority": "cross",
                    "third_party": "release_authority",
                }[stage]
                ledger = json.loads(
                    (project / ".guardrails" / "evidence-ledger.json").read_text()
                )
                source = next(
                    run for run in reversed(ledger["runs"])
                    if run["audit_stage"] == expected
                )
                arguments.extend(["--review-run", source["run_id"]])
        return subprocess.run(
            [sys.executable, str(EVALUATE), "--root", str(project), *arguments],
            check=False, capture_output=True, text=True,
        )

    def register_campaign(self, project: Path, specification: dict) -> subprocess.CompletedProcess[str]:
        campaign_path = project.parent / f"{project.name}-campaign.json"
        campaign_path.write_text(json.dumps(specification, indent=2) + "\n")
        return subprocess.run(
            [
                sys.executable, str(REGISTER), "--root", str(project),
                "--campaign", str(campaign_path),
            ],
            check=False, capture_output=True, text=True,
        )

    def test_initializer_generates_machine_sources_and_traceability(self) -> None:
        project = self.make_project()
        guardrails = project / ".guardrails"
        for name in (
            "quality-manifest.yaml", "control-registry.yaml",
            "evidence-ledger.json", "traceability-graph.json",
        ):
            self.assertTrue((guardrails / name).is_file(), name)

        graph = json.loads((guardrails / "traceability-graph.json").read_text())
        registry = json.loads((guardrails / "control-registry.yaml").read_text())
        self.assertEqual(len(graph["links"]), len(registry["controls"]))
        self.assertEqual("2.0", graph["schema_version"])
        self.assertEqual("2.0", registry["schema_version"])
        manifest = json.loads((guardrails / "quality-manifest.yaml").read_text())
        self.assertIn("claim_policies", manifest)
        self.assertIn("development_policy", manifest)
        self.assertEqual(["none"], manifest["profile"]["public_contracts"])
        self.assertEqual("single_form", manifest["profile"]["build_topology"])
        self.assertEqual("none", manifest["profile"]["persistent_state"])
        self.assertEqual("accepted", manifest["profile"]["external_contributions"])

    def test_open_core_round_trips_through_v2_contract(self) -> None:
        project = self.make_project(distribution_model="open_core")
        result = self.run_evaluator(project, "--claim")
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertNotIn("profile.distribution_model is invalid", result.stderr)
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_ids = {item["id"] for item in registry["controls"]}
        self.assertIn("QF.OSPS.CONTRIBUTING", control_ids)
        self.assertIn("QF.OPENCORE.LICENSE_BOUNDARY", control_ids)
        self.assertIn("QF.OPENCORE.COMPONENT_LICENSE_INVENTORY", control_ids)

    def test_path_keywords_do_not_select_applicable_controls(self) -> None:
        project = self.make_project({
            "src/kernel_cache.rs": "pub fn cache() {}\n",
            "docs/migration-guide.md": "# Rename a CLI flag\n",
            "crates/app/src/lib.rs": "pub fn app() {}\n",
            "crates/internal/src/lib.rs": "pub(crate) fn helper() {}\n",
        })
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_ids = {item["id"] for item in registry["controls"]}
        self.assertNotIn("QF.API.STABILITY", control_ids)
        self.assertNotIn("QF.ARCHITECTURE.WORKSPACE_BOUNDARY", control_ids)
        self.assertNotIn("QF.OPERATIONS.SCHEMA_EVOLUTION", control_ids)

    def test_explicit_profile_selects_controls_without_path_markers(self) -> None:
        project = self.make_project(
            distribution_model="private_commercial",
            public_contracts=("extension_api",),
            build_topology="cross_target",
            persistent_state="client_state",
            external_contributions="closed",
        )
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        controls = {item["id"]: item for item in registry["controls"]}
        self.assertIn("QF.API.STABILITY", controls)
        self.assertIn("QF.ARCHITECTURE.WORKSPACE_BOUNDARY", controls)
        self.assertIn("QF.OPERATIONS.SCHEMA_EVOLUTION", controls)
        self.assertNotIn("QF.CONTRIBUTION.AI_POLICY", controls)
        self.assertIn("extension_api", controls["QF.API.STABILITY"]["applicability_rationale"])

    def test_external_contribution_decision_is_independent_of_product_ai(self) -> None:
        closed_ai = self.make_project(
            distribution_model="private_commercial",
            external_contributions="closed",
            ai_system=True,
        )
        closed_registry = json.loads(
            (closed_ai / ".guardrails" / "control-registry.yaml").read_text()
        )
        closed_ids = {item["id"] for item in closed_registry["controls"]}
        self.assertIn("QF.AI.INTENDED_USE", closed_ids)
        self.assertNotIn("QF.CONTRIBUTION.AI_POLICY", closed_ids)

        restricted_non_ai = self.make_project(
            distribution_model="private_commercial",
            external_contributions="restricted",
        )
        restricted_registry = json.loads(
            (restricted_non_ai / ".guardrails" / "control-registry.yaml").read_text()
        )
        restricted_ids = {item["id"] for item in restricted_registry["controls"]}
        self.assertIn("QF.CONTRIBUTION.AI_POLICY", restricted_ids)
        self.assertNotIn("QF.AI.INTENDED_USE", restricted_ids)

    def test_unknown_claim_critical_manifest_field_is_rejected(self) -> None:
        project = self.make_project()
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["silent_claim_override"] = True
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        result = self.run_evaluator(project, "--claim")
        self.assertEqual(result.returncode, 2)
        self.assertIn("manifest.silent_claim_override is not allowed", result.stderr)

    def test_ambiguous_public_contract_profile_is_rejected(self) -> None:
        project = self.make_project()
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["profile"]["public_contracts"] = ["none", "service_api"]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        result = self.run_evaluator(project, "--claim")
        self.assertEqual(2, result.returncode)
        self.assertIn(
            "profile.public_contracts cannot combine none",
            result.stderr,
        )

    def test_non_string_public_contract_profile_is_rejected_without_crashing(self) -> None:
        project = self.make_project()
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["profile"]["public_contracts"] = [{"type": "service_api"}]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        result = self.run_evaluator(project, "--claim")
        self.assertEqual(2, result.returncode)
        self.assertIn(
            "profile.public_contracts must contain only strings",
            result.stderr,
        )

    def test_missing_declared_capability_blocks_before_product_command(self) -> None:
        project = self.make_project()
        marker = project / "product-command-ran"
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        registry["capabilities"].append({
            "id": "docker",
            "owner": "platform",
            "authorization_required": False,
            "preflight": {
                "command": [sys.executable, "-c", "raise SystemExit(9)"],
                "cwd": ".",
                "timeout_seconds": 10,
            },
        })
        control = registry["controls"][0]
        control["required_capability_refs"] = ["docker"]
        control["execution"] = {
            "type": "command",
            "command": [
                sys.executable, "-c",
                "from pathlib import Path; Path('product-command-ran').write_text('yes')",
            ],
            "cwd": ".",
            "timeout_seconds": 10,
            "authorization_required": False,
        }
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(sync.returncode, 0, sync.stdout + sync.stderr)
        result = self.run_evaluator(
            project, "--run", "--audit-stage", "self", "--actor", "fixture-self",
            "--control", control["id"],
        )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(marker.exists())
        ledger = json.loads(
            (project / ".guardrails" / "evidence-ledger.json").read_text()
        )
        observation = ledger["runs"][-1]["results"][0]
        self.assertEqual("BLOCKED", observation["status"])
        self.assertEqual("environment", observation["blocker_kind"])
        self.assertEqual("UNAVAILABLE", observation["environment"]["preflight"][0]["status"])

    def test_command_output_is_redacted_and_persisted_for_cross_audit(self) -> None:
        project = self.make_project()
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control = registry["controls"][0]
        control["execution"] = {
            "type": "command",
            "command": [
                sys.executable, "-c",
                "print('Authorization: Bearer top-secret-token')",
            ],
            "cwd": ".",
            "timeout_seconds": 10,
            "authorization_required": False,
        }
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(sync.returncode, 0, sync.stdout + sync.stderr)
        result = self.run_evaluator(project, "--run", "--control", control["id"])
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger = json.loads(
            (project / ".guardrails" / "evidence-ledger.json").read_text()
        )
        observation = ledger["runs"][-1]["results"][0]
        output_path = project / observation["output_ref"]
        self.assertTrue(output_path.is_file())
        persisted = output_path.read_text()
        self.assertNotIn("top-secret-token", persisted)
        self.assertIn("Bearer [REDACTED]", persisted)
        for stage in ("cross", "release_authority"):
            audited = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}", "--control", control["id"],
            )
            self.assertEqual(audited.returncode, 0, audited.stderr)
        task = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control["id"],
        )
        self.assertEqual(task.returncode, 0, task.stderr)

    def test_subset_run_cannot_satisfy_full_claim(self) -> None:
        project = self.make_project()
        control_id = "QF.FRAMEWORK.MANIFEST"
        for stage in ("self", "cross", "release_authority"):
            result = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}", "--control", control_id,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        claim = self.run_evaluator(project, "--claim")
        self.assertEqual(claim.returncode, 1)
        self.assertIn("QF.FRAMEWORK.REGISTRY", claim.stderr)
        bypass = self.run_evaluator(project, "--claim", "--control", control_id)
        self.assertEqual(bypass.returncode, 2)
        self.assertIn("project claims cannot select", bypass.stderr)
        task = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control_id,
        )
        self.assertEqual(task.returncode, 0, task.stderr)
        self.assertIn("task controls", task.stdout)
        self.assertIn("COMPLETED [QF-TASK]", task.stdout)
        self.assertIn("project maturity is unchanged", task.stdout)

    def test_subproject_scope_cannot_emit_project_claim(self) -> None:
        project = self.make_project()
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["scope"] = {
            "mode": "subproject",
            "included_paths": ["component"],
            "excluded_paths": [],
            "unassessed_dependencies": ["containing-product"],
            "overall_project_claim_allowed": False,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        claim = self.run_evaluator(project, "--claim")
        self.assertEqual(claim.returncode, 1)
        self.assertIn("cannot support a project or release claim", claim.stderr)

    def test_ai_brownfield_task_requires_registered_campaign_context(self) -> None:
        project = self.make_project(development_mode="ai_brownfield")
        control_id = "QF.FRAMEWORK.MANIFEST"
        for stage in ("self", "cross", "release_authority"):
            result = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}", "--control", control_id,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        task = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control_id,
        )
        self.assertEqual(task.returncode, 1)
        self.assertIn("require an active campaign", task.stderr)

    def test_unconfirmed_applies_false_is_a_framework_error(self) -> None:
        project = self.make_project()
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        registry["controls"][0]["applies"] = False
        registry["controls"][0].pop("applicability_rationale", None)
        registry["controls"][0].pop("applicability_confirmed_by", None)
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(sync.returncode, 2)
        self.assertIn("applicability_rationale is required", sync.stdout + sync.stderr)
        claim = self.run_evaluator(project, "--claim")
        self.assertEqual(claim.returncode, 2)
        self.assertIn("applicability_rationale is required", claim.stderr)

    def test_generated_guidance_qualifies_project_rule_authority(self) -> None:
        project = self.make_project({
            "AGENTS.md": "# Project Rules\n\n- Run the project gate.\n",
        })
        profile = (project / ".guardrails" / "profile.md").read_text()
        index = (project / ".guardrails" / "INDEX.md").read_text()
        self.assertNotIn("single source of truth", profile)
        self.assertNotIn("the **authoritative source of truth**", index)
        self.assertIn("project-specific domain semantics", profile)
        self.assertIn("portable Skill owns claim", profile)
        self.assertIn("project domain semantics", index)
        self.assertIn("claim/evidence meta-semantics", index)
        self.assertIn("Conflicts block", index)
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        self.assertEqual(1, len(registry["federated_rule_mappings"]))
        mapping = registry["federated_rule_mappings"][0]
        self.assertEqual("AGENTS.md", mapping["source_ref"])
        self.assertEqual("unmapped", mapping["status"])
        blocked = self.run_evaluator(
            project, "--claim", "--claim-scope", "task",
            "--control", registry["controls"][0]["id"],
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("mandatory project rule is unmapped", blocked.stderr)

    def test_contract_separates_observation_status_outcome_and_claim(self) -> None:
        lifecycle = (ROOT / "references" / "05-delivery-lifecycle.md").read_text()
        audit = (ROOT / "references" / "35-audit-and-evidence.md").read_text()
        self.assertIn("Observation\n  -> ControlStatus\n  -> TaskOrPhaseOutcome", lifecycle)
        self.assertIn("Do not introduce `RATCHET_PASS` or `INHERITED_PASS`", lifecycle)
        self.assertIn("actor display label does not prove independence", audit)
        self.assertIn("Environment Capability Gate", audit)

    def test_reference_learning_cannot_promote_one_repository_to_a_control(self) -> None:
        lifecycle = (ROOT / "references" / "40-rule-lifecycle.md").read_text()
        self.assertIn("source_revision:", lifecycle)
        self.assertIn("counterexample_or_limitation:", lifecycle)
        self.assertIn(
            "one repository can produce only `observed_once`",
            lifecycle,
        )

    def test_registry_change_invalidates_graph_and_prior_evidence(self) -> None:
        project = self.make_project()
        for stage in ("self", "cross", "release_authority"):
            result = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_evaluator(project, "--claim").returncode, 0)

        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        registry["controls"][0]["title"] += " updated"
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")

        stale = self.run_evaluator(project, "--claim")
        self.assertEqual(stale.returncode, 2)
        self.assertIn("traceability graph is stale", stale.stderr)
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(sync.returncode, 0, sync.stdout + sync.stderr)
        claim = self.run_evaluator(project, "--claim")
        self.assertEqual(claim.returncode, 1)
        self.assertIn("controls without current PASS", claim.stderr)

    def test_same_authority_cannot_cross_audit(self) -> None:
        project = self.make_project()
        initial = self.run_evaluator(
            project, "--run", "--audit-stage", "self", "--actor", "same-agent",
        )
        self.assertEqual(initial.returncode, 0, initial.stderr)
        cross = self.run_evaluator(
            project, "--run", "--audit-stage", "cross", "--actor", "same-agent",
            "--authority-id", "virtual:developer",
        )
        self.assertEqual(cross.returncode, 2)
        self.assertIn("not registered for cross", cross.stderr)

    def test_same_execution_context_cannot_cross_audit(self) -> None:
        project = self.make_project()
        initial = self.run_evaluator(
            project, "--run", "--audit-stage", "self", "--actor", "developer",
            "--execution-context", "shared-context",
        )
        self.assertEqual(initial.returncode, 0, initial.stderr)
        cross = self.run_evaluator(
            project, "--run", "--audit-stage", "cross", "--actor", "quality",
            "--execution-context", "shared-context",
        )
        self.assertEqual(cross.returncode, 1)
        self.assertIn("same execution context", cross.stderr)

    def test_workspace_change_invalidates_prior_evidence(self) -> None:
        project = self.make_project()
        for stage in ("self", "cross", "release_authority"):
            result = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_evaluator(project, "--claim").returncode, 0)
        (project / "README.md").write_text("# Changed after audit\n", encoding="utf-8")
        claim = self.run_evaluator(project, "--claim")
        self.assertEqual(claim.returncode, 1)
        self.assertIn("controls without current PASS", claim.stderr)

    def test_ledger_tampering_is_detected(self) -> None:
        project = self.make_project()
        result = self.run_evaluator(
            project, "--run", "--audit-stage", "self", "--actor", "fixture-self",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger_path = project / ".guardrails" / "evidence-ledger.json"
        ledger = json.loads(ledger_path.read_text())
        ledger["runs"][0]["actor"] = "rewritten"
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
        claim = self.run_evaluator(project, "--claim")
        self.assertEqual(claim.returncode, 2)
        self.assertIn("entry_sha256 does not match", claim.stderr)

    def test_task_claim_uses_task_policy_and_persists_claim(self) -> None:
        project = self.make_project()
        control_id = "QF.FRAMEWORK.MANIFEST"
        for stage in ("self", "cross"):
            result = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}", "--control", control_id,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        claim = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control_id,
        )
        self.assertEqual(claim.returncode, 0, claim.stderr)
        ledger = json.loads(
            (project / ".guardrails" / "evidence-ledger.json").read_text()
        )
        self.assertEqual(1, len(ledger["claims"]))
        self.assertEqual(["cross", "self"], ledger["claims"][0]["audit_stages"])

    def test_modified_output_evidence_blocks_claim(self) -> None:
        project = self.make_project()
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control = registry["controls"][0]
        control_id = control["id"]
        control["execution"] = {
            "type": "command",
            "command": [sys.executable, "-c", "print('evidence')"],
            "cwd": ".", "timeout_seconds": 10, "authorization_required": False,
        }
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(sync.returncode, 0, sync.stderr)
        result = self.run_evaluator(
            project, "--run", "--audit-stage", "self",
            "--actor", "fixture-self", "--control", control_id,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger = json.loads(
            (project / ".guardrails" / "evidence-ledger.json").read_text()
        )
        output_ref = ledger["runs"][0]["results"][0]["output_ref"]
        (project / output_ref).write_text("tampered\n")
        claim = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control_id,
        )
        self.assertEqual(claim.returncode, 2)
        self.assertIn("output evidence digest mismatch", claim.stderr)

    def test_disputed_federated_rule_blocks_affected_claim(self) -> None:
        project = self.make_project({"AGENTS.md": "# Mandatory project rule\n"})
        source = project / "AGENTS.md"
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control_id = registry["controls"][0]["id"]
        registry["federated_rule_mappings"] = [{
            "rule_id": "PROJECT.MANDATORY",
            "source_ref": "AGENTS.md",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "semantic_owner": "project-owner",
            "control_refs": [control_id],
            "mandatory": True,
            "status": "disputed",
            "observed_at": "2026-07-13T00:00:00+00:00",
            "reviewed_at": "2026-07-13T00:00:00+00:00",
        }]
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(sync.returncode, 0, sync.stderr)
        for stage in ("self", "cross"):
            self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}", "--control", control_id,
            )
        claim = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control_id,
        )
        self.assertEqual(claim.returncode, 1)
        self.assertIn("policy_conflict:PROJECT.MANDATORY", claim.stderr)

    def test_ai_brownfield_ratchet_task_completes_with_failed_debt_control(self) -> None:
        baseline_content = "known-a\nknown-b\nknown-c\n"
        project = self.make_project(
            {"quality/baseline.txt": baseline_content},
            development_mode="ai_brownfield",
        )
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control = registry["controls"][0]
        control_id = control["id"]
        baseline_digest = hashlib.sha256(baseline_content.encode()).hexdigest()
        observation = {
            "baseline_ref": "BASE.QUALITY",
            "baseline_revision": 1,
            "baseline_source_sha256": baseline_digest,
            "baseline_count": 3,
            "current_count": 2,
            "new_count": 0,
            "fixed_count": 1,
        }
        command = (
            "import json,pathlib; "
            "p=pathlib.Path('.guardrails/evidence/observations/debt.json'); "
            "p.parent.mkdir(parents=True,exist_ok=True); "
            f"p.write_text(json.dumps({observation!r})); raise SystemExit(1)"
        )
        control["evaluation_mode"] = "ratchet_delta"
        control["ratchet_policy"] = {
            "baseline_ref": "BASE.QUALITY",
            "observation_path": ".guardrails/evidence/observations/debt.json",
        }
        control["execution"] = {
            "type": "command", "command": [sys.executable, "-c", command],
            "cwd": ".", "timeout_seconds": 10, "authorization_required": False,
        }
        registry["baselines"] = [{
            "id": "BASE.QUALITY", "control_id": control_id, "revision": 1,
            "source_ref": "quality/baseline.txt", "source_sha256": baseline_digest,
            "violation_count": 3,
        }]
        registry["cleanup_debts"] = [{
            "id": "DEBT.QUALITY", "control_id": control_id,
            "baseline_ref": "BASE.QUALITY", "scope": ["."], "owner": "quality",
            "status": "open", "delete_by": "2027-07-13T00:00:00+00:00",
            "rationale": "Existing findings must converge to zero.",
        }]
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(sync.returncode, 0, sync.stderr)
        exit_policy = {
            "max_new_violations": 0,
            "minimum_fixed_violations": 1,
            "allow_open_cleanup_debt": True,
        }
        registered = self.register_campaign(project, {
            "id": "CAMP-1", "revision": 1, "target_maturity": "prototype",
            "assessed_scope": ["."], "owner": "quality",
            "phases": [{
                "id": "PHASE-1", "title": "Debt convergence",
                "affected_control_ids": [control_id], "assessed_scope": ["."],
                "exit_policy": exit_policy,
                "tasks": [{
                    "id": "TASK-1", "kind": "debt_reduction",
                    "affected_control_ids": [control_id], "assessed_scope": ["."],
                    "exit_policy": exit_policy,
                }],
            }],
        })
        self.assertEqual(registered.returncode, 0, registered.stderr)
        for stage in ("self", "cross"):
            run = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}", "--control", control_id,
            )
            self.assertEqual(run.returncode, 1, run.stderr)
        claim = self.run_evaluator(
            project, "--claim", "--claim-scope", "task",
            "--campaign-id", "CAMP-1", "--campaign-revision", "1",
            "--phase-id", "PHASE-1", "--task-id", "TASK-1",
        )
        self.assertEqual(claim.returncode, 0, claim.stderr)
        self.assertIn("COMPLETED [QF-TASK]", claim.stdout)
        phase_claim = self.run_evaluator(
            project, "--claim", "--claim-scope", "phase",
            "--campaign-id", "CAMP-1", "--campaign-revision", "1",
            "--phase-id", "PHASE-1",
        )
        self.assertEqual(phase_claim.returncode, 0, phase_claim.stderr)
        self.assertIn("COMPLETED [QF-PHASE]", phase_claim.stdout)
        project_claim = self.run_evaluator(project, "--claim")
        self.assertEqual(project_claim.returncode, 1)
        self.assertIn("open_cleanup_debt:DEBT.QUALITY", project_claim.stderr)

    def test_bounded_output_records_full_stream_digest(self) -> None:
        project = self.make_project()
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control = registry["controls"][0]
        control["execution"] = {
            "type": "command",
            "command": [sys.executable, "-c", "print('x' * 70000, end='')"],
            "cwd": ".", "timeout_seconds": 10, "authorization_required": False,
        }
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(sync.returncode, 0, sync.stderr)
        run = self.run_evaluator(
            project, "--run", "--audit-stage", "self",
            "--actor", "fixture-self", "--control", control["id"],
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        ledger = json.loads(
            (project / ".guardrails" / "evidence-ledger.json").read_text()
        )
        result = ledger["runs"][-1]["results"][0]
        self.assertTrue(result["output_truncated"])
        self.assertEqual(70000, result["raw_output_bytes"])
        self.assertEqual(65536, result["output_bytes"])
        self.assertEqual(
            hashlib.sha256(b"x" * 70000).hexdigest(), result["raw_output_sha256"],
        )

    def test_changed_artifact_stales_claim_without_corrupting_history(self) -> None:
        project = self.make_project({".gitignore": "build/\n"})
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control = registry["controls"][0]
        control["execution"] = {
            "type": "command",
            "command": [
                sys.executable, "-c",
                "from pathlib import Path; p=Path('build/report.txt'); "
                "p.parent.mkdir(exist_ok=True); p.write_text('current')",
            ],
            "cwd": ".", "timeout_seconds": 10, "authorization_required": False,
            "artifact_paths": ["build/report.txt"],
        }
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(sync.returncode, 0, sync.stderr)
        initial = self.run_evaluator(
            project, "--run", "--audit-stage", "self",
            "--actor", "fixture-self", "--control", control["id"],
        )
        self.assertEqual(initial.returncode, 0, initial.stderr)
        (project / "build/report.txt").write_text("changed")
        stale = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control["id"],
        )
        self.assertEqual(stale.returncode, 1)
        self.assertIn("STALE_ARTIFACT", stale.stderr)
        rerun = self.run_evaluator(
            project, "--run", "--audit-stage", "self",
            "--actor", "fixture-second-self", "--control", control["id"],
        )
        self.assertEqual(rerun.returncode, 0, rerun.stderr)

    def test_scanner_collects_project_owned_gate_evidence(self) -> None:
        project = Path(tempfile.mkdtemp(prefix="quality-scan-test-"))
        (project / "Makefile").write_text(
            "gate coverage-gate:\n\t@true\n", encoding="utf-8",
        )
        (project / "package.json").write_text(json.dumps({
            "scripts": {"test": "vitest run", "build": "tsc -b"},
        }))
        workflows = project / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text(
            "jobs:\n  quality:\n    steps:\n      - run: make gate\n",
            encoding="utf-8",
        )
        scripts = project / "scripts"
        scripts.mkdir()
        (scripts / "fitness-runner.sh").write_text(
            '  "FF-01|architecture|check-owner.sh|pr|0|Owner boundary"\n',
            encoding="utf-8",
        )
        output = project / "scan.json"
        result = subprocess.run(
            [sys.executable, str(SCAN), "--root", str(project), "--out", str(output)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        scan = json.loads(output.read_text())
        self.assertEqual({"gate", "coverage-gate"}, set(scan["build_targets"]))
        self.assertEqual("FF-01", scan["fitness_registry"][0]["id"])
        self.assertEqual(2, len(scan["package_scripts"]))
        self.assertEqual("make gate", scan["ci_commands"][0]["value"])

    def test_scanner_keeps_release_and_hygiene_evidence_out_of_security(self) -> None:
        project = self.make_project({
            "PGP-KEY.asc": "fixture release key\n",
            "cosign.pub": "fixture verification key\n",
            "rust-toolchain.toml": "[toolchain]\nchannel = 'stable'\n",
        })
        output = project / "scan-taxonomy.json"
        result = subprocess.run(
            [sys.executable, str(SCAN), "--root", str(project), "--out", str(output)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(output.read_text())["evidence"]
        self.assertIn("PGP-KEY.asc", evidence["release"])
        self.assertIn("cosign.pub", evidence["release"])
        self.assertNotIn("PGP-KEY.asc", evidence["security"])
        self.assertNotIn("cosign.pub", evidence["security"])
        self.assertIn("rust-toolchain.toml", evidence["engineering_hygiene"])
        self.assertNotIn("rust-toolchain.toml", evidence["governance"])

    def test_explicit_scaffold_creates_non_installing_gate_and_pinned_ci(self) -> None:
        project = self.make_project(
            {"Makefile": "gate:\n\t@true\n"},
            ("--scaffold-engineering",),
        )
        runner = project / ".guardrails" / "run-quality-gates.py"
        workflow = project / ".github" / "workflows" / "quality-framework.yml"
        self.assertTrue(runner.is_file())
        self.assertIn('[\n  [\n    "make",\n    "gate"', runner.read_text())
        workflow_text = workflow.read_text()
        self.assertIn("actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0", workflow_text)
        self.assertNotIn("install", runner.read_text())

    def test_detected_ci_creates_authorized_commit_bound_remote_control(self) -> None:
        project = self.make_project({
            ".github/workflows/ci.yml": "jobs:\n  test:\n    steps:\n      - run: true\n",
        })
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control = next(item for item in registry["controls"] if item["id"] == "QF.CI.REMOTE")
        self.assertEqual(control["execution"]["type"], "remote")
        self.assertTrue(control["execution"]["authorization_required"])
        self.assertIn("{commit}", control["execution"]["command"][2])


if __name__ == "__main__":
    unittest.main()
