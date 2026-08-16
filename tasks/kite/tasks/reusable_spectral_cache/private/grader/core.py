"""Trusted parsing and numerical utilities for the reusable spectral cache task."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import stat
import zipfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np


MOMENT_KEYS = {
    "schema_version",
    "system_ids",
    "dimensions",
    "moment_count",
    "probe_count",
    "tau_real",
    "tau_imag",
}
RESPONSE_COLUMNS = [
    "query_id",
    "system_id",
    "prefix",
    "kind",
    "energy",
    "eta",
    "value_real",
    "value_imag",
]
OUTPUT_NAMES = {"moments.npz", "public_response.csv", "diagnostics.json"}
MAX_FILE_BYTES = {
    "moments.npz": 2_000_000,
    "public_response.csv": 500_000,
    "diagnostics.json": 64_000,
}
MAX_NPZ_UNCOMPRESSED_BYTES = 4_000_000
MAX_NPZ_MEMBERS = 16


class SubmissionError(ValueError):
    """An expected, safely reportable submission validation failure."""


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {token}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_strict(path: Path, max_bytes: int = 1_000_000) -> Any:
    if path.stat().st_size > max_bytes:
        raise SubmissionError(f"{path.name} exceeds its size limit")
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise SubmissionError(f"invalid JSON in {path.name}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def require_regular_file(path: Path, max_bytes: int | None = None) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SubmissionError(f"missing required file: {path.name}") from exc
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode):
        raise SubmissionError(f"required artifact is not a regular file: {path.name}")
    if info.st_nlink > 1:
        raise SubmissionError(f"hard-linked artifact is not permitted: {path.name}")
    if max_bytes is not None and info.st_size > max_bytes:
        raise SubmissionError(f"{path.name} exceeds {max_bytes} bytes")


def validate_output_directory(output_dir: Path) -> None:
    try:
        info = output_dir.lstat()
    except OSError as exc:
        raise SubmissionError("submission directory does not exist") from exc
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISDIR(info.st_mode):
        raise SubmissionError("submission path must be a real directory")
    try:
        entries = list(output_dir.iterdir())
    except OSError as exc:
        raise SubmissionError("cannot enumerate submission directory") from exc
    names = {entry.name for entry in entries}
    if names != OUTPUT_NAMES:
        missing = sorted(OUTPUT_NAMES - names)
        unexpected = sorted(names - OUTPUT_NAMES)
        raise SubmissionError(f"artifact inventory mismatch; missing={missing}, unexpected={unexpected}")
    for name in sorted(OUTPUT_NAMES):
        require_regular_file(output_dir / name, MAX_FILE_BYTES[name])


def load_manifest(participant_dir: Path) -> dict[str, Any]:
    path = participant_dir / "input" / "manifest.json"
    data = load_json_strict(path)
    if not isinstance(data, dict) or data.get("schema_version") != "spectral-cache-input/v1":
        raise SubmissionError("unsupported or malformed public manifest")
    systems = data.get("systems")
    if not isinstance(systems, list) or not systems:
        raise SubmissionError("public manifest has no systems")
    return data


def read_csv_rows(path: Path, columns: list[str], max_bytes: int = 1_000_000) -> list[dict[str, str]]:
    require_regular_file(path, max_bytes)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                raise SubmissionError(
                    f"{path.name} header mismatch: expected {columns}, got {reader.fieldnames}"
                )
            rows: list[dict[str, str]] = []
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise SubmissionError(f"extra CSV fields in {path.name} row {row_number}")
                clean: dict[str, str] = {}
                for column in columns:
                    value = row.get(column)
                    if value is None or value == "" or len(value) > 160 or "\x00" in value:
                        raise SubmissionError(
                            f"invalid cell in {path.name} row {row_number}, column {column}"
                        )
                    clean[column] = value
                rows.append(clean)
                if len(rows) > 100_000:
                    raise SubmissionError(f"too many rows in {path.name}")
            return rows
    except SubmissionError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SubmissionError(f"invalid CSV in {path.name}: {exc}") from exc


def parse_float(value: str, label: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise SubmissionError(f"invalid float for {label}") from exc
    if not math.isfinite(result):
        raise SubmissionError(f"non-finite float for {label}")
    return result


def parse_int(value: str, label: str) -> int:
    if not value or any(char not in "0123456789" for char in value):
        raise SubmissionError(f"invalid non-negative integer for {label}")
    try:
        return int(value)
    except ValueError as exc:
        raise SubmissionError(f"invalid integer for {label}") from exc


def load_queries(path: Path) -> list[dict[str, Any]]:
    rows = read_csv_rows(path, RESPONSE_COLUMNS[:6])
    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        query_id = row["query_id"]
        if query_id in seen:
            raise SubmissionError(f"duplicate query_id: {query_id}")
        seen.add(query_id)
        kind = row["kind"]
        if kind not in {"GR", "GA", "DOS"}:
            raise SubmissionError(f"unknown query kind: {kind}")
        prefix = parse_int(row["prefix"], f"{query_id}.prefix")
        eta = parse_float(row["eta"], f"{query_id}.eta")
        if prefix < 1 or eta <= 0.0:
            raise SubmissionError(f"invalid query domain for {query_id}")
        queries.append(
            {
                "query_id": query_id,
                "system_id": row["system_id"],
                "prefix": prefix,
                "kind": kind,
                "energy": parse_float(row["energy"], f"{query_id}.energy"),
                "eta": eta,
            }
        )
    return queries


def _inspect_npz(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise SubmissionError("moments.npz is not a ZIP/NPZ archive")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            if len(members) > MAX_NPZ_MEMBERS:
                raise SubmissionError("moments.npz has too many members")
            total = 0
            names: set[str] = set()
            for member in members:
                if member.is_dir() or member.flag_bits & 0x1:
                    raise SubmissionError("directories and encrypted members are forbidden in NPZ")
                pure_name = Path(member.filename)
                if len(pure_name.parts) != 1 or pure_name.suffix != ".npy":
                    raise SubmissionError("unexpected NPZ member path")
                if member.filename in names:
                    raise SubmissionError("duplicate NPZ member")
                names.add(member.filename)
                total += member.file_size
                if member.file_size > MAX_NPZ_UNCOMPRESSED_BYTES:
                    raise SubmissionError("NPZ member exceeds uncompressed size cap")
                if member.compress_size == 0 and member.file_size != 0:
                    raise SubmissionError("invalid NPZ compression metadata")
            if total > MAX_NPZ_UNCOMPRESSED_BYTES:
                raise SubmissionError("NPZ uncompressed payload exceeds safety cap")
    except SubmissionError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise SubmissionError(f"cannot inspect moments.npz: {exc}") from exc


def _scalar_text(array: np.ndarray, label: str) -> str:
    if array.shape != () or array.dtype.kind not in {"U", "S"}:
        raise SubmissionError(f"{label} must be a scalar string array")
    return _text_value(array.item(), label)


def _text_value(value: Any, label: str) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SubmissionError(f"{label} must contain valid UTF-8") from exc
    if isinstance(value, str):
        return value
    raise SubmissionError(f"{label} must be a string")


def _scalar_int(array: np.ndarray, label: str) -> int:
    if array.shape != () or array.dtype.kind not in {"i", "u"}:
        raise SubmissionError(f"{label} must be a scalar integer array")
    return int(array.item())


def load_moments(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    _inspect_npz(path)
    try:
        with np.load(path, allow_pickle=False, max_header_size=16_384) as archive:
            if set(archive.files) != MOMENT_KEYS:
                raise SubmissionError(
                    f"moments.npz keys mismatch: expected {sorted(MOMENT_KEYS)}, got {sorted(archive.files)}"
                )
            arrays = {key: np.array(archive[key], copy=True) for key in MOMENT_KEYS}
    except SubmissionError:
        raise
    except (OSError, ValueError, TypeError, zipfile.BadZipFile) as exc:
        raise SubmissionError(f"cannot safely load moments.npz: {exc}") from exc

    if _scalar_text(arrays["schema_version"], "schema_version") != "spectral-moments/v1":
        raise SubmissionError("unsupported moments schema_version")
    moment_count = _scalar_int(arrays["moment_count"], "moment_count")
    probe_count = _scalar_int(arrays["probe_count"], "probe_count")
    expected_m = int(manifest["moment_count"])
    expected_p = int(manifest["probe_count"])
    systems = manifest["systems"]
    expected_ids = [system["system_id"] for system in systems]
    expected_dimensions = np.asarray([system["dimension"] for system in systems], dtype=np.int64)

    system_ids = arrays["system_ids"]
    dimensions = arrays["dimensions"]
    if system_ids.shape != (len(systems),) or system_ids.dtype.kind not in {"U", "S"}:
        raise SubmissionError("system_ids has wrong shape or dtype")
    if [_text_value(value, "system_ids") for value in system_ids.tolist()] != expected_ids:
        raise SubmissionError("system_ids do not match the manifest order")
    if dimensions.shape != (len(systems),) or dimensions.dtype.kind not in {"i", "u"}:
        raise SubmissionError("dimensions has wrong shape or dtype")
    if not np.array_equal(dimensions.astype(np.int64), expected_dimensions):
        raise SubmissionError("dimensions do not match the manifest")
    if moment_count != expected_m or probe_count != expected_p:
        raise SubmissionError("moment_count or probe_count does not match the manifest")

    expected_shape = (len(systems), expected_p, expected_m)
    real = arrays["tau_real"]
    imag = arrays["tau_imag"]
    for label, array in (("tau_real", real), ("tau_imag", imag)):
        if array.shape != expected_shape or array.dtype != np.dtype("float64"):
            raise SubmissionError(f"{label} must have shape {expected_shape} and dtype float64")
        if not np.all(np.isfinite(array)):
            raise SubmissionError(f"{label} contains NaN or infinity")
        if np.max(np.abs(array), initial=0.0) > 1.0e12:
            raise SubmissionError(f"{label} exceeds the numeric safety range")
    return {
        "system_ids": expected_ids,
        "dimensions": expected_dimensions,
        "moment_count": moment_count,
        "probe_count": probe_count,
        "tau": real + 1j * imag,
    }


def load_response(path: Path, public_queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = read_csv_rows(path, RESPONSE_COLUMNS, MAX_FILE_BYTES["public_response.csv"])
    if len(rows) != len(public_queries):
        raise SubmissionError("public_response.csv has the wrong row count")
    parsed: list[dict[str, Any]] = []
    for row, expected in zip(rows, public_queries):
        for field in ("query_id", "system_id", "kind"):
            if row[field] != str(expected[field]):
                raise SubmissionError(f"response metadata mismatch for {expected['query_id']}: {field}")
        prefix = parse_int(row["prefix"], f"{expected['query_id']}.prefix")
        energy = parse_float(row["energy"], f"{expected['query_id']}.energy")
        eta = parse_float(row["eta"], f"{expected['query_id']}.eta")
        if prefix != expected["prefix"]:
            raise SubmissionError(f"response prefix mismatch for {expected['query_id']}")
        if energy != expected["energy"] or eta != expected["eta"]:
            raise SubmissionError(f"response query coordinates changed for {expected['query_id']}")
        parsed.append(
            {
                **expected,
                "value": complex(
                    parse_float(row["value_real"], f"{expected['query_id']}.value_real"),
                    parse_float(row["value_imag"], f"{expected['query_id']}.value_imag"),
                ),
            }
        )
    return parsed


def load_diagnostics(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    data = load_json_strict(path, MAX_FILE_BYTES["diagnostics.json"])
    if not isinstance(data, dict):
        raise SubmissionError("diagnostics.json must contain an object")
    expected_top = {
        "schema_version",
        "moment_count",
        "probe_count",
        "public_query_count",
        "systems",
    }
    if set(data) != expected_top or data.get("schema_version") != "spectral-diagnostics/v1":
        raise SubmissionError("diagnostics.json top-level schema mismatch")
    if type(data["moment_count"]) is not int or type(data["probe_count"]) is not int:
        raise SubmissionError("diagnostic counts must be JSON integers")
    if data["moment_count"] != manifest["moment_count"] or data["probe_count"] != manifest["probe_count"]:
        raise SubmissionError("diagnostic cache counts do not match the manifest")
    if type(data["public_query_count"]) is not int:
        raise SubmissionError("public_query_count must be a JSON integer")
    systems = data["systems"]
    if not isinstance(systems, list) or len(systems) != len(manifest["systems"]):
        raise SubmissionError("diagnostic systems list has wrong length")
    expected_keys = {
        "system_id",
        "dimension",
        "tau0_max_abs_error",
        "max_abs_imaginary_moment",
        "max_abs_moment",
        "scaled_gershgorin_radius",
    }
    for item, expected in zip(systems, manifest["systems"]):
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise SubmissionError("diagnostic system record schema mismatch")
        if item["system_id"] != expected["system_id"] or item["dimension"] != expected["dimension"]:
            raise SubmissionError("diagnostic system identity mismatch")
        if type(item["dimension"]) is not int:
            raise SubmissionError("diagnostic dimension must be a JSON integer")
        for key in expected_keys - {"system_id", "dimension"}:
            value = item[key]
            if type(value) not in {int, float} or not math.isfinite(float(value)):
                raise SubmissionError(f"diagnostic {key} must be finite")
            if float(value) < 0.0:
                raise SubmissionError(f"diagnostic {key} must be non-negative")
    return data


def load_system(participant_dir: Path, system: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = int(system["dimension"])
    onsite_rows = read_csv_rows(participant_dir / "input" / system["onsite_file"], ["index", "value"])
    edge_rows = read_csv_rows(
        participant_dir / "input" / system["edges_file"],
        ["i", "j", "value_real", "value_imag"],
    )
    probe_rows = read_csv_rows(
        participant_dir / "input" / system["probes_file"],
        ["probe_id", "index", "value_real", "value_imag"],
    )
    if len(onsite_rows) != n:
        raise SubmissionError("onsite row count mismatch")
    onsite = np.empty(n, dtype=np.float64)
    seen_indices: set[int] = set()
    for row in onsite_rows:
        index = parse_int(row["index"], "onsite.index")
        if index >= n or index in seen_indices:
            raise SubmissionError("onsite indices must be a permutation of 0..N-1")
        seen_indices.add(index)
        onsite[index] = parse_float(row["value"], "onsite.value")

    edges: list[tuple[int, int, complex]] = []
    seen_edges: set[tuple[int, int]] = set()
    for row in edge_rows:
        i = parse_int(row["i"], "edges.i")
        j = parse_int(row["j"], "edges.j")
        if i >= n or j >= n or i >= j or (i, j) in seen_edges:
            raise SubmissionError("edges must be unique canonical pairs 0 <= i < j < N")
        seen_edges.add((i, j))
        value = complex(
            parse_float(row["value_real"], "edges.value_real"),
            parse_float(row["value_imag"], "edges.value_imag"),
        )
        if value == 0.0:
            raise SubmissionError("zero-valued edges are forbidden")
        edges.append((i, j, value))

    probe_count = int(system.get("probe_count", 0) or load_manifest(participant_dir)["probe_count"])
    probes = np.empty((probe_count, n), dtype=np.complex128)
    seen_probe_entries: set[tuple[int, int]] = set()
    for row in probe_rows:
        probe_id = parse_int(row["probe_id"], "probes.probe_id")
        index = parse_int(row["index"], "probes.index")
        key = (probe_id, index)
        if probe_id >= probe_count or index >= n or key in seen_probe_entries:
            raise SubmissionError("invalid or duplicate probe entry")
        seen_probe_entries.add(key)
        probes[key] = complex(
            parse_float(row["value_real"], "probes.value_real"),
            parse_float(row["value_imag"], "probes.value_imag"),
        )
    if len(seen_probe_entries) != probe_count * n:
        raise SubmissionError("probe table is incomplete")
    return onsite, np.asarray(edges, dtype=object), probes


def dense_hamiltonian(onsite: np.ndarray, edges: Iterable[tuple[int, int, complex]]) -> np.ndarray:
    hamiltonian = np.diag(onsite.astype(np.complex128))
    for i_raw, j_raw, value_raw in edges:
        i, j, value = int(i_raw), int(j_raw), complex(value_raw)
        hamiltonian[i, j] = value
        hamiltonian[j, i] = value.conjugate()
    return hamiltonian


def scaled_gershgorin_radius(
    onsite: np.ndarray,
    edges: Iterable[tuple[int, int, complex]],
    lower: float,
    upper: float,
) -> float:
    a = 0.5 * (upper - lower)
    b = 0.5 * (upper + lower)
    radii = np.abs((onsite - b) / a)
    for i_raw, j_raw, value_raw in edges:
        value = abs(complex(value_raw)) / a
        radii[int(i_raw)] += value
        radii[int(j_raw)] += value
    return float(np.max(radii))


def _decaying_root(z: complex) -> tuple[complex, complex]:
    candidate = complex(np.sqrt(z * z - 1.0 + 0.0j))
    root = candidate if abs(z - candidate) <= abs(z + candidate) else -candidate
    q = 1.0 / (z + root)
    if not (abs(q) < 1.0 + 1.0e-13):
        raise ArithmeticError("failed to choose the decaying CPGF branch")
    return root, q


def contract_moments(
    tau_mean: np.ndarray,
    prefix: int,
    kind: str,
    energy: float,
    eta: float,
    lower: float,
    upper: float,
) -> complex:
    if prefix < 1 or prefix > tau_mean.shape[0]:
        raise SubmissionError("query prefix is outside the submitted cache")
    a = 0.5 * (upper - lower)
    b = 0.5 * (upper + lower)
    sigma = -1.0 if kind == "GA" else 1.0
    z = complex((energy - b) / a, sigma * eta / a)
    root, q = _decaying_root(z)
    powers = np.empty(prefix, dtype=np.complex128)
    powers[0] = 1.0
    for index in range(1, prefix):
        powers[index] = powers[index - 1] * q
    value = (tau_mean[0] + 2.0 * np.dot(powers[1:], tau_mean[1:prefix])) / (a * root)
    if kind == "DOS":
        return complex(-value.imag / math.pi, 0.0)
    return complex(value)


def response_values(
    tau: np.ndarray,
    manifest: dict[str, Any],
    queries: list[dict[str, Any]],
) -> np.ndarray:
    system_index = {system["system_id"]: index for index, system in enumerate(manifest["systems"])}
    values = np.empty(len(queries), dtype=np.complex128)
    for row_index, query in enumerate(queries):
        if query["system_id"] not in system_index:
            raise SubmissionError(f"unknown query system: {query['system_id']}")
        index = system_index[query["system_id"]]
        system = manifest["systems"][index]
        if query["prefix"] > manifest["moment_count"]:
            raise SubmissionError(f"query prefix too large: {query['query_id']}")
        values[row_index] = contract_moments(
            np.mean(tau[index], axis=0),
            query["prefix"],
            query["kind"],
            query["energy"],
            query["eta"],
            float(system["spectral_lower"]),
            float(system["spectral_upper"]),
        )
    return values


def compute_diagnostics(
    participant_dir: Path,
    manifest: dict[str, Any],
    tau: np.ndarray,
    public_query_count: int,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for index, system in enumerate(manifest["systems"]):
        onsite, edges, _ = load_system(participant_dir, system)
        values = tau[index]
        records.append(
            {
                "system_id": system["system_id"],
                "dimension": int(system["dimension"]),
                "tau0_max_abs_error": float(np.max(np.abs(values[:, 0] - 1.0))),
                "max_abs_imaginary_moment": float(np.max(np.abs(values.imag))),
                "max_abs_moment": float(np.max(np.abs(values))),
                "scaled_gershgorin_radius": scaled_gershgorin_radius(
                    onsite,
                    edges,
                    float(system["spectral_lower"]),
                    float(system["spectral_upper"]),
                ),
            }
        )
    return {
        "schema_version": "spectral-diagnostics/v1",
        "moment_count": int(manifest["moment_count"]),
        "probe_count": int(manifest["probe_count"]),
        "public_query_count": int(public_query_count),
        "systems": records,
    }


def write_moments(path: Path, manifest: dict[str, Any], tau: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        schema_version=np.asarray("spectral-moments/v1"),
        system_ids=np.asarray([item["system_id"] for item in manifest["systems"]]),
        dimensions=np.asarray([item["dimension"] for item in manifest["systems"]], dtype=np.int64),
        moment_count=np.asarray(int(manifest["moment_count"]), dtype=np.int64),
        probe_count=np.asarray(int(manifest["probe_count"]), dtype=np.int64),
        tau_real=np.asarray(tau.real, dtype=np.float64),
        tau_imag=np.asarray(tau.imag, dtype=np.float64),
    )


def write_response(path: Path, queries: list[dict[str, Any]], values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(RESPONSE_COLUMNS)
        for query, value in zip(queries, values):
            writer.writerow(
                [
                    query["query_id"],
                    query["system_id"],
                    query["prefix"],
                    query["kind"],
                    format(float(query["energy"]), ".17g"),
                    format(float(query["eta"]), ".17g"),
                    format(float(value.real), ".17g"),
                    format(float(value.imag), ".17g"),
                ]
            )


def write_diagnostics(path: Path, diagnostics: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalized_rmse(actual: np.ndarray, reference: np.ndarray, absolute: float, relative: float) -> float:
    scale = np.maximum(absolute, relative * np.abs(reference))
    ratio = np.abs(actual - reference) / scale
    clipped = np.minimum(ratio, 1.0e12)
    return float(np.sqrt(np.mean(clipped * clipped)))


def quality_score(error: float, excellent: float, minimum: float) -> float:
    if error <= excellent:
        return 1.0
    if error >= minimum:
        return 0.0
    return float((minimum - error) / (minimum - excellent))


def compare_diagnostics(actual: dict[str, Any], expected: dict[str, Any]) -> tuple[float, list[str]]:
    checks: list[tuple[str, bool]] = []
    checks.append(("public_query_count", actual["public_query_count"] == expected["public_query_count"]))
    numeric_keys = {
        "tau0_max_abs_error": (2.0e-12, 2.0e-8),
        "max_abs_imaginary_moment": (2.0e-12, 2.0e-8),
        "max_abs_moment": (2.0e-12, 2.0e-10),
        "scaled_gershgorin_radius": (2.0e-12, 2.0e-10),
    }
    for got, want in zip(actual["systems"], expected["systems"]):
        for key, (absolute, relative) in numeric_keys.items():
            difference = abs(float(got[key]) - float(want[key]))
            limit = max(absolute, relative * abs(float(want[key])))
            checks.append((f"{got['system_id']}.{key}", difference <= limit))
    failed = [name for name, passed in checks if not passed]
    return sum(passed for _, passed in checks) / len(checks), failed
