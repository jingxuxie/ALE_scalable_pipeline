"""Deterministic content identities used by paper2ale pipeline stages."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .schema import canonical_json_bytes


_READ_CHUNK_SIZE = 1024 * 1024


def sha256_bytes(data: bytes | bytearray | memoryview) -> str:
    """Return the lowercase SHA-256 hex digest of a bytes-like object."""

    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Stream a file and return its lowercase SHA-256 hex digest."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(prefix: str, payload: Any) -> str:
    """Build a readable, content-derived identity for a JSON payload."""

    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError("prefix must be a nonempty string")
    prefix = prefix.strip()
    digest = sha256_bytes(canonical_json_bytes(payload))
    return f"{prefix}_{digest}"


def stage_key(
    stage: str,
    version: str | int,
    inputs: Any,
    config: Any,
) -> str:
    """Return the cache key for one versioned stage invocation.

    Lists preserve order because it can be semantically meaningful.  Mapping
    order is normalized by :func:`canonical_json_bytes`.
    """

    if not isinstance(stage, str) or not stage.strip():
        raise ValueError("stage must be a nonempty string")
    if not isinstance(version, (str, int)) or isinstance(version, bool):
        raise TypeError("version must be a string or integer")
    if isinstance(version, str) and not version.strip():
        raise ValueError("version must not be empty")
    stage = stage.strip()
    return stable_id(
        "stage",
        {
            "stage": stage,
            "version": version,
            "inputs": inputs,
            "config": config,
        },
    )


__all__ = ["sha256_bytes", "sha256_file", "stable_id", "stage_key"]
