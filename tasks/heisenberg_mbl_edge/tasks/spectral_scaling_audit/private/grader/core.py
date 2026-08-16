#!/usr/bin/env python3
"""Trusted parser, behavioral evaluator, and guarded execution helpers."""

from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
import zipfile

import numpy as np


TASK_ROOT = Path(__file__).resolve().parents[2]
PRIVATE = TASK_ROOT / "private"
GUARDED_RUNNER = Path(__file__).with_name("guarded_runner.py")
PUBLIC_INPUT_ROLES = ("packets", "eigenvalues", "queries", "analysis_grid")
PACKET_COLUMNS = [
    "packet_id", "realization_id", "size", "control", "target", "e_min",
    "e_max", "shift_energy", "keep_count", "eigen_offset", "eigen_count",
]
QUERY_COLUMNS = ["query_id", "target", "size", "control"]
OUTPUT_HEADERS = {
    "realization_stats.csv": ["case_id", "target", "size", "control", "realization_id", "n_ratios", "mean_r"],
    "packet_stats.csv": ["case_id", "target", "size", "control", "n_realizations", "n_ratios", "mean_r", "se_r"],
    "transition.csv": ["case_id", "target", "h_c", "nu", "h_c_lo", "h_c_hi", "nu_lo", "nu_hi", "fit_score", "stable"],
    "stability.csv": ["case_id", "target", "min_size", "halfwidth", "h_c", "nu", "validation_rmse", "n_groups", "fit_ok"],
    "predictions.csv": ["query_id", "mean_r", "se_r"],
}
CLAIM_KEYS = {
    "schema_version", "case_id", "case_token", "finite_size_crossover", "phase_direction",
    "n_realizations", "n_groups", "n_targets", "low_control_mean_r", "high_control_mean_r",
}
WEIGHTS = {
    "realization_statistics": 0.17,
    "grouped_statistics": 0.16,
    "heldout_prediction": 0.22,
    "critical_curve_and_exponent": 0.18,
    "stability_sweep": 0.12,
    "uncertainty": 0.08,
    "evidence_consistency": 0.07,
}
MANDATORY = {
    "realization_statistics": 0.90,
    "grouped_statistics": 0.90,
    "heldout_prediction": 0.52,
    "critical_curve_and_exponent": 0.50,
    "stability_sweep": 0.38,
    "uncertainty": 0.50,
    "evidence_consistency": 1.00,
}
PER_CASE_MANDATORY = {
    "realization_statistics": 0.85,
    "grouped_statistics": 0.72,
    "heldout_prediction": 0.40,
    "critical_curve_and_exponent": 0.20,
    "stability_sweep": 0.30,
    "uncertainty": 0.25,
    "evidence_consistency": 1.00,
}
MIN_AGGREGATION_WEIGHT = 0.20
PASS_SCORE = 0.76
STDOUT_TAIL_BYTES = 2_000
STDERR_TAIL_BYTES = 4_000
MAX_CASE_INPUT_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 65_536
MAX_NPZ_UNCOMPRESSED_BYTES = 40_020_000
MAX_NPY_HEADER_BYTES = 4_096
MAX_BOOTSTRAP_SEED = 2**64 - 1 - 1009 * 7
AFFINE_ULP_MULTIPLIER = 2**20
AFFINE_CUTOFF_RELATIVE_MARGIN = 1e-8
AFFINE_GAP_RELATIVE_MARGIN = 1e-9
MAX_CSV_FIELD_BYTES = 128
MAX_INTEGER_TEXT_DIGITS = 20
CSV_PARSER_FIELD_LIMIT = 1_024


class GateFailure(ValueError):
    pass


class EvaluatorConfigurationError(RuntimeError):
    """Trusted evaluator data/configuration failed its disclosed contract."""


def _reject_json_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant {token!r}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def is_linklike(path: Path) -> bool:
    """Return true for symbolic links and Windows directory junctions."""
    if path.is_symlink():
        return True
    junction_test = getattr(path, "is_junction", None)
    return bool(junction_test()) if junction_test is not None else False


def require_single_link_regular_file(path: Path, label: str) -> os.stat_result:
    """Reject special files, symlinks/junctions, and hard-linked files."""
    if is_linklike(path):
        raise GateFailure(f"{label} is linked")
    try:
        information = path.lstat()
    except OSError as error:
        raise GateFailure(f"{label} is unavailable") from error
    if not stat.S_ISREG(information.st_mode):
        raise GateFailure(f"{label} is not a regular file")
    if information.st_nlink != 1:
        raise GateFailure(f"{label} is hard-linked")
    return information


def strict_json(path: Path) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except Exception as error:
        raise GateFailure(f"invalid JSON {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise GateFailure(f"{path.name} must contain an object")
    return value


def rounded(value: float) -> float:
    return round(float(value), 10)


def finite_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except Exception as error:
        raise GateFailure(f"{label} is not numeric") from error
    if not math.isfinite(parsed):
        raise GateFailure(f"{label} is not finite")
    return parsed


def integer(value: str, label: str) -> int:
    if (
        not 1 <= len(value) <= MAX_INTEGER_TEXT_DIGITS
        or not value.isascii()
        or not value.isdecimal()
    ):
        raise GateFailure(f"{label} is not a bounded unsigned ASCII integer")
    return int(value)


def _json_number(value: Any, label: str) -> float:
    if type(value) not in {int, float}:
        raise ValueError(f"{label} must be a JSON number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite")
    return parsed


def _json_integer(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be a JSON integer")
    return value


def _unsigned_decimal(value: str, label: str) -> int:
    if (
        not 1 <= len(value) <= MAX_INTEGER_TEXT_DIGITS
        or not value.isascii()
        or not value.isdecimal()
    ):
        raise ValueError(
            f"{label} must be unsigned ASCII decimal text of at most "
            f"{MAX_INTEGER_TEXT_DIGITS} digits"
        )
    return int(value)


def _finite_text(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except Exception as error:
        raise ValueError(f"{label} must be numeric") from error
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite")
    return parsed


def read_rows(path: Path, expected: list[str]) -> list[dict[str, str]]:
    csv.field_size_limit(CSV_PARSER_FIELD_LIMIT)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != expected:
                raise GateFailure(f"{path.name} header mismatch")
            rows = list(reader)
    except UnicodeError as error:
        raise GateFailure(f"{path.name} is not UTF-8") from error
    except csv.Error as error:
        raise GateFailure(f"{path.name} has an invalid or oversized CSV field") from error
    if not rows:
        raise GateFailure(f"{path.name} has no rows")
    for index, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise GateFailure(f"{path.name}:{index} is malformed")
        if any(len(value.encode("utf-8")) > MAX_CSV_FIELD_BYTES for value in row.values()):
            raise GateFailure(
                f"{path.name}:{index} contains a field longer than "
                f"{MAX_CSV_FIELD_BYTES} bytes"
            )
    return rows


def _read_case_rows(path: Path, columns: list[str], max_rows: int) -> list[dict[str, str]]:
    """Read a bounded public-input CSV with its exact ordered v1 header."""
    csv.field_size_limit(CSV_PARSER_FIELD_LIMIT)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                raise ValueError(f"{path.name} header does not match the public v1 schema")
            rows: list[dict[str, str]] = []
            for row in reader:
                rows.append(row)
                if len(rows) > max_rows:
                    raise ValueError(f"{path.name} exceeds the public {max_rows}-row limit")
    except UnicodeError as error:
        raise ValueError(f"{path.name} is not UTF-8") from error
    except csv.Error as error:
        raise ValueError(f"{path.name} has an invalid or oversized CSV field") from error
    if not rows:
        raise ValueError(f"{path.name} has no data rows")
    for index, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"{path.name}:{index} is malformed")
        if any(len(value.encode("utf-8")) > MAX_CSV_FIELD_BYTES for value in row.values()):
            raise ValueError(
                f"{path.name}:{index} contains a field longer than "
                f"{MAX_CSV_FIELD_BYTES} bytes"
            )
    return rows


def _read_npy_header(member: Any, name: str) -> tuple[tuple[int, ...], bool, np.dtype, int]:
    """Inspect one bounded NPY header without allocating its payload."""
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
        raise ValueError(f"{name} uses unsupported NPY header version {version}")
    return tuple(shape), bool(fortran_order), np.dtype(dtype), int(member.tell())


def _preflight_eigenvalue_npz(path: Path) -> dict[str, dict[str, Any]]:
    """Validate physical ZIP/NPY structure before any call to ``np.load``."""
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
            if (
                len(members) != 2
                or names.count("schema_version.npy") != 1
                or names.count("energies.npy") != 1
            ):
                raise ValueError(
                    "eigenvalue NPZ must contain exactly one schema_version.npy "
                    "and one energies.npy physical member"
                )
            if sum(member.file_size for member in members) > MAX_NPZ_UNCOMPRESSED_BYTES:
                raise ValueError("eigenvalue NPZ exceeds the 40,020,000-byte expansion bound")
            metadata: dict[str, dict[str, Any]] = {}
            for member in members:
                if member.flag_bits & 0x1:
                    raise ValueError("encrypted NPZ members are not allowed")
                if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValueError("unsupported NPZ compression method")
                with archive.open(member, mode="r") as stream:
                    shape, fortran_order, dtype, header_bytes = _read_npy_header(
                        stream, member.filename
                    )
                if fortran_order:
                    raise ValueError(f"{member.filename} must not use Fortran-order storage")
                item_count = math.prod(shape) if shape else 1
                payload_bytes = item_count * dtype.itemsize
                if header_bytes + payload_bytes != member.file_size:
                    raise ValueError(
                        f"{member.filename} physical size disagrees with its NPY header"
                    )
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
        or schema["dtype"].fields is not None
        or schema["dtype"].subdtype is not None
        or schema["dtype"].itemsize > 256
    ):
        raise ValueError("schema_version.npy must be a bounded scalar Unicode array")
    if energies["dtype"] != np.dtype(np.float64) or len(energies["shape"]) != 1:
        raise ValueError("energies.npy must declare one-dimensional float64 data")
    if not 1 <= energies["shape"][0] <= 5_000_000:
        raise ValueError("energies.npy violates the public element-count bound")
    return metadata


def _preliminary_center(target_rows: list[dict[str, Any]]) -> float:
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
                candidates.append(float(controls[index] + fraction * (controls[index + 1] - controls[index])))
        if candidates:
            middle = float(np.median(controls))
            centers.append(min(candidates, key=lambda value: abs(value - middle)))
    if centers:
        return float(np.median(np.asarray(centers, dtype=np.float64)))
    return float(np.median(np.asarray([float(row["control"]) for row in target_rows], dtype=np.float64)))


def _load_expected_case(input_dir: Path) -> dict[str, Any]:
    """Validate and snapshot one trusted public-v1 case before participant code runs.

    A failure here is evaluator configuration failure, never evidence about a
    participant submission.  In particular, the NPZ's physical members and
    bounded NPY headers are checked before ``np.load`` can allocate arrays.
    """
    try:
        supplied_root = Path(input_dir)
        if is_linklike(supplied_root):
            raise ValueError("case directory is linked")
        root = supplied_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("case path is not a directory")
        manifest_path = root / "manifest.json"
        manifest_stat = require_single_link_regular_file(manifest_path, "case manifest.json")
        if manifest_stat.st_size > MAX_MANIFEST_BYTES:
            raise ValueError("manifest.json exceeds 65,536 bytes")
        manifest = strict_json(manifest_path)
        if manifest.get("schema_version") != "spectral-scaling-input/v1":
            raise ValueError("manifest schema_version mismatch")
        for label in ("case_id", "case_token"):
            value = manifest.get(label)
            if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 48:
                raise ValueError(f"manifest {label} violates the 48-byte string bound")
        bootstrap_seed = _json_integer(manifest.get("bootstrap_seed"), "manifest bootstrap_seed")
        if not 0 <= bootstrap_seed <= MAX_BOOTSTRAP_SEED:
            raise ValueError("manifest bootstrap_seed or a derived target seed exceeds uint64")

        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(PUBLIC_INPUT_ROLES):
            raise ValueError("manifest files object does not have the exact public v1 roles")
        data_names: list[str] = []
        for role in PUBLIC_INPUT_ROLES:
            name = files.get(role)
            if (
                not isinstance(name, str)
                or not name
                or len(name.encode("utf-8")) > 128
                or "/" in name
                or "\\" in name
                or PureWindowsPath(name).drive
                or Path(name).is_absolute()
                or Path(name).name != name
                or name in {".", "..", "manifest.json"}
            ):
                raise ValueError(f"manifest files.{role} is not a safe bounded filename")
            data_names.append(name)
        if len(set(data_names)) != 4:
            raise ValueError("manifest data filenames are not distinct")
        entries = sorted(root.iterdir(), key=lambda path: path.name)
        expected_names = {"manifest.json", *data_names}
        if {path.name for path in entries} != expected_names or len(entries) != 5:
            raise ValueError("case directory does not contain exactly its five declared files")
        fingerprints: dict[str, tuple[int, int, int, int]] = {}
        total_bytes = 0
        for path in entries:
            information = require_single_link_regular_file(path, f"case input {path.name}")
            total_bytes += information.st_size
            fingerprints[path.name] = (
                information.st_dev,
                information.st_ino,
                information.st_size,
                information.st_mtime_ns,
            )
        if total_bytes > MAX_CASE_INPUT_BYTES:
            raise ValueError("case input exceeds the 256 MiB physical-byte limit")
        case_files = {role: root / files[role] for role in PUBLIC_INPUT_ROLES}

        resource = manifest.get("resource_contract")
        resource_keys = {"python", "numpy", "network", "wall_time_seconds", "output_bytes"}
        if not isinstance(resource, dict) or set(resource) != resource_keys:
            raise ValueError("manifest resource_contract key set mismatch")
        if resource.get("python") != "3.11+":
            raise ValueError("resource_contract.python must equal '3.11+' in v1")
        if resource.get("numpy") != "2.3.5" or resource.get("network") != "disabled":
            raise ValueError("resource_contract NumPy/network declaration mismatch")
        wall_time = _json_integer(resource.get("wall_time_seconds"), "wall_time_seconds")
        output_bytes = _json_integer(resource.get("output_bytes"), "output_bytes")
        if wall_time != 180 or not 1 <= output_bytes <= 4_000_000:
            raise ValueError("resource_contract wall time or output-byte cap is invalid")
        if manifest.get("packet_columns") != PACKET_COLUMNS:
            raise ValueError("manifest packet_columns does not match public v1")
        if manifest.get("query_columns") != QUERY_COLUMNS:
            raise ValueError("manifest query_columns does not match public v1")

        packet_rows = _read_case_rows(case_files["packets"], PACKET_COLUMNS, 6_000)
        query_rows = _read_case_rows(case_files["queries"], QUERY_COLUMNS, 512)
        grid_stat = require_single_link_regular_file(case_files["analysis_grid"], "analysis grid")
        if grid_stat.st_size > MAX_MANIFEST_BYTES:
            raise ValueError("analysis-grid JSON exceeds 65,536 bytes")
        grid = strict_json(case_files["analysis_grid"])
        grid_keys = {
            "schema_version", "min_sizes", "halfwidths", "primary_min_size",
            "primary_halfwidth", "bootstrap_replicates", "interval_level",
        }
        if set(grid) != grid_keys or grid.get("schema_version") != "spectral-scaling-analysis-grid/v1":
            raise ValueError("analysis-grid schema/key set mismatch")
        if _json_number(grid.get("interval_level"), "interval_level") != 0.68:
            raise ValueError("v1 interval_level must equal 0.68")
        raw_min_sizes = grid.get("min_sizes")
        raw_halfwidths = grid.get("halfwidths")
        if not isinstance(raw_min_sizes, list) or not isinstance(raw_halfwidths, list):
            raise ValueError("analysis-grid axes must be JSON arrays")
        min_sizes = [_json_integer(value, "min_size") for value in raw_min_sizes]
        numeric_halfwidths = [_json_number(value, "halfwidth") for value in raw_halfwidths]
        halfwidths = [rounded(value) for value in numeric_halfwidths]
        if (
            not min_sizes
            or len(min_sizes) > 8
            or len(set(min_sizes)) != len(min_sizes)
            or any(not 1 <= value <= 1_000_000 for value in min_sizes)
        ):
            raise ValueError("analysis-grid min_sizes is empty, duplicated, or out of bounds")
        if (
            not halfwidths
            or len(halfwidths) > 8
            or len(set(halfwidths)) != len(halfwidths)
            or any(not 0.4 <= value <= 1_000_000 for value in numeric_halfwidths)
            or any(not 0.4 <= value <= 1_000_000 for value in halfwidths)
        ):
            raise ValueError("analysis-grid halfwidths is empty, duplicated, or out of bounds")
        stability_cells = len(min_sizes) * len(halfwidths)
        if not 2 <= stability_cells <= 24:
            raise ValueError("analysis-grid must contain from two through 24 cells")
        primary_min = _json_integer(grid.get("primary_min_size"), "primary_min_size")
        primary_halfwidth = rounded(_json_number(grid.get("primary_halfwidth"), "primary_halfwidth"))
        if primary_min not in min_sizes or primary_halfwidth not in set(halfwidths):
            raise ValueError("primary analysis-grid pair is not in its grid")
        bootstrap_replicates = _json_integer(
            grid.get("bootstrap_replicates"), "bootstrap_replicates"
        )
        if not 8 <= bootstrap_replicates <= 64:
            raise ValueError("bootstrap_replicates violates the public bound")

        npz_metadata = _preflight_eigenvalue_npz(case_files["eigenvalues"])
        header_energy_count = int(npz_metadata["energies.npy"]["shape"][0])
        preflight_offset = 0
        for index, row in enumerate(packet_rows, start=2):
            offset = _unsigned_decimal(row["eigen_offset"], f"packets:{index}:eigen_offset")
            count = _unsigned_decimal(row["eigen_count"], f"packets:{index}:eigen_count")
            keep = _unsigned_decimal(row["keep_count"], f"packets:{index}:keep_count")
            if offset != preflight_offset or not 5 <= keep <= count <= 4096:
                raise ValueError(f"packets:{index}: offset/count fails pre-allocation validation")
            preflight_offset += count
            if preflight_offset > header_energy_count:
                raise ValueError("packet slices exceed the preflighted energies shape")
        if preflight_offset != header_energy_count:
            raise ValueError("packet slices do not match the preflighted energies shape")
        with np.load(case_files["eigenvalues"], allow_pickle=False) as archive:
            if set(archive.files) != {"schema_version", "energies"}:
                raise ValueError("eigenvalue archive logical members mismatch")
            schema = np.asarray(archive["schema_version"])
            energies = np.asarray(archive["energies"])
        if (
            schema.shape != ()
            or schema.dtype.kind != "U"
            or str(schema.item()) != "spectral-scaling-eigenvalues/v1"
        ):
            raise ValueError("eigenvalue archive schema mismatch")
        if (
            energies.dtype != np.float64
            or energies.ndim != 1
            or not np.all(np.isfinite(energies))
            or np.any(np.abs(energies) > 1e100)
        ):
            raise ValueError("energies must be bounded finite one-dimensional float64")
        if tuple(energies.shape) != npz_metadata["energies.npy"]["shape"]:
            raise ValueError("loaded energy shape differs from its physical NPY header")

        realization: dict[tuple, dict[str, Any]] = {}
        group_means: dict[tuple, list[float]] = {}
        group_ratios: dict[tuple, int] = {}
        canonical_coordinate_sources: dict[tuple, tuple[float, int, float]] = {}
        packet_ids: set[str] = set()
        expected_offset = 0
        for index, row in enumerate(packet_rows, start=2):
            packet_id = row["packet_id"]
            realization_id = row["realization_id"]
            if not packet_id or len(packet_id.encode("utf-8")) > 48 or packet_id in packet_ids:
                raise ValueError(f"packets:{index}: invalid or duplicate packet_id")
            if not realization_id or len(realization_id.encode("utf-8")) > 48:
                raise ValueError(f"packets:{index}: invalid realization_id")
            packet_ids.add(packet_id)
            size = _unsigned_decimal(row["size"], f"packets:{index}:size")
            target = _finite_text(row["target"], f"packets:{index}:target")
            control = _finite_text(row["control"], f"packets:{index}:control")
            e_min = _finite_text(row["e_min"], f"packets:{index}:e_min")
            e_max = _finite_text(row["e_max"], f"packets:{index}:e_max")
            shift_energy = _finite_text(row["shift_energy"], f"packets:{index}:shift_energy")
            keep = _unsigned_decimal(row["keep_count"], f"packets:{index}:keep_count")
            offset = _unsigned_decimal(row["eigen_offset"], f"packets:{index}:eigen_offset")
            count = _unsigned_decimal(row["eigen_count"], f"packets:{index}:eigen_count")
            if (
                not 1 <= size <= 1_000_000
                or not 0.0 <= target <= 1.0
                or not e_min < e_max
                or abs(control) > 1_000_000
                or any(abs(value) > 1e100 for value in (e_min, e_max, shift_energy))
            ):
                raise ValueError(f"packets:{index}: coordinate/extrema outside public bounds")
            if offset != expected_offset or not 5 <= keep <= count <= 4096 or offset + count > energies.size:
                raise ValueError(f"packets:{index}: inconsistent offset/count")
            expected_offset += count
            chunk = energies[offset : offset + count]
            if np.any(chunk < e_min) or np.any(chunk > e_max):
                raise ValueError(f"packets:{index}: energy slice lies outside [e_min,e_max]")
            target_energy = e_max + target * (e_min - e_max)
            distances = np.abs(chunk - target_energy)
            if not math.isfinite(target_energy) or not np.all(np.isfinite(distances)):
                raise ValueError(f"packets:{index}: target-energy arithmetic overflowed")
            if abs(shift_energy - target_energy) > 0.005 * (e_max - e_min):
                raise ValueError(f"packets:{index}: shift_energy violates its span bound")
            distance_order = np.argsort(distances, kind="stable")
            selected = np.sort(chunk[distance_order[:keep]])
            gaps = np.diff(selected)
            if gaps.size < 3 or not np.all(np.isfinite(gaps)) or np.any(gaps <= 0.0):
                raise ValueError(f"packets:{index}: selected spectrum is not strictly increasing")
            span_scale = max(float(np.ptp(chunk)), e_max - e_min)
            magnitude = max(
                1.0, abs(e_min), abs(e_max), abs(target_energy),
                float(np.max(np.abs(chunk))),
            )
            ulp_margin = AFFINE_ULP_MULTIPLIER * math.ulp(magnitude)
            gap_margin = max(AFFINE_GAP_RELATIVE_MARGIN * span_scale, ulp_margin)
            cutoff_required = max(AFFINE_CUTOFF_RELATIVE_MARGIN * span_scale, ulp_margin)
            if float(np.min(gaps)) < gap_margin:
                raise ValueError(f"packets:{index}: selected gaps violate affine float64 safety")
            if keep < count:
                cutoff_margin = float(distances[distance_order[keep]] - distances[distance_order[keep - 1]])
                if not math.isfinite(cutoff_margin) or cutoff_margin < cutoff_required:
                    raise ValueError(f"packets:{index}: retain cutoff violates affine float64 safety")
            ratios = np.minimum(gaps[:-1], gaps[1:]) / np.maximum(gaps[:-1], gaps[1:])
            if not np.all(np.isfinite(ratios)):
                raise ValueError(f"packets:{index}: adjacent-gap ratios are non-finite")
            canonical_group = (rounded(target), size, rounded(control))
            raw_group = (target, size, control)
            previous_raw_group = canonical_coordinate_sources.setdefault(canonical_group, raw_group)
            if previous_raw_group != raw_group:
                raise ValueError(
                    f"packets:{index}: distinct raw group coordinates collide after canonicalization"
                )
            key = (*canonical_group, realization_id)
            if key in realization:
                raise ValueError(f"packets:{index}: duplicate canonical group-realization key")
            mean = float(np.mean(ratios))
            realization[key] = {"n_ratios": int(ratios.size), "mean_r": mean}
            group_means.setdefault(key[:3], []).append(mean)
            group_ratios[key[:3]] = group_ratios.get(key[:3], 0) + int(ratios.size)
        if expected_offset != energies.size:
            raise ValueError("packet slices do not exhaust the energies array")

        grouped: dict[tuple, dict[str, Any]] = {}
        for key, values in group_means.items():
            means = np.asarray(values, dtype=np.float64)
            if not 2 <= means.size <= 128:
                raise ValueError(f"group {key} violates the two-through-128 realization bound")
            grouped[key] = {
                "mean_r": float(np.mean(means)),
                "se_r": float(np.std(means, ddof=1) / math.sqrt(means.size)),
                "n_realizations": int(means.size),
                "n_ratios": group_ratios[key],
            }
        targets = sorted({key[0] for key in grouped})
        sizes = sorted({key[1] for key in grouped})
        if not 1 <= len(targets) <= 8 or not 3 <= len(sizes) <= 8:
            raise ValueError("case target/size cardinality violates public bounds")
        controls_by_curve: dict[tuple[float, int], set[float]] = {}
        for target, size, control in grouped:
            controls_by_curve.setdefault((target, size), set()).add(control)
        if any(
            len({size for observed_target, size in controls_by_curve if observed_target == target}) < 3
            for target in targets
        ):
            raise ValueError("each target must contain at least three observed sizes")
        if any(not 5 <= len(controls) <= 21 for controls in controls_by_curve.values()):
            raise ValueError("a target-size curve violates the five-through-21 control bound")

        query_ids: set[str] = set()
        for index, row in enumerate(query_rows, start=2):
            query_id = row["query_id"]
            target = rounded(_finite_text(row["target"], f"queries:{index}:target"))
            size = _finite_text(row["size"], f"queries:{index}:size")
            control = _finite_text(row["control"], f"queries:{index}:control")
            if (
                not query_id
                or len(query_id.encode("utf-8")) > 48
                or query_id in query_ids
                or target not in targets
                or not 1.0 <= size <= 1_000_000.0
                or abs(control) > 1_000_000
            ):
                raise ValueError(f"queries:{index}: invalid or duplicate query")
            query_ids.add(query_id)

        target_rows: dict[float, list[dict[str, Any]]] = {
            target: [
                {
                    "target": key[0], "size": key[1], "control": key[2],
                    "mean_r": value["mean_r"], "se_r": value["se_r"],
                }
                for key, value in grouped.items() if key[0] == target
            ]
            for target in targets
        }
        for target, rows in target_rows.items():
            center = _preliminary_center(rows)
            for min_size in min_sizes:
                for halfwidth in halfwidths:
                    selected = [
                        row for row in rows
                        if int(row["size"]) >= min_size
                        and abs(float(row["control"]) - center) <= halfwidth * (1.0 + 1e-12)
                    ]
                    if len(selected) < 8 or len({int(row["size"]) for row in selected}) < 3:
                        raise ValueError(
                            f"target {target} stability cell ({min_size},{halfwidth}) lacks fit support"
                        )
        required_rows = (
            len(packet_rows) + len(grouped) + len(targets)
            + len(targets) * stability_cells + len(query_rows)
        )
        if output_bytes < 512 * required_rows + 8192:
            raise ValueError("resource_contract output_bytes cannot hold all mandatory rows")
        expected_stability = {
            (target, min_size, rounded(halfwidth))
            for target in targets for min_size in min_sizes for halfwidth in halfwidths
        }
        target_control_ranges = {
            target: (
                min(float(row["control"]) for row in target_rows[target]),
                max(float(row["control"]) for row in target_rows[target]),
            )
            for target in targets
        }
        return {
            "root": root,
            "manifest": manifest,
            "grid": grid,
            "files": {"manifest": manifest_path, **case_files},
            "fingerprints": fingerprints,
            "statistics": {"realization": realization, "grouped": grouped},
            "realization_keys": set(realization),
            "group_keys": set(grouped),
            "targets": set(targets),
            "stability_keys": expected_stability,
            "query_ids": query_ids,
            "target_control_ranges": target_control_ranges,
        }
    except EvaluatorConfigurationError:
        raise
    except Exception as error:
        raise EvaluatorConfigurationError(
            f"trusted case {Path(input_dir)} violates the public v1 contract: "
            f"{type(error).__name__}: {error}"
        ) from error


def inspect_output(output_dir: Path, byte_limit: int) -> dict[str, int]:
    expected = set(OUTPUT_HEADERS) | {"claims.json"}
    if not output_dir.is_dir() or is_linklike(output_dir):
        raise GateFailure("output directory missing or linked")
    files = []
    total = 0
    for path in output_dir.iterdir():
        information = require_single_link_regular_file(path, f"output artifact {path.name}")
        files.append(path.name)
        total += information.st_size
    if set(files) != expected:
        raise GateFailure(f"output inventory mismatch: {sorted(files)}")
    if total > byte_limit:
        raise GateFailure("output byte limit exceeded")
    return {"file_count": len(files), "total_bytes": total}


def parse_output(
    output_dir: Path,
    manifest: dict,
    input_dir: Path,
    expected_case: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if expected_case is None:
        expected_case = _load_expected_case(input_dir)
    inspect_output(output_dir, int(manifest["resource_contract"]["output_bytes"]))
    raw = {name: read_rows(output_dir / name, header) for name, header in OUTPUT_HEADERS.items()}
    case_id = manifest["case_id"]
    realization: dict[tuple, dict] = {}
    for row in raw["realization_stats.csv"]:
        if row["case_id"] != case_id:
            raise GateFailure("realization case ID mismatch")
        key = (rounded(finite_float(row["target"], "target")), integer(row["size"], "size"), rounded(finite_float(row["control"], "control")), row["realization_id"])
        if key in realization:
            raise GateFailure("duplicate realization row")
        mean = finite_float(row["mean_r"], "mean_r")
        count = integer(row["n_ratios"], "n_ratios")
        if not 0.0 <= mean <= 1.0 or count <= 0:
            raise GateFailure("invalid realization statistic range")
        realization[key] = {"n_ratios": count, "mean_r": mean}

    grouped: dict[tuple, dict] = {}
    for row in raw["packet_stats.csv"]:
        if row["case_id"] != case_id:
            raise GateFailure("group case ID mismatch")
        key = (rounded(finite_float(row["target"], "target")), integer(row["size"], "size"), rounded(finite_float(row["control"], "control")))
        if key in grouped:
            raise GateFailure("duplicate grouped row")
        mean = finite_float(row["mean_r"], "mean_r")
        se = finite_float(row["se_r"], "se_r")
        nr = integer(row["n_realizations"], "n_realizations")
        ng = integer(row["n_ratios"], "n_ratios")
        if not 0.0 <= mean <= 1.0 or se < 0.0 or nr < 2 or ng <= 0:
            raise GateFailure("invalid grouped statistic range")
        grouped[key] = {"mean_r": mean, "se_r": se, "n_realizations": nr, "n_ratios": ng}

    transitions: dict[float, dict] = {}
    for row in raw["transition.csv"]:
        if row["case_id"] != case_id:
            raise GateFailure("transition case ID mismatch")
        target = rounded(finite_float(row["target"], "target"))
        if target in transitions:
            raise GateFailure("duplicate transition target")
        values = {name: finite_float(row[name], name) for name in ("h_c", "nu", "h_c_lo", "h_c_hi", "nu_lo", "nu_hi", "fit_score")}
        if not values["h_c_lo"] <= values["h_c"] <= values["h_c_hi"]:
            raise GateFailure("unordered h_c interval")
        if not 0.0 < values["nu_lo"] <= values["nu"] <= values["nu_hi"]:
            raise GateFailure("unordered/nonpositive nu interval")
        if not 0.2 <= values["nu"] <= 4.0 or values["nu_hi"] > 10.0:
            raise GateFailure("transition exponent exceeds the public point/interval domain")
        if max(abs(values["h_c_lo"]), abs(values["h_c_hi"])) > 4_000_000:
            raise GateFailure("transition control interval exceeds the public domain")
        if not 0.0 <= values["fit_score"] <= 1.0 or row["stable"] not in {"0", "1"}:
            raise GateFailure("invalid transition score/flag")
        values["stable"] = int(row["stable"])
        transitions[target] = values

    stability: dict[tuple, dict] = {}
    for row in raw["stability.csv"]:
        if row["case_id"] != case_id:
            raise GateFailure("stability case ID mismatch")
        key = (rounded(finite_float(row["target"], "target")), integer(row["min_size"], "min_size"), rounded(finite_float(row["halfwidth"], "halfwidth")))
        if key in stability:
            raise GateFailure("duplicate stability row")
        values = {name: finite_float(row[name], name) for name in ("h_c", "nu", "validation_rmse")}
        values["n_groups"] = integer(row["n_groups"], "n_groups")
        values["fit_ok"] = integer(row["fit_ok"], "fit_ok")
        if not 0.2 <= values["nu"] <= 4.0 or values["validation_rmse"] < 0.0 or values["n_groups"] <= 0 or values["fit_ok"] not in {0, 1}:
            raise GateFailure("invalid stability values")
        stability[key] = values

    predictions: dict[str, dict] = {}
    for row in raw["predictions.csv"]:
        query_id = row["query_id"]
        if query_id in predictions:
            raise GateFailure("duplicate prediction")
        mean = finite_float(row["mean_r"], "mean_r")
        se = finite_float(row["se_r"], "se_r")
        if not 0.0 <= mean <= 1.0 or not 0.0 <= se <= 0.25:
            raise GateFailure("invalid prediction range")
        predictions[query_id] = {"mean_r": mean, "se_r": se}

    claims = strict_json(output_dir / "claims.json")
    if set(claims) != CLAIM_KEYS or claims.get("schema_version") != "spectral-scaling-claims/v1":
        raise GateFailure("claims schema mismatch")
    for key in ("n_realizations", "n_groups", "n_targets"):
        if type(claims.get(key)) is not int:
            raise GateFailure(f"claims {key} must be a JSON integer")
    for key in ("low_control_mean_r", "high_control_mean_r"):
        if type(claims.get(key)) not in {int, float} or not math.isfinite(float(claims[key])):
            raise GateFailure("claims contain non-finite summary")

    expected_realization_keys = expected_case["realization_keys"]
    expected_group_keys = expected_case["group_keys"]
    expected_targets = expected_case["targets"]
    expected_stability = expected_case["stability_keys"]
    if set(realization) != expected_realization_keys:
        raise GateFailure("realization key coverage mismatch")
    if set(grouped) != expected_group_keys:
        raise GateFailure("group key coverage mismatch")
    if set(transitions) != expected_targets:
        raise GateFailure("transition target coverage mismatch")
    if set(stability) != expected_stability:
        raise GateFailure("stability grid coverage mismatch")
    if set(predictions) != expected_case["query_ids"]:
        raise GateFailure("prediction query coverage mismatch")
    for target, row in transitions.items():
        low, high = expected_case["target_control_ranges"][target]
        if not low <= row["h_c"] <= high:
            raise GateFailure("transition h_c lies outside the observed target control range")
    for key, row in stability.items():
        low, high = expected_case["target_control_ranges"][key[0]]
        if not low <= row["h_c"] <= high:
            raise GateFailure("stability h_c lies outside the observed target control range")
    return {
        "realization": realization,
        "grouped": grouped,
        "transitions": transitions,
        "stability": stability,
        "predictions": predictions,
        "claims": claims,
    }


def expected_statistics(
    input_dir: Path,
    manifest: dict | None = None,
    expected_case: dict[str, Any] | None = None,
) -> dict[str, dict]:
    """Return statistics only from a fully preflighted trusted case."""
    loaded = expected_case if expected_case is not None else _load_expected_case(input_dir)
    if manifest is not None and manifest.get("case_id") != loaded["manifest"].get("case_id"):
        raise EvaluatorConfigurationError("trusted manifest changed during evaluation")
    return loaded["statistics"]


def error_score(errors: list[float], excellent: float, minimum: float) -> float:
    if not errors:
        return 0.0
    array = np.asarray(errors, dtype=np.float64)
    aggregate = 0.7 * float(np.mean(array)) + 0.3 * float(np.quantile(array, 0.90))
    if aggregate <= excellent:
        return 1.0
    if aggregate >= minimum:
        return 0.0
    return float((minimum - aggregate) / (minimum - excellent))


def parse_reference_output(
    path: Path,
    manifest: dict,
    input_dir: Path,
    expected_case: dict[str, Any] | None = None,
) -> dict:
    return parse_output(path, manifest, input_dir, expected_case)


def score_case(
    parsed: dict,
    input_dir: Path,
    truth_path: Path,
    oracle_output: Path,
    manifest: dict,
    expected_case: dict[str, Any] | None = None,
) -> tuple[dict, dict]:
    expected = expected_statistics(input_dir, manifest, expected_case)
    realization_errors = []
    count_errors = 0
    for key, reference in expected["realization"].items():
        submitted = parsed["realization"][key]
        realization_errors.append(abs(submitted["mean_r"] - reference["mean_r"]))
        count_errors += int(submitted["n_ratios"] != reference["n_ratios"])
    realization_score = error_score(realization_errors, 2e-7, 0.012)
    if count_errors:
        realization_score = 0.0

    group_mean_errors = []
    group_se_errors = []
    group_count_errors = 0
    for key, reference in expected["grouped"].items():
        submitted = parsed["grouped"][key]
        group_mean_errors.append(abs(submitted["mean_r"] - reference["mean_r"]))
        group_se_errors.append(abs(submitted["se_r"] - reference["se_r"]))
        group_count_errors += int(submitted["n_realizations"] != reference["n_realizations"] or submitted["n_ratios"] != reference["n_ratios"])
    grouped_score = 0.58 * error_score(group_mean_errors, 3e-7, 0.012) + 0.42 * error_score(group_se_errors, 3e-7, 0.006)
    if group_count_errors:
        grouped_score = 0.0

    with np.load(truth_path, allow_pickle=False) as truth:
        truth_targets = np.asarray(truth["targets"], dtype=np.float64)
        true_hc = np.asarray(truth["h_c"], dtype=np.float64)
        true_nu = np.asarray(truth["nu"], dtype=np.float64)
        query_ids = [str(value) for value in np.asarray(truth["query_ids"])]
        query_truth = np.asarray(truth["query_mean_r"], dtype=np.float64)
    query_errors = [abs(parsed["predictions"][query_id]["mean_r"] - float(reference)) for query_id, reference in zip(query_ids, query_truth)]
    prediction_score = error_score(query_errors, 0.010, 0.065)

    hc_errors = []
    nu_errors = []
    for target, hc, nu in zip(truth_targets, true_hc, true_nu):
        row = parsed["transitions"][rounded(float(target))]
        hc_errors.append(abs(row["h_c"] - float(hc)))
        nu_errors.append(abs(row["nu"] - float(nu)))
    edge_score = 0.68 * error_score(hc_errors, 0.10, 0.52) + 0.32 * error_score(nu_errors, 0.18, 0.95)

    oracle = parse_reference_output(oracle_output, manifest, input_dir, expected_case)
    stability_hc = []
    stability_nu = []
    stability_rmse = []
    for key, reference in oracle["stability"].items():
        submitted = parsed["stability"][key]
        stability_hc.append(abs(submitted["h_c"] - reference["h_c"]))
        stability_nu.append(abs(submitted["nu"] - reference["nu"]))
        stability_rmse.append(abs(submitted["validation_rmse"] - reference["validation_rmse"]))
    stability_score = (
        0.50 * error_score(stability_hc, 0.035, 0.42)
        + 0.30 * error_score(stability_nu, 0.08, 0.75)
        + 0.20 * error_score(stability_rmse, 0.002, 0.045)
    )
    sweep_coordinates = {(key[1], key[2]) for key in parsed["stability"]}
    sweep_signatures: dict[float, set[tuple[float, float, int]]] = {}
    for key, row in parsed["stability"].items():
        sweep_signatures.setdefault(key[0], set()).add((row["h_c"], row["nu"], row["n_groups"]))
    copied_stability_sweep = (
        len(sweep_coordinates) > 1
        and bool(sweep_signatures)
        and all(len(signatures) == 1 for signatures in sweep_signatures.values())
    )
    if copied_stability_sweep:
        stability_score = 0.0

    width_errors = []
    coverage = []
    for target, hc, nu in zip(truth_targets, true_hc, true_nu):
        key = rounded(float(target))
        row = parsed["transitions"][key]
        ref = oracle["transitions"][key]
        submitted_h_width = max(row["h_c_hi"] - row["h_c_lo"], 1e-12)
        reference_h_width = max(ref["h_c_hi"] - ref["h_c_lo"], 1e-12)
        submitted_n_width = max(row["nu_hi"] - row["nu_lo"], 1e-12)
        reference_n_width = max(ref["nu_hi"] - ref["nu_lo"], 1e-12)
        width_errors.extend([abs(math.log(submitted_h_width / reference_h_width)), abs(math.log(submitted_n_width / reference_n_width))])
        coverage.extend([row["h_c_lo"] <= hc <= row["h_c_hi"], row["nu_lo"] <= nu <= row["nu_hi"]])
    query_coverage = []
    query_width_errors = []
    for query_id, truth_value in zip(query_ids, query_truth):
        row = parsed["predictions"][query_id]
        ref = oracle["predictions"][query_id]
        query_coverage.append(abs(row["mean_r"] - float(truth_value)) <= 2.0 * row["se_r"] + 0.004)
        query_width_errors.append(abs(math.log(max(row["se_r"], 1e-12) / max(ref["se_r"], 1e-12))))
    coverage_score = 0.45 * float(np.mean(coverage)) + 0.55 * float(np.mean(query_coverage))
    width_score = 0.60 * error_score(width_errors, 0.08, 2.2) + 0.40 * error_score(query_width_errors, 0.08, 1.8)
    uncertainty_score = 0.58 * coverage_score + 0.42 * width_score

    claims = parsed["claims"]
    controls = [key[2] for key in expected["grouped"]]
    minimum_control = min(controls)
    maximum_control = max(controls)
    low_mean = float(np.mean([value["mean_r"] for key, value in expected["grouped"].items() if key[2] == minimum_control]))
    high_mean = float(np.mean([value["mean_r"] for key, value in expected["grouped"].items() if key[2] == maximum_control]))
    evidence_checks = [
        claims.get("case_id") == manifest["case_id"],
        claims.get("case_token") == manifest["case_token"],
        claims.get("finite_size_crossover") is True,
        claims.get("phase_direction") == "mean_r_decreases_with_control",
        int(claims.get("n_realizations", -1)) == len(expected["realization"]),
        int(claims.get("n_groups", -1)) == len(expected["grouped"]),
        int(claims.get("n_targets", -1)) == len(truth_targets),
        abs(float(claims.get("low_control_mean_r", math.inf)) - low_mean) <= 5e-7,
        abs(float(claims.get("high_control_mean_r", math.inf)) - high_mean) <= 5e-7,
        low_mean > high_mean,
    ]
    evidence_score = float(np.mean(evidence_checks))
    components = {
        "realization_statistics": realization_score,
        "grouped_statistics": grouped_score,
        "heldout_prediction": prediction_score,
        "critical_curve_and_exponent": edge_score,
        "stability_sweep": stability_score,
        "uncertainty": uncertainty_score,
        "evidence_consistency": evidence_score,
    }
    diagnostics = {
        "mean_realization_abs_error": float(np.mean(realization_errors)),
        "mean_group_abs_error": float(np.mean(group_mean_errors)),
        "mean_group_sem_abs_error": float(np.mean(group_se_errors)),
        "mean_query_abs_error": float(np.mean(query_errors)),
        "mean_hc_abs_error": float(np.mean(hc_errors)),
        "mean_nu_abs_error": float(np.mean(nu_errors)),
        "transition_coverage": float(np.mean(coverage)),
        "query_coverage": float(np.mean(query_coverage)),
        "copied_stability_sweep": copied_stability_sweep,
    }
    return components, diagnostics


def aggregate(per_case: list[dict[str, float]]) -> dict[str, float]:
    aggregated = {}
    for name in WEIGHTS:
        values = np.asarray([case[name] for case in per_case], dtype=np.float64)
        mean_value = float(np.mean(values))
        minimum_value = float(np.min(values))
        aggregated[name] = (1.0 - MIN_AGGREGATION_WEIGHT) * mean_value + MIN_AGGREGATION_WEIGHT * minimum_value
    return aggregated


def _minimal_child_environment() -> dict[str, str]:
    """Build a small, non-secret-bearing environment for the child process."""
    environment = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")
        if key in os.environ
    }
    # -I ignores Python configuration variables, but these values also document
    # and reinforce the intended deterministic, UTF-8 execution contract.
    environment.update({"PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    return environment


def _copy_staged_file(source: Path, destination: Path, label: str) -> None:
    if is_linklike(source):
        raise GateFailure(f"{label} source is linked")
    try:
        information = source.lstat()
    except OSError as error:
        raise GateFailure(f"{label} source is unavailable") from error
    if not stat.S_ISREG(information.st_mode):
        raise GateFailure(f"{label} source is not a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    require_single_link_regular_file(destination, f"staged {label}")


def _stage_flat_input(expected_case: dict[str, Any], destination_dir: Path) -> None:
    """Copy exactly the already-validated case snapshot into the child root."""
    source_dir = expected_case["root"]
    try:
        if not source_dir.is_dir() or is_linklike(source_dir):
            raise ValueError("hidden input directory is missing or linked")
        entries = sorted(source_dir.iterdir(), key=lambda path: path.name)
        expected_names = set(expected_case["fingerprints"])
        if {path.name for path in entries} != expected_names or len(entries) != 5:
            raise ValueError("hidden input inventory changed after trusted preflight")
        for source in entries:
            information = require_single_link_regular_file(source, f"hidden input {source.name}")
            fingerprint = (
                information.st_dev,
                information.st_ino,
                information.st_size,
                information.st_mtime_ns,
            )
            if fingerprint != expected_case["fingerprints"][source.name]:
                raise ValueError(f"hidden input {source.name} changed after trusted preflight")
        destination_dir.mkdir(parents=True, exist_ok=False)
        for source in entries:
            _copy_staged_file(source, destination_dir / source.name, f"hidden input {source.name}")
    except EvaluatorConfigurationError:
        raise
    except Exception as error:
        raise EvaluatorConfigurationError(
            f"trusted case staging snapshot is invalid: {type(error).__name__}: {error}"
        ) from error


def _drain_bounded(stream: Any, tail: bytearray, limit: int) -> None:
    """Continuously drain a child pipe while retaining only a bounded tail."""
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            tail.extend(chunk)
            if len(tail) > limit:
                del tail[: len(tail) - limit]
    finally:
        stream.close()


def _copy_checked_outputs(staged_output: Path, output_dir: Path) -> None:
    if not staged_output.is_dir() or is_linklike(staged_output):
        raise GateFailure("analyzer did not leave a regular output directory")
    produced = sorted(staged_output.iterdir(), key=lambda path: path.name)
    for source in produced:
        require_single_link_regular_file(source, f"produced output artifact {source.name}")
    if output_dir.exists() or is_linklike(output_dir):
        raise GateFailure("trusted output destination already exists")
    output_dir.mkdir(parents=True, exist_ok=False)
    for source in produced:
        _copy_staged_file(source, output_dir / source.name, f"produced output artifact {source.name}")


def run_analyzer(
    analyzer: Path,
    input_dir: Path,
    output_dir: Path,
    timeout: int = 180,
    *,
    expected_case: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute from a fresh staging tree without exposing private repo paths.

    The child receives copies of the analyzer, guarded runner, and one hidden
    input case. Trusted truth and reference paths never enter its argv, cwd, or
    environment. Streams are drained concurrently so output cannot accumulate
    without bound in the grader process.
    """
    validated_case = expected_case if expected_case is not None else _load_expected_case(input_dir)
    try:
        supplied_input = Path(input_dir).resolve(strict=True)
    except OSError as error:
        raise EvaluatorConfigurationError("trusted case disappeared before staging") from error
    if supplied_input != validated_case["root"]:
        raise EvaluatorConfigurationError("validated trusted case does not match analyzer input")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage_root = output_dir.parent / "child-root"
    if stage_root.exists() or is_linklike(stage_root):
        raise GateFailure("fresh child staging root already exists")
    stage_root.mkdir(parents=True, exist_ok=False)
    staged_analyzer = stage_root / "submission" / "output" / "analyze.py"
    staged_runner = stage_root / "runtime" / "guarded_runner.py"
    staged_input = stage_root / "input"
    staged_output = stage_root / "result"
    child_working_dir = stage_root / "work"
    _copy_staged_file(analyzer, staged_analyzer, "analyzer")
    _copy_staged_file(GUARDED_RUNNER, staged_runner, "guarded runner")
    _stage_flat_input(validated_case, staged_input)
    staged_output.mkdir(parents=True, exist_ok=False)
    child_working_dir.mkdir(parents=True, exist_ok=False)

    started = time.perf_counter()
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-B",
            "-X",
            "utf8",
            str(staged_runner),
            str(staged_analyzer),
            str(staged_input),
            str(staged_output),
        ],
        cwd=child_working_dir,
        env=_minimal_child_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise GateFailure("failed to establish bounded child streams")
    stdout_tail = bytearray()
    stderr_tail = bytearray()
    stdout_thread = threading.Thread(target=_drain_bounded, args=(process.stdout, stdout_tail, STDOUT_TAIL_BYTES), daemon=True)
    stderr_thread = threading.Thread(target=_drain_bounded, args=(process.stderr, stderr_tail, STDERR_TAIL_BYTES), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    stdout_thread.join(timeout=10.0)
    stderr_thread.join(timeout=10.0)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        process.kill()
        raise GateFailure("child stream drain did not terminate")
    result = {
        "returncode": process.returncode,
        "runtime_seconds": time.perf_counter() - started,
        "stdout": bytes(stdout_tail).decode("utf-8", errors="replace"),
        "stderr": bytes(stderr_tail).decode("utf-8", errors="replace"),
    }
    if timed_out:
        raise GateFailure(f"analyzer timed out after {timeout} seconds: {result['stderr']}")
    if process.returncode != 0:
        raise GateFailure(f"analyzer execution failed: {result['stderr']}")
    _copy_checked_outputs(staged_output, output_dir)
    return result


def grade_submission(submission_root: Path) -> dict[str, Any]:
    def rejected(message: str) -> dict[str, Any]:
        return {
            "score": 0.0,
            "passed": False,
            "hard_gate_failures": [message],
            "mandatory_failures": [],
            "per_case_mandatory_failures": [],
            "components": {name: 0.0 for name in WEIGHTS},
            "cases": [],
        }

    supplied_root = Path(submission_root)
    if is_linklike(supplied_root):
        return rejected("submission root is linked")
    try:
        submission_root = supplied_root.resolve(strict=True)
    except OSError:
        return rejected("submission root is missing")
    if not submission_root.is_dir():
        return rejected("submission root is not a directory")
    top_entries = sorted(submission_root.iterdir(), key=lambda path: path.name)
    if len(top_entries) != 1 or top_entries[0].name != "output" or not top_entries[0].is_dir() or is_linklike(top_entries[0]):
        inventory = [path.name for path in top_entries]
        return rejected(f"submission top-level inventory: {inventory}")
    output_entries = sorted(top_entries[0].iterdir(), key=lambda path: path.name)
    if len(output_entries) != 1 or output_entries[0].name != "analyze.py":
        inventory = [f"output/{path.name}" for path in output_entries]
        return rejected(f"submission output inventory: {inventory}")
    analyzer = output_entries[0]
    try:
        analyzer_information = require_single_link_regular_file(analyzer, "analyzer")
    except GateFailure as error:
        return rejected(str(error))
    if analyzer_information.st_size > 250000:
        return rejected("analyzer is oversized")
    try:
        suite = strict_json(PRIVATE / "reference" / "suite.json")
        if suite.get("schema_version") != "spectral-scaling-hidden-suite/v1":
            raise ValueError("hidden suite schema mismatch")
        raw_cases = suite.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ValueError("hidden suite has no scored cases")
        prepared_cases: list[dict[str, Any]] = []
        for case in raw_cases:
            if not isinstance(case, dict):
                raise ValueError("hidden suite case entry is not an object")
            case_id = case.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                raise ValueError("hidden suite case_id is invalid")
            input_dir = (PRIVATE / "reference" / case["input"]).resolve(strict=True)
            expected_case = _load_expected_case(input_dir)
            if expected_case["manifest"].get("case_id") != case_id:
                raise ValueError(f"suite/manifest case_id mismatch for {case_id}")
            prepared_cases.append({
                "record": case,
                "case_id": case_id,
                "input_dir": input_dir,
                "truth_path": (PRIVATE / "reference" / case["truth"]).resolve(strict=True),
                "oracle_output": (PRIVATE / "reference" / case["oracle_output"]).resolve(strict=True),
                "expected_case": expected_case,
            })
    except EvaluatorConfigurationError:
        raise
    except Exception as error:
        raise EvaluatorConfigurationError(
            f"private suite configuration is invalid: {type(error).__name__}: {error}"
        ) from error
    records = []
    case_components = []
    hard_failures = []
    for case_index, prepared in enumerate(prepared_cases):
        # Only one hidden case is ever present in a child staging root. The
        # directory is destroyed before the next case is staged.
        with tempfile.TemporaryDirectory(prefix=f"spectral-private-case-{case_index:02d}-") as temporary:
            temp = Path(temporary)
            case_id = prepared["case_id"]
            input_dir = prepared["input_dir"]
            truth_path = prepared["truth_path"]
            oracle_output = prepared["oracle_output"]
            expected_case = prepared["expected_case"]
            output_dir = temp / "trusted-output"
            try:
                manifest = expected_case["manifest"]
                run = run_analyzer(
                    analyzer,
                    input_dir,
                    output_dir,
                    timeout=int(manifest["resource_contract"]["wall_time_seconds"]),
                    expected_case=expected_case,
                )
                parsed = parse_output(output_dir, manifest, input_dir, expected_case)
                components, diagnostics = score_case(
                    parsed,
                    input_dir,
                    truth_path,
                    oracle_output,
                    manifest,
                    expected_case,
                )
                case_components.append(components)
                case_floor_failures = [
                    name for name, threshold in PER_CASE_MANDATORY.items() if components[name] < threshold
                ]
                records.append({
                    "case_id": case_id,
                    "components": components,
                    "mandatory_failures": case_floor_failures,
                    "diagnostics": diagnostics,
                    "runtime_seconds": run["runtime_seconds"],
                })
            except EvaluatorConfigurationError:
                raise
            except Exception as error:
                hard_failures.append(f"{case_id}: {type(error).__name__}: {error}")
                records.append({"case_id": case_id, "hard_gate_failure": str(error)})
    if hard_failures or not case_components:
        return {
            "score": 0.0,
            "passed": False,
            "hard_gate_failures": hard_failures,
            "mandatory_failures": [],
            "per_case_mandatory_failures": [],
            "components": {name: 0.0 for name in WEIGHTS},
            "cases": records,
        }
    component_means = {
        name: float(np.mean([case[name] for case in case_components])) for name in WEIGHTS
    }
    component_minima = {
        name: float(np.min([case[name] for case in case_components])) for name in WEIGHTS
    }
    components = aggregate(case_components)
    score = float(sum(WEIGHTS[name] * components[name] for name in WEIGHTS))
    mandatory_failures = [name for name, threshold in MANDATORY.items() if components[name] < threshold]
    per_case_mandatory_failures = [
        f"{record['case_id']}:{name}"
        for record in records
        for name in record.get("mandatory_failures", [])
    ]
    passed = score >= PASS_SCORE and not mandatory_failures and not per_case_mandatory_failures
    return {
        "score": score,
        "passed": passed,
        "hard_gate_failures": [],
        "mandatory_failures": mandatory_failures,
        "per_case_mandatory_failures": per_case_mandatory_failures,
        "components": components,
        "component_means": component_means,
        "component_minima": component_minima,
        "minimum_aggregation_weight": MIN_AGGREGATION_WEIGHT,
        "cases": records,
    }
