#!/usr/bin/env python3
"""Independent vectorized/eigen-density implementation of the public task."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


METRICS = (
    "gap_ratio",
    "entanglement",
    "participation_s1",
    "participation_s2",
    "subsystem_mz_mean",
    "subsystem_mz_variance",
)
CLAIMS = ("gap_ratio", "entanglement", "participation_s1", "participation_s2")


def eigensystem(record: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    length = int(record["L"])
    states = np.fromiter(
        (value for value in range(1 << length) if value.bit_count() == int(record["n_up"])),
        dtype=np.int64,
    )
    dimension = len(states)
    bits = ((states[:, None] >> np.arange(length, dtype=np.int64)) & 1).astype(np.float64)
    spins = bits - 0.5
    coupling = float(record["exchange"])
    diagonal = -(spins @ np.asarray(record["fields"], dtype=np.float64))
    diagonal += coupling * np.sum(spins * np.roll(spins, -1, axis=1), axis=1)
    matrix = np.diag(diagonal)
    lookup = np.full(1 << length, -1, dtype=np.int64)
    lookup[states] = np.arange(dimension, dtype=np.int64)
    rows = np.arange(dimension, dtype=np.int64)
    for site in range(length):
        neighbor = (site + 1) % length
        unlike = bits[:, site] != bits[:, neighbor]
        flipped = states ^ (1 << site) ^ (1 << neighbor)
        matrix[rows[unlike], lookup[flipped[unlike]]] += 0.5 * coupling
    values, vectors = np.linalg.eigh(matrix)
    return states, values, vectors


def subsystem_encoding(states: np.ndarray, length: int, start: int, size: int):
    sites_a = [(start + step) % length for step in range(size)]
    selected = set(sites_a)
    sites_b = [site for site in range(length) if site not in selected]
    index_a = np.zeros(len(states), dtype=np.int64)
    index_b = np.zeros(len(states), dtype=np.int64)
    for output, site in enumerate(sites_a):
        index_a |= ((states >> site) & 1) << output
    for output, site in enumerate(sites_b):
        index_b |= ((states >> site) & 1) << output
    magnetization = np.zeros(len(states), dtype=np.float64)
    for site in sites_a:
        magnetization += ((states >> site) & 1).astype(np.float64) - 0.5
    return index_a, index_b, magnetization, len(sites_a), len(sites_b)


def measure(vector: np.ndarray, encoding) -> dict:
    vector = np.asarray(vector, dtype=np.float64)
    vector = vector / np.sqrt(np.vdot(vector, vector).real)
    probabilities = vector * vector
    nonzero = probabilities > 0.0
    s1 = float(-np.dot(probabilities[nonzero], np.log(probabilities[nonzero])))
    s2 = float(-np.log(np.dot(probabilities, probabilities)))
    index_a, index_b, magnetization, count_a, count_b = encoding
    coefficient = np.zeros((1 << count_a, 1 << count_b), dtype=np.float64)
    coefficient[index_a, index_b] = vector
    reduced = coefficient @ coefficient.T
    lambdas = np.linalg.eigvalsh(reduced)
    lambdas = np.clip(lambdas, 0.0, None)
    lambdas /= np.sum(lambdas)
    retained = lambdas > 1.0e-15
    entropy = float(-np.dot(lambdas[retained], np.log(lambdas[retained])))
    mean = float(np.dot(probabilities, magnetization))
    variance = float(np.dot(probabilities, magnetization * magnetization) - mean * mean)
    return {
        "entanglement": entropy,
        "participation_s1": s1,
        "participation_s2": s2,
        "subsystem_mz_mean": mean,
        "subsystem_mz_variance": max(0.0, variance),
    }


def state_rows(experiment: dict) -> list[dict]:
    output: list[dict] = []
    for record in sorted(experiment["records"], key=lambda item: item["record_id"]):
        states, values, vectors = eigensystem(record)
        minimum, maximum = float(values[0]), float(values[-1])
        for query in sorted(record["queries"], key=lambda item: item["query_id"]):
            target = maximum + float(query["epsilon"]) * (minimum - maximum)
            candidates = np.arange(1, len(values) - 1, dtype=np.int64)
            ordering = np.lexsort((candidates, values[candidates], np.abs(values[candidates] - target)))
            chosen = np.sort(candidates[ordering[: int(query["packet_size"])]])
            encoding = subsystem_encoding(
                states,
                int(record["L"]),
                int(query["subsystem_start"]),
                int(query["subsystem_size"]),
            )
            for rank, raw_index in enumerate(chosen.tolist()):
                index = int(raw_index)
                gaps = (float(values[index] - values[index - 1]), float(values[index + 1] - values[index]))
                row = {
                    "record_id": record["record_id"],
                    "condition_id": record["condition_id"],
                    "query_id": query["query_id"],
                    "state_rank": rank,
                    "eigen_index": index,
                    "eigenvalue": float(values[index]),
                    "normalized_energy": float((values[index] - maximum) / (minimum - maximum)),
                    "gap_ratio": min(gaps) / max(gaps),
                }
                row.update(measure(vectors[:, index], encoding))
                output.append(row)
    output.sort(key=lambda row: (row["record_id"], row["query_id"], row["state_rank"]))
    return output


def sem(values: np.ndarray) -> float:
    return 0.0 if len(values) < 2 else float(np.std(values, ddof=1) / np.sqrt(len(values)))


def aggregate(experiment: dict, rows: list[dict]) -> list[dict]:
    records = {record["record_id"]: record for record in experiment["records"]}
    keys = sorted({(row["condition_id"], row["query_id"]) for row in rows})
    output: list[dict] = []
    for condition, query_id in keys:
        relevant = [row for row in rows if row["condition_id"] == condition and row["query_id"] == query_id]
        record_ids = sorted({row["record_id"] for row in relevant})
        query = next(item for item in records[record_ids[0]]["queries"] if item["query_id"] == query_id)
        item = {
            "aggregate_id": f"{condition}::{query_id}",
            "condition_id": condition,
            "query_id": query_id,
            "epsilon": float(query["epsilon"]),
            "subsystem_start": int(query["subsystem_start"]),
            "subsystem_size": int(query["subsystem_size"]),
            "realization_count": len(record_ids),
            "state_count": len(relevant),
        }
        for metric in METRICS:
            per_record = np.asarray(
                [
                    np.mean([row[metric] for row in relevant if row["record_id"] == record_id])
                    for record_id in record_ids
                ],
                dtype=np.float64,
            )
            item[f"mean_{metric}"] = float(np.mean(per_record))
            item[f"sem_{metric}"] = sem(per_record)
        output.append(item)
    return output


def finish(experiment: dict, rows: list[dict], aggregates: list[dict]) -> dict:
    by_id = {row["aggregate_id"]: row for row in aggregates}
    conclusions: list[dict] = []
    for comparison in sorted(experiment["comparisons"], key=lambda item: item["comparison_id"]):
        weak_id = f"{comparison['weak_condition']}::{comparison['query_id']}"
        strong_id = f"{comparison['strong_condition']}::{comparison['query_id']}"
        for metric in CLAIMS:
            effect = float(by_id[weak_id][f"mean_{metric}"] - by_id[strong_id][f"mean_{metric}"])
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
    return {
        "schema_version": "sector-audit-result/v1",
        "experiment_id": experiment["experiment_id"],
        "state_rows": rows,
        "aggregate_rows": aggregates,
        "conclusions": conclusions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    experiment = json.loads((args.experiment / "experiment.json").read_text(encoding="utf-8"))
    rows = state_rows(experiment)
    result = finish(experiment, rows, aggregate(experiment, rows))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
