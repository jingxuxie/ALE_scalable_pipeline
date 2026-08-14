"""Trusted compiler for bounded, declarative research-task protocols.

The generic family is intentionally a small protocol virtual machine, not a
code generator.  A protocol may select only registered data generators,
reference solvers, output types, metrics, and gates.  All executable files in
the resulting inventory are fixed strings owned by this module; protocol
values are validated data and are never imported, evaluated, or passed to a
shell.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import random
import re
import textwrap
from typing import Any

import numpy as np

from paper2ale.difficulty import (
    difficulty_profile_index,
    make_consumption_manifest,
    resolve_task_difficulty,
)
from paper2ale.packaging import BuildFile


AGENT = "agent"
EVALUATOR = "evaluator"
AUTHOR = "author"

PROTOCOL_SCHEMA_VERSION = "paper2ale.generic-protocol/v1"
SUPPORTED_TEMPLATES = (
    "numeric-affine-v1",
    "table-filter-sort-v1",
    "json-group-aggregate-v1",
)

GENERIC_CAPABILITIES: Mapping[str, tuple[str, ...]] = {
    "instance_generators": (
        "uniform_numeric_matrix",
        "typed_record_table",
        "grouped_integer_records",
    ),
    "reference_solvers": (
        "affine_transform",
        "filter_sort_project",
        "grouped_aggregate",
    ),
    "output_contracts": (
        "numeric_predictions_json",
        "table_rows_json",
        "json_object",
    ),
    "metrics": (
        "numeric_rmse",
        "numeric_max_abs",
        "table_exact",
        "json_exact",
    ),
    "gates": (
        "strict_json",
        "max_bytes",
        "shape_match",
        "finite_numbers",
        "query_id_match",
        "row_schema_match",
        "required_keys",
    ),
}

_TEMPLATE_GENERATOR = {
    "numeric-affine-v1": "uniform_numeric_matrix",
    "table-filter-sort-v1": "typed_record_table",
    "json-group-aggregate-v1": "grouped_integer_records",
}
_TEMPLATE_SOLVER = {
    "numeric-affine-v1": "affine_transform",
    "table-filter-sort-v1": "filter_sort_project",
    "json-group-aggregate-v1": "grouped_aggregate",
}
_TEMPLATE_OUTPUT = {
    "numeric-affine-v1": "numeric_predictions_json",
    "table-filter-sort-v1": "table_rows_json",
    "json-group-aggregate-v1": "json_object",
}
_TEMPLATE_METRICS = {
    "numeric-affine-v1": frozenset({"numeric_rmse", "numeric_max_abs"}),
    "table-filter-sort-v1": frozenset({"table_exact"}),
    "json-group-aggregate-v1": frozenset({"json_exact"}),
}
_TEMPLATE_REQUIRED_GATES = {
    "numeric-affine-v1": frozenset(
        {"strict_json", "max_bytes", "shape_match", "finite_numbers", "query_id_match"}
    ),
    "table-filter-sort-v1": frozenset(
        {"strict_json", "max_bytes", "row_schema_match"}
    ),
    "json-group-aggregate-v1": frozenset(
        {"strict_json", "max_bytes", "required_keys"}
    ),
}

# These are semantic controls, not merely values that happen to be present in
# a resolved profile. Conditional controls are included in the per-build audit
# only when the protocol makes them capable of changing task behavior.
TEMPLATE_DIFFICULTY_CONTROLS: Mapping[str, Mapping[str, Any]] = {
    "numeric-affine-v1": {
        "generator": (
            "instance_count",
            "input_complexity_scale",
            "masked_fraction",
            "constraint_count",
        ),
        "evaluator": (
            "hidden_case_count",
            "threshold_scale",
            "rollout_horizon_scale",
            "adversarial_case_count",
        ),
        "conditional": {
            "generator.noise_scale": "generator.public_noise_std > 0",
            "evaluator.required_pass_fraction": "at least two metrics are configured",
        },
    },
    "table-filter-sort-v1": {
        "generator": (
            "instance_count",
            "input_complexity_scale",
            "constraint_count",
        ),
        "evaluator": ("hidden_case_count", "adversarial_case_count"),
        "conditional": {},
    },
    "json-group-aggregate-v1": {
        "generator": (
            "instance_count",
            "input_complexity_scale",
            "constraint_count",
        ),
        "evaluator": ("hidden_case_count", "adversarial_case_count"),
        "conditional": {},
    },
}

_DIFFICULTY_EFFECTS: Mapping[str, str] = {
    "generator.instance_count": "number of independently seeded packaged instances",
    "generator.input_complexity_scale": "number of generated query or record cases",
    "generator.noise_scale": "standard deviation of affine public-label noise",
    "generator.masked_fraction": "number of affine worked examples disclosed",
    "generator.constraint_count": "number of generated nuisance context fields",
    "evaluator.hidden_case_count": "number of generated hidden query or record cases",
    "evaluator.threshold_scale": "numeric metric acceptance thresholds",
    "evaluator.rollout_horizon_scale": "affine hidden input range",
    "evaluator.required_pass_fraction": "fraction of distinct numeric metrics required",
    "evaluator.adversarial_case_count": "number of deterministic boundary cases",
}

MAX_PROTOCOL_BYTES = 64 * 1024
MAX_SUBMISSION_BYTES = 1024 * 1024
MAX_EFFECTIVE_RECORDS = 10_000
MAX_DECOY_FIELDS = 16
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_TASK_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9_-])?$")


class ProtocolValidationError(ValueError):
    """Raised when a declarative protocol leaves the trusted capability set."""


def _error(path: str, message: str) -> ProtocolValidationError:
    return ProtocolValidationError(f"invalid generic protocol at {path}: {message}")


def _object(
    value: Any,
    path: str,
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(path, "must be an object")
    allowed = set(required) | set(optional)
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _error(path, f"unknown field {unknown[0]!r}")
    missing = [key for key in required if key not in value]
    if missing:
        raise _error(path, f"missing required field {missing[0]!r}")
    return value


def _identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise _error(path, "must match ^[A-Za-z][A-Za-z0-9_]{0,63}$")
    return value


def _string(value: Any, path: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _error(path, f"must be a nonempty string of at most {maximum} characters")
    if any(ord(character) < 32 for character in value):
        raise _error(path, "must not contain control characters")
    return value


def _number(
    value: Any,
    path: str,
    *,
    minimum: float = -1_000_000.0,
    maximum: float = 1_000_000.0,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(path, "must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise _error(path, "must be finite")
    if result < minimum or result > maximum:
        raise _error(path, f"must be between {minimum:g} and {maximum:g}")
    return result


def _integer(
    value: Any,
    path: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(path, "must be an integer")
    if value < minimum or value > maximum:
        raise _error(path, f"must be between {minimum} and {maximum}")
    return value


def _enum(value: Any, path: str, choices: Sequence[str]) -> str:
    if value not in choices:
        raise _error(path, f"must be one of {', '.join(choices)}")
    return str(value)


def _canonical_copy(value: Any) -> Any:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise _error("/", f"must be strict JSON data: {error}") from error
    if len(encoded.encode("utf-8")) > MAX_PROTOCOL_BYTES:
        raise _error("/", f"encoded protocol exceeds {MAX_PROTOCOL_BYTES} bytes")
    return json.loads(encoded)


def _validate_output(value: Any, template_id: str) -> dict[str, Any]:
    output = _object(value, "/output", required=("primitive",), optional=("filename",))
    primitive = _enum(
        output["primitive"],
        "/output/primitive",
        (_TEMPLATE_OUTPUT[template_id],),
    )
    filename = output.get("filename", "submission.json")
    if filename != "submission.json":
        raise _error(
            "/output/filename",
            "the generic family fixes the only participant path to submission.json",
        )
    return {"primitive": primitive, "filename": filename}


def _validate_evaluation(value: Any, template_id: str) -> dict[str, Any]:
    evaluation = _object(
        value,
        "/evaluation",
        required=("metrics", "gates"),
        optional=("max_submission_bytes", "required_pass_fraction"),
    )
    raw_metrics = evaluation["metrics"]
    if not isinstance(raw_metrics, list) or not 1 <= len(raw_metrics) <= 8:
        raise _error("/evaluation/metrics", "must contain between 1 and 8 metrics")
    metrics: list[dict[str, Any]] = []
    metric_ids: set[str] = set()
    for index, raw in enumerate(raw_metrics):
        path = f"/evaluation/metrics/{index}"
        metric = _object(
            raw,
            path,
            required=("id", "primitive", "threshold", "weight"),
        )
        metric_id = _identifier(metric["id"], f"{path}/id")
        if metric_id in metric_ids:
            raise _error(f"{path}/id", "metric IDs must be unique")
        metric_ids.add(metric_id)
        primitive = _enum(
            metric["primitive"],
            f"{path}/primitive",
            tuple(sorted(_TEMPLATE_METRICS[template_id])),
        )
        if primitive.startswith("numeric_"):
            threshold = _number(
                metric["threshold"],
                f"{path}/threshold",
                minimum=1e-12,
                maximum=1_000_000,
            )
        else:
            threshold = _number(
                metric["threshold"],
                f"{path}/threshold",
                minimum=0,
                maximum=1,
            )
        weight = _number(
            metric["weight"], f"{path}/weight", minimum=1e-12, maximum=100
        )
        metrics.append(
            {
                "id": metric_id,
                "primitive": primitive,
                "threshold": threshold,
                "weight": weight,
            }
        )
    raw_gates = evaluation["gates"]
    if not isinstance(raw_gates, list) or not raw_gates:
        raise _error("/evaluation/gates", "must be a nonempty array")
    gates = [
        _enum(
            gate,
            f"/evaluation/gates/{index}",
            GENERIC_CAPABILITIES["gates"],
        )
        for index, gate in enumerate(raw_gates)
    ]
    if len(set(gates)) != len(gates):
        raise _error("/evaluation/gates", "gate IDs must be unique")
    missing = sorted(_TEMPLATE_REQUIRED_GATES[template_id] - set(gates))
    if missing:
        raise _error("/evaluation/gates", f"required gate {missing[0]!r} is missing")
    maximum_bytes = _integer(
        evaluation.get("max_submission_bytes", 256 * 1024),
        "/evaluation/max_submission_bytes",
        minimum=128,
        maximum=MAX_SUBMISSION_BYTES,
    )
    required_fraction = _number(
        evaluation.get("required_pass_fraction", 1.0),
        "/evaluation/required_pass_fraction",
        minimum=0.5,
        maximum=1.0,
    )
    return {
        "metrics": metrics,
        "gates": gates,
        "max_submission_bytes": maximum_bytes,
        "required_pass_fraction": required_fraction,
    }


def _validate_numeric_generator(value: Any) -> dict[str, Any]:
    generator = _object(
        value,
        "/generator",
        required=(
            "primitive",
            "input_dimension",
            "output_dimension",
            "query_count",
            "public_example_count",
            "low",
            "high",
        ),
        optional=("decimals", "public_noise_std"),
    )
    primitive = _enum(
        generator["primitive"],
        "/generator/primitive",
        ("uniform_numeric_matrix",),
    )
    input_dimension = _integer(
        generator["input_dimension"], "/generator/input_dimension", minimum=1, maximum=16
    )
    output_dimension = _integer(
        generator["output_dimension"],
        "/generator/output_dimension",
        minimum=1,
        maximum=16,
    )
    query_count = _integer(
        generator["query_count"], "/generator/query_count", minimum=1, maximum=2048
    )
    public_example_count = _integer(
        generator["public_example_count"],
        "/generator/public_example_count",
        minimum=input_dimension + 1,
        maximum=512,
    )
    low = _number(generator["low"], "/generator/low")
    high = _number(generator["high"], "/generator/high")
    if high <= low:
        raise _error("/generator/high", "must be greater than low")
    decimals = _integer(
        generator.get("decimals", 6), "/generator/decimals", minimum=0, maximum=10
    )
    public_noise_std = _number(
        generator.get("public_noise_std", 0.0),
        "/generator/public_noise_std",
        minimum=0,
        maximum=100,
    )
    return {
        "primitive": primitive,
        "input_dimension": input_dimension,
        "output_dimension": output_dimension,
        "query_count": query_count,
        "public_example_count": public_example_count,
        "low": low,
        "high": high,
        "decimals": decimals,
        "public_noise_std": public_noise_std,
    }


def _validate_numeric_solver(
    value: Any, input_dimension: int, output_dimension: int
) -> dict[str, Any]:
    solver = _object(
        value,
        "/reference_solver",
        required=("primitive", "weights", "bias"),
    )
    primitive = _enum(
        solver["primitive"], "/reference_solver/primitive", ("affine_transform",)
    )
    weights = solver["weights"]
    if not isinstance(weights, list) or len(weights) != output_dimension:
        raise _error(
            "/reference_solver/weights",
            f"must contain {output_dimension} output rows",
        )
    normalized_weights: list[list[float]] = []
    for row_index, row in enumerate(weights):
        if not isinstance(row, list) or len(row) != input_dimension:
            raise _error(
                f"/reference_solver/weights/{row_index}",
                f"must contain {input_dimension} coefficients",
            )
        normalized_weights.append(
            [
                _number(item, f"/reference_solver/weights/{row_index}/{column_index}")
                for column_index, item in enumerate(row)
            ]
        )
    bias = solver["bias"]
    if not isinstance(bias, list) or len(bias) != output_dimension:
        raise _error(
            "/reference_solver/bias", f"must contain {output_dimension} values"
        )
    normalized_bias = [
        _number(item, f"/reference_solver/bias/{index}")
        for index, item in enumerate(bias)
    ]
    return {"primitive": primitive, "weights": normalized_weights, "bias": normalized_bias}


def _validate_column(value: Any, index: int) -> dict[str, Any]:
    path = f"/generator/columns/{index}"
    if not isinstance(value, Mapping):
        raise _error(path, "must be an object")
    primitive = value.get("primitive")
    common = ("name", "primitive")
    if primitive == "sequence_integer":
        column = _object(value, path, required=common + ("start", "step"))
        result = {
            "name": _identifier(column["name"], f"{path}/name"),
            "primitive": primitive,
            "start": _integer(column["start"], f"{path}/start", minimum=-1_000_000, maximum=1_000_000),
            "step": _integer(column["step"], f"{path}/step", minimum=-1_000_000, maximum=1_000_000),
        }
        if result["step"] == 0:
            raise _error(f"{path}/step", "must be nonzero")
        return result
    if primitive == "uniform_integer":
        column = _object(value, path, required=common + ("low", "high"))
        low = _integer(column["low"], f"{path}/low", minimum=-1_000_000, maximum=1_000_000)
        high = _integer(column["high"], f"{path}/high", minimum=-1_000_000, maximum=1_000_000)
        if high < low:
            raise _error(f"{path}/high", "must be greater than or equal to low")
        return {"name": _identifier(column["name"], f"{path}/name"), "primitive": primitive, "low": low, "high": high}
    if primitive == "uniform_number":
        column = _object(
            value, path, required=common + ("low", "high"), optional=("decimals",)
        )
        low = _number(column["low"], f"{path}/low")
        high = _number(column["high"], f"{path}/high")
        if high <= low:
            raise _error(f"{path}/high", "must be greater than low")
        return {
            "name": _identifier(column["name"], f"{path}/name"),
            "primitive": primitive,
            "low": low,
            "high": high,
            "decimals": _integer(column.get("decimals", 6), f"{path}/decimals", minimum=0, maximum=10),
        }
    if primitive == "choice":
        column = _object(value, path, required=common + ("values",))
        choices = column["values"]
        if not isinstance(choices, list) or not 1 <= len(choices) <= 32:
            raise _error(f"{path}/values", "must contain between 1 and 32 strings")
        normalized = [
            _string(item, f"{path}/values/{choice_index}", maximum=64)
            for choice_index, item in enumerate(choices)
        ]
        if len(set(normalized)) != len(normalized):
            raise _error(f"{path}/values", "choice values must be unique")
        return {"name": _identifier(column["name"], f"{path}/name"), "primitive": primitive, "values": normalized}
    raise _error(
        f"{path}/primitive",
        "must be one of sequence_integer, uniform_integer, uniform_number, choice",
    )


def _validate_table_generator(value: Any) -> dict[str, Any]:
    generator = _object(
        value,
        "/generator",
        required=("primitive", "row_count", "columns"),
    )
    primitive = _enum(
        generator["primitive"], "/generator/primitive", ("typed_record_table",)
    )
    row_count = _integer(
        generator["row_count"], "/generator/row_count", minimum=1, maximum=2048
    )
    raw_columns = generator["columns"]
    if not isinstance(raw_columns, list) or not 1 <= len(raw_columns) <= 16:
        raise _error("/generator/columns", "must contain between 1 and 16 columns")
    columns = [_validate_column(column, index) for index, column in enumerate(raw_columns)]
    names = [column["name"] for column in columns]
    if len(set(names)) != len(names):
        raise _error("/generator/columns", "column names must be unique")
    return {"primitive": primitive, "row_count": row_count, "columns": columns}


def _validate_table_solver(value: Any, columns: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    solver = _object(
        value,
        "/reference_solver",
        required=("primitive", "filter", "sort", "project"),
    )
    primitive = _enum(
        solver["primitive"],
        "/reference_solver/primitive",
        ("filter_sort_project",),
    )
    by_name = {str(column["name"]): column for column in columns}
    filter_spec = _object(
        solver["filter"],
        "/reference_solver/filter",
        required=("column", "operator", "value"),
    )
    filter_column = _identifier(
        filter_spec["column"], "/reference_solver/filter/column"
    )
    if filter_column not in by_name:
        raise _error("/reference_solver/filter/column", "unknown generated column")
    operator = _enum(
        filter_spec["operator"],
        "/reference_solver/filter/operator",
        ("eq", "ne", "lt", "lte", "gt", "gte"),
    )
    column = by_name[filter_column]
    if column["primitive"] == "choice":
        if operator not in {"eq", "ne"}:
            raise _error(
                "/reference_solver/filter/operator",
                "choice columns support only eq and ne",
            )
        filter_value: Any = _string(
            filter_spec["value"], "/reference_solver/filter/value", maximum=64
        )
    else:
        filter_value = _number(filter_spec["value"], "/reference_solver/filter/value")

    raw_sort = solver["sort"]
    if not isinstance(raw_sort, list) or not 1 <= len(raw_sort) <= 3:
        raise _error("/reference_solver/sort", "must contain between 1 and 3 keys")
    sort: list[dict[str, Any]] = []
    sort_names: set[str] = set()
    for index, raw in enumerate(raw_sort):
        path = f"/reference_solver/sort/{index}"
        item = _object(raw, path, required=("column", "direction"))
        name = _identifier(item["column"], f"{path}/column")
        if name not in by_name:
            raise _error(f"{path}/column", "unknown generated column")
        if name in sort_names:
            raise _error(f"{path}/column", "sort columns must be unique")
        sort_names.add(name)
        sort.append(
            {
                "column": name,
                "direction": _enum(item["direction"], f"{path}/direction", ("ascending", "descending")),
            }
        )
    raw_project = solver["project"]
    if not isinstance(raw_project, list) or not raw_project:
        raise _error("/reference_solver/project", "must be a nonempty array")
    project = [
        _identifier(item, f"/reference_solver/project/{index}")
        for index, item in enumerate(raw_project)
    ]
    if len(set(project)) != len(project):
        raise _error("/reference_solver/project", "projected columns must be unique")
    unknown = [name for name in project if name not in by_name]
    if unknown:
        raise _error("/reference_solver/project", f"unknown generated column {unknown[0]!r}")
    return {
        "primitive": primitive,
        "filter": {"column": filter_column, "operator": operator, "value": filter_value},
        "sort": sort,
        "project": project,
    }


def _validate_json_generator(value: Any) -> dict[str, Any]:
    generator = _object(
        value,
        "/generator",
        required=(
            "primitive",
            "record_count",
            "groups",
            "group_field",
            "value_field",
            "value_low",
            "value_high",
        ),
    )
    primitive = _enum(
        generator["primitive"],
        "/generator/primitive",
        ("grouped_integer_records",),
    )
    record_count = _integer(
        generator["record_count"], "/generator/record_count", minimum=1, maximum=2048
    )
    raw_groups = generator["groups"]
    if not isinstance(raw_groups, list) or not 1 <= len(raw_groups) <= 32:
        raise _error("/generator/groups", "must contain between 1 and 32 group names")
    groups = [
        _string(item, f"/generator/groups/{index}", maximum=64)
        for index, item in enumerate(raw_groups)
    ]
    if len(set(groups)) != len(groups):
        raise _error("/generator/groups", "group names must be unique")
    group_field = _identifier(generator["group_field"], "/generator/group_field")
    value_field = _identifier(generator["value_field"], "/generator/value_field")
    if group_field == value_field:
        raise _error("/generator/value_field", "must differ from group_field")
    value_low = _integer(
        generator["value_low"], "/generator/value_low", minimum=-1_000_000, maximum=1_000_000
    )
    value_high = _integer(
        generator["value_high"], "/generator/value_high", minimum=-1_000_000, maximum=1_000_000
    )
    if value_high < value_low:
        raise _error("/generator/value_high", "must be greater than or equal to value_low")
    return {
        "primitive": primitive,
        "record_count": record_count,
        "groups": groups,
        "group_field": group_field,
        "value_field": value_field,
        "value_low": value_low,
        "value_high": value_high,
    }


def _validate_json_solver(value: Any, generator: Mapping[str, Any]) -> dict[str, Any]:
    solver = _object(
        value,
        "/reference_solver",
        required=("primitive", "operation", "group_field", "value_field"),
    )
    primitive = _enum(
        solver["primitive"],
        "/reference_solver/primitive",
        ("grouped_aggregate",),
    )
    operation = _enum(
        solver["operation"],
        "/reference_solver/operation",
        ("sum", "count", "min", "max"),
    )
    group_field = _identifier(solver["group_field"], "/reference_solver/group_field")
    value_field = _identifier(solver["value_field"], "/reference_solver/value_field")
    if group_field != generator["group_field"] or value_field != generator["value_field"]:
        raise _error(
            "/reference_solver",
            "group_field and value_field must exactly match the generator fields",
        )
    return {
        "primitive": primitive,
        "operation": operation,
        "group_field": group_field,
        "value_field": value_field,
    }


def validate_protocol(protocol: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate and return a canonical JSON copy of a trusted protocol.

    Unknown fields and primitive IDs are rejecting errors.  In particular,
    there is no protocol field for source code, imports, commands, modules,
    paths, URLs, environment variables, or shell fragments.
    """

    root = _object(
        protocol,
        "/",
        required=(
            "schema_version",
            "template_id",
            "generator",
            "reference_solver",
            "output",
            "evaluation",
        ),
    )
    if root["schema_version"] != PROTOCOL_SCHEMA_VERSION:
        raise _error(
            "/schema_version", f"must equal {PROTOCOL_SCHEMA_VERSION!r}"
        )
    template_id = _enum(root["template_id"], "/template_id", SUPPORTED_TEMPLATES)
    if template_id == "numeric-affine-v1":
        generator = _validate_numeric_generator(root["generator"])
        solver = _validate_numeric_solver(
            root["reference_solver"],
            generator["input_dimension"],
            generator["output_dimension"],
        )
    elif template_id == "table-filter-sort-v1":
        generator = _validate_table_generator(root["generator"])
        solver = _validate_table_solver(root["reference_solver"], generator["columns"])
    else:
        generator = _validate_json_generator(root["generator"])
        solver = _validate_json_solver(root["reference_solver"], generator)
    normalized = {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "template_id": template_id,
        "generator": generator,
        "reference_solver": solver,
        "output": _validate_output(root["output"], template_id),
        "evaluation": _validate_evaluation(root["evaluation"], template_id),
    }
    return _canonical_copy(normalized)


def protocol_json_schema() -> dict[str, Any]:
    """Return a self-contained provider-facing schema for generic protocols.

    JSON Schema expresses all structural, enum, and scalar bounds.  Relational
    invariants (matrix shapes, high greater than low, field references, and
    required gate membership) are repeated by :func:`validate_protocol`, which
    remains the authoritative admission boundary.
    """

    identifier = {"type": "string", "pattern": _IDENTIFIER.pattern}
    finite_number = {
        "type": "number",
        "minimum": -1_000_000,
        "maximum": 1_000_000,
    }

    def strict_object(required: Sequence[str], properties: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": list(required),
            "properties": dict(properties),
        }

    def output_schema(primitive: str) -> dict[str, Any]:
        return strict_object(
            ("primitive",),
            {
                "primitive": {"const": primitive},
                "filename": {"const": "submission.json"},
            },
        )

    def evaluation_schema(
        metric_ids: Sequence[str], required_gates: Sequence[str]
    ) -> dict[str, Any]:
        exact = all(not primitive.startswith("numeric_") for primitive in metric_ids)
        metric = strict_object(
            ("id", "primitive", "threshold", "weight"),
            {
                "id": identifier,
                "primitive": {"enum": list(metric_ids)},
                "threshold": (
                    {"type": "number", "minimum": 0, "maximum": 1}
                    if exact
                    else {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 1_000_000,
                    }
                ),
                "weight": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 100,
                },
            },
        )
        gates: dict[str, Any] = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"enum": list(GENERIC_CAPABILITIES["gates"])},
            "allOf": [
                {"contains": {"const": gate}, "minContains": 1}
                for gate in required_gates
            ],
        }
        return strict_object(
            ("metrics", "gates"),
            {
                "metrics": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": metric,
                },
                "gates": gates,
                "max_submission_bytes": {
                    "type": "integer",
                    "minimum": 128,
                    "maximum": MAX_SUBMISSION_BYTES,
                },
                "required_pass_fraction": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 1,
                },
            },
        )

    def root_schema(
        template_id: str,
        generator: Mapping[str, Any],
        solver: Mapping[str, Any],
    ) -> dict[str, Any]:
        return strict_object(
            (
                "schema_version",
                "template_id",
                "generator",
                "reference_solver",
                "output",
                "evaluation",
            ),
            {
                "schema_version": {"const": PROTOCOL_SCHEMA_VERSION},
                "template_id": {"const": template_id},
                "generator": generator,
                "reference_solver": solver,
                "output": output_schema(_TEMPLATE_OUTPUT[template_id]),
                "evaluation": evaluation_schema(
                    tuple(sorted(_TEMPLATE_METRICS[template_id])),
                    tuple(sorted(_TEMPLATE_REQUIRED_GATES[template_id])),
                ),
            },
        )

    numeric_generator = strict_object(
        (
            "primitive",
            "input_dimension",
            "output_dimension",
            "query_count",
            "public_example_count",
            "low",
            "high",
        ),
        {
            "primitive": {"const": "uniform_numeric_matrix"},
            "input_dimension": {"type": "integer", "minimum": 1, "maximum": 16},
            "output_dimension": {"type": "integer", "minimum": 1, "maximum": 16},
            "query_count": {"type": "integer", "minimum": 1, "maximum": 2048},
            "public_example_count": {
                "type": "integer",
                "minimum": 2,
                "maximum": 512,
            },
            "low": finite_number,
            "high": finite_number,
            "decimals": {"type": "integer", "minimum": 0, "maximum": 10},
            "public_noise_std": {"type": "number", "minimum": 0, "maximum": 100},
        },
    )
    numeric_solver = strict_object(
        ("primitive", "weights", "bias"),
        {
            "primitive": {"const": "affine_transform"},
            "weights": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 16,
                    "items": finite_number,
                },
            },
            "bias": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": finite_number,
            },
        },
    )

    table_columns = {
        "oneOf": [
            strict_object(
                ("name", "primitive", "start", "step"),
                {
                    "name": identifier,
                    "primitive": {"const": "sequence_integer"},
                    "start": {"type": "integer", "minimum": -1_000_000, "maximum": 1_000_000},
                    "step": {
                        "type": "integer",
                        "minimum": -1_000_000,
                        "maximum": 1_000_000,
                        "not": {"const": 0},
                    },
                },
            ),
            strict_object(
                ("name", "primitive", "low", "high"),
                {
                    "name": identifier,
                    "primitive": {"const": "uniform_integer"},
                    "low": {"type": "integer", "minimum": -1_000_000, "maximum": 1_000_000},
                    "high": {"type": "integer", "minimum": -1_000_000, "maximum": 1_000_000},
                },
            ),
            strict_object(
                ("name", "primitive", "low", "high"),
                {
                    "name": identifier,
                    "primitive": {"const": "uniform_number"},
                    "low": finite_number,
                    "high": finite_number,
                    "decimals": {"type": "integer", "minimum": 0, "maximum": 10},
                },
            ),
            strict_object(
                ("name", "primitive", "values"),
                {
                    "name": identifier,
                    "primitive": {"const": "choice"},
                    "values": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 64},
                    },
                },
            ),
        ]
    }
    table_generator = strict_object(
        ("primitive", "row_count", "columns"),
        {
            "primitive": {"const": "typed_record_table"},
            "row_count": {"type": "integer", "minimum": 1, "maximum": 2048},
            "columns": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": table_columns,
            },
        },
    )
    table_solver = strict_object(
        ("primitive", "filter", "sort", "project"),
        {
            "primitive": {"const": "filter_sort_project"},
            "filter": strict_object(
                ("column", "operator", "value"),
                {
                    "column": identifier,
                    "operator": {"enum": ["eq", "ne", "lt", "lte", "gt", "gte"]},
                    "value": {"oneOf": [finite_number, {"type": "string", "minLength": 1, "maxLength": 64}]},
                },
            ),
            "sort": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": strict_object(
                    ("column", "direction"),
                    {
                        "column": identifier,
                        "direction": {"enum": ["ascending", "descending"]},
                    },
                ),
            },
            "project": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "uniqueItems": True,
                "items": identifier,
            },
        },
    )

    json_generator = strict_object(
        (
            "primitive",
            "record_count",
            "groups",
            "group_field",
            "value_field",
            "value_low",
            "value_high",
        ),
        {
            "primitive": {"const": "grouped_integer_records"},
            "record_count": {"type": "integer", "minimum": 1, "maximum": 2048},
            "groups": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 64},
            },
            "group_field": identifier,
            "value_field": identifier,
            "value_low": {"type": "integer", "minimum": -1_000_000, "maximum": 1_000_000},
            "value_high": {"type": "integer", "minimum": -1_000_000, "maximum": 1_000_000},
        },
    )
    json_solver = strict_object(
        ("primitive", "operation", "group_field", "value_field"),
        {
            "primitive": {"const": "grouped_aggregate"},
            "operation": {"enum": ["sum", "count", "min", "max"]},
            "group_field": identifier,
            "value_field": identifier,
        },
    )
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://paper2ale.local/schemas/generic_protocol.schema.json",
        "title": "paper2ale trusted generic task protocol",
        "oneOf": [
            root_schema("numeric-affine-v1", numeric_generator, numeric_solver),
            root_schema("table-filter-sort-v1", table_generator, table_solver),
            root_schema("json-group-aggregate-v1", json_generator, json_solver),
        ],
    }
    return json.loads(json.dumps(schema, allow_nan=False, sort_keys=True))


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _normalized_text(value: str) -> str:
    return textwrap.dedent(value).strip()


def _text_bytes(value: str) -> bytes:
    return (_normalized_text(value) + "\n").encode("utf-8")


def _file(
    path: str,
    data: bytes | str,
    visibility: str,
    *,
    executable: bool = False,
) -> BuildFile:
    payload = data if isinstance(data, bytes) else _text_bytes(data)
    return BuildFile(path, payload, visibility, executable)


def _derived_seed(master_seed: int, task_id: str, index: int) -> int:
    material = (
        f"paper2ale-generic-v1\0{master_seed}\0{task_id}\0{index}".encode("utf-8")
    )
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _instance_count(
    project: Mapping[str, Any], task: Mapping[str, Any], instances: int | None
) -> int:
    value: Any = instances
    if value is None:
        defaults = project.get("defaults", {})
        fallback = defaults.get("instances", 1) if isinstance(defaults, Mapping) else 1
        value = task.get("instances", fallback)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 64:
        raise ValueError("generic task instances must be an integer between 1 and 64")
    return value


def _difficulty_settings(
    project: Mapping[str, Any],
    task: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> tuple[dict[str, Any], Any | None, dict[str, Any] | None]:
    resolved = resolve_task_difficulty(project, task)
    if resolved is None:
        return {
            "level": None,
            "effective_record_count": int(
                protocol["generator"].get(
                    "query_count",
                    protocol["generator"].get("row_count", protocol["generator"].get("record_count")),
                )
            ),
            "range_scale": 1.0,
            "public_fraction": 1.0,
            "public_noise_scale": 1.0,
            "decoy_field_count": 0,
            "adversarial_case_count": 0,
            "threshold_scale": 1.0,
            "required_pass_fraction": float(protocol["evaluation"]["required_pass_fraction"]),
        }, None, None

    template_id = str(protocol["template_id"])
    declared = TEMPLATE_DIFFICULTY_CONTROLS[template_id]
    consumed = {
        "generator": set(declared["generator"]),
        "evaluator": set(declared["evaluator"]),
    }
    conditional: dict[str, bool] = {}
    if template_id == "numeric-affine-v1":
        has_label_noise = float(protocol["generator"]["public_noise_std"]) > 0
        has_metric_fraction = len(protocol["evaluation"]["metrics"]) > 1
        conditional = {
            "generator.noise_scale": has_label_noise,
            "evaluator.required_pass_fraction": has_metric_fraction,
        }
        if has_label_noise:
            consumed["generator"].add("noise_scale")
        if has_metric_fraction:
            consumed["evaluator"].add("required_pass_fraction")

    profile = difficulty_profile_index(project)[
        (resolved.profile_id, resolved.profile_version)
    ]
    profile_level = next(
        level for level in profile["levels"] if level["name"] == resolved.level
    )
    raw_selection = task.get("difficulty", {})
    if not isinstance(raw_selection, Mapping):
        raise ValueError("generic task difficulty must be an object")
    explicit_overrides: dict[str, dict[str, int | float]] = {
        "generator": {},
        "evaluator": {},
    }
    for section, field in (
        ("generator", "generator_overrides"),
        ("evaluator", "evaluator_overrides"),
    ):
        raw_overrides = raw_selection.get(field, {})
        if not isinstance(raw_overrides, Mapping):
            raise ValueError(f"generic task difficulty {field} must be an object")
        for control, value in raw_overrides.items():
            explicit_overrides[section][str(control)] = value
            if (
                control not in consumed[section]
                and value != profile_level[section][control]
            ):
                raise ValueError(
                    f"generic template {template_id!r} does not semantically consume "
                    f"difficulty control {section}.{control}; a non-default override "
                    "is not allowed"
                )

    generator = resolved.generator
    evaluator = resolved.evaluator
    base_count = int(
        protocol["generator"].get(
            "query_count",
            protocol["generator"].get("row_count", protocol["generator"].get("record_count")),
        )
    )
    complexity = float(generator["input_complexity_scale"])
    hidden = int(evaluator["hidden_case_count"])
    adversarial = int(evaluator["adversarial_case_count"])
    effective_count = hidden + math.ceil(base_count * math.sqrt(complexity)) + adversarial
    if effective_count > MAX_EFFECTIVE_RECORDS:
        raise ValueError(
            "resolved generic protocol would generate more than "
            f"{MAX_EFFECTIVE_RECORDS} records per instance; lower hidden_case_count "
            "or input_complexity_scale"
        )
    constraints = int(generator["constraint_count"])
    if constraints > MAX_DECOY_FIELDS:
        raise ValueError(
            f"resolved constraint_count {constraints} exceeds the generic family's "
            f"semantic limit of {MAX_DECOY_FIELDS} nuisance fields"
        )
    settings: dict[str, Any] = {
        "level": resolved.level,
        "effective_record_count": effective_count,
        "decoy_field_count": constraints,
        "adversarial_case_count": adversarial,
        "resolution_id": resolved.resolution_id,
    }
    if template_id == "numeric-affine-v1":
        settings.update(
            {
                "range_scale": complexity
                * float(evaluator["rollout_horizon_scale"]),
                "public_fraction": max(
                    0.05, 1.0 - float(generator["masked_fraction"])
                ),
                "threshold_scale": float(evaluator["threshold_scale"]),
            }
        )
        if "noise_scale" in consumed["generator"]:
            settings["public_noise_scale"] = float(generator["noise_scale"])
        if "required_pass_fraction" in consumed["evaluator"]:
            settings["required_pass_fraction"] = float(
                evaluator["required_pass_fraction"]
            )

    resolved_maps = {
        "generator": dict(resolved.generator),
        "evaluator": dict(resolved.evaluator),
    }
    control_audit = {
        "schema_version": "paper2ale.generic-difficulty-control-audit/v1",
        "template_id": template_id,
        "resolution_id": resolved.resolution_id,
        "profile_id": resolved.profile_id,
        "profile_version": resolved.profile_version,
        "level": resolved.level,
        "consumed": {
            section: {
                control: resolved_maps[section][control]
                for control in sorted(consumed[section])
            }
            for section in ("generator", "evaluator")
        },
        "unsupported": {
            section: {
                control: value
                for control, value in sorted(resolved_maps[section].items())
                if control not in consumed[section]
            }
            for section in ("generator", "evaluator")
        },
        "effects": {
            f"{section}.{control}": _DIFFICULTY_EFFECTS[
                f"{section}.{control}"
            ]
            for section in ("generator", "evaluator")
            for control in sorted(consumed[section])
        },
        "conditional_support": conditional,
        "explicit_overrides": explicit_overrides,
        "unsupported_non_default_overrides_allowed": False,
        "standard_manifest_role": (
            "locks the complete resolved profile for pipeline compatibility; "
            "this audit is authoritative for semantic consumption"
        ),
    }
    return settings, resolved, control_audit


def _round(value: float, decimals: int) -> float:
    result = round(float(value), decimals)
    return 0.0 if result == 0 else result


def _affine(values: Sequence[float], solver: Mapping[str, Any]) -> list[float]:
    return [
        sum(float(weight) * float(item) for weight, item in zip(row, values, strict=True))
        + float(bias)
        for row, bias in zip(solver["weights"], solver["bias"], strict=True)
    ]


def _numeric_instance(
    protocol: Mapping[str, Any],
    settings: Mapping[str, Any],
    rng: random.Random,
    instance_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    generator = protocol["generator"]
    solver = protocol["reference_solver"]
    dimension = int(generator["input_dimension"])
    decimals = int(generator["decimals"])
    midpoint = (float(generator["low"]) + float(generator["high"])) / 2
    half_span = (float(generator["high"]) - float(generator["low"])) / 2
    half_span *= float(settings["range_scale"])
    low, high = midpoint - half_span, midpoint + half_span
    public_count = max(
        dimension + 1,
        math.ceil(int(generator["public_example_count"]) * float(settings["public_fraction"])),
    )
    noise_std = float(generator["public_noise_std"]) * float(
        settings.get("public_noise_scale", 1.0)
    )
    decoys = int(settings["decoy_field_count"])

    def vector() -> list[float]:
        return [_round(rng.uniform(low, high), decimals) for _ in range(dimension)]

    public_examples = []
    for index in range(public_count):
        inputs = vector()
        outputs = _affine(inputs, solver)
        if noise_std:
            outputs = [value + rng.gauss(0.0, noise_std) for value in outputs]
        public_examples.append(
            {
                "id": f"e{index:05d}",
                "input": inputs,
                "output": outputs,
                "context": [_round(rng.uniform(-1, 1), decimals) for _ in range(decoys)],
            }
        )

    query_count = int(settings["effective_record_count"])
    adversarial = int(settings["adversarial_case_count"])
    adversarial_vectors = (
        [[low] * dimension, [high] * dimension, [0.0] * dimension]
        + [[low if index % 2 == 0 else high for index in range(dimension)]]
    )
    queries = []
    predictions = []
    for index in range(query_count):
        inputs = (
            list(adversarial_vectors[index % len(adversarial_vectors)])
            if index < adversarial
            else vector()
        )
        query_id = f"q{index:05d}"
        queries.append(
            {
                "id": query_id,
                "input": inputs,
                "context": [_round(rng.uniform(-1, 1), decimals) for _ in range(decoys)],
            }
        )
        predictions.append({"id": query_id, "values": _affine(inputs, solver)})
    public = {
        "schema_version": "paper2ale.generic-instance/v1",
        "instance_id": instance_id,
        "template_id": protocol["template_id"],
        "task": "Infer the affine rule from the worked examples and predict every query.",
        "public_examples": public_examples,
        "queries": queries,
        "context_fields_are_decoys": bool(decoys),
        "output_contract": {
            "path": "output/<NNN>/submission.json",
            "object": {"predictions": [{"id": "qNNNNN", "values": ["finite number"]}]},
        },
    }
    golden = {"predictions": predictions}
    mutant = json.loads(json.dumps(golden))
    # A systematic omitted-intercept style error remains detectable even when
    # difficulty expands the hidden query population.  Mutating one scalar
    # would be diluted by RMSE as query_count grows.
    magnitude = max(
        1.0,
        100
        * max(float(metric["threshold"]) for metric in protocol["evaluation"]["metrics"])
        * math.sqrt(int(generator["output_dimension"])),
    )
    for prediction in mutant["predictions"]:
        prediction["values"] = [value + magnitude for value in prediction["values"]]
    return public, golden, mutant


def _column_value(column: Mapping[str, Any], index: int, rng: random.Random) -> Any:
    primitive = column["primitive"]
    if primitive == "sequence_integer":
        return int(column["start"]) + index * int(column["step"])
    if primitive == "uniform_integer":
        return rng.randint(int(column["low"]), int(column["high"]))
    if primitive == "uniform_number":
        return _round(
            rng.uniform(float(column["low"]), float(column["high"])),
            int(column["decimals"]),
        )
    return rng.choice(list(column["values"]))


def _compare(left: Any, operator: str, right: Any) -> bool:
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "lt":
        return left < right
    if operator == "lte":
        return left <= right
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    raise RuntimeError("unreachable filter operator")


def _solve_table(rows: Sequence[Mapping[str, Any]], solver: Mapping[str, Any]) -> list[dict[str, Any]]:
    filter_spec = solver["filter"]
    selected = [
        dict(row)
        for row in rows
        if _compare(row[filter_spec["column"]], filter_spec["operator"], filter_spec["value"])
    ]
    for sort_spec in reversed(solver["sort"]):
        selected.sort(
            key=lambda row, column=sort_spec["column"]: row[column],
            reverse=sort_spec["direction"] == "descending",
        )
    return [
        {column: row[column] for column in solver["project"]}
        for row in selected
    ]


def _table_instance(
    protocol: Mapping[str, Any],
    settings: Mapping[str, Any],
    rng: random.Random,
    instance_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    generator = protocol["generator"]
    solver = protocol["reference_solver"]
    count = int(settings["effective_record_count"])
    decoys = int(settings["decoy_field_count"])
    adversarial = int(settings["adversarial_case_count"])
    rows = []
    filter_spec = solver["filter"]
    for index in range(count):
        row = {
            column["name"]: _column_value(column, index, rng)
            for column in generator["columns"]
        }
        if index < adversarial:
            row[filter_spec["column"]] = filter_spec["value"]
        for decoy_index in range(decoys):
            row[f"context_{decoy_index:02d}"] = _round(rng.uniform(-100, 100), 6)
        rows.append(row)
    public = {
        "schema_version": "paper2ale.generic-instance/v1",
        "instance_id": instance_id,
        "template_id": protocol["template_id"],
        "task": "Filter, stably sort, and project the supplied table exactly as specified.",
        "rows": rows,
        "operation": solver,
        "tie_policy": "Preserve input order for rows tied on all sort keys.",
        "output_contract": {
            "path": "output/<NNN>/submission.json",
            "object": {"rows": [{column: "typed value" for column in solver["project"]}]},
        },
    }
    golden = {"rows": _solve_table(rows, solver)}
    mutant = {"rows": [{"__invalid_mutant__": True}]}
    return public, golden, mutant


def _solve_groups(
    records: Sequence[Mapping[str, Any]], solver: Mapping[str, Any]
) -> dict[str, int]:
    grouped: dict[str, list[int]] = {}
    for record in records:
        grouped.setdefault(str(record[solver["group_field"]]), []).append(
            int(record[solver["value_field"]])
        )
    operation = solver["operation"]
    result: dict[str, int] = {}
    for group, values in sorted(grouped.items()):
        if operation == "sum":
            result[group] = sum(values)
        elif operation == "count":
            result[group] = len(values)
        elif operation == "min":
            result[group] = min(values)
        else:
            result[group] = max(values)
    return result


def _json_instance(
    protocol: Mapping[str, Any],
    settings: Mapping[str, Any],
    rng: random.Random,
    instance_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    generator = protocol["generator"]
    solver = protocol["reference_solver"]
    count = int(settings["effective_record_count"])
    adversarial = int(settings["adversarial_case_count"])
    decoys = int(settings["decoy_field_count"])
    groups = list(generator["groups"])
    records = []
    for index in range(count):
        group = groups[index % len(groups)] if index < adversarial else rng.choice(groups)
        value = (
            int(generator["value_low"] if index % 2 == 0 else generator["value_high"])
            if index < adversarial
            else rng.randint(int(generator["value_low"]), int(generator["value_high"]))
        )
        record: dict[str, Any] = {
            generator["group_field"]: group,
            generator["value_field"]: value,
        }
        for decoy_index in range(decoys):
            record[f"context_{decoy_index:02d}"] = rng.randint(-10_000, 10_000)
        records.append(record)
    public = {
        "schema_version": "paper2ale.generic-instance/v1",
        "instance_id": instance_id,
        "template_id": protocol["template_id"],
        "task": "Group the records and compute the requested integer aggregate.",
        "records": records,
        "operation": solver,
        "output_contract": {
            "path": "output/<NNN>/submission.json",
            "object": {"result": {"group name": "integer aggregate"}},
        },
    }
    golden = {"result": _solve_groups(records, solver)}
    mutant = json.loads(json.dumps(golden))
    if mutant["result"]:
        first = sorted(mutant["result"])[0]
        mutant["result"][first] += 1
    else:  # validation makes this unreachable, retained as a safe invariant
        mutant["result"] = {"__invalid_mutant__": 1}
    return public, golden, mutant


def _effective_evaluation(
    protocol: Mapping[str, Any], settings: Mapping[str, Any], expected: Mapping[str, Any]
) -> dict[str, Any]:
    metrics = []
    for metric in protocol["evaluation"]["metrics"]:
        normalized = dict(metric)
        if normalized["primitive"].startswith("numeric_"):
            normalized["threshold"] = float(normalized["threshold"]) * float(
                settings.get("threshold_scale", 1.0)
            )
            normalized["direction"] = "lower_is_better"
        else:
            normalized["direction"] = "higher_is_better"
        metrics.append(normalized)
    return {
        "schema_version": "paper2ale.generic-evaluation/v1",
        "output_primitive": protocol["output"]["primitive"],
        "filename": protocol["output"]["filename"],
        "expected": expected,
        "metrics": metrics,
        "gates": list(protocol["evaluation"]["gates"]),
        "max_submission_bytes": int(protocol["evaluation"]["max_submission_bytes"]),
        "required_pass_fraction": float(
            settings.get(
                "required_pass_fraction",
                protocol["evaluation"]["required_pass_fraction"],
            )
        ),
    }


def _contract_mutants(
    template_id: str, golden: Mapping[str, Any]
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Return deterministic interface bug classes in addition to the scientific mutant."""

    extra_key = json.loads(json.dumps(golden))
    extra_key["unexpected"] = True
    missing = json.loads(json.dumps(golden))
    if template_id == "numeric-affine-v1":
        missing["predictions"] = missing["predictions"][:-1]
    elif template_id == "table-filter-sort-v1":
        missing.pop("rows", None)
    else:
        result = missing.get("result", {})
        if result:
            result.pop(sorted(result)[0])
        else:
            missing.pop("result", None)
    return (
        ("contract-extra-key", extra_key),
        ("contract-missing-output", missing),
    )


def _visible_baseline(
    template_id: str,
    public: Mapping[str, Any],
    golden: Mapping[str, Any],
) -> dict[str, Any]:
    """Solve using participant-visible information, never hidden solver parameters."""

    if template_id == "numeric-affine-v1":
        examples = public["public_examples"]
        design = np.asarray(
            [list(example["input"]) + [1.0] for example in examples],
            dtype=float,
        )
        targets = np.asarray([example["output"] for example in examples], dtype=float)
        coefficients, *_ = np.linalg.lstsq(design, targets, rcond=None)
        predictions = []
        for query in public["queries"]:
            values = np.asarray(list(query["input"]) + [1.0], dtype=float) @ coefficients
            predictions.append(
                {"id": query["id"], "values": [float(value) for value in values]}
            )
        return {"predictions": predictions}
    if template_id == "table-filter-sort-v1":
        return {"rows": _solve_table(public["rows"], public["operation"])}
    if template_id == "json-group-aggregate-v1":
        return {"result": _solve_groups(public["records"], public["operation"])}
    raise RuntimeError("unsupported visible baseline template")


_GRADER = r'''
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


def strict_json(data):
    def reject(value):
        raise ValueError("non-finite JSON constant " + value)
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key " + repr(key))
            result[key] = value
        return result
    return json.loads(
        data.decode("utf-8"),
        parse_constant=reject,
        object_pairs_hook=unique_object,
    )


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def numeric_values(submitted, expected):
    if not isinstance(submitted, dict) or set(submitted) != {"predictions"}:
        raise ValueError("submission must contain only predictions")
    actual_rows = submitted["predictions"]
    expected_rows = expected["predictions"]
    if not isinstance(actual_rows, list) or len(actual_rows) != len(expected_rows):
        raise ValueError("prediction count mismatch")
    actual_by_id = {}
    for row in actual_rows:
        if not isinstance(row, dict) or set(row) != {"id", "values"} or not isinstance(row["id"], str):
            raise ValueError("invalid prediction row")
        if row["id"] in actual_by_id:
            raise ValueError("duplicate query ID")
        actual_by_id[row["id"]] = row["values"]
    expected_ids = [row["id"] for row in expected_rows]
    if set(actual_by_id) != set(expected_ids):
        raise ValueError("query ID mismatch")
    actual, target = [], []
    for row in expected_rows:
        values = actual_by_id[row["id"]]
        if not isinstance(values, list) or len(values) != len(row["values"]):
            raise ValueError("prediction shape mismatch")
        if not all(finite_number(value) for value in values):
            raise ValueError("predictions must be finite numbers")
        actual.extend(float(value) for value in values)
        target.extend(float(value) for value in row["values"])
    return actual, target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True)
    parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    evaluation = strict_json((root / "instances" / args.instance / "evaluation.json").read_bytes())
    submission = Path(args.submission)
    if submission.is_dir():
        submission = submission / evaluation["filename"]
    errors = []
    gate_results = {gate: True for gate in evaluation["gates"]}
    try:
        if submission.is_symlink() or not submission.is_file():
            raise ValueError("submission file is missing or is a symbolic link")
        size = submission.stat().st_size
        if size > evaluation["max_submission_bytes"]:
            gate_results["max_bytes"] = False
            raise ValueError("submission exceeds byte limit")
        submitted = strict_json(submission.read_bytes())
    except Exception as error:
        submitted = None
        gate_results = {gate: False for gate in evaluation["gates"]}
        errors.append(type(error).__name__ + ": " + str(error))

    metric_results = []
    if submitted is not None:
        primitive = evaluation["output_primitive"]
        expected = evaluation["expected"]
        try:
            if primitive == "numeric_predictions_json":
                actual, target = numeric_values(submitted, expected)
                differences = [left - right for left, right in zip(actual, target)]
                values = {
                    "numeric_rmse": math.sqrt(sum(value * value for value in differences) / len(differences)),
                    "numeric_max_abs": max(abs(value) for value in differences),
                }
            elif primitive == "table_rows_json":
                if not isinstance(submitted, dict) or set(submitted) != {"rows"} or not isinstance(submitted["rows"], list):
                    raise ValueError("submission must contain only a rows array")
                values = {"table_exact": 1.0 if submitted == expected else 0.0}
            elif primitive == "json_object":
                if not isinstance(submitted, dict) or set(submitted) != {"result"} or not isinstance(submitted["result"], dict):
                    raise ValueError("submission must contain only a result object")
                values = {"json_exact": 1.0 if submitted == expected else 0.0}
            else:
                raise ValueError("untrusted output primitive")
            for metric in evaluation["metrics"]:
                value = values[metric["primitive"]]
                passed = value <= metric["threshold"] if metric["direction"] == "lower_is_better" else value >= metric["threshold"]
                if metric["direction"] == "lower_is_better":
                    metric_score = 1.0 if passed else max(0.0, metric["threshold"] / value) if value > 0 else 1.0
                else:
                    metric_score = min(1.0, max(0.0, value))
                metric_results.append({"id": metric["id"], "primitive": metric["primitive"], "value": value, "threshold": metric["threshold"], "weight": metric["weight"], "score": metric_score, "passed": passed})
        except Exception as error:
            for gate in gate_results:
                if gate not in {"strict_json", "max_bytes"}:
                    gate_results[gate] = False
            errors.append(type(error).__name__ + ": " + str(error))

    total_weight = sum(metric["weight"] for metric in evaluation["metrics"])
    passed_weight = sum(metric["weight"] for metric in metric_results if metric["passed"])
    fraction = passed_weight / total_weight if total_weight else 0.0
    hard_gates_passed = all(gate_results.values())
    passed = hard_gates_passed and fraction >= evaluation["required_pass_fraction"]
    metric_scores = {metric["id"]: 0.0 for metric in evaluation["metrics"]}
    metric_scores.update({metric["id"]: metric["score"] for metric in metric_results})
    weighted_score = sum(metric["weight"] * metric["score"] for metric in metric_results) / total_weight if total_weight else 0.0
    score = weighted_score if hard_gates_passed else 0.0
    result = {
        "passed": passed,
        "hard_gates_passed": hard_gates_passed,
        "score": score,
        "instance": args.instance,
        "metric_pass_fraction": fraction,
        "metric_scores": metric_scores,
        "metrics": metric_results,
        "gates": gate_results,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
'''


def _ale_main(task_id: str, count: int, description: str) -> str:
    variants = tuple(f"{index:03d}" for index in range(count))
    return f'''
    """ALE adapter for a trusted generic JSON task."""

    from __future__ import annotations

    from dataclasses import dataclass
    import json
    import math
    import shlex

    import cua_bench as cb
    from tasks.linux_runtime import LinuxTaskConfig

    VARIANTS = {variants!r}
    TASK_DESCRIPTION = {description!r}


    @dataclass
    class TaskConfig(LinuxTaskConfig):
        DOMAIN_NAME: str = "research_workflows"
        TASK_NAME: str = "{task_id}"
        VARIANT_NAME: str = "000"

        @property
        def task_description(self) -> str:
            return (
                TASK_DESCRIPTION + "\\n\\nRead "
                + str(self.input_dir).rstrip("/") + "/input.json and write "
                + str(self.remote_output_dir).rstrip("/") + "/submission.json. "
            )


    def metadata(cfg, instance_id):
        result = dict(cfg.to_metadata())
        result.update({{
            "instance_id": instance_id,
            "grader_path": str(cfg.reference_dir).rstrip("/") + "/grader.py",
            "submission_path": str(cfg.remote_output_dir).rstrip("/") + "/submission.json",
            "remote_output_dir": str(cfg.remote_output_dir),
        }})
        return result


    @cb.tasks_config(split="train")
    def load():
        tasks = []
        for instance_id in VARIANTS:
            cfg = TaskConfig(VARIANT_NAME=instance_id)
            tasks.append(cb.Task(
                description=cfg.task_description,
                metadata=metadata(cfg, instance_id),
                computer={{"provider": "computer", "setup_config": {{"os_type": cfg.OS_TYPE}}}},
            ))
        return tasks


    @cb.setup_task(split="train")
    async def start(task_cfg, session: cb.DesktopSession):
        await session.run_command(
            "mkdir -p " + shlex.quote(task_cfg.metadata["remote_output_dir"]),
            check=True,
        )


    @cb.evaluate_task(split="train")
    async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
        metadata = task_cfg.metadata
        command = (
            "python3 " + shlex.quote(metadata["grader_path"])
            + " --submission " + shlex.quote(metadata["submission_path"])
            + " --instance " + shlex.quote(metadata["instance_id"])
        )
        completed = await session.run_command(command, check=False)
        stdout = completed.get("stdout", "") if isinstance(completed, dict) else getattr(completed, "stdout", "")
        try:
            begin, end = stdout.find("{{"), stdout.rfind("}}")
            result = json.loads(stdout[begin:end + 1]) if begin >= 0 and end >= begin else {{}}
        except (TypeError, ValueError, json.JSONDecodeError):
            result = {{}}
        score = result.get("score", 0.0)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            score = 0.0
        return [min(1.0, max(0.0, float(score)))]


    if __name__ == "__main__":
        cb.interact(__file__)
    '''


def _task_card(
    task_id: str,
    template_id: str,
    count: int,
    task: Mapping[str, Any],
) -> dict[str, Any]:
    budget = task.get("resource_budget", {})
    budget = budget if isinstance(budget, Mapping) else {}
    timeout = budget.get("cpu_seconds", 300)
    timeout = int(timeout) if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) else 300
    timeout = min(3600, max(1, timeout))
    return {
        "taskId": f"research_workflows/{task_id}",
        "title": {
            "numeric-affine-v1": "Recover a numeric transformation",
            "table-filter-sort-v1": "Transform a structured table",
            "json-group-aggregate-v1": "Aggregate structured records",
        }[template_id],
        "summary": "A paper-blind task compiled from a bounded trusted protocol.",
        "category": "research_workflows",
        "vm": {
            "snapshot": "cpu-free-ubuntu",
            "vcpus": 2,
            "memory_gb": 8,
            "disk_gb": 50,
            "timeout_s": timeout,
        },
        "paper2ale": {
            "schemaVersion": 1,
            "family": "generic",
            "familyTaskId": task_id,
            "templateId": template_id,
            "paperBlind": True,
            "instanceCount": count,
            "instancePattern": "input/instances/<NNN>/",
            "entrypoint": "main.py",
            "runtime": {"language": "python", "minimumVersion": "3.11", "dependencies": []},
            "submission": {
                "format": _TEMPLATE_OUTPUT[template_id],
                "path": "output/<NNN>/submission.json",
                "executable": False,
            },
        },
    }


def _description(
    template_id: str,
    public: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> str:
    if template_id == "numeric-affine-v1":
        examples = public["public_examples"]
        queries = public["queries"]
        input_dimension = len(examples[0]["input"])
        output_dimension = len(examples[0]["output"])
        example_values = json.dumps([0.0] * output_dimension)
        thresholds = ", ".join(
            f'`{metric["id"]}` <= `{metric["threshold"]:.8g}`'
            for metric in evaluation["metrics"]
        )
        required_fraction = float(evaluation["required_pass_fraction"])
        return f'''
        # Recover an affine transformation from examples

        ## Goal

        Infer one affine rule from worked numeric examples, then apply that same
        rule to every unlabeled query. This is a small system-identification
        problem, not a request to memorize rows. The hidden rule has the form

        ```text
        y = W x + b
        ```

        where each input `x` has `{input_dimension}` numbers and each output `y`
        has `{output_dimension}` numbers. Recover the matrix `W` and intercept
        `b` well enough to predict held-out inputs. A neural network is neither
        required nor especially useful; least squares with an intercept is a
        suitable starting point.

        ## Input

        Read the variant's `input.json`. In a compiled bundle it is stored at
        `input/instances/<NNN>/input.json`; the ALE runtime supplies the exact
        variant path. The file contains:

        - `public_examples`: `{len(examples)}` rows with `id`, `input`, and
          possibly noisy `output` values;
        - `queries`: `{len(queries)}` rows with `id` and `input`, but no output;
        - `output_contract`: the required destination and JSON shape;
        - `context` values that are explicit decoys and must not affect the rule.

        Use the example inputs and outputs to fit all coefficients jointly.
        Preserve every query ID exactly and compute one prediction vector for
        each query.

        ## Required output

        Write `submission.json` with exactly one top-level key:

        ```json
        {{
          "predictions": [
            {{"id": "q00000", "values": {example_values}}}
          ]
        }}
        ```

        Each `values` array must contain exactly `{output_dimension}` finite
        numbers. Include every query ID exactly once; do not include example
        IDs, extra keys, comments, code, commands, or serialized objects. The
        maximum file size is `{evaluation["max_submission_bytes"]}` bytes.

        ## Evaluation

        The private evaluator applies the exact affine rule to all public query
        inputs and compares your values with those references. Required numeric
        thresholds are {thresholds}. Passing metrics must contribute at least
        `{required_fraction:.0%}` of the declared metric weight. The grader also
        enforces strict JSON, the byte limit, exact vector shapes, finite
        numbers, and complete unique query IDs.

        ## Common mistakes

        - fitting a linear rule without an intercept column;
        - using the unrelated `context` fields as predictors;
        - predicting the examples instead of the query rows;
        - rounding coefficients or predictions too early;
        - omitting IDs, changing their spelling, or adding extra JSON fields.
        '''
    if template_id == "table-filter-sort-v1":
        return f'''
        # Filter, sort, and project a typed table

        ## Goal

        Apply the operation declared in `input.json` to every supplied row:
        first filter by the stated comparison, then perform the stated stable
        sort, and finally keep only the requested columns. This is an exact
        data-transformation task; do not infer an unstated rule.

        ## Input and output

        The input contains `{len(public["rows"])}` typed rows plus an `operation`
        object defining the filter, sort keys and directions, and projection.
        Write `submission.json` as `{{"rows": [...]}}`. Preserve original data
        types, apply sort keys in their declared order, and include no extra
        keys. The file must be at most `{evaluation["max_submission_bytes"]}`
        bytes.

        ## Evaluation

        The grader recomputes the complete table and requires exact equality,
        strict JSON, the declared row schema, and the byte limit. Common errors
        are sorting before filtering, reversing a direction, using an unstable
        tie-breaker, or projecting columns before the comparison is evaluated.
        '''
    return f'''
    # Group and aggregate JSON records

    ## Goal

    Group all records using the field named in `operation` and calculate the
    declared integer aggregate for every required group. This is an exact
    transformation; use only the supplied records and operation.

    ## Input and output

    `input.json` contains `{len(public["records"])}` records and the group,
    value, and aggregation fields. Write `submission.json` as
    `{{"result": {{"group-name": 0}}}}`, with exactly the required group keys
    and finite integer results. Add no extra top-level fields. The file must be
    at most `{evaluation["max_submission_bytes"]}` bytes.

    ## Evaluation

    The grader independently recomputes every aggregate and requires exact JSON
    equality, all required keys, and the byte limit. Common mistakes are
    grouping by the value field, dropping zero or negative values, confusing
    `count` with `sum`, and omitting groups that are present in the input.
    '''


def _source_ids(project: Mapping[str, Any]) -> list[str]:
    sources = project.get("source_bundle", [])
    if not isinstance(sources, list):
        return []
    return sorted(
        {
            str(source["id"])
            for source in sources
            if isinstance(source, Mapping)
            and isinstance(source.get("id"), str)
            and source["id"]
        }
    )


def build_task_files(
    project: dict,
    task: dict,
    *,
    master_seed: int,
    instances: int | None = None,
    build_context: Any | None = None,
) -> list[BuildFile]:
    """Compile one declarative protocol into deterministic task files."""

    del build_context  # Generic v1 materializes only trusted synthetic inputs.
    if not isinstance(project, dict) or not isinstance(task, dict):
        raise TypeError("project and task must be dictionaries")
    task_id = task.get("id") or task.get("task_id")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id) or len(task_id) > 128:
        raise ValueError("generic task id must be a safe path-component identifier")
    if isinstance(master_seed, bool) or not isinstance(master_seed, int):
        raise TypeError("master_seed must be an integer")
    raw_protocol = task.get("protocol")
    if not isinstance(raw_protocol, Mapping):
        raise ValueError("generic tasks require a declarative protocol object")
    protocol = validate_protocol(raw_protocol)
    count = _instance_count(project, task, instances)
    settings, resolved, difficulty_control_audit = _difficulty_settings(
        project, task, protocol
    )
    if resolved is not None and instances is None and count != int(resolved.generator["instance_count"]):
        raise ValueError(
            "generic task instances must equal resolved difficulty instance_count; "
            "use generator_overrides.instance_count to choose a count"
        )

    protocol_hash = hashlib.sha256(
        json.dumps(protocol, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    files: list[BuildFile] = []
    seeds: list[int] = []
    for index in range(count):
        instance_id = f"{index:03d}"
        seed = _derived_seed(master_seed, task_id, index)
        seeds.append(seed)
        rng = random.Random(seed)
        if protocol["template_id"] == "numeric-affine-v1":
            public, golden, mutant = _numeric_instance(protocol, settings, rng, instance_id)
        elif protocol["template_id"] == "table-filter-sort-v1":
            public, golden, mutant = _table_instance(protocol, settings, rng, instance_id)
        else:
            public, golden, mutant = _json_instance(protocol, settings, rng, instance_id)
        evaluation = _effective_evaluation(protocol, settings, golden)
        baseline = _visible_baseline(protocol["template_id"], public, golden)
        files.extend(
            [
                _file(f"input/instances/{instance_id}/input.json", _json_bytes(public), AGENT),
                _file(f"reference/instances/{instance_id}/evaluation.json", _json_bytes(evaluation), EVALUATOR),
                _file(f"example/instances/{instance_id}/golden.json", _json_bytes(golden), EVALUATOR),
                _file(f"example/instances/{instance_id}/visible_baseline.json", _json_bytes(baseline), EVALUATOR),
                _file(f"example/instances/{instance_id}/mutant.json", _json_bytes(mutant), EVALUATOR),
            ]
        )
        for mutant_id, mutant_payload in _contract_mutants(
            protocol["template_id"], golden
        ):
            files.append(
                _file(
                    f"example/instances/{instance_id}/mutants/{mutant_id}.json",
                    _json_bytes(mutant_payload),
                    EVALUATOR,
                )
            )

    description = _normalized_text(
        _description(protocol["template_id"], public, evaluation)
    )
    files.extend(
        [
            _file("description.md", description, AGENT),
            _file("task_card.json", _json_bytes(_task_card(task_id, protocol["template_id"], count, task)), AGENT),
            _file("main.py", _ale_main(task_id, count, description), AGENT, executable=True),
            _file("reference/grader.py", _GRADER, EVALUATOR, executable=True),
            _file("author/protocol.json", _json_bytes(protocol), AUTHOR),
            _file(
                "author/protocol_validation.json",
                _json_bytes(
                    {
                        "schema_version": "paper2ale.generic-protocol-validation/v1",
                        "protocol_sha256": protocol_hash,
                        "template_id": protocol["template_id"],
                        "generator_primitive": protocol["generator"]["primitive"],
                        "reference_solver_primitive": protocol["reference_solver"]["primitive"],
                        "output_primitive": protocol["output"]["primitive"],
                        "metric_primitives": [metric["primitive"] for metric in protocol["evaluation"]["metrics"]],
                        "gate_primitives": list(protocol["evaluation"]["gates"]),
                        "executes_protocol_code": False,
                    }
                ),
                AUTHOR,
            ),
            _file(
                "author/provenance.json",
                _json_bytes(
                    {
                        "schema_version": "paper2ale.generic-provenance/v1",
                        "project_id": project.get("project_id"),
                        "task_id": task_id,
                        "source_ids": _source_ids(project),
                        "evidence_ids": sorted(str(item) for item in task.get("evidence_ids", []) if isinstance(item, str)),
                        "workflow_nodes": sorted(str(item) for item in task.get("workflow_nodes", []) if isinstance(item, str)),
                        "protocol_sha256": protocol_hash,
                    }
                ),
                AUTHOR,
            ),
            _file(
                "author/reference_solver.json",
                _json_bytes(
                    {
                        "schema_version": "paper2ale.generic-reference-solver/v1",
                        "primitive": protocol["reference_solver"]["primitive"],
                        "parameters": protocol["reference_solver"],
                        "implementation": "trusted in-process primitive",
                        "model_supplied_code_executed": False,
                    }
                ),
                AUTHOR,
            ),
            _file(
                "author/generation_parameters.json",
                _json_bytes(
                    {
                        "schema_version": "paper2ale.generic-generation-parameters/v1",
                        "task_id": task_id,
                        "instance_count": count,
                        "instance_seeds": seeds,
                        "protocol_sha256": protocol_hash,
                        "derived_difficulty_settings": settings,
                    }
                ),
                AUTHOR,
            ),
        ]
    )
    if resolved is not None:
        assert difficulty_control_audit is not None
        files.extend(
            [
                _file(
                    "author/difficulty_manifest.json",
                    _json_bytes(
                        make_consumption_manifest(
                            resolved, resolved.generator, resolved.evaluator
                        )
                    ),
                    AUTHOR,
                ),
                _file(
                    "author/difficulty_control_audit.json",
                    _json_bytes(difficulty_control_audit),
                    AUTHOR,
                ),
            ]
        )
    paths = [item.path.casefold() for item in files]
    if len(paths) != len(set(paths)):
        raise RuntimeError("generic compiler produced duplicate package paths")
    return sorted(files, key=lambda item: item.path)


__all__ = [
    "GENERIC_CAPABILITIES",
    "MAX_EFFECTIVE_RECORDS",
    "MAX_PROTOCOL_BYTES",
    "MAX_SUBMISSION_BYTES",
    "PROTOCOL_SCHEMA_VERSION",
    "ProtocolValidationError",
    "SUPPORTED_TEMPLATES",
    "TEMPLATE_DIFFICULTY_CONTROLS",
    "build_task_files",
    "protocol_json_schema",
    "validate_protocol",
]
