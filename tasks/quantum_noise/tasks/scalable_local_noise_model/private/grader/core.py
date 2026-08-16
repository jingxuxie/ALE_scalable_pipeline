"""Trusted parsing, junction-tree inference, and scoring utilities."""

from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
from typing import Any, Iterable

import numpy as np


OUTPUT_NAMES = {"model.json", "query_results.jsonl", "audit.json", "diagnostics.json"}
OUTPUT_LIMITS = {
    "model.json": 1_500_000,
    "query_results.jsonl": 500_000,
    "audit.json": 500_000,
    "diagnostics.json": 64_000,
}


class SubmissionError(ValueError):
    """An expected validation failure safe to expose to a participant."""


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {token}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path, max_bytes: int = 4_000_000) -> Any:
    try:
        if path.stat().st_size > max_bytes:
            raise SubmissionError(f"{path.name} exceeds its size limit")
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except SubmissionError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise SubmissionError(f"invalid JSON in {path.name}: {exc}") from exc


def load_jsonl(path: Path, max_bytes: int = 2_000_000, max_rows: int = 10_000) -> list[Any]:
    try:
        if path.stat().st_size > max_bytes:
            raise SubmissionError(f"{path.name} exceeds its size limit")
        rows: list[Any] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise SubmissionError(f"blank line in {path.name}:{line_number}")
                rows.append(
                    json.loads(
                        line,
                        parse_constant=_reject_constant,
                        object_pairs_hook=_unique_object,
                    )
                )
                if len(rows) > max_rows:
                    raise SubmissionError(f"too many rows in {path.name}")
        return rows
    except SubmissionError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise SubmissionError(f"invalid JSONL in {path.name}: {exc}") from exc


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.write_bytes(payload.encode("utf-8"))


def dump_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")


def _is_regular(path: Path, max_bytes: int | None = None) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
        return False
    return max_bytes is None or info.st_size <= max_bytes


def validate_real_directory(path: Path, expected_names: set[str], limits: dict[str, int]) -> None:
    try:
        info = path.lstat()
        reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISDIR(info.st_mode):
            raise SubmissionError("output path must be a real directory")
        entries = list(path.iterdir())
    except SubmissionError:
        raise
    except OSError as exc:
        raise SubmissionError("output directory is missing or unreadable") from exc
    names = {entry.name for entry in entries}
    if names != expected_names:
        raise SubmissionError(
            f"artifact inventory mismatch; missing={sorted(expected_names - names)}, "
            f"unexpected={sorted(names - expected_names)}"
        )
    for name in sorted(names):
        if not _is_regular(path / name, limits[name]):
            raise SubmissionError(f"{name} must be one bounded regular non-linked file")


def _require_int(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise SubmissionError(f"{label} must be an integer >= {minimum}")
    return value


def _require_float(value: Any, label: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise SubmissionError(f"{label} must be a finite JSON number")
    return float(value)


def load_instance(input_dir: Path) -> dict[str, Any]:
    manifest = load_json(input_dir / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "local-noise-input/v1":
        raise SubmissionError("unsupported input manifest")
    required = {
        "schema_version", "instance_id", "variable_count", "variable_ids", "root_clique_id",
        "table_encoding", "smoothing_pseudocount", "cliques", "counts_file", "queries_file",
        "validation_file", "audit_top_k", "declared_bounds",
    }
    if set(manifest) != required:
        raise SubmissionError("manifest fields do not match local-noise-input/v1")
    variable_count = _require_int(manifest["variable_count"], "variable_count", 1)
    if variable_count > 96:
        raise SubmissionError("variable_count exceeds the declared task bound")
    variable_ids = manifest["variable_ids"]
    if (
        not isinstance(variable_ids, list)
        or len(variable_ids) != variable_count
        or any(not isinstance(item, str) or not item or len(item) > 80 for item in variable_ids)
        or len(set(variable_ids)) != len(variable_ids)
    ):
        raise SubmissionError("variable_ids must be unique nonempty strings")
    encoding = manifest["table_encoding"]
    if encoding != {"assignment_values": [0, 1], "index_rule": "sum(value[j] * 2**j)"}:
        raise SubmissionError("unsupported table encoding")
    alpha = _require_float(manifest["smoothing_pseudocount"], "smoothing_pseudocount")
    if alpha <= 0.0 or alpha > 100.0:
        raise SubmissionError("smoothing_pseudocount is out of range")
    bounds = manifest["declared_bounds"]
    expected_bounds = {
        "maximum_variables": 96,
        "maximum_clique_size": 7,
        "maximum_queries": 64,
        "maximum_validation_interactions": 64,
    }
    if bounds != expected_bounds:
        raise SubmissionError("declared_bounds does not match the task contract")
    cliques = manifest["cliques"]
    if not isinstance(cliques, list) or not cliques or len(cliques) > 48:
        raise SubmissionError("cliques must be a nonempty list")
    clique_ids: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for position, clique in enumerate(cliques):
        expected = {"clique_id", "parent_id", "variables", "separator_variables", "new_variables"}
        if not isinstance(clique, dict) or set(clique) != expected:
            raise SubmissionError(f"clique {position} schema mismatch")
        cid = clique["clique_id"]
        if not isinstance(cid, str) or not cid or cid in clique_ids:
            raise SubmissionError("clique IDs must be unique nonempty strings")
        clique_ids.add(cid)
        scope = clique["variables"]
        if (
            not isinstance(scope, list)
            or not scope
            or len(scope) > 7
            or len(set(scope)) != len(scope)
            or any(item not in variable_ids for item in scope)
        ):
            raise SubmissionError(f"invalid scope for {cid}")
        by_id[cid] = clique
    root_id = manifest["root_clique_id"]
    if root_id not in by_id:
        raise SubmissionError("root_clique_id is unknown")
    introduced: set[str] = set()
    root = by_id[root_id]
    if root["parent_id"] is not None or root["separator_variables"] != [] or root["new_variables"] != root["variables"]:
        raise SubmissionError("root clique metadata is inconsistent")
    introduced.update(root["new_variables"])
    remaining = set(clique_ids - {root_id})
    ordered = [root_id]
    while remaining:
        progressed = False
        for cid in sorted(remaining):
            clique = by_id[cid]
            parent_id = clique["parent_id"]
            if parent_id not in ordered:
                continue
            parent = by_id[parent_id]
            expected_sep = [item for item in clique["variables"] if item in set(parent["variables"])]
            expected_new = [item for item in clique["variables"] if item not in set(parent["variables"])]
            if clique["separator_variables"] != expected_sep or clique["new_variables"] != expected_new or not expected_new:
                raise SubmissionError(f"separator/new-variable metadata mismatch for {cid}")
            if any(item in introduced for item in expected_new):
                raise SubmissionError(f"variable introduced more than once at {cid}")
            introduced.update(expected_new)
            ordered.append(cid)
            remaining.remove(cid)
            progressed = True
            break
        if not progressed:
            raise SubmissionError("clique parent references are cyclic or disconnected")
    if introduced != set(variable_ids):
        raise SubmissionError("cliques do not introduce exactly all variables")
    manifest["_clique_by_id"] = by_id
    manifest["_topological_ids"] = ordered

    counts_doc = load_json(input_dir / manifest["counts_file"])
    if not isinstance(counts_doc, dict) or set(counts_doc) != {"schema_version", "instance_id", "tables"}:
        raise SubmissionError("count-table document schema mismatch")
    if counts_doc["schema_version"] != "local-count-tables/v1" or counts_doc["instance_id"] != manifest["instance_id"]:
        raise SubmissionError("count-table identity mismatch")
    tables = counts_doc["tables"]
    if not isinstance(tables, list) or len(tables) != len(cliques):
        raise SubmissionError("count-table inventory mismatch")
    count_by_id: dict[str, dict[str, Any]] = {}
    for item in tables:
        if not isinstance(item, dict) or set(item) != {"clique_id", "shots", "counts"}:
            raise SubmissionError("count table record schema mismatch")
        cid = item["clique_id"]
        if cid not in by_id or cid in count_by_id:
            raise SubmissionError("unknown or duplicate count table")
        shots = _require_int(item["shots"], f"{cid}.shots", 1)
        values = item["counts"]
        expected_size = 1 << len(by_id[cid]["variables"])
        if (
            not isinstance(values, list)
            or len(values) != expected_size
            or any(type(value) is not int or value < 0 for value in values)
            or sum(values) != shots
        ):
            raise SubmissionError(f"invalid counts for {cid}")
        count_by_id[cid] = item
    manifest["_count_by_id"] = count_by_id

    queries = load_jsonl(input_dir / manifest["queries_file"])
    if len(queries) > 64:
        raise SubmissionError("query count exceeds the declared task bound")
    seen_query: set[str] = set()
    for row in queries:
        if not isinstance(row, dict) or set(row) != {"query_id", "assignment"}:
            raise SubmissionError("query record schema mismatch")
        qid, assignment = row["query_id"], row["assignment"]
        if not isinstance(qid, str) or not qid or qid in seen_query or not isinstance(assignment, dict):
            raise SubmissionError("invalid or duplicate query record")
        seen_query.add(qid)
        if len(assignment) > 20:
            raise SubmissionError(f"query {qid} assigns too many variables")
        for variable, value in assignment.items():
            if variable not in variable_ids or type(value) is not int or value not in {0, 1}:
                raise SubmissionError(f"invalid assignment in query {qid}")
    manifest["_queries"] = queries

    validation = load_jsonl(input_dir / manifest["validation_file"])
    if len(validation) > 64:
        raise SubmissionError("validation count exceeds the declared task bound")
    seen_interaction: set[str] = set()
    for row in validation:
        expected = {"interaction_id", "variables", "parity", "shots", "successes"}
        if not isinstance(row, dict) or set(row) != expected:
            raise SubmissionError("validation record schema mismatch")
        iid, variables = row["interaction_id"], row["variables"]
        if (
            not isinstance(iid, str) or not iid or iid in seen_interaction
            or not isinstance(variables, list) or not variables or len(variables) > 7
            or len(set(variables)) != len(variables) or any(item not in variable_ids for item in variables)
        ):
            raise SubmissionError("invalid validation interaction")
        seen_interaction.add(iid)
        parity = _require_int(row["parity"], f"{iid}.parity")
        shots = _require_int(row["shots"], f"{iid}.shots", 1)
        successes = _require_int(row["successes"], f"{iid}.successes")
        if parity not in {0, 1} or successes > shots:
            raise SubmissionError("invalid validation count")
    manifest["_validation"] = validation
    top_k = _require_int(manifest["audit_top_k"], "audit_top_k", 0)
    if top_k > len(validation):
        raise SubmissionError("audit_top_k exceeds validation row count")
    return manifest


def assignment_index(scope: list[str], assignment: dict[str, int]) -> int:
    return sum(int(assignment[variable]) << position for position, variable in enumerate(scope))


def project_index(source_scope: list[str], source_index: int, target_scope: list[str]) -> int:
    positions = {variable: position for position, variable in enumerate(source_scope)}
    return sum(((source_index >> positions[variable]) & 1) << j for j, variable in enumerate(target_scope))


def marginalize_table(table: np.ndarray, source_scope: list[str], target_scope: list[str]) -> np.ndarray:
    result = np.zeros(1 << len(target_scope), dtype=np.float64)
    for source_index, value in enumerate(table):
        result[project_index(source_scope, source_index, target_scope)] += float(value)
    return result


def smoothed_count_tables(instance: dict[str, Any]) -> dict[str, np.ndarray]:
    alpha = float(instance["smoothing_pseudocount"])
    result: dict[str, np.ndarray] = {}
    for clique in instance["cliques"]:
        record = instance["_count_by_id"][clique["clique_id"]]
        counts = np.asarray(record["counts"], dtype=np.float64)
        result[clique["clique_id"]] = (counts + alpha) / (float(record["shots"]) + alpha * counts.size)
    return result


def validate_model(model: Any, instance: dict[str, Any], normalization_tolerance: float = 2.0e-7) -> dict[str, Any]:
    if not isinstance(model, dict) or set(model) != {"schema_version", "instance_id", "root_clique_id", "factors"}:
        raise SubmissionError("model.json top-level schema mismatch")
    if model["schema_version"] != "rooted-junction-model/v1" or model["instance_id"] != instance["instance_id"]:
        raise SubmissionError("model identity or schema mismatch")
    if model["root_clique_id"] != instance["root_clique_id"]:
        raise SubmissionError("model root does not match the manifest")
    factors = model["factors"]
    if not isinstance(factors, list) or len(factors) != len(instance["cliques"]):
        raise SubmissionError("model factor inventory mismatch")
    by_id: dict[str, dict[str, Any]] = {}
    max_error = 0.0
    for factor, clique in zip(factors, instance["cliques"]):
        expected_keys = {
            "clique_id", "parent_id", "variables", "separator_variables", "new_variables", "probabilities"
        }
        if not isinstance(factor, dict) or set(factor) != expected_keys:
            raise SubmissionError("model factor schema mismatch")
        for key in expected_keys - {"probabilities"}:
            if factor[key] != clique[key]:
                raise SubmissionError(f"model metadata mismatch for {clique['clique_id']}.{key}")
        values = factor["probabilities"]
        size = 1 << len(clique["variables"])
        if not isinstance(values, list) or len(values) != size:
            raise SubmissionError(f"wrong factor table size for {clique['clique_id']}")
        array = np.empty(size, dtype=np.float64)
        for index, value in enumerate(values):
            number = _require_float(value, f"{clique['clique_id']}.probabilities[{index}]")
            if number < 0.0 or number > 1.0:
                raise SubmissionError("factor probability outside [0,1]")
            array[index] = number
        separator = clique["separator_variables"]
        group_sums = np.zeros(1 << len(separator), dtype=np.float64)
        for index, value in enumerate(array):
            group_sums[project_index(clique["variables"], index, separator)] += value
        error = float(np.max(np.abs(group_sums - 1.0)))
        max_error = max(max_error, error)
        if error > normalization_tolerance:
            raise SubmissionError(f"factor normalization failed for {clique['clique_id']}")
        copy = dict(factor)
        copy["_array"] = array
        by_id[clique["clique_id"]] = copy
    model["_factor_by_id"] = by_id
    model["_max_normalization_error"] = max_error
    return model


def evidence_probability(instance: dict[str, Any], model: dict[str, Any], evidence: dict[str, int]) -> float:
    known = set(instance["variable_ids"])
    if any(variable not in known or value not in {0, 1} for variable, value in evidence.items()):
        raise SubmissionError("invalid evidence assignment")
    children: dict[str, list[str]] = {cid: [] for cid in instance["_clique_by_id"]}
    for clique in instance["cliques"]:
        if clique["parent_id"] is not None:
            children[clique["parent_id"]].append(clique["clique_id"])
    for values in children.values():
        values.sort()

    def message(clique_id: str) -> np.ndarray:
        clique = instance["_clique_by_id"][clique_id]
        scope = clique["variables"]
        values = np.array(model["_factor_by_id"][clique_id]["_array"], copy=True)
        positions = {variable: position for position, variable in enumerate(scope)}
        for index in range(values.size):
            for variable, expected in evidence.items():
                if variable in positions and ((index >> positions[variable]) & 1) != expected:
                    values[index] = 0.0
                    break
        for child_id in children[clique_id]:
            child = instance["_clique_by_id"][child_id]
            child_message = message(child_id)
            separator = child["separator_variables"]
            for index in range(values.size):
                values[index] *= child_message[project_index(scope, index, separator)]
        separator = clique["separator_variables"]
        if not separator:
            return np.asarray([float(np.sum(values))], dtype=np.float64)
        return marginalize_table(values, scope, separator)

    value = float(message(instance["root_clique_id"])[0])
    if not math.isfinite(value):
        raise SubmissionError("inference produced a non-finite probability")
    return min(1.0, max(0.0, value))


def clique_marginals(instance: dict[str, Any], model: dict[str, Any]) -> dict[str, np.ndarray]:
    children: dict[str, list[str]] = {cid: [] for cid in instance["_clique_by_id"]}
    for clique in instance["cliques"]:
        if clique["parent_id"] is not None:
            children[clique["parent_id"]].append(clique["clique_id"])
    for values in children.values():
        values.sort()
    order = instance["_topological_ids"]

    upward: dict[str, np.ndarray] = {}
    for clique_id in reversed(order):
        clique = instance["_clique_by_id"][clique_id]
        scope = clique["variables"]
        values = np.array(model["_factor_by_id"][clique_id]["_array"], copy=True)
        for child_id in children[clique_id]:
            child = instance["_clique_by_id"][child_id]
            message = upward[child_id]
            for index in range(values.size):
                values[index] *= message[project_index(scope, index, child["separator_variables"])]
        if clique["parent_id"] is not None:
            upward[clique_id] = marginalize_table(values, scope, clique["separator_variables"])

    downward: dict[str, np.ndarray] = {}
    for clique_id in order:
        clique = instance["_clique_by_id"][clique_id]
        scope = clique["variables"]
        for child_id in children[clique_id]:
            child = instance["_clique_by_id"][child_id]
            values = np.array(model["_factor_by_id"][clique_id]["_array"], copy=True)
            if clique["parent_id"] is not None:
                incoming = downward[clique_id]
                for index in range(values.size):
                    values[index] *= incoming[project_index(scope, index, clique["separator_variables"])]
            for sibling_id in children[clique_id]:
                if sibling_id == child_id:
                    continue
                sibling = instance["_clique_by_id"][sibling_id]
                message = upward[sibling_id]
                for index in range(values.size):
                    values[index] *= message[project_index(scope, index, sibling["separator_variables"])]
            downward[child_id] = marginalize_table(values, scope, child["separator_variables"])

    result: dict[str, np.ndarray] = {}
    for clique_id in order:
        clique = instance["_clique_by_id"][clique_id]
        scope = clique["variables"]
        values = np.array(model["_factor_by_id"][clique_id]["_array"], copy=True)
        if clique["parent_id"] is not None:
            incoming = downward[clique_id]
            for index in range(values.size):
                values[index] *= incoming[project_index(scope, index, clique["separator_variables"])]
        for child_id in children[clique_id]:
            child = instance["_clique_by_id"][child_id]
            message = upward[child_id]
            for index in range(values.size):
                values[index] *= message[project_index(scope, index, child["separator_variables"])]
        total = float(np.sum(values))
        if total <= 0.0 or not math.isfinite(total):
            raise SubmissionError("model has zero or non-finite total mass")
        result[clique_id] = values / total
    return result


def parity_probability(
    instance: dict[str, Any], model: dict[str, Any], variables: list[str], parity: int
) -> float:
    selected = set(variables)
    children: dict[str, list[str]] = {cid: [] for cid in instance["_clique_by_id"]}
    for clique in instance["cliques"]:
        if clique["parent_id"] is not None:
            children[clique["parent_id"]].append(clique["clique_id"])
    for values in children.values():
        values.sort()

    def signed_message(clique_id: str) -> np.ndarray:
        clique = instance["_clique_by_id"][clique_id]
        scope = clique["variables"]
        introduced_positions = [
            scope.index(variable) for variable in clique["new_variables"] if variable in selected
        ]
        values = np.array(model["_factor_by_id"][clique_id]["_array"], copy=True)
        if introduced_positions:
            for index in range(values.size):
                if sum((index >> position) & 1 for position in introduced_positions) % 2:
                    values[index] = -values[index]
        for child_id in children[clique_id]:
            child = instance["_clique_by_id"][child_id]
            child_message = signed_message(child_id)
            separator = child["separator_variables"]
            for index in range(values.size):
                values[index] *= child_message[project_index(scope, index, separator)]
        separator = clique["separator_variables"]
        if separator:
            return marginalize_table(values, scope, separator)
        return np.asarray([float(np.sum(values))], dtype=np.float64)

    expectation = float(signed_message(instance["root_clique_id"])[0])
    probability_even = 0.5 * (1.0 + expectation)
    probability = probability_even if parity == 0 else 1.0 - probability_even
    return min(1.0, max(0.0, probability))


def audit_records(instance: dict[str, Any], model: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    for row in instance["_validation"]:
        probability = parity_probability(instance, model, row["variables"], row["parity"])
        variance = max(float(row["shots"]) * probability * (1.0 - probability), 1.0)
        z_score = (float(row["successes"]) - float(row["shots"]) * probability) / math.sqrt(variance)
        records.append(
            {
                "interaction_id": row["interaction_id"],
                "predicted_probability": probability,
                "z_score": z_score,
                "absolute_z": abs(z_score),
                "rank": 0,
            }
        )
    order = sorted(range(len(records)), key=lambda i: (-records[i]["absolute_z"], records[i]["interaction_id"]))
    for rank, index in enumerate(order, start=1):
        records[index]["rank"] = rank
    flagged = [records[index]["interaction_id"] for index in order[: int(instance["audit_top_k"])]]
    return records, flagged


def compute_diagnostics(instance: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    fitted = clique_marginals(instance, model)
    raw = smoothed_count_tables(instance)
    weighted_tv = 0.0
    total_shots = 0.0
    max_raw_separator_tv = 0.0
    max_model_separator_tv = 0.0
    for clique in instance["cliques"]:
        cid = clique["clique_id"]
        shots = float(instance["_count_by_id"][cid]["shots"])
        weighted_tv += shots * 0.5 * float(np.sum(np.abs(fitted[cid] - raw[cid])))
        total_shots += shots
        if clique["parent_id"] is not None:
            parent_id = clique["parent_id"]
            parent_scope = instance["_clique_by_id"][parent_id]["variables"]
            separator = clique["separator_variables"]
            raw_parent = marginalize_table(raw[parent_id], parent_scope, separator)
            raw_child = marginalize_table(raw[cid], clique["variables"], separator)
            model_parent = marginalize_table(fitted[parent_id], parent_scope, separator)
            model_child = marginalize_table(fitted[cid], clique["variables"], separator)
            max_raw_separator_tv = max(max_raw_separator_tv, 0.5 * float(np.sum(np.abs(raw_parent - raw_child))))
            max_model_separator_tv = max(
                max_model_separator_tv, 0.5 * float(np.sum(np.abs(model_parent - model_child)))
            )
    return {
        "schema_version": "local-noise-diagnostics/v1",
        "instance_id": instance["instance_id"],
        "factor_max_normalization_error": float(model["_max_normalization_error"]),
        "weighted_clique_tv_to_smoothed_counts": weighted_tv / total_shots,
        "max_raw_separator_tv": max_raw_separator_tv,
        "max_model_separator_tv": max_model_separator_tv,
        "query_count": len(instance["_queries"]),
        "interaction_count": len(instance["_validation"]),
    }


def build_outputs(instance: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    validate_model(model, instance)
    query_rows = [
        {
            "query_id": row["query_id"],
            "probability": evidence_probability(instance, model, row["assignment"]),
        }
        for row in instance["_queries"]
    ]
    interactions, flagged = audit_records(instance, model)
    audit = {
        "schema_version": "local-noise-audit/v1",
        "instance_id": instance["instance_id"],
        "interactions": interactions,
        "flagged_interaction_ids": flagged,
    }
    diagnostics = compute_diagnostics(instance, model)
    return {"model": model, "queries": query_rows, "audit": audit, "diagnostics": diagnostics}


def write_outputs(output_dir: Path, instance: dict[str, Any], model: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    built = build_outputs(instance, model)
    clean_model = {key: value for key, value in built["model"].items() if not key.startswith("_")}
    clean_factors = []
    for factor in clean_model["factors"]:
        clean_factors.append({key: value for key, value in factor.items() if not key.startswith("_")})
    clean_model["factors"] = clean_factors
    dump_json(output_dir / "model.json", clean_model)
    dump_jsonl(output_dir / "query_results.jsonl", built["queries"])
    dump_json(output_dir / "audit.json", built["audit"])
    dump_json(output_dir / "diagnostics.json", built["diagnostics"])


def load_submission_outputs(output_dir: Path, instance: dict[str, Any]) -> dict[str, Any]:
    validate_real_directory(output_dir, OUTPUT_NAMES, OUTPUT_LIMITS)
    model = validate_model(load_json(output_dir / "model.json", OUTPUT_LIMITS["model.json"]), instance)

    query_rows = load_jsonl(output_dir / "query_results.jsonl", OUTPUT_LIMITS["query_results.jsonl"])
    if len(query_rows) != len(instance["_queries"]):
        raise SubmissionError("query_results.jsonl row count mismatch")
    parsed_queries: list[dict[str, Any]] = []
    for actual, expected in zip(query_rows, instance["_queries"]):
        if not isinstance(actual, dict) or set(actual) != {"query_id", "probability"}:
            raise SubmissionError("query result schema mismatch")
        if actual["query_id"] != expected["query_id"]:
            raise SubmissionError("query result identity/order mismatch")
        probability = _require_float(actual["probability"], f"{actual['query_id']}.probability")
        if probability < 0.0 or probability > 1.0:
            raise SubmissionError("query probability outside [0,1]")
        parsed_queries.append({"query_id": actual["query_id"], "probability": probability})

    audit = load_json(output_dir / "audit.json", OUTPUT_LIMITS["audit.json"])
    if not isinstance(audit, dict) or set(audit) != {
        "schema_version", "instance_id", "interactions", "flagged_interaction_ids"
    }:
        raise SubmissionError("audit.json top-level schema mismatch")
    if audit["schema_version"] != "local-noise-audit/v1" or audit["instance_id"] != instance["instance_id"]:
        raise SubmissionError("audit identity or schema mismatch")
    records = audit["interactions"]
    if not isinstance(records, list) or len(records) != len(instance["_validation"]):
        raise SubmissionError("audit interaction inventory mismatch")
    ranks: set[int] = set()
    for actual, expected in zip(records, instance["_validation"]):
        if not isinstance(actual, dict) or set(actual) != {
            "interaction_id", "predicted_probability", "z_score", "absolute_z", "rank"
        }:
            raise SubmissionError("audit interaction schema mismatch")
        if actual["interaction_id"] != expected["interaction_id"]:
            raise SubmissionError("audit interaction identity/order mismatch")
        for key in ("predicted_probability", "z_score", "absolute_z"):
            _require_float(actual[key], f"{actual['interaction_id']}.{key}")
        probability = float(actual["predicted_probability"])
        if not 0.0 <= probability <= 1.0 or float(actual["absolute_z"]) < 0.0:
            raise SubmissionError("invalid audit numeric range")
        rank = _require_int(actual["rank"], f"{actual['interaction_id']}.rank", 1)
        ranks.add(rank)
    if ranks != set(range(1, len(records) + 1)):
        raise SubmissionError("audit ranks must be a permutation of 1..M")
    flagged = audit["flagged_interaction_ids"]
    known_ids = {row["interaction_id"] for row in instance["_validation"]}
    if (
        not isinstance(flagged, list)
        or len(flagged) != instance["audit_top_k"]
        or len(set(flagged)) != len(flagged)
        or any(item not in known_ids for item in flagged)
    ):
        raise SubmissionError("flagged_interaction_ids is invalid")

    diagnostics = load_json(output_dir / "diagnostics.json", OUTPUT_LIMITS["diagnostics.json"])
    expected_diag_keys = {
        "schema_version", "instance_id", "factor_max_normalization_error",
        "weighted_clique_tv_to_smoothed_counts", "max_raw_separator_tv",
        "max_model_separator_tv", "query_count", "interaction_count",
    }
    if not isinstance(diagnostics, dict) or set(diagnostics) != expected_diag_keys:
        raise SubmissionError("diagnostics schema mismatch")
    if diagnostics["schema_version"] != "local-noise-diagnostics/v1" or diagnostics["instance_id"] != instance["instance_id"]:
        raise SubmissionError("diagnostics identity or schema mismatch")
    for key in expected_diag_keys - {"schema_version", "instance_id", "query_count", "interaction_count"}:
        value = _require_float(diagnostics[key], key)
        if value < 0.0:
            raise SubmissionError(f"{key} must be nonnegative")
    if diagnostics["query_count"] != len(instance["_queries"]) or diagnostics["interaction_count"] != len(instance["_validation"]):
        raise SubmissionError("diagnostic counts mismatch")
    if type(diagnostics["query_count"]) is not int or type(diagnostics["interaction_count"]) is not int:
        raise SubmissionError("diagnostic counts must be integers")
    return {"model": model, "queries": parsed_queries, "audit": audit, "diagnostics": diagnostics}


def normalized_error(actual: np.ndarray, expected: np.ndarray, absolute: float, relative: float) -> float:
    scale = absolute + relative * np.abs(expected)
    ratio = np.abs(actual - expected) / scale
    return float(np.sqrt(np.mean(np.minimum(ratio, 1.0e8) ** 2)))


def linear_score(error: float, excellent: float, minimum: float) -> float:
    if error <= excellent:
        return 1.0
    if error >= minimum:
        return 0.0
    return float((minimum - error) / (minimum - excellent))


def average_precision(ranked_ids: list[str], positive_ids: set[str]) -> float:
    if not positive_ids:
        return 1.0
    hits = 0
    total = 0.0
    for rank, identifier in enumerate(ranked_ids, start=1):
        if identifier in positive_ids:
            hits += 1
            total += hits / rank
    return total / len(positive_ids)
