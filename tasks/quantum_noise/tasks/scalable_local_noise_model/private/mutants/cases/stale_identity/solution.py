#!/usr/bin/env python3
"""Clean-room NumPy-only reference solver for local binary junction trees."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


MUTATION = "stale_identity"
ESTIMATOR = "direct_conditionals"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.write_bytes(payload.encode("utf-8"))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for row in rows
    )
    path.write_bytes(payload.encode("utf-8"))


def project_index(source_scope: list[str], source_index: int, target_scope: list[str]) -> int:
    positions = {variable: position for position, variable in enumerate(source_scope)}
    return sum(((source_index >> positions[variable]) & 1) << j for j, variable in enumerate(target_scope))


def marginalize(table: np.ndarray, source_scope: list[str], target_scope: list[str]) -> np.ndarray:
    result = np.zeros(1 << len(target_scope), dtype=np.float64)
    for index, value in enumerate(table):
        result[project_index(source_scope, index, target_scope)] += float(value)
    return result


def load_input(input_dir: Path) -> dict[str, Any]:
    manifest = read_json(input_dir / "manifest.json")
    counts_doc = read_json(input_dir / manifest["counts_file"])
    manifest["_count_by_id"] = {row["clique_id"]: row for row in counts_doc["tables"]}
    manifest["_clique_by_id"] = {row["clique_id"]: row for row in manifest["cliques"]}
    manifest["_queries"] = read_jsonl(input_dir / manifest["queries_file"])
    manifest["_validation"] = read_jsonl(input_dir / manifest["validation_file"])
    return manifest


def fit_model(instance: dict[str, Any]) -> dict[str, Any]:
    alpha = 0.0 if MUTATION == "no_smoothing" else float(instance["smoothing_pseudocount"])
    child_counts = {clique["clique_id"]: 0 for clique in instance["cliques"]}
    for clique in instance["cliques"]:
        if clique["parent_id"] is not None:
            child_counts[clique["parent_id"]] += 1
    corrupt_single_topology = MUTATION == "single_topology_failure" and max(child_counts.values()) == 3
    factors = []
    for clique in instance["cliques"]:
        record = instance["_count_by_id"][clique["clique_id"]]
        scope = clique["variables"]
        counts = np.asarray(record["counts"], dtype=np.float64)
        if MUTATION == "wrong_endian":
            width = len(scope)
            reversed_indices = np.asarray(
                [int(f"{index:0{width}b}"[::-1], 2) for index in range(counts.size)],
                dtype=np.int64,
            )
            counts = counts[reversed_indices]
        separator = clique["separator_variables"]
        size = counts.size
        table = np.zeros(size, dtype=np.float64)
        if not separator:
            if MUTATION == "uniform_root":
                table.fill(1.0 / size)
            else:
                table = counts + alpha
                table /= np.sum(table)
        elif MUTATION == "ignore_context":
            new_variables = clique["new_variables"]
            pooled = np.zeros(1 << len(new_variables), dtype=np.float64)
            for index, value in enumerate(counts):
                pooled[project_index(scope, index, new_variables)] += value
            pooled += alpha * (1 << len(separator))
            pooled /= np.sum(pooled)
            for index in range(size):
                table[index] = pooled[project_index(scope, index, new_variables)]
        else:
            for separator_index in range(1 << len(separator)):
                indices = [
                    index for index in range(size)
                    if project_index(scope, index, separator) == separator_index
                ]
                local = counts[indices] + alpha
                if float(np.sum(local)) <= 0.0:
                    local = np.ones(len(indices), dtype=np.float64)
                local /= np.sum(local)
                if ESTIMATOR == "shrunken_conditionals":
                    new_variables = clique["new_variables"]
                    pooled = np.zeros(1 << len(new_variables), dtype=np.float64)
                    for source_index, value in enumerate(counts):
                        pooled[project_index(scope, source_index, new_variables)] += value
                    pooled += 1.0
                    pooled /= np.sum(pooled)
                    beta = 8.0
                    context_shots = float(np.sum(counts[indices]))
                    for offset, index in enumerate(indices):
                        pooled_value = pooled[project_index(scope, index, new_variables)]
                        table[index] = (context_shots * local[offset] + beta * pooled_value) / (context_shots + beta)
                else:
                    table[np.asarray(indices, dtype=np.int64)] = local
        if corrupt_single_topology:
            uniform_value = 1.0 / (1 << len(clique["new_variables"]))
            table = 0.65 * table + 0.35 * uniform_value
        if MUTATION == "validation_contamination" and not separator:
            total_shots = sum(int(row["shots"]) for row in instance["_validation"])
            validation_rate = sum(int(row["successes"]) for row in instance["_validation"]) / total_shots
            tilt = 1.0e-3 * (validation_rate - 0.5)
            table *= np.exp(tilt * np.linspace(-1.0, 1.0, table.size))
            table /= np.sum(table)
        if MUTATION == "hash_nondeterminism" and not separator:
            jitter = ((hash(instance["instance_id"]) & 0xFFFF) / 65535.0) - 0.5
            table *= np.exp(1.0e-4 * jitter * np.linspace(-1.0, 1.0, table.size))
            table /= np.sum(table)
        factors.append({**clique, "probabilities": [float(value) for value in table]})
    if MUTATION == "truncate_tree":
        factors = factors[:-1]
    model = {
        "schema_version": "rooted-junction-model/v1",
        "instance_id": "stale_public_instance" if MUTATION == "stale_identity" else instance["instance_id"],
        "root_clique_id": instance["root_clique_id"],
        "factors": factors,
    }
    return model


def prepare_model(instance: dict[str, Any], model: dict[str, Any]) -> None:
    model["_factor_by_id"] = {}
    max_error = 0.0
    for factor in model["factors"]:
        copy = dict(factor)
        array = np.asarray(factor["probabilities"], dtype=np.float64)
        copy["_array"] = array
        model["_factor_by_id"][factor["clique_id"]] = copy
        separator = factor["separator_variables"]
        sums = marginalize(array, factor["variables"], separator)
        max_error = max(max_error, float(np.max(np.abs(sums - 1.0))))
    model["_max_normalization_error"] = max_error


def evidence_probability(instance: dict[str, Any], model: dict[str, Any], evidence: dict[str, int]) -> float:
    children = {cid: [] for cid in instance["_clique_by_id"]}
    for clique in instance["cliques"]:
        if clique["parent_id"] is not None:
            children[clique["parent_id"]].append(clique["clique_id"])
    for values in children.values():
        values.sort()

    def recurse(clique_id: str) -> np.ndarray:
        clique = instance["_clique_by_id"][clique_id]
        scope = clique["variables"]
        positions = {variable: position for position, variable in enumerate(scope)}
        values = np.array(model["_factor_by_id"][clique_id]["_array"], copy=True)
        for index in range(values.size):
            if any(
                variable in positions and ((index >> positions[variable]) & 1) != expected
                for variable, expected in evidence.items()
            ):
                values[index] = 0.0
        for child_id in children[clique_id]:
            child = instance["_clique_by_id"][child_id]
            child_message = recurse(child_id)
            for index in range(values.size):
                values[index] *= child_message[project_index(scope, index, child["separator_variables"])]
        if clique["separator_variables"]:
            return marginalize(values, scope, clique["separator_variables"])
        return np.asarray([float(np.sum(values))], dtype=np.float64)

    return float(np.clip(recurse(instance["root_clique_id"])[0], 0.0, 1.0))


def clique_marginals(instance: dict[str, Any], model: dict[str, Any]) -> dict[str, np.ndarray]:
    children = {cid: [] for cid in instance["_clique_by_id"]}
    for clique in instance["cliques"]:
        if clique["parent_id"] is not None:
            children[clique["parent_id"]].append(clique["clique_id"])
    for values in children.values():
        values.sort()
    order = []
    queue = [instance["root_clique_id"]]
    while queue:
        cid = queue.pop(0)
        order.append(cid)
        queue.extend(children[cid])
    upward = {}
    for cid in reversed(order):
        clique = instance["_clique_by_id"][cid]
        scope = clique["variables"]
        values = np.array(model["_factor_by_id"][cid]["_array"], copy=True)
        for child_id in children[cid]:
            child = instance["_clique_by_id"][child_id]
            for index in range(values.size):
                values[index] *= upward[child_id][project_index(scope, index, child["separator_variables"])]
        if clique["parent_id"] is not None:
            upward[cid] = marginalize(values, scope, clique["separator_variables"])
    downward = {}
    for cid in order:
        clique = instance["_clique_by_id"][cid]
        scope = clique["variables"]
        for child_id in children[cid]:
            child = instance["_clique_by_id"][child_id]
            values = np.array(model["_factor_by_id"][cid]["_array"], copy=True)
            if clique["parent_id"] is not None:
                for index in range(values.size):
                    values[index] *= downward[cid][project_index(scope, index, clique["separator_variables"])]
            for sibling_id in children[cid]:
                if sibling_id == child_id:
                    continue
                sibling = instance["_clique_by_id"][sibling_id]
                for index in range(values.size):
                    values[index] *= upward[sibling_id][project_index(scope, index, sibling["separator_variables"])]
            downward[child_id] = marginalize(values, scope, child["separator_variables"])
    result = {}
    for cid in order:
        clique = instance["_clique_by_id"][cid]
        scope = clique["variables"]
        values = np.array(model["_factor_by_id"][cid]["_array"], copy=True)
        if clique["parent_id"] is not None:
            for index in range(values.size):
                values[index] *= downward[cid][project_index(scope, index, clique["separator_variables"])]
        for child_id in children[cid]:
            child = instance["_clique_by_id"][child_id]
            for index in range(values.size):
                values[index] *= upward[child_id][project_index(scope, index, child["separator_variables"])]
        values /= np.sum(values)
        result[cid] = values
    return result


def parity_probability(instance: dict[str, Any], model: dict[str, Any], variables: list[str], parity: int) -> float:
    selected = set(variables)
    children = {cid: [] for cid in instance["_clique_by_id"]}
    for clique in instance["cliques"]:
        if clique["parent_id"] is not None:
            children[clique["parent_id"]].append(clique["clique_id"])
    for values in children.values():
        values.sort()

    def recurse(clique_id: str) -> np.ndarray:
        clique = instance["_clique_by_id"][clique_id]
        scope = clique["variables"]
        introduced_positions = [scope.index(v) for v in clique["new_variables"] if v in selected]
        values = np.array(model["_factor_by_id"][clique_id]["_array"], copy=True)
        for index in range(values.size):
            if sum((index >> position) & 1 for position in introduced_positions) % 2:
                values[index] = -values[index]
        for child_id in children[clique_id]:
            child = instance["_clique_by_id"][child_id]
            child_message = recurse(child_id)
            for index in range(values.size):
                values[index] *= child_message[project_index(scope, index, child["separator_variables"])]
        if clique["separator_variables"]:
            return marginalize(values, scope, clique["separator_variables"])
        return np.asarray([float(np.sum(values))], dtype=np.float64)

    expectation = float(recurse(instance["root_clique_id"])[0])
    probability_even = 0.5 * (1.0 + expectation)
    return float(np.clip(probability_even if parity == 0 else 1.0 - probability_even, 0.0, 1.0))


def diagnostics(instance: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    fitted = clique_marginals(instance, model)
    alpha = float(instance["smoothing_pseudocount"])
    raw = {}
    for clique in instance["cliques"]:
        row = instance["_count_by_id"][clique["clique_id"]]
        values = np.asarray(row["counts"], dtype=np.float64)
        raw[clique["clique_id"]] = (values + alpha) / (float(row["shots"]) + alpha * values.size)
    weighted_tv = 0.0
    total_shots = 0.0
    max_raw = 0.0
    max_model = 0.0
    for clique in instance["cliques"]:
        cid = clique["clique_id"]
        shots = float(instance["_count_by_id"][cid]["shots"])
        weighted_tv += shots * 0.5 * float(np.sum(np.abs(fitted[cid] - raw[cid])))
        total_shots += shots
        if clique["parent_id"] is not None:
            parent = instance["_clique_by_id"][clique["parent_id"]]
            sep = clique["separator_variables"]
            rp = marginalize(raw[parent["clique_id"]], parent["variables"], sep)
            rc = marginalize(raw[cid], clique["variables"], sep)
            mp = marginalize(fitted[parent["clique_id"]], parent["variables"], sep)
            mc = marginalize(fitted[cid], clique["variables"], sep)
            max_raw = max(max_raw, 0.5 * float(np.sum(np.abs(rp - rc))))
            max_model = max(max_model, 0.5 * float(np.sum(np.abs(mp - mc))))
    return {
        "schema_version": "local-noise-diagnostics/v1",
        "instance_id": instance["instance_id"],
        "factor_max_normalization_error": float(model["_max_normalization_error"]),
        "weighted_clique_tv_to_smoothed_counts": weighted_tv / total_shots,
        "max_raw_separator_tv": max_raw,
        "max_model_separator_tv": max_model,
        "query_count": len(instance["_queries"]),
        "interaction_count": len(instance["_validation"]),
    }


def solve(input_dir: Path, output_dir: Path) -> None:
    instance = load_input(input_dir)
    model = fit_model(instance)
    output_dir.mkdir(parents=True, exist_ok=True)
    if len(model["factors"]) != len(instance["cliques"]):
        write_json(output_dir / "model.json", model)
        for name in ("query_results.jsonl", "audit.json", "diagnostics.json"):
            (output_dir / name).write_bytes(b"{}\n")
        return
    prepare_model(instance, model)
    query_rows = []
    for query in instance["_queries"]:
        probability = evidence_probability(instance, model, query["assignment"])
        if MUTATION == "query_product" and len(query["assignment"]) > 1:
            probability = 1.0
            for variable, value in query["assignment"].items():
                probability *= evidence_probability(instance, model, {variable: value})
        query_rows.append({"query_id": query["query_id"], "probability": probability})

    audit_rows = []
    for row in instance["_validation"]:
        probability = parity_probability(instance, model, row["variables"], row["parity"])
        variance = max(float(row["shots"]) * probability * (1.0 - probability), 1.0)
        z_score = (float(row["successes"]) - float(row["shots"]) * probability) / math.sqrt(variance)
        audit_rows.append(
            {
                "interaction_id": row["interaction_id"],
                "predicted_probability": probability,
                "z_score": z_score,
                "absolute_z": abs(z_score),
                "rank": 0,
            }
        )
    if MUTATION == "ascending_audit":
        order = sorted(range(len(audit_rows)), key=lambda i: (audit_rows[i]["absolute_z"], audit_rows[i]["interaction_id"]))
    else:
        order = sorted(range(len(audit_rows)), key=lambda i: (-audit_rows[i]["absolute_z"], audit_rows[i]["interaction_id"]))
    for rank, index in enumerate(order, start=1):
        audit_rows[index]["rank"] = rank
    flagged = [audit_rows[index]["interaction_id"] for index in order[: int(instance["audit_top_k"])]]
    clean_model = {key: value for key, value in model.items() if not key.startswith("_")}
    write_json(output_dir / "model.json", clean_model)
    write_jsonl(output_dir / "query_results.jsonl", query_rows)
    write_json(
        output_dir / "audit.json",
        {
            "schema_version": "local-noise-audit/v1",
            "instance_id": instance["instance_id"],
            "interactions": audit_rows,
            "flagged_interaction_ids": flagged,
        },
    )
    write_json(output_dir / "diagnostics.json", diagnostics(instance, model))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    solve(args.input.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
