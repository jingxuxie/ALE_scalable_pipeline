"""Score the induced field of a safe latent-canonical Hamiltonian."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np


def locate(path: Path, instance: str) -> Path:
    candidates = [path, path / "recovery.json", path / "output" / instance / "recovery.json", path / instance / "recovery.json"]
    result = next((item for item in candidates if item.is_file()), None)
    if result is None:
        raise FileNotFoundError("recovery.json is missing")
    if result.stat().st_size > 1_000_000:
        raise ValueError("recovery JSON exceeds 1 MB")
    return result


def parse(path):
    artifact = json.loads(path.read_text(encoding="utf-8"))
    expected = {"format", "canonical_from_observed", "kinetic", "stiffness", "quartic"}
    if set(artifact) != expected or artifact.get("format") != "latent-canonical-hamiltonian-v1":
        raise ValueError("artifact keys or format are invalid")
    transform = np.asarray(artifact["canonical_from_observed"], dtype=float)
    kinetic = np.asarray(artifact["kinetic"], dtype=float)
    stiffness = np.asarray(artifact["stiffness"], dtype=float)
    quartic = np.asarray(artifact["quartic"], dtype=float)
    if transform.shape != (4, 4) or kinetic.shape != (2, 2) or stiffness.shape != (2, 2) or quartic.shape != (3,):
        raise ValueError("artifact parameter shapes are invalid")
    if not all(np.all(np.isfinite(value)) for value in (transform, kinetic, stiffness, quartic)):
        raise ValueError("parameters must be finite")
    if np.linalg.cond(transform) > 100:
        raise ValueError("canonicalizer is singular or ill-conditioned")
    for name, matrix in (("kinetic", kinetic), ("stiffness", stiffness)):
        if not np.allclose(matrix, matrix.T, atol=1e-12) or np.min(np.linalg.eigvalsh(matrix)) <= 0:
            raise ValueError(f"{name} must be symmetric positive definite")
    if np.max(np.abs(transform)) > 20 or np.max(np.abs(kinetic)) > 20 or np.max(np.abs(stiffness)) > 20 or np.max(np.abs(quartic)) > 20:
        raise ValueError("parameter safety bound exceeded")
    return transform, kinetic, stiffness, quartic


def field(observed, transform, kinetic, stiffness, quartic):
    observed = np.asarray(observed, dtype=float)
    canonical = observed @ transform.T
    q, p = canonical[..., :2], canonical[..., 2:]
    grad_q = q @ stiffness.T
    grad_q[..., 0] += quartic[0]*q[..., 0]**3 + quartic[2]*q[..., 0]*q[..., 1]**2
    grad_q[..., 1] += quartic[1]*q[..., 1]**3 + quartic[2]*q[..., 1]*q[..., 0]**2
    canonical_field = np.concatenate((p @ kinetic.T, -grad_q), axis=-1)
    return canonical_field @ np.linalg.inv(transform).T


def rollout(parameters, initial, times):
    trajectory = np.empty((len(times), 4), dtype=float)
    trajectory[0] = initial
    for index in range(1, len(times)):
        dt = float(times[index] - times[index - 1])
        state = trajectory[index - 1]
        k1 = field(state[None], *parameters)[0]
        k2 = field((state + 0.5*dt*k1)[None], *parameters)[0]
        k3 = field((state + 0.5*dt*k2)[None], *parameters)[0]
        k4 = field((state + dt*k3)[None], *parameters)[0]
        trajectory[index] = state + dt*(k1 + 2*k2 + 2*k3 + k4)/6.0
    return trajectory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    truth_path = Path(__file__).resolve().parent / "instances" / args.instance / "truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    errors, metrics = [], {}
    try:
        predicted = parse(locate(args.submission, args.instance))
        values = truth["parameters"]
        actual = tuple(np.asarray(values[name], dtype=float) for name in ("canonical_from_observed", "kinetic", "stiffness", "quartic"))
        states = np.asarray(truth["hidden_observed_states"], dtype=float)
        expected_field = field(states, *actual)
        predicted_field = field(states, *predicted)
        field_mse = float(np.mean((predicted_field - expected_field) ** 2))
        initials = np.asarray(truth["rollout_initial_observed_states"], dtype=float)
        times = np.asarray(truth["rollout_times"], dtype=float)
        expected_rollouts = np.stack([rollout(actual, value, times) for value in initials])
        predicted_rollouts = np.stack([rollout(predicted, value, times) for value in initials])
        rollout_mse = float(np.mean((predicted_rollouts - expected_rollouts) ** 2))
        metrics = {"field_mse": field_mse, "rollout_mse": rollout_mse}
        if not all(np.isfinite(value) for value in metrics.values()):
            errors.append("metrics are non-finite")
        if field_mse > truth["thresholds"]["field_mse_max"]:
            errors.append("hidden transformed-field MSE exceeds threshold")
        if rollout_mse > truth["thresholds"]["rollout_mse_max"]:
            errors.append("hidden transformed rollout MSE exceeds threshold")
    except Exception as error:
        errors.append(f"{type(error).__name__}: {error}")
    passed = not errors
    thresholds = truth.get("thresholds", {})
    metric_scores = {
        "hidden_induced_field": max(
            0.0,
            1.0 - metrics.get("field_mse", float("inf"))
            / max(float(thresholds.get("field_mse_max", 0.0)), 1e-30),
        ),
        "transformed_rollout": max(
            0.0,
            1.0 - metrics.get("rollout_mse", float("inf"))
            / max(float(thresholds.get("rollout_mse_max", 0.0)), 1e-30),
        ),
        "artifact_structure": 1.0 if passed else 0.0,
    }
    score = (
        0.45 * metric_scores["hidden_induced_field"]
        + 0.45 * metric_scores["transformed_rollout"]
        + 0.1 * metric_scores["artifact_structure"]
        if passed
        else 0.0
    )
    print(json.dumps({"passed": passed, "score": score, "instance": args.instance, "metrics": metrics, "metric_scores": metric_scores, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
