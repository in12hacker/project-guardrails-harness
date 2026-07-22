from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "scripts" / "init_quality_framework.py"
EVALUATE = ROOT / "scripts" / "evaluate_quality.py"
SCAN = ROOT / "scripts" / "scan_project.py"
SYNC = ROOT / "scripts" / "sync_traceability.py"
REGISTER = ROOT / "scripts" / "register_campaign.py"
LINT_CAMPAIGN = ROOT / "scripts" / "lint_campaign.py"
REVIEW_UPDATE = ROOT / "scripts" / "review_skill_update.py"
READINESS = ROOT / "scripts" / "assess_readiness.py"
HARNESS_CANDIDATE = ROOT / "scripts" / "validate_harness_candidate.py"
MUTATOR_CANDIDATE = ROOT / "scripts" / "validate_mutator_candidate.py"
HANDOFF = ROOT / "scripts" / "render_task_handoff.py"
SEAL = ROOT / "scripts" / "seal_evidence.py"
PREFLIGHT = ROOT / "templates" / "preflight.py"


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
                "--skill-deployment", "environment_managed",
                "--evidence-profile", "open_source",
                "--evidence-retention", "project_lifetime",
                "--evidence-max-active-bytes", "1073741824",
                "--evidence-sealing-profile", "sha256_chain",
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

    def lint_campaign(
        self, project: Path, specification: dict, *args: str,
    ) -> subprocess.CompletedProcess[str]:
        campaign_path = project.parent / f"{project.name}-campaign-lint.json"
        campaign_path.write_text(json.dumps(specification, indent=2) + "\n")
        return subprocess.run(
            [
                sys.executable, str(LINT_CAMPAIGN), "--root", str(project),
                "--campaign", str(campaign_path), *args,
            ],
            check=False, capture_output=True, text=True,
        )

    def load_quality_common(self):
        spec = importlib.util.spec_from_file_location(
            "quality_common_selector_fixture", ROOT / "scripts" / "quality_common.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def load_script_module(self, name: str, path: Path):
        scripts = str(ROOT / "scripts")
        sys.path.insert(0, scripts)
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            sys.path.remove(scripts)

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
        self.assertEqual("3.0", graph["schema_version"])
        self.assertEqual("3.0", registry["schema_version"])
        manifest = json.loads((guardrails / "quality-manifest.yaml").read_text())
        self.assertIn("claim_policies", manifest)
        self.assertIn("development_policy", manifest)
        self.assertEqual(["none"], manifest["profile"]["public_contracts"])
        self.assertEqual("single_form", manifest["profile"]["build_topology"])
        self.assertEqual("none", manifest["profile"]["persistent_state"])
        self.assertEqual("accepted", manifest["profile"]["external_contributions"])
        self.assertEqual(".", manifest["project"]["root"])
        for markdown in guardrails.rglob("*.md"):
            with self.subTest(markdown=markdown.name):
                self.assertTrue(all(line == line.rstrip() for line in markdown.read_text().splitlines()))
        supply_chain = (guardrails / "supply-chain.md").read_text()
        for label in ("Produce", "Publish", "Verify at deploy", "Gate incoming deps"):
            self.assertIn(f"- **{label}:**", supply_chain)
        self.assertEqual("environment_managed", manifest["profile"]["skill_deployment"])
        self.assertEqual("open_source", manifest["evidence_policy"]["profile"])
        self.assertEqual(
            "project_lifetime", manifest["evidence_policy"]["retention"]
        )
        self.assertEqual(
            1073741824, manifest["evidence_policy"]["max_active_bytes"]
        )

    def test_open_core_round_trips_through_v3_contract(self) -> None:
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
        secret = f"{project}/secret-value"
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control = registry["controls"][0]
        control["execution"] = {
            "type": "command",
            "command": [
                sys.executable, "-c",
                "import os, sys; token=os.environ['QUALITY_TEST_TOKEN']; "
                "print('\\x1b[31mAuthorization: Bearer '+token+'\\x1b[0m'); "
                f"print({str(project)!r}); "
                "sys.stdout.write('\\x1b]0;hidden-title\\x07visible\\rrewritten\\b!\\n')",
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
        with mock.patch.dict(os.environ, {"QUALITY_TEST_TOKEN": secret}):
            result = self.run_evaluator(project, "--run", "--control", control["id"])
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger = json.loads(
            (project / ".guardrails" / "evidence-ledger.json").read_text()
        )
        observation = ledger["runs"][-1]["results"][0]
        output_path = project / observation["output_ref"]
        self.assertTrue(output_path.is_file())
        persisted = output_path.read_text()
        self.assertNotIn(secret, persisted)
        self.assertNotIn("secret-value", persisted)
        self.assertNotIn("hidden-title", persisted)
        self.assertNotIn("\x1b", persisted)
        self.assertFalse(any(
            (ord(character) < 32 and character not in "\n\t")
            or 127 <= ord(character) <= 159
            for character in persisted
        ))
        self.assertIn("Bearer [REDACTED]", persisted)
        self.assertNotIn(str(project), persisted)
        self.assertIn("[PROJECT_ROOT]", persisted)
        for stage in ("cross", "release_authority"):
            with mock.patch.dict(os.environ, {"QUALITY_TEST_TOKEN": secret}):
                audited = self.run_evaluator(
                    project, "--run", "--audit-stage", stage,
                    "--actor", f"fixture-{stage}", "--control", control["id"],
                )
            self.assertEqual(audited.returncode, 0, audited.stderr)
        task = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control["id"],
        )
        self.assertEqual(task.returncode, 0, task.stderr)

    def test_evidence_persistence_is_canonical_atomic_and_portable(self) -> None:
        module = self.load_script_module("evaluate_quality_storage_fixture", EVALUATE)
        root = Path(tempfile.mkdtemp(prefix="quality-storage-test-"))
        evidence_dir = root / ".guardrails" / "evidence" / "nested" / "outputs"
        canonical = module.normalize_terminal_text(
            "alpha  \r\nbeta\t \r\ngamma\t\ninternal\tvalue  \n",
        )
        self.assertEqual("alpha\nbeta\ngamma\ninternal\tvalue\n", canonical)

        previous_umask = os.umask(0o077)
        try:
            output_ref, output_digest, output_size = module.persist_output(
                root, evidence_dir, canonical,
            )
            source = root / "report.bin"
            source.write_bytes(b"immutable artifact\x00")
            source.chmod(0o600)
            with mock.patch.object(
                Path, "read_bytes", side_effect=AssertionError("artifact must stream"),
            ):
                artifact_ref, artifact_digest, artifact_size = module.persist_evidence_file(
                    root, evidence_dir, source, ".artifact.bin",
                )
        finally:
            os.umask(previous_umask)

        output_path = root / output_ref
        artifact_path = root / artifact_ref
        self.assertEqual(output_digest, hashlib.sha256(output_path.read_bytes()).hexdigest())
        self.assertEqual(output_size, output_path.stat().st_size)
        self.assertEqual(artifact_digest, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(artifact_size, artifact_path.stat().st_size)
        if os.name == "posix":
            self.assertEqual(0o644, output_path.stat().st_mode & 0o777)
            self.assertEqual(0o644, artifact_path.stat().st_mode & 0o777)
            for directory in (
                root / ".guardrails", root / ".guardrails" / "evidence",
                root / ".guardrails" / "evidence" / "nested", evidence_dir,
            ):
                self.assertEqual(0o755, directory.stat().st_mode & 0o777)

        failed_text = "atomic failure"
        failed_digest = hashlib.sha256(failed_text.encode()).hexdigest()
        with mock.patch.object(module.os, "link", side_effect=OSError("injected")):
            with self.assertRaisesRegex(OSError, "injected"):
                module.persist_output(root, evidence_dir, failed_text)
        self.assertFalse((evidence_dir / f"{failed_digest}.log").exists())
        self.assertFalse(any(evidence_dir.glob(f".{failed_digest}.log.*.tmp")))

    def test_file_evidence_digest_and_size_bind_the_published_snapshot(self) -> None:
        module = self.load_script_module("evaluate_quality_snapshot_fixture", EVALUATE)
        root = Path(tempfile.mkdtemp(prefix="quality-snapshot-test-"))
        source = root / "changing.bin"
        source.write_bytes(b"snapshot content")
        evidence_dir = root / ".guardrails" / "evidence" / "outputs"
        original_digest_file = module.digest_file

        def reject_source_rehash(path: Path) -> tuple[str, int]:
            if path == source:
                raise AssertionError("source must be read only by the snapshot stream")
            return original_digest_file(path)

        with mock.patch.object(module, "digest_file", side_effect=reject_source_rehash):
            reference, digest, size = module.persist_evidence_file(
                root, evidence_dir, source, ".artifact.bin",
            )

        persisted = root / reference
        self.assertEqual(hashlib.sha256(persisted.read_bytes()).hexdigest(), digest)
        self.assertEqual(persisted.stat().st_size, size)
        self.assertEqual(source.read_bytes(), persisted.read_bytes())

        wrong_name = f"{'0' * 64}.log"
        with self.assertRaisesRegex(ValueError, "does not match payload digest"):
            module.publish_content_addressed_bytes(
                root, evidence_dir, wrong_name, b"wrong binding",
            )
        self.assertFalse((evidence_dir / wrong_name).exists())

    def test_file_evidence_snapshot_failures_leave_no_partial_objects(self) -> None:
        module = self.load_script_module("evaluate_quality_failure_fixture", EVALUATE)
        root = Path(tempfile.mkdtemp(prefix="quality-snapshot-failure-test-"))
        evidence_dir = root / ".guardrails" / "evidence" / "outputs"
        missing = root / "missing.bin"

        with self.assertRaises(FileNotFoundError):
            module.persist_evidence_file(
                root, evidence_dir, missing, ".artifact.bin",
            )
        self.assertEqual([], list(evidence_dir.iterdir()))

        source = root / "stream.bin"
        source.write_bytes(b"source is replaced by the injected stream")
        original_open = Path.open

        class FailingStream:
            def __init__(self) -> None:
                self.reads = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self, _size: int) -> bytes:
                self.reads += 1
                if self.reads == 1:
                    return b"partial snapshot"
                raise OSError("injected read failure")

        def controlled_open(path: Path, *args, **kwargs):
            if path == source:
                return FailingStream()
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", autospec=True, side_effect=controlled_open):
            with self.assertRaisesRegex(OSError, "injected read failure"):
                module.persist_evidence_file(
                    root, evidence_dir, source, ".artifact.bin",
                )
        self.assertEqual([], list(evidence_dir.iterdir()))

    def test_create_only_publish_handles_same_and_conflicting_races(self) -> None:
        module = self.load_script_module("evaluate_quality_race_fixture", EVALUATE)
        root = Path(tempfile.mkdtemp(prefix="quality-publish-race-test-"))
        payload = b"race-bound evidence"
        digest = hashlib.sha256(payload).hexdigest()

        same_temporary = root / "same.tmp"
        same_destination = root / f"{digest}.artifact.bin"
        same_temporary.write_bytes(payload)
        same_destination.write_bytes(payload)
        module.publish_temporary(
            same_temporary, same_destination, digest, len(payload),
        )
        self.assertFalse(same_temporary.exists())
        self.assertEqual(payload, same_destination.read_bytes())

        conflict_temporary = root / "conflict.tmp"
        conflict_destination = root / f"{digest}.conflict.bin"
        conflict_temporary.write_bytes(payload)
        conflict_destination.write_bytes(b"conflicting bytes")
        with self.assertRaisesRegex(OSError, "was modified"):
            module.publish_temporary(
                conflict_temporary, conflict_destination, digest, len(payload),
            )
        self.assertFalse(conflict_temporary.exists())
        self.assertEqual(b"conflicting bytes", conflict_destination.read_bytes())

    def test_evidence_persistence_rejects_storage_symlink_escape(self) -> None:
        module = self.load_script_module("evaluate_quality_symlink_fixture", EVALUATE)
        root = Path(tempfile.mkdtemp(prefix="quality-storage-root-"))
        external = Path(tempfile.mkdtemp(prefix="quality-storage-external-"))
        evidence_parent = root / ".guardrails" / "evidence"
        evidence_parent.mkdir(parents=True)
        escaped = evidence_parent / "outputs"
        escaped.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "escapes project root"):
            module.persist_output(root, escaped, "must stay local")
        self.assertEqual([], list(external.iterdir()))

    def test_unreadable_evidence_is_a_validation_error(self) -> None:
        project = self.make_project()
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control = registry["controls"][0]
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
        run = self.run_evaluator(project, "--run", "--control", control["id"])
        self.assertEqual(run.returncode, 0, run.stderr)
        ledger = json.loads(
            (project / ".guardrails" / "evidence-ledger.json").read_text()
        )
        output_path = project / ledger["runs"][-1]["results"][0]["output_ref"]
        common = self.load_quality_common()
        original = common.file_sha256

        def unreadable(path: Path) -> str:
            if path == output_path:
                raise PermissionError("injected unreadable evidence")
            return original(path)

        with mock.patch.object(common, "file_sha256", side_effect=unreadable):
            errors = common.validate_ledger(ledger, project)
        self.assertIn("runs[0].results[0] output evidence cannot be read", errors)

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

    def test_campaign_lint_proves_task_scope_requirements_without_writes(self) -> None:
        project = self.make_project(development_mode="ai_brownfield")
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_id = registry["controls"][0]["id"]
        exit_policy = {
            "max_new_violations": 0,
            "minimum_fixed_violations": 0,
            "allow_open_cleanup_debt": True,
        }
        campaign = {
            "id": "LINT-CAMPAIGN", "revision": 1,
            "target_maturity": "prototype",
            "assessed_scope": ["component", ".guardrails"],
            "owner": "quality",
            "phases": [{
                "id": "PHASE-1", "title": "Closed task contract",
                "affected_control_ids": [control_id],
                "assessed_scope": ["component", ".guardrails"],
                "exit_policy": exit_policy,
                "tasks": [{
                    "id": "TASK-1", "kind": "framework_adoption",
                    "affected_control_ids": [control_id],
                    "assessed_scope": ["component/src", ".guardrails/DEV-REPORT.md"],
                    "exit_policy": exit_policy,
                }],
            }],
        }
        guardrails = project / ".guardrails"
        before = {
            path.relative_to(guardrails).as_posix(): path.read_bytes()
            for path in guardrails.rglob("*") if path.is_file()
        }
        result = self.lint_campaign(
            project, campaign,
            "--phase-id", "PHASE-1", "--task-id", "TASK-1",
            "--require-path", ".guardrails/DEV-REPORT.md",
            "--require-control", control_id,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("CAMPAIGN_LINT_OK", payload["status"])
        self.assertFalse(payload["writes_performed"])
        self.assertFalse(payload["controls_executed"])
        self.assertFalse(payload["claim_supported"])
        self.assertEqual([], payload["blocker_details"])
        self.assertEqual(
            [".guardrails/DEV-REPORT.md"],
            payload["task_contract"]["required_paths"],
        )
        after = {
            path.relative_to(guardrails).as_posix(): path.read_bytes()
            for path in guardrails.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)

    def test_active_campaign_lint_uses_only_registered_manifest_revision(self) -> None:
        project = self.make_project(development_mode="ai_brownfield")
        missing = subprocess.run(
            [sys.executable, str(LINT_CAMPAIGN), "--root", str(project), "--active"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(1, missing.returncode, missing.stderr)
        self.assertIn(
            "ACTIVE_CAMPAIGN_MISSING",
            {item["code"] for item in json.loads(missing.stdout)["blocker_details"]},
        )

        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_id = registry["controls"][0]["id"]
        exit_policy = {
            "max_new_violations": 0,
            "minimum_fixed_violations": 0,
            "allow_open_cleanup_debt": True,
        }
        specification = {
            "id": "ACTIVE-LINT", "revision": 7,
            "target_maturity": "prototype", "assessed_scope": ["."],
            "owner": "quality",
            "phases": [{
                "id": "PHASE-1", "title": "Registered contract",
                "affected_control_ids": [control_id], "assessed_scope": ["."],
                "exit_policy": exit_policy,
                "tasks": [{
                    "id": "TASK-1", "kind": "framework_adoption",
                    "affected_control_ids": [control_id], "assessed_scope": ["."],
                    "exit_policy": exit_policy,
                }],
            }],
        }
        registered = self.register_campaign(project, specification)
        self.assertEqual(0, registered.returncode, registered.stderr)

        stale_candidate = copy.deepcopy(specification)
        stale_candidate["revision"] = 6
        candidate_path = project.parent / f"{project.name}-stale-candidate.json"
        candidate_path.write_text(json.dumps(stale_candidate) + "\n")
        active = subprocess.run(
            [
                sys.executable, str(LINT_CAMPAIGN), "--root", str(project),
                "--active", "--phase-id", "PHASE-1", "--task-id", "TASK-1",
                "--require-control", control_id,
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, active.returncode, active.stdout + active.stderr)
        payload = json.loads(active.stdout)
        self.assertEqual("active_manifest", payload["campaign"]["source"])
        self.assertEqual(7, payload["campaign"]["revision"])
        self.assertNotEqual(
            json.loads(candidate_path.read_text())["revision"],
            payload["campaign"]["revision"],
        )

    def test_active_campaign_lint_types_malformed_manifest_blockers(self) -> None:
        for malformed in ([], "invalid", None):
            with self.subTest(development_policy=malformed):
                project = self.make_project(development_mode="ai_brownfield")
                manifest_path = project / ".guardrails" / "quality-manifest.yaml"
                manifest = json.loads(manifest_path.read_text())
                manifest["development_policy"] = malformed
                manifest_path.write_text(json.dumps(manifest) + "\n")

                result = subprocess.run(
                    [
                        sys.executable, str(LINT_CAMPAIGN),
                        "--root", str(project), "--active",
                    ],
                    check=False, capture_output=True, text=True,
                )

                self.assertEqual(1, result.returncode, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                payload = json.loads(result.stdout)
                codes = {item["code"] for item in payload["blocker_details"]}
                self.assertIn("FRAMEWORK_INVALID", codes)
                self.assertIn("ACTIVE_CAMPAIGN_MISSING", codes)

    def test_campaign_lint_rejects_unclosed_scope_and_unmodeled_acquisition(self) -> None:
        project = self.make_project(development_mode="ai_brownfield")
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_id = registry["controls"][0]["id"]
        exit_policy = {
            "max_new_violations": 0,
            "minimum_fixed_violations": 0,
            "allow_open_cleanup_debt": True,
        }

        def campaign(task_scope: list[str]) -> dict:
            return {
                "id": "LINT-BLOCKED", "revision": 1,
                "target_maturity": "prototype", "assessed_scope": ["component"],
                "owner": "quality",
                "phases": [{
                    "id": "PHASE-1", "title": "Scope boundary",
                    "affected_control_ids": [control_id],
                    "assessed_scope": ["component"], "exit_policy": exit_policy,
                    "tasks": [{
                        "id": "TASK-1", "kind": "framework_adoption",
                        "affected_control_ids": [control_id],
                        "assessed_scope": task_scope, "exit_policy": exit_policy,
                    }],
                }],
            }

        outside = self.lint_campaign(project, campaign(["outside"]))
        self.assertEqual(1, outside.returncode)
        outside_payload = json.loads(outside.stdout)
        self.assertIn(
            "CAMPAIGN_STRUCTURE_INVALID",
            {item["code"] for item in outside_payload["blocker_details"]},
        )
        registered = self.register_campaign(project, campaign(["outside"]))
        self.assertEqual(2, registered.returncode)
        self.assertIn("outside", registered.stderr)

        acquisition = self.lint_campaign(
            project, campaign(["component/src"]),
            "--phase-id", "PHASE-1", "--task-id", "TASK-1",
            "--require-path", "component/report.md",
            "--require-product-acquisition",
        )
        self.assertEqual(1, acquisition.returncode)
        payload = json.loads(acquisition.stdout)
        codes = {item["code"] for item in payload["blocker_details"]}
        self.assertIn("REQUIRED_PATH_OUTSIDE_TASK_SCOPE", codes)
        self.assertIn("PRODUCT_ACQUISITION_CAPABILITIES_UNMODELED", codes)

    def test_registry_validation_reports_malformed_collections_without_raising(self) -> None:
        module = self.load_quality_common()
        project = self.make_project()
        guardrails = project / ".guardrails"
        registry = json.loads((guardrails / "control-registry.yaml").read_text())
        traceability = json.loads((guardrails / "traceability-graph.json").read_text())

        for collection in (
            "capabilities", "baselines", "cleanup_debts",
            "design_scope_exemptions", "federated_rule_mappings",
        ):
            with self.subTest(collection=collection):
                malformed = json.loads(json.dumps(registry))
                malformed[collection] = None
                errors = module.validate_registry(malformed)
                self.assertIn(
                    f"control registry {collection} must be an array",
                    errors,
                )
                self.assertIsInstance(
                    module.validate_traceability(traceability, malformed), list,
                )

        malformed = json.loads(json.dumps(registry))
        malformed["controls"] = [None, {
            "evaluation_mode": "ratchet_delta",
            "ratchet_policy": None,
        }]
        errors = module.validate_registry(malformed)
        self.assertIn("controls[0] must be an object", errors)
        self.assertIn(
            "controls[1].ratchet_policy.baseline_ref references an unknown baseline",
            errors,
        )
        self.assertIsInstance(
            module.validate_traceability(traceability, malformed), list,
        )
        malformed_traceability = json.loads(json.dumps(traceability))
        malformed_traceability["links"] = [{"control_id": {}}]
        self.assertIn(
            "traceability links[0].control_id is required",
            module.validate_traceability(malformed_traceability, registry),
        )
        self.assertEqual(
            ["quality manifest must be an object"],
            module.validate_manifest(None),
        )
        self.assertEqual(
            ["control registry must be an object"],
            module.validate_registry(None),
        )
        self.assertEqual(
            ["traceability graph must be an object"],
            module.validate_traceability(None, registry),
        )
        self.assertEqual(
            ["evidence ledger must be an object"],
            module.validate_ledger(None),
        )

    def test_campaign_lint_fails_closed_for_malformed_framework_roots(self) -> None:
        for filename in (
            "quality-manifest.yaml", "control-registry.yaml",
            "traceability-graph.json",
        ):
            with self.subTest(filename=filename):
                project = self.make_project(development_mode="ai_brownfield")
                guardrails = project / ".guardrails"
                registry = json.loads((guardrails / "control-registry.yaml").read_text())
                control_id = registry["controls"][0]["id"]
                exit_policy = {
                    "max_new_violations": 0,
                    "minimum_fixed_violations": 0,
                    "allow_open_cleanup_debt": True,
                }
                campaign = {
                    "id": "ROOT-SHAPE", "revision": 1,
                    "target_maturity": "prototype", "assessed_scope": ["."],
                    "owner": "quality",
                    "phases": [{
                        "id": "PHASE-1", "title": "Root shape",
                        "affected_control_ids": [control_id], "assessed_scope": ["."],
                        "exit_policy": exit_policy,
                        "tasks": [{
                            "id": "TASK-1", "kind": "framework_adoption",
                            "affected_control_ids": [control_id], "assessed_scope": ["."],
                            "exit_policy": exit_policy,
                        }],
                    }],
                }
                (guardrails / filename).write_text("null\n", encoding="utf-8")

                result = self.lint_campaign(project, campaign)

                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                self.assertEqual("", result.stderr)
                self.assertNotIn("Traceback", result.stdout)
                payload = json.loads(result.stdout)
                self.assertEqual("CAMPAIGN_LINT_ERROR", payload["status"])
                self.assertIn(
                    "INPUT_UNAVAILABLE",
                    {item["code"] for item in payload["blocker_details"]},
                )

    def test_campaign_lint_returns_typed_blockers_for_malformed_nested_input(self) -> None:
        exit_policy = {
            "max_new_violations": 0,
            "minimum_fixed_violations": 0,
            "allow_open_cleanup_debt": True,
        }

        for case in (
            "phases_none", "task_arrays_none", "control_without_id", "controls_none",
            "capabilities_none", "capability_id_object", "command_nested_array",
            "baseline_control_object",
        ):
            with self.subTest(case=case):
                project = self.make_project(development_mode="ai_brownfield")
                registry_path = project / ".guardrails" / "control-registry.yaml"
                registry = json.loads(registry_path.read_text())
                control_id = registry["controls"][0]["id"]
                campaign = {
                    "id": "MALFORMED-CAMPAIGN", "revision": 1,
                    "target_maturity": "prototype", "assessed_scope": ["component"],
                    "owner": "quality",
                    "phases": [{
                        "id": "PHASE-1", "title": "Malformed fixture",
                        "affected_control_ids": [control_id],
                        "assessed_scope": ["component"], "exit_policy": exit_policy,
                        "tasks": [{
                            "id": "TASK-1", "kind": "framework_adoption",
                            "affected_control_ids": [control_id],
                            "assessed_scope": ["component/src"],
                            "exit_policy": exit_policy,
                        }],
                    }],
                }
                if case == "phases_none":
                    campaign["phases"] = None
                elif case == "task_arrays_none":
                    campaign["phases"][0]["tasks"][0]["affected_control_ids"] = None
                    campaign["phases"][0]["tasks"][0]["assessed_scope"] = None
                elif case == "control_without_id":
                    registry["controls"] = [{}]
                    registry_path.write_text(json.dumps(registry, indent=2) + "\n")
                elif case == "controls_none":
                    registry["controls"] = None
                    registry_path.write_text(json.dumps(registry, indent=2) + "\n")
                elif case == "capabilities_none":
                    registry["capabilities"] = None
                    registry_path.write_text(json.dumps(registry, indent=2) + "\n")
                elif case == "capability_id_object":
                    registry["capabilities"].append({
                        "id": {}, "owner": "quality", "authorization_required": False,
                        "preflight": {
                            "command": ["true"], "cwd": ".", "timeout_seconds": 1,
                        },
                    })
                    registry_path.write_text(json.dumps(registry, indent=2) + "\n")
                elif case == "command_nested_array":
                    registry["controls"][0]["execution"]["command"] = [[], "x"]
                    registry_path.write_text(json.dumps(registry, indent=2) + "\n")
                elif case == "baseline_control_object":
                    registry["baselines"].append({
                        "id": "MALFORMED-BASELINE", "control_id": {}, "revision": 1,
                        "source_ref": "baseline.json", "source_sha256": "0" * 64,
                        "violation_count": 0,
                    })
                    registry_path.write_text(json.dumps(registry, indent=2) + "\n")

                result = self.lint_campaign(
                    project, campaign,
                    "--phase-id", "PHASE-1", "--task-id", "TASK-1",
                )
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertEqual("", result.stderr)
                self.assertNotIn("Traceback", result.stdout)
                payload = json.loads(result.stdout)
                self.assertEqual("CAMPAIGN_LINT_BLOCKED", payload["status"])
                codes = {item["code"] for item in payload["blocker_details"]}
                expected = (
                    "FRAMEWORK_INVALID"
                    if case not in {"phases_none", "task_arrays_none"}
                    else "CAMPAIGN_STRUCTURE_INVALID"
                )
                self.assertIn(expected, codes)

    def test_control_plane_entrypoints_fail_closed_for_non_array_controls(self) -> None:
        project = self.make_project(development_mode="ai_brownfield")
        guardrails = project / ".guardrails"
        registry_path = guardrails / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        registry["controls"] = None
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        campaign_path = project / "campaign.json"
        campaign_path.write_text("{}\n", encoding="utf-8")
        core_files = (
            "quality-manifest.yaml", "control-registry.yaml",
            "evidence-ledger.json", "traceability-graph.json",
        )
        before = {name: (guardrails / name).read_bytes() for name in core_files}
        commands = {
            "readiness": [sys.executable, str(READINESS), "--root", str(project)],
            "evaluate": [
                sys.executable, str(EVALUATE), "--root", str(project), "--dry-run",
            ],
            "register": [
                sys.executable, str(REGISTER), "--root", str(project),
                "--campaign", str(campaign_path),
            ],
            "review": [
                sys.executable, str(REVIEW_UPDATE), "--root", str(project), "--check",
            ],
            "seal": [
                sys.executable, str(SEAL), "--root", str(project),
                "--archive-id", "malformed-registry-fixture",
            ],
            "lint": [
                sys.executable, str(LINT_CAMPAIGN), "--root", str(project),
                "--campaign", str(campaign_path),
            ],
            "handoff": [
                sys.executable, str(HANDOFF), "--root", str(project),
                "--campaign-id", "MALFORMED", "--campaign-revision", "1",
                "--phase-id", "PHASE-1", "--task-id", "TASK-1", "--check",
            ],
        }
        diagnostic_markers = {
            "readiness": '"status": "BLOCKED"',
            "evaluate": "FAIL [QF-FRAMEWORK]",
            "register": "FAIL [QF-FRAMEWORK]",
            "review": '"status": "error"',
            "seal": "cannot seal invalid active control plane",
            "lint": '"status": "CAMPAIGN_LINT_BLOCKED"',
            "handoff": '"status": "HANDOFF_ERROR"',
        }
        for name, command in commands.items():
            with self.subTest(entrypoint=name):
                result = subprocess.run(
                    command, check=False, capture_output=True, text=True,
                )
                combined = result.stdout + result.stderr
                self.assertNotEqual(0, result.returncode, combined)
                self.assertNotIn("Traceback", combined)
                self.assertTrue(combined.strip())
                self.assertIn(diagnostic_markers[name], combined)
        after = {name: (guardrails / name).read_bytes() for name in core_files}
        self.assertEqual(before, after)
        self.assertFalse((guardrails / "archive" / "malformed-registry-fixture").exists())
        self.assertFalse((guardrails / "evidence" / "task-handoff.md").exists())

    def test_shared_validators_reject_nested_json_shape_mutations_without_raising(self) -> None:
        project = self.make_project()
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_id = registry["controls"][0]["id"]
        for stage in ("self", "cross", "release_authority"):
            result = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"shape-fixture-{stage}", "--control", control_id,
            )
            self.assertEqual(0, result.returncode, result.stderr)
        claim = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control_id,
        )
        self.assertEqual(0, claim.returncode, claim.stderr)

        module = self.load_quality_common()
        guardrails = project / ".guardrails"
        documents = {
            name: json.loads((guardrails / name).read_text())
            for name in (
                "quality-manifest.yaml", "control-registry.yaml",
                "traceability-graph.json", "evidence-ledger.json",
            )
        }
        registry = documents["control-registry.yaml"]
        control_ids = module.registry_control_ids(registry)
        validators = {
            "quality-manifest.yaml": lambda value: module.validate_manifest(
                value, control_ids,
            ),
            "control-registry.yaml": module.validate_registry,
            "traceability-graph.json": lambda value: module.validate_traceability(
                value, registry,
            ),
            "evidence-ledger.json": lambda value: module.validate_ledger(value, project),
        }

        def nested_paths(value, path=()):
            if path:
                yield path
            if isinstance(value, dict):
                for key, child in value.items():
                    yield from nested_paths(child, (*path, key))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from nested_paths(child, (*path, index))

        def shape_mutation(value, path):
            candidate = copy.deepcopy(value)
            parent = candidate
            for part in path[:-1]:
                parent = parent[part]
            current = parent[path[-1]]
            parent[path[-1]] = None if isinstance(current, (dict, list)) else {}
            return candidate

        for name, document in documents.items():
            validator = validators[name]
            paths = list(nested_paths(document))
            self.assertTrue(paths)
            for path in paths:
                with self.subTest(document=name, path=path):
                    errors = validator(shape_mutation(document, path))
                    self.assertTrue(errors, f"mutation was accepted: {name}:{path}")

    def test_json_integer_and_execution_contracts_fail_closed(self) -> None:
        module = self.load_quality_common()
        project = self.make_project(development_mode="ai_brownfield")
        guardrails = project / ".guardrails"
        registry = json.loads((guardrails / "control-registry.yaml").read_text())

        file_control = copy.deepcopy(registry)
        file_control["controls"][0]["execution"].pop("path")
        self.assertIn(
            "controls[0].execution.path is required for file path controls",
            module.validate_registry(file_control),
        )

        command_timeout = copy.deepcopy(registry)
        command_timeout["controls"][0]["execution"] = {
            "type": "command", "command": ["true"],
            "timeout_seconds": True, "authorization_required": False,
        }
        self.assertIn(
            "controls[0].execution.timeout_seconds is invalid",
            module.validate_registry(command_timeout),
        )

        capability_timeout = copy.deepcopy(registry)
        capability_timeout["capabilities"].append({
            "id": "fixture", "owner": "quality", "authorization_required": False,
            "preflight": {
                "command": ["true"], "cwd": ".", "timeout_seconds": True,
            },
        })
        self.assertIn(
            "capabilities[0].preflight.timeout_seconds is invalid",
            module.validate_registry(capability_timeout),
        )

        baseline = copy.deepcopy(registry)
        baseline["baselines"].append({
            "id": "FIXTURE", "control_id": registry["controls"][0]["id"],
            "revision": True, "source_ref": "baseline.json",
            "source_sha256": "0" * 64, "violation_count": False,
        })
        baseline_errors = module.validate_registry(baseline)
        self.assertIn("baselines[0].revision must be an integer >= 1", baseline_errors)
        self.assertIn(
            "baselines[0].violation_count must be a non-negative integer",
            baseline_errors,
        )

        exit_errors = module.validate_exit_policy({
            "max_new_violations": True,
            "minimum_fixed_violations": False,
            "allow_open_cleanup_debt": True,
        }, "exit")
        self.assertIn("exit.max_new_violations must be a non-negative integer", exit_errors)
        self.assertIn("exit.minimum_fixed_violations must be a non-negative integer", exit_errors)
        self.assertIsNone(module.selected_source_sha256(
            project / "README.md",
            {"kind": "markdown_heading", "value": "# Fixture", "occurrence": True},
        ))

        traceability = json.loads(
            (guardrails / "traceability-graph.json").read_text()
        )
        traceability["links"][0]["requirement_ids"] = ["REQ.FORGED"]
        self.assertIn(
            "traceability graph content does not match the control registry",
            module.validate_traceability(traceability, registry),
        )

        campaign_path = project / "malformed-campaign.json"
        for revision in (True, {}):
            with self.subTest(campaign_revision=revision):
                campaign_path.write_text(json.dumps({"revision": revision}) + "\n")
                result = subprocess.run(
                    [
                        sys.executable, str(REGISTER), "--root", str(project),
                        "--campaign", str(campaign_path),
                    ],
                    check=False, capture_output=True, text=True,
                )
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertIn("campaign revision must be an integer", result.stderr)

    def test_update_and_predecessor_metadata_reject_object_enums(self) -> None:
        review_module = self.load_script_module(
            "review_skill_update_enum_fixture", REVIEW_UPDATE,
        )
        declaration = Path(tempfile.mkdtemp()) / "update.json"
        declaration.write_text(json.dumps({
            "schema_version": "3.0", "change_class": {}, "compatible": True,
            "affected_control_ids": ["*"], "summary": "fixture",
        }) + "\n")
        with self.assertRaisesRegex(ValueError, "change_class is invalid"):
            review_module.load_declaration(declaration)

        init_module = self.load_script_module(
            "init_quality_framework_enum_fixture", INIT,
        )
        guardrails = Path(tempfile.mkdtemp())
        archive = guardrails / "archive" / "fixture"
        archive.mkdir(parents=True)
        manifest = {
            "archive_id": "fixture", "validation_status": {},
            "signature_status": "untrusted", "files": [],
        }
        manifest["archive_sha256"] = init_module.canonical_digest(manifest)
        (archive / "archive-manifest.json").write_text(
            json.dumps(manifest) + "\n", encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "validation status is invalid"):
            init_module.predecessor_archive_binding(guardrails, "fixture")

    def test_readiness_blocks_drifted_ai_brownfield_campaign(self) -> None:
        project = self.make_project(development_mode="ai_brownfield")
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_id = registry["controls"][0]["id"]
        exit_policy = {
            "max_new_violations": 0,
            "minimum_fixed_violations": 0,
            "allow_open_cleanup_debt": True,
        }
        registered = self.register_campaign(project, {
            "id": "DRIFT-CAMPAIGN", "revision": 1,
            "target_maturity": "prototype", "assessed_scope": ["."],
            "owner": "quality",
            "phases": [{
                "id": "PHASE-1", "title": "Framework adoption",
                "affected_control_ids": [control_id], "assessed_scope": ["."],
                "exit_policy": exit_policy,
                "tasks": [{
                    "id": "TASK-1", "kind": "framework_adoption",
                    "affected_control_ids": [control_id], "assessed_scope": ["."],
                    "exit_policy": exit_policy,
                }],
            }],
        })
        self.assertEqual(0, registered.returncode, registered.stderr)
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["development_policy"]["active_campaign"]["baseline_binding"][
            "registry_sha256"
        ] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        result = subprocess.run(
            [
                sys.executable, str(READINESS), "--root", str(project),
                "--campaign-id", "DRIFT-CAMPAIGN", "--campaign-revision", "1",
                "--phase-id", "PHASE-1", "--task-id", "TASK-1",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        levels = json.loads(result.stdout)["levels"]
        for level in ("DEVELOPMENT_START_READY", "TASK_CLAIM_READY", "MERGE_READY"):
            self.assertEqual("BLOCKED", levels[level]["status"])
            self.assertIn(
                "registry drift requires a campaign revision",
                levels[level]["blockers"],
            )

    def test_ai_brownfield_readiness_requires_exact_typed_task_context(self) -> None:
        project = self.make_project(development_mode="ai_brownfield")
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_id = registry["controls"][0]["id"]
        exit_policy = {
            "max_new_violations": 0,
            "minimum_fixed_violations": 0,
            "allow_open_cleanup_debt": True,
        }
        registered = self.register_campaign(project, {
            "id": "CONTEXT-CAMPAIGN", "revision": 7,
            "target_maturity": "prototype", "assessed_scope": ["."],
            "owner": "quality",
            "phases": [{
                "id": "PHASE-1", "title": "Context fixture",
                "affected_control_ids": [control_id], "assessed_scope": ["."],
                "exit_policy": exit_policy,
                "tasks": [
                    {
                        "id": task_id, "kind": "framework_adoption",
                        "affected_control_ids": [control_id], "assessed_scope": ["."],
                        "exit_policy": exit_policy,
                    }
                    for task_id in ("TASK-1", "TASK-2")
                ],
            }],
        })
        self.assertEqual(0, registered.returncode, registered.stderr)

        def assess(*context: str) -> dict:
            result = subprocess.run(
                [sys.executable, str(READINESS), "--root", str(project), *context],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            return json.loads(result.stdout)

        complete = assess(
            "--campaign-id", "CONTEXT-CAMPAIGN", "--campaign-revision", "7",
            "--phase-id", "PHASE-1", "--task-id", "TASK-2",
        )
        self.assertEqual("1.1", complete["schema_version"])
        task_level = complete["levels"]["TASK_CLAIM_READY"]
        self.assertEqual("BLOCKED", task_level["status"])
        self.assertEqual([control_id], task_level["control_ids"])
        self.assertTrue(task_level["blocker_details"])

        wrong_revision = assess(
            "--campaign-id", "CONTEXT-CAMPAIGN", "--campaign-revision", "6",
            "--phase-id", "PHASE-1", "--task-id", "TASK-1",
        )["levels"]["TASK_CLAIM_READY"]
        self.assertEqual("NOT_EVALUATED", wrong_revision["status"])
        self.assertEqual(
            "CAMPAIGN_REVISION_MISMATCH",
            wrong_revision["blocker_details"][0]["code"],
        )

        missing_phase_task = assess(
            "--campaign-id", "CONTEXT-CAMPAIGN", "--campaign-revision", "7",
        )["levels"]["TASK_CLAIM_READY"]
        self.assertEqual("TASK_CONTEXT_MISSING", missing_phase_task["blocker_details"][0]["code"])
        self.assertEqual(
            ["phase_id", "task_id"],
            missing_phase_task["blocker_details"][0]["missing_fields"],
        )

        missing_task = assess(
            "--campaign-id", "CONTEXT-CAMPAIGN", "--campaign-revision", "7",
            "--phase-id", "PHASE-1",
        )["levels"]["TASK_CLAIM_READY"]
        self.assertEqual(["task_id"], missing_task["blocker_details"][0]["missing_fields"])

        unknown_task = assess(
            "--campaign-id", "CONTEXT-CAMPAIGN", "--campaign-revision", "7",
            "--phase-id", "PHASE-1", "--task-id", "TASK-UNKNOWN",
        )["levels"]["TASK_CLAIM_READY"]
        self.assertEqual("CAMPAIGN_TASK_UNKNOWN", unknown_task["blocker_details"][0]["code"])

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

    def test_markdown_heading_selector_ignores_fenced_headings_and_occurrences(self) -> None:
        module = self.load_quality_common()
        root = Path(tempfile.mkdtemp(prefix="markdown-selector-test-"))
        source = root / "rules.md"
        text = (
            "# Primary\n"
            "before\n"
            "```text\n"
            "# Fenced fake\n"
            "## Repeated\n"
            "```\n"
            "after\n"
            "# Following\n"
            "following body\n"
            "## Repeated\n"
            "first real\n"
            "## Repeated\n"
            "second real\n"
        )
        source.write_text(text, encoding="utf-8")
        sections = module.markdown_heading_sections(text)
        selectors = [
            (section["value"], section["occurrence"])
            for section in sections
        ]
        self.assertEqual(
            [
                ("# Primary", 1), ("# Following", 1),
                ("## Repeated", 1), ("## Repeated", 2),
            ],
            selectors,
        )
        self.assertIsNone(module.selected_source_sha256(source, {
            "kind": "markdown_heading", "value": "# Fenced fake", "occurrence": 1,
        }))
        primary = text[:text.index("# Following")]
        self.assertEqual(
            hashlib.sha256(primary.encode()).hexdigest(),
            module.selected_source_sha256(source, {
                "kind": "markdown_heading", "value": "# Primary", "occurrence": 1,
            }),
        )
        following = text[text.index("# Following"):]
        self.assertEqual(
            hashlib.sha256(following.encode()).hexdigest(),
            module.selected_source_sha256(source, {
                "kind": "markdown_heading", "value": "# Following", "occurrence": 1,
            }),
        )
        second = "## Repeated\nsecond real\n"
        repeated_selector = {
            "kind": "markdown_heading", "value": "## Repeated", "occurrence": 2,
        }
        self.assertEqual(
            hashlib.sha256(second.encode()).hexdigest(),
            module.selected_source_sha256(source, repeated_selector),
        )
        self.assertEqual(
            module.selected_source_sha256(source, repeated_selector),
            module.selected_source_sha256(source, repeated_selector),
        )
        self.assertIsNone(module.selected_source_sha256(source, {
            "kind": "markdown_heading", "value": "## Repeated", "occurrence": 3,
        }))

    def test_markdown_heading_selector_honors_fence_marker_and_length(self) -> None:
        module = self.load_quality_common()
        root = Path(tempfile.mkdtemp(prefix="markdown-fence-test-"))
        fixtures = {
            "tilde-long-close.md": (
                "# Before\n~~~text\n# Tilde fake\n~~~~~\nbody\n# After\nreal\n",
                ["# Before", "# After"],
            ),
            "short-close.md": (
                "# Before\n````text\n# Fake one\n```\n# Fake two\n````\nbody\n# After\nreal\n",
                ["# Before", "# After"],
            ),
            "different-marker.md": (
                "# Before\n```text\n# Fake mixed\n~~~\n# Still fenced\n```\n# After\nreal\n",
                ["# Before", "# After"],
            ),
            "unclosed.md": (
                "# Before\n~~~text\n# Fake forever\n## Also fake\n",
                ["# Before"],
            ),
        }
        for name, (text, expected) in fixtures.items():
            with self.subTest(name=name):
                source = root / name
                source.write_text(text, encoding="utf-8")
                sections = module.markdown_heading_sections(text)
                self.assertEqual(expected, [section["value"] for section in sections])
                for fake in (
                    "# Tilde fake", "# Fake one", "# Fake two", "# Fake mixed",
                    "# Still fenced", "# Fake forever",
                ):
                    self.assertIsNone(module.selected_source_sha256(source, {
                        "kind": "markdown_heading", "value": fake, "occurrence": 1,
                    }))
        whole = root / "whole.md"
        whole.write_text("# Heading\nbody\n", encoding="utf-8")
        self.assertEqual(
            hashlib.sha256(whole.read_bytes()).hexdigest(),
            module.selected_source_sha256(whole, {
                "kind": "whole_file", "value": None, "occurrence": None,
            }),
        )

    def test_evaluator_and_registry_share_fence_aware_selector_digest(self) -> None:
        module = self.load_quality_common()
        text = (
            "# Real rule\n"
            "before\n"
            "```text\n"
            "# Example heading\n"
            "```\n"
            "after\n"
            "# Next rule\n"
            "next\n"
        )
        project = self.make_project({"AGENTS.md": text})
        source = project / "AGENTS.md"
        selector = {
            "kind": "markdown_heading", "value": "# Real rule", "occurrence": 1,
        }
        new_digest = module.selected_source_sha256(source, selector)
        self.assertIsNotNone(new_digest)

        lines = text.splitlines(keepends=True)
        start = next(index for index, line in enumerate(lines) if line.strip() == "# Real rule")
        old_end = next(
            index for index in range(start + 1, len(lines))
            if lines[index].lstrip().startswith("#")
        )
        old_digest = hashlib.sha256("".join(lines[start:old_end]).encode()).hexdigest()
        self.assertNotEqual(old_digest, new_digest)

        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control_id = registry["controls"][0]["id"]
        mapping = {
            "rule_id": "PROJECT.REAL_RULE",
            "source_ref": "AGENTS.md",
            "source_sha256": old_digest,
            "source_selector": selector,
            "disposition": "federated",
            "semantic_owner": "project-owner",
            "control_refs": [control_id],
            "mandatory": True,
            "status": "current",
            "observed_at": "2026-07-14T00:00:00+00:00",
            "reviewed_at": "2026-07-14T00:00:00+00:00",
        }
        registry["federated_rule_mappings"] = [mapping]
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, sync.returncode, sync.stdout + sync.stderr)
        stale = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control_id,
        )
        self.assertEqual(1, stale.returncode)
        self.assertIn("stale_project_rule:PROJECT.REAL_RULE", stale.stderr)

        registry = json.loads(registry_path.read_text())
        registry["federated_rule_mappings"][0]["source_sha256"] = new_digest
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, sync.returncode, sync.stdout + sync.stderr)
        for stage in ("self", "cross"):
            run = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}", "--control", control_id,
            )
            self.assertEqual(0, run.returncode, run.stderr)
        current = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control_id,
        )
        self.assertEqual(0, current.returncode, current.stderr)

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

    def test_evidence_only_commit_preserves_subject_evidence(self) -> None:
        project = self.make_project()
        control_id = "QF.FRAMEWORK.MANIFEST"
        for stage in ("self", "cross"):
            result = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}", "--control", control_id,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        ledger_path = project / ".guardrails" / "evidence-ledger.json"
        before = json.loads(ledger_path.read_text())
        subject = before["runs"][0]["subject_binding"]
        subprocess.run(
            ["git", "add", ".guardrails/evidence-ledger.json"],
            cwd=project, check=True,
        )
        subprocess.run(
            ["git", "commit", "-qm", "persist quality evidence"],
            cwd=project, check=True,
        )
        claim = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control_id,
        )
        self.assertEqual(claim.returncode, 0, claim.stderr)
        after = json.loads(ledger_path.read_text())
        self.assertEqual(subject, after["runs"][1]["subject_binding"])
        self.assertRegex(subject["tree_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            after["claims"][-1]["storage_binding"]["runs_chain_head_sha256"],
            r"^[0-9a-f]{64}$",
        )
        (project / "README.md").write_text("# Changed subject\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "change audited subject"],
            cwd=project, check=True,
        )
        stale = self.run_evaluator(
            project, "--claim", "--claim-scope", "task", "--control", control_id,
        )
        self.assertEqual(1, stale.returncode)
        self.assertIn("controls without current PASS", stale.stderr)

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
            "source_selector": {"kind": "whole_file", "value": None, "occurrence": None},
            "disposition": "federated",
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
            "command": [
                sys.executable, "-c",
                "import sys; sys.stdout.write('HEAD-' + 'Bearer x ' * 1000 + "
                "'h' * 40995 + "
                "'omitted-middle-' + 'm' * 49985 + 't' * 49995 + '-TAIL')",
            ],
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
        self.assertEqual(150000, result["raw_output_bytes"])
        self.assertEqual(65536, result["output_bytes"])
        raw = (
            b"HEAD-" + b"Bearer x " * 1000 + b"h" * 40995
            + b"omitted-middle-" + b"m" * 49985
            + b"t" * 49995 + b"-TAIL"
        )
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result["raw_output_sha256"])
        persisted = (project / result["output_ref"]).read_text()
        self.assertTrue(persisted.startswith("HEAD-"))
        self.assertTrue(persisted.endswith("-TAIL"))
        self.assertIn("RAW_OMITTED_BYTES=", persisted)
        self.assertIn("REDACTION_OMITTED_BYTES=", persisted)
        self.assertNotIn("Bearer x", persisted)
        self.assertNotIn("omitted-middle-", persisted)

    def test_redaction_expansion_remains_within_output_limit(self) -> None:
        project = self.make_project()
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control = registry["controls"][0]
        control["execution"] = {
            "type": "command",
            "command": [
                sys.executable, "-c",
                "import sys; sys.stdout.write('BEGIN-' + 'Bearer x ' * 7279 + 'END')",
            ],
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
        persisted = (project / result["output_ref"]).read_text()
        self.assertTrue(result["output_truncated"])
        self.assertLessEqual(result["output_bytes"], 65536)
        self.assertIn("RAW_OMITTED_BYTES=00000000000000000000", persisted)
        self.assertIn("REDACTION_OMITTED_BYTES=", persisted)
        self.assertNotIn("Bearer x", persisted)
        self.assertTrue(persisted.endswith("END"))

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

    def test_scanner_excludes_generated_guardrails_from_project_samples(self) -> None:
        project = Path(tempfile.mkdtemp(prefix="quality-scan-self-test-"))
        (project / "src").mkdir()
        (project / "src" / "lib.py").write_text("VALUE = 1\n", encoding="utf-8")
        guardrails = project / ".guardrails"
        guardrails.mkdir()
        (guardrails / "INDEX.md").write_text("# Generated index\n", encoding="utf-8")
        (guardrails / "generated.py").write_text("raise RuntimeError('generated')\n", encoding="utf-8")
        output = project / "scan.json"
        result = subprocess.run(
            [sys.executable, str(SCAN), "--root", str(project), "--out", str(output)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        scan = json.loads(output.read_text())
        self.assertEqual(1, scan["languages"]["python"])
        self.assertNotIn(".guardrails/INDEX.md", scan["module_index_samples"])
        self.assertIn(".guardrails/INDEX.md", scan["evidence"]["guardrails"])

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

    def test_scanner_discovers_nested_skills_without_truncating_rules(self) -> None:
        project = Path(tempfile.mkdtemp(prefix="quality-scan-rules-test-"))
        for index in range(45):
            path = project / f"area-{index:02d}" / "AGENTS.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"# Rule {index}\n", encoding="utf-8")
        nested_skill = project / ".claude" / "skills" / "testing" / "SKILL.md"
        nested_skill.parent.mkdir(parents=True)
        nested_skill.write_text("---\nname: testing\ndescription: fixture\n---\n", encoding="utf-8")
        output = project / "scan.json"
        result = subprocess.run(
            [sys.executable, str(SCAN), "--root", str(project), "--out", str(output)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        paths = {item["path"] for item in json.loads(output.read_text())["instruction_files"]}
        self.assertEqual(46, len(paths))
        self.assertIn(".claude/skills/testing/SKILL.md", paths)
        self.assertIn("area-44/AGENTS.md", paths)

    def test_manifest_framework_binding_drift_blocks_evaluation(self) -> None:
        project = self.make_project()
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["framework"]["content_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        result = self.run_evaluator(project, "--dry-run")
        self.assertEqual(1, result.returncode)
        self.assertIn("active Skill revision/content/trust differs", result.stderr)

    def test_skill_update_check_is_read_only_and_apply_preserves_project_files(self) -> None:
        project = self.make_project()
        guardrails = project / ".guardrails"
        manifest_path = guardrails / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["framework"]["content_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        decisions = guardrails / "decisions.md"
        decisions.write_text("# Project-owned decision\n", encoding="utf-8")
        declaration = project.parent / f"{project.name}-compatible-update.json"
        declaration.write_text(json.dumps({
            "schema_version": "3.0",
            "change_class": "presentation",
            "compatible": True,
            "affected_control_ids": ["*"],
            "summary": "Fixture presentation update.",
        }) + "\n")
        before = {path: path.read_bytes() for path in guardrails.rglob("*") if path.is_file()}
        checked = subprocess.run(
            [
                sys.executable, str(REVIEW_UPDATE), "--root", str(project),
                "--declaration", str(declaration), "--check",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(1, checked.returncode, checked.stderr)
        self.assertEqual("update_available", json.loads(checked.stdout)["status"])
        self.assertEqual(before, {
            path: path.read_bytes() for path in guardrails.rglob("*") if path.is_file()
        })
        applied = subprocess.run(
            [
                sys.executable, str(REVIEW_UPDATE), "--root", str(project),
                "--declaration", str(declaration), "--apply",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, applied.returncode, applied.stderr)
        self.assertEqual("applied", json.loads(applied.stdout)["status"])
        self.assertEqual("# Project-owned decision\n", decisions.read_text())
        updated = json.loads(manifest_path.read_text())
        self.assertNotEqual("0" * 64, updated["framework"]["content_sha256"])

    def test_default_update_declaration_treats_reviewed_docs_as_control_logic(self) -> None:
        module = self.load_script_module("review_skill_update_fixture", REVIEW_UPDATE)
        self.assertEqual("presentation", module.inferred_change_class([]))
        for paths in (
            ["SKILL.md"],
            ["references/30-harness-catalog.md"],
            ["scripts/render_task_handoff.py"],
            ["templates/preflight.py"],
        ):
            with self.subTest(paths=paths):
                self.assertEqual("control_logic", module.inferred_change_class(paths))
        self.assertEqual(
            "schema", module.inferred_change_class(["schemas/control-registry.schema.json"]),
        )
        self.assertEqual("incompatible_semantics", module.inferred_change_class(None))

    def test_skill_update_refuses_incompatible_schema_without_mutation(self) -> None:
        project = self.make_project()
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["schema_version"] = "2.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        before = manifest_path.read_bytes()
        result = subprocess.run(
            [sys.executable, str(REVIEW_UPDATE), "--root", str(project), "--apply"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(2, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("schema", report["change_class"])
        self.assertTrue(report["requires_seal"])
        self.assertEqual(before, manifest_path.read_bytes())

    def test_compatible_skill_update_increments_active_campaign_revision(self) -> None:
        project = self.make_project(development_mode="ai_brownfield")
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_id = registry["controls"][0]["id"]
        exit_policy = {
            "max_new_violations": 0,
            "minimum_fixed_violations": 0,
            "allow_open_cleanup_debt": True,
        }
        registered = self.register_campaign(project, {
            "id": "UPDATE-CAMPAIGN", "revision": 1,
            "target_maturity": "prototype", "assessed_scope": ["."],
            "owner": "quality",
            "phases": [{
                "id": "PHASE-1", "title": "Framework update",
                "affected_control_ids": [control_id], "assessed_scope": ["."],
                "exit_policy": exit_policy,
                "tasks": [{
                    "id": "TASK-1", "kind": "framework_adoption",
                    "affected_control_ids": [control_id], "assessed_scope": ["."],
                    "exit_policy": exit_policy,
                }],
            }],
        })
        self.assertEqual(0, registered.returncode, registered.stderr)
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["framework"]["content_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        declaration = project.parent / f"{project.name}-campaign-update.json"
        declaration.write_text(json.dumps({
            "schema_version": "3.0", "change_class": "control_logic",
            "compatible": True, "affected_control_ids": [control_id],
            "summary": "Fixture control update.",
        }) + "\n")
        applied = subprocess.run(
            [
                sys.executable, str(REVIEW_UPDATE), "--root", str(project),
                "--declaration", str(declaration), "--apply",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, applied.returncode, applied.stderr)
        updated = json.loads(manifest_path.read_text())
        campaign = updated["development_policy"]["active_campaign"]
        self.assertEqual(2, campaign["revision"])
        self.assertEqual(
            updated["framework"]["content_sha256"],
            campaign["baseline_binding"]["framework_sha256"],
        )

    def test_readiness_distinguishes_handoff_merge_and_release_without_writes(self) -> None:
        project = self.make_project()
        control_id = "QF.FRAMEWORK.MANIFEST"
        initial = subprocess.run(
            [
                sys.executable, str(READINESS), "--root", str(project),
                "--control", control_id,
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, initial.returncode, initial.stderr)
        levels = json.loads(initial.stdout)["levels"]
        self.assertEqual("READY", levels["DEVELOPMENT_START_READY"]["status"])
        self.assertEqual("BLOCKED", levels["TASK_CLAIM_READY"]["status"])
        self.assertEqual("BLOCKED", levels["MERGE_READY"]["status"])
        self.assertEqual("BLOCKED", levels["RELEASE_READY"]["status"])
        for stage in ("self", "cross"):
            result = self.run_evaluator(
                project, "--run", "--audit-stage", stage,
                "--actor", f"fixture-{stage}", "--control", control_id,
            )
            self.assertEqual(0, result.returncode, result.stderr)
        guardrails = project / ".guardrails"
        before = {path: path.read_bytes() for path in guardrails.rglob("*") if path.is_file()}
        ready = subprocess.run(
            [
                sys.executable, str(READINESS), "--root", str(project),
                "--control", control_id, "--require-level", "TASK_CLAIM_READY",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, ready.returncode, ready.stderr)
        levels = json.loads(ready.stdout)["levels"]
        self.assertEqual("READY", levels["TASK_CLAIM_READY"]["status"])
        self.assertEqual("READY", levels["MERGE_READY"]["status"])
        self.assertEqual("BLOCKED", levels["RELEASE_READY"]["status"])
        self.assertEqual(before, {
            path: path.read_bytes() for path in guardrails.rglob("*") if path.is_file()
        })

    def test_handoff_requires_task_claim_readiness_and_accepts_typed_blocked(self) -> None:
        module = self.load_script_module("render_task_handoff_fixture", HANDOFF)
        args = argparse.Namespace(
            guardrails_dir=".guardrails", campaign_id="CAMPAIGN-1",
            campaign_revision=7, phase_id="PHASE-1", task_id="TASK-1",
        )
        report = {
            "schema_version": "1.1",
            "subject_binding": {"commit": "fixture"},
            "levels": {
                "TASK_CLAIM_READY": {
                    "status": "BLOCKED", "control_ids": [],
                    "blockers": ["evidence missing"],
                    "blocker_details": [{
                        "code": "QUALITY_BLOCKER", "category": "quality",
                        "message": "evidence missing",
                    }],
                },
            },
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(report), stderr="",
        )
        with mock.patch.object(module.subprocess, "run", return_value=completed) as run:
            self.assertEqual(report, module.readiness_report(args, Path("/project")))
        command = run.call_args.args[0]
        require_index = command.index("--require-level")
        self.assertEqual("TASK_CLAIM_READY", command[require_index + 1])
        self.assertIn("--campaign-id", command)
        self.assertIn("--campaign-revision", command)
        self.assertIn("--phase-id", command)
        self.assertIn("--task-id", command)

        invalid = json.loads(json.dumps(report))
        invalid["levels"]["TASK_CLAIM_READY"]["blocker_details"] = []
        with self.assertRaisesRegex(ValueError, "typed blocker_details"):
            module.validate_readiness_report(invalid, 1)
        with self.assertRaisesRegex(ValueError, "infrastructure exit 2"):
            module.validate_readiness_report(report, 2)
        invalid_json = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="not-json", stderr="fixture failure",
        )
        with mock.patch.object(module.subprocess, "run", return_value=invalid_json):
            with self.assertRaisesRegex(ValueError, "did not return JSON"):
                module.readiness_report(args, Path("/project"))

    def test_generated_task_handoff_is_deterministic_and_stale_on_campaign_revision(self) -> None:
        project = self.make_project(development_mode="ai_brownfield")
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_id = registry["controls"][0]["id"]
        exit_policy = {
            "max_new_violations": 0,
            "minimum_fixed_violations": 0,
            "allow_open_cleanup_debt": True,
        }

        def campaign(revision: int) -> dict:
            return {
                "id": "HANDOFF-CAMPAIGN", "revision": revision,
                "target_maturity": "prototype", "assessed_scope": ["."],
                "owner": "quality",
                "phases": [{
                    "id": "PHASE-1", "title": "Portable handoff",
                    "affected_control_ids": [control_id], "assessed_scope": ["."],
                    "exit_policy": exit_policy,
                    "tasks": [{
                        "id": "TASK-1", "kind": "framework_adoption",
                        "affected_control_ids": [control_id],
                        "assessed_scope": ["src", "tests"],
                        "exit_policy": exit_policy,
                    }],
                }],
            }

        registered = self.register_campaign(project, campaign(1))
        self.assertEqual(0, registered.returncode, registered.stderr)
        context = [
            "--campaign-id", "HANDOFF-CAMPAIGN", "--campaign-revision", "1",
            "--phase-id", "PHASE-1", "--task-id", "TASK-1",
        ]
        rendered = subprocess.run(
            [sys.executable, str(HANDOFF), "--root", str(project), *context, "--write"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, rendered.returncode, rendered.stdout + rendered.stderr)
        handoff = project / ".guardrails" / "evidence" / "task-handoff.md"
        first = handoff.read_bytes()
        text = first.decode()
        payload = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertEqual(1, payload["campaign"]["revision"])
        self.assertEqual("TASK-1", payload["campaign"]["task_id"])
        self.assertEqual([control_id], payload["affected_control_ids"])
        self.assertEqual(["src", "tests"], payload["assessed_scope"])
        self.assertIn("TASK_CLAIM_READY", payload["readiness"])
        self.assertEqual("BLOCKED", payload["readiness"]["TASK_CLAIM_READY"]["status"])
        self.assertEqual(
            "MODELED", payload["capabilities"]["control_verification"]["status"],
        )
        acquisition = payload["capabilities"]["product_acquisition"]
        self.assertEqual("UNMODELED", acquisition["status"])
        self.assertEqual("NOT_EVALUATED", acquisition["applicability"])
        self.assertEqual("BLOCKED", acquisition["execution"])
        self.assertIsNone(acquisition["required_capability_ids"])
        self.assertTrue(acquisition["blocker_details"])
        self.assertNotIn("handoff_blocker_details", payload)
        self.assertTrue(payload["action_policy"]["machine_fields_are_authoritative"])

        rerendered = subprocess.run(
            [sys.executable, str(HANDOFF), "--root", str(project), *context, "--write"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, rerendered.returncode, rerendered.stdout + rerendered.stderr)
        self.assertEqual(first, handoff.read_bytes())
        current = subprocess.run(
            [sys.executable, str(HANDOFF), "--root", str(project), *context, "--check"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, current.returncode, current.stdout + current.stderr)

        clean_text = handoff.read_text()
        handoff.write_text(clean_text + "\ncampaign_revision: 99\n")
        override = subprocess.run(
            [sys.executable, str(HANDOFF), "--root", str(project), *context, "--check"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(1, override.returncode)
        self.assertEqual("MANUAL_OVERRIDE_REJECTED", json.loads(override.stdout)["status"])
        handoff.write_text(clean_text)

        replacement_path = project.parent / f"{project.name}-campaign-v2.json"
        replacement_path.write_text(json.dumps(campaign(2), indent=2) + "\n")
        replaced = subprocess.run(
            [
                sys.executable, str(REGISTER), "--root", str(project),
                "--campaign", str(replacement_path), "--replace-active",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, replaced.returncode, replaced.stderr)
        revision_two = [
            "--campaign-id", "HANDOFF-CAMPAIGN", "--campaign-revision", "2",
            "--phase-id", "PHASE-1", "--task-id", "TASK-1",
        ]
        stale = subprocess.run(
            [sys.executable, str(HANDOFF), "--root", str(project), *revision_two, "--check"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(1, stale.returncode, stale.stdout + stale.stderr)
        self.assertEqual("STALE_HANDOFF", json.loads(stale.stdout)["status"])

    def test_evidence_uses_project_relative_paths(self) -> None:
        project = self.make_project()
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        file_control = next(
            control for control in registry["controls"]
            if control["execution"]["type"] == "file_exists"
        )
        result = self.run_evaluator(project, "--run", "--control", file_control["id"])
        self.assertEqual(0, result.returncode, result.stderr)
        script = project / "absolute-command.py"
        script.write_text("pass\n", encoding="utf-8")
        file_control["execution"] = {
            "type": "command", "command": [sys.executable, str(script)],
            "cwd": ".", "timeout_seconds": 10, "authorization_required": False,
        }
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, sync.returncode, sync.stderr)
        result = self.run_evaluator(project, "--run", "--control", file_control["id"])
        self.assertEqual(0, result.returncode, result.stderr)
        ledger = json.loads(
            (project / ".guardrails" / "evidence-ledger.json").read_text()
        )
        file_result = ledger["runs"][-2]["results"][0]
        command_result = ledger["runs"][-1]["results"][0]
        self.assertFalse(Path(file_result["path"]).is_absolute())
        self.assertFalse(Path(command_result["cwd"]).is_absolute())
        persisted_command = json.dumps(command_result["command"])
        self.assertNotIn(str(project), persisted_command)
        self.assertIn("[PROJECT_ROOT]", persisted_command)
        self.assertRegex(command_result["command_sha256"], r"^[0-9a-f]{64}$")

    def test_scanner_excludes_gitignored_local_instruction_overrides(self) -> None:
        project = Path(tempfile.mkdtemp(prefix="quality-scan-ignore-test-"))
        (project / "AGENTS.md").write_text("# Shared\n", encoding="utf-8")
        (project / "CLAUDE.local.md").write_text("# Local\n", encoding="utf-8")
        (project / ".gitignore").write_text("CLAUDE.local.md\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        subprocess.run(["git", "add", "AGENTS.md", ".gitignore"], cwd=project, check=True)
        output = project / "scan.json"
        result = subprocess.run(
            [sys.executable, str(SCAN), "--root", str(project), "--out", str(output)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        paths = {item["path"] for item in json.loads(output.read_text())["instruction_files"]}
        self.assertIn("AGENTS.md", paths)
        self.assertNotIn("CLAUDE.local.md", paths)

    def test_generation_primitives_are_deduplicated_bounded_and_transactional(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "generation_common_fixture", ROOT / "scripts" / "generation_common.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        records = module.deduplicate_source_records([
            {"source_ref": "AGENTS.md"},
            {"source_ref": "AGENTS.md"},
            {"source_ref": ".guardrails/INDEX.md"},
            {"source_ref": "CLAUDE.md", "generated_adapter": True},
            {"source_ref": "docs/rules.md"},
        ])
        self.assertEqual(["AGENTS.md", "docs/rules.md"], [
            record["source_ref"] for record in records
        ])
        diagnostics = module.bounded_diagnostics(
            ["duplicate id"] * 100 + [f"problem-{index}" for index in range(100)],
            max_bytes=300, max_samples=3,
        )
        self.assertEqual(200, diagnostics["total_count"])
        self.assertLessEqual(len(diagnostics["samples"]), 3)
        self.assertTrue(diagnostics["truncated"])

        root = Path(tempfile.mkdtemp(prefix="generation-transaction-test-"))
        target = root / "target"
        candidate = root / "candidate"
        target.mkdir()
        candidate.mkdir()
        for name in ("a.txt", "b.txt"):
            (target / name).write_text(f"old-{name}\n")
            (candidate / name).write_text(f"new-{name}\n")
        original_replace = module.os.replace

        def fail_second_install(source: str | Path, destination: str | Path) -> None:
            if Path(source) == candidate / "b.txt" and Path(destination) == target / "b.txt":
                raise OSError("fixture replacement failure")
            original_replace(source, destination)

        with mock.patch.object(module.os, "replace", side_effect=fail_second_install):
            with self.assertRaises(OSError):
                module.transactional_replace_entries(
                    candidate, target, ("a.txt", "b.txt"),
                )
        self.assertEqual("old-a.txt\n", (target / "a.txt").read_text())
        self.assertEqual("old-b.txt\n", (target / "b.txt").read_text())

    def test_portable_execution_harness_candidate_accepts_only_closed_runtime_chain(self) -> None:
        digest = "a" * 64
        phases = {
            "capability_preflight": "pre_effect",
            "target_context_readiness": "pre_effect",
            "effect_attempt": "effect",
            "effect_execution_step": "effect",
            "effect_commit": "effect",
            "effect_outcome": "post_effect",
            "product_assertion": "post_effect",
            "cleanup": "post_effect",
        }
        hops = [
            {
                "hop_id": "browser-entry", "owner": "client-owner",
                "target": "client-session", "vantage_point": "browser", "depends_on": [],
            },
            {
                "hop_id": "container-runtime", "owner": "runtime-owner",
                "target": "runtime-container", "vantage_point": "container",
                "depends_on": ["browser-entry"],
            },
            {
                "hop_id": "host-provider", "owner": "platform-owner",
                "target": "host-provider", "vantage_point": "host",
                "depends_on": ["container-runtime"],
            },
            {
                "hop_id": "browser-assertion", "owner": "client-owner",
                "target": "client-session", "vantage_point": "browser",
                "depends_on": ["host-provider"],
            },
            {
                "hop_id": "host-cleanup", "owner": "platform-owner",
                "target": "host-provider", "vantage_point": "host",
                "depends_on": ["browser-assertion"],
            },
            {
                "hop_id": "container-cleanup", "owner": "runtime-owner",
                "target": "runtime-container", "vantage_point": "container",
                "depends_on": ["host-cleanup"],
            },
        ]
        capabilities = [
            {
                "capability_id": f"CAP-{hop['hop_id']}", "hop_id": hop["hop_id"],
                "owner": hop["owner"], "target": hop["target"],
                "vantage_point": hop["vantage_point"], "authorization_required": True,
            }
            for hop in hops
        ]
        observation_specs = [
            ("OBS-browser-preflight", "browser-entry", "capability_preflight", None, None, [], []),
            ("OBS-browser-ready", "browser-entry", "target_context_readiness", None, None, ["OBS-browser-preflight"], []),
            ("OBS-container-preflight", "container-runtime", "capability_preflight", None, None, ["OBS-browser-ready"], []),
            ("OBS-container-ready", "container-runtime", "target_context_readiness", None, None, ["OBS-container-preflight"], []),
            ("OBS-host-preflight", "host-provider", "capability_preflight", None, None, ["OBS-container-ready"], []),
            ("OBS-host-ready", "host-provider", "target_context_readiness", None, None, ["OBS-host-preflight"], []),
            ("OBS-effect-attempt", "browser-entry", "effect_attempt", "EFFECT-1", None, ["OBS-host-ready"], []),
            ("OBS-effect-step", "container-runtime", "effect_execution_step", "EFFECT-1", None, ["OBS-effect-attempt"], ["OBS-effect-attempt"]),
            ("OBS-effect-commit", "host-provider", "effect_commit", "EFFECT-1", None, ["OBS-effect-step"], ["OBS-effect-step"]),
            ("OBS-effect-outcome", "host-provider", "effect_outcome", "EFFECT-1", "committed", ["OBS-effect-commit"], ["OBS-effect-commit"]),
            ("OBS-browser-assert", "browser-assertion", "product_assertion", "EFFECT-1", "committed", ["OBS-effect-outcome"], ["OBS-effect-outcome"]),
            ("OBS-host-cleanup", "host-cleanup", "cleanup", None, None, ["OBS-browser-assert"], ["OBS-browser-assert"]),
            ("OBS-container-cleanup", "container-cleanup", "cleanup", None, None, ["OBS-host-cleanup"], ["OBS-host-cleanup"]),
        ]
        hops_by_id = {hop["hop_id"]: hop for hop in hops}
        runtime_artifacts = [f"evidence/{item[0]}.json" for item in observation_specs]
        static_artifact = "evidence/static-composition.json"
        artifacts = [*runtime_artifacts, static_artifact]
        candidate = {
            "candidate_version": "2.0",
            "candidate_status": "proposal",
            "owner_review": {"status": "pending", "owner": "quality", "reviewed_at": None},
            "compatibility": {
                "evidence_ledger_schema_change": False,
                "ledger_integration": "not_proposed",
            },
            "run": {
                "run_id": "RUN-1", "subject_sha256": digest,
                "authorization_id": "AUTH-1",
            },
            "entrypoint_closure": {
                "entrypoint": "project-owned-entrypoint",
                "preconditions": ["target is selected"],
                "authorization_boundary": "before effect",
                "effect_attempts": ["OBS-effect-attempt"],
                "effect_execution_steps": ["OBS-effect-step"],
                "effect_commit_points": ["OBS-effect-commit"],
                "effect_outcomes": ["OBS-effect-outcome"],
                "runtime_assertions": ["OBS-browser-assert"],
                "required_artifacts": artifacts,
                "offline_verifier": "project-owned-offline-verifier",
                "cleanup_observations": ["OBS-host-cleanup", "OBS-container-cleanup"],
                "cleanup_owners": ["platform-owner", "runtime-owner"],
                "failure_paths": [{
                    "path_id": "cleanup-after-effect",
                    "owners": ["platform-owner", "runtime-owner"],
                    "cleanup_observation_ids": ["OBS-host-cleanup", "OBS-container-cleanup"],
                }],
                "static_evidence": [{
                    "artifact_ref": static_artifact,
                    "sha256": digest,
                    "evidence_kind": "static_reachability",
                }],
            },
            "acquisition": {
                "capabilities": capabilities,
                "authorization": {
                    "authorization_id": "AUTH-1", "required": True, "granted": True,
                },
                "artifact_set": artifacts,
            },
            "hops": hops,
            "protection_edges": [
                {
                    "capability_id": f"CAP-{hop_id}", "effect_id": "EFFECT-1",
                    "preflight_observation_id": f"OBS-{prefix}-preflight",
                    "readiness_observation_id": f"OBS-{prefix}-ready",
                }
                for hop_id, prefix in (
                    ("browser-entry", "browser"),
                    ("container-runtime", "container"),
                    ("host-provider", "host"),
                )
            ],
            "observations": [
                {
                    "observation_id": observation_id,
                    "hop_id": hop_id,
                    "capability_id": f"CAP-{hop_id}",
                    "depends_on": dependencies,
                    "flow_depends_on": flow_dependencies,
                    "effect_id": effect_id,
                    "effect_result": effect_result,
                    "required_capability_ids": [
                        "CAP-browser-entry", "CAP-container-runtime", "CAP-host-provider",
                    ] if kind == "effect_attempt" else [],
                    "run_id": "RUN-1", "execution_state": "executed",
                    "phase": phases[kind],
                    "vantage_point": hops_by_id[hop_id]["vantage_point"],
                    "target": hops_by_id[hop_id]["target"], "command_digest": digest,
                    "started_at": f"2026-07-15T00:00:{index * 2:02d}+00:00",
                    "finished_at": f"2026-07-15T00:00:{index * 2 + 1:02d}+00:00",
                    "result_digest": digest, "status": "PASS",
                    "subject_sha256": digest, "authorization_id": "AUTH-1",
                    "assertion_kind": kind, "artifact_ref": runtime_artifacts[index],
                    "evidence_kind": "runtime",
                }
                for index, (
                    observation_id, hop_id, kind, effect_id, effect_result,
                    dependencies, flow_dependencies,
                )
                in enumerate(observation_specs)
            ],
        }
        fixture = Path(tempfile.mkdtemp(prefix="harness-candidate-test-")) / "candidate.json"

        def validate(value: dict) -> subprocess.CompletedProcess[str]:
            fixture.write_text(json.dumps(value, indent=2) + "\n")
            return subprocess.run(
                [sys.executable, str(HARNESS_CANDIDATE), str(fixture)],
                check=False, capture_output=True, text=True,
            )

        accepted = validate(candidate)
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
        self.assertEqual("CANDIDATE_VALID", json.loads(accepted.stdout)["status"])
        self.assertNotIn("\"status\": \"PASS\"", accepted.stdout)
        self.assertGreater(
            sum(
                item["assertion_kind"] == "capability_preflight"
                for item in candidate["observations"]
            ),
            1,
        )

        prevented = json.loads(json.dumps(candidate))
        prevented["observations"] = [
            item for item in prevented["observations"]
            if item["observation_id"] != "OBS-effect-commit"
        ]
        prevented["entrypoint_closure"]["effect_commit_points"] = []
        prevented["entrypoint_closure"]["required_artifacts"].remove(
            "evidence/OBS-effect-commit.json",
        )
        prevented["acquisition"]["artifact_set"].remove(
            "evidence/OBS-effect-commit.json",
        )
        prevented_observations = {
            item["observation_id"]: item for item in prevented["observations"]
        }
        prevented_observations["OBS-effect-outcome"].update(
            depends_on=["OBS-effect-step"], flow_depends_on=["OBS-effect-step"],
            effect_result="prevented",
        )
        prevented_observations["OBS-browser-assert"].update(effect_result="prevented")
        accepted_prevented = validate(prevented)
        self.assertEqual(
            0, accepted_prevented.returncode,
            accepted_prevented.stdout + accepted_prevented.stderr,
        )
        self.assertEqual("CANDIDATE_VALID", json.loads(accepted_prevented.stdout)["status"])

        def post_attempt_preflight(value: dict) -> None:
            observations = {
                item["observation_id"]: item for item in value["observations"]
            }
            observations["OBS-effect-attempt"].update(
                depends_on=["OBS-container-ready"],
                started_at="2026-07-15T00:00:08+00:00",
                finished_at="2026-07-15T00:00:09+00:00",
            )
            observations["OBS-host-preflight"].update(
                depends_on=["OBS-effect-attempt"],
                started_at="2026-07-15T00:00:10+00:00",
                finished_at="2026-07-15T00:00:11+00:00",
            )
            observations["OBS-host-ready"].update(
                started_at="2026-07-15T00:00:12+00:00",
                finished_at="2026-07-15T00:00:13+00:00",
            )
            for index, observation_id in enumerate((
                "OBS-effect-step", "OBS-effect-commit", "OBS-effect-outcome", "OBS-browser-assert",
                "OBS-host-cleanup", "OBS-container-cleanup",
            ), start=7):
                observations[observation_id].update(
                    started_at=f"2026-07-15T00:00:{index * 2:02d}+00:00",
                    finished_at=f"2026-07-15T00:00:{index * 2 + 1:02d}+00:00",
                )

        def unused_hop(value: dict) -> None:
            value["hops"].append({
                "hop_id": "unused-device", "owner": "device-owner",
                "target": "device-target", "vantage_point": "device",
                "depends_on": [],
            })

        def unused_capability(value: dict) -> None:
            value["acquisition"]["capabilities"].append({
                "capability_id": "CAP-unused-host", "hop_id": "host-provider",
                "owner": "platform-owner", "target": "host-provider",
                "vantage_point": "host", "authorization_required": True,
            })

        def remove_commit(value: dict, *, result: str) -> None:
            value["observations"] = [
                item for item in value["observations"]
                if item["observation_id"] != "OBS-effect-commit"
            ]
            value["entrypoint_closure"]["effect_commit_points"] = []
            value["entrypoint_closure"]["required_artifacts"].remove(
                "evidence/OBS-effect-commit.json",
            )
            value["acquisition"]["artifact_set"].remove(
                "evidence/OBS-effect-commit.json",
            )
            observations = {
                item["observation_id"]: item for item in value["observations"]
            }
            observations["OBS-effect-outcome"].update(
                depends_on=["OBS-effect-step"], flow_depends_on=["OBS-effect-step"],
                effect_result=result,
            )
            observations["OBS-browser-assert"].update(effect_result=result)

        mutations = {
            "owner_review_status_object": lambda value: value["owner_review"].update(
                status={},
            ),
            "hop_vantage_object": lambda value: value["hops"][0].update(
                vantage_point={},
            ),
            "capability_hop_object": lambda value: value["acquisition"][
                "capabilities"
            ][0].update(hop_id={}),
            "assertion_kind_object": lambda value: value["observations"][0].update(
                assertion_kind={},
            ),
            "effect_result_object": lambda value: value["observations"][9].update(
                effect_result={},
            ),
            "observation_capability_object": lambda value: value["observations"][0].update(
                capability_id={},
            ),
            "observation_hop_object": lambda value: value["observations"][0].update(
                hop_id={},
            ),
            "failure_cleanup_object": lambda value: value["entrypoint_closure"][
                "failure_paths"
            ][0].update(cleanup_observation_ids=[{}]),
            "protection_preflight_object": lambda value: value["protection_edges"][0].update(
                preflight_observation_id={},
            ),
            "assertion_effect_object": lambda value: value["observations"][10].update(
                effect_id={},
            ),
            "not_executed": lambda value: value["observations"][8].update(
                execution_state="not_executed",
            ),
            "wrong_vantage": lambda value: value["observations"][4].update(
                vantage_point="container",
            ),
            "capability_owner_mismatch": lambda value: value["acquisition"][
                "capabilities"
            ][2].update(owner="wrong-owner"),
            "wrong_order": lambda value: value["observations"][8].update(
                started_at="2026-07-14T23:59:00+00:00",
            ),
            "run_mismatch": lambda value: value["observations"][10].update(run_id="RUN-OTHER"),
            "subject_mismatch": lambda value: value["observations"][10].update(
                subject_sha256="b" * 64,
            ),
            "authorization_mismatch": lambda value: value["observations"][8].update(
                authorization_id="AUTH-OTHER",
            ),
            "static_is_not_runtime": lambda value: value["observations"][8].update(
                evidence_kind="static_reachability",
            ),
            "cleanup_failed": lambda value: value["observations"][12].update(status="FAIL"),
            "unknown_artifact": lambda value: value["acquisition"]["artifact_set"].append(
                "evidence/unknown.json",
            ),
            "missing_preflight": lambda value: value["observations"].pop(4),
            "hop_cycle": lambda value: value["hops"][0]["depends_on"].append(
                "container-cleanup",
            ),
            "missing_effect_dependency": lambda value: value["observations"][8].update(
                depends_on=[],
            ),
            "disconnected_flow": lambda value: value["observations"][9].update(
                flow_depends_on=[],
            ),
            "assertion_without_outcome_flow": lambda value: value["observations"][10].update(
                flow_depends_on=["OBS-host-ready"],
            ),
            "post_attempt_preflight": post_attempt_preflight,
            "unused_hop": unused_hop,
            "unused_capability": unused_capability,
            "unbound_commit_point": lambda value: value["entrypoint_closure"].update(
                effect_commit_points=["arbitrary-text"],
            ),
            "unbound_runtime_assertion": lambda value: value["entrypoint_closure"].update(
                runtime_assertions=["arbitrary-text"],
            ),
            "unbound_cleanup_owner": lambda value: value["entrypoint_closure"].update(
                cleanup_owners=["arbitrary-owner"],
            ),
            "missing_protection": lambda value: value["protection_edges"].pop(),
            "conflated_attempt_commit": lambda value: value["observations"][6].update(
                assertion_kind="effect_commit",
            ),
            "prevented_with_commit": lambda value: (
                value["observations"][9].update(effect_result="prevented"),
                value["observations"][10].update(effect_result="prevented"),
            ),
            "committed_without_commit": lambda value: remove_commit(value, result="committed"),
            "outcome_result_missing": lambda value: value["observations"][9].update(
                effect_result=None,
            ),
            "assertion_result_mismatch": lambda value: value["observations"][10].update(
                effect_result="prevented",
            ),
            "assertion_wrong_effect": lambda value: value["observations"][10].update(
                effect_id="EFFECT-UNKNOWN",
            ),
            "unbound_static_evidence": lambda value: value["entrypoint_closure"].update(
                static_evidence=["arbitrary-text"],
            ),
            "unbound_failure_path": lambda value: value["entrypoint_closure"].update(
                failure_paths=["arbitrary-text"],
            ),
        }
        expected_diagnostics = {
            "post_attempt_preflight": "readiness does not precede protected OBS-effect-attempt",
            "unused_hop": "declared hop has no runtime observation: unused-device",
            "unused_capability": "declared capability has no runtime observation: CAP-unused-host",
            "unbound_commit_point": "effect_commit_points must exactly reference",
            "unbound_runtime_assertion": "runtime_assertions must exactly reference",
            "unbound_cleanup_owner": "cleanup_owners must exactly match",
            "missing_protection": "required_capability_ids do not match protection edges",
            "conflated_attempt_commit": "effect_attempts must exactly reference",
            "assertion_without_outcome_flow": "lacks effect_outcome data flow",
            "prevented_with_commit": "must not contain an effect_commit",
            "committed_without_commit": "requires exactly one effect_commit",
            "outcome_result_missing": "effect_result must be one of",
            "assertion_result_mismatch": "assertion result does not match",
            "assertion_wrong_effect": "references unknown effect",
            "unbound_static_evidence": "must be an object",
            "unbound_failure_path": "must be an object",
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                rejected_candidate = json.loads(json.dumps(candidate))
                mutate(rejected_candidate)
                rejected = validate(rejected_candidate)
                self.assertEqual(1, rejected.returncode, rejected.stdout + rejected.stderr)
                report = json.loads(rejected.stdout)
                self.assertEqual("CANDIDATE_REJECTED", report["status"])
                if name in expected_diagnostics:
                    messages = "\n".join(
                        sample["message"] for sample in report["diagnostics"]["samples"]
                    )
                    self.assertIn(expected_diagnostics[name], messages)

    def test_mutator_candidate_requires_read_only_checks_and_transactional_convergence(self) -> None:
        baseline = "a" * 64
        environment = "b" * 64
        command = "c" * 64
        planned_output = "d" * 64
        protected = "e" * 64
        plan = "f" * 64
        unrelated = "1" * 64
        conflict = "2" * 64
        mutable_paths = [
            ".guardrails/control-registry.yaml",
            ".guardrails/traceability-graph.json",
        ]
        protected_paths = [
            ".guardrails/decisions.md",
            ".guardrails/memory.md",
        ]
        kinds = [
            "help", "invalid_invocation", "check_drift", "plan", "apply",
            "check_clean", "repeat_apply", "stale_plan", "injected_failure",
        ]
        outcomes = {
            "help": "reported",
            "invalid_invocation": "usage_rejected",
            "check_clean": "clean",
            "check_drift": "drift_detected",
            "plan": "planned",
            "apply": "applied",
            "repeat_apply": "no_change",
            "stale_plan": "stale_input_rejected",
            "injected_failure": "rolled_back",
        }
        candidate = {
            "candidate_version": "1.0",
            "candidate_status": "proposal",
            "owner_review": {"status": "pending", "owner": "quality", "reviewed_at": None},
            "compatibility": {
                "evidence_ledger_schema_change": False,
                "ledger_integration": "not_proposed",
            },
            "run": {
                "run_id": "MUTATION-RUN-1",
                "subject_sha256": baseline,
                "environment_sha256": environment,
            },
            "mutation_contract": {
                "operation_id": "CONTROL-PLANE-REGENERATOR",
                "owner": "quality-owner",
                "command_sha256": command,
                "mutable_paths": mutable_paths,
                "protected_paths": protected_paths,
                "protection_rationale": "preserve project-owned decisions and memory",
                "planned_output_sha256": planned_output,
            },
            "observations": [],
        }
        for sequence, kind in enumerate(kinds, start=1):
            input_digest = baseline
            expected_input = baseline
            output_digest = baseline
            planned: list[str] = []
            attempted: list[str] = []
            committed: list[str] = []
            plan_digest = None
            if kind == "check_clean":
                input_digest = expected_input = output_digest = planned_output
            elif kind == "plan":
                planned = mutable_paths
                plan_digest = plan
            elif kind == "apply":
                planned = attempted = committed = mutable_paths
                output_digest = planned_output
                plan_digest = plan
            elif kind == "repeat_apply":
                input_digest = expected_input = output_digest = planned_output
            elif kind == "stale_plan":
                input_digest = output_digest = conflict
                planned = mutable_paths
                plan_digest = plan
            elif kind == "injected_failure":
                attempted = mutable_paths[:1]
            candidate["observations"].append({
                "observation_id": f"OBS-{kind}",
                "kind": kind,
                "sequence": sequence,
                "run_id": "MUTATION-RUN-1",
                "command_sha256": command,
                "environment_sha256": environment,
                "execution_state": "executed",
                "outcome": outcomes[kind],
                "exit_code": 0 if kind in {
                    "help", "check_clean", "plan", "apply", "repeat_apply",
                } else 1,
                "input_tree_sha256": input_digest,
                "expected_input_sha256": expected_input,
                "output_tree_sha256": output_digest,
                "protected_tree_sha256": protected,
                "plan_sha256": plan_digest,
                "planned_write_set": planned,
                "attempted_write_set": attempted,
                "committed_write_set": committed,
                "residual_paths": [],
                "artifact_ref": f"evidence/mutator/{kind}.json",
                "artifact_sha256": hashlib.sha256(kind.encode()).hexdigest(),
            })

        fixture = Path(tempfile.mkdtemp(prefix="mutator-candidate-test-")) / "candidate.json"

        def validate(value: dict) -> subprocess.CompletedProcess[str]:
            fixture.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(MUTATOR_CANDIDATE), str(fixture)],
                check=False, capture_output=True, text=True,
            )

        accepted = validate(candidate)
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
        report = json.loads(accepted.stdout)
        self.assertEqual("CANDIDATE_VALID", report["status"])
        self.assertEqual("PROPOSAL_ONLY", report["assurance_status"])
        self.assertNotIn('"status": "PASS"', accepted.stdout)

        full_ownership = copy.deepcopy(candidate)
        full_ownership["mutation_contract"].update(
            protected_paths=[],
            protection_rationale="greenfield output has one reviewed semantic owner",
        )
        accepted_full_ownership = validate(full_ownership)
        self.assertEqual(
            0,
            accepted_full_ownership.returncode,
            accepted_full_ownership.stdout + accepted_full_ownership.stderr,
        )

        def observation(value: dict, kind: str) -> dict:
            return next(item for item in value["observations"] if item["kind"] == kind)

        def replace_mutable_paths(value: dict, paths: list[str]) -> None:
            value["mutation_contract"]["mutable_paths"] = paths
            for kind in ("plan", "apply", "stale_plan"):
                observation(value, kind)["planned_write_set"] = paths
            observation(value, "apply")["attempted_write_set"] = paths
            observation(value, "apply")["committed_write_set"] = paths
            observation(value, "injected_failure")["attempted_write_set"] = paths[:1]

        def swap_sequences(value: dict, left: str, right: str) -> None:
            left_observation = observation(value, left)
            right_observation = observation(value, right)
            left_observation["sequence"], right_observation["sequence"] = (
                right_observation["sequence"], left_observation["sequence"]
            )

        mutations = {
            "help_writes": lambda value: observation(value, "help").update(
                committed_write_set=mutable_paths[:1],
            ),
            "check_drift_mutates": lambda value: observation(value, "check_drift").update(
                output_tree_sha256=planned_output,
            ),
            "clean_claims_pre_apply_subject": lambda value: observation(
                value, "check_clean",
            ).update(
                input_tree_sha256=baseline,
                expected_input_sha256=baseline,
                output_tree_sha256=baseline,
            ),
            "drift_uses_unrelated_fixture": lambda value: observation(
                value, "check_drift",
            ).update(
                input_tree_sha256=unrelated,
                expected_input_sha256=unrelated,
                output_tree_sha256=unrelated,
            ),
            "clean_before_apply": lambda value: swap_sequences(
                value, "apply", "check_clean",
            ),
            "invented_write": lambda value: observation(value, "apply").update(
                committed_write_set=[".guardrails/unknown.json"],
            ),
            "noncanonical_write_path": lambda value: replace_mutable_paths(
                value, [".guardrails//control-registry.yaml"],
            ),
            "backslash_write_path": lambda value: replace_mutable_paths(
                value, [".guardrails\\control-registry.yaml"],
            ),
            "glob_write_path": lambda value: replace_mutable_paths(
                value, [".guardrails/*.yaml"],
            ),
            "artifact_path_alias": lambda value: observation(value, "apply").update(
                artifact_ref="evidence//mutator/apply.json",
            ),
            "non_idempotent_repeat": lambda value: observation(value, "repeat_apply").update(
                attempted_write_set=mutable_paths,
            ),
            "stale_plan_applied": lambda value: observation(value, "stale_plan").update(
                output_tree_sha256=planned_output,
            ),
            "rollback_residue": lambda value: observation(value, "injected_failure").update(
                residual_paths=[".guardrails/.partial.tmp"],
            ),
            "protected_scope_changed": lambda value: observation(value, "apply").update(
                protected_tree_sha256="3" * 64,
            ),
            "plan_substitution": lambda value: observation(value, "apply").update(
                plan_sha256="4" * 64,
            ),
            "missing_invalid_invocation": lambda value: value["observations"].remove(
                observation(value, "invalid_invocation"),
            ),
            "ledger_promotion": lambda value: value["compatibility"].update(
                ledger_integration="proposed",
            ),
            "no_state_transition": lambda value: value["mutation_contract"].update(
                planned_output_sha256=baseline,
            ),
            "nested_scope_overlap": lambda value: value["mutation_contract"].update(
                protected_paths=[".guardrails"],
            ),
            "missing_protection_rationale": lambda value: value["mutation_contract"].update(
                protection_rationale="",
            ),
            "owner_status_object": lambda value: value["owner_review"].update(
                status={},
            ),
            "kind_object": lambda value: value["observations"][0].update(kind={}),
            "input_digest_object": lambda value: observation(value, "check_drift").update(
                input_tree_sha256={},
            ),
            "write_set_object": lambda value: observation(value, "apply").update(
                committed_write_set=[{}],
            ),
            "sequence_object": lambda value: observation(value, "apply").update(
                sequence={},
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                rejected_candidate = copy.deepcopy(candidate)
                mutate(rejected_candidate)
                rejected = validate(rejected_candidate)
                self.assertEqual(1, rejected.returncode, rejected.stdout + rejected.stderr)
                self.assertEqual("CANDIDATE_REJECTED", json.loads(rejected.stdout)["status"])

        directory_input = fixture.parent / "candidate-directory"
        directory_input.mkdir()
        unreadable = subprocess.run(
            [sys.executable, str(MUTATOR_CANDIDATE), str(directory_input)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(2, unreadable.returncode, unreadable.stdout + unreadable.stderr)
        self.assertNotIn("Traceback", unreadable.stderr)
        self.assertEqual("CANDIDATE_ERROR", json.loads(unreadable.stdout)["status"])

    def test_seal_rejects_archive_id_path_escape(self) -> None:
        project = self.make_project()
        result = subprocess.run(
            [
                sys.executable, str(SEAL), "--root", str(project),
                "--archive-id", "../../escaped",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("cannot contain a path", result.stderr)
        self.assertFalse((project / "escaped").exists())

    def test_seal_rejects_symlink_without_mutating_target(self) -> None:
        project = self.make_project()
        external = Path(tempfile.mkdtemp(prefix="quality-seal-external-")) / "target.txt"
        external.write_text("fixture\n", encoding="utf-8")
        external.chmod(0o600)
        evidence = project / ".guardrails" / "evidence"
        evidence.mkdir()
        (evidence / "external-link").symlink_to(external)

        result = subprocess.run(
            [
                sys.executable, str(SEAL), "--root", str(project),
                "--archive-id", "linked",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("symbolic link", result.stderr)
        self.assertEqual(0o600, external.stat().st_mode & 0o777)
        self.assertFalse((project / ".guardrails" / "archive" / "linked").exists())

    def test_seal_validates_the_entire_control_plane(self) -> None:
        project = self.make_project()
        names = (
            "quality-manifest.yaml", "control-registry.yaml",
            "traceability-graph.json", "evidence-ledger.json",
        )
        for index, name in enumerate(names):
            with self.subTest(name=name):
                path = project / ".guardrails" / name
                original = path.read_text()
                path.write_text("{}\n", encoding="utf-8")
                archive_id = f"invalid-plane-{index}"
                result = subprocess.run(
                    [
                        sys.executable, str(SEAL), "--root", str(project),
                        "--archive-id", archive_id,
                    ],
                    check=False, capture_output=True, text=True,
                )
                path.write_text(original, encoding="utf-8")
                self.assertEqual(1, result.returncode)
                self.assertIn("invalid active control plane", result.stderr)
                self.assertFalse(
                    (project / ".guardrails" / "archive" / archive_id).exists()
                )

    def test_valid_seal_records_active_policy_and_digest(self) -> None:
        project = self.make_project()
        result = subprocess.run(
            [
                sys.executable, str(SEAL), "--root", str(project),
                "--archive-id", "revision-1",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        archive_manifest = json.loads(
            (
                project / ".guardrails" / "archive" / "revision-1"
                / "archive-manifest.json"
            ).read_text()
        )
        self.assertEqual("validated", archive_manifest["validation_status"])
        self.assertEqual("sha256_chain", archive_manifest["sealing_profile"])
        self.assertEqual("digest_only", archive_manifest["signature_status"])
        self.assertEqual(64, len(archive_manifest["archive_sha256"]))
        self.assertEqual(
            {"runs": "GENESIS", "audits": "GENESIS", "claims": "GENESIS"},
            archive_manifest["ledger_chain_heads"],
        )

    def test_seal_packages_immutable_artifacts_and_rejects_tampered_evidence(self) -> None:
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
        self.assertEqual(0, sync.returncode, sync.stderr)
        run = self.run_evaluator(
            project, "--run", "--audit-stage", "self",
            "--actor", "fixture-self", "--control", control["id"],
        )
        self.assertEqual(0, run.returncode, run.stderr)
        sealed = subprocess.run(
            [
                sys.executable, str(SEAL), "--root", str(project),
                "--archive-id", "with-artifact",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, sealed.returncode, sealed.stderr)
        archive_manifest = json.loads(
            (
                project / ".guardrails" / "archive" / "with-artifact"
                / "archive-manifest.json"
            ).read_text()
        )
        archived_artifact = archive_manifest["referenced_artifacts"][0]
        self.assertEqual("build/report.txt", archived_artifact["source_path"])
        self.assertEqual(
            "current",
            (
                project / ".guardrails" / "archive" / "with-artifact"
                / archived_artifact["archive_path"]
            ).read_text(),
        )

        ledger = json.loads(
            (project / ".guardrails" / "evidence-ledger.json").read_text()
        )
        artifact_evidence = ledger["runs"][-1]["results"][0]["artifacts"][0]
        self.assertEqual(
            Path(artifact_evidence["evidence_ref"]).relative_to(".guardrails").as_posix(),
            archived_artifact["archive_path"],
        )

        (project / "build" / "report.txt").write_text("changed")
        evolved = subprocess.run(
            [
                sys.executable, str(SEAL), "--root", str(project),
                "--archive-id", "evolved-source",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, evolved.returncode, evolved.stderr)

        immutable = project / artifact_evidence["evidence_ref"]
        immutable.write_text("tampered\n", encoding="utf-8")
        tampered = subprocess.run(
            [
                sys.executable, str(SEAL), "--root", str(project),
                "--archive-id", "tampered-evidence",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(1, tampered.returncode)
        self.assertIn("immutable evidence digest mismatch", tampered.stderr)

    def test_predecessor_binding_revalidates_archived_file_digests(self) -> None:
        project = self.make_project()
        result = subprocess.run(
            [
                sys.executable, str(SEAL), "--root", str(project),
                "--archive-id", "revision-1",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        probe = (
            "import json,sys; from pathlib import Path; "
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
            "from init_quality_framework import predecessor_archive_binding; "
            "print(json.dumps(predecessor_archive_binding(Path(sys.argv[1]), sys.argv[2])))"
        )
        valid = subprocess.run(
            [sys.executable, "-c", probe, str(project / ".guardrails"), "revision-1"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, valid.returncode, valid.stderr)
        self.assertEqual("revision-1", json.loads(valid.stdout)["archive_id"])

        archive_manifest = json.loads(
            (
                project / ".guardrails" / "archive" / "revision-1"
                / "archive-manifest.json"
            ).read_text()
        )
        archived_file = (
            project / ".guardrails" / "archive" / "revision-1"
            / archive_manifest["files"][0]["path"]
        )
        archived_file.chmod(0o600)
        archived_file.write_text("tampered\n", encoding="utf-8")
        invalid = subprocess.run(
            [sys.executable, "-c", probe, str(project / ".guardrails"), "revision-1"],
            check=False, capture_output=True, text=True,
        )
        self.assertNotEqual(0, invalid.returncode)
        self.assertIn("digest mismatch", invalid.stderr)

    def test_reinitialization_binds_predecessor_and_resets_active_evidence(self) -> None:
        project = self.make_project()
        custom_rule = project / ".guardrails" / "rules" / "project-specific.md"
        custom_rule.write_text("# Project-specific rule\n", encoding="utf-8")
        evidence = project / ".guardrails" / "evidence"
        evidence.mkdir()
        (evidence / "stale.log").write_text("old evidence\n", encoding="utf-8")
        sealed = subprocess.run(
            [
                sys.executable, str(SEAL), "--root", str(project),
                "--archive-id", "revision-1",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, sealed.returncode, sealed.stderr)
        regenerated = subprocess.run(
            [
                sys.executable, str(INIT), "--root", str(project),
                "--development-mode", "human_brownfield",
                "--target-maturity", "prototype",
                "--product-type", "cli",
                "--distribution-model", "open_source",
                "--market", "global_unspecified",
                "--criticality", "low",
                "--data-sensitivity", "public",
                "--deployment-model", "local",
                "--support-model", "community",
                "--primary-user", "developer",
                "--public-contract", "none",
                "--build-topology", "single_form",
                "--persistent-state", "none",
                "--external-contributions", "accepted",
                "--skill-deployment", "environment_managed",
                "--evidence-profile", "open_source",
                "--evidence-retention", "project_lifetime",
                "--evidence-max-active-bytes", "1073741824",
                "--evidence-sealing-profile", "sha256_chain",
                "--no-ai-system", "--scope-mode", "full_repo",
                "--legal-profile", "none_identified",
                "--predecessor-archive-id", "revision-1", "--force",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, regenerated.returncode, regenerated.stderr)
        self.assertFalse(evidence.exists())
        self.assertEqual("# Project-specific rule\n", custom_rule.read_text())
        self.assertTrue(
            (
                project / ".guardrails" / "archive" / "revision-1"
                / "archive-manifest.json"
            ).is_file()
        )
        manifest = json.loads(
            (project / ".guardrails" / "quality-manifest.yaml").read_text()
        )
        predecessor = manifest["evidence_policy"]["predecessor_archive"]
        self.assertEqual("revision-1", predecessor["archive_id"])
        self.assertEqual(64, len(predecessor["archive_sha256"]))

    def test_archive_history_is_excluded_from_active_evidence_budget(self) -> None:
        project = self.make_project()
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["evidence_policy"]["max_active_bytes"] = 8 * 1024 * 1024
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        archived = project / ".guardrails" / "archive" / "old" / "payload.bin"
        archived.parent.mkdir(parents=True)
        with archived.open("wb") as stream:
            stream.truncate(32 * 1024 * 1024)
        registry = json.loads(
            (project / ".guardrails" / "control-registry.yaml").read_text()
        )
        control_id = registry["controls"][0]["id"]
        result = self.run_evaluator(project, "--run", "--control", control_id)
        self.assertNotIn("QF-EVIDENCE", result.stderr)

    def test_artifact_persistence_cannot_overrun_active_evidence_budget(self) -> None:
        project = self.make_project({".gitignore": "build/\n"})
        manifest_path = project / ".guardrails" / "quality-manifest.yaml"
        manifest = json.loads(manifest_path.read_text())
        manifest["evidence_policy"]["max_active_bytes"] = 4 * 1024 * 1024
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        registry_path = project / ".guardrails" / "control-registry.yaml"
        registry = json.loads(registry_path.read_text())
        control = registry["controls"][0]
        control["execution"] = {
            "type": "command",
            "command": [
                sys.executable, "-c",
                "from pathlib import Path; p=Path('build/large.bin'); "
                "p.parent.mkdir(exist_ok=True); f=p.open('wb'); "
                "f.seek(8*1024*1024-1); f.write(b'0'); f.close()",
            ],
            "cwd": ".", "timeout_seconds": 10, "authorization_required": False,
            "artifact_paths": ["build/large.bin"],
        }
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        sync = subprocess.run(
            [sys.executable, str(SYNC), "--root", str(project)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(0, sync.returncode, sync.stderr)
        result = self.run_evaluator(project, "--run", "--control", control["id"])
        self.assertEqual(1, result.returncode)
        ledger = json.loads(
            (project / ".guardrails" / "evidence-ledger.json").read_text()
        )
        control_result = ledger["runs"][-1]["results"][0]
        self.assertEqual("BLOCKED", control_result["status"])
        self.assertEqual("evidence", control_result["blocker_kind"])
        self.assertIn("exceeds active evidence budget", control_result["detail"])
        evidence_dir = project / ".guardrails" / "evidence" / "outputs"
        self.assertEqual([], list(evidence_dir.glob("*.artifact.bin")))
        self.assertEqual([], list(evidence_dir.glob(".evidence-*.tmp")))

    def test_writable_preflight_does_not_create_missing_directory(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="quality-preflight-test-"))
        missing = root / "missing" / "nested"
        result = subprocess.run(
            [sys.executable, str(PREFLIGHT), "writable", str(missing)],
            check=False,
        )
        self.assertEqual(1, result.returncode)
        self.assertFalse(missing.exists())

    def test_framework_dirty_ignores_non_normative_untracked_files(self) -> None:
        skill = Path(tempfile.mkdtemp(prefix="quality-skill-binding-test-"))
        (skill / "scripts").mkdir()
        (skill / "SKILL.md").write_text("# Fixture\n", encoding="utf-8")
        script = skill / "scripts" / "fixture.py"
        script.write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=skill, check=True)
        subprocess.run(
            ["git", "config", "user.email", "fixture@example.invalid"],
            cwd=skill, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Fixture"], cwd=skill, check=True,
        )
        subprocess.run(["git", "add", "."], cwd=skill, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=skill, check=True)

        probe = (
            "import json,sys; from pathlib import Path; "
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
            "from quality_common import framework_binding; "
            "print(json.dumps(framework_binding(Path(sys.argv[1]))))"
        )
        (skill / "notes.tmp").write_text("untracked\n", encoding="utf-8")
        clean = subprocess.run(
            [sys.executable, "-c", probe, str(skill)],
            check=True, capture_output=True, text=True,
        )
        self.assertFalse(json.loads(clean.stdout)["dirty"])

        script.write_text("VALUE = 2\n", encoding="utf-8")
        dirty = subprocess.run(
            [sys.executable, "-c", probe, str(skill)],
            check=True, capture_output=True, text=True,
        )
        self.assertTrue(json.loads(dirty.stdout)["dirty"])


if __name__ == "__main__":
    unittest.main()
