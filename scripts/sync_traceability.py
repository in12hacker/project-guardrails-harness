#!/usr/bin/env python3
"""Regenerate the derived traceability graph after registry review."""

from __future__ import annotations

import argparse
from pathlib import Path

from quality_common import (
    build_traceability_graph,
    load_json_yaml,
    validate_registry,
    write_json_yaml,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--guardrails-dir", default=".guardrails")
    args = parser.parse_args()

    guardrails = Path(args.root).resolve() / args.guardrails_dir
    try:
        registry = load_json_yaml(guardrails / "control-registry.yaml")
    except ValueError as exc:
        print(f"FAIL [QF-TRACEABILITY]: {exc}")
        return 2
    errors = validate_registry(registry)
    if errors:
        for error in errors:
            print(f"FAIL [QF-TRACEABILITY]: {error}")
        return 2
    target = guardrails / "traceability-graph.json"
    write_json_yaml(target, build_traceability_graph(registry))
    print(f"regenerated {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
