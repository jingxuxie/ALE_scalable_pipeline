"""Starter for variable-N softened gravitational Hamiltonian queries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def solve_problem(problem: dict, constants: dict) -> dict:
    # TODO: compute scalar H and the [dq_x,dq_y,dp_x,dp_y] field for every body.
    body_count = len(problem["masses"])
    return {
        "query_id": problem["query_id"],
        "hamiltonian": 0.0,
        "field": [[0.0, 0.0, 0.0, 0.0] for _ in range(body_count)],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    instance = json.loads(args.input.read_text(encoding="utf-8"))
    artifact = {
        "format": "nbody-query-results-v1",
        "instance_id": instance["instance_id"],
        "results": [solve_problem(query, instance["constants"]) for query in instance["queries"]],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
