#!/usr/bin/env python3
"""Validate a control-plane mutator proposal without executing it or emitting PASS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath

from generation_common import bounded_diagnostics
from quality_common import (
    load_json_yaml,
    safe_relative_path,
    valid_enum,
    valid_sha256,
    valid_timestamp,
)


OBSERVATION_KINDS = {
    "help",
    "invalid_invocation",
    "check_clean",
    "check_drift",
    "plan",
    "apply",
    "repeat_apply",
    "stale_plan",
    "injected_failure",
}
EXPECTED_OUTCOMES = {
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
SUCCESS_KINDS = {"help", "check_clean", "plan", "apply", "repeat_apply"}
BASELINE_KINDS = {
    "help",
    "invalid_invocation",
    "plan",
    "apply",
    "injected_failure",
}
READ_ONLY_KINDS = {
    "help",
    "invalid_invocation",
    "check_clean",
    "check_drift",
    "plan",
    "repeat_apply",
    "stale_plan",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", help="JSON-compatible mutator candidate")
    return parser.parse_args()


def non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def canonical_relative_path(value: object) -> bool:
    """Accept one exact, portable, slash-normalized project-relative path."""
    return (
        safe_relative_path(value)
        and "\\" not in value
        and not any(character in value for character in "*?[]")
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
        and PurePosixPath(value).as_posix() == value
    )


def exact_object(value: object, fields: set[str], path: str) -> tuple[list[str], dict]:
    if not isinstance(value, dict):
        return [f"{path} must be an object"], {}
    errors = [f"{path}.{field} is required" for field in sorted(fields - set(value))]
    errors.extend(
        f"{path}.{field} is not allowed" for field in sorted(set(value) - fields)
    )
    return errors, value


def path_list(
    value: object, path: str, *, allow_empty: bool
) -> tuple[list[str], list[str]]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "a path list" if allow_empty else "a non-empty path list"
        return [f"{path} must be {qualifier}"], []
    errors: list[str] = []
    parsed: list[str] = []
    for index, item in enumerate(value):
        if not canonical_relative_path(item):
            errors.append(
                f"{path}[{index}] must be an exact canonical project-relative path"
            )
        else:
            parsed.append(item)
    if len(parsed) != len(set(parsed)):
        errors.append(f"{path} contains duplicate paths")
    if parsed != sorted(parsed):
        errors.append(f"{path} must use canonical sorted order")
    return errors, parsed


def require_digest(
    value: object, path: str, errors: list[str], *, nullable: bool = False
) -> None:
    if value is None and nullable:
        return
    if not valid_sha256(value):
        errors.append(f"{path} must be a SHA-256 digest")


def scope_overlaps(left: str, right: str) -> bool:
    """Return whether two canonical project-relative paths contain one another."""
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def nested_scope_errors(paths: list[str], path: str) -> list[str]:
    errors: list[str] = []
    for index, left in enumerate(paths):
        for right in paths[index + 1 :]:
            if scope_overlaps(left, right):
                errors.append(f"{path} contains overlapping scopes: {left}, {right}")
    return errors


def validate_candidate(candidate: dict) -> list[str]:
    errors, candidate = exact_object(
        candidate,
        {
            "candidate_version",
            "candidate_status",
            "owner_review",
            "compatibility",
            "run",
            "mutation_contract",
            "observations",
        },
        "candidate",
    )
    if candidate.get("candidate_version") != "1.0":
        errors.append("candidate.candidate_version must be 1.0")
    if candidate.get("candidate_status") != "proposal":
        errors.append("candidate.candidate_status must remain proposal")

    review_errors, review = exact_object(
        candidate.get("owner_review"),
        {"status", "owner", "reviewed_at"},
        "candidate.owner_review",
    )
    errors.extend(review_errors)
    if not valid_enum(review.get("status"), {"pending", "approved"}):
        errors.append("candidate.owner_review.status is invalid")
    if not non_empty_string(review.get("owner")):
        errors.append("candidate.owner_review.owner is required")
    if review.get("status") == "approved" and not valid_timestamp(
        review.get("reviewed_at")
    ):
        errors.append("approved candidate owner review requires reviewed_at")
    if review.get("status") == "pending" and review.get("reviewed_at") is not None:
        errors.append("pending candidate owner review must not set reviewed_at")

    compatibility_errors, compatibility = exact_object(
        candidate.get("compatibility"),
        {"evidence_ledger_schema_change", "ledger_integration"},
        "candidate.compatibility",
    )
    errors.extend(compatibility_errors)
    if compatibility.get("evidence_ledger_schema_change") is not False:
        errors.append("candidate must not change the v3 evidence ledger schema")
    if compatibility.get("ledger_integration") != "not_proposed":
        errors.append("candidate ledger integration must remain not_proposed")

    run_errors, run = exact_object(
        candidate.get("run"),
        {"run_id", "subject_sha256", "environment_sha256"},
        "candidate.run",
    )
    errors.extend(run_errors)
    if not non_empty_string(run.get("run_id")):
        errors.append("candidate.run.run_id is required")
    require_digest(run.get("subject_sha256"), "candidate.run.subject_sha256", errors)
    require_digest(
        run.get("environment_sha256"), "candidate.run.environment_sha256", errors
    )

    contract_errors, contract = exact_object(
        candidate.get("mutation_contract"),
        {
            "operation_id",
            "owner",
            "command_sha256",
            "mutable_paths",
            "protected_paths",
            "protection_rationale",
            "planned_output_sha256",
        },
        "candidate.mutation_contract",
    )
    errors.extend(contract_errors)
    for field in ("operation_id", "owner"):
        if not non_empty_string(contract.get(field)):
            errors.append(f"candidate.mutation_contract.{field} is required")
    if not non_empty_string(contract.get("protection_rationale")):
        errors.append("candidate.mutation_contract.protection_rationale is required")
    require_digest(
        contract.get("command_sha256"),
        "candidate.mutation_contract.command_sha256",
        errors,
    )
    require_digest(
        contract.get("planned_output_sha256"),
        "candidate.mutation_contract.planned_output_sha256",
        errors,
    )
    if contract.get("planned_output_sha256") == run.get("subject_sha256"):
        errors.append("planned_output_sha256 must differ from the input subject")
    mutable_errors, mutable_paths = path_list(
        contract.get("mutable_paths"),
        "candidate.mutation_contract.mutable_paths",
        allow_empty=False,
    )
    protected_errors, protected_paths = path_list(
        contract.get("protected_paths"),
        "candidate.mutation_contract.protected_paths",
        allow_empty=True,
    )
    errors.extend(mutable_errors)
    errors.extend(protected_errors)
    errors.extend(
        nested_scope_errors(mutable_paths, "candidate.mutation_contract.mutable_paths")
    )
    errors.extend(
        nested_scope_errors(
            protected_paths, "candidate.mutation_contract.protected_paths"
        )
    )
    for mutable in mutable_paths:
        for protected_path in protected_paths:
            if scope_overlaps(mutable, protected_path):
                errors.append(
                    "candidate.mutation_contract mutable and protected scopes overlap: "
                    f"{mutable}, {protected_path}"
                )

    observations = candidate.get("observations")
    if not isinstance(observations, list) or not observations:
        return errors + ["candidate.observations must be a non-empty array"]
    observation_fields = {
        "observation_id",
        "kind",
        "sequence",
        "run_id",
        "command_sha256",
        "environment_sha256",
        "execution_state",
        "outcome",
        "exit_code",
        "input_tree_sha256",
        "expected_input_sha256",
        "output_tree_sha256",
        "protected_tree_sha256",
        "plan_sha256",
        "planned_write_set",
        "attempted_write_set",
        "committed_write_set",
        "residual_paths",
        "artifact_ref",
        "artifact_sha256",
    }
    by_kind: dict[str, dict] = {}
    ids: set[str] = set()
    sequences: set[int] = set()
    artifacts: set[str] = set()
    protected_digest: str | None = None
    parsed: list[tuple[str, dict, list[str], list[str], list[str], list[str]]] = []
    for index, raw in enumerate(observations):
        path = f"candidate.observations[{index}]"
        item_errors, item = exact_object(raw, observation_fields, path)
        errors.extend(item_errors)
        observation_id = item.get("observation_id")
        if not non_empty_string(observation_id):
            errors.append(f"{path}.observation_id is required")
        elif observation_id in ids:
            errors.append(f"duplicate observation_id: {observation_id}")
        else:
            ids.add(observation_id)
        kind = item.get("kind")
        if not valid_enum(kind, OBSERVATION_KINDS):
            errors.append(f"{path}.kind is invalid")
            kind = ""
        elif kind in by_kind:
            errors.append(f"duplicate mutation observation kind: {kind}")
        else:
            by_kind[kind] = item
        sequence = item.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            errors.append(f"{path}.sequence must be a positive integer")
        elif sequence in sequences:
            errors.append(f"duplicate observation sequence: {sequence}")
        else:
            sequences.add(sequence)
        if item.get("run_id") != run.get("run_id"):
            errors.append(f"{path}.run_id does not match candidate.run")
        if item.get("command_sha256") != contract.get("command_sha256"):
            errors.append(f"{path}.command_sha256 does not match mutation contract")
        if item.get("environment_sha256") != run.get("environment_sha256"):
            errors.append(f"{path}.environment_sha256 does not match candidate.run")
        if item.get("execution_state") != "executed":
            errors.append(f"{path}.execution_state must be executed")
        if kind and item.get("outcome") != EXPECTED_OUTCOMES[kind]:
            errors.append(f"{path}.outcome does not match {kind}")
        exit_code = item.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            errors.append(f"{path}.exit_code must be an integer")
        elif kind in SUCCESS_KINDS and exit_code != 0:
            errors.append(f"{path}.exit_code must be zero")
        elif kind and kind not in SUCCESS_KINDS and exit_code == 0:
            errors.append(f"{path}.exit_code must be non-zero")
        for field in (
            "input_tree_sha256",
            "expected_input_sha256",
            "output_tree_sha256",
            "protected_tree_sha256",
            "artifact_sha256",
        ):
            require_digest(item.get(field), f"{path}.{field}", errors)
        require_digest(
            item.get("plan_sha256"), f"{path}.plan_sha256", errors, nullable=True
        )
        current_protected = item.get("protected_tree_sha256")
        if valid_sha256(current_protected):
            if protected_digest is None:
                protected_digest = current_protected
            elif protected_digest != current_protected:
                errors.append(
                    "protected scope digest changed across mutator observations"
                )
        set_values: list[list[str]] = []
        for field in (
            "planned_write_set",
            "attempted_write_set",
            "committed_write_set",
            "residual_paths",
        ):
            set_errors, values = path_list(
                item.get(field), f"{path}.{field}", allow_empty=True
            )
            errors.extend(set_errors)
            set_values.append(values)
        artifact_ref = item.get("artifact_ref")
        if not canonical_relative_path(artifact_ref):
            errors.append(
                f"{path}.artifact_ref must be an exact canonical project-relative path"
            )
        elif artifact_ref in artifacts:
            errors.append(f"duplicate observation artifact_ref: {artifact_ref}")
        else:
            artifacts.add(artifact_ref)
        parsed.append((kind, item, *set_values))

    missing = OBSERVATION_KINDS - set(by_kind)
    extra = set(by_kind) - OBSERVATION_KINDS
    if missing:
        errors.append(
            "candidate is missing mutation observations: " + ", ".join(sorted(missing))
        )
    if extra:
        errors.append(
            "candidate has unknown mutation observations: " + ", ".join(sorted(extra))
        )
    if sequences and sequences != set(range(1, len(observations) + 1)):
        errors.append("observation sequence must be contiguous from one")

    baseline = run.get("subject_sha256")
    planned_output = contract.get("planned_output_sha256")
    plan_digest: str | None = None
    for kind, item, planned, attempted, committed, residual in parsed:
        path = f"candidate observation {kind or '<invalid>'}"
        input_digest = item.get("input_tree_sha256")
        expected_input = item.get("expected_input_sha256")
        output_digest = item.get("output_tree_sha256")
        if kind in BASELINE_KINDS and input_digest != baseline:
            errors.append(f"{path} must start from candidate.run.subject_sha256")
        if kind in BASELINE_KINDS and expected_input != baseline:
            errors.append(
                f"{path} expected input must match candidate.run.subject_sha256"
            )
        if kind in READ_ONLY_KINDS and input_digest != output_digest:
            errors.append(f"{path} changed its input tree")
        if kind in READ_ONLY_KINDS and (attempted or committed or residual):
            errors.append(f"{path} must have no writes or residual paths")
        if (
            kind not in {"plan", "apply", "stale_plan"}
            and item.get("plan_sha256") is not None
        ):
            errors.append(f"{path} must not bind a plan")
        if kind == "plan":
            plan_digest = (
                item.get("plan_sha256")
                if valid_sha256(item.get("plan_sha256"))
                else None
            )
            if planned != mutable_paths:
                errors.append("plan planned_write_set must exactly match mutable_paths")
        elif kind == "apply":
            if output_digest != planned_output:
                errors.append("apply output does not match planned_output_sha256")
            if (
                planned != mutable_paths
                or attempted != mutable_paths
                or committed != mutable_paths
            ):
                errors.append("apply write sets must exactly match mutable_paths")
            if residual:
                errors.append("apply must not leave residual paths")
        elif kind == "repeat_apply":
            if input_digest != planned_output or expected_input != planned_output:
                errors.append("repeat_apply must start from planned_output_sha256")
            if planned or attempted or committed or residual:
                errors.append("repeat_apply must converge without writes")
        elif kind == "check_clean":
            if input_digest != planned_output or expected_input != planned_output:
                errors.append(
                    "check_clean must evaluate the converged planned_output_sha256"
                )
        elif kind == "check_drift":
            if input_digest != baseline or expected_input != baseline:
                errors.append(
                    "check_drift must evaluate candidate.run.subject_sha256 before apply"
                )
            if planned or attempted or committed or residual:
                errors.append("check_drift must be read-only")
        elif kind == "stale_plan":
            if input_digest == baseline or input_digest == planned_output:
                errors.append("stale_plan requires a conflicting input fixture")
            if expected_input != baseline:
                errors.append("stale_plan must bind the original expected input")
            if planned != mutable_paths:
                errors.append("stale_plan must bind the original planned write set")
        elif kind == "injected_failure":
            if not attempted or not set(attempted) <= set(mutable_paths):
                errors.append(
                    "injected_failure must attempt a non-empty subset of mutable_paths"
                )
            if output_digest != input_digest or committed or residual:
                errors.append(
                    "injected_failure must roll back fully without residual paths"
                )
            if planned:
                errors.append("injected_failure must not claim a completed plan")
        elif planned or attempted or committed or residual:
            errors.append(f"{path} must have empty mutation sets")

    if plan_digest is not None:
        for kind in ("apply", "stale_plan"):
            if kind in by_kind and by_kind[kind].get("plan_sha256") != plan_digest:
                errors.append(f"{kind} does not bind the validated plan")
    ordered_kinds = ("check_drift", "plan", "apply", "check_clean", "repeat_apply")
    if all(kind in by_kind for kind in ordered_kinds):
        ordered_sequences = [by_kind[kind].get("sequence") for kind in ordered_kinds]
        if all(
            isinstance(sequence, int) and not isinstance(sequence, bool)
            for sequence in ordered_sequences
        ) and ordered_sequences != sorted(ordered_sequences):
            errors.append(
                "mutation sequence must be check_drift before plan before apply "
                "before check_clean before repeat_apply"
            )
    if all(kind in by_kind for kind in ("plan", "stale_plan")):
        plan_sequence = by_kind["plan"].get("sequence")
        stale_sequence = by_kind["stale_plan"].get("sequence")
        if (
            isinstance(plan_sequence, int)
            and not isinstance(plan_sequence, bool)
            and isinstance(stale_sequence, int)
            and not isinstance(stale_sequence, bool)
            and plan_sequence >= stale_sequence
        ):
            errors.append("stale_plan must execute after the validated plan")
    return errors


def main() -> int:
    args = parse_args()
    try:
        candidate = load_json_yaml(Path(args.candidate))
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "CANDIDATE_ERROR", "errors": [str(exc)]}, sort_keys=True
            )
        )
        return 2
    errors = validate_candidate(candidate)
    if errors:
        print(
            json.dumps(
                {
                    "status": "CANDIDATE_REJECTED",
                    "diagnostics": bounded_diagnostics(errors),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "CANDIDATE_VALID",
                "assurance_status": "PROPOSAL_ONLY",
                "promotion_status": "OWNER_REVIEW_REQUIRED"
                if candidate["owner_review"]["status"] == "pending"
                else "CONTROL_INTEGRATION_REVIEW_REQUIRED",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
