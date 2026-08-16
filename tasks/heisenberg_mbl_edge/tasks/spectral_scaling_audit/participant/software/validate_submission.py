#!/usr/bin/env python3
"""Public validator for the finite-size spectral crossover analyzer.

This is deliberately stronger than a shape-only checker: it rebuilds the
retired case's realization and grouped statistics from the raw eigenvalues and
checks the declared cubic diagnostics.  Its numeric cutoffs are public smoke-
test tolerances, not the private evaluation thresholds.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import subprocess
import sys
import tempfile
from typing import Any
import zipfile

import numpy as np


EXPECTED_OUTPUTS = {
    "realization_stats.csv": [
        "case_id", "target", "size", "control", "realization_id", "n_ratios", "mean_r",
    ],
    "packet_stats.csv": [
        "case_id", "target", "size", "control", "n_realizations", "n_ratios", "mean_r", "se_r",
    ],
    "transition.csv": [
        "case_id", "target", "h_c", "nu", "h_c_lo", "h_c_hi", "nu_lo", "nu_hi", "fit_score", "stable",
    ],
    "stability.csv": [
        "case_id", "target", "min_size", "halfwidth", "h_c", "nu", "validation_rmse", "n_groups", "fit_ok",
    ],
    "predictions.csv": ["query_id", "mean_r", "se_r"],
}
PACKET_COLUMNS = [
    "packet_id", "realization_id", "size", "control", "target", "e_min",
    "e_max", "shift_energy", "keep_count", "eigen_offset", "eigen_count",
]
QUERY_COLUMNS = ["query_id", "target", "size", "control"]
CLAIM_KEYS = {
    "schema_version", "case_id", "case_token", "finite_size_crossover", "phase_direction",
    "n_realizations", "n_groups", "n_targets", "low_control_mean_r", "high_control_mean_r",
}
ALLOWED_IMPORT_ROOTS = {
    "__future__", "argparse", "collections", "csv", "itertools", "json", "math", "numpy", "pathlib", "typing",
}
SOURCE_LIMIT = 250_000
LOG_LIMIT = 1_000_000
STAT_TOLERANCE = 5e-9
DIAGNOSTIC_TOLERANCE = 2e-7
PUBLIC_PREDICTION_TOLERANCE = 0.08
MAX_CASE_INPUT_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 65_536
MAX_NPZ_UNCOMPRESSED_BYTES = 40_020_000
MAX_NPY_HEADER_BYTES = 4_096
MAX_STANDARDIZED_QUERY = 2.0
MAX_CUBIC_CONDITION = 1e12
MAX_CUBIC_COEFFICIENT = 1e6
MAX_SCALING_COORDINATE = 2.1e36
MAX_RAW_CUBIC_PREDICTION = 2e7
AFFINE_ULP_MULTIPLIER = 2**20
AFFINE_CUTOFF_RELATIVE_MARGIN = 1e-8
AFFINE_GAP_RELATIVE_MARGIN = 1e-9
UINT64_MAX = 2**64 - 1
MAX_BOOTSTRAP_SEED = UINT64_MAX - 1009 * 7
MAX_CSV_FIELD_BYTES = 128
MAX_INTEGER_TEXT_DIGITS = 20
CSV_PARSER_FIELD_LIMIT = 1_024


def reject_json_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant {token!r}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def strict_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_json_constant,
        object_pairs_hook=reject_duplicate_keys,
    )
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: expected a JSON object")
    return value


def is_linklike(path: Path) -> bool:
    """Recognize symbolic links and Windows directory junctions when exposed."""
    if path.is_symlink():
        return True
    junction_test = getattr(path, "is_junction", None)
    return bool(junction_test()) if junction_test is not None else False


def require_single_link_file(path: Path, label: str) -> None:
    if is_linklike(path) or not path.is_file():
        raise ValueError(f"{label} must be a regular non-link file")
    if path.stat().st_nlink != 1:
        raise ValueError(f"{label} must not be hard-linked")


def canonical(value: float) -> float:
    return round(float(value), 10)


def finite_number(value: str | int | float, label: str) -> float:
    try:
        parsed = float(value)
    except Exception as error:
        raise ValueError(f"{label}: expected a number") from error
    if not math.isfinite(parsed):
        raise ValueError(f"{label}: value is not finite")
    return parsed


def json_number(value: Any, label: str) -> float:
    if type(value) not in {int, float}:
        raise ValueError(f"{label}: expected a JSON number, not {type(value).__name__}")
    return finite_number(value, label)


def json_integer(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label}: expected a JSON integer")
    return value


def integer_text(value: str, label: str) -> int:
    if (
        not 1 <= len(value) <= MAX_INTEGER_TEXT_DIGITS
        or not value.isascii()
        or not value.isdecimal()
    ):
        raise ValueError(
            f"{label}: expected 1 through {MAX_INTEGER_TEXT_DIGITS} unsigned "
            f"ASCII decimal digits, got {value!r}"
        )
    return int(value)


def read_rows(
    path: Path,
    columns: list[str],
    *,
    max_rows: int | None = None,
) -> list[dict[str, str]]:
    csv.field_size_limit(CSV_PARSER_FIELD_LIMIT)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                raise ValueError(
                    f"{path.name}: expected columns {columns}, got {reader.fieldnames}"
                )
            result = []
            for index, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"{path.name}:{index}: malformed CSV row")
                if any(
                    len(value.encode("utf-8")) > MAX_CSV_FIELD_BYTES
                    for value in row.values()
                ):
                    raise ValueError(
                        f"{path.name}:{index}: CSV field exceeds the public "
                        f"{MAX_CSV_FIELD_BYTES}-byte UTF-8 limit"
                    )
                result.append(row)
                if max_rows is not None and len(result) > max_rows:
                    raise ValueError(f"{path.name}: exceeds the public {max_rows}-row limit")
    except UnicodeError as error:
        raise ValueError(f"{path.name}: file is not UTF-8") from error
    except csv.Error as error:
        raise ValueError(f"{path.name}: invalid or oversized CSV field: {error}") from error
    if not result:
        raise ValueError(f"{path.name}: no data rows")
    return result


def preflight_case_files(input_dir: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    """Validate the flat five-file case inventory before reading bulk data."""
    root = input_dir.resolve()
    if is_linklike(input_dir) or not root.is_dir():
        raise ValueError("case directory must be a regular non-link directory")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("manifest files must be an object")
    resolved: dict[str, Path] = {}
    names: list[str] = []
    for role in ("packets", "eigenvalues", "queries", "analysis_grid"):
        name = files.get(role)
        if (
            not isinstance(name, str)
            or not name
            or len(name.encode("utf-8")) > 128
            or "/" in name
            or "\\" in name
            or PurePosixPath(name).is_absolute()
            or PureWindowsPath(name).is_absolute()
            or bool(PureWindowsPath(name).drive)
            or name in {".", "..", "manifest.json"}
        ):
            raise ValueError(f"manifest files.{role} must be a safe distinct filename")
        names.append(name)
    if len(set(names)) != 4:
        raise ValueError("manifest data filenames must be distinct")
    entries = list(root.iterdir())
    expected_names = {"manifest.json", *names}
    if {path.name for path in entries} != expected_names:
        raise ValueError("case directory must contain exactly the manifest and four named data files")
    total_bytes = 0
    for path in entries:
        require_single_link_file(path, f"case input {path.name}")
        total_bytes += path.stat().st_size
    if total_bytes > MAX_CASE_INPUT_BYTES:
        raise ValueError("case input exceeds the published 256 MiB physical-byte limit")
    for role, name in zip(("packets", "eigenvalues", "queries", "analysis_grid"), names):
        resolved[role] = root / name
    return resolved


def read_npy_header(member: Any, name: str) -> tuple[tuple[int, ...], bool, np.dtype, int]:
    """Read one bounded NPY header without allocating its array payload."""
    version = np.lib.format.read_magic(member)
    if version == (1, 0):
        shape, fortran_order, dtype = np.lib.format.read_array_header_1_0(
            member, max_header_size=MAX_NPY_HEADER_BYTES
        )
    elif version == (2, 0):
        shape, fortran_order, dtype = np.lib.format.read_array_header_2_0(
            member, max_header_size=MAX_NPY_HEADER_BYTES
        )
    else:
        raise ValueError(f"{name}: unsupported NPY header version {version}")
    return tuple(shape), bool(fortran_order), np.dtype(dtype), int(member.tell())


def preflight_npz(path: Path) -> dict[str, Any]:
    """Inspect physical ZIP members and NPY metadata before ``np.load``."""
    try:
        with zipfile.ZipFile(path, mode="r") as archive:
            members = archive.infolist()
            if any(
                member.orig_filename != member.filename
                or "\x00" in member.orig_filename
                or "\x00" in member.filename
                for member in members
            ):
                raise ValueError("NPZ physical member names must be exact and contain no NUL")
            names = [member.filename for member in members]
            if len(members) != 2 or names.count("schema_version.npy") != 1 or names.count("energies.npy") != 1:
                raise ValueError(
                    "eigenvalue NPZ must have exactly the two physical members "
                    "schema_version.npy and energies.npy"
                )
            if sum(member.file_size for member in members) > MAX_NPZ_UNCOMPRESSED_BYTES:
                raise ValueError("eigenvalue NPZ exceeds the published uncompressed-size bound")
            metadata: dict[str, Any] = {}
            for member in members:
                if member.flag_bits & 0x1:
                    raise ValueError("encrypted NPZ members are not allowed")
                if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValueError("unsupported NPZ compression method")
                with archive.open(member, mode="r") as stream:
                    shape, fortran_order, dtype, header_bytes = read_npy_header(stream, member.filename)
                if fortran_order:
                    raise ValueError(f"{member.filename}: Fortran-order storage is not allowed")
                item_count = math.prod(shape) if shape else 1
                payload_bytes = item_count * dtype.itemsize
                if header_bytes + payload_bytes != member.file_size:
                    raise ValueError(f"{member.filename}: physical size does not match its NPY header")
                metadata[member.filename] = {
                    "shape": shape,
                    "dtype": dtype,
                    "file_size": member.file_size,
                }
    except (OSError, zipfile.BadZipFile, EOFError) as error:
        raise ValueError(f"invalid eigenvalue NPZ container: {error}") from error
    schema = metadata["schema_version.npy"]
    energies = metadata["energies.npy"]
    if (
        schema["shape"] != ()
        or schema["dtype"].kind != "U"
        or schema["dtype"].itemsize > 256
        or schema["dtype"].fields is not None
        or schema["dtype"].subdtype is not None
    ):
        raise ValueError("schema_version.npy must be a bounded scalar Unicode array")
    if energies["dtype"] != np.dtype(np.float64) or len(energies["shape"]) != 1:
        raise ValueError("energies.npy header must declare one-dimensional float64 data")
    if not 1 <= energies["shape"][0] <= 5_000_000:
        raise ValueError("energies.npy header exceeds the published element-count bound")
    return metadata


def preliminary_center(target_rows: list[dict[str, Any]]) -> float:
    centers: list[float] = []
    for size in sorted({int(row["size"]) for row in target_rows}):
        curve = sorted(
            (row for row in target_rows if int(row["size"]) == size),
            key=lambda row: float(row["control"]),
        )
        controls = np.asarray([float(row["control"]) for row in curve], dtype=np.float64)
        values = np.asarray([float(row["mean_r"]) for row in curve], dtype=np.float64)
        flank = max(2, min(3, values.size // 3))
        midpoint = 0.5 * (float(np.median(values[:flank])) + float(np.median(values[-flank:])))
        candidates: list[float] = []
        for index in range(values.size - 1):
            left = float(values[index] - midpoint)
            right = float(values[index + 1] - midpoint)
            if left == 0.0:
                candidates.append(float(controls[index]))
            elif (
                ((left < 0.0 < right) or (left > 0.0 > right) or right == 0.0)
                and values[index + 1] != values[index]
            ):
                fraction = (midpoint - values[index]) / (values[index + 1] - values[index])
                candidates.append(
                    float(controls[index] + fraction * (controls[index + 1] - controls[index]))
                )
        if candidates:
            middle = float(np.median(controls))
            centers.append(min(candidates, key=lambda value: abs(value - middle)))
    if centers:
        return float(np.median(np.asarray(centers, dtype=np.float64)))
    return float(np.median(np.asarray([float(row["control"]) for row in target_rows])))


def cubic_diagnostic(
    target_rows: list[dict[str, Any]],
    h_c: float,
    nu: float,
    min_size: int,
    halfwidth: float,
) -> dict[str, Any]:
    if not math.isfinite(h_c) or not math.isfinite(nu) or nu <= 0.0:
        raise ValueError("cubic diagnostic received invalid h_c/nu")
    center = preliminary_center(target_rows)
    selected = [
        row for row in target_rows
        if int(row["size"]) >= min_size
        and abs(float(row["control"]) - center) <= halfwidth * (1.0 + 1e-12)
    ]
    if len(selected) < 8 or len({int(row["size"]) for row in selected}) < 3:
        raise ValueError("cubic diagnostic has insufficient selected support")
    control = np.asarray([float(row["control"]) for row in selected], dtype=np.float64)
    size = np.asarray([float(row["size"]) for row in selected], dtype=np.float64)
    observed = np.asarray([float(row["mean_r"]) for row in selected], dtype=np.float64)
    se = np.asarray([max(float(row["se_r"]), 0.0025) for row in selected], dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        x = (control - h_c) * np.power(size, 1.0 / nu)
    if not np.all(np.isfinite(x)) or float(np.max(np.abs(x))) > MAX_SCALING_COORDINATE:
        raise ValueError("cubic diagnostic scaling coordinate exceeds the public float64 bound")
    scale = max(float(np.max(np.abs(x))), 1.0)
    z = x / scale
    if not np.all(np.isfinite(z)) or np.any(np.abs(z) > 1.0 + 8.0 * np.finfo(np.float64).eps):
        raise ValueError("cubic diagnostic standardized coordinates are invalid")
    matrix = np.column_stack([np.ones(z.size), z, z * z, z * z * z])
    weights = 1.0 / se
    weighted_matrix = matrix * weights[:, None]
    weighted_observed = observed * weights
    if not np.all(np.isfinite(weighted_matrix)) or not np.all(np.isfinite(weighted_observed)):
        raise ValueError("cubic diagnostic weighted system is non-finite")
    condition = float(np.linalg.cond(weighted_matrix))
    if not math.isfinite(condition) or condition > MAX_CUBIC_CONDITION:
        raise ValueError("cubic diagnostic exceeds the public conditioning bound")
    coefficients, _, rank, _ = np.linalg.lstsq(
        weighted_matrix, weighted_observed, rcond=None
    )
    if (
        rank < 4
        or not np.all(np.isfinite(coefficients))
        or float(np.max(np.abs(coefficients))) > MAX_CUBIC_COEFFICIENT
    ):
        raise ValueError("cubic diagnostic violates its rank/coefficient bound")
    residual = matrix @ coefficients - observed
    weighted_residual = residual * weights
    squared_residual = np.square(weighted_residual)
    squared_weight = np.square(weights)
    numerator = float(np.sum(squared_residual))
    denominator = float(np.sum(squared_weight))
    if (
        not np.all(np.isfinite(residual))
        or not np.all(np.isfinite(weighted_residual))
        or not np.all(np.isfinite(squared_residual))
        or not np.all(np.isfinite(squared_weight))
        or not math.isfinite(numerator)
        or numerator > 1e35
        or not math.isfinite(denominator)
        or denominator <= 0.0
    ):
        raise ValueError("cubic diagnostic residual reduction exceeds the public float64 bound")
    rmse = float(math.sqrt(numerator / denominator))
    if not math.isfinite(rmse):
        raise ValueError("cubic diagnostic produced a non-finite RMSE")
    return {
        "rmse": rmse,
        "n_groups": len(selected),
        "coefficients": coefficients,
        "x_scale": scale,
        "condition": condition,
    }


def load_expected(input_dir: Path) -> dict[str, Any]:
    if is_linklike(input_dir) or not input_dir.is_dir():
        raise ValueError("case input root must be a regular non-link directory")
    manifest_path = input_dir / "manifest.json"
    require_single_link_file(manifest_path, "case input manifest.json")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("manifest.json exceeds the published 65,536-byte bound")
    manifest = strict_json(manifest_path)
    if manifest.get("schema_version") != "spectral-scaling-input/v1":
        raise ValueError("manifest schema_version mismatch")
    required_file_roles = {"packets", "eigenvalues", "queries", "analysis_grid"}
    if set(manifest.get("files", {})) != required_file_roles:
        raise ValueError("manifest files object has unexpected roles")
    bootstrap_seed = json_integer(manifest.get("bootstrap_seed"), "manifest bootstrap_seed")
    if not 0 <= bootstrap_seed <= MAX_BOOTSTRAP_SEED:
        raise ValueError("manifest bootstrap_seed or a derived target seed exceeds uint64")
    for label in ("case_id", "case_token"):
        value = manifest.get(label)
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 48:
            raise ValueError(f"manifest {label} must be a nonempty string of at most 48 bytes")
    resource = manifest.get("resource_contract")
    expected_resource_keys = {
        "python", "numpy", "network", "wall_time_seconds", "output_bytes",
    }
    if not isinstance(resource, dict) or set(resource) != expected_resource_keys:
        raise ValueError("manifest resource_contract exact key set mismatch")
    if resource.get("python") != "3.11+":
        raise ValueError("resource_contract.python must equal '3.11+'")
    if resource.get("numpy") != "2.3.5" or resource.get("network") != "disabled":
        raise ValueError("resource_contract NumPy/network declaration mismatch")
    wall_time = json_integer(resource.get("wall_time_seconds"), "wall_time_seconds")
    output_bytes = json_integer(resource.get("output_bytes"), "output_bytes")
    if wall_time != 180 or not 1 <= output_bytes <= 4_000_000:
        raise ValueError("resource_contract wall time or output byte cap is invalid")
    packet_columns = manifest.get("packet_columns")
    query_columns = manifest.get("query_columns")
    if packet_columns != PACKET_COLUMNS:
        raise ValueError("manifest packet_columns does not match the exact v1 schema")
    if query_columns != QUERY_COLUMNS:
        raise ValueError("manifest query_columns does not match the exact v1 schema")
    case_files = preflight_case_files(input_dir, manifest)
    packet_rows = read_rows(case_files["packets"], packet_columns, max_rows=6_000)
    query_rows = read_rows(case_files["queries"], query_columns, max_rows=512)
    if case_files["analysis_grid"].stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("analysis-grid JSON exceeds the published 65,536-byte bound")
    grid = strict_json(case_files["analysis_grid"])
    expected_grid_keys = {
        "schema_version", "min_sizes", "halfwidths", "primary_min_size",
        "primary_halfwidth", "bootstrap_replicates", "interval_level",
    }
    if set(grid) != expected_grid_keys:
        raise ValueError("analysis-grid exact key set mismatch")
    if grid.get("schema_version") != "spectral-scaling-analysis-grid/v1":
        raise ValueError("analysis-grid schema_version mismatch")
    if json_number(grid.get("interval_level"), "interval_level") != 0.68:
        raise ValueError("v1 cases require interval_level=0.68")
    raw_min_sizes = grid.get("min_sizes")
    raw_halfwidths = grid.get("halfwidths")
    if not isinstance(raw_min_sizes, list) or not isinstance(raw_halfwidths, list):
        raise ValueError("analysis-grid min_sizes and halfwidths must be JSON arrays")
    min_sizes = [json_integer(value, "min_size") for value in raw_min_sizes]
    raw_numeric_halfwidths = [json_number(value, "halfwidth") for value in raw_halfwidths]
    halfwidths = [canonical(value) for value in raw_numeric_halfwidths]
    if not min_sizes or len(min_sizes) > 8 or len(set(min_sizes)) != len(min_sizes) or any(not 1 <= value <= 1_000_000 for value in min_sizes):
        raise ValueError("analysis-grid min_sizes is empty, duplicated, or invalid")
    if not halfwidths or len(halfwidths) > 8 or len(set(halfwidths)) != len(halfwidths) or any(not 0.4 <= value <= 1e6 for value in raw_numeric_halfwidths) or any(not 0.4 <= value <= 1e6 for value in halfwidths):
        raise ValueError("analysis-grid halfwidths is empty, duplicated, or invalid")
    stability_cells = len(min_sizes) * len(halfwidths)
    if not 2 <= stability_cells <= 24:
        raise ValueError("analysis-grid must contain from two through 24 stability cells")
    primary_min = json_integer(grid.get("primary_min_size"), "primary_min_size")
    primary_halfwidth = canonical(json_number(grid.get("primary_halfwidth"), "primary_halfwidth"))
    if primary_min not in min_sizes or primary_halfwidth not in set(halfwidths):
        raise ValueError("primary analysis-grid pair is not in the stability grid")
    bootstrap_replicates = json_integer(grid.get("bootstrap_replicates"), "bootstrap_replicates")
    if not 8 <= bootstrap_replicates <= 64:
        raise ValueError("bootstrap_replicates must be from eight through 64")

    archive_path = case_files["eigenvalues"]
    npz_metadata = preflight_npz(archive_path)
    header_energy_count = int(npz_metadata["energies.npy"]["shape"][0])
    preflight_offset = 0
    for index, row in enumerate(packet_rows, start=2):
        offset = integer_text(row["eigen_offset"], f"packets:{index}:eigen_offset")
        count = integer_text(row["eigen_count"], f"packets:{index}:eigen_count")
        keep = integer_text(row["keep_count"], f"packets:{index}:keep_count")
        if offset != preflight_offset or not 5 <= keep <= count <= 4096:
            raise ValueError(f"packets:{index}: offset/count fails the pre-allocation check")
        preflight_offset += count
        if preflight_offset > header_energy_count:
            raise ValueError("packet slices exceed the preflighted energies shape")
    if preflight_offset != header_energy_count:
        raise ValueError("packet slices do not match the preflighted energies shape")
    with np.load(archive_path, allow_pickle=False) as archive:
        if set(archive.files) != {"schema_version", "energies"}:
            raise ValueError("eigenvalue archive member mismatch")
        schema = np.asarray(archive["schema_version"])
        energies = np.asarray(archive["energies"])
    if schema.shape != () or schema.dtype.kind != "U" or str(schema.item()) != "spectral-scaling-eigenvalues/v1":
        raise ValueError("eigenvalue archive schema mismatch")
    if (
        energies.dtype != np.float64
        or energies.ndim != 1
        or not np.all(np.isfinite(energies))
        or np.any(np.abs(energies) > 1e100)
    ):
        raise ValueError("energies must be a bounded finite one-dimensional float64 array")
    if tuple(energies.shape) != npz_metadata["energies.npy"]["shape"]:
        raise ValueError("loaded energies shape differs from its physical NPY header")
    if len(packet_rows) > 6_000 or energies.size > 5_000_000 or len(query_rows) > 512:
        raise ValueError("retired input exceeds the published cardinality bounds")

    expected_realization: dict[tuple, dict[str, Any]] = {}
    group_means: dict[tuple, list[float]] = {}
    group_ratios: dict[tuple, int] = {}
    raw_group_coordinates: dict[tuple[float, int, float], tuple[float, int, float]] = {}
    packet_ids: set[str] = set()
    expected_offset = 0
    for index, row in enumerate(packet_rows, start=2):
        packet_id = row["packet_id"]
        realization_id = row["realization_id"]
        if not packet_id or len(packet_id.encode("utf-8")) > 48 or packet_id in packet_ids:
            raise ValueError(f"packets:{index}: empty or duplicate packet_id")
        if not realization_id or len(realization_id.encode("utf-8")) > 48:
            raise ValueError(f"packets:{index}: empty realization_id")
        packet_ids.add(packet_id)
        size = integer_text(row["size"], f"packets:{index}:size")
        target = finite_number(row["target"], f"packets:{index}:target")
        control = finite_number(row["control"], f"packets:{index}:control")
        e_min = finite_number(row["e_min"], f"packets:{index}:e_min")
        e_max = finite_number(row["e_max"], f"packets:{index}:e_max")
        shift_energy = finite_number(row["shift_energy"], f"packets:{index}:shift_energy")
        keep = integer_text(row["keep_count"], f"packets:{index}:keep_count")
        offset = integer_text(row["eigen_offset"], f"packets:{index}:eigen_offset")
        count = integer_text(row["eigen_count"], f"packets:{index}:eigen_count")
        if (
            not 1 <= size <= 1_000_000
            or not 0.0 <= target <= 1.0
            or not e_min < e_max
            or abs(control) > 1e6
            or any(abs(value) > 1e100 for value in (e_min, e_max, shift_energy))
        ):
            raise ValueError(f"packets:{index}: invalid coordinate/extrema")
        canonical_group = (canonical(target), size, canonical(control))
        raw_group = (target, size, control)
        prior_raw_group = raw_group_coordinates.setdefault(canonical_group, raw_group)
        if prior_raw_group != raw_group:
            raise ValueError(
                f"packets:{index}: distinct raw coordinates collide after canonicalization"
            )
        if offset != expected_offset or not 5 <= keep <= count <= 4096 or offset + count > energies.size:
            raise ValueError(f"packets:{index}: inconsistent offset/count")
        expected_offset += count
        chunk = np.asarray(energies[offset : offset + count], dtype=np.float64)
        if np.any(chunk < e_min) or np.any(chunk > e_max):
            raise ValueError(f"packets:{index}: raw eigenvalue slice is outside [e_min,e_max]")
        target_energy = e_max + target * (e_min - e_max)
        distances = np.abs(chunk - target_energy)
        if not math.isfinite(target_energy) or not np.all(np.isfinite(distances)):
            raise ValueError(f"packets:{index}: target-energy arithmetic overflowed")
        if abs(shift_energy - target_energy) > 0.005 * (e_max - e_min):
            raise ValueError(f"packets:{index}: shift_energy violates its affine-covariant span bound")
        distance_order = np.argsort(distances, kind="stable")
        nearest = distance_order[:keep]
        selected = np.sort(chunk[nearest])
        gaps = np.diff(selected)
        if gaps.size < 3 or not np.all(np.isfinite(gaps)) or np.any(gaps <= 0.0):
            raise ValueError(f"packets:{index}: selected spectrum is not strictly increasing")
        span_scale = max(float(np.ptp(chunk)), e_max - e_min)
        magnitude = max(1.0, abs(e_min), abs(e_max), abs(target_energy), float(np.max(np.abs(chunk))))
        ulp_margin = AFFINE_ULP_MULTIPLIER * math.ulp(magnitude)
        gap_margin = max(AFFINE_GAP_RELATIVE_MARGIN * span_scale, ulp_margin)
        cutoff_required = max(AFFINE_CUTOFF_RELATIVE_MARGIN * span_scale, ulp_margin)
        if float(np.min(gaps)) < gap_margin:
            raise ValueError(f"packets:{index}: selected gaps violate the affine float64 margin")
        if keep < count:
            cutoff_margin = float(distances[distance_order[keep]] - distances[distance_order[keep - 1]])
            if not math.isfinite(cutoff_margin) or cutoff_margin < cutoff_required:
                raise ValueError(f"packets:{index}: keep-count cutoff tie margin is not float64-safe")
        ratios = np.minimum(gaps[:-1], gaps[1:]) / np.maximum(gaps[:-1], gaps[1:])
        if not np.all(np.isfinite(ratios)):
            raise ValueError(f"packets:{index}: adjacent-gap ratios are non-finite")
        key = (*canonical_group, realization_id)
        if key in expected_realization:
            raise ValueError(f"packets:{index}: duplicate group-realization key")
        mean = float(np.mean(ratios))
        if not math.isfinite(mean):
            raise ValueError(f"packets:{index}: realization mean is non-finite")
        expected_realization[key] = {"n_ratios": int(ratios.size), "mean_r": mean}
        group_means.setdefault(key[:3], []).append(mean)
        group_ratios[key[:3]] = group_ratios.get(key[:3], 0) + int(ratios.size)
    if expected_offset != energies.size:
        raise ValueError("packet slices do not exhaust the energies array")

    expected_grouped: dict[tuple, dict[str, Any]] = {}
    for key, values in group_means.items():
        array = np.asarray(values, dtype=np.float64)
        if not 2 <= array.size <= 128:
            raise ValueError(f"group {key} violates the two-through-128 realization bound")
        group_mean = float(np.mean(array))
        group_se = float(np.std(array, ddof=1) / math.sqrt(array.size))
        if not math.isfinite(group_mean) or not math.isfinite(group_se):
            raise ValueError(f"group {key} produced a non-finite statistic")
        expected_grouped[key] = {
            "mean_r": group_mean,
            "se_r": group_se,
            "n_realizations": int(array.size),
            "n_ratios": group_ratios[key],
            "target": key[0],
            "size": key[1],
            "control": key[2],
        }
    targets = sorted({key[0] for key in expected_grouped})
    if not targets or len(targets) > 8:
        raise ValueError("input must contain from one through eight targets")
    sizes = sorted({key[1] for key in expected_grouped})
    if not 3 <= len(sizes) <= 8:
        raise ValueError("input must contain from three through eight distinct sizes")
    controls_by_curve: dict[tuple[float, int], set[float]] = {}
    for target, size, control in expected_grouped:
        controls_by_curve.setdefault((target, size), set()).add(control)
    if any(
        len({size for observed_target, size in controls_by_curve if observed_target == target}) < 3
        for target in targets
    ):
        raise ValueError("each target must contain at least three observed sizes")
    if any(not 5 <= len(controls) <= 21 for controls in controls_by_curve.values()):
        raise ValueError("each observed target-size curve must contain from five through 21 controls")
    query_ids: set[str] = set()
    normalized_queries: list[dict[str, Any]] = []
    for index, row in enumerate(query_rows, start=2):
        query_id = row["query_id"]
        target = canonical(finite_number(row["target"], f"queries:{index}:target"))
        size = finite_number(row["size"], f"queries:{index}:size")
        control = finite_number(row["control"], f"queries:{index}:control")
        if not query_id or len(query_id.encode("utf-8")) > 48 or query_id in query_ids or target not in targets or not 1.0 <= size <= 1_000_000.0 or abs(control) > 1e6:
            raise ValueError(f"queries:{index}: invalid/duplicate query key or coordinate")
        query_ids.add(query_id)
        normalized_queries.append({"query_id": query_id, "target": target, "size": size, "control": control})
    expected_stability = {
        (target, min_size, canonical(halfwidth))
        for target in targets for min_size in min_sizes for halfwidth in halfwidths
    }
    required_rows = (
        len(packet_rows)
        + len(expected_grouped)
        + len(targets)
        + len(targets) * stability_cells
        + len(query_rows)
    )
    if output_bytes < 512 * required_rows + 8192:
        raise ValueError("resource_contract output_bytes cannot hold all mandatory rows")
    target_rows = {
        target: [value for key, value in expected_grouped.items() if key[0] == target]
        for target in targets
    }
    expected_n_groups: dict[tuple, int] = {}
    for key in expected_stability:
        target, min_size, halfwidth = key
        center = preliminary_center(target_rows[target])
        expected_n_groups[key] = sum(
            int(row["size"]) >= min_size
            and abs(float(row["control"]) - center) <= halfwidth * (1.0 + 1e-12)
            for row in target_rows[target]
        )
    return {
        "manifest": manifest,
        "grid": grid,
        "realization": expected_realization,
        "grouped": expected_grouped,
        "targets": targets,
        "stability_keys": expected_stability,
        "n_groups_by_stability": expected_n_groups,
        "queries": normalized_queries,
        "query_ids": query_ids,
        "target_rows": target_rows,
        "primary_min": primary_min,
        "primary_halfwidth": primary_halfwidth,
    }


def parse_outputs(output: Path, expected: dict[str, Any]) -> dict[str, Any]:
    expected_files = set(EXPECTED_OUTPUTS) | {"claims.json"}
    if not output.is_dir() or is_linklike(output):
        raise ValueError("result directory is missing or is a symbolic link")
    entries = list(output.iterdir())
    if any(is_linklike(path) or not path.is_file() or path.stat().st_nlink != 1 for path in entries):
        raise ValueError("result directory contains a link or non-regular artifact")
    if {path.name for path in entries} != expected_files:
        raise ValueError(f"output inventory mismatch: {sorted(path.name for path in entries)}")
    byte_limit = int(expected["manifest"]["resource_contract"]["output_bytes"])
    total_bytes = sum(path.stat().st_size for path in entries)
    if total_bytes > byte_limit:
        raise ValueError(f"output uses {total_bytes} bytes, exceeding {byte_limit}")
    raw = {name: read_rows(output / name, columns) for name, columns in EXPECTED_OUTPUTS.items()}
    case_id = expected["manifest"]["case_id"]

    realization: dict[tuple, dict[str, Any]] = {}
    for row in raw["realization_stats.csv"]:
        if row["case_id"] != case_id:
            raise ValueError("realization_stats.csv: case_id mismatch")
        key = (
            canonical(finite_number(row["target"], "realization target")),
            integer_text(row["size"], "realization size"),
            canonical(finite_number(row["control"], "realization control")),
            row["realization_id"],
        )
        if key in realization:
            raise ValueError(f"realization_stats.csv: duplicate key {key}")
        count = integer_text(row["n_ratios"], "realization n_ratios")
        mean = finite_number(row["mean_r"], "realization mean_r")
        if count <= 0 or not 0.0 <= mean <= 1.0:
            raise ValueError("realization_stats.csv: statistic outside public range")
        realization[key] = {"n_ratios": count, "mean_r": mean}

    grouped: dict[tuple, dict[str, Any]] = {}
    for row in raw["packet_stats.csv"]:
        if row["case_id"] != case_id:
            raise ValueError("packet_stats.csv: case_id mismatch")
        key = (
            canonical(finite_number(row["target"], "group target")),
            integer_text(row["size"], "group size"),
            canonical(finite_number(row["control"], "group control")),
        )
        if key in grouped:
            raise ValueError(f"packet_stats.csv: duplicate key {key}")
        n_realizations = integer_text(row["n_realizations"], "group n_realizations")
        n_ratios = integer_text(row["n_ratios"], "group n_ratios")
        mean = finite_number(row["mean_r"], "group mean_r")
        se = finite_number(row["se_r"], "group se_r")
        if n_realizations < 2 or n_ratios <= 0 or not 0.0 <= mean <= 1.0 or se < 0.0:
            raise ValueError("packet_stats.csv: statistic outside public range")
        grouped[key] = {
            "n_realizations": n_realizations, "n_ratios": n_ratios, "mean_r": mean, "se_r": se,
        }

    transitions: dict[float, dict[str, Any]] = {}
    for row in raw["transition.csv"]:
        if row["case_id"] != case_id:
            raise ValueError("transition.csv: case_id mismatch")
        target = canonical(finite_number(row["target"], "transition target"))
        if target in transitions:
            raise ValueError(f"transition.csv: duplicate target {target}")
        values = {
            name: finite_number(row[name], f"transition {name}")
            for name in ("h_c", "nu", "h_c_lo", "h_c_hi", "nu_lo", "nu_hi", "fit_score")
        }
        stable = integer_text(row["stable"], "transition stable")
        if not values["h_c_lo"] <= values["h_c"] <= values["h_c_hi"]:
            raise ValueError("transition.csv: h_c interval is unordered")
        if not 0.0 < values["nu_lo"] <= values["nu"] <= values["nu_hi"]:
            raise ValueError("transition.csv: nu interval is unordered/nonpositive")
        if not 0.2 <= values["nu"] <= 4.0 or values["nu_hi"] > 10.0:
            raise ValueError("transition.csv: exponent values exceed the public float64 domain")
        if max(abs(values["h_c_lo"]), abs(values["h_c_hi"])) > 4e6:
            raise ValueError("transition.csv: control interval exceeds the public float64 domain")
        if not 0.0 <= values["fit_score"] <= 1.0 or stable not in {0, 1}:
            raise ValueError("transition.csv: invalid score or stable flag")
        values["stable"] = stable
        transitions[target] = values

    stability: dict[tuple, dict[str, Any]] = {}
    for row in raw["stability.csv"]:
        if row["case_id"] != case_id:
            raise ValueError("stability.csv: case_id mismatch")
        key = (
            canonical(finite_number(row["target"], "stability target")),
            integer_text(row["min_size"], "stability min_size"),
            canonical(finite_number(row["halfwidth"], "stability halfwidth")),
        )
        if key in stability:
            raise ValueError(f"stability.csv: duplicate key {key}")
        values = {
            "h_c": finite_number(row["h_c"], "stability h_c"),
            "nu": finite_number(row["nu"], "stability nu"),
            "validation_rmse": finite_number(row["validation_rmse"], "stability validation_rmse"),
            "n_groups": integer_text(row["n_groups"], "stability n_groups"),
            "fit_ok": integer_text(row["fit_ok"], "stability fit_ok"),
        }
        if not 0.2 <= values["nu"] <= 4.0 or values["validation_rmse"] < 0.0 or values["n_groups"] <= 0 or values["fit_ok"] not in {0, 1}:
            raise ValueError("stability.csv: invalid fit diagnostic")
        stability[key] = values

    predictions: dict[str, dict[str, float]] = {}
    for row in raw["predictions.csv"]:
        query_id = row["query_id"]
        if not query_id or query_id in predictions:
            raise ValueError(f"predictions.csv: empty or duplicate query_id {query_id!r}")
        mean = finite_number(row["mean_r"], "prediction mean_r")
        se = finite_number(row["se_r"], "prediction se_r")
        if not 0.0 <= mean <= 1.0 or not 0.0 <= se <= 0.25:
            raise ValueError("predictions.csv: mean/uncertainty outside public range")
        predictions[query_id] = {"mean_r": mean, "se_r": se}

    if set(realization) != set(expected["realization"]):
        raise ValueError("realization_stats.csv: exact input-key coverage mismatch")
    if set(grouped) != set(expected["grouped"]):
        raise ValueError("packet_stats.csv: exact group-key coverage mismatch")
    if set(transitions) != set(expected["targets"]):
        raise ValueError("transition.csv: exact target coverage mismatch")
    if set(stability) != expected["stability_keys"]:
        raise ValueError("stability.csv: exact target/min-size/halfwidth grid mismatch")
    if set(predictions) != expected["query_ids"]:
        raise ValueError("predictions.csv: exact query-id coverage mismatch")

    for key, truth in expected["realization"].items():
        value = realization[key]
        if value["n_ratios"] != truth["n_ratios"] or abs(value["mean_r"] - truth["mean_r"]) > STAT_TOLERANCE:
            raise ValueError(f"realization_stats.csv: incorrect raw statistic at {key}")
    for key, truth in expected["grouped"].items():
        value = grouped[key]
        if value["n_realizations"] != truth["n_realizations"] or value["n_ratios"] != truth["n_ratios"]:
            raise ValueError(f"packet_stats.csv: incorrect counts at {key}")
        if abs(value["mean_r"] - truth["mean_r"]) > STAT_TOLERANCE or abs(value["se_r"] - truth["se_r"]) > STAT_TOLERANCE:
            raise ValueError(f"packet_stats.csv: incorrect realization-first mean/SEM at {key}")

    # Stability diagnostics are normative even when h_c/nu come from an
    # independently implemented search.
    for key, value in stability.items():
        target, min_size, halfwidth = key
        target_controls = [float(row["control"]) for row in expected["target_rows"][target]]
        if not min(target_controls) <= value["h_c"] <= max(target_controls):
            raise ValueError(f"stability.csv: h_c lies outside its target control range at {key}")
        if value["fit_ok"] != 1:
            raise ValueError(f"stability.csv: retired valid fit marked failed at {key}")
        if value["n_groups"] != expected["n_groups_by_stability"][key]:
            raise ValueError(f"stability.csv: n_groups does not match fixed public window at {key}")
        diagnostic = cubic_diagnostic(
            expected["target_rows"][target], value["h_c"], value["nu"], min_size, halfwidth
        )
        if abs(value["validation_rmse"] - diagnostic["rmse"]) > DIAGNOSTIC_TOLERANCE:
            raise ValueError(f"stability.csv: validation_rmse is not reproducible at {key}")

    controls = [key[2] for key in expected["grouped"]]
    control_low, control_high = min(controls), max(controls)
    for target, value in transitions.items():
        target_controls = [float(row["control"]) for row in expected["target_rows"][target]]
        target_low, target_high = min(target_controls), max(target_controls)
        if not target_low <= value["h_c"] <= target_high:
            raise ValueError(f"transition.csv: h_c lies outside the observed control range for {target}")
        primary = cubic_diagnostic(
            expected["target_rows"][target], value["h_c"], value["nu"],
            expected["primary_min"], expected["primary_halfwidth"],
        )
        fit_score = 1.0 / (1.0 + primary["rmse"] / 0.02)
        if abs(value["fit_score"] - fit_score) > DIAGNOSTIC_TOLERANCE:
            raise ValueError(f"transition.csv: fit_score is inconsistent for target {target}")
        variants = [row for key, row in stability.items() if key[0] == target]
        spread_h = float(np.std([row["h_c"] for row in variants], ddof=1))
        spread_nu = float(np.std([row["nu"] for row in variants], ddof=1))
        if not math.isfinite(spread_h) or not math.isfinite(spread_nu):
            raise ValueError(f"transition.csv: non-finite stability spread for target {target}")
        stable = int(spread_h <= 0.5 * expected["primary_halfwidth"] and spread_nu <= 0.9)
        if value["stable"] != stable:
            raise ValueError(f"transition.csv: stable flag is inconsistent for target {target}")

    # A broad public model check catches unrelated/query-table answers without
    # exposing the much stronger private behavioral calibration.
    query_groups: dict[tuple, list[tuple[float, float]]] = {}
    for query in expected["queries"]:
        transition = transitions[query["target"]]
        primary = cubic_diagnostic(
            expected["target_rows"][query["target"]], transition["h_c"], transition["nu"],
            expected["primary_min"], expected["primary_halfwidth"],
        )
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            x = (query["control"] - transition["h_c"]) * query["size"] ** (1.0 / transition["nu"])
        if not math.isfinite(x) or abs(x) > MAX_SCALING_COORDINATE:
            raise ValueError(f"predictions.csv: {query['query_id']} scaling coordinate exceeds its public bound")
        z = x / primary["x_scale"]
        if not math.isfinite(z) or abs(z) > MAX_STANDARDIZED_QUERY:
            raise ValueError(f"predictions.csv: {query['query_id']} standardized coordinate exceeds its public bound")
        basis = np.asarray([1.0, z, z * z, z * z * z], dtype=np.float64)
        raw_prediction = float(np.dot(basis, primary["coefficients"]))
        if (
            not np.all(np.isfinite(basis))
            or not math.isfinite(raw_prediction)
            or abs(raw_prediction) > MAX_RAW_CUBIC_PREDICTION
        ):
            raise ValueError(f"predictions.csv: {query['query_id']} raw prediction exceeds its public bound")
        reference_mean = float(np.clip(raw_prediction, 0.0, 1.0))
        submitted = predictions[query["query_id"]]
        if abs(submitted["mean_r"] - reference_mean) > PUBLIC_PREDICTION_TOLERANCE:
            raise ValueError(f"predictions.csv: {query['query_id']} is incompatible with its finite-size fit")
        query_groups.setdefault((query["target"], query["size"]), []).append(
            (query["control"], submitted["mean_r"])
        )
    for key, curve in query_groups.items():
        ordered = sorted(curve)
        if len(ordered) >= 2 and ordered[0][1] + 0.015 < ordered[-1][1]:
            raise ValueError(f"predictions.csv: public phase direction is reversed for {key}")
    if len(transitions) >= 2 and np.ptp([value["h_c"] for value in transitions.values()]) <= 0.03:
        raise ValueError("transition.csv: retired target-dependent curve collapsed to one crossing")

    claims = strict_json(output / "claims.json")
    if set(claims) != CLAIM_KEYS:
        raise ValueError(f"claims.json: exact key set mismatch: {sorted(claims)}")
    if claims.get("schema_version") != "spectral-scaling-claims/v1":
        raise ValueError("claims.json: schema_version mismatch")
    if claims.get("case_id") != case_id or claims.get("case_token") != expected["manifest"]["case_token"]:
        raise ValueError("claims.json: current case identity/token mismatch")
    if claims.get("finite_size_crossover") is not True or claims.get("phase_direction") != "mean_r_decreases_with_control":
        raise ValueError("claims.json: finite-size claim/direction mismatch")
    for name in ("n_realizations", "n_groups", "n_targets"):
        if type(claims.get(name)) is not int:
            raise ValueError(f"claims.json: {name} must be a JSON integer")
    expected_counts = {
        "n_realizations": len(expected["realization"]),
        "n_groups": len(expected["grouped"]),
        "n_targets": len(expected["targets"]),
    }
    if any(claims[name] != value for name, value in expected_counts.items()):
        raise ValueError("claims.json: evidence counts mismatch")
    low_mean = float(np.mean([
        value["mean_r"] for key, value in expected["grouped"].items() if key[2] == control_low
    ]))
    high_mean = float(np.mean([
        value["mean_r"] for key, value in expected["grouped"].items() if key[2] == control_high
    ]))
    submitted_low = json_number(claims.get("low_control_mean_r"), "claims low_control_mean_r")
    submitted_high = json_number(claims.get("high_control_mean_r"), "claims high_control_mean_r")
    if abs(submitted_low - low_mean) > STAT_TOLERANCE or abs(submitted_high - high_mean) > STAT_TOLERANCE:
        raise ValueError("claims.json: low/high summaries do not match grouped evidence")
    if not submitted_low > submitted_high:
        raise ValueError("claims.json: low/high summaries reverse the guaranteed phase direction")
    return {
        "files": sorted(path.name for path in entries),
        "bytes": total_bytes,
        "realizations": len(realization),
        "groups": len(grouped),
        "targets": len(transitions),
        "queries": len(predictions),
        "public_scientific_checks": "passed",
    }


def inspect_source(analyzer: Path, manifest: dict[str, Any] | None = None) -> None:
    require_single_link_file(analyzer, "output/analyze.py")
    if analyzer.stat().st_size > SOURCE_LIMIT:
        raise ValueError(f"analyzer exceeds {SOURCE_LIMIT:,} bytes")
    try:
        source = analyzer.read_text(encoding="utf-8")
    except UnicodeError as error:
        raise ValueError("output/analyze.py is not UTF-8") from error
    tree = ast.parse(source, filename=str(analyzer))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".", 1)[0] for alias in node.names}
            unexpected = roots - ALLOWED_IMPORT_ROOTS
            if unexpected:
                raise ValueError(f"analyzer imports unsupported module(s): {sorted(unexpected)}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if node.level or root not in ALLOWED_IMPORT_ROOTS:
                raise ValueError(f"analyzer imports unsupported module: {node.module!r}")


def validate_submission_inventory(submission: Path) -> Path:
    if not submission.is_dir() or is_linklike(submission):
        raise ValueError("submission root must be a regular directory")
    artifacts = list(submission.rglob("*"))
    if any(is_linklike(path) for path in artifacts):
        raise ValueError("submission may not contain symbolic links")
    files = sorted(path.relative_to(submission).as_posix() for path in artifacts if path.is_file())
    directories = sorted(path.relative_to(submission).as_posix() for path in artifacts if path.is_dir())
    if files != ["output/analyze.py"] or directories != ["output"]:
        raise ValueError(
            f"submission must contain only output/analyze.py; files={files}, directories={directories}"
        )
    require_single_link_file(submission / "output" / "analyze.py", "output/analyze.py")
    return submission / "output" / "analyze.py"


def run_public(analyzer: Path, participant: Path, expected: dict[str, Any]) -> dict[str, Any]:
    timeout = min(180, int(expected["manifest"]["resource_contract"]["wall_time_seconds"]))
    with tempfile.TemporaryDirectory(prefix="spectral-public-validation-") as temporary_name:
        temporary = Path(temporary_name)
        output = temporary / "result"
        stdout_path = temporary / "stdout.bin"
        stderr_path = temporary / "stderr.bin"
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.run(
                    [
                        sys.executable, "-I", "-B", str(analyzer),
                        "--input", str(participant / "input"), "--output", str(output),
                    ],
                    cwd=temporary,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=timeout,
                    check=False,
                )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"public analyzer exceeded {timeout} seconds") from error
        if stdout_path.stat().st_size > LOG_LIMIT or stderr_path.stat().st_size > LOG_LIMIT:
            raise RuntimeError("public analyzer emitted more than 1,000,000 bytes of console output")
        if process.returncode != 0:
            diagnostic = stderr_path.read_bytes()[-4000:].decode("utf-8", errors="replace")
            raise RuntimeError(f"public analyzer exited {process.returncode}:\n{diagnostic}")
        return parse_outputs(output, expected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--run-public", action="store_true")
    arguments = parser.parse_args()
    raw_submission = arguments.submission
    if is_linklike(raw_submission):
        raise ValueError("submission root must not be a symbolic link or junction")
    try:
        submission = raw_submission.resolve(strict=True)
    except OSError as error:
        raise ValueError("submission root does not exist") from error
    analyzer = validate_submission_inventory(submission)
    participant = Path(__file__).resolve().parents[1]
    expected = load_expected(participant / "input") if arguments.run_public else None
    inspect_source(analyzer, None if expected is None else expected["manifest"])
    result: dict[str, Any] = {"submission": "valid structure and source policy"}
    if arguments.run_public:
        result["public_run"] = run_public(analyzer, participant, expected)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
