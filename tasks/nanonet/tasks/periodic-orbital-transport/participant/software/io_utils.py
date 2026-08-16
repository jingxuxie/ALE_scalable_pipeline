"""Small, solution-independent helpers for the participant file contract.

The functions here deliberately provide only safe parsing, generic validation,
atomic serialization, and hashing. They do not implement the scientific model.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np


MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_NPZ_BYTES = 50 * 1024 * 1024
_NPZ_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class ContractError(ValueError):
    """Raised when a public input or output violates the declared contract."""


def _reject_constant(token: str) -> None:
    raise ContractError(f"non-finite JSON number is not allowed: {token}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _regular_file(path: str | os.PathLike[str], max_bytes: int) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(f"expected a regular, non-symlink file: {candidate}")
    size = candidate.stat().st_size
    if size > max_bytes:
        raise ContractError(f"file exceeds {max_bytes} bytes: {candidate}")
    return candidate


def load_json(
    path: str | os.PathLike[str], *, max_bytes: int = MAX_JSON_BYTES
) -> Any:
    """Load strict UTF-8 JSON, rejecting duplicates and non-finite constants."""

    source = _regular_file(path, max_bytes)
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid UTF-8 JSON in {source}: {exc}") from exc


def require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be an object")
    return value


def require_sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ContractError(f"{name} must be an array")
    return value


def require_exact_keys(
    value: Mapping[str, Any], expected: Sequence[str], name: str
) -> None:
    wanted = set(expected)
    actual = set(value)
    missing = sorted(wanted - actual)
    extra = sorted(actual - wanted)
    if missing or extra:
        raise ContractError(f"{name} keys: missing={missing}, extra={extra}")


def require_string(value: Any, name: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ContractError(f"{name} must be a nonempty string")
    return value


def require_finite_real(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{name} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise ContractError(f"{name} must be finite")
    return result


def require_integer(
    value: Any,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not float(value).is_integer()
    ):
        raise ContractError(f"{name} must be an integer")
    result = int(value)
    if minimum is not None and result < minimum:
        raise ContractError(f"{name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ContractError(f"{name} must be at most {maximum}")
    return result


def as_array(
    value: Any,
    name: str,
    *,
    dtype: np.dtype[Any] | type,
    ndim: int | None = None,
    shape: tuple[int | None, ...] | None = None,
    finite: bool = True,
) -> np.ndarray:
    """Convert generic data to a C-contiguous array and validate its shape."""

    try:
        array = np.ascontiguousarray(np.asarray(value, dtype=dtype))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError(f"cannot convert {name} to {np.dtype(dtype)}: {exc}") from exc
    if ndim is not None and array.ndim != ndim:
        raise ContractError(f"{name} must have {ndim} dimensions, got {array.ndim}")
    if shape is not None:
        if array.ndim != len(shape):
            raise ContractError(f"{name} must have shape {shape}, got {array.shape}")
        for axis, (actual, expected) in enumerate(zip(array.shape, shape)):
            if expected is not None and actual != expected:
                raise ContractError(
                    f"{name} axis {axis} must have length {expected}, got {actual}"
                )
    if finite and array.dtype.kind in "fc" and not np.isfinite(array).all():
        raise ContractError(f"{name} contains NaN or infinity")
    return array


def ensure_output_dir(path: str | os.PathLike[str]) -> Path:
    """Create and return an output directory without accepting a symlink."""

    output = Path(path)
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink() or not output.is_dir():
        raise ContractError(f"expected a non-symlink output directory: {output}")
    return output


def save_npz_atomic(
    path: str | os.PathLike[str], arrays: Mapping[str, np.ndarray]
) -> None:
    """Atomically write numeric, C-contiguous arrays to a compressed NPZ."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    prepared: dict[str, np.ndarray] = {}
    for key, value in arrays.items():
        if not _NPZ_KEY.fullmatch(key):
            raise ContractError(f"unsafe NPZ key: {key!r}")
        array = np.ascontiguousarray(np.asarray(value))
        if array.dtype.hasobject or array.dtype.kind not in "biufc":
            raise ContractError(f"NPZ array {key!r} must have a numeric dtype")
        if array.dtype.kind in "fc" and not np.isfinite(array).all():
            raise ContractError(f"NPZ array {key!r} contains NaN or infinity")
        prepared[key] = array

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
            np.savez_compressed(temporary, **prepared)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def load_npz(
    path: str | os.PathLike[str],
    *,
    expected_keys: Sequence[str] | None = None,
    max_bytes: int = MAX_NPZ_BYTES,
) -> dict[str, np.ndarray]:
    """Load an NPZ without pickle and detach every array from the archive."""

    source = _regular_file(path, max_bytes)
    try:
        with np.load(source, allow_pickle=False) as archive:
            if expected_keys is not None:
                actual = set(archive.files)
                wanted = set(expected_keys)
                if actual != wanted:
                    raise ContractError(
                        f"{source} keys: missing={sorted(wanted - actual)}, "
                        f"extra={sorted(actual - wanted)}"
                    )
            result = {key: np.ascontiguousarray(archive[key]) for key in archive.files}
    except (OSError, ValueError) as exc:
        raise ContractError(f"invalid NPZ file {source}: {exc}") from exc
    for key, array in result.items():
        if array.dtype.hasobject:
            raise ContractError(f"NPZ array {key!r} has object dtype")
    return result


def _json_compatible(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [_json_compatible(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _json_compatible(value.item())
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


def save_json_atomic(path: str | os.PathLike[str], value: Any) -> None:
    """Atomically write deterministic UTF-8 JSON and reject NaN/infinity."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(
                _json_compatible(value),
                temporary,
                allow_nan=False,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
    except (TypeError, ValueError) as exc:
        raise ContractError(f"value is not finite JSON data: {exc}") from exc
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def sha256_file(path: str | os.PathLike[str], *, chunk_bytes: int = 1024 * 1024) -> str:
    """Return lowercase SHA-256 for the file's raw bytes."""

    source = _regular_file(path, MAX_JSON_BYTES)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()
