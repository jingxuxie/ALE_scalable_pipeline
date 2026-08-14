"""Trusted compiler context for content-addressed paper assets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .assets import AssetCache


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


@dataclass(frozen=True, slots=True)
class BuildContext:
    """Read-only, digest-verifying asset resolver supplied to trusted families.

    Project JSON remains portable and contains only file-tree snapshots. Raw
    bytes live in an operator-selected :class:`AssetCache`; a family must ask
    for an exact ``asset_id`` and ``relative_path`` already present in the
    snapshot. No cache path crosses into generated artifacts or build identity.
    """

    asset_bundle_digest: str
    asset_snapshots: tuple[Mapping[str, Any], ...]
    _cache: AssetCache | None = None

    @classmethod
    def from_project(
        cls,
        project: Mapping[str, Any],
        *,
        asset_cache: AssetCache | None = None,
    ) -> "BuildContext":
        raw = project.get("asset_snapshots", [])
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise TypeError("project asset_snapshots must be an array")
        snapshots = json.loads(_canonical(list(raw)))
        if not isinstance(snapshots, list):
            raise TypeError("project asset_snapshots must be an array")
        by_id: dict[str, Mapping[str, Any]] = {}
        frozen: list[Mapping[str, Any]] = []
        for snapshot in sorted(snapshots, key=lambda item: str(item.get("asset_id", ""))):
            if not isinstance(snapshot, dict):
                raise TypeError("asset snapshot must be an object")
            asset_id = snapshot.get("asset_id")
            if not isinstance(asset_id, str) or not asset_id:
                raise ValueError("asset snapshot requires asset_id")
            if asset_id in by_id:
                raise ValueError(f"duplicate asset snapshot {asset_id!r}")
            value = _freeze(snapshot)
            by_id[asset_id] = value
            frozen.append(value)
        digest = hashlib.sha256(
            _canonical(
                sorted(snapshots, key=lambda item: str(item.get("asset_id", "")))
            )
        ).hexdigest()
        return cls(digest, tuple(frozen), asset_cache)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "paper2ale.build-context/v1",
            "asset_bundle_digest": self.asset_bundle_digest,
            "asset_ids": sorted(
                str(snapshot["asset_id"]) for snapshot in self.asset_snapshots
            ),
            "cache_available": self._cache is not None,
        }

    def read_asset(
        self,
        asset_id: str,
        relative_path: str,
        *,
        max_bytes: int | None = None,
    ) -> bytes:
        """Read and verify one snapshot-bound blob from the configured CAS."""

        snapshot = next(
            (
                item
                for item in self.asset_snapshots
                if item.get("asset_id") == asset_id
            ),
            None,
        )
        if snapshot is None:
            raise KeyError(f"project has no asset snapshot {asset_id!r}")
        files = snapshot.get("files")
        if isinstance(files, (str, bytes)) or not isinstance(files, Sequence):
            raise ValueError(f"asset snapshot {asset_id!r} has no file manifest")
        entry = next(
            (
                item
                for item in files
                if isinstance(item, Mapping)
                and item.get("relative_path") == relative_path
            ),
            None,
        )
        if entry is None:
            raise KeyError(
                f"asset snapshot {asset_id!r} has no file {relative_path!r}"
            )
        digest = entry.get("sha256")
        size = entry.get("size_bytes")
        if not isinstance(digest, str) or not isinstance(size, int):
            raise ValueError("asset file manifest lacks digest or size")
        if self._cache is None:
            raise RuntimeError(
                "asset bytes are required but no AssetCache was supplied to the build"
            )
        limit = size if max_bytes is None else max_bytes
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("max_bytes must be a positive integer")
        if size > limit:
            raise ValueError(
                f"asset file uses {size} bytes, exceeding the {limit}-byte read limit"
            )
        data = self._cache.read(digest, max_bytes=limit)
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("asset cache bytes do not match the project snapshot")
        return data


__all__ = ["BuildContext"]
