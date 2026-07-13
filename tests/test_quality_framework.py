from __future__ import annotations

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


class QualityFrameworkTest(unittest.TestCase):
    def make_project(
        self, extra_files: dict[str, str] | None = None,
        init_args: tuple[str, ...] = (),
        development_mode: str = "human_brownfield",
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
                "--distribution-model", "open_source",
                "--market", "global_unspecified",
                "--criticality", "low",
                "--data-sensitivity", "public",
                "--deployment-model", "local",
                "--support-model", "community",
                "--primary-user", "developer",
                "--no-ai-system",
                "--scope-mode", "full_repo",
                "--legal-profile", "none_identified",
                *init_args,
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return temp

    def run_evaluator(self, project: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(EVALUATE), "--root", str(project), *args],
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

    def test_unknown_claim_critical_manifest_field_is_rejected(self) -> None:
        project = self.make_project()
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["silent_claim_override"] = True
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        result = self.run_evaluator(project, "--claim")
        self.assertEqual(result.returncode, 2)
        self.assertIn("manifest.silent_claim_override is not allowed", result.stderr)

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
        self.assertIn("registered campaign revision and phase context", task.stderr)

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

    def test_contract_separates_observation_status_outcome_and_claim(self) -> None:
        lifecycle = (ROOT / "references" / "05-delivery-lifecycle.md").read_text()
        audit = (ROOT / "references" / "35-audit-and-evidence.md").read_text()
        self.assertIn("Observation\n  -> ControlStatus\n  -> TaskOrPhaseOutcome", lifecycle)
        self.assertIn("Do not introduce `RATCHET_PASS` or `INHERITED_PASS`", lifecycle)
        self.assertIn("actor display label does not prove independence", audit)
        self.assertIn("Environment Capability Gate", audit)

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

    def test_same_actor_cannot_self_audit_and_release(self) -> None:
        project = self.make_project()
        for stage in ("self", "cross", "release_authority"):
            result = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", "same-agent",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        claim = self.run_evaluator(project, "--claim")
        self.assertEqual(claim.returncode, 1)
        self.assertIn("independent actors", claim.stderr)

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
