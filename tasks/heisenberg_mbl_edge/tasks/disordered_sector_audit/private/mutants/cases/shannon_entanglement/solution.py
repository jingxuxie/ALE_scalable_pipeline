#!/usr/bin/env python3
"""Clean-room public-contract implementation for the sector audit."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


MUTATION = "shannon_entanglement"
METRICS = (
    "gap_ratio",
    "entanglement",
    "participation_s1",
    "participation_s2",
    "subsystem_mz_mean",
    "subsystem_mz_variance",
)
CLAIM_METRICS = ("gap_ratio", "entanglement", "participation_s1", "participation_s2")


def basis_states(length: int, n_up: int) -> list[int]:
    return [mask for mask in range(1 << length) if mask.bit_count() == n_up]


def diagonalize(record: dict) -> tuple[list[int], np.ndarray, np.ndarray]:
    length = int(record["L"])
    coupling = 1.0 if MUTATION == "unit_exchange" else float(record["exchange"])
    fields = [float(value) for value in record["fields"]]
    basis = basis_states(length, int(record["n_up"]))
    lookup = {mask: index for index, mask in enumerate(basis)}
    matrix = np.zeros((len(basis), len(basis)), dtype=np.float64)
    bonds = range(length - 1) if MUTATION == "open_boundary" else range(length)
    for row, mask in enumerate(basis):
        diagonal = 0.0
        for site in range(length):
            spin = 0.5 if (mask >> site) & 1 else -0.5
            if MUTATION == "pauli_scale":
                spin *= 2.0
            diagonal -= fields[site] * spin
        for site in bonds:
            neighbor = (site + 1) % length
            left = 0.5 if (mask >> site) & 1 else -0.5
            right = 0.5 if (mask >> neighbor) & 1 else -0.5
            flip_weight = 0.5 * coupling
            if MUTATION == "pauli_scale":
                left *= 2.0
                right *= 2.0
                flip_weight = 2.0 * coupling
            diagonal += coupling * left * right
            if ((mask >> site) & 1) != ((mask >> neighbor) & 1):
                flipped = mask ^ (1 << site) ^ (1 << neighbor)
                matrix[row, lookup[flipped]] += flip_weight
        matrix[row, row] += diagonal
    eigenvalues, eigenvectors = np.linalg.eigh(matrix)
    return basis, eigenvalues, eigenvectors


def site_lists(length: int, start: int, size: int) -> tuple[list[int], list[int]]:
    selected = [(start + offset) % length for offset in range(size)]
    selected_set = set(selected)
    complement = [site for site in range(length) if site not in selected_set]
    return selected, complement


def compressed(mask: int, sites: list[int]) -> int:
    result = 0
    for output_bit, site in enumerate(sites):
        result |= ((mask >> site) & 1) << output_bit
    return result


def observables(vector: np.ndarray, basis: list[int], length: int, start: int, size: int) -> dict:
    vector = np.asarray(vector, dtype=np.float64)
    vector /= np.linalg.norm(vector)
    probabilities = np.square(vector)
    keep = probabilities > 0.0
    s1 = float(-np.sum(probabilities[keep] * np.log(probabilities[keep])))
    ipr = float(np.sum(np.square(probabilities)))
    s2 = ipr if MUTATION == "s2_ipr" else float(-math.log(ipr))
    sites_a, sites_b = site_lists(length, start, size)
    coefficient = np.zeros((1 << len(sites_a), 1 << len(sites_b)), dtype=np.float64)
    magnetization = np.empty(len(basis), dtype=np.float64)
    for index, mask in enumerate(basis):
        coefficient[compressed(mask, sites_a), compressed(mask, sites_b)] = vector[index]
        magnetization[index] = sum((mask >> site) & 1 for site in sites_a) - 0.5 * len(sites_a)
    singular = np.linalg.svd(coefficient, compute_uv=False)
    schmidt = np.square(singular)
    schmidt /= np.sum(schmidt)
    positive = schmidt > 1.0e-15
    entanglement = float(-np.sum(schmidt[positive] * np.log(schmidt[positive])))
    if MUTATION == "shannon_entanglement":
        entanglement = s1
    elif MUTATION == "log2_entanglement":
        entanglement /= math.log(2.0)
    mz_mean = float(np.dot(probabilities, magnetization))
    mz_second = float(np.dot(probabilities, np.square(magnetization)))
    mz_variance = max(0.0, mz_second - mz_mean * mz_mean)
    if MUTATION == "mz_second_moment":
        mz_variance = mz_second
    return {
        "entanglement": entanglement,
        "participation_s1": s1,
        "participation_s2": s2,
        "subsystem_mz_mean": mz_mean,
        "subsystem_mz_variance": mz_variance,
    }


def record_rows(record: dict) -> list[dict]:
    basis, eigenvalues, eigenvectors = diagonalize(record)
    minimum = float(eigenvalues[0])
    maximum = float(eigenvalues[-1])
    rows: list[dict] = []
    for query in sorted(record["queries"], key=lambda item: item["query_id"]):
        epsilon = float(query["epsilon"])
        if MUTATION == "wrong_energy_normalization":
            target = minimum + epsilon * (maximum - minimum)
        else:
            target = maximum + epsilon * (minimum - maximum)
        candidates = list(range(1, len(eigenvalues) - 1))
        if MUTATION == "one_sided_packet":
            above = [index for index in candidates if float(eigenvalues[index]) >= target]
            below = [index for index in candidates if float(eigenvalues[index]) < target]
            above.sort(key=lambda index: (float(eigenvalues[index]) - target, index))
            below.sort(key=lambda index: (target - float(eigenvalues[index]), index))
            selected = sorted((above + below)[: int(query["packet_size"])])
        else:
            candidates.sort(
                key=lambda index: (
                    abs(float(eigenvalues[index]) - target),
                    float(eigenvalues[index]),
                    index,
                )
            )
            selected = sorted(candidates[: int(query["packet_size"])])
        for rank, index in enumerate(selected):
            lower = float(eigenvalues[index] - eigenvalues[index - 1])
            upper = float(eigenvalues[index + 1] - eigenvalues[index])
            row = {
                "record_id": record["record_id"],
                "condition_id": record["condition_id"],
                "query_id": query["query_id"],
                "state_rank": rank,
                "eigen_index": int(index),
                "eigenvalue": float(eigenvalues[index]),
                "normalized_energy": float(
                    (eigenvalues[index] - maximum) / (minimum - maximum)
                ),
                "gap_ratio": min(lower, upper) / max(lower, upper),
            }
            if MUTATION == "wrong_energy_normalization":
                row["normalized_energy"] = float(
                    (eigenvalues[index] - minimum) / (maximum - minimum)
                )
            row.update(
                observables(
                    eigenvectors[:, index],
                    basis,
                    int(record["L"]),
                    int(query["subsystem_start"]),
                    int(query["subsystem_size"]),
                )
            )
            rows.append(row)
    return rows


def standard_error(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(np.std(np.asarray(values, dtype=np.float64), ddof=1) / math.sqrt(len(values)))


def aggregates(experiment: dict, rows: list[dict]) -> list[dict]:
    record_map = {record["record_id"]: record for record in experiment["records"]}
    weak_conditions = {
        comparison["weak_condition"] for comparison in experiment["comparisons"]
    }
    groups: dict[tuple[str, str], dict[str, list[dict]]] = {}
    for row in rows:
        groups.setdefault((row["condition_id"], row["query_id"]), {}).setdefault(
            row["record_id"], []
        ).append(row)
    output: list[dict] = []
    for (condition, query_id), per_record in sorted(groups.items()):
        first_record = record_map[sorted(per_record)[0]]
        query = next(item for item in first_record["queries"] if item["query_id"] == query_id)
        aggregate = {
            "aggregate_id": f"{condition}::{query_id}",
            "condition_id": condition,
            "query_id": query_id,
            "epsilon": float(query["epsilon"]),
            "subsystem_start": int(query["subsystem_start"]),
            "subsystem_size": int(query["subsystem_size"]),
            "realization_count": len(per_record),
            "state_count": sum(len(items) for items in per_record.values()),
        }
        for metric in METRICS:
            realization_means = [
                float(np.mean([float(row[metric]) for row in per_record[record_id]]))
                for record_id in sorted(per_record)
            ]
            if MUTATION == "naive_aggregation":
                flat = [float(row[metric]) for items in per_record.values() for row in items]
                aggregate[f"mean_{metric}"] = float(np.mean(flat))
                aggregate[f"sem_{metric}"] = standard_error(flat)
            else:
                aggregate[f"mean_{metric}"] = float(np.mean(realization_means))
                if MUTATION == "sem_over_states":
                    flat = [float(row[metric]) for items in per_record.values() for row in items]
                    aggregate[f"sem_{metric}"] = standard_error(flat)
                else:
                    aggregate[f"sem_{metric}"] = standard_error(realization_means)
            if MUTATION == "stale_evidence" and metric == "gap_ratio":
                aggregate[f"mean_{metric}"] += (
                    0.125 if condition in weak_conditions else -0.125
                )
        output.append(aggregate)
    return output


def conclusions(experiment: dict, aggregate_rows: list[dict]) -> list[dict]:
    by_id = {row["aggregate_id"]: row for row in aggregate_rows}
    output: list[dict] = []
    for comparison in sorted(experiment["comparisons"], key=lambda item: item["comparison_id"]):
        weak_id = f"{comparison['weak_condition']}::{comparison['query_id']}"
        strong_id = f"{comparison['strong_condition']}::{comparison['query_id']}"
        for metric in CLAIM_METRICS:
            effect = float(by_id[weak_id][f"mean_{metric}"] - by_id[strong_id][f"mean_{metric}"])
            output.append(
                {
                    "claim_id": f"{comparison['comparison_id']}::{metric}",
                    "metric": metric,
                    "direction": "weak_greater_than_strong",
                    "positive_effect": bool(effect > 0.0),
                    "effect": effect,
                    "weak_aggregate_id": weak_id,
                    "strong_aggregate_id": strong_id,
                }
            )
    return output


def solve(experiment: dict) -> dict:
    rows: list[dict] = []
    for record in sorted(experiment["records"], key=lambda item: item["record_id"]):
        rows.extend(record_rows(record))
    rows.sort(key=lambda row: (row["record_id"], row["query_id"], row["state_rank"]))
    aggregate_rows = aggregates(experiment, rows)
    result = {
        "schema_version": "sector-audit-result/v1",
        "experiment_id": experiment["experiment_id"],
        "state_rows": rows,
        "aggregate_rows": aggregate_rows,
        "conclusions": conclusions(experiment, aggregate_rows),
    }
    if MUTATION == "wrong_state_condition":
        result["state_rows"][0]["condition_id"] = "tampered"
    elif MUTATION == "wrong_aggregate_epsilon":
        result["aggregate_rows"][0]["epsilon"] += 0.01
    elif MUTATION == "inconsistent_conclusion":
        result["conclusions"][0]["effect"] += 0.01
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    experiment = json.loads((args.experiment / "experiment.json").read_text(encoding="utf-8"))
    result = solve(experiment)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
