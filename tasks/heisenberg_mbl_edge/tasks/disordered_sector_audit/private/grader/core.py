"""Strict result parser and scientific scoring for the private evaluator."""

from __future__ import annotations

import ast
import json
import math
import os
import stat
import time
from pathlib import Path
from typing import Any

import numpy as np


MAX_SOLUTION_BYTES = 200_000
MAX_RESULT_BYTES = 8 * 1024 * 1024
RESULT_KEYS = {"schema_version", "experiment_id", "state_rows", "aggregate_rows", "conclusions"}
STATE_KEYS = {
    "record_id",
    "condition_id",
    "query_id",
    "state_rank",
    "eigen_index",
    "eigenvalue",
    "normalized_energy",
    "gap_ratio",
    "entanglement",
    "participation_s1",
    "participation_s2",
    "subsystem_mz_mean",
    "subsystem_mz_variance",
}
AGGREGATE_KEYS = {
    "aggregate_id",
    "condition_id",
    "query_id",
    "epsilon",
    "subsystem_start",
    "subsystem_size",
    "realization_count",
    "state_count",
    "mean_gap_ratio",
    "sem_gap_ratio",
    "mean_entanglement",
    "sem_entanglement",
    "mean_participation_s1",
    "sem_participation_s1",
    "mean_participation_s2",
    "sem_participation_s2",
    "mean_subsystem_mz_mean",
    "sem_subsystem_mz_mean",
    "mean_subsystem_mz_variance",
    "sem_subsystem_mz_variance",
}
CONCLUSION_KEYS = {
    "claim_id",
    "metric",
    "direction",
    "positive_effect",
    "effect",
    "weak_aggregate_id",
    "strong_aggregate_id",
}
STATE_NUMERIC = (
    "eigenvalue",
    "normalized_energy",
    "gap_ratio",
    "entanglement",
    "participation_s1",
    "participation_s2",
    "subsystem_mz_mean",
    "subsystem_mz_variance",
)
AGGREGATE_NUMERIC = tuple(
    sorted(
        key
        for key in AGGREGATE_KEYS
        if key.startswith("mean_") or key.startswith("sem_") or key == "epsilon"
    )
)


class SubmissionError(ValueError):
    """Expected safe rejection boundary."""


def _persistent_multiple_links(path: Path, info: os.stat_result) -> bool:
    """Confirm link multiplicity while tolerating transient Windows metadata."""
    if info.st_nlink <= 1:
        return False
    # Windows/NTFS can briefly report link-count metadata from a just-closed
    # writer inconsistently across handles.  A real post-exit hard link remains
    # stable, so require the multiplicity to persist for a bounded half-second.
    for _attempt in range(10):
        time.sleep(0.05)
        try:
            info = path.lstat()
        except OSError:
            return True
        if info.st_nlink <= 1:
            return False
    return True


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-standard JSON constant {token}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON key {key}")
        output[key] = value
    return output


def load_json_strict(path: Path, maximum_bytes: int) -> Any:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SubmissionError(f"missing result file: {path.name}") from exc
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode):
        raise SubmissionError("result must be a regular file")
    if _persistent_multiple_links(path, info):
        raise SubmissionError("hard-linked result files are forbidden")
    if info.st_size > maximum_bytes:
        raise SubmissionError("result exceeds the size limit")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise SubmissionError(f"invalid result JSON: {exc}") from exc


def validate_submission(directory: Path) -> Path:
    directory = Path(os.path.abspath(directory))
    try:
        info = directory.lstat()
    except OSError as exc:
        raise SubmissionError("submission directory is missing") from exc
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISDIR(info.st_mode):
        raise SubmissionError("submission must be a real directory")
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise SubmissionError("submission directory cannot be enumerated") from exc
    if len(entries) != 1 or entries[0].name != "solution.py":
        raise SubmissionError("submission must contain exactly solution.py")
    solution = entries[0]
    try:
        file_info = solution.lstat()
    except OSError as exc:
        raise SubmissionError("solution.py is missing") from exc
    reparse = bool(getattr(file_info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(file_info.st_mode) or reparse or not stat.S_ISREG(file_info.st_mode):
        raise SubmissionError("solution.py must be a regular file")
    if _persistent_multiple_links(solution, file_info):
        raise SubmissionError("hard-linked solution.py is forbidden")
    if not 1 <= file_info.st_size <= MAX_SOLUTION_BYTES:
        raise SubmissionError("solution.py violates the size limit")
    try:
        source = solution.read_text(encoding="utf-8")
        ast.parse(source, filename="solution.py")
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise SubmissionError(f"solution.py is not valid UTF-8 Python: {exc}") from exc
    return solution


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubmissionError(f"{label} must be a JSON number")
    result = float(value)
    if not math.isfinite(result) or abs(result) > 1.0e12:
        raise SubmissionError(f"{label} is non-finite or outside the safety range")
    return result


def _integer(value: Any, label: str) -> int:
    if type(value) is not int:
        raise SubmissionError(f"{label} must be an integer")
    return int(value)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160 or "\x00" in value:
        raise SubmissionError(f"{label} must be a short nonempty string")
    return value


def _row_map(rows: Any, key_fields: tuple[str, ...], exact_keys: set[str], label: str) -> dict[tuple, dict]:
    if not isinstance(rows, list):
        raise SubmissionError(f"{label} must be a list")
    if len(rows) > 20_000:
        raise SubmissionError(f"{label} has too many rows")
    output: dict[tuple, dict] = {}
    for row_number, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != exact_keys:
            raise SubmissionError(f"{label}[{row_number}] has the wrong fields")
        for field in key_fields:
            if field == "state_rank":
                _integer(row[field], f"{label}[{row_number}].{field}")
            else:
                _text(row[field], f"{label}[{row_number}].{field}")
        key = tuple(row[field] for field in key_fields)
        if key in output:
            raise SubmissionError(f"duplicate key in {label}: {key}")
        output[key] = row
    return output


def validate_result(data: Any, reference: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != RESULT_KEYS:
        raise SubmissionError("result top-level schema mismatch")
    if data.get("schema_version") != "sector-audit-result/v1":
        raise SubmissionError("unsupported result schema_version")
    if data.get("experiment_id") != reference.get("experiment_id"):
        raise SubmissionError("result experiment_id is stale or wrong")
    states = _row_map(
        data["state_rows"],
        ("record_id", "query_id", "state_rank"),
        STATE_KEYS,
        "state_rows",
    )
    aggregates = _row_map(
        data["aggregate_rows"],
        ("aggregate_id",),
        AGGREGATE_KEYS,
        "aggregate_rows",
    )
    conclusions = _row_map(
        data["conclusions"],
        ("claim_id",),
        CONCLUSION_KEYS,
        "conclusions",
    )
    expected_states = _row_map(
        reference["state_rows"],
        ("record_id", "query_id", "state_rank"),
        STATE_KEYS,
        "reference.state_rows",
    )
    expected_aggregates = _row_map(
        reference["aggregate_rows"],
        ("aggregate_id",),
        AGGREGATE_KEYS,
        "reference.aggregate_rows",
    )
    expected_conclusions = _row_map(
        reference["conclusions"],
        ("claim_id",),
        CONCLUSION_KEYS,
        "reference.conclusions",
    )
    if set(states) != set(expected_states):
        raise SubmissionError("state row keys do not match the experiment")
    if set(aggregates) != set(expected_aggregates):
        raise SubmissionError("aggregate row keys do not match the experiment")
    if set(conclusions) != set(expected_conclusions):
        raise SubmissionError("conclusion row keys do not match the experiment")
    for key, row in states.items():
        for field in ("record_id", "condition_id", "query_id"):
            _text(row[field], f"state {key}.{field}")
        _integer(row["state_rank"], f"state {key}.state_rank")
        _integer(row["eigen_index"], f"state {key}.eigen_index")
        for field in STATE_NUMERIC:
            _finite_number(row[field], f"state {key}.{field}")
        if row["condition_id"] != expected_states[key]["condition_id"]:
            raise SubmissionError(f"state {key}.condition_id does not match its record")
    for key, row in aggregates.items():
        for field in ("aggregate_id", "condition_id", "query_id"):
            _text(row[field], f"aggregate {key}.{field}")
        for field in ("subsystem_start", "subsystem_size", "realization_count", "state_count"):
            _integer(row[field], f"aggregate {key}.{field}")
        for field in AGGREGATE_NUMERIC:
            _finite_number(row[field], f"aggregate {key}.{field}")
        for field in (
            "condition_id",
            "query_id",
            "epsilon",
            "subsystem_start",
            "subsystem_size",
            "realization_count",
            "state_count",
        ):
            if row[field] != expected_aggregates[key][field]:
                raise SubmissionError(f"aggregate {key}.{field} does not match the experiment")
    for key, row in conclusions.items():
        for field in (
            "claim_id",
            "metric",
            "direction",
            "weak_aggregate_id",
            "strong_aggregate_id",
        ):
            _text(row[field], f"conclusion {key}.{field}")
        if type(row["positive_effect"]) is not bool:
            raise SubmissionError(f"conclusion {key}.positive_effect must be boolean")
        effect = _finite_number(row["effect"], f"conclusion {key}.effect")
        expected_row = expected_conclusions[key]
        for field in (
            "metric",
            "direction",
            "weak_aggregate_id",
            "strong_aggregate_id",
        ):
            if row[field] != expected_row[field]:
                raise SubmissionError(f"conclusion {key}.{field} does not match the requested comparison")
        weak_key = (row["weak_aggregate_id"],)
        strong_key = (row["strong_aggregate_id"],)
        if weak_key not in aggregates or strong_key not in aggregates:
            raise SubmissionError(f"conclusion {key} references a missing aggregate")
        mean_field = f"mean_{row['metric']}"
        if mean_field not in AGGREGATE_KEYS:
            raise SubmissionError(f"conclusion {key} uses an unsupported metric")
        derived = float(aggregates[weak_key][mean_field]) - float(
            aggregates[strong_key][mean_field]
        )
        tolerance = max(5.0e-8, 2.0e-7 * abs(derived))
        if abs(effect - derived) > tolerance:
            raise SubmissionError(f"conclusion {key}.effect is inconsistent with its aggregates")
        if row["positive_effect"] is not bool(derived > 0.0):
            raise SubmissionError(f"conclusion {key}.positive_effect is inconsistent with its aggregates")
    return {"states": states, "aggregates": aggregates, "conclusions": conclusions}


def normalized_rmse(actual: list[float], expected: list[float], absolute: float, relative: float) -> float:
    left = np.asarray(actual, dtype=np.float64)
    right = np.asarray(expected, dtype=np.float64)
    scale = np.maximum(absolute, relative * np.abs(right))
    return float(np.sqrt(np.mean(np.square((left - right) / scale))))


def quality(error: float, excellent: float = 1.0, minimum: float = 50.0) -> float:
    if error <= excellent:
        return 1.0
    if error >= minimum:
        return 0.0
    return float((minimum - error) / (minimum - excellent))


def score_result(parsed: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "states": _row_map(reference["state_rows"], ("record_id", "query_id", "state_rank"), STATE_KEYS, "reference.state_rows"),
        "aggregates": _row_map(reference["aggregate_rows"], ("aggregate_id",), AGGREGATE_KEYS, "reference.aggregate_rows"),
        "conclusions": _row_map(reference["conclusions"], ("claim_id",), CONCLUSION_KEYS, "reference.conclusions"),
    }
    state_keys = sorted(expected["states"])
    spectral_fields = ("eigenvalue", "normalized_energy", "gap_ratio")
    entanglement_fields = ("entanglement", "participation_s1", "participation_s2")
    magnetization_fields = ("subsystem_mz_mean", "subsystem_mz_variance")
    def values(field_names: tuple[str, ...]):
        actual = [float(parsed["states"][key][field]) for key in state_keys for field in field_names]
        truth = [float(expected["states"][key][field]) for key in state_keys for field in field_names]
        return actual, truth
    spectral_actual, spectral_truth = values(spectral_fields)
    entropy_actual, entropy_truth = values(entanglement_fields)
    mz_actual, mz_truth = values(magnetization_fields)
    spectral_error = normalized_rmse(spectral_actual, spectral_truth, 2.0e-8, 1.0e-7)
    entropy_error = normalized_rmse(entropy_actual, entropy_truth, 2.0e-8, 1.0e-7)
    magnetization_error = normalized_rmse(mz_actual, mz_truth, 2.0e-8, 1.0e-7)
    index_fraction = float(
        np.mean(
            [
                parsed["states"][key]["eigen_index"] == expected["states"][key]["eigen_index"]
                for key in state_keys
            ]
        )
    )
    spectral_score = min(index_fraction, quality(spectral_error))

    aggregate_keys = sorted(expected["aggregates"])
    aggregate_float_fields = tuple(
        sorted(field for field in AGGREGATE_KEYS if field.startswith("mean_") or field.startswith("sem_"))
    )
    aggregate_actual = [
        float(parsed["aggregates"][key][field])
        for key in aggregate_keys
        for field in aggregate_float_fields
    ]
    aggregate_truth = [
        float(expected["aggregates"][key][field])
        for key in aggregate_keys
        for field in aggregate_float_fields
    ]
    aggregate_error = normalized_rmse(aggregate_actual, aggregate_truth, 5.0e-8, 2.0e-7)
    aggregate_identity_fraction = float(
        np.mean(
            [
                all(
                    parsed["aggregates"][key][field] == expected["aggregates"][key][field]
                    for field in (
                        "condition_id",
                        "query_id",
                        "subsystem_start",
                        "subsystem_size",
                        "realization_count",
                        "state_count",
                    )
                )
                for key in aggregate_keys
            ]
        )
    )
    aggregate_score = min(aggregate_identity_fraction, quality(aggregate_error))

    claim_keys = sorted(expected["conclusions"])
    conclusion_fraction = float(
        np.mean(
            [
                parsed["conclusions"][key][field] == expected["conclusions"][key][field]
                for key in claim_keys
                for field in (
                    "metric",
                    "direction",
                    "positive_effect",
                    "weak_aggregate_id",
                    "strong_aggregate_id",
                )
            ]
        )
    )
    effect_error = normalized_rmse(
        [float(parsed["conclusions"][key]["effect"]) for key in claim_keys],
        [float(expected["conclusions"][key]["effect"]) for key in claim_keys],
        5.0e-8,
        2.0e-7,
    )
    evidence_score = min(conclusion_fraction, quality(effect_error))
    return {
        "spectral_packet": {"score": spectral_score, "normalized_rmse": spectral_error, "index_fraction": index_fraction},
        "entanglement_participation": {"score": quality(entropy_error), "normalized_rmse": entropy_error},
        "magnetization": {"score": quality(magnetization_error), "normalized_rmse": magnetization_error},
        "realization_aggregation": {"score": aggregate_score, "normalized_rmse": aggregate_error},
        "evidence_consistency": {"score": evidence_score, "normalized_rmse": effect_error},
    }
