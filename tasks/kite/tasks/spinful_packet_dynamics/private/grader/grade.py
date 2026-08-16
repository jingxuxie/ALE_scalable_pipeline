#!/usr/bin/env python3
"""Strict, deterministic, non-executing evaluator for submitted artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np


TASK_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_INPUT = TASK_ROOT / "participant" / "input"
REFERENCE = TASK_ROOT / "private" / "reference"
HIDDEN_REFERENCE = TASK_ROOT / "private" / "reference_hidden"
HIDDEN_INPUT = TASK_ROOT / "private" / "hidden_inputs"
REQUIRED_FILES = {"basis.npz", "trajectories.csv", "ensemble.csv", "analysis.json"}
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_NPZ_UNCOMPRESSED = 10 * 1024 * 1024
MAX_TEXT_BYTES = 512 * 1024

TRAJECTORY_COLUMNS = [
    "realization_id",
    "disorder_model",
    "time",
    "norm",
    "sx",
    "sy",
    "sz",
    "mean_x",
    "mean_y",
    "second_x",
    "second_y",
    "second_xy",
]
OBSERVABLES = TRAJECTORY_COLUMNS[3:]
ENSEMBLE_COLUMNS = ["disorder_model", "time", "count"] + [
    f"{name}_{suffix}" for name in OBSERVABLES for suffix in ("mean", "std")
]


class GateFailure(Exception):
    """A structural failure that must produce score zero."""


def _is_link_or_reparse(path: Path) -> bool:
    try:
        information = path.lstat()
    except OSError:
        return False
    attributes = int(getattr(information, "st_file_attributes", 0))
    return stat.S_ISLNK(information.st_mode) or bool(attributes & 0x400)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def load_json(path: Path) -> Any:
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise GateFailure(f"text artifact too large: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise GateFailure(f"invalid JSON in {path.name}: {error}") from error


def read_csv(path: Path, expected_header: list[str]) -> list[dict[str, str]]:
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise GateFailure(f"text artifact too large: {path.name}")
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != expected_header:
                raise GateFailure(f"wrong header in {path.name}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as error:
        raise GateFailure(f"invalid CSV in {path.name}: {error}") from error
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise GateFailure(f"ragged CSV in {path.name}")
    return rows


def public_metadata() -> dict[str, Any]:
    config = load_json(PUBLIC_INPUT / "config.json")
    sites = read_csv(PUBLIC_INPUT / "sites.csv", ["site_id", "x", "y"])
    bonds = read_csv(PUBLIC_INPUT / "bonds.csv", ["bond_id", "source_id", "target_id", "phi"])
    realizations = read_csv(
        PUBLIC_INPUT / "realizations.csv",
        ["realization_id", "disorder_model", "center", "half_width"],
    )
    onsite = read_csv(
        PUBLIC_INPUT / "onsite.csv", ["realization_id", "site_id", "u", "m_z"]
    )
    times = [float(row["time"]) for row in read_csv(PUBLIC_INPUT / "times.csv", ["time"])]
    return {
        "config": config,
        "sites": sites,
        "bonds": bonds,
        "realizations": realizations,
        "onsite": onsite,
        "times": times,
    }


def validate_submission_tree(root: Path) -> None:
    if _is_link_or_reparse(root) or not root.exists() or not root.is_dir():
        raise GateFailure("submission root must be a real directory")
    entries = list(root.iterdir())
    names = {entry.name for entry in entries}
    if names != REQUIRED_FILES:
        missing = sorted(REQUIRED_FILES - names)
        unexpected = sorted(names - REQUIRED_FILES)
        raise GateFailure(f"artifact set mismatch; missing={missing}, unexpected={unexpected}")
    total = 0
    for entry in entries:
        try:
            mode = entry.lstat().st_mode
        except OSError as error:
            raise GateFailure(f"cannot inspect {entry.name}: {error}") from error
        if _is_link_or_reparse(entry) or not stat.S_ISREG(mode):
            raise GateFailure(f"{entry.name} is not a regular file")
        total += entry.stat().st_size
    if total > MAX_TOTAL_BYTES:
        raise GateFailure(f"submission exceeds {MAX_TOTAL_BYTES} bytes")


def safe_basis(path: Path, metadata: dict[str, Any]) -> np.ndarray:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if len(infos) != 5:
                raise GateFailure("basis.npz must contain exactly five array members")
            if any(info.is_dir() or not info.filename.endswith(".npy") for info in infos):
                raise GateFailure("basis.npz has an invalid archive member")
            if any("/" in info.filename or "\\" in info.filename for info in infos):
                raise GateFailure("basis.npz has a nested archive member")
            if sum(info.file_size for info in infos) > MAX_NPZ_UNCOMPRESSED:
                raise GateFailure("basis.npz expands beyond the safe limit")
    except (OSError, zipfile.BadZipFile) as error:
        raise GateFailure(f"basis.npz is not a valid NPZ archive: {error}") from error
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != {
                "basis",
                "realization_ids",
                "site_ids",
                "orders",
                "instance_id",
            }:
                raise GateFailure("basis.npz array names do not match the contract")
            arrays = {name: np.array(archive[name], copy=True) for name in archive.files}
    except GateFailure:
        raise
    except Exception as error:
        raise GateFailure(f"basis.npz could not be loaded safely: {error}") from error

    realizations = metadata["realizations"]
    sites = metadata["sites"]
    order = int(metadata["config"]["basis_order"])
    expected_shape = (len(realizations), order, len(sites), 2)
    if arrays["basis"].shape != expected_shape or arrays["basis"].dtype != np.complex128:
        raise GateFailure(f"basis has wrong shape or dtype; expected {expected_shape} complex128")
    expected_realizations = np.asarray(
        [row["realization_id"] for row in realizations], dtype=np.str_
    )
    expected_sites = np.asarray([row["site_id"] for row in sites], dtype=np.str_)
    if arrays["realization_ids"].ndim != 1 or not np.array_equal(
        arrays["realization_ids"], expected_realizations
    ):
        raise GateFailure("realization_ids are missing, stale, or out of order")
    if arrays["site_ids"].ndim != 1 or not np.array_equal(arrays["site_ids"], expected_sites):
        raise GateFailure("site_ids are missing, stale, or out of order")
    if arrays["orders"].dtype != np.int64 or not np.array_equal(
        arrays["orders"], np.arange(order, dtype=np.int64)
    ):
        raise GateFailure("orders must be int64 arange(basis_order)")
    if arrays["instance_id"].shape != () or str(arrays["instance_id"].item()) != str(
        metadata["config"]["instance_id"]
    ):
        raise GateFailure("basis.npz has a stale instance_id")
    if not np.isfinite(arrays["basis"].real).all() or not np.isfinite(
        arrays["basis"].imag
    ).all():
        raise GateFailure("basis contains NaN or infinity")
    return arrays["basis"]


def _canonical_time(value: str, times: list[float], artifact: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise GateFailure(f"non-numeric time in {artifact}") from error
    if not math.isfinite(parsed):
        raise GateFailure(f"non-finite time in {artifact}")
    matches = [time for time in times if abs(parsed - time) <= 2.0e-12]
    if len(matches) != 1:
        raise GateFailure(f"unexpected time {parsed!r} in {artifact}")
    return matches[0]


def parse_trajectories(
    path: Path, metadata: dict[str, Any]
) -> dict[tuple[str, float], dict[str, float | str]]:
    rows = read_csv(path, TRAJECTORY_COLUMNS)
    realizations = metadata["realizations"]
    model_by_id = {row["realization_id"]: row["disorder_model"] for row in realizations}
    times = metadata["times"]
    expected_count = len(realizations) * len(times)
    if len(rows) != expected_count:
        raise GateFailure(f"trajectories.csv must have {expected_count} rows")
    parsed: dict[tuple[str, float], dict[str, float | str]] = {}
    for row in rows:
        realization_id = row["realization_id"]
        if realization_id not in model_by_id or row["disorder_model"] != model_by_id[realization_id]:
            raise GateFailure("unknown realization/model pair in trajectories.csv")
        time = _canonical_time(row["time"], times, "trajectories.csv")
        key = (realization_id, time)
        if key in parsed:
            raise GateFailure("duplicate trajectory key")
        values: dict[str, float | str] = {"disorder_model": row["disorder_model"]}
        for name in OBSERVABLES:
            try:
                value = float(row[name])
            except ValueError as error:
                raise GateFailure(f"non-numeric {name} in trajectories.csv") from error
            if not math.isfinite(value):
                raise GateFailure(f"non-finite {name} in trajectories.csv")
            values[name] = value
        parsed[key] = values
    if len(parsed) != expected_count:
        raise GateFailure("trajectories.csv is incomplete")
    return parsed


def parse_ensemble(
    path: Path, metadata: dict[str, Any]
) -> dict[tuple[str, float], dict[str, float]]:
    rows = read_csv(path, ENSEMBLE_COLUMNS)
    models = list(dict.fromkeys(row["disorder_model"] for row in metadata["realizations"]))
    times = metadata["times"]
    expected_count = len(models) * len(times)
    if len(rows) != expected_count:
        raise GateFailure(f"ensemble.csv must have {expected_count} rows")
    parsed: dict[tuple[str, float], dict[str, float]] = {}
    expected_members = {
        model: sum(row["disorder_model"] == model for row in metadata["realizations"])
        for model in models
    }
    for row in rows:
        model = row["disorder_model"]
        if model not in models:
            raise GateFailure("unknown model in ensemble.csv")
        time = _canonical_time(row["time"], times, "ensemble.csv")
        key = (model, time)
        if key in parsed:
            raise GateFailure("duplicate ensemble key")
        try:
            count = int(row["count"])
        except ValueError as error:
            raise GateFailure("non-integer ensemble count") from error
        if str(count) != row["count"].strip() or count != expected_members[model]:
            raise GateFailure("wrong ensemble count")
        values: dict[str, float] = {}
        for name in ENSEMBLE_COLUMNS[3:]:
            try:
                value = float(row[name])
            except ValueError as error:
                raise GateFailure(f"non-numeric {name} in ensemble.csv") from error
            if not math.isfinite(value):
                raise GateFailure(f"non-finite {name} in ensemble.csv")
            values[name] = value
        parsed[key] = values
    if len(parsed) != expected_count:
        raise GateFailure("ensemble.csv is incomplete")
    return parsed


def _finite_tree(value: Any) -> bool:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_finite_tree(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _finite_tree(item) for key, item in value.items())
    return False


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateFailure(f"analysis field {field} must be numeric")
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise GateFailure(f"analysis field {field} cannot be represented as float64") from error
    if not math.isfinite(converted):
        raise GateFailure(f"analysis field {field} must be finite")
    return converted


def parse_analysis(path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    analysis = load_json(path)
    if not isinstance(analysis, dict) or set(analysis) != {
        "schema_version",
        "instance_id",
        "basis_order",
        "bounds",
        "contrasts",
        "conclusion",
    }:
        raise GateFailure("analysis.json top-level schema mismatch")
    config = metadata["config"]
    if analysis["schema_version"] != "spinful-packet-analysis/v1":
        raise GateFailure("wrong analysis schema version")
    if analysis["instance_id"] != config["instance_id"]:
        raise GateFailure("analysis.json has a stale instance_id")
    if type(analysis["basis_order"]) is not int or analysis["basis_order"] != int(
        config["basis_order"]
    ):
        raise GateFailure("analysis.json has the wrong basis order")
    realizations = metadata["realizations"]
    if not isinstance(analysis["bounds"], list) or len(analysis["bounds"]) != len(realizations):
        raise GateFailure("bounds list is incomplete")
    bound_keys = {
        "realization_id",
        "eigenvalue_min",
        "eigenvalue_max",
        "scaled_radius",
        "within_declared_interval",
    }
    for expected, record in zip(realizations, analysis["bounds"]):
        if not isinstance(record, dict) or set(record) != bound_keys:
            raise GateFailure("bound object schema mismatch")
        if record["realization_id"] != expected["realization_id"]:
            raise GateFailure("bound realization order mismatch")
        for field in ("eigenvalue_min", "eigenvalue_max", "scaled_radius"):
            _finite_number(record[field], field)
        if type(record["within_declared_interval"]) is not bool:
            raise GateFailure("bound interval flag must be Boolean")
    contrast_keys = {
        "time",
        "scalar_sz_mean",
        "scalar_ising_sz_mean",
        "delta_sz",
        "scalar_spread_mean",
        "scalar_ising_spread_mean",
        "delta_spread",
    }
    if not isinstance(analysis["contrasts"], list) or len(analysis["contrasts"]) != len(
        metadata["times"]
    ):
        raise GateFailure("contrasts list is incomplete")
    for expected_time, record in zip(metadata["times"], analysis["contrasts"]):
        if not isinstance(record, dict) or set(record) != contrast_keys:
            raise GateFailure("contrast object schema mismatch")
        for field in contrast_keys:
            _finite_number(record[field], field)
        if abs(float(record["time"]) - expected_time) > 2e-12:
            raise GateFailure("contrast time order mismatch")
    conclusion = analysis["conclusion"]
    if not isinstance(conclusion, dict) or set(conclusion) != {
        "comparison_time",
        "smaller_final_abs_sz_model",
        "greater_spreading_model",
    }:
        raise GateFailure("conclusion schema mismatch")
    if not isinstance(conclusion["smaller_final_abs_sz_model"], str) or conclusion[
        "smaller_final_abs_sz_model"
    ] not in {"scalar", "scalar_ising", "tie"}:
        raise GateFailure("invalid spin conclusion")
    if not isinstance(conclusion["greater_spreading_model"], str) or conclusion[
        "greater_spreading_model"
    ] not in {"scalar", "scalar_ising", "tie"}:
        raise GateFailure("invalid spreading conclusion")
    _finite_number(conclusion["comparison_time"], "comparison_time")
    if not _finite_tree(analysis):
        raise GateFailure("analysis.json contains non-finite or unsupported values")
    return analysis


def bessel_sequence(argument: float, count: int) -> np.ndarray:
    x = float(argument)
    result = np.zeros(count, dtype=np.float64)
    if x == 0.0:
        result[0] = 1.0
        return result
    sign_x = -1 if x < 0.0 else 1
    magnitude = abs(x)
    for n in range(count):
        term = math.exp(n * math.log(magnitude / 2.0) - math.lgamma(n + 1.0))
        total = term
        k = 0
        while k < 512:
            k += 1
            term *= -(magnitude * magnitude / 4.0) / (k * (n + k))
            total += term
            if abs(term) <= 1.0e-16 * max(1.0, abs(total)):
                break
        result[n] = total * ((-1) ** n if sign_x < 0 else 1)
    return result


def state_observables(state: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    spinors = state.reshape(x.size, 2)
    alpha, beta = spinors[:, 0], spinors[:, 1]
    probability = np.abs(alpha) ** 2 + np.abs(beta) ** 2
    norm = probability.sum()
    overlap = np.conj(alpha) * beta
    return np.array(
        [
            norm,
            2.0 * np.real(overlap).sum(),
            2.0 * np.imag(overlap).sum(),
            (np.abs(alpha) ** 2 - np.abs(beta) ** 2).sum(),
            np.dot(x, probability) / norm,
            np.dot(y, probability) / norm,
            np.dot(x * x, probability) / norm,
            np.dot(y * y, probability) / norm,
            np.dot(x * y, probability) / norm,
        ],
        dtype=np.float64,
    )


def contract_observables(
    basis: np.ndarray, metadata: dict[str, Any], times: list[float]
) -> dict[tuple[str, float], dict[str, float | str]]:
    sites = metadata["sites"]
    x = np.asarray([float(row["x"]) for row in sites], dtype=np.float64)
    y = np.asarray([float(row["y"]) for row in sites], dtype=np.float64)
    answer: dict[tuple[str, float], dict[str, float | str]] = {}
    orders = np.arange(basis.shape[1])
    for index, realization in enumerate(metadata["realizations"]):
        center = float(realization["center"])
        half_width = float(realization["half_width"])
        flat_basis = basis[index].reshape(basis.shape[1], -1)
        for time in times:
            coefficients = bessel_sequence(half_width * time, basis.shape[1]).astype(np.complex128)
            coefficients[1:] *= 2.0 * (-1.0j) ** orders[1:]
            state = np.exp(-1.0j * center * time) * np.einsum(
                "n,nd->d", coefficients, flat_basis
            )
            values = state_observables(state, x, y)
            record: dict[str, float | str] = {"disorder_model": realization["disorder_model"]}
            record.update({name: float(value) for name, value in zip(OBSERVABLES, values)})
            answer[(realization["realization_id"], time)] = record
    return answer


def recompute_ensemble(
    trajectory: dict[tuple[str, float], dict[str, float | str]], metadata: dict[str, Any]
) -> dict[tuple[str, float], dict[str, float]]:
    answer: dict[tuple[str, float], dict[str, float]] = {}
    models = list(dict.fromkeys(row["disorder_model"] for row in metadata["realizations"]))
    ids_by_model = {
        model: [
            row["realization_id"]
            for row in metadata["realizations"]
            if row["disorder_model"] == model
        ]
        for model in models
    }
    for model in models:
        for time in metadata["times"]:
            record: dict[str, float] = {}
            for name in OBSERVABLES:
                values = np.asarray(
                    [float(trajectory[(rid, time)][name]) for rid in ids_by_model[model]],
                    dtype=np.float64,
                )
                with np.errstate(over="ignore", invalid="ignore"):
                    mean_value = float(values.mean())
                    std_value = float(values.std(ddof=0))
                record[f"{name}_mean"] = (
                    mean_value if math.isfinite(mean_value) else math.copysign(1.0e300, mean_value)
                )
                record[f"{name}_std"] = std_value if math.isfinite(std_value) else 1.0e300
            answer[(model, time)] = record
    return answer


def numeric_score(
    observed: np.ndarray, reference: np.ndarray, absolute: float, relative: float
) -> tuple[float, float]:
    observed = np.asarray(observed)
    reference = np.asarray(reference)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        denominator = np.maximum(absolute, relative * np.abs(reference))
        standardized = np.abs(observed - reference) / denominator
        rms = float(np.sqrt(np.mean(np.square(standardized, dtype=np.float64))))
    if not math.isfinite(rms):
        return 0.0, 1.0e300
    return 1.0 / (1.0 + rms), rms


def keyed_numeric(
    observed: dict[Any, dict[str, float | str]],
    reference: dict[Any, dict[str, float | str]],
    columns: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    keys = sorted(reference, key=lambda item: str(item))
    return (
        np.asarray([float(observed[key][column]) for key in keys for column in columns]),
        np.asarray([float(reference[key][column]) for key in keys for column in columns]),
    )


def analysis_vectors(analysis: dict[str, Any]) -> tuple[np.ndarray, tuple[Any, ...]]:
    numeric: list[float] = []
    categories: list[Any] = []
    for bound in analysis["bounds"]:
        numeric.extend(
            [bound["eigenvalue_min"], bound["eigenvalue_max"], bound["scaled_radius"]]
        )
        categories.append(bound["within_declared_interval"])
    for contrast in analysis["contrasts"]:
        numeric.extend(
            [
                contrast["time"],
                contrast["scalar_sz_mean"],
                contrast["scalar_ising_sz_mean"],
                contrast["delta_sz"],
                contrast["scalar_spread_mean"],
                contrast["scalar_ising_spread_mean"],
                contrast["delta_spread"],
            ]
        )
    conclusion = analysis["conclusion"]
    numeric.append(conclusion["comparison_time"])
    categories.extend(
        [
            conclusion["smaller_final_abs_sz_model"],
            conclusion["greater_spreading_model"],
        ]
    )
    return np.asarray(numeric, dtype=np.float64), tuple(categories)


def recompute_analysis_from_trajectory(
    trajectory: dict[tuple[str, float], dict[str, float | str]],
    metadata: dict[str, Any],
    trusted_bounds: list[dict[str, Any]],
) -> dict[str, Any]:
    def central_spread(member: dict[str, float | str]) -> float:
        with np.errstate(over="ignore", invalid="ignore"):
            value = (
                np.float64(member["second_x"])
                - np.square(np.float64(member["mean_x"]))
                + np.float64(member["second_y"])
                - np.square(np.float64(member["mean_y"]))
            )
        if not np.isfinite(value):
            if np.isnan(value):
                return 1.0e300
            return math.copysign(1.0e300, float(value))
        return float(np.clip(value, -1.0e300, 1.0e300))

    ids_by_model = {
        model: [
            row["realization_id"]
            for row in metadata["realizations"]
            if row["disorder_model"] == model
        ]
        for model in ("scalar", "scalar_ising")
    }
    contrasts: list[dict[str, float]] = []
    for time in metadata["times"]:
        sz: dict[str, float] = {}
        spread: dict[str, float] = {}
        for model, realization_ids in ids_by_model.items():
            members = [trajectory[(realization_id, time)] for realization_id in realization_ids]
            sz[model] = float(np.mean([float(member["sz"]) for member in members]))
            spread[model] = float(
                np.mean(
                    [central_spread(member) for member in members],
                    dtype=np.float64,
                )
            )
        contrasts.append(
            {
                "time": float(time),
                "scalar_sz_mean": sz["scalar"],
                "scalar_ising_sz_mean": sz["scalar_ising"],
                "delta_sz": sz["scalar_ising"] - sz["scalar"],
                "scalar_spread_mean": spread["scalar"],
                "scalar_ising_spread_mean": spread["scalar_ising"],
                "delta_spread": spread["scalar_ising"] - spread["scalar"],
            }
        )
    final = contrasts[-1]
    scalar_abs = abs(final["scalar_sz_mean"])
    ising_abs = abs(final["scalar_ising_sz_mean"])
    if abs(scalar_abs - ising_abs) <= 1.0e-14:
        smaller_abs_sz = "tie"
    else:
        smaller_abs_sz = "scalar" if scalar_abs < ising_abs else "scalar_ising"
    scalar_spread = final["scalar_spread_mean"]
    ising_spread = final["scalar_ising_spread_mean"]
    if abs(scalar_spread - ising_spread) <= 1.0e-14:
        greater_spreading = "tie"
    else:
        greater_spreading = "scalar" if scalar_spread > ising_spread else "scalar_ising"
    return {
        "schema_version": "spinful-packet-analysis/v1",
        "instance_id": metadata["config"]["instance_id"],
        "basis_order": int(metadata["config"]["basis_order"]),
        "bounds": trusted_bounds,
        "contrasts": contrasts,
        "conclusion": {
            "comparison_time": float(metadata["times"][-1]),
            "smaller_final_abs_sz_model": smaller_abs_sz,
            "greater_spreading_model": greater_spreading,
        },
    }


def grade(submission_root: Path) -> dict[str, Any]:
    try:
        metadata = public_metadata()
        validate_submission_tree(submission_root)
        submitted_basis = safe_basis(submission_root / "basis.npz", metadata)
        submitted_trajectory = parse_trajectories(
            submission_root / "trajectories.csv", metadata
        )
        submitted_ensemble = parse_ensemble(submission_root / "ensemble.csv", metadata)
        submitted_analysis = parse_analysis(submission_root / "analysis.json", metadata)

        reference_basis = safe_basis(REFERENCE / "basis.npz", metadata)
        reference_trajectory = parse_trajectories(REFERENCE / "trajectories.csv", metadata)
        reference_ensemble = parse_ensemble(REFERENCE / "ensemble.csv", metadata)
        reference_analysis = parse_analysis(REFERENCE / "analysis.json", metadata)
        hidden_spec = load_json(HIDDEN_INPUT / "private_times.json")
        if hidden_spec["instance_id"] != metadata["config"]["instance_id"]:
            raise GateFailure("private time suite does not match the public instance")
        hidden_times = [float(value) for value in hidden_spec["times"]]
        hidden_reference_metadata = dict(metadata)
        hidden_reference_metadata["times"] = hidden_times
        hidden_reference = parse_trajectories(
            HIDDEN_REFERENCE / "hidden_trajectories.csv", hidden_reference_metadata
        )
    except GateFailure as error:
        return {
            "schema_version": "spinful-packet-grade/v1",
            "passed": False,
            "score": 0.0,
            "hard_gate_failures": [str(error)],
            "metrics": {},
        }

    basis_score, basis_error = numeric_score(
        submitted_basis, reference_basis, absolute=2.0e-10, relative=2.0e-8
    )
    hidden_observed = contract_observables(submitted_basis, metadata, hidden_times)
    hidden_values, hidden_truth = keyed_numeric(hidden_observed, hidden_reference, OBSERVABLES)
    hidden_score, hidden_error = numeric_score(
        hidden_values, hidden_truth, absolute=2.0e-8, relative=1.0e-7
    )

    public_from_basis = contract_observables(submitted_basis, metadata, metadata["times"])
    submitted_values, reference_values = keyed_numeric(
        submitted_trajectory, reference_trajectory, OBSERVABLES
    )
    _, basis_values = keyed_numeric(submitted_trajectory, public_from_basis, OBSERVABLES)
    public_reference_score, public_reference_error = numeric_score(
        submitted_values, reference_values, absolute=2.0e-8, relative=1.0e-7
    )
    public_consistency_score, public_consistency_error = numeric_score(
        submitted_values, basis_values, absolute=2.0e-8, relative=1.0e-7
    )
    public_score = min(public_reference_score, public_consistency_score)

    recomputed_ensemble = recompute_ensemble(submitted_trajectory, metadata)
    ensemble_values, ensemble_truth = keyed_numeric(
        submitted_ensemble, reference_ensemble, ENSEMBLE_COLUMNS[3:]
    )
    _, ensemble_recomputed = keyed_numeric(
        submitted_ensemble, recomputed_ensemble, ENSEMBLE_COLUMNS[3:]
    )
    ensemble_reference_score, ensemble_reference_error = numeric_score(
        ensemble_values, ensemble_truth, absolute=3.0e-8, relative=2.0e-7
    )
    ensemble_consistency_score, ensemble_consistency_error = numeric_score(
        ensemble_values, ensemble_recomputed, absolute=3.0e-8, relative=2.0e-7
    )
    ensemble_score = min(ensemble_reference_score, ensemble_consistency_score)

    analysis_values, analysis_categories = analysis_vectors(submitted_analysis)
    analysis_truth, truth_categories = analysis_vectors(reference_analysis)
    analysis_reference_score, analysis_reference_error = numeric_score(
        analysis_values, analysis_truth, absolute=5.0e-8, relative=3.0e-7
    )
    recomputed_analysis = recompute_analysis_from_trajectory(
        submitted_trajectory, metadata, reference_analysis["bounds"]
    )
    analysis_recomputed, recomputed_categories = analysis_vectors(recomputed_analysis)
    analysis_evidence_score, analysis_evidence_error = numeric_score(
        analysis_values, analysis_recomputed, absolute=5.0e-8, relative=3.0e-7
    )
    analysis_numeric_score = min(analysis_reference_score, analysis_evidence_score)
    reference_category_score = sum(
        a == b for a, b in zip(analysis_categories, truth_categories)
    ) / len(truth_categories)
    evidence_category_score = sum(
        a == b for a, b in zip(analysis_categories, recomputed_categories)
    ) / len(recomputed_categories)
    category_score = min(reference_category_score, evidence_category_score)
    categories_exact = (
        analysis_categories == truth_categories
        and analysis_categories == recomputed_categories
    )
    analysis_score = 0.8 * analysis_numeric_score + 0.2 * category_score

    weights = {
        "recurrence-basis": 0.30,
        "hidden-time-contraction": 0.25,
        "public-trajectories": 0.20,
        "ensemble-aggregation": 0.12,
        "evidence-consistency": 0.13,
    }
    component_scores = {
        "recurrence-basis": basis_score,
        "hidden-time-contraction": hidden_score,
        "public-trajectories": public_score,
        "ensemble-aggregation": ensemble_score,
        "evidence-consistency": analysis_score,
    }
    total = float(sum(weights[name] * component_scores[name] for name in weights))
    mandatory = all(component_scores[name] >= 0.90 for name in component_scores) and categories_exact
    passed = bool(total >= 0.96 and mandatory)
    return {
        "schema_version": "spinful-packet-grade/v1",
        "passed": passed,
        "score": total,
        "hard_gate_failures": [],
        "metrics": {
            "recurrence-basis": {"score": basis_score, "normalized_rms_error": basis_error},
            "hidden-time-contraction": {
                "score": hidden_score,
                "normalized_rms_error": hidden_error,
            },
            "public-trajectories": {
                "score": public_score,
                "reference_normalized_rms_error": public_reference_error,
                "basis_consistency_normalized_rms_error": public_consistency_error,
            },
            "ensemble-aggregation": {
                "score": ensemble_score,
                "reference_normalized_rms_error": ensemble_reference_error,
                "trajectory_consistency_normalized_rms_error": ensemble_consistency_error,
            },
            "evidence-consistency": {
                "score": analysis_score,
                "reference_normalized_rms_error": analysis_reference_error,
                "trajectory_consistency_normalized_rms_error": analysis_evidence_error,
                "categorical_fraction": category_score,
                "categorical_exact": categories_exact,
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", type=Path)
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args()
    result = grade(arguments.submission)
    print(
        json.dumps(
            result,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
            allow_nan=False,
        )
    )
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
