"""Bounded ingestion of local text and PDF sources.

Local paths are an operator concern and never enter provider requests.  The
provider sees only pinned source metadata, byte digests, deterministic
locators, extractor identity, and extracted text.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_MAX_SOURCE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_TOTAL_SOURCE_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_EVIDENCE_CHARS = 2_000_000
DEFAULT_MAX_TOTAL_EVIDENCE_CHARS = 4_000_000
DEFAULT_MAX_PDF_PAGES = 1_000
DEFAULT_CHUNK_CHARS = 20_000

_SOURCE_REQUIRED = frozenset(
    {"id", "kind", "uri", "version", "license", "visibility"}
)
_SOURCE_OPTIONAL = frozenset({"sha256", "citation", "retrieved_at"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    source_id: str
    locator: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "locator": self.locator,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class IngestedSource:
    local_path: str
    source_ref: Mapping[str, Any]
    media_type: str
    extractor: str
    size_bytes: int
    chunks: tuple[EvidenceChunk, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ref", MappingProxyType(dict(self.source_ref)))

    def source_dict(self) -> dict[str, Any]:
        return dict(self.source_ref)


def _positive_integer(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _strict_json_loads(text: str, *, context: str) -> Any:
    def reject_constant(token: str) -> None:
        raise ValueError(f"{context} contains forbidden numeric constant {token}")

    def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{context} contains duplicate object key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=object_without_duplicates,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"{context} is not valid JSON: {error.msg}") from error


def load_json_value(path: str | os.PathLike[str], *, name: str = "JSON file") -> Any:
    """Load strict JSON, rejecting duplicate keys and non-finite values."""

    json_path = Path(path)
    try:
        text = json_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{name} {json_path} is not valid UTF-8") from error
    return _strict_json_loads(text, context=f"{name} {json_path}")


def load_json_object(path: str | os.PathLike[str], *, name: str = "JSON file") -> dict[str, Any]:
    """Load a strict JSON object, rejecting duplicate keys and non-finite values."""

    json_path = Path(path)
    value = load_json_value(json_path, name=name)
    if not isinstance(value, dict):
        raise ValueError(f"{name} {json_path} must contain one JSON object")
    return value


def _strict_json_copy(value: Mapping[str, Any], *, name: str) -> dict[str, Any]:
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
    copied = _strict_json_loads(encoded, context=name)
    assert isinstance(copied, dict)
    return copied


def normalize_source_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the exact source-ref fields accepted by project schema v1."""

    source = _strict_json_copy(metadata, name="source metadata")
    missing = sorted(_SOURCE_REQUIRED - set(source))
    if missing:
        raise ValueError(f"source metadata is missing required fields: {', '.join(missing)}")
    unknown = sorted(set(source) - _SOURCE_REQUIRED - _SOURCE_OPTIONAL)
    if unknown:
        raise ValueError(f"source metadata contains unknown fields: {', '.join(unknown)}")
    for key in sorted(_SOURCE_REQUIRED | ({"citation", "retrieved_at"} & set(source))):
        value = source[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"source metadata field {key!r} must be a nonempty string")
    digest = source.get("sha256")
    if digest is not None and (
        not isinstance(digest, str) or _SHA256.fullmatch(digest) is None
    ):
        raise ValueError("source metadata sha256 must be 64 lowercase hexadecimal characters")
    return source


def load_source_metadata(path: str | os.PathLike[str]) -> dict[str, Any]:
    return normalize_source_metadata(load_json_object(path, name="source metadata"))


def _read_regular_file(path: Path, *, max_bytes: int) -> tuple[bytes, str]:
    if path.is_symlink():
        raise ValueError(f"source path must not be a symbolic link: {path}")
    try:
        with path.open("rb") as stream:
            mode = os.fstat(stream.fileno()).st_mode
            if not stat.S_ISREG(mode):
                raise ValueError(f"source path is not a regular file: {path}")
            data = stream.read(max_bytes + 1)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"source file does not exist: {path}") from error
    if len(data) > max_bytes:
        raise ValueError(f"source file exceeds the {max_bytes}-byte limit: {path}")
    if not data:
        raise ValueError(f"source file is empty: {path}")
    return data, str(path.resolve())


def _split_text_chunks(
    source_id: str,
    text: str,
    *,
    locator_prefix: str,
    chunk_chars: int,
) -> tuple[EvidenceChunk, ...]:
    """Split text deterministically without truncating long logical lines."""

    chunks: list[EvidenceChunk] = []
    lines = text.splitlines(keepends=True)
    if not lines:
        return ()
    pending: list[str] = []
    pending_start = 1
    pending_chars = 0

    def flush(end_line: int) -> None:
        nonlocal pending, pending_chars, pending_start
        if not pending:
            return
        locator = (
            f"{locator_prefix}{pending_start}"
            if pending_start == end_line
            else f"{locator_prefix}{pending_start}-{end_line}"
        )
        chunks.append(EvidenceChunk(source_id, locator, "".join(pending)))
        pending = []
        pending_chars = 0

    for line_number, line in enumerate(lines, start=1):
        if len(line) > chunk_chars:
            flush(line_number - 1)
            for offset in range(0, len(line), chunk_chars):
                fragment = line[offset : offset + chunk_chars]
                chunks.append(
                    EvidenceChunk(
                        source_id,
                        f"{locator_prefix}{line_number}:chars:{offset + 1}-{offset + len(fragment)}",
                        fragment,
                    )
                )
            pending_start = line_number + 1
            continue
        if pending and pending_chars + len(line) > chunk_chars:
            flush(line_number - 1)
            pending_start = line_number
        if not pending:
            pending_start = line_number
        pending.append(line)
        pending_chars += len(line)
    flush(len(lines))
    return tuple(chunks)


def _extract_text(
    data: bytes,
    source_id: str,
    *,
    max_evidence_chars: int,
    chunk_chars: int,
) -> tuple[tuple[EvidenceChunk, ...], str]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("text source must be valid UTF-8") from error
    if "\x00" in text:
        raise ValueError("text source contains NUL bytes and appears to be binary")
    if not text.strip():
        raise ValueError("text source contains no non-whitespace content")
    if len(text) > max_evidence_chars:
        raise ValueError(
            f"text extraction exceeds the {max_evidence_chars}-character limit"
        )
    return (
        _split_text_chunks(
            source_id,
            text,
            locator_prefix="lines:",
            chunk_chars=chunk_chars,
        ),
        "utf-8-text/v1",
    )


def _extract_pdf(
    data: bytes,
    source_id: str,
    *,
    max_evidence_chars: int,
    max_pdf_pages: int,
    chunk_chars: int,
) -> tuple[tuple[EvidenceChunk, ...], str]:
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError(
            "PDF ingestion requires the 'pypdf' package; reinstall Paper2ALE "
            "dependencies or provide a UTF-8 text extraction with the same pinned metadata"
        ) from error

    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=True)
    except Exception as error:
        raise ValueError(f"PDF could not be parsed safely: {error}") from error
    if reader.is_encrypted:
        raise ValueError("encrypted PDFs are not supported; decrypt the source explicitly first")
    page_count = len(reader.pages)
    if page_count > max_pdf_pages:
        raise ValueError(f"PDF has {page_count} pages, exceeding the {max_pdf_pages}-page limit")

    chunks: list[EvidenceChunk] = []
    total_chars = 0
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as error:
            raise ValueError(f"PDF text extraction failed on page {page_number}: {error}") from error
        if not page_text.strip():
            continue
        total_chars += len(page_text)
        if total_chars > max_evidence_chars:
            raise ValueError(
                f"PDF extraction exceeds the {max_evidence_chars}-character limit"
            )
        if len(page_text) <= chunk_chars:
            chunks.append(EvidenceChunk(source_id, f"page:{page_number}", page_text))
        else:
            for offset in range(0, len(page_text), chunk_chars):
                fragment = page_text[offset : offset + chunk_chars]
                chunks.append(
                    EvidenceChunk(
                        source_id,
                        f"page:{page_number}:chars:{offset + 1}-{offset + len(fragment)}",
                        fragment,
                    )
                )
    if not chunks:
        raise ValueError(
            "PDF contains no extractable text; run OCR explicitly and ingest the resulting UTF-8 text"
        )
    try:
        version = importlib.metadata.version("pypdf")
    except importlib.metadata.PackageNotFoundError:
        version = str(getattr(pypdf, "__version__", "unknown"))
    return tuple(chunks), f"pypdf/{version}"


def ingest_source(
    path: str | os.PathLike[str],
    metadata: Mapping[str, Any],
    *,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_evidence_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
    max_pdf_pages: int = DEFAULT_MAX_PDF_PAGES,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
) -> IngestedSource:
    """Read, hash, verify, and extract one local source without truncation."""

    _positive_integer(max_source_bytes, "max_source_bytes")
    _positive_integer(max_evidence_chars, "max_evidence_chars")
    _positive_integer(max_pdf_pages, "max_pdf_pages")
    _positive_integer(chunk_chars, "chunk_chars")
    source = normalize_source_metadata(metadata)
    source_path = Path(path)
    data, resolved_path = _read_regular_file(source_path, max_bytes=max_source_bytes)
    digest = hashlib.sha256(data).hexdigest()
    expected_digest = source.get("sha256")
    if expected_digest is not None and expected_digest != digest:
        raise ValueError(
            f"source sha256 mismatch for {source_path}: expected {expected_digest}, got {digest}"
        )
    source["sha256"] = digest

    pdf_header = b"%PDF-" in data[:1024]
    pdf_suffix = source_path.suffix.casefold() == ".pdf"
    if pdf_suffix and not pdf_header:
        raise ValueError(f"source has a .pdf suffix but no PDF header: {source_path}")
    if pdf_header:
        chunks, extractor = _extract_pdf(
            data,
            str(source["id"]),
            max_evidence_chars=max_evidence_chars,
            max_pdf_pages=max_pdf_pages,
            chunk_chars=chunk_chars,
        )
        media_type = "application/pdf"
    else:
        chunks, extractor = _extract_text(
            data,
            str(source["id"]),
            max_evidence_chars=max_evidence_chars,
            chunk_chars=chunk_chars,
        )
        media_type = "text/plain; charset=utf-8"
    return IngestedSource(
        local_path=resolved_path,
        source_ref=source,
        media_type=media_type,
        extractor=extractor,
        size_bytes=len(data),
        chunks=chunks,
    )


def ingest_sources(
    paths: Sequence[str | os.PathLike[str]],
    metadata: Sequence[Mapping[str, Any]],
    *,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_total_source_bytes: int = DEFAULT_MAX_TOTAL_SOURCE_BYTES,
    max_evidence_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
    max_total_evidence_chars: int = DEFAULT_MAX_TOTAL_EVIDENCE_CHARS,
    max_pdf_pages: int = DEFAULT_MAX_PDF_PAGES,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
) -> tuple[IngestedSource, ...]:
    """Ingest paired paths/metadata and return a stable source-id ordering."""

    if isinstance(paths, (str, bytes)) or isinstance(metadata, Mapping):
        raise TypeError("paths and metadata must be sequences")
    if not paths:
        raise ValueError("at least one local source is required")
    if len(paths) != len(metadata):
        raise ValueError("each local source requires one --metadata object")
    _positive_integer(max_total_source_bytes, "max_total_source_bytes")
    _positive_integer(max_total_evidence_chars, "max_total_evidence_chars")
    normalized_metadata = [
        normalize_source_metadata(item) for item in metadata
    ]
    metadata_ids = [str(item["id"]) for item in normalized_metadata]
    if len(set(metadata_ids)) != len(metadata_ids):
        duplicate = next(
            source_id
            for index, source_id in enumerate(metadata_ids)
            if source_id in metadata_ids[:index]
        )
        raise ValueError(f"duplicate source metadata id {duplicate!r}")
    ingested: list[IngestedSource] = []
    total_bytes = 0
    total_chars = 0
    for path, source_metadata in zip(paths, normalized_metadata, strict=True):
        source = ingest_source(
            path,
            source_metadata,
            max_source_bytes=max_source_bytes,
            max_evidence_chars=max_evidence_chars,
            max_pdf_pages=max_pdf_pages,
            chunk_chars=chunk_chars,
        )
        total_bytes += source.size_bytes
        total_chars += sum(len(chunk.text) for chunk in source.chunks)
        if total_bytes > max_total_source_bytes:
            raise ValueError(
                f"source bundle uses {total_bytes} bytes, exceeding the "
                f"{max_total_source_bytes}-byte total limit"
            )
        if total_chars > max_total_evidence_chars:
            raise ValueError(
                f"source bundle extraction uses {total_chars} characters, exceeding "
                f"the {max_total_evidence_chars}-character total limit"
            )
        ingested.append(source)
    return tuple(sorted(ingested, key=lambda item: str(item.source_ref["id"])))


def source_bundle(sources: Iterable[IngestedSource]) -> list[dict[str, Any]]:
    return [source.source_dict() for source in sources]


__all__ = [
    "DEFAULT_CHUNK_CHARS",
    "DEFAULT_MAX_EVIDENCE_CHARS",
    "DEFAULT_MAX_PDF_PAGES",
    "DEFAULT_MAX_SOURCE_BYTES",
    "DEFAULT_MAX_TOTAL_SOURCE_BYTES",
    "DEFAULT_MAX_TOTAL_EVIDENCE_CHARS",
    "EvidenceChunk",
    "IngestedSource",
    "ingest_source",
    "ingest_sources",
    "load_json_object",
    "load_json_value",
    "load_source_metadata",
    "normalize_source_metadata",
    "source_bundle",
]
