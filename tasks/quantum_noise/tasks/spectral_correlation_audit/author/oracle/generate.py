#!/usr/bin/env python3
"""Trusted deterministic generator for public and hidden analyzer instances."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path

import numpy as np


TASK_ROOT = Path(__file__).resolve().parents[2]

CASES = [
    {
        "name": "public_cedar",
        "experiment_id": "cedar-array",
        "seed": 712031,
        "bit_count": 7,
        "lengths": [0, 1, 2, 3, 5, 8, 12],
        "sequence_count": 40,
        "shots": 2300,
        "nonlocal_pairs": [[0, 6, 1.85], [1, 5, 1.55], [0, 4, 1.20]],
        "public": True,
    },
    {
        "name": "case_amber",
        "experiment_id": "amber-array",
        "seed": 909173,
        "bit_count": 6,
        "lengths": [0, 1, 2, 4, 7, 11, 15],
        "sequence_count": 38,
        "shots": 2500,
        "nonlocal_pairs": [[0, 5, 1.75], [1, 4, 1.45], [0, 3, 1.10]],
        "topology": "branched",
        "public": False,
    },
    {
        "name": "case_indigo",
        "experiment_id": "indigo-array",
        "seed": 439889,
        "bit_count": 8,
        "lengths": [1, 2, 3, 4, 6, 9, 13],
        "sequence_count": 42,
        "shots": 2400,
        "nonlocal_pairs": [[0, 7, 1.95], [2, 6, 1.60], [1, 5, 1.35], [0, 4, 1.05]],
        "public": False,
    },
    {
        "name": "case_sable",
        "experiment_id": "sable-array",
        "seed": 182071,
        "bit_count": 7,
        "lengths": [1, 2, 3, 5, 7, 10, 14],
        "sequence_count": 36,
        "shots": 2700,
        "nonlocal_pairs": [[0, 6, 2.05], [1, 5, 1.35], [2, 6, 1.05]],
        "public": False,
    },
    {
        "name": "case_verdant",
        "experiment_id": "verdant-array",
        "seed": 670487,
        "bit_count": 8,
        "lengths": [0, 1, 2, 5, 8, 12, 16],
        "sequence_count": 40,
        "shots": 2600,
        "nonlocal_pairs": [[0, 7, 2.00], [1, 6, 1.70], [2, 5, 1.40], [0, 5, 1.15]],
        "public": False,
    },
]


def character_matrix(bit_count: int) -> np.ndarray:
    size = 1 << bit_count
    matrix = np.empty((size, size), dtype=np.float64)
    for mode in range(size):
        for mask in range(size):
            matrix[mode, mask] = -1.0 if (mode & mask).bit_count() % 2 else 1.0
    return matrix


def thinning_matrix(bit_count: int) -> np.ndarray:
    """Map Pauli-support masks to observed masks with 2/3 local visibility."""
    size = 1 << bit_count
    matrix = np.zeros((size, size), dtype=np.float64)
    for support_mask in range(size):
        observed_mask = support_mask
        while True:
            visible = observed_mask.bit_count()
            hidden = support_mask.bit_count() - visible
            matrix[observed_mask, support_mask] = (2.0 / 3.0) ** visible * (1.0 / 3.0) ** hidden
            if observed_mask == 0:
                break
            observed_mask = (observed_mask - 1) & support_mask
    return matrix


def profile_decay(lengths: np.ndarray, observed: np.ndarray) -> tuple[float, float]:
    grid = np.linspace(0.0, 1.0, 2001, dtype=np.float64)

    def loss(value: float) -> float:
        basis = value**lengths
        denominator = float(np.dot(basis, basis))
        if denominator == 0.0:
            return math.inf
        amplitude = float(np.clip(np.dot(basis, observed) / denominator, 0.0, 1.0))
        residual = amplitude * basis - observed
        return float(np.dot(residual, residual))

    losses = np.asarray([loss(float(value)) for value in grid])
    best = int(np.argmin(losses))
    lower = float(grid[max(0, best - 1)])
    upper = float(grid[min(grid.size - 1, best + 1)])
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    x1 = upper - ratio * (upper - lower)
    x2 = lower + ratio * (upper - lower)
    f1 = loss(x1)
    f2 = loss(x2)
    for _ in range(50):
        if f1 <= f2:
            upper, x2, f2 = x2, x1, f1
            x1 = upper - ratio * (upper - lower)
            f1 = loss(x1)
        else:
            lower, x1, f1 = x1, x2, f2
            x2 = lower + ratio * (upper - lower)
            f2 = loss(x2)
    eigenvalue = 0.5 * (lower + upper)
    minimum = loss(eigenvalue)
    outside = [loss(max(0.0, eigenvalue - 1e-4)), loss(min(1.0, eigenvalue + 1e-4))]
    outside.extend(
        float(grid_loss)
        for grid_value, grid_loss in zip(grid, losses)
        if abs(float(grid_value) - eigenvalue) >= 1e-4
    )
    return eigenvalue, min(outside) - minimum


def project_simplex(values: np.ndarray) -> np.ndarray:
    ordered = np.sort(values)[::-1]
    cumulative = np.cumsum(ordered) - 1.0
    active = ordered - cumulative / np.arange(1, values.size + 1) > 0.0
    rho = int(np.flatnonzero(active)[-1])
    threshold = cumulative[rho] / float(rho + 1)
    projected = np.maximum(values - threshold, 0.0)
    return projected / projected.sum()


def marginal(distribution: np.ndarray, units: list[int]) -> np.ndarray:
    result = np.zeros(1 << len(units), dtype=np.float64)
    for mask, probability in enumerate(distribution):
        index = sum(((mask >> unit) & 1) << position for position, unit in enumerate(units))
        result[index] += probability
    return result


def assert_sampled_contract(
    config: dict,
    pooled: np.ndarray,
    transform: np.ndarray,
    cliques: list[list[int]],
    tree_edges: list[list[int]],
) -> None:
    lengths = np.asarray(config["lengths"], dtype=np.float64)
    probabilities = pooled / pooled.sum(axis=1, keepdims=True)
    spectra = probabilities @ transform.T
    eigenvalues = np.ones(transform.shape[0], dtype=np.float64)
    for mode in range(1, transform.shape[0]):
        eigenvalues[mode], gap = profile_decay(lengths, spectra[:, mode])
        if gap < 1e-10:
            raise AssertionError(f"sampled decay objective lacks promised separation for mode {mode}: {gap}")
    reconstructed = project_simplex((transform @ eigenvalues) / transform.shape[0])
    for left, right in tree_edges:
        separator = sorted(set(cliques[left]).intersection(cliques[right]))
        if float(marginal(reconstructed, separator).min()) < 1e-3:
            raise AssertionError("canonical reconstruction violates separator-marginal floor")


def construct_distribution(config: dict, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[list[int]], list[list[int]]]:
    bit_count = int(config["bit_count"])
    state_count = 1 << bit_count
    bits = ((np.arange(state_count)[:, None] >> np.arange(bit_count)[None, :]) & 1).astype(np.float64)
    biases = rng.uniform(-3.15, -2.55, size=bit_count)
    local_couplings = rng.uniform(-0.25, 0.60, size=bit_count - 1)
    log_weights = bits @ biases
    for unit, coupling in enumerate(local_couplings):
        log_weights += coupling * bits[:, unit] * bits[:, unit + 1]
    for unit_i, unit_j, coupling in config["nonlocal_pairs"]:
        log_weights += float(coupling) * bits[:, int(unit_i)] * bits[:, int(unit_j)]
    log_weights -= float(log_weights.max())
    pauli_support_distribution = np.exp(log_weights)
    pauli_support_distribution /= pauli_support_distribution.sum()
    distribution = thinning_matrix(bit_count) @ pauli_support_distribution
    distribution /= distribution.sum()

    spam_rates = rng.uniform(0.010, 0.035, size=bit_count)
    spam = np.ones(state_count, dtype=np.float64)
    for mask in range(state_count):
        for unit in range(bit_count):
            spam[mask] *= spam_rates[unit] if (mask >> unit) & 1 else 1.0 - spam_rates[unit]
    spam /= spam.sum()

    if config.get("topology", "chain") == "branched":
        if bit_count != 6:
            raise AssertionError("the disclosed branched authoring topology expects six bits")
        cliques = [[0, 1, 2], [1, 2, 3], [2, 3, 4], [2, 3, 5]]
        tree_edges = [[0, 1], [1, 2], [1, 3]]
    else:
        cliques = [list(range(start, start + 3)) for start in range(bit_count - 2)]
        tree_edges = [[index, index + 1] for index in range(len(cliques) - 1)]
    transform = character_matrix(bit_count)
    eigenvalues = transform @ distribution
    amplitudes = transform @ spam
    if float(eigenvalues.min()) <= 0.12 or float(eigenvalues.max()) > 1.0 + 1e-12:
        raise AssertionError("generator produced an ill-conditioned spectral case")
    if float(amplitudes.min()) <= 0.45:
        raise AssertionError("generator produced excessive nuisance decay")
    recovered_support = np.linalg.solve(thinning_matrix(bit_count), distribution)
    if float(recovered_support.min()) < -1e-12 or float(np.max(np.abs(recovered_support - pauli_support_distribution))) > 2e-12:
        raise AssertionError("generator produced a nonphysical observed error distribution")
    return distribution, pauli_support_distribution, spam, eigenvalues, cliques, tree_edges


def manifest_for(config: dict, cliques: list[list[int]], tree_edges: list[list[int]]) -> dict:
    bit_count = int(config["bit_count"])
    return {
        "schema_version": "spectral-correlation-audit-input/v1",
        "experiment_id": config["experiment_id"],
        "bit_count": bit_count,
        "sequence_lengths": config["lengths"],
        "count_file": "raw_counts.csv",
        "mask_convention": "unsigned decimal; unit 0 is the least-significant bit",
        "count_columns": ["length", "sequence_id", "target_mask", "observed_mask", "count"],
        "local_model": {
            "type": "junction_tree_clique_marginals",
            "cliques": cliques,
            "tree_edges": tree_edges,
            "top_k_nonlocal": len(config["nonlocal_pairs"]),
        },
    }


def write_case(config: dict, destination: Path, truth_destination: Path | None) -> None:
    rng = np.random.default_rng(int(config["seed"]))
    distribution, pauli_support_distribution, spam, eigenvalues, cliques, tree_edges = construct_distribution(config, rng)
    manifest = manifest_for(config, cliques, tree_edges)
    transform = character_matrix(int(config["bit_count"]))
    state_count = distribution.size
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.json"
    count_path = destination / "raw_counts.csv"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    pooled = np.zeros((len(config["lengths"]), state_count), dtype=np.int64)
    with count_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(manifest["count_columns"])
        for length_index, length in enumerate(config["lengths"]):
            spectrum = (transform @ spam) * eigenvalues ** int(length)
            observed_distribution = (transform @ spectrum) / state_count
            observed_distribution = np.maximum(observed_distribution, 0.0)
            observed_distribution /= observed_distribution.sum()
            for sequence in range(int(config["sequence_count"])):
                target = int(rng.integers(0, state_count))
                shots = int(config["shots"] + rng.integers(-150, 151))
                counts = rng.multinomial(shots, observed_distribution)
                pooled[length_index] += counts
                for error_mask, count in enumerate(counts):
                    if count:
                        writer.writerow(
                            [int(length), f"s{sequence:03d}", target, target ^ error_mask, int(count)]
                        )
    if manifest_path.stat().st_size > 16_384 or count_path.stat().st_size > 12_000_000:
        raise AssertionError("generated input exceeds the public byte envelope")
    assert_sampled_contract(config, pooled, transform, cliques, tree_edges)
    if truth_destination is not None:
        truth_destination.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            truth_destination / "truth.npz",
            schema_version=np.asarray("spectral-correlation-audit-truth/v1"),
            distribution=distribution.astype(np.float64),
            pauli_support_distribution=pauli_support_distribution.astype(np.float64),
            spam_distribution=spam.astype(np.float64),
            eigenvalues=eigenvalues.astype(np.float64),
            amplitudes=(transform @ spam).astype(np.float64),
            bit_count=np.asarray(int(config["bit_count"]), dtype=np.int64),
        )
        truth_summary = {
            "schema_version": "spectral-correlation-audit-truth-summary/v1",
            "experiment_id": config["experiment_id"],
            "clique_topology": config.get("topology", "chain"),
            "injected_nonlocal_pairs": [pair[:2] for pair in config["nonlocal_pairs"]],
            "minimum_eigenvalue": float(eigenvalues.min()),
            "maximum_eigenvalue": float(eigenvalues.max()),
            "minimum_probability": float(distribution.min()),
            "minimum_pauli_support_probability": float(pauli_support_distribution.min()),
            "normalization_error": abs(float(distribution.sum()) - 1.0),
        }
        (truth_destination / "truth_summary.json").write_text(
            json.dumps(truth_summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def generate(output_root: Path) -> None:
    public_input = output_root / "participant" / "input"
    hidden_root = output_root / "private" / "hidden_inputs"
    reference_root = output_root / "private" / "reference"
    for config in CASES:
        if config["public"]:
            write_case(config, public_input, None)
        else:
            write_case(config, hidden_root / config["name"], reference_root / config["name"])
    canonical_submission = reference_root / "canonical_submission"
    canonical_submission.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TASK_ROOT / "author" / "reference_solver" / "analyze.py", canonical_submission / "analyze.py")
    suite = {
        "schema_version": "spectral-correlation-audit-hidden-suite/v1",
        "cases": [
            {
                "case_id": config["name"],
                "input": f"../hidden_inputs/{config['name']}",
                "truth": f"{config['name']}/truth.npz",
                "class": "distribution_shift" if config["bit_count"] == 8 else "ordinary",
                "topology": config.get("topology", "chain"),
            }
            for config in CASES
            if not config["public"]
        ],
    }
    reference_root.mkdir(parents=True, exist_ok=True)
    (reference_root / "suite.json").write_text(
        json.dumps(suite, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=TASK_ROOT)
    arguments = parser.parse_args()
    generate(arguments.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
