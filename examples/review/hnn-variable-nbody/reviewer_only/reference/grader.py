"""Recompute variable-N Hamiltonian query truth from public inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np


def locate(path: Path, instance: str) -> Path:
    candidates = [path, path / "results.json", path / "output" / instance / "results.json", path / instance / "results.json"]
    result = next((item for item in candidates if item.is_file()), None)
    if result is None:
        raise FileNotFoundError("results.json is missing")
    if result.stat().st_size > 4_000_000:
        raise ValueError("results JSON exceeds 4 MB")
    return result


def truth(query, constants):
    masses = np.asarray(query["masses"], dtype=float)
    state = np.asarray(query["state"], dtype=float)
    if state.shape != (len(masses), 4) or len(masses) < 2:
        raise ValueError("invalid query state")
    g = float(constants["gravitational_constant"])
    epsilon = float(constants["softening"])
    positions, momenta = state[:, :2], state[:, 2:]
    energy = float(np.sum(np.sum(momenta * momenta, axis=-1) / (2.0 * masses)))
    field = np.zeros_like(state)
    field[:, :2] = momenta / masses[:, None]
    for left in range(len(masses)):
        for right in range(left + 1, len(masses)):
            displacement = positions[left] - positions[right]
            squared = float(displacement @ displacement + epsilon * epsilon)
            coefficient = g * masses[left] * masses[right]
            energy -= coefficient / np.sqrt(squared)
            force = -coefficient * displacement / squared**1.5
            field[left, 2:] += force
            field[right, 2:] -= force
    return energy, field


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    input_path = root / "input" / "instances" / args.instance / "problems.json"
    policy_path = Path(__file__).resolve().parent / "instances" / args.instance / "policy.json"
    instance = json.loads(input_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    errors, metrics = [], {}
    try:
        artifact = json.loads(locate(args.submission, args.instance).read_text(encoding="utf-8"))
        if set(artifact) != {"format", "instance_id", "results"} or artifact.get("format") != "nbody-query-results-v1":
            raise ValueError("artifact does not match nbody-query-results-v1")
        if artifact.get("instance_id") != args.instance:
            raise ValueError("instance_id mismatch")
        submitted = artifact["results"]
        if not isinstance(submitted, list) or len(submitted) != policy["required_query_count"]:
            raise ValueError("wrong result count")
        by_id = {item.get("query_id"): item for item in submitted if isinstance(item, dict)}
        if len(by_id) != len(submitted):
            raise ValueError("query IDs must be unique")
        max_energy_error = 0.0
        max_field_error = 0.0
        for query in instance["queries"]:
            answer = by_id.get(query["query_id"])
            if answer is None or set(answer) != {"query_id", "hamiltonian", "field"}:
                raise ValueError(f"missing or malformed result {query['query_id']}")
            expected_energy, expected_field = truth(query, instance["constants"])
            actual_energy = float(answer["hamiltonian"])
            actual_field = np.asarray(answer["field"], dtype=float)
            if actual_field.shape != expected_field.shape or not np.all(np.isfinite(actual_field)) or not np.isfinite(actual_energy):
                raise ValueError(f"non-finite or wrong-shaped result {query['query_id']}")
            energy_error = abs(actual_energy - expected_energy)
            field_error = float(np.max(np.abs(actual_field - expected_field)))
            max_energy_error = max(max_energy_error, energy_error)
            max_field_error = max(max_field_error, field_error)
            if not np.isclose(actual_energy, expected_energy, atol=policy["absolute_tolerance"], rtol=policy["relative_tolerance"]):
                errors.append(f"{query['query_id']}: incorrect Hamiltonian")
            if not np.allclose(actual_field, expected_field, atol=policy["absolute_tolerance"], rtol=policy["relative_tolerance"]):
                errors.append(f"{query['query_id']}: incorrect canonical field")
        metrics = {"max_energy_absolute_error": max_energy_error, "max_field_absolute_error": max_field_error}
    except Exception as error:
        errors.append(f"{type(error).__name__}: {error}")
    passed = not errors
    tolerance = max(float(policy.get("absolute_tolerance", 0.0)), 1e-30)
    metric_scores = {
        "energy": max(
            0.0,
            1.0 - metrics.get("max_energy_absolute_error", float("inf")) / tolerance,
        ),
        "canonical_field": max(
            0.0,
            1.0 - metrics.get("max_field_absolute_error", float("inf")) / tolerance,
        ),
        "composition_and_equivariance": 1.0 if passed else 0.0,
    }
    score = (
        0.25 * metric_scores["energy"]
        + 0.55 * metric_scores["canonical_field"]
        + 0.2 * metric_scores["composition_and_equivariance"]
        if passed
        else 0.0
    )
    print(json.dumps({"passed": passed, "score": score, "instance": args.instance, "metrics": metrics, "metric_scores": metric_scores, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
