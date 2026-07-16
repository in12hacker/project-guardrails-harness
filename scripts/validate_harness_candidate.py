#!/usr/bin/env python3
"""Validate a portable multi-hop execution proposal without emitting evidence PASS."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from generation_common import bounded_diagnostics
from quality_common import (
    load_json_yaml,
    safe_relative_path,
    valid_enum,
    valid_sha256,
    valid_timestamp,
)


ASSERTION_KINDS = {
    "capability_preflight",
    "target_context_readiness",
    "effect_attempt",
    "effect_execution_step",
    "effect_commit",
    "effect_outcome",
    "product_assertion",
    "cleanup",
}
EFFECT_KINDS = {
    "effect_attempt", "effect_execution_step", "effect_commit", "effect_outcome",
}
EFFECT_RESULTS = {"committed", "prevented"}
ASSERTION_PHASE = {
    "capability_preflight": "pre_effect",
    "target_context_readiness": "pre_effect",
    "effect_attempt": "effect",
    "effect_execution_step": "effect",
    "effect_commit": "effect",
    "effect_outcome": "post_effect",
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


def string_list(value: object, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(non_empty_string(item) for item in value)
    )


def string_key_get(mapping: dict[str, dict], key: object) -> dict | None:
    """Read an externally selected object without hashing malformed keys."""
    return mapping.get(key) if isinstance(key, str) else None


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def graph_ancestors(graph: dict[str, list[str]], node: str) -> set[str]:
    ancestors: set[str] = set()
    pending = list(graph.get(node, []))
    while pending:
        parent = pending.pop()
        if parent in ancestors:
            continue
        ancestors.add(parent)
        pending.extend(graph.get(parent, []))
    return ancestors


def graph_errors(graph: dict[str, list[str]], path: str) -> list[str]:
    errors: list[str] = []
    nodes = set(graph)
    for node, dependencies in graph.items():
        for dependency in dependencies:
            if dependency not in nodes:
                errors.append(f"{path}.{node} references unknown dependency {dependency}")
            if dependency == node:
                errors.append(f"{path}.{node} cannot depend on itself")
        if len(dependencies) != len(set(dependencies)):
            errors.append(f"{path}.{node} contains duplicate dependencies")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"{path} contains a cycle at {node}")
            return
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, []):
            if dependency in graph:
                visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    return errors


def exact_references(
    declared: object, actual: set[str], path: str, *, allow_empty: bool = False,
) -> list[str]:
    if not string_list(declared, allow_empty=allow_empty):
        qualifier = "an observation ID list" if allow_empty else "a non-empty observation ID list"
        return [f"{path} must be {qualifier}"]
    errors: list[str] = []
    if len(declared) != len(set(declared)):
        errors.append(f"{path} contains duplicate observation IDs")
    if set(declared) != actual:
        errors.append(f"{path} must exactly reference its runtime observations")
    return errors


def validate_candidate(candidate: dict) -> list[str]:
    errors, candidate = object_fields(candidate, {
        "candidate_version", "candidate_status", "owner_review", "compatibility",
        "run", "entrypoint_closure", "acquisition", "hops", "protection_edges",
        "observations",
    }, "candidate")
    if candidate.get("candidate_version") != "2.0":
        errors.append("candidate.candidate_version must be 2.0")
    if candidate.get("candidate_status") != "proposal":
        errors.append("candidate.candidate_status must remain proposal")

    review_errors, review = object_fields(
        candidate.get("owner_review"), {"status", "owner", "reviewed_at"},
        "candidate.owner_review",
    )
    errors.extend(review_errors)
    if not valid_enum(review.get("status"), {"pending", "approved"}):
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
        "entrypoint", "preconditions", "authorization_boundary", "effect_attempts",
        "effect_execution_steps", "effect_commit_points", "effect_outcomes", "runtime_assertions",
        "required_artifacts", "offline_verifier", "cleanup_observations",
        "cleanup_owners", "failure_paths", "static_evidence",
    }, "candidate.entrypoint_closure")
    errors.extend(closure_errors)
    for field in ("entrypoint", "authorization_boundary", "offline_verifier"):
        if not non_empty_string(closure.get(field)):
            errors.append(f"candidate.entrypoint_closure.{field} is required")
    if not string_list(closure.get("preconditions")):
        errors.append("candidate.entrypoint_closure.preconditions must be a non-empty string list")

    static_evidence = closure.get("static_evidence")
    static_artifacts: list[str] = []
    if not isinstance(static_evidence, list) or not static_evidence:
        errors.append("candidate.entrypoint_closure.static_evidence must be a non-empty array")
        static_evidence = []
    for index, raw in enumerate(static_evidence):
        path = f"candidate.entrypoint_closure.static_evidence[{index}]"
        item_errors, item = object_fields(raw, {"artifact_ref", "sha256", "evidence_kind"}, path)
        errors.extend(item_errors)
        artifact_ref = item.get("artifact_ref")
        if not safe_relative_path(artifact_ref):
            errors.append(f"{path}.artifact_ref must be project-relative")
        else:
            static_artifacts.append(artifact_ref)
        if not valid_sha256(item.get("sha256")):
            errors.append(f"{path}.sha256 must be a SHA-256 digest")
        if item.get("evidence_kind") != "static_reachability":
            errors.append(f"{path}.evidence_kind must be static_reachability")

    failure_paths = closure.get("failure_paths")
    parsed_failure_paths: list[dict] = []
    failure_path_ids: set[str] = set()
    if not isinstance(failure_paths, list) or not failure_paths:
        errors.append("candidate.entrypoint_closure.failure_paths must be a non-empty array")
        failure_paths = []
    for index, raw in enumerate(failure_paths):
        path = f"candidate.entrypoint_closure.failure_paths[{index}]"
        item_errors, item = object_fields(
            raw, {"path_id", "owners", "cleanup_observation_ids"}, path,
        )
        errors.extend(item_errors)
        path_id = item.get("path_id")
        if not non_empty_string(path_id):
            errors.append(f"{path}.path_id is required")
        elif path_id in failure_path_ids:
            errors.append(f"duplicate failure path_id: {path_id}")
        else:
            failure_path_ids.add(path_id)
        if not string_list(item.get("owners")):
            errors.append(f"{path}.owners must be a non-empty owner list")
        if not string_list(item.get("cleanup_observation_ids")):
            errors.append(f"{path}.cleanup_observation_ids must be a non-empty observation ID list")
        parsed_failure_paths.append(item)
    required_artifacts = closure.get("required_artifacts", [])
    if not string_list(required_artifacts):
        errors.append("candidate.entrypoint_closure.required_artifacts must be a non-empty string list")
        required_artifacts = []
    else:
        if len(required_artifacts) != len(set(required_artifacts)):
            errors.append("candidate.entrypoint_closure.required_artifacts contains duplicates")
        for artifact in required_artifacts:
            if not safe_relative_path(artifact):
                errors.append(f"required artifact is not project-relative: {artifact}")

    hop_graph: dict[str, list[str]] = {}
    hops_by_id: dict[str, dict] = {}
    hops = candidate.get("hops")
    if not isinstance(hops, list) or not hops:
        errors.append("candidate.hops must be a non-empty array")
        hops = []
    hop_fields = {"hop_id", "owner", "target", "vantage_point", "depends_on"}
    for index, raw in enumerate(hops):
        path = f"candidate.hops[{index}]"
        hop_errors, hop = object_fields(raw, hop_fields, path)
        errors.extend(hop_errors)
        hop_id = hop.get("hop_id")
        if not non_empty_string(hop_id):
            errors.append(f"{path}.hop_id is required")
            continue
        if hop_id in hops_by_id:
            errors.append(f"duplicate hop_id: {hop_id}")
            continue
        hops_by_id[hop_id] = hop
        for field in ("owner", "target"):
            if not non_empty_string(hop.get(field)):
                errors.append(f"{path}.{field} is required")
        if not valid_enum(hop.get("vantage_point"), VANTAGE_POINTS):
            errors.append(f"{path}.vantage_point is invalid")
        dependencies = hop.get("depends_on")
        if not string_list(dependencies, allow_empty=True):
            errors.append(f"{path}.depends_on must be a string array")
            dependencies = []
        hop_graph[hop_id] = dependencies
    errors.extend(graph_errors(hop_graph, "candidate.hops"))

    acquisition_errors, acquisition = object_fields(candidate.get("acquisition"), {
        "capabilities", "authorization", "artifact_set",
    }, "candidate.acquisition")
    errors.extend(acquisition_errors)
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

    capabilities_by_id: dict[str, dict] = {}
    capabilities = acquisition.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        errors.append("candidate.acquisition.capabilities must be a non-empty array")
        capabilities = []
    capability_fields = {
        "capability_id", "hop_id", "owner", "target", "vantage_point",
        "authorization_required",
    }
    for index, raw in enumerate(capabilities):
        path = f"candidate.acquisition.capabilities[{index}]"
        capability_errors, capability = object_fields(raw, capability_fields, path)
        errors.extend(capability_errors)
        capability_id = capability.get("capability_id")
        if not non_empty_string(capability_id):
            errors.append(f"{path}.capability_id is required")
            continue
        if capability_id in capabilities_by_id:
            errors.append(f"duplicate capability_id: {capability_id}")
            continue
        capabilities_by_id[capability_id] = capability
        hop = string_key_get(hops_by_id, capability.get("hop_id"))
        if hop is None:
            errors.append(f"{path}.hop_id references an unknown hop")
        else:
            for field in ("owner", "target", "vantage_point"):
                if capability.get(field) != hop.get(field):
                    errors.append(f"{path}.{field} does not match its hop")
        if not isinstance(capability.get("authorization_required"), bool):
            errors.append(f"{path}.authorization_required must be boolean")
        if capability.get("authorization_required") is True and authorization.get("granted") is not True:
            errors.append(f"{path} requires acquisition authorization")

    artifact_set = acquisition.get("artifact_set")
    if not string_list(artifact_set):
        errors.append("candidate.acquisition.artifact_set must be a non-empty string list")
        artifact_set = []
    elif len(artifact_set) != len(set(artifact_set)):
        errors.append("candidate.acquisition.artifact_set contains duplicates")
    if set(artifact_set) != set(required_artifacts):
        errors.append("acquisition artifact_set must exactly match required_artifacts")

    observations = candidate.get("observations")
    if not isinstance(observations, list) or not observations:
        return errors + ["candidate.observations must be a non-empty array"]
    observations_by_id: dict[str, dict] = {}
    temporal_graph: dict[str, list[str]] = {}
    flow_graph: dict[str, list[str]] = {}
    observed_artifacts: list[str] = []
    observation_fields = {
        "observation_id", "hop_id", "capability_id", "depends_on", "flow_depends_on",
        "effect_id", "effect_result", "required_capability_ids", "run_id", "execution_state", "phase",
        "vantage_point", "target", "command_digest", "started_at", "finished_at",
        "result_digest", "status", "subject_sha256", "authorization_id",
        "assertion_kind", "artifact_ref", "evidence_kind",
    }
    for index, raw in enumerate(observations):
        path = f"candidate.observations[{index}]"
        observation_errors, observation = object_fields(raw, observation_fields, path)
        errors.extend(observation_errors)
        observation_id = observation.get("observation_id")
        if not non_empty_string(observation_id):
            errors.append(f"{path}.observation_id is required")
            continue
        if observation_id in observations_by_id:
            errors.append(f"duplicate observation_id: {observation_id}")
            continue
        observations_by_id[observation_id] = observation
        for field, graph in (("depends_on", temporal_graph), ("flow_depends_on", flow_graph)):
            dependencies = observation.get(field)
            if not string_list(dependencies, allow_empty=True):
                errors.append(f"{path}.{field} must be a string array")
                dependencies = []
            graph[observation_id] = dependencies
        kind = observation.get("assertion_kind")
        if not valid_enum(kind, ASSERTION_KINDS):
            errors.append(f"{path}.assertion_kind is invalid")
        else:
            if observation.get("phase") != ASSERTION_PHASE[kind]:
                errors.append(f"{path}.phase is invalid for {kind}")
            effect_id = observation.get("effect_id")
            if kind in EFFECT_KINDS | {"product_assertion"} and not non_empty_string(effect_id):
                errors.append(f"{path}.effect_id is required for {kind}")
            if kind not in EFFECT_KINDS | {"product_assertion"} and effect_id is not None:
                errors.append(f"{path}.effect_id must be null for {kind}")
            effect_result = observation.get("effect_result")
            if kind in {"effect_outcome", "product_assertion"}:
                if not valid_enum(effect_result, EFFECT_RESULTS):
                    errors.append(
                        f"{path}.effect_result must be one of: {', '.join(sorted(EFFECT_RESULTS))}",
                    )
            elif effect_result is not None:
                errors.append(f"{path}.effect_result must be null for {kind}")
            required_capabilities = observation.get("required_capability_ids")
            if kind == "effect_attempt":
                if not string_list(required_capabilities):
                    errors.append(f"{path}.required_capability_ids must be non-empty")
                else:
                    if len(required_capabilities) != len(set(required_capabilities)):
                        errors.append(f"{path}.required_capability_ids contains duplicates")
                    unknown = sorted(set(required_capabilities) - set(capabilities_by_id))
                    if unknown:
                        errors.append(
                            f"{path}.required_capability_ids contains unknown capabilities: "
                            + ", ".join(unknown),
                        )
            elif required_capabilities != []:
                errors.append(f"{path}.required_capability_ids must be empty for {kind}")
        capability = string_key_get(
            capabilities_by_id, observation.get("capability_id"),
        )
        if capability is None:
            errors.append(f"{path}.capability_id references an unknown capability")
        else:
            if observation.get("hop_id") != capability.get("hop_id"):
                errors.append(f"{path}.hop_id does not match its capability")
            for field in ("target", "vantage_point"):
                if observation.get(field) != capability.get(field):
                    errors.append(f"{path}.{field} does not match its capability")
        if (
            not isinstance(observation.get("hop_id"), str)
            or observation["hop_id"] not in hops_by_id
        ):
            errors.append(f"{path}.hop_id references an unknown hop")
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

    errors.extend(graph_errors(temporal_graph, "candidate.observations.depends_on"))
    errors.extend(graph_errors(flow_graph, "candidate.observations.flow_depends_on"))
    all_artifacts = [*observed_artifacts, *static_artifacts]
    if set(all_artifacts) != set(required_artifacts) or len(all_artifacts) != len(required_artifacts):
        errors.append("runtime and static artifacts must exactly close the required artifact set")

    used_hops = {
        item["hop_id"] for item in observations_by_id.values()
        if isinstance(item.get("hop_id"), str)
    }
    for hop_id in sorted(set(hops_by_id) - used_hops):
        errors.append(f"declared hop has no runtime observation: {hop_id}")
    used_capabilities = {
        item["capability_id"] for item in observations_by_id.values()
        if isinstance(item.get("capability_id"), str)
    }
    for capability_id in sorted(set(capabilities_by_id) - used_capabilities):
        errors.append(f"declared capability has no runtime observation: {capability_id}")

    actual_by_kind = {
        kind: {
            observation_id for observation_id, observation in observations_by_id.items()
            if observation.get("assertion_kind") == kind
        }
        for kind in ASSERTION_KINDS
    }
    closure_fields = {
        "effect_attempts": "effect_attempt",
        "effect_execution_steps": "effect_execution_step",
        "effect_commit_points": "effect_commit",
        "effect_outcomes": "effect_outcome",
        "runtime_assertions": "product_assertion",
        "cleanup_observations": "cleanup",
    }
    for field, kind in closure_fields.items():
        errors.extend(exact_references(
            closure.get(field), actual_by_kind[kind],
            f"candidate.entrypoint_closure.{field}",
            allow_empty=field in {"effect_execution_steps", "effect_commit_points"},
        ))
    cleanup_owners = closure.get("cleanup_owners")
    actual_cleanup_owners: set[str] = set()
    for observation in observations_by_id.values():
        if observation.get("assertion_kind") != "cleanup":
            continue
        capability = string_key_get(
            capabilities_by_id, observation.get("capability_id"),
        )
        if capability is not None and isinstance(capability.get("owner"), str):
            actual_cleanup_owners.add(capability["owner"])
    if not string_list(cleanup_owners):
        errors.append("candidate.entrypoint_closure.cleanup_owners must be a non-empty owner list")
    elif len(cleanup_owners) != len(set(cleanup_owners)) or set(cleanup_owners) != actual_cleanup_owners:
        errors.append("candidate.entrypoint_closure.cleanup_owners must exactly match cleanup observation owners")

    referenced_failure_cleanups: set[str] = set()
    for index, failure_path in enumerate(parsed_failure_paths):
        path = f"candidate.entrypoint_closure.failure_paths[{index}]"
        cleanup_ids = failure_path.get("cleanup_observation_ids", [])
        if not string_list(cleanup_ids):
            cleanup_ids = []
        valid_cleanup_ids = {
            item for item in cleanup_ids if item in actual_by_kind["cleanup"]
        }
        if not string_list(cleanup_ids) or len(valid_cleanup_ids) != len(cleanup_ids):
            errors.append(f"{path}.cleanup_observation_ids must reference cleanup observations")
        referenced_failure_cleanups.update(valid_cleanup_ids)
        actual_owners: set[str] = set()
        for item in valid_cleanup_ids:
            capability = string_key_get(
                capabilities_by_id,
                observations_by_id[item].get("capability_id"),
            )
            if capability is not None and isinstance(capability.get("owner"), str):
                actual_owners.add(capability["owner"])
        owners = failure_path.get("owners")
        if string_list(owners) and (
            len(owners) != len(set(owners)) or set(owners) != actual_owners
        ):
            errors.append(f"{path}.owners must exactly match its cleanup observation owners")
    if referenced_failure_cleanups != actual_by_kind["cleanup"]:
        errors.append("failure paths must collectively reference every cleanup observation")

    for observation_id, observation in observations_by_id.items():
        temporal_ancestors = graph_ancestors(temporal_graph, observation_id)
        flow_ancestors = graph_ancestors(flow_graph, observation_id)
        for dependency_id in temporal_graph.get(observation_id, []):
            dependency = observations_by_id.get(dependency_id)
            if dependency is None:
                continue
            if valid_timestamp(dependency.get("finished_at")) and valid_timestamp(observation.get("started_at")):
                if parse_time(dependency["finished_at"]) > parse_time(observation["started_at"]):
                    errors.append(f"observation order is invalid: {dependency_id} must precede {observation_id}")
        for dependency_id in flow_graph.get(observation_id, []):
            dependency = observations_by_id.get(dependency_id)
            if dependency is None:
                continue
            if dependency_id not in temporal_ancestors:
                errors.append(f"data flow {dependency_id}->{observation_id} lacks temporal ordering")
            source_hop = dependency.get("hop_id")
            target_hop = observation.get("hop_id")
            cross_hop_valid = (
                isinstance(source_hop, str)
                and isinstance(target_hop, str)
                and source_hop in graph_ancestors(hop_graph, target_hop)
            )
            if source_hop != target_hop and not cross_hop_valid:
                errors.append(f"data flow {dependency_id}->{observation_id} violates the hop DAG")
        kind = observation.get("assertion_kind")
        if valid_enum(kind, {"product_assertion", "cleanup"}) and not any(
            observations_by_id[item].get("assertion_kind") == "effect_outcome"
            for item in temporal_ancestors if item in observations_by_id
        ):
            errors.append(f"{kind} observation {observation_id} lacks an effect_outcome ancestor")
        if kind == "product_assertion" and not any(
            observations_by_id[item].get("assertion_kind") == "effect_outcome"
            for item in flow_ancestors if item in observations_by_id
        ):
            errors.append(
                f"product_assertion observation {observation_id} lacks effect_outcome data flow",
            )
        if kind == "effect_commit" and not flow_ancestors:
            errors.append(f"effect_commit observation {observation_id} lacks execution data flow")

    for hop_id, direct_dependencies in hop_graph.items():
        hop_observations = [
            observation_id for observation_id, observation in observations_by_id.items()
            if observation.get("hop_id") == hop_id
        ]
        for dependency_hop in direct_dependencies:
            if not any(
                any(
                    observations_by_id[ancestor].get("hop_id") == dependency_hop
                    for ancestor in graph_ancestors(flow_graph, observation_id)
                    if ancestor in observations_by_id
                )
                for observation_id in hop_observations
            ):
                errors.append(f"hop {hop_id} has no data-flow observation from {dependency_hop}")

    lifecycle_by_effect: dict[str, dict[str, list[str]]] = {}
    for observation_id, observation in observations_by_id.items():
        kind = observation.get("assertion_kind")
        effect_id = observation.get("effect_id")
        if valid_enum(kind, EFFECT_KINDS) and non_empty_string(effect_id):
            lifecycle_by_effect.setdefault(effect_id, {}).setdefault(kind, []).append(observation_id)
    for effect_id, lifecycle in lifecycle_by_effect.items():
        for kind in ("effect_attempt", "effect_outcome"):
            if len(lifecycle.get(kind, [])) != 1:
                errors.append(f"effect {effect_id} requires exactly one {kind} observation")
        if not all(
            len(lifecycle.get(kind, [])) == 1
            for kind in ("effect_attempt", "effect_outcome")
        ):
            continue
        attempt = lifecycle["effect_attempt"][0]
        outcome = lifecycle["effect_outcome"][0]
        execution_steps = lifecycle.get("effect_execution_step", [])
        commits = lifecycle.get("effect_commit", [])
        outcome_result = observations_by_id[outcome].get("effect_result")
        for step in execution_steps:
            if attempt not in graph_ancestors(temporal_graph, step):
                errors.append(f"effect {effect_id} execution step does not follow its attempt: {step}")
            if attempt not in graph_ancestors(flow_graph, step):
                errors.append(f"effect {effect_id} execution step is not data-flow connected: {step}")
        required_predecessors = execution_steps or [attempt]
        if outcome_result == "committed":
            if len(commits) != 1:
                errors.append(f"committed effect {effect_id} requires exactly one effect_commit observation")
            else:
                commit = commits[0]
                for predecessor in required_predecessors:
                    if predecessor not in graph_ancestors(temporal_graph, commit):
                        errors.append(f"effect {effect_id} commit does not follow {predecessor}")
                    if predecessor not in graph_ancestors(flow_graph, commit):
                        errors.append(f"effect {effect_id} commit is not data-flow connected to {predecessor}")
                if commit not in graph_ancestors(temporal_graph, outcome):
                    errors.append(f"effect {effect_id} outcome does not follow its commit")
                if commit not in graph_ancestors(flow_graph, outcome):
                    errors.append(f"effect {effect_id} outcome is not data-flow connected to its commit")
        elif outcome_result == "prevented":
            if commits:
                errors.append(f"prevented effect {effect_id} must not contain an effect_commit observation")
            for predecessor in required_predecessors:
                if predecessor not in graph_ancestors(temporal_graph, outcome):
                    errors.append(f"prevented effect {effect_id} outcome does not follow {predecessor}")
                if predecessor not in graph_ancestors(flow_graph, outcome):
                    errors.append(
                        f"prevented effect {effect_id} outcome is not data-flow connected to {predecessor}",
                    )
        assertions = [
            item for item in actual_by_kind["product_assertion"]
            if observations_by_id[item].get("effect_id") == effect_id
        ]
        if not assertions:
            errors.append(f"effect {effect_id} has no product assertion descendant")
        for assertion in assertions:
            if outcome not in graph_ancestors(temporal_graph, assertion):
                errors.append(f"effect {effect_id} assertion does not follow its outcome: {assertion}")
            if outcome not in graph_ancestors(flow_graph, assertion):
                errors.append(f"effect {effect_id} assertion lacks outcome data flow: {assertion}")
            if observations_by_id[assertion].get("effect_result") != outcome_result:
                errors.append(f"effect {effect_id} assertion result does not match its outcome")
        cleanups = actual_by_kind["cleanup"]
        if not any(outcome in graph_ancestors(temporal_graph, item) for item in cleanups):
            errors.append(f"effect {effect_id} has no cleanup descendant")
    for assertion_id in actual_by_kind["product_assertion"]:
        asserted_effect = observations_by_id[assertion_id].get("effect_id")
        if (
            not isinstance(asserted_effect, str)
            or asserted_effect not in lifecycle_by_effect
        ):
            errors.append(
                f"product assertion {assertion_id} references unknown effect {asserted_effect}",
            )

    protection_edges = candidate.get("protection_edges")
    if not isinstance(protection_edges, list) or not protection_edges:
        errors.append("candidate.protection_edges must be a non-empty array")
        protection_edges = []
    protected_effects: set[str] = set()
    protected_capabilities: dict[str, set[str]] = {}
    protection_keys: set[tuple[str, str]] = set()
    protection_fields = {
        "capability_id", "effect_id", "preflight_observation_id",
        "readiness_observation_id",
    }
    for index, raw in enumerate(protection_edges):
        path = f"candidate.protection_edges[{index}]"
        edge_errors, edge = object_fields(raw, protection_fields, path)
        errors.extend(edge_errors)
        capability_id = edge.get("capability_id")
        effect_id = edge.get("effect_id")
        if not non_empty_string(capability_id) or capability_id not in capabilities_by_id:
            errors.append(f"{path}.capability_id references an unknown capability")
        if not non_empty_string(effect_id) or effect_id not in lifecycle_by_effect:
            errors.append(f"{path}.effect_id references an unknown effect")
        if non_empty_string(capability_id) and non_empty_string(effect_id):
            key = (capability_id, effect_id)
            if key in protection_keys:
                errors.append(f"duplicate protection edge: {capability_id}->{effect_id}")
            protection_keys.add(key)
            protected_effects.add(effect_id)
            protected_capabilities.setdefault(effect_id, set()).add(capability_id)
        preflight_id = edge.get("preflight_observation_id")
        readiness_id = edge.get("readiness_observation_id")
        preflight = string_key_get(observations_by_id, preflight_id)
        readiness = string_key_get(observations_by_id, readiness_id)
        if preflight is None or preflight.get("assertion_kind") != "capability_preflight":
            errors.append(f"{path}.preflight_observation_id must reference capability_preflight")
        elif preflight.get("capability_id") != capability_id:
            errors.append(f"{path}.preflight observation uses a different capability")
        if readiness is None or readiness.get("assertion_kind") != "target_context_readiness":
            errors.append(f"{path}.readiness_observation_id must reference target_context_readiness")
        elif readiness.get("capability_id") != capability_id:
            errors.append(f"{path}.readiness observation uses a different capability")
        lifecycle = (
            lifecycle_by_effect.get(effect_id, {})
            if isinstance(effect_id, str) else {}
        )
        attempts = lifecycle.get("effect_attempt", [])
        commits = lifecycle.get("effect_commit", [])
        if (
            isinstance(preflight_id, str)
            and isinstance(readiness_id, str)
            and preflight_id in observations_by_id
            and readiness_id in observations_by_id
        ):
            if preflight_id not in graph_ancestors(temporal_graph, readiness_id):
                errors.append(f"{path} readiness does not follow its preflight")
            for protected_id in [*attempts, *commits]:
                if readiness_id not in graph_ancestors(temporal_graph, protected_id):
                    errors.append(f"{path} readiness does not precede protected {protected_id}")
    for effect_id in sorted(set(lifecycle_by_effect) - protected_effects):
        errors.append(f"effect has no capability protection edge: {effect_id}")
    for effect_id, lifecycle in lifecycle_by_effect.items():
        attempts = lifecycle.get("effect_attempt", [])
        if len(attempts) != 1:
            continue
        declared = observations_by_id[attempts[0]].get("required_capability_ids")
        if string_list(declared) and set(declared) != protected_capabilities.get(effect_id, set()):
            errors.append(
                f"effect {effect_id} required_capability_ids do not match protection edges",
            )
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
