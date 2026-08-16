#!/usr/bin/env python3
"""Public structural checks for a source submission or one solve output."""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
from pathlib import Path
from typing import Any


OUTPUT_NAMES = {"model.json", "query_results.jsonl", "audit.json", "diagnostics.json"}
LIMITS = {"model.json": 1_500_000, "query_results.jsonl": 500_000, "audit.json": 500_000, "diagnostics.json": 64_000}


class ValidationError(ValueError):
    pass


def lexical_absolute(path: Path) -> Path:
    """Make a CLI path absolute without dereferencing its final link."""
    return Path(os.path.abspath(os.fspath(path)))


def real_directory(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValidationError(f"{label} directory is unreadable") from exc
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISDIR(info.st_mode):
        raise ValidationError(f"{label} must be a real directory")


def regular(path: Path, limit: int) -> None:
    info = path.lstat()
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
        raise ValidationError(f"not a regular unlinked file: {path.name}")
    if info.st_size > limit:
        raise ValidationError(f"file exceeds public limit: {path.name}")


def reject_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON token: {token}")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant, object_pairs_hook=unique_object)


def read_jsonl(path: Path) -> list[Any]:
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            raise ValidationError(f"blank JSONL line {number}")
        result.append(json.loads(line, parse_constant=reject_constant, object_pairs_hook=unique_object))
    return result


def finite_number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(float(value))


def project(scope: list[str], index: int, target: list[str]) -> int:
    positions = {variable: position for position, variable in enumerate(scope)}
    return sum(((index >> positions[variable]) & 1) << j for j, variable in enumerate(target))


def validate_input_contract(input_dir: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected_bounds = {
        "maximum_variables": 96,
        "maximum_clique_size": 7,
        "maximum_queries": 64,
        "maximum_validation_interactions": 64,
    }
    variables = manifest.get("variable_ids")
    cliques = manifest.get("cliques")
    if (
        manifest.get("schema_version") != "local-noise-input/v1"
        or type(manifest.get("variable_count")) is not int
        or not 1 <= manifest["variable_count"] <= 96
        or not isinstance(variables, list)
        or len(variables) != manifest["variable_count"]
        or len(set(variables)) != len(variables)
        or not finite_number(manifest.get("smoothing_pseudocount"))
        or float(manifest["smoothing_pseudocount"]) <= 0.0
        or manifest.get("declared_bounds") != expected_bounds
        or not isinstance(cliques, list)
        or not 1 <= len(cliques) <= 48
    ):
        raise ValidationError("input manifest violates the public bounds or invariants")
    clique_by_id = {}
    for clique in cliques:
        if not isinstance(clique, dict) or set(clique) != {
            "clique_id", "parent_id", "variables", "separator_variables", "new_variables"
        }:
            raise ValidationError("clique schema mismatch")
        cid = clique["clique_id"]
        scope = clique["variables"]
        if (
            not isinstance(cid, str) or not cid or cid in clique_by_id
            or not isinstance(scope, list) or not 1 <= len(scope) <= 7
            or len(set(scope)) != len(scope) or any(variable not in variables for variable in scope)
        ):
            raise ValidationError("invalid clique identity or scope")
        clique_by_id[cid] = clique
    counts_doc = read_json(input_dir / manifest["counts_file"])
    tables = counts_doc.get("tables") if isinstance(counts_doc, dict) else None
    if not isinstance(tables, list) or len(tables) != len(cliques):
        raise ValidationError("count table inventory mismatch")
    seen = set()
    for table in tables:
        if not isinstance(table, dict) or set(table) != {"clique_id", "shots", "counts"}:
            raise ValidationError("count table schema mismatch")
        cid = table["clique_id"]
        if cid not in clique_by_id or cid in seen:
            raise ValidationError("count table IDs must be known and one-to-one")
        seen.add(cid)
        shots, counts = table["shots"], table["counts"]
        if (
            type(shots) is not int or shots <= 0 or not isinstance(counts, list)
            or len(counts) != 1 << len(clique_by_id[cid]["variables"])
            or any(type(value) is not int or value < 0 for value in counts)
            or sum(counts) != shots
        ):
            raise ValidationError("invalid count values or total")
    queries = read_jsonl(input_dir / manifest["queries_file"])
    if len(queries) > 64:
        raise ValidationError("too many queries")
    query_ids = set()
    for query in queries:
        if not isinstance(query, dict) or set(query) != {"query_id", "assignment"}:
            raise ValidationError("query schema mismatch")
        qid, assignment = query["query_id"], query["assignment"]
        if (
            not isinstance(qid, str) or not qid or qid in query_ids
            or not isinstance(assignment, dict) or len(assignment) > 20
            or any(variable not in variables or type(value) is not int or value not in {0, 1} for variable, value in assignment.items())
        ):
            raise ValidationError("invalid query identity or assignment")
        query_ids.add(qid)
    validation = read_jsonl(input_dir / manifest["validation_file"])
    if len(validation) > 64:
        raise ValidationError("too many validation interactions")
    interaction_ids = set()
    for row in validation:
        if not isinstance(row, dict) or set(row) != {"interaction_id", "variables", "parity", "shots", "successes"}:
            raise ValidationError("validation schema mismatch")
        iid, scope = row["interaction_id"], row["variables"]
        if (
            not isinstance(iid, str) or not iid or iid in interaction_ids
            or not isinstance(scope, list) or not 1 <= len(scope) <= 7
            or len(set(scope)) != len(scope) or any(variable not in variables for variable in scope)
            or type(row["parity"]) is not int or row["parity"] not in {0, 1}
            or type(row["shots"]) is not int or row["shots"] <= 0
            or type(row["successes"]) is not int or not 0 <= row["successes"] <= row["shots"]
        ):
            raise ValidationError("invalid validation identity, scope, or counts")
        interaction_ids.add(iid)
    top_k = manifest.get("audit_top_k")
    if type(top_k) is not int or not 0 <= top_k <= len(validation):
        raise ValidationError("audit_top_k must be an integer in [0,M]")
    return queries, validation


def check_source(submission: Path) -> dict[str, Any]:
    real_directory(submission, "submission")
    entries = list(submission.iterdir())
    if {entry.name for entry in entries} != {"solution.py"}:
        raise ValidationError("submission directory must contain exactly solution.py")
    regular(submission / "solution.py", 512_000)
    compile((submission / "solution.py").read_text(encoding="utf-8"), "solution.py", "exec")
    return {"source": "structurally valid"}


def check_output(input_dir: Path, output_dir: Path) -> dict[str, Any]:
    real_directory(input_dir, "input")
    real_directory(output_dir, "output")
    entries = list(output_dir.iterdir())
    if {entry.name for entry in entries} != OUTPUT_NAMES:
        raise ValidationError("output inventory mismatch")
    for name in OUTPUT_NAMES:
        regular(output_dir / name, LIMITS[name])
    manifest = read_json(input_dir / "manifest.json")
    queries, validation = validate_input_contract(input_dir, manifest)
    model = read_json(output_dir / "model.json")
    if set(model) != {"schema_version", "instance_id", "root_clique_id", "factors"}:
        raise ValidationError("model top-level fields mismatch")
    if model["schema_version"] != "rooted-junction-model/v1" or model["instance_id"] != manifest["instance_id"]:
        raise ValidationError("model identity/schema mismatch")
    if model["root_clique_id"] != manifest["root_clique_id"] or len(model["factors"]) != len(manifest["cliques"]):
        raise ValidationError("model layout mismatch")
    factor_keys = {"clique_id", "parent_id", "variables", "separator_variables", "new_variables", "probabilities"}
    max_error = 0.0
    for factor, clique in zip(model["factors"], manifest["cliques"]):
        if not isinstance(factor, dict) or set(factor) != factor_keys:
            raise ValidationError("factor fields mismatch")
        for key in factor_keys - {"probabilities"}:
            if factor[key] != clique[key]:
                raise ValidationError(f"factor metadata mismatch: {clique['clique_id']}.{key}")
        values = factor["probabilities"]
        if not isinstance(values, list) or len(values) != 1 << len(clique["variables"]):
            raise ValidationError("factor table length mismatch")
        sums = [0.0] * (1 << len(clique["separator_variables"]))
        for index, value in enumerate(values):
            if not finite_number(value) or not 0.0 <= float(value) <= 1.0:
                raise ValidationError("invalid factor probability")
            sums[project(clique["variables"], index, clique["separator_variables"])] += float(value)
        max_error = max(max_error, max(abs(total - 1.0) for total in sums))
    if max_error > 2.0e-7:
        raise ValidationError("factor normalization exceeds 2e-7")
    query_results = read_jsonl(output_dir / "query_results.jsonl")
    if len(queries) != len(query_results):
        raise ValidationError("query result count mismatch")
    for expected, actual in zip(queries, query_results):
        if set(actual) != {"query_id", "probability"} or actual["query_id"] != expected["query_id"]:
            raise ValidationError("query result schema/order mismatch")
        if not finite_number(actual["probability"]) or not 0.0 <= float(actual["probability"]) <= 1.0:
            raise ValidationError("invalid query probability")
    audit = read_json(output_dir / "audit.json")
    if set(audit) != {"schema_version", "instance_id", "interactions", "flagged_interaction_ids"}:
        raise ValidationError("audit top-level fields mismatch")
    if audit["schema_version"] != "local-noise-audit/v1" or audit["instance_id"] != manifest["instance_id"]:
        raise ValidationError("audit identity/schema mismatch")
    if not isinstance(audit["interactions"], list) or len(audit["interactions"]) != len(validation):
        raise ValidationError("audit inventory mismatch")
    ranks = set()
    known_interactions = {row["interaction_id"] for row in validation}
    for expected, actual in zip(validation, audit["interactions"]):
        if not isinstance(actual, dict) or set(actual) != {
            "interaction_id", "predicted_probability", "z_score", "absolute_z", "rank"
        } or actual["interaction_id"] != expected["interaction_id"]:
            raise ValidationError("audit interaction schema/order mismatch")
        if (
            not finite_number(actual["predicted_probability"])
            or not 0.0 <= float(actual["predicted_probability"]) <= 1.0
            or not finite_number(actual["z_score"])
            or not finite_number(actual["absolute_z"])
            or float(actual["absolute_z"]) < 0.0
            or type(actual["rank"]) is not int
        ):
            raise ValidationError("invalid audit numeric field")
        if float(actual["absolute_z"]) != abs(float(actual["z_score"])):
            raise ValidationError("absolute_z must equal abs(z_score)")
        ranks.add(actual["rank"])
    if ranks != set(range(1, len(validation) + 1)):
        raise ValidationError("audit ranks must be a permutation of 1..M")
    flagged = audit["flagged_interaction_ids"]
    if (
        not isinstance(flagged, list) or len(flagged) != manifest["audit_top_k"]
        or len(set(flagged)) != len(flagged) or any(item not in known_interactions for item in flagged)
    ):
        raise ValidationError("invalid flagged_interaction_ids")
    expected_order = sorted(
        audit["interactions"],
        key=lambda row: (-float(row["absolute_z"]), row["interaction_id"]),
    )
    if [row["rank"] for row in expected_order] != list(range(1, len(validation) + 1)):
        raise ValidationError("audit ranks violate the public ordering rule")
    if flagged != [row["interaction_id"] for row in expected_order[: manifest["audit_top_k"]]]:
        raise ValidationError("flagged_interaction_ids must be the first audit_top_k ranked IDs")
    diagnostics = read_json(output_dir / "diagnostics.json")
    diagnostic_keys = {
        "schema_version", "instance_id", "factor_max_normalization_error",
        "weighted_clique_tv_to_smoothed_counts", "max_raw_separator_tv",
        "max_model_separator_tv", "query_count", "interaction_count",
    }
    if not isinstance(diagnostics, dict) or set(diagnostics) != diagnostic_keys:
        raise ValidationError("diagnostics fields mismatch")
    if diagnostics.get("schema_version") != "local-noise-diagnostics/v1" or diagnostics.get("instance_id") != manifest["instance_id"]:
        raise ValidationError("diagnostics identity/schema mismatch")
    for key in diagnostic_keys - {"schema_version", "instance_id", "query_count", "interaction_count"}:
        if not finite_number(diagnostics[key]) or float(diagnostics[key]) < 0.0:
            raise ValidationError("invalid diagnostic numeric field")
    if (
        type(diagnostics["query_count"]) is not int
        or diagnostics["query_count"] != len(queries)
        or type(diagnostics["interaction_count"]) is not int
        or diagnostics["interaction_count"] != len(validation)
    ):
        raise ValidationError("diagnostic inventory counts mismatch")
    return {"output": "structurally valid", "maximum_factor_normalization_error": max_error}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.submission is not None and args.input is None and args.output is None:
            result = check_source(lexical_absolute(args.submission))
        elif args.submission is None and args.input is not None and args.output is not None:
            result = check_output(lexical_absolute(args.input), lexical_absolute(args.output))
        else:
            raise ValidationError("use --submission DIR or --input DIR --output DIR")
        print(json.dumps({"passed": True, **result}, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"passed": False, "error": f"{type(exc).__name__}: {exc}"}, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
