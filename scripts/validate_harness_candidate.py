#!/usr/bin/env python3
"""Validate a portable execution-closure proposal without emitting evidence PASS."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from generation_common import bounded_diagnostics
from quality_common import load_json_yaml, safe_relative_path, valid_sha256, valid_timestamp


ASSERTION_ORDER = (
    "capability_preflight",
    "target_context_readiness",
    "effect",
    "product_assertion",
    "cleanup",
)
ASSERTION_PHASE = {
    "capability_preflight": "pre_effect",
    "target_context_readiness": "pre_effect",
    "effect": "effect",
    "product_assertion": "post_effect",
    "cleanup": "post_effect",
}
VANTAGE_POINTS = {
    "host", "container", "browser", "device", "remote_runner", "cloud", "gpu",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", help="JSON-compatible Harness candidate")
    return parser.parse_args()


def object_fields(value: object, required: set[str], path: str) -> tuple[list[str], dict]:
    if not isinstance(value, dict):
        return [f"{path} must be an object"], {}
    errors = [f"{path}.{field} is required" for field in sorted(required - set(value))]
    errors.extend(f"{path}.{field} is not allowed" for field in sorted(set(value) - required))
    return errors, value


def non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def string_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(non_empty_string(item) for item in value)


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_candidate(candidate: dict) -> list[str]:
    errors, candidate = object_fields(candidate, {
        "candidate_version", "candidate_status", "owner_review", "compatibility",
        "run", "entrypoint_closure", "acquisition", "observations",
    }, "candidate")
    if candidate.get("candidate_version") != "1.0":
        errors.append("candidate.candidate_version must be 1.0")
    if candidate.get("candidate_status") != "proposal":
        errors.append("candidate.candidate_status must remain proposal")

    review_errors, review = object_fields(
        candidate.get("owner_review"), {"status", "owner", "reviewed_at"},
        "candidate.owner_review",
    )
    errors.extend(review_errors)
    if review.get("status") not in {"pending", "approved"}:
        errors.append("candidate.owner_review.status is invalid")
    if not non_empty_string(review.get("owner")):
        errors.append("candidate.owner_review.owner is required")
    reviewed_at = review.get("reviewed_at")
    if review.get("status") == "approved" and not valid_timestamp(reviewed_at):
        errors.append("approved candidate owner review requires reviewed_at")
    if review.get("status") == "pending" and reviewed_at is not None:
        errors.append("pending candidate owner review must not set reviewed_at")

    compatibility_errors, compatibility = object_fields(
        candidate.get("compatibility"),
        {"evidence_ledger_schema_change", "ledger_integration"},
        "candidate.compatibility",
    )
    errors.extend(compatibility_errors)
    if compatibility.get("evidence_ledger_schema_change") is not False:
        errors.append("candidate must not change the v3 evidence ledger schema")
    if compatibility.get("ledger_integration") != "not_proposed":
        errors.append("candidate ledger integration must remain not_proposed")

    run_errors, run = object_fields(
        candidate.get("run"), {"run_id", "subject_sha256", "authorization_id"},
        "candidate.run",
    )
    errors.extend(run_errors)
    for field in ("run_id", "authorization_id"):
        if not non_empty_string(run.get(field)):
            errors.append(f"candidate.run.{field} is required")
    if not valid_sha256(run.get("subject_sha256")):
        errors.append("candidate.run.subject_sha256 must be a SHA-256 digest")

    closure_errors, closure = object_fields(candidate.get("entrypoint_closure"), {
        "entrypoint", "preconditions", "authorization_boundary", "effect_commit_point",
        "runtime_assertions", "required_artifacts", "offline_verifier", "cleanup_owner",
        "failure_path", "static_evidence",
    }, "candidate.entrypoint_closure")
    errors.extend(closure_errors)
    for field in (
        "entrypoint", "authorization_boundary", "effect_commit_point",
        "offline_verifier", "cleanup_owner", "failure_path",
    ):
        if not non_empty_string(closure.get(field)):
            errors.append(f"candidate.entrypoint_closure.{field} is required")
    for field in ("preconditions", "runtime_assertions", "required_artifacts", "static_evidence"):
        if not string_list(closure.get(field)):
            errors.append(f"candidate.entrypoint_closure.{field} must be a non-empty string list")
    required_artifacts = closure.get("required_artifacts", [])
    if not string_list(required_artifacts):
        required_artifacts = []
    else:
        if len(required_artifacts) != len(set(required_artifacts)):
            errors.append("candidate.entrypoint_closure.required_artifacts contains duplicates")
        for artifact in required_artifacts:
            if not safe_relative_path(artifact):
                errors.append(f"required artifact is not project-relative: {artifact}")

    acquisition_errors, acquisition = object_fields(candidate.get("acquisition"), {
        "target", "required_vantage_points", "authorization", "artifact_set",
    }, "candidate.acquisition")
    errors.extend(acquisition_errors)
    if not non_empty_string(acquisition.get("target")):
        errors.append("candidate.acquisition.target is required")
    vantage = acquisition.get("required_vantage_points")
    if not isinstance(vantage, dict) or set(vantage) != set(ASSERTION_ORDER):
        errors.append("candidate.acquisition.required_vantage_points must cover every assertion kind")
        vantage = {}
    else:
        for kind, point in vantage.items():
            if point not in VANTAGE_POINTS:
                errors.append(f"candidate.acquisition.required_vantage_points.{kind} is invalid")
        effect_vantage = vantage.get("effect")
        for kind in ("capability_preflight", "target_context_readiness"):
            if vantage.get(kind) != effect_vantage:
                errors.append(f"{kind} must run from the effect vantage point")
    authorization_errors, authorization = object_fields(
        acquisition.get("authorization"), {"authorization_id", "required", "granted"},
        "candidate.acquisition.authorization",
    )
    errors.extend(authorization_errors)
    if authorization.get("authorization_id") != run.get("authorization_id"):
        errors.append("acquisition authorization does not match the run authorization")
    if not isinstance(authorization.get("required"), bool):
        errors.append("candidate.acquisition.authorization.required must be boolean")
    if not isinstance(authorization.get("granted"), bool):
        errors.append("candidate.acquisition.authorization.granted must be boolean")
    if authorization.get("required") is True and authorization.get("granted") is not True:
        errors.append("required acquisition authorization was not granted")
    artifact_set = acquisition.get("artifact_set")
    if not string_list(artifact_set):
        errors.append("candidate.acquisition.artifact_set must be a non-empty string list")
        artifact_set = []
    elif len(artifact_set) != len(set(artifact_set)):
        errors.append("candidate.acquisition.artifact_set contains duplicates")
    if set(artifact_set) != set(required_artifacts):
        errors.append("acquisition artifact_set must exactly match required_artifacts")

    observations = candidate.get("observations")
    if not isinstance(observations, list):
        return errors + ["candidate.observations must be an array"]
    by_kind: dict[str, dict] = {}
    observed_artifacts: list[str] = []
    observation_fields = {
        "run_id", "execution_state", "phase", "vantage_point", "target",
        "command_digest", "started_at", "finished_at", "result_digest", "status",
        "subject_sha256", "authorization_id", "assertion_kind", "artifact_ref",
        "evidence_kind",
    }
    for index, raw in enumerate(observations):
        path = f"candidate.observations[{index}]"
        observation_errors, observation = object_fields(raw, observation_fields, path)
        errors.extend(observation_errors)
        kind = observation.get("assertion_kind")
        if kind not in ASSERTION_ORDER:
            errors.append(f"{path}.assertion_kind is invalid")
            continue
        if kind in by_kind:
            errors.append(f"duplicate observation assertion_kind: {kind}")
        by_kind[kind] = observation
        if observation.get("run_id") != run.get("run_id"):
            errors.append(f"{path}.run_id does not match candidate.run")
        if observation.get("subject_sha256") != run.get("subject_sha256"):
            errors.append(f"{path}.subject_sha256 does not match candidate.run")
        if observation.get("authorization_id") != run.get("authorization_id"):
            errors.append(f"{path}.authorization_id does not match candidate.run")
        if observation.get("execution_state") != "executed":
            errors.append(f"{path}.execution_state must be executed")
        if observation.get("status") != "PASS":
            errors.append(f"{path}.status must be PASS")
        if observation.get("evidence_kind") != "runtime":
            errors.append(f"{path}.evidence_kind must be runtime; static reachability is insufficient")
        if observation.get("phase") != ASSERTION_PHASE[kind]:
            errors.append(f"{path}.phase is invalid for {kind}")
        if observation.get("vantage_point") != vantage.get(kind):
            errors.append(f"{path}.vantage_point does not match the required effect context")
        if observation.get("target") != acquisition.get("target"):
            errors.append(f"{path}.target does not match the acquisition target")
        for field in ("command_digest", "result_digest"):
            if not valid_sha256(observation.get(field)):
                errors.append(f"{path}.{field} must be a SHA-256 digest")
        for field in ("started_at", "finished_at"):
            if not valid_timestamp(observation.get(field)):
                errors.append(f"{path}.{field} must be a timezone-aware timestamp")
        if valid_timestamp(observation.get("started_at")) and valid_timestamp(observation.get("finished_at")):
            if parse_time(observation["started_at"]) > parse_time(observation["finished_at"]):
                errors.append(f"{path} finishes before it starts")
        artifact = observation.get("artifact_ref")
        if not safe_relative_path(artifact):
            errors.append(f"{path}.artifact_ref must be project-relative")
        else:
            observed_artifacts.append(artifact)

    missing_kinds = [kind for kind in ASSERTION_ORDER if kind not in by_kind]
    if missing_kinds:
        errors.append(f"missing required runtime observations: {', '.join(missing_kinds)}")
    if set(observed_artifacts) != set(required_artifacts) or len(observed_artifacts) != len(required_artifacts):
        errors.append("runtime observation artifacts must exactly close the required artifact set")
    if not missing_kinds:
        for earlier, later in zip(ASSERTION_ORDER, ASSERTION_ORDER[1:]):
            first = by_kind[earlier]
            second = by_kind[later]
            if valid_timestamp(first.get("finished_at")) and valid_timestamp(second.get("started_at")):
                if parse_time(first["finished_at"]) > parse_time(second["started_at"]):
                    errors.append(f"observation order is invalid: {earlier} must precede {later}")
    return errors


def main() -> int:
    args = parse_args()
    try:
        candidate = load_json_yaml(Path(args.candidate))
    except ValueError as exc:
        print(json.dumps({"status": "CANDIDATE_ERROR", "errors": [str(exc)]}, sort_keys=True))
        return 2
    errors = validate_candidate(candidate)
    if errors:
        print(json.dumps({
            "status": "CANDIDATE_REJECTED",
            "diagnostics": bounded_diagnostics(errors),
        }, indent=2, sort_keys=True))
        return 1
    print(json.dumps({
        "status": "CANDIDATE_VALID",
        "promotion_status": "OWNER_REVIEW_REQUIRED"
        if candidate["owner_review"]["status"] == "pending"
        else "COMPATIBILITY_REVIEW_REQUIRED",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
