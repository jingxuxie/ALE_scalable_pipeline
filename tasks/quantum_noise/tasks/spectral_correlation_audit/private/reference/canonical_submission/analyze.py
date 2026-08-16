#!/usr/bin/env python3
"""Clean-room reference analyzer for the public task contract."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


AGGREGATED_HEADER = ["length", "error_mask", "corrected_count", "probability"]
SPECTRA_HEADER = ["length", "mode_mask", "coefficient"]
DECAYS_HEADER = ["mode_mask", "amplitude", "eigenvalue", "fit_rmse"]
DISTRIBUTION_HEADER = [
    "error_mask",
    "raw_probability",
    "probability",
    "local_probability",
]
DEPENDENCE_HEADER = [
    "unit_i",
    "unit_j",
    "mutual_information",
    "conditional_mutual_information",
    "pearson_correlation",
    "co_local",
]


def fwht(values: np.ndarray) -> np.ndarray:
    out = np.asarray(values, dtype=np.float64).copy()
    width = 1
    while width < out.size:
        for start in range(0, out.size, 2 * width):
            left = out[start : start + width].copy()
            right = out[start + width : start + 2 * width].copy()
            out[start : start + width] = left + right
            out[start + width : start + 2 * width] = left - right
        width *= 2
    return out


def project_simplex(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    ordered = np.sort(values)[::-1]
    cumulative = np.cumsum(ordered) - 1.0
    positive = ordered - cumulative / np.arange(1, values.size + 1) > 0.0
    rho = int(np.flatnonzero(positive)[-1])
    theta = cumulative[rho] / float(rho + 1)
    projected = np.maximum(values - theta, 0.0)
    return projected / projected.sum()


def fit_decay(lengths: np.ndarray, observed: np.ndarray) -> tuple[float, float, float]:
    """Bounded profile least squares for y_m = A * lambda**m."""
    grid = np.linspace(0.0, 1.0, 2001, dtype=np.float64)
    powers = grid[:, None] ** lengths[None, :]
    denominators = np.sum(powers * powers, axis=1)
    safe_denominators = np.where(denominators > 0.0, denominators, 1.0)
    amplitudes = np.clip((powers @ observed) / safe_denominators, 0.0, 1.0)
    residuals = powers * amplitudes[:, None] - observed[None, :]
    losses = np.sum(residuals * residuals, axis=1)
    losses[denominators == 0.0] = np.inf
    best = int(np.argmin(losses))
    lower = grid[max(0, best - 1)]
    upper = grid[min(grid.size - 1, best + 1)]

    def profile(value: float) -> tuple[float, float]:
        basis = value**lengths
        amplitude = float(np.clip(np.dot(basis, observed) / np.dot(basis, basis), 0.0, 1.0))
        delta = amplitude * basis - observed
        return float(np.dot(delta, delta)), amplitude

    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    x1 = upper - ratio * (upper - lower)
    x2 = lower + ratio * (upper - lower)
    f1, _ = profile(x1)
    f2, _ = profile(x2)
    for _ in range(44):
        if f1 <= f2:
            upper, x2, f2 = x2, x1, f1
            x1 = upper - ratio * (upper - lower)
            f1, _ = profile(x1)
        else:
            lower, x1, f1 = x1, x2, f2
            x2 = lower + ratio * (upper - lower)
            f2, _ = profile(x2)
    eigenvalue = 0.5 * (lower + upper)
    loss, amplitude = profile(eigenvalue)
    return amplitude, eigenvalue, math.sqrt(loss / lengths.size)


def subset_index(mask: int, subset: list[int]) -> int:
    result = 0
    for position, unit in enumerate(subset):
        result |= ((mask >> unit) & 1) << position
    return result


def marginal(distribution: np.ndarray, subset: list[int]) -> np.ndarray:
    result = np.zeros(1 << len(subset), dtype=np.float64)
    for mask, probability in enumerate(distribution):
        result[subset_index(mask, subset)] += probability
    return result


def local_model(distribution: np.ndarray, cliques: list[list[int]], tree_edges: list[list[int]]) -> np.ndarray:
    clique_marginals = [marginal(distribution, clique) for clique in cliques]
    separators = []
    for left, right in tree_edges:
        common = sorted(set(cliques[left]).intersection(cliques[right]))
        separators.append((common, marginal(distribution, common)))

    result = np.zeros_like(distribution)
    for mask in range(distribution.size):
        numerator = 1.0
        denominator = 1.0
        for clique, probabilities in zip(cliques, clique_marginals):
            numerator *= probabilities[subset_index(mask, clique)]
        for separator, probabilities in separators:
            denominator *= probabilities[subset_index(mask, separator)]
        result[mask] = numerator / denominator if denominator > 0.0 else 0.0
    total = float(result.sum())
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("local-model reconstruction has no probability mass")
    return result / total


def information_metrics(distribution: np.ndarray, bit_count: int) -> list[dict[str, float | int]]:
    states = np.arange(distribution.size, dtype=np.int64)
    records: list[dict[str, float | int]] = []
    for unit_i in range(bit_count):
        bit_i = ((states >> unit_i) & 1).astype(np.int64)
        mean_i = float(np.dot(distribution, bit_i))
        for unit_j in range(unit_i + 1, bit_count):
            bit_j = ((states >> unit_j) & 1).astype(np.int64)
            mean_j = float(np.dot(distribution, bit_j))
            joint = np.bincount(2 * bit_i + bit_j, weights=distribution, minlength=4).reshape(2, 2)
            marginal_i = joint.sum(axis=1)
            marginal_j = joint.sum(axis=0)
            mutual_information = 0.0
            for value_i in range(2):
                for value_j in range(2):
                    probability = float(joint[value_i, value_j])
                    denominator = float(marginal_i[value_i] * marginal_j[value_j])
                    if probability > 0.0 and denominator > 0.0:
                        mutual_information += probability * math.log(probability / denominator)

            remaining = [unit for unit in range(bit_count) if unit not in (unit_i, unit_j)]
            z_size = 1 << len(remaining)
            p_z = np.zeros(z_size, dtype=np.float64)
            p_iz = np.zeros((2, z_size), dtype=np.float64)
            p_jz = np.zeros((2, z_size), dtype=np.float64)
            z_indices = np.empty(distribution.size, dtype=np.int64)
            for mask in range(distribution.size):
                z_indices[mask] = subset_index(mask, remaining)
                p_z[z_indices[mask]] += distribution[mask]
                p_iz[bit_i[mask], z_indices[mask]] += distribution[mask]
                p_jz[bit_j[mask], z_indices[mask]] += distribution[mask]
            conditional_information = 0.0
            for mask, probability in enumerate(distribution):
                if probability <= 0.0:
                    continue
                z_index = z_indices[mask]
                denominator = p_iz[bit_i[mask], z_index] * p_jz[bit_j[mask], z_index]
                if denominator > 0.0:
                    conditional_information += probability * math.log(
                        probability * p_z[z_index] / denominator
                    )

            covariance = float(np.dot(distribution, bit_i * bit_j) - mean_i * mean_j)
            variance_i = mean_i * (1.0 - mean_i)
            variance_j = mean_j * (1.0 - mean_j)
            pearson = covariance / math.sqrt(variance_i * variance_j) if variance_i > 0 and variance_j > 0 else 0.0
            records.append(
                {
                    "unit_i": unit_i,
                    "unit_j": unit_j,
                    "mutual_information": mutual_information,
                    "conditional_mutual_information": max(0.0, conditional_information),
                    "pearson_correlation": pearson,
                }
            )
    return records


def divergence_metrics(left: np.ndarray, right: np.ndarray) -> tuple[float, float]:
    mixture = 0.5 * (left + right)

    def relative(first: np.ndarray, second: np.ndarray) -> float:
        keep = first > 0.0
        return float(np.sum(first[keep] * np.log(first[keep] / second[keep])))

    js_divergence = 0.5 * relative(left, mixture) + 0.5 * relative(right, mixture)
    return math.sqrt(max(0.0, js_divergence)), 0.5 * float(np.sum(np.abs(left - right)))


def read_input(input_dir: Path) -> tuple[dict, list[dict[str, str]]]:
    manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    with (input_dir / manifest["count_file"]).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["length", "sequence_id", "target_mask", "observed_mask", "count"]:
            raise ValueError("raw_counts.csv header mismatch")
        rows = list(reader)
    return manifest, rows


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def analyze(input_dir: Path, output_dir: Path) -> None:
    manifest, rows = read_input(input_dir)
    bit_count = int(manifest["bit_count"])
    state_count = 1 << bit_count
    lengths = np.asarray(manifest["sequence_lengths"], dtype=np.int64)
    length_to_index = {int(length): index for index, length in enumerate(lengths)}
    corrected_counts = np.zeros((lengths.size, state_count), dtype=np.int64)
    for row in rows:
        length = int(row["length"])
        target = int(row["target_mask"])
        observed = int(row["observed_mask"])
        count = int(row["count"])
        if length not in length_to_index or not (0 <= target < state_count) or not (0 <= observed < state_count) or count <= 0:
            raise ValueError("invalid raw count row")
        error = target ^ observed
        corrected_counts[length_to_index[length], error] += count

    totals = corrected_counts.sum(axis=1)
    if np.any(totals <= 0):
        raise ValueError("each sequence length needs positive total count")
    probabilities = corrected_counts / totals[:, None]
    spectra = np.vstack([fwht(row) for row in probabilities])

    amplitudes = np.zeros(state_count, dtype=np.float64)
    eigenvalues = np.zeros(state_count, dtype=np.float64)
    fit_rmse = np.zeros(state_count, dtype=np.float64)
    fit_lengths = lengths.astype(np.float64)
    for mode in range(state_count):
        amplitudes[mode], eigenvalues[mode], fit_rmse[mode] = fit_decay(fit_lengths, spectra[:, mode])
    amplitudes[0] = 1.0
    eigenvalues[0] = 1.0
    fit_rmse[0] = float(np.sqrt(np.mean((spectra[:, 0] - 1.0) ** 2)))

    raw_distribution = fwht(eigenvalues) / state_count
    distribution = project_simplex(raw_distribution)
    local_configuration = manifest["local_model"]
    cliques = [[int(unit) for unit in clique] for clique in local_configuration["cliques"]]
    tree_edges = [[int(endpoint) for endpoint in edge] for edge in local_configuration["tree_edges"]]
    local_distribution = local_model(distribution, cliques, tree_edges)
    dependence = information_metrics(distribution, bit_count)
    for record in dependence:
        record["co_local"] = int(
            any(record["unit_i"] in clique and record["unit_j"] in clique for clique in cliques)
        )
    nonlocal_records = [record for record in dependence if record["co_local"] == 0]
    nonlocal_records.sort(
        key=lambda record: (
            -float(record["conditional_mutual_information"]),
            int(record["unit_i"]),
            int(record["unit_j"]),
        )
    )
    top_k = int(local_configuration["top_k_nonlocal"])
    js_distance, tv_distance = divergence_metrics(distribution, local_distribution)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "aggregated.csv",
        AGGREGATED_HEADER,
        [
            [int(length), mask, int(corrected_counts[index, mask]), f"{probabilities[index, mask]:.17g}"]
            for index, length in enumerate(lengths)
            for mask in range(state_count)
        ],
    )
    write_csv(
        output_dir / "spectra.csv",
        SPECTRA_HEADER,
        [
            [int(length), mode, f"{spectra[index, mode]:.17g}"]
            for index, length in enumerate(lengths)
            for mode in range(state_count)
        ],
    )
    write_csv(
        output_dir / "decays.csv",
        DECAYS_HEADER,
        [
            [mode, f"{amplitudes[mode]:.17g}", f"{eigenvalues[mode]:.17g}", f"{fit_rmse[mode]:.17g}"]
            for mode in range(state_count)
        ],
    )
    write_csv(
        output_dir / "distribution.csv",
        DISTRIBUTION_HEADER,
        [
            [
                mask,
                f"{raw_distribution[mask]:.17g}",
                f"{distribution[mask]:.17g}",
                f"{local_distribution[mask]:.17g}",
            ]
            for mask in range(state_count)
        ],
    )
    write_csv(
        output_dir / "dependence.csv",
        DEPENDENCE_HEADER,
        [
            [
                record["unit_i"],
                record["unit_j"],
                f"{record['mutual_information']:.17g}",
                f"{record['conditional_mutual_information']:.17g}",
                f"{record['pearson_correlation']:.17g}",
                record["co_local"],
            ]
            for record in dependence
        ],
    )
    summary = {
        "schema_version": "spectral-correlation-audit-result/v1",
        "experiment_id": manifest["experiment_id"],
        "bit_count": bit_count,
        "simplex_adjustment_l2": float(np.linalg.norm(distribution - raw_distribution)),
        "jensen_shannon_distance": js_distance,
        "total_variation_distance": tv_distance,
        "nonlocal_ranking": [
            {
                "rank": rank,
                "unit_i": int(record["unit_i"]),
                "unit_j": int(record["unit_j"]),
                "conditional_mutual_information": float(record["conditional_mutual_information"]),
            }
            for rank, record in enumerate(nonlocal_records[:top_k], start=1)
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    analyze(arguments.input.resolve(), arguments.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
