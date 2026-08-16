"""Trusted dense-sector oracle for the disordered-sector audit task.

This module is private benchmark infrastructure.  Participant implementations
must follow the public contract rather than importing this file.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np


INPUT_SCHEMA = "sector-audit-experiment/v1"
RESULT_SCHEMA = "sector-audit-result/v1"
STATE_FLOAT_FIELDS = (
    "eigenvalue",
    "normalized_energy",
    "gap_ratio",
    "entanglement",
    "participation_s1",
    "participation_s2",
    "subsystem_mz_mean",
    "subsystem_mz_variance",
)
AGGREGATE_METRICS = (
    "gap_ratio",
    "entanglement",
    "participation_s1",
    "participation_s2",
    "subsystem_mz_mean",
    "subsystem_mz_variance",
)
CLAIM_METRICS = (
    "gap_ratio",
    "entanglement",
    "participation_s1",
    "participation_s2",
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def load_json(path: Path) -> Any:
    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite JSON constant {token}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key {key}")
            out[key] = value
        return out

    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def load_experiment(experiment_dir: Path) -> dict[str, Any]:
    data = load_json(experiment_dir / "experiment.json")
    if not isinstance(data, dict) or data.get("schema_version") != INPUT_SCHEMA:
        raise ValueError("unsupported experiment schema")
    if not isinstance(data.get("experiment_id"), str) or not IDENTIFIER.fullmatch(data["experiment_id"]):
        raise ValueError("missing experiment_id")
    records = data.get("records")
    comparisons = data.get("comparisons")
    if not isinstance(records, list) or not (1 <= len(records) <= 24):
        raise ValueError("experiment records must be a nonempty list")
    if not isinstance(comparisons, list) or not (1 <= len(comparisons) <= 8):
        raise ValueError("experiment comparisons must be a nonempty list")
    seen_records: set[str] = set()
    query_definitions: dict[
        tuple[str, str], tuple[int, int, float, float, int, int]
    ] = {}
    conditions: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each record must be an object")
        record_id = record.get("record_id")
        condition = record.get("condition_id")
        if not isinstance(record_id, str) or not IDENTIFIER.fullmatch(record_id) or record_id in seen_records:
            raise ValueError("record IDs must be unique nonempty strings")
        if not isinstance(condition, str) or not IDENTIFIER.fullmatch(condition):
            raise ValueError("condition_id must be a nonempty string")
        seen_records.add(record_id)
        conditions.add(condition)
        length = record.get("L")
        n_up = record.get("n_up")
        exchange = record.get("exchange")
        fields = record.get("fields")
        if type(length) is not int or not (4 <= length <= 14):
            raise ValueError("L must be an integer in [4, 14]")
        if type(n_up) is not int or not (1 <= n_up < length):
            raise ValueError("n_up must be an interior sector")
        if not isinstance(exchange, (int, float)) or not math.isfinite(float(exchange)) or exchange <= 0:
            raise ValueError("exchange must be finite and positive")
        if not isinstance(fields, list) or len(fields) != length:
            raise ValueError("fields must have length L")
        if not all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in fields):
            raise ValueError("fields must be finite")
        queries = record.get("queries")
        if not isinstance(queries, list) or not (2 <= len(queries) <= 4):
            raise ValueError("every record needs between two and four queries")
        seen_queries: set[str] = set()
        for query in queries:
            if not isinstance(query, dict):
                raise ValueError("query must be an object")
            query_id = query.get("query_id")
            epsilon = query.get("epsilon")
            packet_size = query.get("packet_size")
            start = query.get("subsystem_start")
            size = query.get("subsystem_size")
            if not isinstance(query_id, str) or not IDENTIFIER.fullmatch(query_id) or query_id in seen_queries:
                raise ValueError("query IDs must be unique within a record")
            seen_queries.add(query_id)
            if not isinstance(epsilon, (int, float)) or not 0.0 < float(epsilon) < 1.0:
                raise ValueError("epsilon must lie strictly inside (0,1)")
            dimension = math.comb(length, n_up)
            if type(packet_size) is not int or not (2 <= packet_size <= min(15, dimension - 2)):
                raise ValueError("packet_size is out of range")
            if type(start) is not int or not (0 <= start < length):
                raise ValueError("subsystem_start is out of range")
            if type(size) is not int or not (1 <= size < length):
                raise ValueError("subsystem_size is out of range")
            # Every aggregate is a single physical question.  Realizations may
            # use different packet sizes, but all other model/query descriptors
            # must agree within a condition and across a requested comparison.
            definition = (
                int(length),
                int(n_up),
                float(exchange),
                float(epsilon),
                int(start),
                int(size),
            )
            key = (condition, query_id)
            previous = query_definitions.setdefault(key, definition)
            if previous != definition:
                raise ValueError(
                    "same condition/query must use the same L, sector, exchange, epsilon, and subsystem"
                )
    seen_comparisons: set[str] = set()
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            raise ValueError("comparison must be an object")
        comparison_id = comparison.get("comparison_id")
        if (
            not isinstance(comparison_id, str)
            or not IDENTIFIER.fullmatch(comparison_id)
            or comparison_id in seen_comparisons
        ):
            raise ValueError("comparison IDs must be globally unique safe identifiers")
        seen_comparisons.add(comparison_id)
        weak_condition = comparison.get("weak_condition")
        strong_condition = comparison.get("strong_condition")
        if (
            not isinstance(weak_condition, str)
            or not IDENTIFIER.fullmatch(weak_condition)
            or not isinstance(strong_condition, str)
            or not IDENTIFIER.fullmatch(strong_condition)
            or weak_condition == strong_condition
            or weak_condition not in conditions
            or strong_condition not in conditions
        ):
            raise ValueError("comparison references an unknown condition")
        query_id = comparison.get("query_id")
        if not isinstance(query_id, str) or not IDENTIFIER.fullmatch(query_id):
            raise ValueError("comparison query_id must be a safe identifier")
        for condition in (weak_condition, strong_condition):
            if (condition, query_id) not in query_definitions:
                raise ValueError("comparison query is missing from a condition")
        weak_definition = query_definitions[(weak_condition, query_id)]
        strong_definition = query_definitions[(strong_condition, query_id)]
        if weak_definition != strong_definition:
            raise ValueError(
                "compared aggregates must share L, sector, exchange, epsilon, and subsystem"
            )
    for record in records:
        _basis, matrix = build_hamiltonian(record)
        eigenvalues = np.linalg.eigvalsh(matrix)
        if not float(eigenvalues[-1] - eigenvalues[0]) > 0.0:
            raise ValueError("experiment has zero spectral width")
        gaps = np.diff(eigenvalues)
        if not np.all(gaps > 1.0e-12 * max(1.0, float(eigenvalues[-1] - eigenvalues[0]))):
            raise ValueError("experiment contains a degenerate or numerically unresolved spectrum")
        width = float(eigenvalues[-1] - eigenvalues[0])
        for query in record["queries"]:
            target = float(eigenvalues[-1]) + float(query["epsilon"]) * (
                float(eigenvalues[0]) - float(eigenvalues[-1])
            )
            distances = sorted(
                abs(float(eigenvalues[index]) - target)
                for index in range(1, eigenvalues.size - 1)
            )
            packet_size = int(query["packet_size"])
            if packet_size < len(distances):
                cutoff_margin = distances[packet_size] - distances[packet_size - 1]
                if not cutoff_margin > 1.0e-10 * max(1.0, width):
                    raise ValueError("packet cutoff is numerically ambiguous")
    return data


def sector_basis(length: int, n_up: int) -> np.ndarray:
    return np.asarray(
        [mask for mask in range(1 << length) if mask.bit_count() == n_up],
        dtype=np.int64,
    )


def build_hamiltonian(record: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    length = int(record["L"])
    n_up = int(record["n_up"])
    exchange = float(record["exchange"])
    fields = np.asarray(record["fields"], dtype=np.float64)
    basis = sector_basis(length, n_up)
    positions = {int(mask): index for index, mask in enumerate(basis.tolist())}
    hamiltonian = np.zeros((basis.size, basis.size), dtype=np.float64)
    for row, raw_mask in enumerate(basis.tolist()):
        mask = int(raw_mask)
        diagonal = 0.0
        for site in range(length):
            sz = 0.5 if (mask >> site) & 1 else -0.5
            diagonal -= fields[site] * sz
            neighbor = (site + 1) % length
            sz_neighbor = 0.5 if (mask >> neighbor) & 1 else -0.5
            diagonal += exchange * sz * sz_neighbor
            if ((mask >> site) & 1) != ((mask >> neighbor) & 1):
                flipped = mask ^ (1 << site) ^ (1 << neighbor)
                hamiltonian[row, positions[flipped]] += 0.5 * exchange
        hamiltonian[row, row] += diagonal
    return basis, hamiltonian


def normalized_energy(eigenvalue: float, minimum: float, maximum: float) -> float:
    return (float(eigenvalue) - maximum) / (minimum - maximum)


def subsystem_sites(length: int, start: int, size: int) -> tuple[list[int], list[int]]:
    selected = [int((start + offset) % length) for offset in range(size)]
    chosen = set(selected)
    complement = [site for site in range(length) if site not in chosen]
    return selected, complement


def compressed_index(mask: int, sites: list[int]) -> int:
    value = 0
    for position, site in enumerate(sites):
        value |= ((mask >> site) & 1) << position
    return value


def state_observables(
    vector: np.ndarray,
    basis: np.ndarray,
    length: int,
    subsystem_start: int,
    subsystem_size: int,
) -> dict[str, float]:
    vector = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(vector))
    if not norm > 0.0:
        raise ValueError("zero eigenvector")
    vector = vector / norm
    probabilities = np.square(vector)
    positive = probabilities > 0.0
    participation_s1 = float(-np.sum(probabilities[positive] * np.log(probabilities[positive])))
    participation_s2 = float(-math.log(float(np.sum(np.square(probabilities)))))

    sites_a, sites_b = subsystem_sites(length, subsystem_start, subsystem_size)
    coefficients = np.zeros((1 << len(sites_a), 1 << len(sites_b)), dtype=np.float64)
    magnetizations = np.empty(basis.size, dtype=np.float64)
    for index, raw_mask in enumerate(basis.tolist()):
        mask = int(raw_mask)
        row = compressed_index(mask, sites_a)
        column = compressed_index(mask, sites_b)
        coefficients[row, column] = vector[index]
        up_a = sum((mask >> site) & 1 for site in sites_a)
        magnetizations[index] = float(up_a) - 0.5 * len(sites_a)
    singular_values = np.linalg.svd(coefficients, compute_uv=False)
    schmidt = np.square(singular_values)
    schmidt /= float(np.sum(schmidt))
    keep = schmidt > 1.0e-15
    entanglement = float(-np.sum(schmidt[keep] * np.log(schmidt[keep])))
    mz_mean = float(np.dot(probabilities, magnetizations))
    mz_second = float(np.dot(probabilities, np.square(magnetizations)))
    mz_variance = max(0.0, mz_second - mz_mean * mz_mean)
    return {
        "entanglement": entanglement,
        "participation_s1": participation_s1,
        "participation_s2": participation_s2,
        "subsystem_mz_mean": mz_mean,
        "subsystem_mz_variance": mz_variance,
    }


def solve_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    basis, hamiltonian = build_hamiltonian(record)
    eigenvalues, eigenvectors = np.linalg.eigh(hamiltonian)
    minimum = float(eigenvalues[0])
    maximum = float(eigenvalues[-1])
    rows: list[dict[str, Any]] = []
    for query in sorted(record["queries"], key=lambda item: item["query_id"]):
        epsilon = float(query["epsilon"])
        target = maximum + epsilon * (minimum - maximum)
        candidates = list(range(1, eigenvalues.size - 1))
        candidates.sort(key=lambda index: (abs(float(eigenvalues[index]) - target), float(eigenvalues[index]), index))
        selected = sorted(candidates[: int(query["packet_size"])])
        for state_rank, eigen_index in enumerate(selected):
            lower_gap = float(eigenvalues[eigen_index] - eigenvalues[eigen_index - 1])
            upper_gap = float(eigenvalues[eigen_index + 1] - eigenvalues[eigen_index])
            gap_ratio = min(lower_gap, upper_gap) / max(lower_gap, upper_gap)
            observables = state_observables(
                eigenvectors[:, eigen_index],
                basis,
                int(record["L"]),
                int(query["subsystem_start"]),
                int(query["subsystem_size"]),
            )
            row: dict[str, Any] = {
                "record_id": record["record_id"],
                "condition_id": record["condition_id"],
                "query_id": query["query_id"],
                "state_rank": state_rank,
                "eigen_index": int(eigen_index),
                "eigenvalue": float(eigenvalues[eigen_index]),
                "normalized_energy": normalized_energy(
                    float(eigenvalues[eigen_index]), minimum, maximum
                ),
                "gap_ratio": gap_ratio,
            }
            row.update(observables)
            rows.append(row)
    return rows


def sem(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(np.std(np.asarray(values, dtype=np.float64), ddof=1) / math.sqrt(len(values)))


def aggregate_rows(experiment: dict[str, Any], state_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records_by_id = {record["record_id"]: record for record in experiment["records"]}
    grouped: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
    for row in state_rows:
        key = (row["condition_id"], row["query_id"])
        grouped.setdefault(key, {}).setdefault(row["record_id"], []).append(row)
    aggregates: list[dict[str, Any]] = []
    for (condition_id, query_id), per_record in sorted(grouped.items()):
        first_record_id = sorted(per_record)[0]
        query = next(
            item
            for item in records_by_id[first_record_id]["queries"]
            if item["query_id"] == query_id
        )
        aggregate: dict[str, Any] = {
            "aggregate_id": f"{condition_id}::{query_id}",
            "condition_id": condition_id,
            "query_id": query_id,
            "epsilon": float(query["epsilon"]),
            "subsystem_start": int(query["subsystem_start"]),
            "subsystem_size": int(query["subsystem_size"]),
            "realization_count": len(per_record),
            "state_count": sum(len(rows) for rows in per_record.values()),
        }
        for metric in AGGREGATE_METRICS:
            realization_means = [
                float(np.mean([float(row[metric]) for row in per_record[record_id]]))
                for record_id in sorted(per_record)
            ]
            aggregate[f"mean_{metric}"] = float(np.mean(realization_means))
            aggregate[f"sem_{metric}"] = sem(realization_means)
        aggregates.append(aggregate)
    return aggregates


def conclusion_rows(experiment: dict[str, Any], aggregates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["aggregate_id"]: row for row in aggregates}
    conclusions: list[dict[str, Any]] = []
    for comparison in sorted(experiment["comparisons"], key=lambda item: item["comparison_id"]):
        query_id = comparison["query_id"]
        weak_id = f"{comparison['weak_condition']}::{query_id}"
        strong_id = f"{comparison['strong_condition']}::{query_id}"
        weak = by_id[weak_id]
        strong = by_id[strong_id]
        for metric in CLAIM_METRICS:
            effect = float(weak[f"mean_{metric}"] - strong[f"mean_{metric}"])
            conclusions.append(
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
    return conclusions


def solve_experiment(experiment: dict[str, Any]) -> dict[str, Any]:
    state_rows: list[dict[str, Any]] = []
    for record in sorted(experiment["records"], key=lambda item: item["record_id"]):
        state_rows.extend(solve_record(record))
    state_rows.sort(key=lambda row: (row["record_id"], row["query_id"], row["state_rank"]))
    aggregates = aggregate_rows(experiment, state_rows)
    conclusions = conclusion_rows(experiment, aggregates)
    return {
        "schema_version": RESULT_SCHEMA,
        "experiment_id": experiment["experiment_id"],
        "state_rows": state_rows,
        "aggregate_rows": aggregates,
        "conclusions": conclusions,
    }


def solve_directory(experiment_dir: Path, output_path: Path) -> dict[str, Any]:
    experiment = load_experiment(experiment_dir)
    result = solve_experiment(experiment)
    dump_json(output_path, result)
    return result
