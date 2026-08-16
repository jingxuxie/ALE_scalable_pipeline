#!/usr/bin/env python3
"""Trusted deterministic generator for bounded-width binary noise instances."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

import numpy as np


TASK_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TASK_ROOT / "private" / "grader"))
import core  # noqa: E402


PUBLIC_CONFIG = {
    "instance_id": "review_branch_47",
    "seed": 742_031,
    "n": 47,
    "max_scope": 5,
    "shots": 6_000,
    "topology": "branch",
    "query_count": 18,
    "validation_count": 22,
    "anomaly_count": 3,
    "category": "retired_public_review",
}

HIDDEN_CONFIGS = [
    {"instance_id": "inst_8f2c7a13", "seed": 1_903_117, "n": 58, "max_scope": 5, "shots": 8_000, "topology": "chain", "query_count": 22, "validation_count": 24, "anomaly_count": 0, "category": "ordinary"},
    {"instance_id": "inst_41de9b76", "seed": 2_717_303, "n": 69, "max_scope": 6, "shots": 5_000, "topology": "branch", "query_count": 24, "validation_count": 26, "anomaly_count": 0, "category": "ordinary"},
    {"instance_id": "inst_c5a30e84", "seed": 3_141_593, "n": 61, "max_scope": 5, "shots": 6_000, "topology": "fork", "query_count": 23, "validation_count": 28, "anomaly_count": 4, "category": "anomaly"},
    {"instance_id": "inst_729bf016", "seed": 4_669_201, "n": 82, "max_scope": 6, "shots": 3_000, "topology": "branch", "query_count": 25, "validation_count": 30, "anomaly_count": 5, "category": "anomaly"},
    {"instance_id": "inst_e14c6952", "seed": 5_772_159, "n": 55, "max_scope": 6, "shots": 550, "topology": "fork", "query_count": 24, "validation_count": 27, "anomaly_count": 3, "category": "ood_low_shots"},
    {"instance_id": "inst_36a8d2f9", "seed": 6_283_185, "n": 88, "max_scope": 7, "shots": 1_500, "topology": "branch", "query_count": 26, "validation_count": 32, "anomaly_count": 4, "category": "ood_width"},
]


def _variable_names(n: int, rng: np.random.Generator) -> list[str]:
    tokens = [f"u{index:02d}_{int(rng.integers(100, 999))}" for index in range(n)]
    rng.shuffle(tokens)
    return tokens


def _layout(config: dict[str, Any], rng: np.random.Generator) -> tuple[list[str], list[dict[str, Any]], str]:
    n = int(config["n"])
    max_scope = int(config["max_scope"])
    variable_ids = _variable_names(n, rng)
    root_size = max(3, max_scope - 1)
    next_variable = root_size
    root_scope = variable_ids[:root_size].copy()
    rng.shuffle(root_scope)
    root_id = f"c{int(rng.integers(1000, 9999))}_root"
    cliques: list[dict[str, Any]] = [
        {
            "clique_id": root_id,
            "parent_id": None,
            "variables": root_scope,
            "separator_variables": [],
            "new_variables": root_scope.copy(),
        }
    ]
    while next_variable < n:
        if config["topology"] == "chain":
            parent = cliques[-1]
        elif config["topology"] == "fork":
            bound = max(1, int(math.sqrt(len(cliques) + 1)))
            parent = cliques[int(rng.integers(0, min(len(cliques), bound + 1)))]
        else:
            parent = cliques[int(rng.integers(0, len(cliques)))]
        separator_size = int(rng.integers(1, min(3, len(parent["variables"])) + 1))
        capacity = max_scope - separator_size
        remaining = n - next_variable
        if capacity <= 1:
            add_count = 1
        else:
            add_count = min(remaining, int(rng.integers(max(1, capacity - 1), capacity + 1)))
        separator = list(rng.choice(parent["variables"], size=separator_size, replace=False))
        new_variables = variable_ids[next_variable : next_variable + add_count]
        next_variable += add_count
        scope = separator + new_variables
        rng.shuffle(scope)
        separator_order = [item for item in scope if item in set(parent["variables"])]
        new_order = [item for item in scope if item not in set(parent["variables"])]
        cid = f"c{len(cliques):02d}_{int(rng.integers(1000, 9999))}"
        cliques.append(
            {
                "clique_id": cid,
                "parent_id": parent["clique_id"],
                "variables": scope,
                "separator_variables": separator_order,
                "new_variables": new_order,
            }
        )
    record_order = rng.permutation(len(cliques))
    shuffled_cliques = [cliques[int(index)] for index in record_order]
    shuffled_variables = variable_ids.copy()
    rng.shuffle(shuffled_variables)
    return shuffled_variables, shuffled_cliques, root_id


def _factor_table(clique: dict[str, Any], rng: np.random.Generator) -> list[float]:
    scope = clique["variables"]
    separator = clique["separator_variables"]
    size = 1 << len(scope)
    table = np.zeros(size, dtype=np.float64)
    if not separator:
        logits = rng.normal(0.0, 0.75, size=size)
        weights = np.exp(logits - np.max(logits)) + 0.025
        table = weights / np.sum(weights)
    else:
        separator_count = 1 << len(separator)
        for separator_index in range(separator_count):
            indices = [
                index
                for index in range(size)
                if core.project_index(scope, index, separator) == separator_index
            ]
            context_phase = 0.45 * (-1.0 if separator_index.bit_count() % 2 else 1.0)
            logits = rng.normal(context_phase, 1.05, size=len(indices))
            if separator_index & 1:
                logits = logits[::-1]
            weights = np.exp(logits - np.max(logits)) + 0.018
            weights /= np.sum(weights)
            table[np.asarray(indices, dtype=np.int64)] = weights
    return [float(value) for value in table]


def _model(instance_id: str, root_id: str, cliques: list[dict[str, Any]], rng: np.random.Generator) -> dict[str, Any]:
    factors = []
    for clique in cliques:
        factors.append({**clique, "probabilities": _factor_table(clique, rng)})
    return {
        "schema_version": "rooted-junction-model/v1",
        "instance_id": instance_id,
        "root_clique_id": root_id,
        "factors": factors,
    }


def _random_assignment(variables: list[str], size: int, rng: np.random.Generator) -> dict[str, int]:
    chosen = list(rng.choice(variables, size=size, replace=False)) if size else []
    rng.shuffle(chosen)
    return {variable: int(rng.integers(0, 2)) for variable in chosen}


def generate_instance(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    rng = np.random.default_rng(int(config["seed"]))
    variables, cliques, root_id = _layout(config, rng)
    instance_id = str(config["instance_id"])
    manifest = {
        "schema_version": "local-noise-input/v1",
        "instance_id": instance_id,
        "variable_count": int(config["n"]),
        "variable_ids": variables,
        "root_clique_id": root_id,
        "table_encoding": {"assignment_values": [0, 1], "index_rule": "sum(value[j] * 2**j)"},
        "smoothing_pseudocount": 0.5,
        "cliques": cliques,
        "counts_file": "clique_counts.json",
        "queries_file": "queries.jsonl",
        "validation_file": "validation.jsonl",
        "audit_top_k": max(3, int(config["anomaly_count"])),
        "declared_bounds": {
            "maximum_variables": 96,
            "maximum_clique_size": 7,
            "maximum_queries": 64,
            "maximum_validation_interactions": 64,
        },
    }
    true_model = _model(instance_id, root_id, cliques, rng)

    with _temporary_instance(manifest, true_model) as parsed:
        marginals = core.clique_marginals(parsed, true_model)
        count_tables: list[dict[str, Any]] = []
        for clique in cliques:
            shot_multiplier = float(rng.uniform(0.72, 1.28))
            shots = max(120, int(round(float(config["shots"]) * shot_multiplier)))
            probabilities = marginals[clique["clique_id"]]
            probabilities = probabilities / probabilities.sum()
            counts = rng.multinomial(shots, probabilities)
            count_tables.append(
                {
                    "clique_id": clique["clique_id"],
                    "shots": shots,
                    "counts": [int(value) for value in counts],
                }
            )

        queries: list[dict[str, Any]] = []
        for index in range(int(config["query_count"])):
            if index == 0:
                size = 0
            elif index < 4:
                size = index
            else:
                size = int(rng.integers(2, min(9, len(variables)) + 1))
            queries.append(
                {
                    "query_id": f"q_{index:03d}_{int(rng.integers(100, 999))}",
                    "assignment": _random_assignment(variables, size, rng),
                }
            )

        validation: list[dict[str, Any]] = []
        interaction_specs: list[tuple[list[str], int, float]] = []
        for _ in range(int(config["validation_count"])):
            size = int(rng.integers(2, min(7, len(variables)) + 1))
            chosen = list(rng.choice(variables, size=size, replace=False))
            rng.shuffle(chosen)
            parity = int(rng.integers(0, 2))
            probability = core.parity_probability(parsed, true_model, chosen, parity)
            interaction_specs.append((chosen, parity, probability))

        anomaly_indices = set(
            int(index)
            for index in rng.choice(
                len(interaction_specs), size=int(config["anomaly_count"]), replace=False
            )
        ) if int(config["anomaly_count"]) else set()
        anomaly_ids: list[str] = []
        for index, (chosen, parity, probability) in enumerate(interaction_specs):
            iid = f"v_{index:03d}_{int(rng.integers(1000, 9999))}"
            shots = int(rng.integers(2_800, 6_500))
            sampled_probability = probability
            if index in anomaly_indices:
                direction = -1.0 if probability > 0.5 else 1.0
                shift = float(rng.uniform(0.16, 0.24))
                sampled_probability = float(np.clip(probability + direction * shift, 0.025, 0.975))
                anomaly_ids.append(iid)
            successes = int(rng.binomial(shots, sampled_probability))
            validation.append(
                {
                    "interaction_id": iid,
                    "variables": chosen,
                    "parity": parity,
                    "shots": shots,
                    "successes": successes,
                }
            )

    counts_doc = {"schema_version": "local-count-tables/v1", "instance_id": instance_id, "tables": count_tables}
    truth = {
        "schema_version": "local-noise-truth/v1",
        "instance_id": instance_id,
        "category": config["category"],
        "topology": config["topology"],
        "seed": int(config["seed"]),
        "true_model": true_model,
        "anomaly_ids": anomaly_ids,
        "private_queries": [
            {
                "query_id": f"h_{index:03d}",
                "assignment": _random_assignment(
                    variables,
                    int(rng.integers(2, min(10, len(variables) + 1))),
                    rng,
                ),
            }
            for index in range(28)
        ],
    }
    public = {"manifest": manifest, "counts": counts_doc, "queries": queries, "validation": validation}
    return public, truth, true_model


class _temporary_instance:
    """Build the in-memory derived keys core inference needs without filesystem I/O."""

    def __init__(self, manifest: dict[str, Any], model: dict[str, Any]):
        self.manifest = manifest
        self.model = model

    def __enter__(self) -> dict[str, Any]:
        by_id = {item["clique_id"]: item for item in self.manifest["cliques"]}
        children = {item["clique_id"]: [] for item in self.manifest["cliques"]}
        for item in self.manifest["cliques"]:
            if item["parent_id"] is not None:
                children[item["parent_id"]].append(item["clique_id"])
        order: list[str] = []
        stack = [self.manifest["root_clique_id"]]
        while stack:
            cid = stack.pop()
            order.append(cid)
            stack.extend(children[cid])
        self.manifest["_clique_by_id"] = by_id
        self.manifest["_topological_ids"] = order
        core.validate_model(self.model, self.manifest)
        return self.manifest

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.manifest.pop("_clique_by_id", None)
        self.manifest.pop("_topological_ids", None)
        self.model.pop("_factor_by_id", None)
        self.model.pop("_max_normalization_error", None)
        for factor in self.model["factors"]:
            factor.pop("_array", None)


def write_instance(input_dir: Path, public: dict[str, Any]) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    core.dump_json(input_dir / "manifest.json", public["manifest"])
    core.dump_json(input_dir / "clique_counts.json", public["counts"])
    core.dump_jsonl(input_dir / "queries.jsonl", public["queries"])
    core.dump_jsonl(input_dir / "validation.jsonl", public["validation"])


def reset_generated_directory(path: Path, task_root: Path) -> None:
    resolved = path.resolve()
    if task_root.resolve() not in resolved.parents:
        raise RuntimeError("refusing to reset generated data outside the task root")
    if path.exists():
        def writable_retry(function, target, _exc_info):
            os.chmod(target, stat.S_IWRITE)
            function(target)
        shutil.rmtree(path, onerror=writable_retry)
    path.mkdir(parents=True)


def generate_all(task_root: Path = TASK_ROOT) -> dict[str, Any]:
    participant_input = task_root / "participant" / "input"
    hidden_root = task_root / "private" / "hidden_inputs" / "cases"
    truth_root = task_root / "private" / "reference" / "truth"
    reset_generated_directory(hidden_root, task_root)
    reset_generated_directory(truth_root, task_root)
    public, public_truth, _ = generate_instance(PUBLIC_CONFIG)
    write_instance(participant_input, public)
    core.dump_json(task_root / "private" / "reference" / "public_truth.json", public_truth)
    hidden_summary = []
    for config in HIDDEN_CONFIGS:
        case_public, case_truth, _ = generate_instance(config)
        write_instance(hidden_root / config["instance_id"], case_public)
        core.dump_json(truth_root / f"{config['instance_id']}.json", case_truth)
        hidden_summary.append(
            {
                "instance_id": config["instance_id"],
                "variable_count": config["n"],
                "maximum_clique_size": config["max_scope"],
            }
        )
    manifest = {
        "schema_version": "local-noise-hidden-suite/v1",
        "private_seed_policy": "fixed retired author seeds; regenerate from server-secret seeds before scored release",
        "cases": hidden_summary,
    }
    core.dump_json(task_root / "private" / "hidden_inputs" / "suite_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, default=TASK_ROOT)
    args = parser.parse_args()
    manifest = generate_all(args.task_root.resolve())
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
