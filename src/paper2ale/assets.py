"""Deterministic, bounded snapshots of local paper-adjacent assets.

This module is deliberately network-free.  An operator first obtains a paper,
repository, or dataset, then resolves it into a content-addressed manifest.
Absolute local paths are never included in manifests or model-facing text.
Symlinks and special files are rejected, and directory traversal is stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib.metadata
import io
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


ASSET_SCHEMA_VERSION = "paper2ale.asset-snapshot/v1"
ASSET_KINDS = frozenset({"document", "repository", "dataset", "file"})
_ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED_STEMS = frozenset(
    {
        "aux",
        "clock$",
        "con",
        "conin$",
        "conout$",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
        "com\u00b9",
        "com\u00b2",
        "com\u00b3",
        "lpt\u00b9",
        "lpt\u00b2",
        "lpt\u00b3",
    }
)
_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_DEFAULT_EXCLUDED_NAMES = frozenset(
    {".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache"}
)
_SENSITIVE_FILE_NAMES = frozenset(
    {
        ".env",
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "application_default_credentials.json",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "kubeconfig",
        "secrets.json",
    }
)
_SENSITIVE_FILE_SUFFIXES = frozenset(
    {".jks", ".key", ".keystore", ".p12", ".pem", ".pfx", ".tfstate"}
)
_TEXT_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cfg",
        ".conf",
        ".cpp",
        ".csv",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".ipynb",
        ".java",
        ".jl",
        ".js",
        ".json",
        ".jsonl",
        ".md",
        ".m",
        ".py",
        ".r",
        ".rst",
        ".sh",
        ".tex",
        ".toml",
        ".ts",
        ".tsv",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)


def _positive(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _asset_id(value: Any) -> str:
    if not isinstance(value, str) or _ASSET_ID.fullmatch(value) is None:
        raise ValueError(f"asset_id must match {_ASSET_ID.pattern}")
    return value


def _strict_json_object(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    try:
        encoded = json.dumps(
            dict(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must contain only strict JSON values") from error
    if len(encoded.encode("utf-8")) > 64 * 1024:
        raise ValueError(f"{name} exceeds the 65536-byte limit")
    decoded = json.loads(encoded)
    assert isinstance(decoded, dict)
    _reject_absolute_paths(decoded, name)
    return decoded


def _reject_absolute_paths(value: Any, name: str, path: str = "$") -> None:
    """Keep operator-local filesystem locations out of portable manifests."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if key.casefold() in {"absolute_path", "local_path", "source_path"}:
                raise ValueError(f"{name} contains forbidden local path field {path}.{key}")
            _reject_absolute_paths(item, name, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_absolute_paths(item, name, f"{path}[{index}]")
    elif isinstance(value, str) and Path(value).is_absolute():
        raise ValueError(f"{name} contains an absolute local path at {path}")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("asset relative paths must be nonempty POSIX paths")
    if "\x00" in value or any(ord(character) < 32 for character in value):
        raise ValueError(f"unsafe asset relative path {value!r}")
    path = PurePosixPath(value)
    parts = value.split("/")
    if path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe asset relative path {value!r}")
    for part in parts:
        if ":" in part or part.endswith((".", " ")):
            raise ValueError(f"unsafe asset relative path {value!r}")
        device_stem = part.split(".", 1)[0].rstrip(" .").casefold()
        if device_stem in _WINDOWS_RESERVED_STEMS:
            raise ValueError(f"unsafe asset relative path {value!r}")
    return path.as_posix()


def _reject_sensitive_relative_path(value: str) -> None:
    """Fail closed on common credential and private-key filenames.

    This is deliberately name-based and deterministic.  It does not claim to
    discover secrets in otherwise ordinary files.
    """

    relative = _safe_relative_path(value)
    name = relative.rsplit("/", 1)[-1].casefold()
    sensitive = (
        name in _SENSITIVE_FILE_NAMES
        or name.startswith(".env.")
        or any(name.endswith(suffix) for suffix in _SENSITIVE_FILE_SUFFIXES)
    )
    if sensitive:
        raise ValueError(
            f"asset contains a sensitive filename that must not be snapshotted: {relative!r}"
        )


def _win32_normalized_path(value: str) -> str:
    return "/".join(part.rstrip(" .").casefold() for part in value.split("/"))


def _register_win32_path(
    seen: dict[str, tuple[str, str, bool, bool]],
    value: str,
    *,
    description: str,
    leaf_is_file: bool = True,
) -> None:
    """Reject paths whose file or directory components alias on Win32."""

    literal_parts = value.split("/")
    for length in range(1, len(literal_parts) + 1):
        literal = "/".join(literal_parts[:length])
        normalized = _win32_normalized_path(literal)
        previous = seen.get(normalized)
        component_is_leaf = length == len(literal_parts)
        component_is_file = leaf_is_file and length == len(literal_parts)
        if previous is not None and (
            previous[0] != literal
            or previous[2]
            or component_is_file
            or (previous[3] and component_is_leaf)
        ):
            raise ValueError(
                f"{description} contain a Win32-normalized collision between "
                f"{previous[1]!r} and {value!r}"
            )
        if previous is None:
            seen[normalized] = (
                literal,
                value,
                component_is_file,
                component_is_leaf,
            )


def _reject_win32_collisions(paths: Iterable[str], *, description: str) -> None:
    seen: dict[str, tuple[str, str, bool, bool]] = {}
    for value in paths:
        _register_win32_path(seen, value, description=description)


def _lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _reject_link_or_reparse(path: Path, *, description: str) -> None:
    metadata = _lstat_or_none(path)
    if metadata is None:
        return
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{description} must not be a symbolic link: {path}")
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    if attributes & _WINDOWS_REPARSE_POINT:
        raise ValueError(f"{description} must not be a Windows reparse point: {path}")


def _require_contained_path(
    path: Path,
    *,
    root: Path,
    description: str,
    require_exists: bool,
) -> Path:
    """Reject link-like components and paths resolving outside a trusted root."""

    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{description} escapes its selected root: {path}") from error

    current = root
    _reject_link_or_reparse(current, description=description)
    for part in relative.parts:
        current /= part
        metadata = _lstat_or_none(current)
        if metadata is None:
            if require_exists:
                raise FileNotFoundError(f"{description} does not exist: {current}")
            break
        _reject_link_or_reparse(current, description=description)

    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=require_exists)
    except FileNotFoundError:
        if require_exists:
            raise
        resolved = path.resolve(strict=False)
        resolved_root = root.resolve(strict=True)
    if resolved_root != root:
        raise ValueError(f"{description} root changed or resolves through a link: {root}")
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"{description} resolves outside its selected root: {path}") from error
    return resolved


@dataclass(frozen=True, slots=True)
class AssetLimits:
    max_files: int = 5_000
    max_file_bytes: int = 32 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    max_depth: int = 32
    max_text_chars_per_file: int = 2_000_000
    max_total_text_chars: int = 8_000_000
    max_pdf_pages: int = 1_000

    def __post_init__(self) -> None:
        for name in (
            "max_files",
            "max_file_bytes",
            "max_total_bytes",
            "max_depth",
            "max_text_chars_per_file",
            "max_total_text_chars",
            "max_pdf_pages",
        ):
            _positive(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class AssetSpec:
    asset_id: str
    path: str | os.PathLike[str]
    kind: str = "auto"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _asset_id(self.asset_id))
        if self.kind != "auto" and self.kind not in ASSET_KINDS:
            raise ValueError(f"asset kind must be 'auto' or one of {sorted(ASSET_KINDS)}")
        object.__setattr__(self, "metadata", _freeze(_strict_json_object(self.metadata, "asset metadata")))


@dataclass(frozen=True, slots=True)
class AssetFile:
    relative_path: str
    size_bytes: int
    sha256: str
    media_type: str
    extraction_status: str
    extractor: str | None = None
    text: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "relative_path", _safe_relative_path(self.relative_path))
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ValueError("asset file size_bytes must be a nonnegative integer")
        if not isinstance(self.sha256, str) or _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("asset file sha256 must be lowercase hexadecimal SHA-256")
        if not isinstance(self.media_type, str) or not self.media_type:
            raise ValueError("asset file media_type must be nonempty")
        if self.extraction_status not in {"extracted", "binary", "empty", "omitted_limit"}:
            raise ValueError("invalid asset file extraction_status")
        if self.text is not None and self.extraction_status != "extracted":
            raise ValueError("asset file text requires extracted status")
        if self.text is None and self.extraction_status == "extracted":
            raise ValueError("extracted asset files require text")
        if self.extractor is not None and (not isinstance(self.extractor, str) or not self.extractor):
            raise ValueError("asset file extractor must be nonempty when present")

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "extraction_status": self.extraction_status,
        }
        if self.extractor is not None:
            value["extractor"] = self.extractor
        if include_text and self.text is not None:
            value["text"] = self.text
        return value


@dataclass(frozen=True, slots=True)
class AssetSnapshot:
    asset_id: str
    kind: str
    content_sha256: str
    files: tuple[AssetFile, ...]
    metadata: Mapping[str, Any]
    schema_version: str = ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ASSET_SCHEMA_VERSION:
            raise ValueError(f"asset schema_version must be {ASSET_SCHEMA_VERSION!r}")
        object.__setattr__(self, "asset_id", _asset_id(self.asset_id))
        if self.kind not in ASSET_KINDS:
            raise ValueError(f"asset kind must be one of {sorted(ASSET_KINDS)}")
        if not isinstance(self.content_sha256, str) or _SHA256.fullmatch(self.content_sha256) is None:
            raise ValueError("asset content_sha256 must be lowercase hexadecimal SHA-256")
        object.__setattr__(self, "files", tuple(self.files))
        if not self.files:
            raise ValueError("asset snapshot must contain at least one file")
        paths = [item.relative_path for item in self.files]
        if paths != sorted(paths) or len(set(paths)) != len(paths):
            raise ValueError("asset files must have unique, sorted relative paths")
        _reject_win32_collisions(paths, description="asset files")
        object.__setattr__(self, "metadata", _freeze(_strict_json_object(self.metadata, "asset metadata")))

    @property
    def size_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)

    @property
    def extracted_chars(self) -> int:
        return sum(len(item.text or "") for item in self.files)

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "kind": self.kind,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
            "metadata": _thaw(self.metadata),
            "files": [item.to_dict(include_text=include_text) for item in self.files],
        }

    def text_records(self) -> tuple[dict[str, str], ...]:
        """Return deterministic model-facing text without local filesystem paths."""

        return tuple(
            {
                "asset_id": self.asset_id,
                "file_sha256": item.sha256,
                "relative_path": item.relative_path,
                "locator": f"asset:{self.asset_id}/file:{item.relative_path}",
                "text": item.text,
            }
            for item in self.files
            if item.text is not None
        )


class AssetCache:
    """A local content-addressed blob cache with verified reads and writes."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        _reject_link_or_reparse(self.root, description="asset cache root")
        self.root.mkdir(parents=True, exist_ok=True)
        _reject_link_or_reparse(self.root, description="asset cache root")
        if not self.root.is_dir():
            raise ValueError(f"asset cache root is not a directory: {self.root}")
        self._resolved_root = self.root.resolve(strict=True)
        _require_contained_path(
            self._resolved_root,
            root=self._resolved_root,
            description="asset cache root",
            require_exists=True,
        )

    def _blob_path(self, digest: str) -> Path:
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError("cache digest must be lowercase hexadecimal SHA-256")
        return self._resolved_root / "blobs" / digest[:2] / digest

    def put(self, data: bytes) -> str:
        if not isinstance(data, bytes):
            raise TypeError("asset cache accepts bytes")
        digest = hashlib.sha256(data).hexdigest()
        destination = self._blob_path(digest)
        _require_contained_path(
            destination.parent,
            root=self._resolved_root,
            description="asset cache path",
            require_exists=False,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        _require_contained_path(
            destination,
            root=self._resolved_root,
            description="asset cache path",
            require_exists=False,
        )
        if destination.exists():
            cached = _read_regular_file(
                destination,
                limit=max(1, len(data)),
                root=self._resolved_root,
                description="asset cache blob",
            )
            if hashlib.sha256(cached).hexdigest() != digest:
                raise ValueError(f"asset cache blob is corrupt: {digest}")
            return digest
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=".p2a-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            try:
                os.link(temporary_name, destination)
            except FileExistsError:
                pass
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
        cached = _read_regular_file(
            destination,
            limit=max(1, len(data)),
            root=self._resolved_root,
            description="asset cache blob",
        )
        if hashlib.sha256(cached).hexdigest() != digest:
            raise ValueError(f"asset cache write verification failed: {digest}")
        return digest

    def read(self, digest: str, *, max_bytes: int) -> bytes:
        _positive(max_bytes, "max_bytes")
        path = self._blob_path(digest)
        _require_contained_path(
            path,
            root=self._resolved_root,
            description="asset cache blob",
            require_exists=False,
        )
        try:
            with path.open("rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError(f"asset cache blob is not a regular file: {digest}")
                data = stream.read(max_bytes + 1)
        except FileNotFoundError as error:
            raise KeyError(f"asset cache has no blob {digest}") from error
        if len(data) > max_bytes:
            raise ValueError(f"asset cache blob {digest} exceeds the read limit")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"asset cache blob is corrupt: {digest}")
        return data


def _read_regular_file(
    path: Path,
    *,
    limit: int,
    root: Path,
    description: str = "asset path",
) -> bytes:
    _require_contained_path(
        path,
        root=root,
        description=description,
        require_exists=True,
    )
    try:
        with path.open("rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError(f"asset path is not a regular file: {path}")
            data = stream.read(limit + 1)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"asset path does not exist: {path}") from error
    if len(data) > limit:
        raise ValueError(f"asset file exceeds the {limit}-byte limit: {path}")
    return data


def _extract_pdf(data: bytes, limits: AssetLimits) -> tuple[str | None, str, str | None]:
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError("PDF asset extraction requires pypdf") from error
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=True)
    except Exception as error:
        raise ValueError(f"PDF asset could not be parsed safely: {error}") from error
    if reader.is_encrypted:
        raise ValueError("encrypted PDF assets are not supported")
    if len(reader.pages) > limits.max_pdf_pages:
        return None, "omitted_limit", None
    pages: list[str] = []
    total = 0
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as error:
            raise ValueError(f"PDF extraction failed on page {page_number}: {error}") from error
        total += len(text)
        if total > limits.max_text_chars_per_file:
            return None, "omitted_limit", None
        pages.append(f"\n\n[PAGE {page_number}]\n{text}")
    extracted = "".join(pages).lstrip()
    if not extracted.strip():
        return None, "empty", None
    try:
        version = importlib.metadata.version("pypdf")
    except importlib.metadata.PackageNotFoundError:
        version = str(getattr(pypdf, "__version__", "unknown"))
    return extracted, "extracted", f"pypdf/{version}"


def _extract_file_text(
    relative_path: str,
    data: bytes,
    media_type: str,
    limits: AssetLimits,
) -> tuple[str | None, str, str | None]:
    suffix = PurePosixPath(relative_path).suffix.casefold()
    if data.startswith(b"%PDF-") or suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError(f"asset file has .pdf suffix but no PDF header: {relative_path}")
        return _extract_pdf(data, limits)
    is_text = suffix in _TEXT_SUFFIXES or media_type.startswith("text/")
    if not is_text:
        return None, "binary", None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"text-like asset is not valid UTF-8: {relative_path}") from error
    if "\x00" in text:
        raise ValueError(f"text-like asset contains NUL bytes: {relative_path}")
    if not text.strip():
        return None, "empty", "utf-8-text/v1"
    if len(text) > limits.max_text_chars_per_file:
        return None, "omitted_limit", None
    return text, "extracted", "utf-8-text/v1"


def _directory_files(root: Path, limits: AssetLimits) -> tuple[tuple[Path, str], ...]:
    found: list[tuple[Path, str]] = []
    win32_paths: dict[str, tuple[str, str, bool, bool]] = {}
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        _require_contained_path(
            current_path,
            root=root,
            description="asset directory path",
            require_exists=True,
        )
        relative_dir = current_path.relative_to(root)
        depth = 0 if relative_dir == Path(".") else len(relative_dir.parts)
        if depth > limits.max_depth:
            raise ValueError(f"asset directory exceeds the {limits.max_depth}-level depth limit")
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            child = current_path / name
            # Exclusions affect snapshot contents, not safety validation.  A
            # malicious checkout must not be able to hide a junction under a
            # normally ignored name such as ``.git``.
            _reject_link_or_reparse(child, description="asset directory path")
            if name in _DEFAULT_EXCLUDED_NAMES:
                continue
            relative = _safe_relative_path(child.relative_to(root).as_posix())
            _register_win32_path(
                win32_paths,
                relative,
                description="asset directory paths",
                leaf_is_file=False,
            )
            _require_contained_path(
                child,
                root=root,
                description="asset directory path",
                require_exists=True,
            )
            kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in sorted(file_names):
            child = current_path / name
            _reject_link_or_reparse(child, description="asset directory path")
            if name in _DEFAULT_EXCLUDED_NAMES:
                continue
            relative = _safe_relative_path(child.relative_to(root).as_posix())
            _register_win32_path(
                win32_paths,
                relative,
                description="asset directory paths",
            )
            _require_contained_path(
                child,
                root=root,
                description="asset directory path",
                require_exists=True,
            )
            found.append((child, relative))
            if len(found) > limits.max_files:
                raise ValueError(f"asset directory exceeds the {limits.max_files}-file limit")
    return tuple(sorted(found, key=lambda item: item[1]))


def _infer_kind(path: Path) -> str:
    if path.is_dir():
        return "repository"
    suffix = path.suffix.casefold()
    if suffix in {".pdf", ".md", ".rst", ".tex", ".txt"}:
        return "document"
    if suffix in {".csv", ".jsonl", ".parquet", ".tsv", ".h5", ".hdf5"}:
        return "dataset"
    return "file"


def snapshot_asset(
    path: str | os.PathLike[str],
    *,
    asset_id: str,
    kind: str = "auto",
    metadata: Mapping[str, Any] | None = None,
    cache: AssetCache | None = None,
    limits: AssetLimits | None = None,
) -> AssetSnapshot:
    """Resolve a local file or directory to a deterministic asset snapshot."""

    asset_id = _asset_id(asset_id)
    selected_limits = limits or AssetLimits()
    source = Path(path)
    _reject_link_or_reparse(source, description="asset root")
    if not source.exists():
        raise FileNotFoundError(f"asset path does not exist: {source}")
    if not (source.is_file() or source.is_dir()):
        raise ValueError(f"asset path must be a regular file or directory: {source}")
    selected_kind = _infer_kind(source) if kind == "auto" else kind
    if selected_kind not in ASSET_KINDS:
        raise ValueError(f"asset kind must be 'auto' or one of {sorted(ASSET_KINDS)}")
    if source.is_dir() and selected_kind in {"document", "file"}:
        raise ValueError(f"asset kind {selected_kind!r} requires a regular file")

    resolved_source = source.resolve(strict=True)
    if source.is_file():
        read_root = resolved_source.parent
        discovered = ((resolved_source, _safe_relative_path(source.name)),)
    else:
        read_root = resolved_source
        discovered = _directory_files(resolved_source, selected_limits)
    if not discovered:
        raise ValueError("asset directory contains no included regular files")

    # Validate the complete inventory before reading or caching any bytes, so
    # a sensitive file found late in sorted order cannot leave a partial cache.
    for _, relative_path in discovered:
        _reject_sensitive_relative_path(relative_path)

    files: list[AssetFile] = []
    total_bytes = 0
    total_text = 0
    for file_path, relative_path in discovered:
        data = _read_regular_file(
            file_path,
            limit=selected_limits.max_file_bytes,
            root=read_root,
        )
        total_bytes += len(data)
        if total_bytes > selected_limits.max_total_bytes:
            raise ValueError(
                f"asset uses {total_bytes} bytes, exceeding the "
                f"{selected_limits.max_total_bytes}-byte total limit"
            )
        digest = hashlib.sha256(data).hexdigest()
        if cache is not None and cache.put(data) != digest:
            raise RuntimeError("asset cache returned a mismatched digest")
        media_type = mimetypes.guess_type(relative_path, strict=False)[0] or "application/octet-stream"
        text, extraction_status, extractor = _extract_file_text(
            relative_path, data, media_type, selected_limits
        )
        total_text += len(text or "")
        if total_text > selected_limits.max_total_text_chars:
            raise ValueError(
                f"asset extraction uses {total_text} characters, exceeding the "
                f"{selected_limits.max_total_text_chars}-character total limit"
            )
        files.append(
            AssetFile(
                relative_path=relative_path,
                size_bytes=len(data),
                sha256=digest,
                media_type=media_type,
                extraction_status=extraction_status,
                extractor=extractor,
                text=text,
            )
        )
    tree = [
        {
            "relative_path": item.relative_path,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
        }
        for item in files
    ]
    content_digest = hashlib.sha256(_canonical(tree)).hexdigest()
    return AssetSnapshot(
        asset_id=asset_id,
        kind=selected_kind,
        content_sha256=content_digest,
        files=tuple(files),
        metadata={} if metadata is None else metadata,
    )


def resolve_assets(
    specs: Sequence[AssetSpec],
    *,
    cache: AssetCache | None = None,
    limits: AssetLimits | None = None,
    max_assets: int = 256,
) -> tuple[AssetSnapshot, ...]:
    """Resolve asset specifications in stable ID order."""

    _positive(max_assets, "max_assets")
    if isinstance(specs, (str, bytes)) or not isinstance(specs, Sequence):
        raise TypeError("asset specs must be an array")
    if not specs:
        raise ValueError("at least one asset spec is required")
    if len(specs) > max_assets:
        raise ValueError(f"asset bundle exceeds the {max_assets}-asset limit")
    ids = [spec.asset_id for spec in specs]
    if len(set(ids)) != len(ids):
        raise ValueError("asset specs contain duplicate asset IDs")
    return tuple(
        snapshot_asset(
            spec.path,
            asset_id=spec.asset_id,
            kind=spec.kind,
            metadata=spec.metadata,
            cache=cache,
            limits=limits,
        )
        for spec in sorted(specs, key=lambda item: item.asset_id)
    )


def asset_bundle_digest(assets: Iterable[AssetSnapshot]) -> str:
    manifests = [asset.to_dict(include_text=False) for asset in assets]
    manifests.sort(key=lambda item: item["asset_id"])
    return hashlib.sha256(_canonical(manifests)).hexdigest()


__all__ = [
    "ASSET_KINDS",
    "ASSET_SCHEMA_VERSION",
    "AssetCache",
    "AssetFile",
    "AssetLimits",
    "AssetSnapshot",
    "AssetSpec",
    "asset_bundle_digest",
    "resolve_assets",
    "snapshot_asset",
]
