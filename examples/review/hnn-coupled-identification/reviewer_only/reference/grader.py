"""Independently evaluate a safe coupled-periodic Hamiltonian artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np


def locate(path: Path, instance: str) -> Path:
    candidates = [path, path / "model.json", path / "output" / instance / "model.json", path / instance / "model.json"]
    result = next((item for item in candidates if item.is_file()), None)
    if result is None:
        raise FileNotFoundError("model.json is missing")
    if result.stat().st_size > 1_000_000:
        raise ValueError("model JSON exceeds 1 MB")
    return result


def parse(path: Path):
    model = json.loads(path.read_text(encoding="utf-8"))
    if set(model) != {"format", "dof", "inverse_mass", "onsite", "couplings"}:
        raise ValueError("model keys do not match the safe contract")
    if model["format"] != "coupled-periodic-hamiltonian-v1" or model["dof"] != 3:
        raise ValueError("wrong model format or degree count")
    inverse_mass = np.asarray(model["inverse_mass"], dtype=float)
    onsite = np.asarray(model["onsite"], dtype=float)
    couplings = np.asarray(model["couplings"], dtype=float)
    if inverse_mass.shape != (3, 3) or couplings.shape != (3, 3) or onsite.shape != (3,):
        raise ValueError("parameter shapes are invalid")
    if not all(np.all(np.isfinite(value)) for value in (inverse_mass, onsite, couplings)):
        raise ValueError("parameters must be finite")
    if not np.allclose(inverse_mass, inverse_mass.T, atol=1e-12) or np.min(np.linalg.eigvalsh(inverse_mass)) <= 0:
        raise ValueError("inverse_mass must be symmetric positive definite")
    if not np.allclose(couplings, couplings.T, atol=1e-12) or not np.allclose(np.diag(couplings), 0.0, atol=1e-12):
        raise ValueError("couplings must be symmetric with zero diagonal")
    if np.max(np.abs(inverse_mass)) > 10 or np.max(np.abs(onsite)) > 10 or np.max(np.abs(couplings)) > 10:
        raise ValueError("parameters exceed safety bounds")
    return inverse_mass, onsite, couplings


def field(states, inverse_mass, onsite, couplings):
    states = np.asarray(states, dtype=float)
    q, p = states[..., :3], states[..., 3:]
    dq = p @ inverse_mass.T
    grad_q = onsite * np.sin(q)
    for left in range(3):
        for right in range(left + 1, 3):
            value = couplings[left, right] * np.sin(q[..., left] - q[..., right])
            grad_q[..., left] += value
            grad_q[..., right] -= value
    return np.concatenate((dq, -grad_q), axis=-1)


def rollout(parameters, initial, times):
    trajectory = np.empty((len(times), 6), dtype=float)
    trajectory[0] = initial
    for index in range(1, len(times)):
        dt = float(times[index] - times[index - 1])
        state = trajectory[index - 1]
        k1 = field(state[None], *parameters)[0]
        k2 = field((state + 0.5 * dt * k1)[None], *parameters)[0]
        k3 = field((state + 0.5 * dt * k2)[None], *parameters)[0]
        k4 = field((state + dt * k3)[None], *parameters)[0]
        trajectory[index] = state + dt * (k1 + 2*k2 + 2*k3 + k4) / 6.0
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
        predicted_parameters = parse(locate(args.submission, args.instance))
        values = truth["parameters"]
        true_parameters = tuple(np.asarray(values[name], dtype=float) for name in ("inverse_mass", "onsite", "couplings"))
        states = np.asarray(truth["hidden_states"], dtype=float)
        expected = field(states, *true_parameters)
        actual = field(states, *predicted_parameters)
        field_mse = float(np.mean((actual - expected) ** 2))
        times = np.asarray(truth["rollout_times"], dtype=float)
        initials = np.asarray(truth["rollout_initial_states"], dtype=float)
        true_rollouts = np.stack([rollout(true_parameters, value, times) for value in initials])
        predicted_rollouts = np.stack([rollout(predicted_parameters, value, times) for value in initials])
        rollout_mse = float(np.mean((predicted_rollouts - true_rollouts) ** 2))
        metrics = {"field_mse": field_mse, "rollout_mse": rollout_mse}
        if not all(np.isfinite(value) for value in metrics.values()):
            errors.append("metrics are non-finite")
        if field_mse > truth["thresholds"]["field_mse_max"]:
            errors.append("hidden nonlinear field MSE exceeds threshold")
        if rollout_mse > truth["thresholds"]["rollout_mse_max"]:
            errors.append("hidden rollout MSE exceeds threshold")
    except Exception as error:
        errors.append(f"{type(error).__name__}: {error}")
    passed = not errors
    thresholds = truth.get("thresholds", {})
    metric_scores = {
        "hidden_field": max(
            0.0,
            1.0 - metrics.get("field_mse", float("inf"))
            / max(float(thresholds.get("field_mse_max", 0.0)), 1e-30),
        ),
        "nonlinear_rollout": max(
            0.0,
            1.0 - metrics.get("rollout_mse", float("inf"))
            / max(float(thresholds.get("rollout_mse_max", 0.0)), 1e-30),
        ),
        "artifact_safety": 1.0 if passed else 0.0,
    }
    score = (
        0.45 * metric_scores["hidden_field"]
        + 0.45 * metric_scores["nonlinear_rollout"]
        + 0.1 * metric_scores["artifact_safety"]
        if passed
        else 0.0
    )
    print(json.dumps({"passed": passed, "score": score, "instance": args.instance, "metrics": metrics, "metric_scores": metric_scores, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
