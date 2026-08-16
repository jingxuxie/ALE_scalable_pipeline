#!/usr/bin/env python3
"""Run every local release gate for the spectral-scaling audit task.

The verifier is intentionally self-contained and cross-platform.  It builds
the two clean-room submissions in a temporary directory, regenerates the
privileged fixtures twice, invokes the real guarded evaluator, and checks the
scientific negative controls.  Nothing is written into the task package unless
``--results`` is supplied; release automation normally points that option at
``author/verification_results.json``.
"""

from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable
import warnings
import zipfile

import numpy as np


sys.dont_write_bytecode = True


TASK_ROOT = Path(__file__).resolve().parents[1]
PARTICIPANT = TASK_ROOT / "participant"
AUTHOR = TASK_ROOT / "author"
PRIVATE = TASK_ROOT / "private"

CASE_INVENTORY = {
    "analysis_grid.json",
    "eigenvalues.npz",
    "manifest.json",
    "packets.csv",
    "queries.csv",
}
ALLOWED_ANALYZER_IMPORTS = {
    "__future__",
    "argparse",
    "collections",
    "csv",
    "itertools",
    "json",
    "math",
    "numpy",
    "pathlib",
    "typing",
}
REQUIRED_METAMORPHICS = {
    "row_packet_permutation",
    "realization_id_permutation",
    "positive_affine_energy",
    "affine_control",
    "target_mirror",
    "shard_rejoin",
}
MUTATION_MARKER = 'MUTATION_MODE = "correct"'
MAX_CASE_INPUT_BYTES = 256 * 1024 * 1024
MAX_NPZ_UNCOMPRESSED_BYTES = 40_020_000
MAX_NPY_HEADER_BYTES = 4_096
MAX_GENERIC_NPZ_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_GENERIC_NPZ_MEMBERS = 1_024
MAX_GENERIC_NPZ_RANK = 32
MAX_GENERIC_NPZ_ELEMENTS = MAX_GENERIC_NPZ_UNCOMPRESSED_BYTES
MAX_GENERIC_NPZ_ITEMSIZE = MAX_GENERIC_NPZ_UNCOMPRESSED_BYTES
UINT64_MAX = 2**64 - 1
MAX_BOOTSTRAP_SEED = UINT64_MAX - 1009 * 7
MAX_CSV_FIELD_BYTES = 128
MAX_INTEGER_TEXT_DIGITS = 20
CSV_PARSER_FIELD_LIMIT = 1_024
PACKET_COLUMNS = [
    "packet_id",
    "realization_id",
    "size",
    "control",
    "target",
    "e_min",
    "e_max",
    "shift_energy",
    "keep_count",
    "eigen_offset",
    "eigen_count",
]
QUERY_COLUMNS = ["query_id", "target", "size", "control"]
REFERENCE_OUTPUT_COLUMNS = {
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
REFERENCE_OUTPUT_INTEGER_COLUMNS = {
    "realization_stats.csv": {"size", "n_ratios"},
    "packet_stats.csv": {"size", "n_realizations", "n_ratios"},
    "transition.csv": {"stable"},
    "stability.csv": {"min_size", "n_groups", "fit_ok"},
    "predictions.csv": set(),
}


class VerificationFailure(RuntimeError):
    """A failed release gate, optionally carrying structured diagnostics."""

    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message)
        self.details = details


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_linklike(path: Path) -> bool:
    if path.is_symlink():
        return True
    junction = getattr(path, "is_junction", None)
    if junction is not None:
        try:
            if junction():
                return True
        except OSError:
            return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(TASK_ROOT).as_posix()
    except ValueError:
        return path.name


def _strict_json_loads(source: str, label: str) -> Any:
    """Parse JSON with duplicate-key and recursively finite-number checks."""

    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite JSON constant {token!r}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = value
        return result

    value = json.loads(
        source,
        parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )

    def require_finite(item: Any, location: str) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError(f"non-finite JSON number at {location}")
        if isinstance(item, dict):
            for key, child in item.items():
                require_finite(child, f"{location}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                require_finite(child, f"{location}[{index}]")

    require_finite(value, label)
    return value


def _json(path: Path) -> dict[str, Any]:
    try:
        value = _strict_json_loads(path.read_text(encoding="utf-8"), _relative(path))
    except Exception as error:
        raise VerificationFailure(f"invalid JSON in {_relative(path)}: {error}") from error
    if not isinstance(value, dict):
        raise VerificationFailure(f"{_relative(path)} must contain a JSON object")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_unsigned_integer_text(value: str) -> bool:
    return (
        1 <= len(value) <= MAX_INTEGER_TEXT_DIGITS
        and value.isascii()
        and value.isdecimal()
    )


def _read_contract_csv(
    path: Path,
    columns: list[str],
    *,
    integer_columns: set[str] | frozenset[str] = frozenset(),
    max_rows: int | None = None,
) -> list[dict[str, str]]:
    """Independently enforce the bounded public CSV lexical contract."""

    csv.field_size_limit(CSV_PARSER_FIELD_LIMIT)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                raise VerificationFailure(
                    f"CSV column drift in {_relative(path)}: {reader.fieldnames!r}"
                )
            rows: list[dict[str, str]] = []
            for row_index, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    raise VerificationFailure(
                        f"malformed CSV row in {_relative(path)}:{row_index}"
                    )
                oversized = [
                    name
                    for name, value in row.items()
                    if len(value.encode("utf-8")) > MAX_CSV_FIELD_BYTES
                ]
                if oversized:
                    raise VerificationFailure(
                        f"CSV field exceeds {MAX_CSV_FIELD_BYTES} UTF-8 bytes in "
                        f"{_relative(path)}:{row_index}: {oversized}"
                    )
                invalid_integers = [
                    name
                    for name in integer_columns
                    if not _is_unsigned_integer_text(row[name])
                ]
                if invalid_integers:
                    raise VerificationFailure(
                        f"CSV integer lexeme violates the 1-through-"
                        f"{MAX_INTEGER_TEXT_DIGITS}-digit ASCII contract in "
                        f"{_relative(path)}:{row_index}: {sorted(invalid_integers)}"
                    )
                rows.append(row)
                if max_rows is not None and len(rows) > max_rows:
                    raise VerificationFailure(
                        f"CSV row count exceeds {max_rows}: {_relative(path)}"
                    )
    except VerificationFailure:
        raise
    except (UnicodeError, csv.Error) as error:
        raise VerificationFailure(f"invalid bounded CSV {_relative(path)}: {error}") from error
    if not rows:
        raise VerificationFailure(f"CSV has no data rows: {_relative(path)}")
    return rows


def _safe_case_data_filename(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return False
    return (
        len(encoded) <= MAX_CSV_FIELD_BYTES
        and "/" not in value
        and "\\" not in value
        and not PurePosixPath(value).is_absolute()
        and not PureWindowsPath(value).is_absolute()
        and not bool(PureWindowsPath(value).drive)
        and value not in {".", "..", "manifest.json"}
    )


def _preflight_case_inventory(
    case_dir: Path, manifest: dict[str, Any]
) -> tuple[dict[str, Path], int]:
    """Independently enforce the flat, cross-platform five-file inventory."""

    if _is_linklike(case_dir) or not case_dir.is_dir():
        raise VerificationFailure(f"case root is not a regular directory: {_relative(case_dir)}")
    files = manifest.get("files")
    roles = ("packets", "eigenvalues", "queries", "analysis_grid")
    if not isinstance(files, dict) or set(files) != set(roles):
        raise VerificationFailure(f"manifest file-role drift: {_relative(case_dir)}")
    names = [files[role] for role in roles]
    if any(not _safe_case_data_filename(name) for name in names) or len(set(names)) != 4:
        raise VerificationFailure(
            f"manifest contains unsafe, non-portable, or duplicate filenames: {_relative(case_dir)}"
        )
    entries = list(case_dir.iterdir())
    if {entry.name for entry in entries} != {"manifest.json", *names}:
        raise VerificationFailure(f"case does not have the exact five-file inventory: {_relative(case_dir)}")
    physical_bytes = 0
    for entry in entries:
        if _is_linklike(entry) or not entry.is_file() or entry.stat().st_nlink != 1:
            raise VerificationFailure(
                f"case entry is not a single-link regular file: {_relative(entry)}"
            )
        physical_bytes += entry.stat().st_size
    if physical_bytes > MAX_CASE_INPUT_BYTES:
        raise VerificationFailure(f"case package exceeds 256 MiB: {_relative(case_dir)}")
    return ({role: case_dir / str(files[role]) for role in roles}, physical_bytes)


def _read_npy_header(
    member: Any, member_name: str
) -> tuple[tuple[int, ...], bool, np.dtype[Any], int]:
    """Read bounded NPY metadata without allocating the declared array."""

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
        raise VerificationFailure(
            f"{member_name}: unsupported NPY header version {version}"
        )
    return tuple(shape), bool(fortran_order), np.dtype(dtype), int(member.tell())


def _preflight_npz(path: Path, *, eigenvalue_contract: bool = False) -> dict[str, Any]:
    """Validate physical ZIP/NPY metadata before any eager ``np.load``.

    The generic bound protects semantic comparisons of author-only NPZ files.
    The stricter branch implements the participant eigenvalue-archive contract.
    """

    if not path.is_file() or _is_linklike(path):
        raise VerificationFailure(f"NPZ is not a regular non-link file: {_relative(path)}")
    if path.stat().st_size > MAX_CASE_INPUT_BYTES:
        raise VerificationFailure(f"NPZ physical size exceeds 256 MiB: {_relative(path)}")
    try:
        with zipfile.ZipFile(path, mode="r") as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if not 1 <= len(members) <= MAX_GENERIC_NPZ_MEMBERS:
                raise VerificationFailure(
                    f"NPZ physical member count is invalid: {_relative(path)}"
                )
            if len(set(names)) != len(names):
                raise VerificationFailure(
                    f"NPZ contains duplicate physical member names: {_relative(path)}"
                )
            if any(
                member.orig_filename != member.filename
                or "\x00" in member.orig_filename
                or "\x00" in member.filename
                for member in members
            ):
                raise VerificationFailure(
                    f"NPZ physical member names are inexact or contain NUL: {_relative(path)}"
                )
            if any(
                not name.endswith(".npy")
                or Path(name).name != name
                or "/" in name
                or "\\" in name
                or name in {".", ".."}
                for name in names
            ):
                raise VerificationFailure(
                    f"NPZ contains a non-flat or non-NPY member: {_relative(path)}"
                )
            uncompressed_bytes = sum(int(member.file_size) for member in members)
            generic_limit = MAX_GENERIC_NPZ_UNCOMPRESSED_BYTES
            if uncompressed_bytes > generic_limit:
                raise VerificationFailure(
                    f"NPZ uncompressed bytes exceed the safe semantic-load bound: {_relative(path)}"
                )
            if eigenvalue_contract and (
                len(members) != 2
                or names.count("schema_version.npy") != 1
                or names.count("energies.npy") != 1
                or uncompressed_bytes > MAX_NPZ_UNCOMPRESSED_BYTES
            ):
                raise VerificationFailure(
                    f"eigenvalue NPZ physical inventory/size contract failed: {_relative(path)}"
                )

            metadata: dict[str, Any] = {}
            for member in members:
                if member.flag_bits & 0x1:
                    raise VerificationFailure(
                        f"encrypted NPZ member is forbidden: {_relative(path)}:{member.filename}"
                    )
                if member.compress_type not in {
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                }:
                    raise VerificationFailure(
                        f"unsupported NPZ compression: {_relative(path)}:{member.filename}"
                    )
                with archive.open(member, mode="r") as stream:
                    shape, fortran_order, dtype, header_bytes = _read_npy_header(
                        stream, member.filename
                    )
                if fortran_order:
                    raise VerificationFailure(
                        f"Fortran-order NPY member is forbidden: {_relative(path)}:{member.filename}"
                    )
                if dtype.hasobject:
                    raise VerificationFailure(
                        f"object NPY member is forbidden: {_relative(path)}:{member.filename}"
                    )
                if len(shape) > MAX_GENERIC_NPZ_RANK:
                    raise VerificationFailure(
                        f"NPY rank exceeds the semantic-load bound: {_relative(path)}:{member.filename}"
                    )
                if any(
                    dimension < 0 or dimension > MAX_GENERIC_NPZ_ELEMENTS
                    for dimension in shape
                ):
                    raise VerificationFailure(
                        f"NPY dimension is negative or exceeds the semantic-load bound: "
                        f"{_relative(path)}:{member.filename}"
                    )
                if not 1 <= int(dtype.itemsize) <= MAX_GENERIC_NPZ_ITEMSIZE:
                    raise VerificationFailure(
                        f"NPY itemsize is zero or exceeds the semantic-load bound: "
                        f"{_relative(path)}:{member.filename}"
                    )
                item_count = math.prod(shape) if shape else 1
                if item_count > MAX_GENERIC_NPZ_ELEMENTS:
                    raise VerificationFailure(
                        f"NPY element/dimension count exceeds the semantic-load bound: "
                        f"{_relative(path)}:{member.filename}"
                    )
                payload_bytes = item_count * int(dtype.itemsize)
                if header_bytes + payload_bytes != int(member.file_size):
                    raise VerificationFailure(
                        f"NPY physical size disagrees with its header: {_relative(path)}:{member.filename}"
                    )
                metadata[member.filename] = {
                    "shape": shape,
                    "dtype": dtype,
                    "file_size": int(member.file_size),
                    "header_bytes": header_bytes,
                    "payload_bytes": payload_bytes,
                }
    except VerificationFailure:
        raise
    except (EOFError, OSError, OverflowError, ValueError, zipfile.BadZipFile) as error:
        raise VerificationFailure(f"invalid NPZ {_relative(path)}: {error}") from error

    if eigenvalue_contract:
        schema = metadata["schema_version.npy"]
        energies = metadata["energies.npy"]
        if (
            schema["shape"] != ()
            or schema["dtype"].kind != "U"
            or schema["dtype"].itemsize > 256
            or schema["dtype"].fields is not None
            or schema["dtype"].subdtype is not None
        ):
            raise VerificationFailure(
                f"schema_version.npy violates its bounded scalar contract: {_relative(path)}"
            )
        if (
            energies["dtype"] != np.dtype(np.float64)
            or not energies["dtype"].isnative
            or energies["dtype"].itemsize != 8
            or len(energies["shape"]) != 1
            or not 1 <= energies["shape"][0] <= 5_000_000
        ):
            raise VerificationFailure(
                f"energies.npy violates its float64 vector bounds: {_relative(path)}"
            )
    return {
        "physical_members": len(metadata),
        "uncompressed_bytes": sum(item["file_size"] for item in metadata.values()),
        "members": metadata,
    }


def _semantic_digest(path: Path) -> str:
    """Hash generated content without depending on ZIP member timestamps."""

    digest = hashlib.sha256()
    suffix = path.suffix.lower()
    if suffix == ".npz":
        preflight = _preflight_npz(path)
        with zipfile.ZipFile(path, mode="r") as archive:
            members = {member.filename: member for member in archive.infolist()}
            for name in sorted(members):
                metadata = preflight["members"][name]
                digest.update(name.encode("utf-8"))
                digest.update(
                    repr(np.lib.format.dtype_to_descr(metadata["dtype"])).encode("utf-8")
                )
                digest.update(json.dumps(list(metadata["shape"])).encode("ascii"))
                with archive.open(members[name], mode="r") as stream:
                    header = stream.read(int(metadata["header_bytes"]))
                    if len(header) != int(metadata["header_bytes"]):
                        raise VerificationFailure(
                            f"truncated NPY header during semantic hashing: {_relative(path)}:{name}"
                        )
                    remaining = int(metadata["payload_bytes"])
                    while remaining:
                        block = stream.read(min(1 << 20, remaining))
                        if not block:
                            raise VerificationFailure(
                                f"truncated NPY payload during semantic hashing: {_relative(path)}:{name}"
                            )
                        digest.update(block)
                        remaining -= len(block)
    elif suffix == ".json":
        try:
            value = _strict_json_loads(
                path.read_text(encoding="utf-8"), _relative(path)
            )
        except Exception as error:
            raise VerificationFailure(
                f"invalid JSON in semantic comparison for {_relative(path)}: {error}"
            ) from error
        digest.update(
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("ascii")
        )
    else:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise VerificationFailure(f"missing directory: {_relative(root)}")
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    }


def _compare_trees(left: Path, right: Path, label: str) -> dict[str, Any]:
    left_files = _files(left)
    right_files = _files(right)
    missing = sorted(set(left_files) - set(right_files))
    extra = sorted(set(right_files) - set(left_files))
    mismatched = [
        name
        for name in sorted(set(left_files) & set(right_files))
        if _semantic_digest(left_files[name]) != _semantic_digest(right_files[name])
    ]
    if missing or extra or mismatched:
        raise VerificationFailure(
            f"{label} differs",
            {
                "missing": missing[:20],
                "extra": extra[:20],
                "mismatched": mismatched[:20],
            },
        )
    combined = hashlib.sha256()
    for name, path in left_files.items():
        combined.update(name.encode("utf-8"))
        combined.update(_semantic_digest(path).encode("ascii"))
    return {"file_count": len(left_files), "semantic_sha256": combined.hexdigest()}


def _compare_trees_bytes(left: Path, right: Path, label: str) -> dict[str, Any]:
    left_files = _files(left)
    right_files = _files(right)
    missing = sorted(set(left_files) - set(right_files))
    extra = sorted(set(right_files) - set(left_files))
    hashes = {name: _sha256(path.read_bytes()) for name, path in left_files.items()}
    mismatched = [
        name
        for name in sorted(set(left_files) & set(right_files))
        if hashes[name] != _sha256(right_files[name].read_bytes())
    ]
    if missing or extra or mismatched:
        raise VerificationFailure(
            f"{label} is not byte-identical",
            {"missing": missing, "extra": extra, "mismatched": mismatched},
        )
    return {"file_count": len(left_files), "sha256": hashes}


def _run(
    arguments: list[str],
    *,
    cwd: Path,
    timeout: float,
    label: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    started = time.perf_counter()
    try:
        process = subprocess.run(
            arguments,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise VerificationFailure(f"{label} exceeded {timeout:g} seconds") from error
    if process.returncode != 0:
        stdout = process.stdout.decode("utf-8", errors="replace")[-3000:]
        stderr = process.stderr.decode("utf-8", errors="replace")[-5000:]
        raise VerificationFailure(
            f"{label} exited with status {process.returncode}",
            {
                "runtime_seconds": time.perf_counter() - started,
                "stdout_tail": stdout,
                "stderr_tail": stderr,
            },
        )
    return process


def _run_json(
    arguments: list[str],
    *,
    cwd: Path,
    timeout: float,
    label: str,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    process = _run(
        arguments,
        cwd=cwd,
        timeout=timeout,
        label=label,
        environment=environment,
    )
    try:
        value = _strict_json_loads(
            process.stdout.decode("utf-8"), f"{label} stdout"
        )
    except Exception as error:
        raise VerificationFailure(
            f"{label} did not emit one JSON object",
            {"stdout_tail": process.stdout.decode("utf-8", errors="replace")[-3000:]},
        ) from error
    if not isinstance(value, dict):
        raise VerificationFailure(f"{label} JSON result is not an object")
    return value


def _without_runtime(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_runtime(item)
            for key, item in value.items()
            if key not in {"runtime_seconds", "elapsed_seconds"}
        }
    if isinstance(value, list):
        return [_without_runtime(item) for item in value]
    return value


class Recorder:
    def __init__(self) -> None:
        self.gates: list[dict[str, Any]] = []

    def run(self, name: str, callback: Callable[[], Any]) -> Any | None:
        started = time.perf_counter()
        try:
            details = callback()
        except Exception as error:  # Each independent gate should still run.
            record: dict[str, Any] = {
                "name": name,
                "passed": False,
                "duration_seconds": time.perf_counter() - started,
                "error": f"{type(error).__name__}: {error}",
            }
            if isinstance(error, VerificationFailure) and error.details is not None:
                record["details"] = error.details
            self.gates.append(record)
            print(f"[verify] FAIL {name}: {error}", file=sys.stderr, flush=True)
            return None
        self.gates.append(
            {
                "name": name,
                "passed": True,
                "duration_seconds": time.perf_counter() - started,
                "details": details,
            }
        )
        print(f"[verify] PASS {name}", file=sys.stderr, flush=True)
        return details


def gate_inventory() -> dict[str, Any]:
    required = [
        PARTICIPANT / "TASK.md",
        PARTICIPANT / "software" / "README.md",
        PARTICIPANT / "software" / "validate_submission.py",
        AUTHOR / "task_spec.yaml",
        AUTHOR / "verification_report.md",
        AUTHOR / "oracle" / "generate.py",
        AUTHOR / "oracle" / "ed_realism.py",
        AUTHOR / "reference_solver" / "analyze.py",
        AUTHOR / "reference_solver" / "solve.py",
        AUTHOR / "alternative_solver" / "analyze.py",
        AUTHOR / "alternative_solver" / "solve.py",
        PRIVATE / "evaluation_spec.yaml",
        PRIVATE / "grader" / "core.py",
        PRIVATE / "grader" / "grade.py",
        PRIVATE / "grader" / "guarded_runner.py",
        PRIVATE / "reference" / "suite.json",
        PRIVATE / "mutants" / "manifest.json",
        PRIVATE / "mutants" / "build_mutants.py",
        PRIVATE / "probes" / "manifest.json",
        PRIVATE / "probes" / "run_probes.py",
        PRIVATE / "metamorphic" / "run.py",
        Path(__file__).resolve(),
    ]
    missing = [_relative(path) for path in required if not path.is_file()]
    checklists = [
        path
        for directory in (TASK_ROOT, AUTHOR)
        for path in directory.glob("*.md")
        if "checklist" in path.name.lower()
    ]
    if not checklists:
        missing.append("author/<release-checklist>.md")
    if missing:
        raise VerificationFailure("required package files are missing", {"missing": missing})

    expected_participant_files = {
        "TASK.md",
        "input/analysis_grid.json",
        "input/eigenvalues.npz",
        "input/manifest.json",
        "input/packets.csv",
        "input/queries.csv",
        "software/README.md",
        "software/validate_submission.py",
    }
    participant_inventory = set(_files(PARTICIPANT))
    if participant_inventory != expected_participant_files:
        raise VerificationFailure(
            "participant package inventory mismatch",
            {
                "missing": sorted(expected_participant_files - participant_inventory),
                "extra": sorted(participant_inventory - expected_participant_files),
            },
        )

    public_files = set(_files(PARTICIPANT / "input"))
    if public_files != CASE_INVENTORY:
        raise VerificationFailure(
            "retired public case inventory mismatch",
            {"expected": sorted(CASE_INVENTORY), "actual": sorted(public_files)},
        )
    public_manifest = _json(PARTICIPANT / "input" / "manifest.json")
    suite = _json(PRIVATE / "reference" / "suite.json")
    cases = suite.get("cases")
    if not isinstance(cases, list) or len(cases) < 3:
        raise VerificationFailure("hidden suite must contain at least three fresh cases")
    identifiers: list[str] = []
    for record in cases:
        if not isinstance(record, dict):
            raise VerificationFailure("hidden suite case record is not an object")
        case_id = str(record.get("case_id", ""))
        input_dir = (PRIVATE / "reference" / str(record.get("input", ""))).resolve()
        truth = (PRIVATE / "reference" / str(record.get("truth", ""))).resolve()
        oracle = (PRIVATE / "reference" / str(record.get("oracle_output", ""))).resolve()
        if not case_id or not _inside(input_dir, PRIVATE / "hidden_inputs"):
            raise VerificationFailure(f"unsafe or incomplete suite entry: {case_id!r}")
        if not _inside(truth, PRIVATE / "reference") or not _inside(
            oracle, PRIVATE / "reference"
        ):
            raise VerificationFailure(f"reference paths escape private tree: {case_id}")
        if set(_files(input_dir)) != CASE_INVENTORY:
            raise VerificationFailure(f"hidden input inventory mismatch: {case_id}")
        if _json(input_dir / "manifest.json").get("case_id") != case_id:
            raise VerificationFailure(f"suite/manifest case ID mismatch: {case_id}")
        if not truth.is_file() or not oracle.is_dir():
            raise VerificationFailure(f"missing truth or oracle output for {case_id}")
        identifiers.append(case_id)
    if public_manifest.get("case_id") in identifiers:
        raise VerificationFailure("retired public case is also used for hidden scoring")
    realism_records = suite.get("realism_cases", [])
    if realism_records:
        if not isinstance(realism_records, list):
            raise VerificationFailure("realism_cases must be a list")
        for record in realism_records:
            realism_path = (TASK_ROOT / str(record.get("path", ""))).resolve()
            if not _inside(realism_path, PRIVATE / "realism") or not realism_path.is_dir():
                raise VerificationFailure("realism fixture path is missing or unsafe")
    return {
        "required_file_count": len(required),
        "participant_file_count": len(participant_inventory),
        "release_checklist": _relative(checklists[0]),
        "retired_case": public_manifest.get("case_id"),
        "hidden_case_count": len(identifiers),
        "hidden_classes": sorted({str(record.get("class")) for record in cases}),
        "realism_case_count": len(realism_records),
    }


def gate_separation_and_leaks() -> dict[str, Any]:
    link_candidates = [PARTICIPANT, AUTHOR, PRIVATE, TASK_ROOT / "scripts"] + list(
        TASK_ROOT.rglob("*")
    )
    links = sorted({_relative(path) for path in link_candidates if _is_linklike(path)})
    if links:
        raise VerificationFailure("task package contains symbolic links", {"links": links})
    hardlinks = [
        _relative(path)
        for path in _files(TASK_ROOT).values()
        if path.stat().st_nlink != 1
    ]
    if hardlinks:
        raise VerificationFailure(
            "task package contains hard-linked files", {"hardlinks": hardlinks}
        )

    suite = _json(PRIVATE / "reference" / "suite.json")
    secrets: set[str] = set()
    for case in suite.get("cases", []):
        case_id = str(case["case_id"])
        secrets.add(case_id.lower())
        input_dir = (PRIVATE / "reference" / str(case["input"])).resolve()
        manifest = _json(input_dir / "manifest.json")
        token = str(manifest.get("case_token", ""))
        if token:
            secrets.add(token.lower())
    secrets.update(
        {
            "1411.0660",
            "many-body localization edge in the random-field heisenberg chain",
            "arxiv.org/abs/1411.0660",
            "luitz",
            "laflorencie",
            "private/reference",
            "truth.npz",
            "oracle_output",
            "pass_score",
            "mandatory =",
        }
    )
    forbidden_path_atoms = {"truth", "oracle", "reference", "hidden", "grader", "mutant"}
    text_files = []
    total_text_bytes = 0
    leaks: list[dict[str, str]] = []
    for path in _files(PARTICIPANT).values():
        relative = path.relative_to(PARTICIPANT).as_posix()
        atoms = {part.lower() for part in Path(relative).parts}
        if atoms & forbidden_path_atoms:
            leaks.append({"path": relative, "match": "forbidden participant path"})
        if path.suffix.lower() not in {".md", ".json", ".csv", ".py"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        text_files.append(relative)
        total_text_bytes += path.stat().st_size
        for secret in sorted(secrets):
            if secret and secret in text:
                leaks.append({"path": relative, "match": secret})
    if leaks:
        raise VerificationFailure("participant package leaks author-only evidence", {"leaks": leaks[:30]})
    for path in _files(PARTICIPANT).values():
        if not _inside(path, PARTICIPANT):
            raise VerificationFailure(f"participant artifact escapes its root: {path}")
    return {
        "participant_files_scanned": len(_files(PARTICIPANT)),
        "participant_text_files_scanned": len(text_files),
        "participant_text_bytes_scanned": total_text_bytes,
        "hidden_identifiers_checked": len(secrets),
        "symlink_count": 0,
        "hardlink_count": 0,
    }


def _analyzer_imports(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    if len(source.encode("utf-8")) > 250_000:
        raise VerificationFailure(f"analyzer source is oversized: {_relative(path)}")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        raise VerificationFailure(f"analyzer does not compile: {_relative(path)}: {error}") from error
    imports: set[str] = set()
    forbidden_calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add((node.module or "").split(".", 1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec", "compile", "__import__"}:
                forbidden_calls.add(node.func.id)
    unexpected = imports - ALLOWED_ANALYZER_IMPORTS
    if unexpected or forbidden_calls:
        raise VerificationFailure(
            f"analyzer uses capabilities outside the participant contract: {_relative(path)}",
            {
                "unexpected_imports": sorted(unexpected),
                "forbidden_dynamic_calls": sorted(forbidden_calls),
            },
        )
    return imports


def _load_public_validator() -> Any:
    path = PARTICIPANT / "software" / "validate_submission.py"
    specification = importlib.util.spec_from_file_location(
        "_spectral_scaling_public_validator_release_audit", path
    )
    if specification is None or specification.loader is None:
        raise VerificationFailure("could not load the public validator for release audit")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    for name in (
        "load_expected",
        "parse_outputs",
        "preflight_npz",
        "inspect_source",
        "preliminary_center",
    ):
        if not callable(getattr(module, name, None)):
            raise VerificationFailure(f"public validator is missing callable {name}")
    return module


def _independent_preliminary_center(target_rows: list[dict[str, Any]]) -> float:
    centers: list[float] = []
    for size in sorted({int(row["size"]) for row in target_rows}):
        curve = sorted(
            (row for row in target_rows if int(row["size"]) == size),
            key=lambda row: float(row["control"]),
        )
        controls = np.asarray([float(row["control"]) for row in curve], dtype=np.float64)
        values = np.asarray([float(row["mean_r"]) for row in curve], dtype=np.float64)
        flank = max(2, min(3, values.size // 3))
        midpoint = 0.5 * (
            float(np.median(values[:flank])) + float(np.median(values[-flank:]))
        )
        candidates: list[float] = []
        for index in range(values.size - 1):
            left = float(values[index] - midpoint)
            right = float(values[index + 1] - midpoint)
            if left == 0.0:
                candidates.append(float(controls[index]))
            elif (
                (left < 0.0 < right)
                or (left > 0.0 > right)
                or right == 0.0
            ) and values[index + 1] != values[index]:
                fraction = (midpoint - values[index]) / (
                    values[index + 1] - values[index]
                )
                candidates.append(
                    float(
                        controls[index]
                        + fraction * (controls[index + 1] - controls[index])
                    )
                )
        if candidates:
            middle = float(np.median(controls))
            centers.append(min(candidates, key=lambda value: abs(value - middle)))
    if centers:
        return float(np.median(np.asarray(centers, dtype=np.float64)))
    return float(
        np.median(np.asarray([float(row["control"]) for row in target_rows]))
    )


def _independent_packet_numeric_envelope(
    case_dir: Path,
    manifest: dict[str, Any],
    packet_rows: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[float, list[dict[str, Any]]]]:
    """Recompute packet evidence and affine float64 margins independently."""

    archive_path = case_dir / str(manifest["files"]["eigenvalues"])
    _preflight_npz(archive_path, eigenvalue_contract=True)
    with np.load(archive_path, allow_pickle=False) as archive:
        if set(archive.files) != {"schema_version", "energies"}:
            raise VerificationFailure(f"logical eigenvalue members drifted: {_relative(case_dir)}")
        schema = np.asarray(archive["schema_version"])
        energies = np.asarray(archive["energies"])
    if (
        schema.shape != ()
        or schema.dtype.kind != "U"
        or str(schema.item()) != "spectral-scaling-eigenvalues/v1"
        or energies.dtype != np.float64
        or not energies.dtype.isnative
        or energies.ndim != 1
        or not np.all(np.isfinite(energies))
        or np.any(np.abs(energies) > 1e100)
    ):
        raise VerificationFailure(f"logical eigenvalue contract failed: {_relative(case_dir)}")

    groups: dict[tuple[float, int, float], list[tuple[float, int]]] = {}
    realization_keys: set[tuple[float, int, float, str]] = set()
    raw_group_coordinates: dict[
        tuple[float, int, float], tuple[float, int, float]
    ] = {}
    expected_offset = 0
    packets_with_boundary = 0
    minimum_gap_requirement_ratio = math.inf
    minimum_cutoff_requirement_ratio = math.inf
    transformed_minimum_gap_requirement_ratio = math.inf
    transformed_minimum_cutoff_requirement_ratio = math.inf
    minimum_gap_margin = math.inf
    minimum_gap_margin_over_span = math.inf
    minimum_gap_margin_ulps = math.inf
    minimum_cutoff_margin = math.inf
    minimum_cutoff_margin_over_span = math.inf
    minimum_cutoff_margin_ulps = math.inf
    maximum_shift_span_fraction = 0.0
    transformed_maximum_shift_span_fraction = 0.0
    minimum_shift_offset = math.inf
    maximum_shift_offset = 0.0
    maximum_ratio_perturbation = 0.0
    maximum_absolute_energy_coordinate = 0.0
    exact_selected_prefix = True
    exact_energy_sorted_indices = True

    for row_index, row in enumerate(packet_rows, start=2):
        offset = int(row["eigen_offset"])
        count = int(row["eigen_count"])
        keep = int(row["keep_count"])
        e_min = float(row["e_min"])
        e_max = float(row["e_max"])
        target = float(row["target"])
        shift = float(row["shift_energy"])
        raw_control = float(row["control"])
        control = round(raw_control, 10)
        size = int(row["size"])
        canonical_target = round(target, 10)
        canonical_group = (canonical_target, size, control)
        raw_group = (target, size, raw_control)
        prior_raw_group = raw_group_coordinates.setdefault(canonical_group, raw_group)
        if prior_raw_group != raw_group:
            raise VerificationFailure(
                f"distinct raw coordinates collide after canonicalization at "
                f"{_relative(case_dir)}:{row_index}"
            )
        if offset != expected_offset or offset + count > energies.size:
            raise VerificationFailure(
                f"independent packet slice coverage failed at {_relative(case_dir)}:{row_index}"
            )
        expected_offset += count
        chunk = np.asarray(energies[offset : offset + count], dtype=np.float64)
        if np.any(chunk < e_min) or np.any(chunk > e_max):
            raise VerificationFailure(
                f"raw chunk escapes declared extrema at {_relative(case_dir)}:{row_index}"
            )
        target_energy = e_max + target * (e_min - e_max)
        span = max(float(np.ptp(chunk)), e_max - e_min)
        magnitude = max(
            1.0,
            float(np.max(np.abs(chunk))),
            abs(e_min),
            abs(e_max),
            abs(target_energy),
        )
        if not math.isfinite(target_energy) or not 0.0 < span:
            raise VerificationFailure(
                f"independent target/span arithmetic failed at {_relative(case_dir)}:{row_index}"
            )
        shift_offset = abs(shift - target_energy)
        shift_fraction = shift_offset / (e_max - e_min)
        if not math.isfinite(shift_fraction) or shift_fraction > 0.005:
            raise VerificationFailure(
                f"shift/span predicate failed at {_relative(case_dir)}:{row_index}"
            )
        minimum_shift_offset = min(minimum_shift_offset, shift_offset)
        maximum_shift_offset = max(maximum_shift_offset, shift_offset)
        maximum_shift_span_fraction = max(maximum_shift_span_fraction, shift_fraction)

        distances = np.abs(chunk - target_energy)
        order = np.argsort(distances, kind="stable")
        selected_prefix = order[:keep]
        energy_order = selected_prefix[
            np.argsort(chunk[selected_prefix], kind="stable")
        ]
        selected = chunk[energy_order]
        gaps = np.diff(selected)
        ulp_requirement = 1_048_576.0 * math.ulp(magnitude)
        gap_requirement = max(1e-9 * span, ulp_requirement)
        minimum_gap = float(np.min(gaps))
        if (
            gaps.size < 3
            or not np.all(np.isfinite(gaps))
            or minimum_gap < gap_requirement
        ):
            raise VerificationFailure(
                f"selected-gap conditioning failed at {_relative(case_dir)}:{row_index}"
            )
        minimum_gap_requirement_ratio = min(
            minimum_gap_requirement_ratio, minimum_gap / gap_requirement
        )
        minimum_gap_margin = min(minimum_gap_margin, minimum_gap)
        minimum_gap_margin_over_span = min(
            minimum_gap_margin_over_span, minimum_gap / span
        )
        minimum_gap_margin_ulps = min(
            minimum_gap_margin_ulps, minimum_gap / math.ulp(magnitude)
        )
        if keep < count:
            packets_with_boundary += 1
            cutoff_margin = float(distances[order[keep]] - distances[order[keep - 1]])
            cutoff_requirement = max(1e-8 * span, ulp_requirement)
            if not math.isfinite(cutoff_margin) or cutoff_margin < cutoff_requirement:
                raise VerificationFailure(
                    f"keep-boundary conditioning failed at {_relative(case_dir)}:{row_index}"
                )
            minimum_cutoff_requirement_ratio = min(
                minimum_cutoff_requirement_ratio, cutoff_margin / cutoff_requirement
            )
            minimum_cutoff_margin = min(minimum_cutoff_margin, cutoff_margin)
            minimum_cutoff_margin_over_span = min(
                minimum_cutoff_margin_over_span, cutoff_margin / span
            )
            minimum_cutoff_margin_ulps = min(
                minimum_cutoff_margin_ulps, cutoff_margin / math.ulp(magnitude)
            )
        ratios = np.minimum(gaps[:-1], gaps[1:]) / np.maximum(gaps[:-1], gaps[1:])

        scale = 1.625
        translation = -4.75
        transformed_chunk = scale * chunk + translation
        transformed_e_min = scale * e_min + translation
        transformed_e_max = scale * e_max + translation
        transformed_shift = scale * shift + translation
        transformed_target_energy = transformed_e_max + target * (
            transformed_e_min - transformed_e_max
        )
        if (
            not np.all(np.isfinite(transformed_chunk))
            or np.any(transformed_chunk < transformed_e_min)
            or np.any(transformed_chunk > transformed_e_max)
        ):
            raise VerificationFailure(
                f"transformed extrema containment failed at {_relative(case_dir)}:{row_index}"
            )
        transformed_span = max(
            float(np.ptp(transformed_chunk)), transformed_e_max - transformed_e_min
        )
        transformed_magnitude = max(
            1.0,
            float(np.max(np.abs(transformed_chunk))),
            abs(transformed_e_min),
            abs(transformed_e_max),
            abs(transformed_target_energy),
        )
        transformed_shift_offset = abs(transformed_shift - transformed_target_energy)
        transformed_shift_fraction = transformed_shift_offset / (
            transformed_e_max - transformed_e_min
        )
        minimum_shift_offset = min(minimum_shift_offset, transformed_shift_offset)
        maximum_shift_offset = max(maximum_shift_offset, transformed_shift_offset)
        transformed_maximum_shift_span_fraction = max(
            transformed_maximum_shift_span_fraction, transformed_shift_fraction
        )
        if (
            not math.isfinite(transformed_shift_fraction)
            or transformed_shift_fraction > 0.005
            or transformed_magnitude > 1e100
        ):
            raise VerificationFailure(
                f"transformed shift/magnitude predicate failed at {_relative(case_dir)}:{row_index}"
            )
        transformed_distances = np.abs(
            transformed_chunk - transformed_target_energy
        )
        transformed_order = np.argsort(transformed_distances, kind="stable")
        transformed_prefix = transformed_order[:keep]
        transformed_energy_order = transformed_prefix[
            np.argsort(transformed_chunk[transformed_prefix], kind="stable")
        ]
        exact_selected_prefix = exact_selected_prefix and np.array_equal(
            selected_prefix, transformed_prefix
        )
        exact_energy_sorted_indices = exact_energy_sorted_indices and np.array_equal(
            energy_order, transformed_energy_order
        )
        transformed_selected = transformed_chunk[transformed_energy_order]
        transformed_gaps = np.diff(transformed_selected)
        transformed_ulp_requirement = 1_048_576.0 * math.ulp(
            transformed_magnitude
        )
        transformed_gap_requirement = max(
            1e-9 * transformed_span, transformed_ulp_requirement
        )
        transformed_minimum_gap = float(np.min(transformed_gaps))
        if (
            not np.all(np.isfinite(transformed_gaps))
            or transformed_minimum_gap < transformed_gap_requirement
        ):
            raise VerificationFailure(
                f"transformed selected-gap conditioning failed at {_relative(case_dir)}:{row_index}"
            )
        transformed_minimum_gap_requirement_ratio = min(
            transformed_minimum_gap_requirement_ratio,
            transformed_minimum_gap / transformed_gap_requirement,
        )
        minimum_gap_margin = min(minimum_gap_margin, transformed_minimum_gap)
        minimum_gap_margin_over_span = min(
            minimum_gap_margin_over_span,
            transformed_minimum_gap / transformed_span,
        )
        minimum_gap_margin_ulps = min(
            minimum_gap_margin_ulps,
            transformed_minimum_gap / math.ulp(transformed_magnitude),
        )
        if keep < count:
            transformed_cutoff_margin = float(
                transformed_distances[transformed_order[keep]]
                - transformed_distances[transformed_order[keep - 1]]
            )
            transformed_cutoff_requirement = max(
                1e-8 * transformed_span, transformed_ulp_requirement
            )
            if (
                not math.isfinite(transformed_cutoff_margin)
                or transformed_cutoff_margin < transformed_cutoff_requirement
            ):
                raise VerificationFailure(
                    f"transformed cutoff conditioning failed at {_relative(case_dir)}:{row_index}"
                )
            transformed_minimum_cutoff_requirement_ratio = min(
                transformed_minimum_cutoff_requirement_ratio,
                transformed_cutoff_margin / transformed_cutoff_requirement,
            )
            minimum_cutoff_margin = min(
                minimum_cutoff_margin, transformed_cutoff_margin
            )
            minimum_cutoff_margin_over_span = min(
                minimum_cutoff_margin_over_span,
                transformed_cutoff_margin / transformed_span,
            )
            minimum_cutoff_margin_ulps = min(
                minimum_cutoff_margin_ulps,
                transformed_cutoff_margin / math.ulp(transformed_magnitude),
            )
        transformed_ratios = np.minimum(
            transformed_gaps[:-1], transformed_gaps[1:]
        ) / np.maximum(transformed_gaps[:-1], transformed_gaps[1:])
        ratio_perturbation = float(np.max(np.abs(ratios - transformed_ratios)))
        maximum_ratio_perturbation = max(
            maximum_ratio_perturbation, ratio_perturbation
        )
        if not np.all(np.isfinite(transformed_ratios)) or not math.isfinite(
            ratio_perturbation
        ) or ratio_perturbation > 1e-10:
            raise VerificationFailure(
                f"affine ratio covariance failed at {_relative(case_dir)}:{row_index}"
            )
        maximum_absolute_energy_coordinate = max(
            maximum_absolute_energy_coordinate,
            float(np.max(np.abs(chunk))),
            abs(e_min),
            abs(e_max),
            abs(shift),
            abs(target_energy),
            float(np.max(np.abs(transformed_chunk))),
            abs(transformed_e_min),
            abs(transformed_e_max),
            abs(transformed_shift),
            abs(transformed_target_energy),
        )
        if maximum_absolute_energy_coordinate > 1e100:
            raise VerificationFailure(
                f"affine energy magnitude bound failed at {_relative(case_dir)}:{row_index}"
            )

        key = (canonical_target, size, control, row["realization_id"])
        if key in realization_keys:
            raise VerificationFailure(
                f"duplicate independent realization key at {_relative(case_dir)}:{row_index}"
            )
        realization_keys.add(key)
        group_key = key[:3]
        groups.setdefault(group_key, []).append((float(np.mean(ratios)), int(ratios.size)))

    if expected_offset != energies.size or not exact_selected_prefix or not exact_energy_sorted_indices:
        raise VerificationFailure(f"independent packet/affine coverage failed: {_relative(case_dir)}")
    grouped_rows: dict[float, list[dict[str, Any]]] = {}
    for (target, size, control), values in groups.items():
        means = np.asarray([value[0] for value in values], dtype=np.float64)
        row = {
            "target": target,
            "size": size,
            "control": control,
            "mean_r": float(np.mean(means)),
            "se_r": float(np.std(means, ddof=1) / math.sqrt(means.size)),
            "n_realizations": int(means.size),
            "n_ratios": sum(value[1] for value in values),
        }
        grouped_rows.setdefault(target, []).append(row)
    envelope = {
        "packets_checked": len(packet_rows),
        "packets_with_keep_boundary": packets_with_boundary,
        "chunk_extrema_containment": True,
        "maximum_shift_span_fraction": maximum_shift_span_fraction,
        "transformed_maximum_shift_span_fraction": (
            transformed_maximum_shift_span_fraction
        ),
        "minimum_absolute_shift_offset": minimum_shift_offset,
        "maximum_absolute_shift_offset": maximum_shift_offset,
        "minimum_selected_gap": minimum_gap_margin,
        "minimum_selected_gap_over_span": minimum_gap_margin_over_span,
        "minimum_selected_gap_ulps": minimum_gap_margin_ulps,
        "minimum_keep_boundary_margin": (
            minimum_cutoff_margin if packets_with_boundary else None
        ),
        "minimum_keep_boundary_margin_over_span": (
            minimum_cutoff_margin_over_span if packets_with_boundary else None
        ),
        "minimum_keep_boundary_margin_ulps": (
            minimum_cutoff_margin_ulps if packets_with_boundary else None
        ),
        "minimum_gap_requirement_ratio": minimum_gap_requirement_ratio,
        "minimum_cutoff_requirement_ratio": (
            minimum_cutoff_requirement_ratio
            if packets_with_boundary
            else None
        ),
        "transformed_minimum_gap_requirement_ratio": (
            transformed_minimum_gap_requirement_ratio
        ),
        "transformed_minimum_cutoff_requirement_ratio": (
            transformed_minimum_cutoff_requirement_ratio
            if packets_with_boundary
            else None
        ),
        "exact_selected_prefix_preserved": True,
        "exact_energy_sorted_indices_preserved": True,
        "maximum_ratio_perturbation": maximum_ratio_perturbation,
        "maximum_absolute_energy_coordinate": maximum_absolute_energy_coordinate,
        "group_count": len(groups),
        "distinct_raw_group_coordinates": len(raw_group_coordinates),
        "canonical_coordinate_collisions": 0,
    }
    return envelope, grouped_rows


def _independent_cubic_diagnostic(
    target_rows: list[dict[str, Any]],
    h_c: float,
    nu: float,
    min_size: int,
    halfwidth: float,
) -> dict[str, Any]:
    if not math.isfinite(h_c) or not math.isfinite(nu) or not 0.2 <= nu <= 4.0:
        raise VerificationFailure("independent cubic diagnostic received invalid h_c/nu")
    center = _independent_preliminary_center(target_rows)
    selected = [
        row
        for row in target_rows
        if int(row["size"]) >= int(min_size)
        and abs(float(row["control"]) - center)
        <= float(halfwidth) * (1.0 + 1e-12)
    ]
    if len(selected) < 8 or len({int(row["size"]) for row in selected}) < 3:
        raise VerificationFailure("independent cubic diagnostic has insufficient support")
    control = np.asarray([float(row["control"]) for row in selected], dtype=np.float64)
    size = np.asarray([float(row["size"]) for row in selected], dtype=np.float64)
    observed = np.asarray([float(row["mean_r"]) for row in selected], dtype=np.float64)
    se = np.asarray(
        [max(float(row["se_r"]), 0.0025) for row in selected], dtype=np.float64
    )
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        x = (control - h_c) * np.power(size, 1.0 / nu)
    maximum_x = float(np.max(np.abs(x)))
    if not np.all(np.isfinite(x)) or maximum_x > 2.1e36:
        raise VerificationFailure("independent training scaling-coordinate bound failed")
    x_scale = max(maximum_x, 1.0)
    z = x / x_scale
    maximum_z = float(np.max(np.abs(z)))
    if not np.all(np.isfinite(z)) or maximum_z > 1.0 + 8.0 * np.finfo(np.float64).eps:
        raise VerificationFailure("independent standardized training-coordinate bound failed")
    matrix = np.column_stack([np.ones(z.size), z, z * z, z * z * z])
    weights = 1.0 / se
    weighted_matrix = matrix * weights[:, None]
    weighted_observed = observed * weights
    if (
        not np.all(np.isfinite(weighted_matrix))
        or not np.all(np.isfinite(weighted_observed))
    ):
        raise VerificationFailure("independent cubic weighted system is non-finite")
    condition = float(np.linalg.cond(weighted_matrix))
    if not math.isfinite(condition) or condition > 1e12:
        raise VerificationFailure("independent cubic design-conditioning bound failed")
    coefficients, _, rank, _ = np.linalg.lstsq(
        weighted_matrix, weighted_observed, rcond=None
    )
    maximum_coefficient = float(np.max(np.abs(coefficients)))
    if rank < 4 or not np.all(np.isfinite(coefficients)) or maximum_coefficient > 1e6:
        raise VerificationFailure("independent cubic rank/coefficient bound failed")
    weighted_residual = (matrix @ coefficients - observed) * weights
    squared_residual_sum = float(np.sum(np.square(weighted_residual)))
    squared_weight_sum = float(np.sum(np.square(weights)))
    if (
        not np.all(np.isfinite(weighted_residual))
        or not math.isfinite(squared_residual_sum)
        or squared_residual_sum > 1e35
        or not math.isfinite(squared_weight_sum)
        or squared_weight_sum <= 0.0
    ):
        raise VerificationFailure("independent cubic residual bound failed")
    return {
        "coefficients": coefficients,
        "x_scale": x_scale,
        "condition": condition,
        "maximum_absolute_coefficient": maximum_coefficient,
        "maximum_absolute_training_x": maximum_x,
        "maximum_absolute_training_z": maximum_z,
        "weighted_residual_square_sum": squared_residual_sum,
        "validation_rmse": math.sqrt(squared_residual_sum / squared_weight_sum),
        "n_groups": len(selected),
    }


def _independent_reference_numeric_envelope(
    output: Path,
    grouped_rows: dict[float, list[dict[str, Any]]],
    grid: dict[str, Any],
    query_rows: list[dict[str, str]],
) -> dict[str, Any]:
    """Recompute every reference cubic/query domain guard from emitted outputs."""

    def rows(name: str) -> list[dict[str, str]]:
        return _read_contract_csv(
            output / name,
            REFERENCE_OUTPUT_COLUMNS[name],
            integer_columns=REFERENCE_OUTPUT_INTEGER_COLUMNS[name],
        )

    output_rows = {name: rows(name) for name in REFERENCE_OUTPUT_COLUMNS}
    transition_rows = output_rows["transition.csv"]
    stability_rows = output_rows["stability.csv"]
    prediction_rows = output_rows["predictions.csv"]
    transitions = {
        round(float(row["target"]), 10): row for row in transition_rows
    }
    predictions = {row["query_id"]: row for row in prediction_rows}
    diagnostics: list[dict[str, Any]] = []
    for row in stability_rows:
        target = round(float(row["target"]), 10)
        diagnostic = _independent_cubic_diagnostic(
            grouped_rows[target],
            float(row["h_c"]),
            float(row["nu"]),
            int(row["min_size"]),
            round(float(row["halfwidth"]), 10),
        )
        if (
            int(row["fit_ok"]) != 1
            or int(row["n_groups"]) != diagnostic["n_groups"]
            or abs(float(row["validation_rmse"]) - diagnostic["validation_rmse"])
            > 2e-7
        ):
            raise VerificationFailure("independent stability diagnostic mismatch")
        diagnostics.append(diagnostic)
    primary: dict[float, dict[str, Any]] = {}
    for target, row in transitions.items():
        diagnostic = _independent_cubic_diagnostic(
            grouped_rows[target],
            float(row["h_c"]),
            float(row["nu"]),
            int(grid["primary_min_size"]),
            round(float(grid["primary_halfwidth"]), 10),
        )
        expected_fit_score = 1.0 / (1.0 + diagnostic["validation_rmse"] / 0.02)
        if abs(float(row["fit_score"]) - expected_fit_score) > 2e-7:
            raise VerificationFailure("independent transition fit-score mismatch")
        primary[target] = diagnostic
        diagnostics.append(diagnostic)

    maximum_query_x = 0.0
    maximum_query_z = 0.0
    maximum_raw_polynomial = 0.0
    for query in query_rows:
        target = round(float(query["target"]), 10)
        transition = transitions[target]
        diagnostic = primary[target]
        nu = float(transition["nu"])
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            x = (float(query["control"]) - float(transition["h_c"])) * float(
                query["size"]
            ) ** (1.0 / nu)
        z = x / float(diagnostic["x_scale"])
        basis = np.asarray([1.0, z, z * z, z * z * z], dtype=np.float64)
        raw_prediction = float(np.dot(basis, diagnostic["coefficients"]))
        if (
            not math.isfinite(x)
            or abs(x) > 2.1e36
            or not math.isfinite(z)
            or abs(z) > 2.0
            or not np.all(np.isfinite(basis))
            or not math.isfinite(raw_prediction)
            or abs(raw_prediction) > 2e7
        ):
            raise VerificationFailure(
                f"independent query numeric bound failed: {query['query_id']}"
            )
        submitted = float(predictions[query["query_id"]]["mean_r"])
        if abs(submitted - float(np.clip(raw_prediction, 0.0, 1.0))) > 0.08:
            raise VerificationFailure(
                f"independent reference query prediction mismatch: {query['query_id']}"
            )
        maximum_query_x = max(maximum_query_x, abs(x))
        maximum_query_z = max(maximum_query_z, abs(z))
        maximum_raw_polynomial = max(maximum_raw_polynomial, abs(raw_prediction))

    return {
        "diagnostics_checked": len(diagnostics),
        "bounded_csv_rows_checked": sum(map(len, output_rows.values())),
        "stability_diagnostics_checked": len(stability_rows),
        "transition_diagnostics_checked": len(transition_rows),
        "queries_checked": len(query_rows),
        "maximum_absolute_training_x": max(
            item["maximum_absolute_training_x"] for item in diagnostics
        ),
        "maximum_absolute_training_z": max(
            item["maximum_absolute_training_z"] for item in diagnostics
        ),
        "maximum_weighted_design_condition": max(
            item["condition"] for item in diagnostics
        ),
        "maximum_absolute_cubic_coefficient": max(
            item["maximum_absolute_coefficient"] for item in diagnostics
        ),
        "maximum_weighted_residual_square_sum": max(
            item["weighted_residual_square_sum"] for item in diagnostics
        ),
        "maximum_absolute_query_x": maximum_query_x,
        "maximum_absolute_query_z": maximum_query_z,
        "maximum_absolute_raw_query_polynomial": maximum_raw_polynomial,
    }


def _audit_case_numeric_contract(
    case_dir: Path,
    public_validator: Any,
    *,
    oracle_output: Path | None,
) -> dict[str, Any]:
    """Apply every published input bound and the public numeric output contract."""

    manifest_path = case_dir / "manifest.json"
    if (
        not manifest_path.is_file()
        or _is_linklike(manifest_path)
        or manifest_path.stat().st_size > 65_536
    ):
        raise VerificationFailure(f"manifest physical contract failed: {_relative(case_dir)}")
    manifest = _json(manifest_path)
    case_files, physical_bytes = _preflight_case_inventory(case_dir, manifest)
    eigenvalue_path = case_files["eigenvalues"]
    npz = _preflight_npz(eigenvalue_path, eigenvalue_contract=True)
    try:
        expected = public_validator.load_expected(case_dir)
    except Exception as error:
        raise VerificationFailure(
            f"published input contract failed: {_relative(case_dir)}: {error}"
        ) from error

    packet_path = case_files["packets"]
    query_path = case_files["queries"]
    packet_rows = _read_contract_csv(
        packet_path,
        PACKET_COLUMNS,
        integer_columns={"size", "keep_count", "eigen_offset", "eigen_count"},
        max_rows=6_000,
    )
    query_rows = _read_contract_csv(
        query_path,
        QUERY_COLUMNS,
        max_rows=512,
    )
    if case_files["analysis_grid"].stat().st_size > 65_536:
        raise VerificationFailure(f"analysis grid is oversized: {_relative(case_dir)}")

    packet_numeric_envelope, independent_target_rows = (
        _independent_packet_numeric_envelope(case_dir, manifest, packet_rows)
    )

    grouped = expected["grouped"]
    realization = expected["realization"]
    targets = list(expected["targets"])
    sizes = sorted({int(key[1]) for key in grouped})
    controls_by_curve: dict[tuple[float, int], set[float]] = {}
    for target, size, control in grouped:
        controls_by_curve.setdefault((float(target), int(size)), set()).add(float(control))
    realizations_per_group = [int(value["n_realizations"]) for value in grouped.values()]
    eigen_counts = [int(row["eigen_count"]) for row in packet_rows]
    keep_counts = [int(row["keep_count"]) for row in packet_rows]
    observed_controls = [float(row["control"]) for row in packet_rows]
    query_controls = [float(row["control"]) for row in query_rows]
    target_coordinates = [float(row["target"]) for row in packet_rows]
    grid = expected["grid"]
    raw_halfwidths = [float(value) for value in grid["halfwidths"]]
    min_sizes = [int(value) for value in grid["min_sizes"]]
    energy_count = int(npz["members"]["energies.npy"]["shape"][0])
    seed = manifest.get("bootstrap_seed")
    resource = manifest.get("resource_contract")
    interval_level = grid.get("interval_level")
    input_field_byte_lengths = [
        len(value.encode("utf-8"))
        for row in (*packet_rows, *query_rows)
        for value in row.values()
    ]
    integer_lexeme_lengths = [
        len(row[name])
        for row in packet_rows
        for name in ("size", "keep_count", "eigen_offset", "eigen_count")
    ]

    independent_grouped = {
        (float(target), int(row["size"]), float(row["control"])): row
        for target, rows_for_target in independent_target_rows.items()
        for row in rows_for_target
    }
    if set(independent_grouped) != set(grouped):
        raise VerificationFailure(
            f"independent grouped-key coverage mismatch: {_relative(case_dir)}"
        )
    for key, reference_group in grouped.items():
        independent_group = independent_grouped[key]
        if (
            independent_group["n_realizations"] != reference_group["n_realizations"]
            or independent_group["n_ratios"] != reference_group["n_ratios"]
            or abs(independent_group["mean_r"] - reference_group["mean_r"]) > 5e-12
            or abs(independent_group["se_r"] - reference_group["se_r"]) > 5e-12
        ):
            raise VerificationFailure(
                f"independent grouped statistic mismatch at {key}: {_relative(case_dir)}"
            )

    target_size_counts = {
        target: len({size for observed_target, size in controls_by_curve if observed_target == target})
        for target in targets
    }
    fit_group_counts = list(expected["n_groups_by_stability"].values())
    fit_size_counts: list[int] = []
    for target, min_size, halfwidth in expected["stability_keys"]:
        rows = expected["target_rows"][target]
        center = public_validator.preliminary_center(rows)
        selected = [
            row
            for row in rows
            if int(row["size"]) >= int(min_size)
            and abs(float(row["control"]) - center)
            <= float(halfwidth) * (1.0 + 1e-12)
        ]
        fit_size_counts.append(len({int(row["size"]) for row in selected}))

    invalid = []
    if (
        not isinstance(resource, dict)
        or set(resource)
        != {"python", "numpy", "network", "wall_time_seconds", "output_bytes"}
        or resource.get("python") != "3.11+"
        or resource.get("numpy") != "2.3.5"
        or resource.get("network") != "disabled"
    ):
        invalid.append("exact resource string contract")
    if type(interval_level) not in {int, float} or interval_level != 0.68:
        invalid.append("exact numeric interval level")
    if not 1 <= len(packet_rows) <= 6_000:
        invalid.append("packet count")
    if len(packet_rows) != len(realization):
        invalid.append("one-packet-per-realization coverage")
    if not 1 <= len(query_rows) <= 512:
        invalid.append("query count")
    if not 1 <= len(targets) <= 8 or any(not 0.0 <= value <= 1.0 for value in target_coordinates):
        invalid.append("target count/domain")
    if not 3 <= len(sizes) <= 8 or any(not 1 <= value <= 1_000_000 for value in sizes):
        invalid.append("size count/domain")
    if any(not 3 <= count <= 8 for count in target_size_counts.values()):
        invalid.append("per-target observed size count")
    if any(not 5 <= len(values) <= 21 for values in controls_by_curve.values()):
        invalid.append("controls per target-size curve")
    if not realizations_per_group or any(
        not 2 <= value <= 128 for value in realizations_per_group
    ):
        invalid.append("realizations per observed group")
    if not eigen_counts or any(not 5 <= value <= 4_096 for value in eigen_counts):
        invalid.append("eigenvalues per packet")
    if any(not 5 <= keep <= count for keep, count in zip(keep_counts, eigen_counts)):
        invalid.append("keep-count bounds")
    if sum(eigen_counts) != energy_count or not 1 <= energy_count <= 5_000_000:
        invalid.append("flat eigenvalue count/coverage")
    if physical_bytes > MAX_CASE_INPUT_BYTES:
        invalid.append("256 MiB physical case bound")
    if any(not math.isfinite(value) or abs(value) > 1_000_000.0 for value in observed_controls):
        invalid.append("observed control magnitude")
    if any(not math.isfinite(value) or abs(value) > 1_000_000.0 for value in query_controls):
        invalid.append("query control magnitude")
    if any(not math.isfinite(value) or not 0.4 <= value <= 1_000_000.0 for value in raw_halfwidths):
        invalid.append("halfwidth magnitude")
    if any(not 1 <= value <= 1_000_000 for value in min_sizes):
        invalid.append("minimum-size domain")
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed <= MAX_BOOTSTRAP_SEED
        or seed + 1009 * max(0, len(targets) - 1) > UINT64_MAX
    ):
        invalid.append("bootstrap seed/derived uint64 seed")
    if not fit_group_counts or min(fit_group_counts) < 8:
        invalid.append("minimum groups per required fit")
    if not fit_size_counts or min(fit_size_counts) < 3:
        invalid.append("minimum sizes per required fit")
    if invalid:
        raise VerificationFailure(
            f"published numerical/cardinality guarantee failed: {_relative(case_dir)}",
            {"failed_guarantees": invalid},
        )

    reference_contract: dict[str, Any] | str
    reference_numeric_envelope: dict[str, Any] | str
    if oracle_output is None:
        reference_contract = "checked by the clean-room public-validation gate"
        reference_numeric_envelope = "checked by the clean-room reference gate"
    else:
        try:
            reference_contract = public_validator.parse_outputs(oracle_output, expected)
        except Exception as error:
            raise VerificationFailure(
                f"packaged reference violates the public numeric contract for "
                f"{manifest.get('case_id')}: {error}"
            ) from error
        reference_numeric_envelope = _independent_reference_numeric_envelope(
            oracle_output,
            independent_target_rows,
            grid,
            query_rows,
        )

    return {
        "case_id": manifest.get("case_id"),
        "physical_bytes": physical_bytes,
        "packet_rows": len(packet_rows),
        "flat_eigenvalues": energy_count,
        "maximum_eigenvalues_per_packet": max(eigen_counts),
        "query_rows": len(query_rows),
        "targets": len(targets),
        "distinct_sizes": len(sizes),
        "observed_curves": len(controls_by_curve),
        "controls_per_curve_range": [
            min(map(len, controls_by_curve.values())),
            max(map(len, controls_by_curve.values())),
        ],
        "realizations_per_group_range": [
            min(realizations_per_group),
            max(realizations_per_group),
        ],
        "required_fit_group_count_minimum": min(fit_group_counts),
        "required_fit_size_count_minimum": min(fit_size_counts),
        "maximum_absolute_observed_control": max(map(abs, observed_controls)),
        "maximum_absolute_query_control": max(map(abs, query_controls)),
        "maximum_halfwidth": max(raw_halfwidths),
        "bootstrap_seed": seed,
        "maximum_derived_target_seed": seed + 1009 * max(0, len(targets) - 1),
        "npz_physical_members": npz["physical_members"],
        "npz_uncompressed_bytes": npz["uncompressed_bytes"],
        "maximum_input_csv_field_bytes": max(input_field_byte_lengths),
        "maximum_input_integer_lexeme_digits": max(integer_lexeme_lengths),
        "resource_python": resource.get("python") if isinstance(resource, dict) else None,
        "interval_level": interval_level,
        "cross_platform_data_filenames": {
            role: manifest["files"][role]
            for role in ("packets", "eigenvalues", "queries", "analysis_grid")
        },
        "independent_packet_numeric_envelope": packet_numeric_envelope,
        "reference_numeric_contract": reference_contract,
        "independent_reference_numeric_envelope": reference_numeric_envelope,
    }


def _npy_bytes(array: np.ndarray[Any, Any]) -> bytes:
    stream = io.BytesIO()
    np.save(stream, array, allow_pickle=False)
    return stream.getvalue()


def _declared_npy_header(shape: tuple[int, ...], dtype: np.dtype[Any]) -> bytes:
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        stream,
        {
            "descr": np.lib.format.dtype_to_descr(dtype),
            "fortran_order": False,
            "shape": shape,
        },
    )
    return stream.getvalue()


def _npz_preflight_self_tests(public_validator: Any) -> dict[str, Any]:
    """Prove malformed archives are rejected before an eager NumPy load."""

    attacks = (
        "duplicate_physical_member",
        "header_declared_oversize",
        "nul_truncated_member_name",
        "negative_dimensions",
        "zero_itemsize_huge_shape",
        "oversized_zero_length_itemsize",
    )
    reports: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="spectral-npz-preflight-") as temporary:
        root = Path(temporary)
        for attack in attacks:
            case_dir = root / attack
            shutil.copytree(PARTICIPANT / "input", case_dir)
            manifest = _json(case_dir / "manifest.json")
            archive_path = case_dir / str(manifest["files"]["eigenvalues"])
            schema_member = _npy_bytes(
                np.asarray("spectral-scaling-eigenvalues/v1")
            )
            small_energies = _npy_bytes(np.asarray([0.0, 1.0], dtype=np.float64))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=UserWarning)
                with zipfile.ZipFile(
                    archive_path, mode="w", compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    archive.writestr("schema_version.npy", schema_member)
                    if attack == "duplicate_physical_member":
                        archive.writestr("energies.npy", small_energies)
                        archive.writestr("energies.npy", small_energies)
                    elif attack == "header_declared_oversize":
                        # A header-only member declares a 400 MB array.  Both
                        # preflights must reject its metadata without allocating it.
                        bomb_header = _declared_npy_header(
                            (50_000_001,), np.dtype(np.float64)
                        )
                        archive.writestr("energies.npy", bomb_header)
                    elif attack == "nul_truncated_member_name":
                        archive.writestr("energies.npyX", small_energies)
                    elif attack == "negative_dimensions":
                        archive.writestr(
                            "energies.npy",
                            _declared_npy_header((-1, -1), np.dtype(np.float64)),
                        )
                    elif attack == "zero_itemsize_huge_shape":
                        archive.writestr(
                            "energies.npy",
                            _declared_npy_header(
                                (100_000_000,), np.dtype("U0")
                            ),
                        )
                    else:
                        archive.writestr(
                            "energies.npy",
                            _declared_npy_header(
                                (0,), np.dtype(f"V{MAX_GENERIC_NPZ_ITEMSIZE + 1}")
                            ),
                        )
            if attack == "nul_truncated_member_name":
                marker = b"energies.npyX"
                contents = archive_path.read_bytes()
                if contents.count(marker) != 2:
                    raise VerificationFailure(
                        "could not construct NUL-name NPZ preflight probe"
                    )
                archive_path.write_bytes(contents.replace(marker, b"energies.npy\x00"))

            eager_calls = 0
            original_np_load = public_validator.np.load

            def forbidden_eager_load(*arguments: Any, **keywords: Any) -> Any:
                nonlocal eager_calls
                eager_calls += 1
                raise AssertionError("adversarial NPZ reached eager np.load")

            public_validator.np.load = forbidden_eager_load
            public_error = ""
            semantic_error = ""
            try:
                try:
                    public_validator.load_expected(case_dir)
                except Exception as error:
                    public_error = f"{type(error).__name__}: {error}"
                try:
                    _semantic_digest(archive_path)
                except Exception as error:
                    semantic_error = f"{type(error).__name__}: {error}"
            finally:
                public_validator.np.load = original_np_load
            if not public_error or not semantic_error or eager_calls:
                raise VerificationFailure(
                    f"NPZ preflight self-test failed: {attack}",
                    {
                        "public_validator_error": public_error,
                        "semantic_digest_error": semantic_error,
                        "eager_np_load_calls": eager_calls,
                    },
                )
            reports[attack] = {
                "public_validator_rejected": True,
                "semantic_digest_rejected": True,
                "eager_np_load_calls": eager_calls,
                "physical_archive_bytes": archive_path.stat().st_size,
                "public_error": public_error,
                "semantic_error": semantic_error,
            }
    return reports


def gate_sizes_and_imports() -> dict[str, Any]:
    all_files = _files(TASK_ROOT)
    participant_files = _files(PARTICIPANT)
    total_bytes = sum(path.stat().st_size for path in all_files.values())
    participant_bytes = sum(path.stat().st_size for path in participant_files.values())
    if total_bytes > 16 * 1024 * 1024:
        raise VerificationFailure(f"task package is too large: {total_bytes} bytes")
    if participant_bytes > 4 * 1024 * 1024:
        raise VerificationFailure(f"participant package is too large: {participant_bytes} bytes")

    analyzers = {
        "reference": AUTHOR / "reference_solver" / "analyze.py",
        "alternative": AUTHOR / "alternative_solver" / "analyze.py",
    }
    import_sets = {name: sorted(_analyzer_imports(path)) for name, path in analyzers.items()}
    reference_source = analyzers["reference"].read_text(encoding="utf-8")
    alternative_source = analyzers["alternative"].read_text(encoding="utf-8")
    if _sha256(reference_source.encode("utf-8")) == _sha256(
        alternative_source.encode("utf-8")
    ):
        raise VerificationFailure("reference and alternative analyzers are byte-identical")
    similarity = difflib.SequenceMatcher(
        None,
        reference_source.splitlines(),
        alternative_source.splitlines(),
        autojunk=False,
    ).ratio()
    if similarity >= 0.92:
        raise VerificationFailure(
            "alternative analyzer is not meaningfully independent",
            {"line_similarity": similarity},
        )

    public_validator = _load_public_validator()
    numeric_contract_constants = {
        "MAX_CASE_INPUT_BYTES": MAX_CASE_INPUT_BYTES,
        "MAX_MANIFEST_BYTES": 65_536,
        "MAX_NPZ_UNCOMPRESSED_BYTES": MAX_NPZ_UNCOMPRESSED_BYTES,
        "MAX_NPY_HEADER_BYTES": MAX_NPY_HEADER_BYTES,
        "MAX_STANDARDIZED_QUERY": 2.0,
        "MAX_CUBIC_CONDITION": 1e12,
        "MAX_CUBIC_COEFFICIENT": 1e6,
        "MAX_SCALING_COORDINATE": 2.1e36,
        "MAX_RAW_CUBIC_PREDICTION": 2e7,
        "AFFINE_ULP_MULTIPLIER": 1_048_576,
        "AFFINE_CUTOFF_RELATIVE_MARGIN": 1e-8,
        "AFFINE_GAP_RELATIVE_MARGIN": 1e-9,
        "UINT64_MAX": UINT64_MAX,
        "MAX_BOOTSTRAP_SEED": MAX_BOOTSTRAP_SEED,
        "MAX_CSV_FIELD_BYTES": MAX_CSV_FIELD_BYTES,
        "MAX_INTEGER_TEXT_DIGITS": MAX_INTEGER_TEXT_DIGITS,
        "CSV_PARSER_FIELD_LIMIT": CSV_PARSER_FIELD_LIMIT,
    }
    drifted_constants = {
        name: {
            "expected": expected,
            "observed": getattr(public_validator, name, None),
        }
        for name, expected in numeric_contract_constants.items()
        if getattr(public_validator, name, None) != expected
    }
    if drifted_constants:
        raise VerificationFailure(
            "public validator numerical constants drifted from the published contract",
            drifted_constants,
        )
    try:
        public_validator.inspect_source(analyzers["reference"])
        public_validator.inspect_source(analyzers["alternative"])
    except Exception as error:
        raise VerificationFailure(f"trusted analyzer violates the public source contract: {error}") from error

    suite = _json(PRIVATE / "reference" / "suite.json")
    case_entries: list[tuple[Path, Path | None]] = [(PARTICIPANT / "input", None)]
    for record in suite.get("cases", []):
        case_entries.append(
            (
                (PRIVATE / "reference" / str(record["input"])).resolve(),
                (PRIVATE / "reference" / str(record["oracle_output"])).resolve(),
            )
        )
    case_sizes: dict[str, int] = {}
    case_resources: dict[str, Any] = {}
    for case_dir, oracle_output in case_entries:
        audit = _audit_case_numeric_contract(
            case_dir, public_validator, oracle_output=oracle_output
        )
        manifest = _json(case_dir / "manifest.json")
        contract = manifest.get("resource_contract", {})
        if (
            not isinstance(contract, dict)
            or set(contract)
            != {"python", "numpy", "network", "wall_time_seconds", "output_bytes"}
            or contract.get("python") != "3.11+"
            or contract.get("numpy") != "2.3.5"
            or contract.get("network") != "disabled"
        ):
            raise VerificationFailure(f"resource contract drift: {_relative(case_dir)}")
        size = sum(path.stat().st_size for path in _files(case_dir).values())
        if size > MAX_CASE_INPUT_BYTES:
            raise VerificationFailure(f"case package exceeds 256 MiB: {_relative(case_dir)}")
        case_id = str(manifest.get("case_id", case_dir.name))
        case_sizes[case_id] = size
        grid = _json(case_dir / str(manifest["files"]["analysis_grid"]))
        seed = manifest.get("bootstrap_seed")
        replicates = grid.get("bootstrap_replicates")
        min_sizes = grid.get("min_sizes")
        halfwidths = grid.get("halfwidths")
        if (
            isinstance(seed, bool)
            or not isinstance(seed, int)
            or seed < 0
            or seed > MAX_BOOTSTRAP_SEED
            or isinstance(replicates, bool)
            or not isinstance(replicates, int)
            or not 8 <= replicates <= 64
            or not isinstance(min_sizes, list)
            or not isinstance(halfwidths, list)
            or not 1 <= len(min_sizes) <= 8
            or not 1 <= len(halfwidths) <= 8
            or not 2 <= len(min_sizes) * len(halfwidths) <= 24
            or any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1_000_000 for value in min_sizes)
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.4 <= float(value) <= 1_000_000.0 for value in halfwidths)
        ):
            raise VerificationFailure(f"unbounded/invalid analysis work: {_relative(case_dir)}")
        packet_path = case_dir / str(manifest["files"]["packets"])
        query_path = case_dir / str(manifest["files"]["queries"])
        with packet_path.open("r", encoding="utf-8", newline="") as handle:
            packet_rows = list(csv.DictReader(handle))
        with query_path.open("r", encoding="utf-8", newline="") as handle:
            query_rows = list(csv.DictReader(handle))
        groups = {
            (row["target"], row["size"], row["control"])
            for row in packet_rows
        }
        targets = {row["target"] for row in packet_rows}
        packet_sizes = [int(row["size"]) for row in packet_rows]
        query_sizes = [float(row["size"]) for row in query_rows]
        packet_controls = [float(row["control"]) for row in packet_rows]
        query_controls = [float(row["control"]) for row in query_rows]
        if (
            not 1 <= len(packet_rows) <= 6000
            or not 1 <= len(query_rows) <= 512
            or not 1 <= len(targets) <= 8
            or any(not 1 <= value <= 1_000_000 for value in packet_sizes)
            or any(not 1.0 <= value <= 1_000_000.0 for value in query_sizes)
            or any(not math.isfinite(value) or abs(value) > 1_000_000.0 for value in packet_controls)
            or any(not math.isfinite(value) or abs(value) > 1_000_000.0 for value in query_controls)
        ):
            raise VerificationFailure(f"case cardinality exceeds release bounds: {_relative(case_dir)}")
        output_bytes = contract.get("output_bytes")
        wall_time = contract.get("wall_time_seconds")
        expected_rows = (
            len(packet_rows)
            + len(groups)
            + len(targets)
            + len(targets) * len(min_sizes) * len(halfwidths)
            + len(query_rows)
        )
        conservative_capacity = 512 * expected_rows + 8192
        if (
            isinstance(output_bytes, bool)
            or not isinstance(output_bytes, int)
            or not conservative_capacity <= output_bytes <= 4_000_000
            or isinstance(wall_time, bool)
            or not isinstance(wall_time, int)
            or wall_time != 180
        ):
            raise VerificationFailure(
                f"resource contract cannot accommodate required output/work: {_relative(case_dir)}",
                {
                    "expected_rows": expected_rows,
                    "conservative_output_capacity": conservative_capacity,
                    "declared_output_bytes": output_bytes,
                    "wall_time_seconds": wall_time,
                },
            )
        case_resources[case_id] = {
            **audit,
            "stability_cells_per_target": len(min_sizes) * len(halfwidths),
            "bootstrap_replicates": replicates,
            "declared_output_bytes": output_bytes,
            "conservative_required_output_bytes": conservative_capacity,
            "wall_time_seconds": wall_time,
        }
    preflight_self_tests = _npz_preflight_self_tests(public_validator)
    if np.__version__ != "2.3.5":
        raise VerificationFailure(
            f"verification requires NumPy 2.3.5, found {np.__version__}"
        )
    if sys.version_info < (3, 11):
        raise VerificationFailure(
            f"verification requires Python 3.11+, found {platform.python_version()}"
        )
    return {
        "task_bytes": total_bytes,
        "participant_bytes": participant_bytes,
        "case_bytes": case_sizes,
        "case_resource_bounds": case_resources,
        "analyzer_source_bytes": {
            name: path.stat().st_size for name, path in analyzers.items()
        },
        "analyzer_imports": import_sets,
        "alternative_line_similarity": similarity,
        "public_validator_contract_audit": "passed for every packaged case",
        "public_numeric_contract_constants": numeric_contract_constants,
        "npz_preflight_self_tests": preflight_self_tests,
        "bootstrap_seed_maximum": MAX_BOOTSTRAP_SEED,
        "uint64_maximum": UINT64_MAX,
        "python_resource_contract": "3.11+",
        "python_runtime": platform.python_version(),
        "numpy_version": np.__version__,
    }


def gate_generator(work: Path, timeout: float) -> dict[str, Any]:
    generator = AUTHOR / "oracle" / "generate.py"
    roots = [work / "generation_a", work / "generation_b"]
    for index, root in enumerate(roots, start=1):
        _run(
            [
                sys.executable,
                "-B",
                str(generator),
                "--output-root",
                str(root),
            ],
            cwd=TASK_ROOT,
            timeout=timeout,
            label=f"oracle generation {index}",
        )
    repeated = _compare_trees(roots[0], roots[1], "two oracle generations")

    public_match = _compare_trees(
        roots[0] / "participant" / "input",
        PARTICIPANT / "input",
        "generated retired case and packaged retired case",
    )
    hidden_match = _compare_trees(
        roots[0] / "private" / "hidden_inputs",
        PRIVATE / "hidden_inputs",
        "generated hidden inputs and packaged hidden inputs",
    )
    generated_realism = roots[0] / "private" / "realism"
    realism_match = None
    if generated_realism.is_dir():
        realism_match = _compare_trees(
            generated_realism,
            PRIVATE / "realism",
            "generated exact-diagonalization realism fixture and packaged fixture",
        )

    generated_reference = roots[0] / "private" / "reference"
    generated_files = _files(generated_reference)
    missing: list[str] = []
    mismatched: list[str] = []
    for relative, generated in generated_files.items():
        packaged = PRIVATE / "reference" / relative
        if not packaged.is_file():
            missing.append(relative)
        elif _semantic_digest(generated) != _semantic_digest(packaged):
            mismatched.append(relative)
    owned_roots = {Path(name).parts[0] for name in generated_files}
    extra = [
        name
        for name in _files(PRIVATE / "reference")
        if Path(name).parts[0] in owned_roots and name not in generated_files
    ]
    if missing or mismatched or extra:
        raise VerificationFailure(
            "generated private references differ from the packaged oracle",
            {
                "missing": missing[:20],
                "mismatched": mismatched[:20],
                "extra": extra[:20],
            },
        )
    return {
        "repeated_generation": repeated,
        "retired_case_match": public_match,
        "hidden_inputs_match": hidden_match,
        "realism_fixture_match": realism_match,
        "reference_file_count": len(generated_files),
        "packaged_reference_match": True,
    }


def _validate_truth_numeric_conditioning(summary: dict[str, Any], case_id: str) -> dict[str, Any]:
    conditioning = summary.get("numeric_conditioning")
    if not isinstance(conditioning, dict):
        raise VerificationFailure(f"hidden truth conditioning is missing: {case_id}")
    required = {
        "affine_energy_scale",
        "affine_energy_offset",
        "minimum_keep_boundary_margin",
        "minimum_keep_boundary_margin_over_span",
        "minimum_keep_boundary_margin_ulps",
        "minimum_selected_gap",
        "minimum_selected_gap_over_span",
        "minimum_selected_gap_ulps",
        "selected_index_prefix_exactly_preserved",
        "minimum_absolute_shift_offset",
        "maximum_absolute_shift_offset",
        "maximum_shift_offset_over_span",
        "maximum_ratio_perturbation",
        "maximum_absolute_energy_coordinate",
    }
    missing = sorted(required - set(conditioning))
    if missing:
        raise VerificationFailure(
            f"hidden truth conditioning coverage is incomplete: {case_id}",
            {"missing": missing},
        )
    numeric_names = required - {"selected_index_prefix_exactly_preserved"}
    values = {name: _finite_metric(conditioning, name) for name in numeric_names}
    if values["affine_energy_scale"] != 1.625 or values["affine_energy_offset"] != -4.75:
        raise VerificationFailure(f"hidden truth affine transform drifted: {case_id}")
    if (
        values["minimum_keep_boundary_margin"] <= 0.0
        or values["minimum_keep_boundary_margin_over_span"] < 1e-8
        or values["minimum_keep_boundary_margin_ulps"] < 1_048_576.0
        or values["minimum_selected_gap"] <= 0.0
        or values["minimum_selected_gap_over_span"] < 1e-9
        or values["minimum_selected_gap_ulps"] < 1_048_576.0
        or conditioning.get("selected_index_prefix_exactly_preserved") is not True
        or values["minimum_absolute_shift_offset"] <= 0.0
        or not values["minimum_absolute_shift_offset"]
        <= values["maximum_absolute_shift_offset"]
        or not 0.0 <= values["maximum_shift_offset_over_span"] <= 0.005
        or not 0.0 <= values["maximum_ratio_perturbation"] <= 1e-10
        or not 0.0 <= values["maximum_absolute_energy_coordinate"] <= 1e100
    ):
        raise VerificationFailure(
            f"hidden truth numeric conditioning invariant failed: {case_id}",
            conditioning,
        )
    return {
        **values,
        "selected_index_prefix_exactly_preserved": True,
    }


def gate_oracle_invariants() -> dict[str, Any]:
    suite = _json(PRIVATE / "reference" / "suite.json")
    required = {
        "bounded_gap_ratio",
        "weak_control_mean_exceeds_strong_control_mean",
        "common_size_crossing",
        "affine_energy_invariance",
        "realization_cluster_is_sampling_unit",
    }
    summaries: dict[str, Any] = {}
    for case in suite["cases"]:
        case_id = case["case_id"]
        summary = _json(PRIVATE / "reference" / case_id / "truth_summary.json")
        invariants = summary.get("invariants", {})
        if not required <= set(invariants) or not all(invariants[name] is True for name in required):
            raise VerificationFailure(f"oracle invariant failure: {case_id}")
        span = float(summary.get("critical_curve_span", math.nan))
        contrast = float(summary.get("weak_minus_strong_minimum", math.nan))
        if not math.isfinite(span) or span <= 0.0 or not math.isfinite(contrast) or contrast <= 0.0:
            raise VerificationFailure(f"unresolved synthetic crossover: {case_id}")
        conditioning = _validate_truth_numeric_conditioning(summary, case_id)
        input_dir = (PRIVATE / "reference" / str(case["input"])).resolve()
        input_manifest = _json(input_dir / "manifest.json")
        with (
            input_dir / str(input_manifest["files"]["packets"])
        ).open("r", encoding="utf-8", newline="") as handle:
            packet_rows = list(csv.DictReader(handle))
        independently_recomputed, _ = _independent_packet_numeric_envelope(
            input_dir, input_manifest, packet_rows
        )
        conditioning_fields = {
            "minimum_keep_boundary_margin": "minimum_keep_boundary_margin",
            "minimum_keep_boundary_margin_over_span": (
                "minimum_keep_boundary_margin_over_span"
            ),
            "minimum_keep_boundary_margin_ulps": "minimum_keep_boundary_margin_ulps",
            "minimum_selected_gap": "minimum_selected_gap",
            "minimum_selected_gap_over_span": "minimum_selected_gap_over_span",
            "minimum_selected_gap_ulps": "minimum_selected_gap_ulps",
            "minimum_absolute_shift_offset": "minimum_absolute_shift_offset",
            "maximum_absolute_shift_offset": "maximum_absolute_shift_offset",
            "maximum_shift_offset_over_span": "maximum_shift_span_fraction",
            "maximum_ratio_perturbation": "maximum_ratio_perturbation",
            "maximum_absolute_energy_coordinate": "maximum_absolute_energy_coordinate",
        }
        mismatched_conditioning = {
            truth_name: {
                "truth": conditioning[truth_name],
                "independent": independently_recomputed[envelope_name],
            }
            for truth_name, envelope_name in conditioning_fields.items()
            if independently_recomputed[envelope_name] is None
            or not math.isclose(
                conditioning[truth_name],
                float(independently_recomputed[envelope_name]),
                rel_tol=5e-13,
                abs_tol=5e-15,
            )
        }
        if (
            mismatched_conditioning
            or independently_recomputed["exact_selected_prefix_preserved"] is not True
        ):
            raise VerificationFailure(
                f"hidden truth conditioning disagrees with independent recomputation: {case_id}",
                {"mismatched": mismatched_conditioning},
            )
        physical_bytes = sum(path.stat().st_size for path in _files(input_dir).values())
        declared_physical_bytes = summary.get("physical_case_input_bytes")
        if (
            isinstance(declared_physical_bytes, bool)
            or not isinstance(declared_physical_bytes, int)
            or declared_physical_bytes != physical_bytes
            or physical_bytes > MAX_CASE_INPUT_BYTES
        ):
            raise VerificationFailure(
                f"hidden truth physical-byte metric failed: {case_id}",
                {
                    "declared": declared_physical_bytes,
                    "observed": physical_bytes,
                    "limit": MAX_CASE_INPUT_BYTES,
                },
            )
        summaries[case_id] = {
            "critical_curve_span": span,
            "weak_minus_strong_minimum": contrast,
            "physical_case_input_bytes": physical_bytes,
            "numeric_conditioning": conditioning,
            "independent_conditioning_match": True,
            "independent_packet_numeric_envelope": independently_recomputed,
            "invariants": sorted(required),
        }
    realism: dict[str, Any] = {}
    for record in suite.get("realism_cases", []):
        fixture = (TASK_ROOT / str(record["path"])).resolve()
        summary = _json(fixture / "truth_summary.json")
        invariants = summary.get("invariants", {})
        if not invariants or not all(value is True for value in invariants.values()):
            raise VerificationFailure("exact-diagonalization realism invariant failed")
        contrast = float(summary.get("aggregate", {}).get("weak_minus_strong", math.nan))
        if not math.isfinite(contrast) or contrast <= 0.0:
            raise VerificationFailure("exact-diagonalization realism contrast is unresolved")
        realism[str(record["case_id"])] = {
            "derivation_type": summary.get("derivation_type"),
            "packet_count": summary.get("packet_count"),
            "weak_minus_strong": contrast,
            "invariant_count": len(invariants),
        }
    return {
        "case_count": len(summaries),
        "cases": summaries,
        "realism_case_count": len(realism),
        "realism_cases": realism,
    }


def gate_ed_realism(work: Path, timeout: float) -> dict[str, Any]:
    """Regenerate the small exact-diagonalization anchor independently twice."""

    generator = AUTHOR / "oracle" / "ed_realism.py"
    roots = [work / "ed_realism_a", work / "ed_realism_b"]
    for index, root in enumerate(roots, start=1):
        _run(
            [
                sys.executable,
                "-B",
                str(generator),
                "--output-root",
                str(root),
            ],
            cwd=TASK_ROOT,
            timeout=timeout,
            label=f"exact-diagonalization realism generation {index}",
        )
    relative = Path("private") / "realism" / "heisenberg_ed_fixed_sector"
    fixtures = [root / relative for root in roots]
    expected_files = {
        "eigenvalues.npz",
        "manifest.json",
        "packets.csv",
        "truth_summary.json",
    }
    if set(_files(fixtures[0])) != expected_files:
        raise VerificationFailure(
            "exact-diagonalization realism fixture inventory mismatch",
            {"actual": sorted(_files(fixtures[0])), "expected": sorted(expected_files)},
        )
    repeated = _compare_trees_bytes(
        fixtures[0], fixtures[1], "two exact-diagonalization realism generations"
    )
    packaged = _compare_trees_bytes(
        fixtures[0], TASK_ROOT / relative, "generated and packaged realism fixtures"
    )

    summary = _json(fixtures[0] / "truth_summary.json")
    dimensions = summary.get("sector_dimensions", {})
    if not isinstance(dimensions, dict) or not dimensions:
        raise VerificationFailure("realism fixture has no sector dimensions")
    for raw_size, raw_dimension in dimensions.items():
        size = int(raw_size)
        dimension = int(raw_dimension)
        if size <= 0 or size % 2 or dimension != math.comb(size, size // 2):
            raise VerificationFailure(
                "realism fixed-sector dimension is inconsistent",
                {"size": size, "dimension": dimension},
            )
    invariants = summary.get("invariants", {})
    if not isinstance(invariants, dict) or not invariants or not all(
        value is True for value in invariants.values()
    ):
        raise VerificationFailure("not all exact-diagonalization invariants hold")
    aggregate = summary.get("aggregate", {})
    weak = float(aggregate.get("weak_mean_r", math.nan))
    strong = float(aggregate.get("strong_mean_r", math.nan))
    contrast = float(aggregate.get("weak_minus_strong", math.nan))
    minimum = float(aggregate.get("minimum_group_weak_minus_strong", math.nan))
    ratio_min = float(aggregate.get("observed_ratio_minimum", math.nan))
    ratio_max = float(aggregate.get("observed_ratio_maximum", math.nan))
    groups = summary.get("group_summaries", [])
    group_margins = [float(group["weak_minus_strong"]) for group in groups]
    numeric = [weak, strong, contrast, minimum, ratio_min, ratio_max, *group_margins]
    if not numeric or not all(math.isfinite(value) for value in numeric):
        raise VerificationFailure("realism margins contain non-finite values")
    if not (
        0.0 <= ratio_min <= ratio_max <= 1.0
        and weak > strong
        and contrast > 0.0
        and minimum > 0.0
        and group_margins
        and min(group_margins) > 0.0
        and abs(contrast - (weak - strong)) <= 1e-12
        and abs(minimum - min(group_margins)) <= 1e-12
    ):
        raise VerificationFailure("exact-diagonalization realism margins are inconsistent")
    return {
        "byte_identical_repetitions": 2,
        "generated": repeated,
        "packaged_match": packaged,
        "sector_dimensions": {str(key): int(value) for key, value in dimensions.items()},
        "packet_count": int(summary["packet_count"]),
        "unique_spectrum_count": int(summary["unique_spectrum_count"]),
        "raw_eigenvalue_count": int(summary["raw_eigenvalue_count"]),
        "weak_mean_r": weak,
        "strong_mean_r": strong,
        "weak_minus_strong": contrast,
        "minimum_group_weak_minus_strong": minimum,
        "observed_ratio_range": [ratio_min, ratio_max],
        "invariants": invariants,
    }


def gate_clean_room(
    work: Path,
    timeout: float,
    state: dict[str, Any],
) -> dict[str, Any]:
    solvers = {
        "reference": AUTHOR / "reference_solver",
        "alternative": AUTHOR / "alternative_solver",
    }
    reports: dict[str, Any] = {}
    submissions: dict[str, Path] = {}
    for name, solver_dir in solvers.items():
        room = work / "clean_rooms" / name
        staged_participant = room / "participant"
        staged_solver = room / "solver"
        destination = room / "submission"
        shutil.copytree(PARTICIPANT, staged_participant)
        staged_solver.mkdir(parents=True)
        shutil.copyfile(solver_dir / "solve.py", staged_solver / "solve.py")
        shutil.copyfile(solver_dir / "analyze.py", staged_solver / "analyze.py")
        staged_participant_before = {
            relative: _semantic_digest(path)
            for relative, path in _files(staged_participant).items()
        }
        _run(
            [
                sys.executable,
                "-I",
                "-B",
                str(staged_solver / "solve.py"),
                "--participant",
                str(staged_participant),
                "--output",
                str(destination),
            ],
            cwd=room,
            timeout=timeout,
            label=f"{name} clean-room solver",
        )
        inventory = sorted(_files(destination))
        if inventory != ["output/analyze.py"]:
            raise VerificationFailure(
                f"{name} solver produced the wrong submission inventory",
                {"inventory": inventory},
            )
        expected = staged_solver / "analyze.py"
        actual = destination / "output" / "analyze.py"
        if _semantic_digest(expected) != _semantic_digest(actual):
            raise VerificationFailure(f"{name} clean-room solver copied stale source")
        validation = _run_json(
            [
                sys.executable,
                "-I",
                "-B",
                str(staged_participant / "software" / "validate_submission.py"),
                "--submission",
                str(destination),
                "--run-public",
            ],
            cwd=room,
            timeout=timeout,
            label=f"{name} public validator",
        )
        if not str(validation.get("submission", "")).startswith("valid") or not isinstance(
            validation.get("public_run"), dict
        ):
            raise VerificationFailure(f"{name} public validation was incomplete")
        deterministic_outputs: list[Path] = []
        for repetition, hash_seed in enumerate(("173", "941"), start=1):
            output = room / f"deterministic_output_{repetition}"
            run_cwd = room / f"run_cwd_{repetition}"
            run_cwd.mkdir()
            environment = dict(os.environ)
            for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT"):
                environment.pop(key, None)
            environment.update(
                {
                    "PYTHONHASHSEED": hash_seed,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONNOUSERSITE": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                    "NUMEXPR_NUM_THREADS": "1",
                }
            )
            _run(
                [
                    sys.executable,
                    "-B",
                    str(actual),
                    "--input",
                    str(staged_participant / "input"),
                    "--output",
                    str(output),
                ],
                cwd=run_cwd,
                timeout=timeout,
                label=f"{name} deterministic public run {repetition}",
                environment=environment,
            )
            deterministic_outputs.append(output)
        deterministic = _compare_trees_bytes(
            deterministic_outputs[0],
            deterministic_outputs[1],
            f"two {name} public analyzer runs",
        )
        independent_public_reference_numeric_envelope: dict[str, Any] | None = None
        if name == "reference":
            public_case = staged_participant / "input"
            public_manifest = _json(public_case / "manifest.json")
            with (
                public_case / str(public_manifest["files"]["packets"])
            ).open("r", encoding="utf-8", newline="") as handle:
                public_packet_rows = list(csv.DictReader(handle))
            with (
                public_case / str(public_manifest["files"]["queries"])
            ).open("r", encoding="utf-8", newline="") as handle:
                public_query_rows = list(csv.DictReader(handle))
            _, public_grouped_rows = _independent_packet_numeric_envelope(
                public_case, public_manifest, public_packet_rows
            )
            public_grid = _json(
                public_case / str(public_manifest["files"]["analysis_grid"])
            )
            independent_public_reference_numeric_envelope = (
                _independent_reference_numeric_envelope(
                    deterministic_outputs[0],
                    public_grouped_rows,
                    public_grid,
                    public_query_rows,
                )
            )
        staged_participant_after = {
            relative: _semantic_digest(path)
            for relative, path in _files(staged_participant).items()
        }
        if staged_participant_before != staged_participant_after:
            raise VerificationFailure(f"{name} solver mutated its clean-room public package")
        submissions[name] = destination
        reports[name] = {
            "submission_inventory": inventory,
            "source_sha256": _semantic_digest(actual),
            "public_run": validation["public_run"],
            "clean_room_participant_unchanged": True,
            "deterministic_public_repetitions": 2,
            "deterministic_public_output": deterministic,
            "independent_public_reference_numeric_envelope": (
                independent_public_reference_numeric_envelope
            ),
        }
    state["submissions"] = submissions
    return reports


def gate_repeated_grading(
    timeout: float,
    state: dict[str, Any],
) -> dict[str, Any]:
    submissions: dict[str, Path] | None = state.get("submissions")
    if not submissions:
        raise VerificationFailure("clean-room submissions were not available")
    grader = PRIVATE / "grader" / "grade.py"
    reports: dict[str, Any] = {}
    grades: dict[str, dict[str, Any]] = {}
    for name, submission in submissions.items():
        repeated: list[dict[str, Any]] = []
        for index, hash_seed in enumerate(("257", "811"), start=1):
            grade_cwd = submission.parent / f"grade_cwd_{index}"
            grade_cwd.mkdir(exist_ok=True)
            environment = dict(os.environ)
            for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT"):
                environment.pop(key, None)
            environment.update(
                {
                    "PYTHONHASHSEED": hash_seed,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONNOUSERSITE": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                    "NUMEXPR_NUM_THREADS": "1",
                }
            )
            repeated.append(
                _run_json(
                    [
                        sys.executable,
                        "-B",
                        str(grader),
                        "--submission",
                        str(submission),
                    ],
                    cwd=grade_cwd,
                    timeout=timeout,
                    label=f"{name} private grade {index}",
                    environment=environment,
                )
            )
        normalized = [_without_runtime(result) for result in repeated]
        if normalized[0] != normalized[1]:
            raise VerificationFailure(
                f"{name} private grade is not deterministic",
                {"first": normalized[0], "second": normalized[1]},
            )
        result = normalized[0]
        if result.get("passed") is not True or result.get("hard_gate_failures"):
            raise VerificationFailure(f"{name} solver did not pass the private evaluator", result)
        score = float(result.get("score", math.nan))
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise VerificationFailure(f"{name} evaluator score is invalid")
        grades[name] = result
        reports[name] = {
            "score": score,
            "components": result.get("components", {}),
            "case_count": len(result.get("cases", [])),
            "deterministic_repetitions": 2,
            "different_working_directories": True,
            "different_hash_seeds": True,
            "passed": True,
        }
    state["grades"] = grades
    return reports


def _grade_one_mutant(
    grader: Path,
    submission: Path,
    timeout: float,
    mutant_id: str,
) -> tuple[str, dict[str, Any]]:
    result = _run_json(
        [
            sys.executable,
            "-B",
            str(grader),
            "--submission",
            str(submission),
        ],
        cwd=TASK_ROOT,
        timeout=timeout,
        label=f"mutant {mutant_id}",
    )
    return mutant_id, _without_runtime(result)


def gate_mutants(
    work: Path, timeout: float, jobs: int, state: dict[str, Any]
) -> dict[str, Any]:
    manifest = _json(PRIVATE / "mutants" / "manifest.json")
    generated_manifest = _json(PRIVATE / "mutants" / "cases" / "mutant_manifest.json")
    records = manifest.get("mutants", [])
    if not isinstance(records, list) or len(records) < 10:
        raise VerificationFailure("fewer than ten scientific mutants are defined")
    categories = {str(record.get("category", "")) for record in records}
    if len(categories) < 5:
        raise VerificationFailure("scientific mutants span fewer than five categories")
    if any(record.get("schema_valid") is not True for record in records):
        raise VerificationFailure("scientific mutant manifest contains a schema-invalid probe")

    source_path = AUTHOR / "reference_solver" / "analyze.py"
    source = source_path.read_text(encoding="utf-8")
    if source.count(MUTATION_MARKER) != 1:
        raise VerificationFailure("reference analyzer mutation marker is missing or ambiguous")
    source_sha = _sha256(source.encode("utf-8"))
    if generated_manifest.get("source_sha256") != source_sha:
        raise VerificationFailure("generated mutant manifest points at stale reference source")
    regenerated = work / "regenerated_mutants"
    _run(
        [
            sys.executable,
            "-I",
            "-B",
            str(PRIVATE / "mutants" / "build_mutants.py"),
            "--source",
            str(source_path),
            "--cases-root",
            str(regenerated),
        ],
        cwd=TASK_ROOT,
        timeout=timeout,
        label="scientific mutant regeneration",
    )
    regeneration = _compare_trees_bytes(
        regenerated,
        PRIVATE / "mutants" / "cases",
        "regenerated and packaged scientific mutants",
    )

    grader = PRIVATE / "grader" / "grade.py"
    raw_results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {
            pool.submit(
                _grade_one_mutant,
                grader,
                PRIVATE / "mutants" / Path(str(record["path"])).parents[1],
                timeout,
                str(record["mutant_id"]),
            ): record
            for record in records
        }
        for future in as_completed(futures):
            record = futures[future]
            mutant_id, result = future.result()
            raw_results[mutant_id] = result

    result_rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for record in records:
        mutant_id = str(record["mutant_id"])
        result = raw_results[mutant_id]
        expected_component = str(record["expected_component"])
        hard = result.get("hard_gate_failures", [])
        mandatory = result.get("mandatory_failures", [])
        if result.get("passed") is not False:
            failures.append(f"{mutant_id}: unexpectedly passed")
        if hard:
            failures.append(f"{mutant_id}: failed a schema/security gate instead of scientifically")
        if expected_component not in mandatory:
            failures.append(f"{mutant_id}: expected component was not independently caught")
        score = float(result.get("score", math.nan))
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            failures.append(f"{mutant_id}: invalid score")
        result_rows.append(
            {
                "mutant_id": mutant_id,
                "category": record["category"],
                "expected_component": expected_component,
                "score": score,
                "passed": result.get("passed"),
                "hard_gate_failures": hard,
                "mandatory_failures": mandatory,
            }
        )
    details = {
        "mutant_count": len(result_rows),
        "category_count": len(categories),
        "all_schema_valid": all(not row["hard_gate_failures"] for row in result_rows),
        "all_rejected": all(row["passed"] is False for row in result_rows),
        "regeneration": regeneration,
        "results": result_rows,
    }
    state["mutants"] = details
    if failures:
        raise VerificationFailure("mutant sensitivity gate failed", {**details, "issues": failures})
    return details


def gate_probes(timeout: float) -> dict[str, Any]:
    manifest = _json(PRIVATE / "probes" / "manifest.json")
    records = manifest.get("probes", [])
    categories = {str(record.get("category", "")) for record in records}
    required = {"malformed", "nonfinite", "partial", "oversize", "security"}
    if not required <= categories:
        raise VerificationFailure(
            "robustness probe categories are incomplete",
            {"required": sorted(required), "actual": sorted(categories)},
        )
    report = _run_json(
        [
            sys.executable,
            "-I",
            "-B",
            str(PRIVATE / "probes" / "run_probes.py"),
            "--timeout",
            str(min(timeout, 240.0)),
        ],
        cwd=TASK_ROOT,
        timeout=max(timeout, 900.0),
        label="robustness probe suite",
    )
    if report.get("all_rejected_safely") is not True:
        raise VerificationFailure("one or more robustness probes were not rejected safely", report)
    if int(report.get("probe_count", -1)) != len(records):
        raise VerificationFailure("probe result count differs from its manifest")
    return {
        "probe_count": len(records),
        "categories": sorted(categories),
        "all_rejected_safely": True,
        "results": report.get("results", []),
    }


def gate_hardlink_rejection(work: Path, timeout: float) -> dict[str, Any]:
    """Exercise real analyzer and produced-artifact hard-link gates."""

    root = work / "hardlink_checks"
    root.mkdir(parents=True)
    analyzer_anchor = root / "analyzer_anchor.py"
    shutil.copyfile(AUTHOR / "reference_solver" / "analyze.py", analyzer_anchor)
    submission = root / "submission"
    analyzer = submission / "output" / "analyze.py"
    analyzer.parent.mkdir(parents=True)
    try:
        os.link(analyzer_anchor, analyzer)
    except (OSError, NotImplementedError) as error:
        return {
            "filesystem_supports_hardlinks": False,
            "skipped_reason": f"{type(error).__name__}: {error}",
        }
    if analyzer.stat().st_nlink < 2:
        raise VerificationFailure("filesystem reported a successful link without link multiplicity")
    result = _run_json(
        [
            sys.executable,
            "-B",
            str(PRIVATE / "grader" / "grade.py"),
            "--submission",
            str(submission),
        ],
        cwd=TASK_ROOT,
        timeout=timeout,
        label="hard-linked analyzer rejection",
    )
    analyzer_failures = "\n".join(str(item) for item in result.get("hard_gate_failures", []))
    if result.get("passed") is not False or "hard-linked" not in analyzer_failures:
        raise VerificationFailure("private evaluator accepted a hard-linked analyzer", result)

    core_path = PRIVATE / "grader" / "core.py"
    specification = importlib.util.spec_from_file_location(
        "_spectral_scaling_private_core_hardlink_check", core_path
    )
    if specification is None or specification.loader is None:
        raise VerificationFailure("could not load the private output inspector")
    core = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(core)
    output = root / "produced_output"
    output.mkdir()
    for name in core.OUTPUT_HEADERS:
        (output / name).write_text("placeholder\n", encoding="utf-8")
    artifact_anchor = root / "claims_anchor.json"
    artifact_anchor.write_text("{}\n", encoding="utf-8")
    os.link(artifact_anchor, output / "claims.json")
    artifact_failure = ""
    try:
        core.inspect_output(output, 4_000_000)
    except Exception as error:  # The concrete private GateFailure is loaded dynamically.
        artifact_failure = f"{type(error).__name__}: {error}"
    if "hard-linked" not in artifact_failure:
        raise VerificationFailure(
            "private evaluator output inspector accepted a hard-linked artifact",
            {"failure": artifact_failure},
        )
    return {
        "filesystem_supports_hardlinks": True,
        "analyzer_hardlink_rejected": True,
        "analyzer_failure": analyzer_failures,
        "produced_output_hardlink_rejected": True,
        "produced_output_failure": artifact_failure,
    }


def gate_hardcoded_public_shortcut(state: dict[str, Any]) -> dict[str, Any]:
    mutants = state.get("mutants")
    if not isinstance(mutants, dict):
        raise VerificationFailure("mutant results were unavailable")
    matches = [
        row for row in mutants.get("results", []) if row.get("mutant_id") == "hardcoded_public"
    ]
    if len(matches) != 1:
        raise VerificationFailure("hardcoded retired-case mutant is absent or duplicated")
    result = matches[0]
    if result.get("passed") is not False or result.get("hard_gate_failures"):
        raise VerificationFailure("hardcoded retired-case shortcut was not rejected scientifically", result)
    return {
        "mutant_id": "hardcoded_public",
        "category": result.get("category"),
        "passed": False,
        "score": result.get("score"),
        "scientific_failure": True,
        "mandatory_failures": result.get("mandatory_failures"),
    }


def _finite_metric(mapping: dict[str, Any], name: str) -> float:
    try:
        value = float(mapping[name])
    except (KeyError, TypeError, ValueError) as error:
        raise VerificationFailure(f"missing/non-numeric required metric {name}") from error
    if not math.isfinite(value):
        raise VerificationFailure(f"non-finite required metric {name}")
    return value


def _validate_energy_affine_conditioning(conditioning: Any) -> dict[str, Any]:
    if not isinstance(conditioning, dict):
        raise VerificationFailure("positive-affine-energy conditioning metrics are missing")
    required = {
        "packet_count",
        "packets_with_keep_boundary",
        "scale",
        "offset",
        "scale_minimum",
        "scale_maximum",
        "magnitude_limit",
        "minimum_required_keep_boundary_span_fraction",
        "minimum_required_selected_adjacent_gap_span_fraction",
        "minimum_required_ulp_multiplier",
        "maximum_allowed_shift_span_fraction",
        "maximum_allowed_retained_adjacent_gap_ratio_perturbation",
        "baseline_max_magnitude",
        "transformed_max_magnitude",
        "baseline_min_keep_boundary_margin_over_span",
        "transformed_min_keep_boundary_margin_over_span",
        "baseline_min_keep_boundary_margin_in_ulps",
        "transformed_min_keep_boundary_margin_in_ulps",
        "baseline_min_keep_boundary_requirement_ratio",
        "transformed_min_keep_boundary_requirement_ratio",
        "baseline_min_selected_adjacent_gap_margin_over_span",
        "transformed_min_selected_adjacent_gap_margin_over_span",
        "baseline_min_selected_adjacent_gap_margin_in_ulps",
        "transformed_min_selected_adjacent_gap_margin_in_ulps",
        "baseline_min_selected_adjacent_gap_requirement_ratio",
        "transformed_min_selected_adjacent_gap_requirement_ratio",
        "baseline_max_shift_span_fraction",
        "transformed_max_shift_span_fraction",
        "exact_stable_selected_prefix_preserved",
        "exact_energy_sorted_selected_index_sequence_preserved",
        "exact_selected_index_sequence_preserved",
        "max_retained_adjacent_gap_ratio_perturbation",
    }
    missing = sorted(required - set(conditioning))
    if missing:
        raise VerificationFailure(
            "positive-affine-energy conditioning coverage is incomplete",
            {"missing": missing},
        )
    packet_count = conditioning.get("packet_count")
    boundary_count = conditioning.get("packets_with_keep_boundary")
    if (
        isinstance(packet_count, bool)
        or not isinstance(packet_count, int)
        or packet_count <= 0
        or isinstance(boundary_count, bool)
        or not isinstance(boundary_count, int)
        or not 1 <= boundary_count <= packet_count
    ):
        raise VerificationFailure("positive-affine-energy packet metrics are invalid")

    values = {name: _finite_metric(conditioning, name) for name in required if name not in {
        "packet_count",
        "packets_with_keep_boundary",
        "exact_stable_selected_prefix_preserved",
        "exact_energy_sorted_selected_index_sequence_preserved",
        "exact_selected_index_sequence_preserved",
    }}
    exact_constants = {
        "scale": 1.625,
        "offset": -4.75,
        "scale_minimum": 0.5,
        "scale_maximum": 2.0,
        "magnitude_limit": 1e100,
        "minimum_required_keep_boundary_span_fraction": 1e-8,
        "minimum_required_selected_adjacent_gap_span_fraction": 1e-9,
        "minimum_required_ulp_multiplier": 1_048_576.0,
        "maximum_allowed_shift_span_fraction": 0.005,
        "maximum_allowed_retained_adjacent_gap_ratio_perturbation": 1e-10,
    }
    if any(values[name] != expected for name, expected in exact_constants.items()):
        raise VerificationFailure(
            "positive-affine-energy declared thresholds/transform drifted",
            {
                "observed": {name: values[name] for name in exact_constants},
                "expected": exact_constants,
            },
        )
    if not values["scale_minimum"] <= values["scale"] <= values["scale_maximum"]:
        raise VerificationFailure("positive-affine-energy scale is outside its declared range")
    if any(
        not 0.0 <= values[name] <= values["magnitude_limit"]
        for name in ("baseline_max_magnitude", "transformed_max_magnitude")
    ):
        raise VerificationFailure("positive-affine-energy magnitude limit failed")
    if any(
        not 0.0
        <= values[name]
        <= values["maximum_allowed_shift_span_fraction"]
        for name in (
            "baseline_max_shift_span_fraction",
            "transformed_max_shift_span_fraction",
        )
    ):
        raise VerificationFailure("positive-affine-energy shift covariance failed")
    for coordinate in ("baseline", "transformed"):
        if (
            values[f"{coordinate}_min_keep_boundary_margin_over_span"] < 1e-8
            or values[f"{coordinate}_min_keep_boundary_margin_in_ulps"] < 1_048_576.0
            or values[f"{coordinate}_min_keep_boundary_requirement_ratio"] < 1.0
            or values[f"{coordinate}_min_selected_adjacent_gap_margin_over_span"] < 1e-9
            or values[f"{coordinate}_min_selected_adjacent_gap_margin_in_ulps"] < 1_048_576.0
            or values[f"{coordinate}_min_selected_adjacent_gap_requirement_ratio"] < 1.0
        ):
            raise VerificationFailure(
                f"positive-affine-energy {coordinate} conditioning margin failed"
            )
    exact_fields = (
        "exact_stable_selected_prefix_preserved",
        "exact_energy_sorted_selected_index_sequence_preserved",
        "exact_selected_index_sequence_preserved",
    )
    if any(conditioning.get(name) is not True for name in exact_fields):
        raise VerificationFailure("positive-affine-energy selected-index identity failed")
    if not (
        0.0
        <= values["max_retained_adjacent_gap_ratio_perturbation"]
        <= values["maximum_allowed_retained_adjacent_gap_ratio_perturbation"]
    ):
        raise VerificationFailure("positive-affine-energy gap-ratio perturbation failed")
    return {
        "packet_count": packet_count,
        "packets_with_keep_boundary": boundary_count,
        **values,
        **{name: True for name in exact_fields},
    }


def _metamorphic_negative_controls(
    runner: Path,
    reference_analyzer: Path,
    source_case: Path,
    timeout: float,
) -> dict[str, Any]:
    """Require both affine-map preflight rejection and a minimal CLI failure report."""

    harness_path = runner.with_name("harness.py")
    specification = importlib.util.spec_from_file_location(
        "_spectral_scaling_metamorphic_negative_harness", harness_path
    )
    if specification is None or specification.loader is None:
        raise VerificationFailure("could not load metamorphic harness for negative control")
    harness = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(harness)
    with tempfile.TemporaryDirectory(prefix="spectral-metamorphic-negative-") as temporary:
        root = Path(temporary)
        rejected_destination = root / "rejected_affine_destination"
        direct_error = ""
        try:
            harness.transform_positive_affine_energy(
                source_case,
                rejected_destination,
                scale=3.0,
                offset=-4.75,
            )
        except Exception as error:
            direct_error = f"{type(error).__name__}: {error}"
        if not direct_error.startswith("ValueError:") or rejected_destination.exists():
            raise VerificationFailure(
                "ill-conditioned affine map was not rejected before destination creation",
                {
                    "error": direct_error,
                    "destination_exists": rejected_destination.exists(),
                },
            )

        malformed_case = root / "malformed_case"
        malformed_case.mkdir()
        report_path = root / "fatal_report.json"
        try:
            process = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(runner),
                    "--analyzer",
                    str(reference_analyzer),
                    "--case",
                    str(malformed_case),
                    "--report",
                    str(report_path),
                    "--python",
                    sys.executable,
                    "--timeout",
                    str(min(timeout, 60.0)),
                ],
                cwd=TASK_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=min(timeout, 60.0),
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise VerificationFailure("metamorphic structured-failure probe timed out") from error
        expected_report = {
            "schema_version": "spectral-scaling-metamorphic-report/v1",
            "passed": False,
            "fatal_error": "metamorphic_suite_exception",
        }
        try:
            parsed = json.loads(process.stdout.decode("utf-8"))
        except Exception as error:
            raise VerificationFailure(
                "metamorphic structured-failure probe emitted invalid JSON"
            ) from error
        report_bytes = report_path.read_bytes() if report_path.is_file() else b""
        if (
            process.returncode != 1
            or process.stderr != b""
            or parsed != expected_report
            or report_bytes != process.stdout
            or set(malformed_case.iterdir())
        ):
            raise VerificationFailure(
                "metamorphic CLI failure boundary is not stable/minimal",
                {
                    "returncode": process.returncode,
                    "stderr": process.stderr.decode("utf-8", errors="replace")[-1000:],
                    "parsed": parsed,
                    "report_matches_stdout": report_bytes == process.stdout,
                    "malformed_case_entries": sorted(
                        path.name for path in malformed_case.iterdir()
                    ),
                },
            )
    return {
        "rejected_affine_scale": 3.0,
        "allowed_affine_scale_interval": [0.5, 2.0],
        "preflight_rejected": True,
        "destination_created": False,
        "direct_error_type": direct_error.split(":", 1)[0],
        "structured_cli_exit": 1,
        "structured_cli_stderr_bytes": 0,
        "structured_failure_report": expected_report,
        "report_bytes_equal_stdout": True,
        "rejected_transform_analysis_started": False,
    }


def gate_metamorphics(timeout: float, state: dict[str, Any]) -> dict[str, Any]:
    submissions: dict[str, Path] | None = state.get("submissions")
    if not submissions:
        raise VerificationFailure("clean-room submissions were not available")
    runner = PRIVATE / "metamorphic" / "run.py"
    if not runner.is_file():
        raise VerificationFailure("private metamorphic harness is missing")
    suite = _json(PRIVATE / "reference" / "suite.json")
    selected = suite["cases"][0]
    case_dir = (PRIVATE / "reference" / selected["input"]).resolve()
    negative_controls = _metamorphic_negative_controls(
        runner,
        submissions["reference"] / "output" / "analyze.py",
        case_dir,
        timeout,
    )
    reports: dict[str, Any] = {}
    for name, submission in submissions.items():
        report = _run_json(
            [
                sys.executable,
                "-B",
                str(runner),
                "--analyzer",
                str(submission / "output" / "analyze.py"),
                "--case",
                str(case_dir),
                "--python",
                sys.executable,
                "--timeout",
                str(min(timeout, 240.0)),
            ],
            cwd=TASK_ROOT,
            timeout=max(timeout, 1200.0),
            label=f"{name} metamorphic suite",
        )
        tests = report.get("tests", {})
        if (
            report.get("schema_version") != "spectral-scaling-metamorphic-report/v1"
            or report.get("passed") is not True
            or not isinstance(tests, dict)
            or Path(str(report.get("case", ""))).resolve() != case_dir.resolve()
            or Path(str(report.get("analyzer", ""))).resolve()
            != (submission / "output" / "analyze.py").resolve()
        ):
            raise VerificationFailure(f"{name} metamorphic suite failed", report)
        missing = REQUIRED_METAMORPHICS - set(tests)
        extra = set(tests) - REQUIRED_METAMORPHICS
        failed = sorted(
            test_name
            for test_name, result in tests.items()
            if not isinstance(result, dict) or result.get("passed") is not True
        )
        if missing or extra or failed:
            raise VerificationFailure(
                f"{name} metamorphic coverage/result failure",
                {
                    "missing": sorted(missing),
                    "extra": sorted(extra),
                    "failed": failed,
                    "report": report,
                },
            )
        relation_metrics: dict[str, Any] = {}
        for test_name in sorted(REQUIRED_METAMORPHICS):
            result = tests[test_name]
            comparisons = result.get("comparisons")
            relaxed = result.get("relaxed_uncertainty_checks")
            atol = _finite_metric(result, "atol")
            rtol = _finite_metric(result, "rtol")
            max_error = _finite_metric(result, "max_abs_error")
            max_ratio = _finite_metric(result, "max_error_to_tolerance_ratio")
            if (
                result.get("relation") != test_name
                or isinstance(comparisons, bool)
                or not isinstance(comparisons, int)
                or comparisons <= 0
                or isinstance(relaxed, bool)
                or not isinstance(relaxed, int)
                or not 0 <= relaxed <= comparisons
                or atol != 5e-9
                or rtol != 5e-8
                or not 0.0 <= max_error
                or not 0.0 <= max_ratio <= 1.0 + 1e-12
                or result.get("messages") != []
            ):
                raise VerificationFailure(
                    f"{name} metamorphic relation metrics are invalid: {test_name}",
                    result,
                )
            expects_relaxed = test_name in {
                "realization_id_permutation",
                "target_mirror",
            }
            if (expects_relaxed and relaxed <= 0) or (not expects_relaxed and relaxed != 0):
                raise VerificationFailure(
                    f"{name} metamorphic uncertainty-check coverage drifted: {test_name}",
                    result,
                )
            relation_metrics[test_name] = {
                "relation": result["relation"],
                "comparisons": comparisons,
                "relaxed_uncertainty_checks": relaxed,
                "atol": atol,
                "rtol": rtol,
                "max_abs_error": max_error,
                "max_error_to_tolerance_ratio": max_ratio,
            }
        energy_conditioning = _validate_energy_affine_conditioning(
            tests["positive_affine_energy"].get("conditioning")
        )
        shard_integrity = tests["shard_rejoin"].get("integrity")
        if (
            not isinstance(shard_integrity, dict)
            or isinstance(shard_integrity.get("packet_count"), bool)
            or not isinstance(shard_integrity.get("packet_count"), int)
            or shard_integrity["packet_count"] <= 0
            or isinstance(shard_integrity.get("eigenvalue_count"), bool)
            or not isinstance(shard_integrity.get("eigenvalue_count"), int)
            or shard_integrity["eigenvalue_count"] <= 0
        ):
            raise VerificationFailure(f"{name} shard relation integrity metrics are invalid")
        reports[name] = {
            "passed": True,
            "case_id": selected["case_id"],
            "tests": {
                test_name: {
                    "passed": result["passed"],
                    "comparisons": result.get("comparisons"),
                    "relaxed_uncertainty_checks": result.get(
                        "relaxed_uncertainty_checks"
                    ),
                    "atol": result.get("atol"),
                    "rtol": result.get("rtol"),
                    "max_abs_error": result.get("max_abs_error"),
                    "max_error_to_tolerance_ratio": result.get(
                        "max_error_to_tolerance_ratio"
                    ),
                    "relation": result.get("relation"),
                }
                for test_name, result in sorted(tests.items())
            },
            "relation_metrics": relation_metrics,
            "positive_affine_energy_conditioning": energy_conditioning,
            "shard_integrity": shard_integrity,
        }
    reports["reference"]["negative_controls"] = negative_controls
    return reports


def _write_results(path: Path, result: dict[str, Any]) -> None:
    destination = path.resolve()
    allowed_destinations = {
        (AUTHOR / "verification_results.json").resolve(),
        (TASK_ROOT / "scripts" / "verification_results.json").resolve(),
    }
    if destination not in allowed_destinations:
        raise VerificationFailure(
            "--results must be author/verification_results.json or scripts/verification_results.json"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(destination)


def _build_identity() -> tuple[str, int]:
    """Hash release-relevant bytes while excluding the self-referential ledger."""

    included_roots = [PARTICIPANT, PRIVATE, AUTHOR, TASK_ROOT / "scripts"]
    excluded = {
        "author/verification_report.md",
        "author/verification_results.json",
        "scripts/verification_results.json",
    }
    records: dict[str, Path] = {}
    for root in included_roots:
        for relative, path in _files(root).items():
            task_relative = path.relative_to(TASK_ROOT).as_posix()
            if task_relative in excluded:
                continue
            if "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".pyo"}:
                continue
            records[task_relative] = path
    digest = hashlib.sha256()
    for relative, path in sorted(records.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path.read_bytes()).encode("ascii"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}", len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        help="optional JSON destination under author/ or scripts/",
    )
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=600.0,
        help="wall-time limit for each outer verification subprocess",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=min(2, os.cpu_count() or 1),
        help="parallel private grades for scientific mutants",
    )
    arguments = parser.parse_args()
    if (
        not math.isfinite(arguments.command_timeout)
        or arguments.command_timeout <= 0.0
        or arguments.jobs < 1
        or arguments.jobs > 4
    ):
        parser.error(
            "--command-timeout must be finite and positive and --jobs must be between 1 and 4"
        )

    started = time.perf_counter()
    recorder = Recorder()
    state: dict[str, Any] = {}
    initial_build_identity, initial_build_file_count = _build_identity()
    with tempfile.TemporaryDirectory(prefix="spectral-scaling-verify-") as temporary:
        work = Path(temporary)
        recorder.run("inventory", gate_inventory)
        recorder.run("participant_private_separation", gate_separation_and_leaks)
        recorder.run("package_sizes_and_imports", gate_sizes_and_imports)
        recorder.run(
            "oracle_generation_determinism",
            lambda: gate_generator(work, arguments.command_timeout),
        )
        recorder.run(
            "exact_diagonalization_realism_determinism",
            lambda: gate_ed_realism(work, arguments.command_timeout),
        )
        recorder.run("oracle_scientific_invariants", gate_oracle_invariants)
        recorder.run(
            "clean_room_public_validation",
            lambda: gate_clean_room(work, arguments.command_timeout, state),
        )
        recorder.run(
            "private_evaluator_determinism",
            lambda: gate_repeated_grading(arguments.command_timeout, state),
        )
        recorder.run(
            "scientific_mutant_sensitivity",
            lambda: gate_mutants(
                work, arguments.command_timeout, arguments.jobs, state
            ),
        )
        recorder.run(
            "hardcoded_retired_case_shortcut",
            lambda: gate_hardcoded_public_shortcut(state),
        )
        recorder.run(
            "malformed_nan_partial_oversize_security_probes",
            lambda: gate_probes(arguments.command_timeout),
        )
        recorder.run(
            "hardlink_rejection",
            lambda: gate_hardlink_rejection(work, arguments.command_timeout),
        )
        recorder.run(
            "metamorphic_covariance",
            lambda: gate_metamorphics(arguments.command_timeout, state),
        )

    def build_unchanged() -> dict[str, Any]:
        current_identity, current_count = _build_identity()
        state["build_identity"] = current_identity
        state["build_file_count"] = current_count
        if (
            current_identity != initial_build_identity
            or current_count != initial_build_file_count
        ):
            raise VerificationFailure(
                "release-relevant package files changed during verification",
                {
                    "initial_build_identity": initial_build_identity,
                    "final_build_identity": current_identity,
                    "initial_file_count": initial_build_file_count,
                    "final_file_count": current_count,
                },
            )
        return {
            "build_identity": current_identity,
            "file_count": current_count,
            "unchanged": True,
        }

    recorder.run("package_unchanged_during_verification", build_unchanged)

    passed = all(record["passed"] for record in recorder.gates)
    build_identity = state.get("build_identity", initial_build_identity)
    build_file_count = state.get("build_file_count", initial_build_file_count)
    result = {
        "schema_version": "spectral-scaling-verification-results/v1",
        "task_id": "spectral-scaling-audit-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "numpy": np.__version__,
        },
        "passed": passed,
        "status": "pass" if passed else "fail",
        "required_failures": [
            record["name"] for record in recorder.gates if not record["passed"]
        ],
        "provisional_difficulty": "structurally_hard_candidate",
        "agent_calibration": "not_run",
        "build_identity": build_identity,
        "build_file_count": build_file_count,
        "release_disposition": (
            "accepted_for_collaborator_review" if passed else "verification_failed"
        ),
        "gate_count": len(recorder.gates),
        "passed_gate_count": sum(record["passed"] for record in recorder.gates),
        "duration_seconds": time.perf_counter() - started,
        "gates": recorder.gates,
    }
    if arguments.results is not None:
        try:
            _write_results(arguments.results, result)
        except Exception as error:
            result["passed"] = False
            result["status"] = "fail"
            result["release_disposition"] = "verification_failed"
            result["results_write_error"] = f"{type(error).__name__}: {error}"
            result["required_failures"].append("verification_results_write")
            passed = False
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
