"""Leakage, manifest, and archive safety checks for generated ALE packages."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Iterable
import zipfile

from .packaging import BuildFile, MANIFEST_NAME, _validate_relative_posix_path


DEFAULT_MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
# Backward-compatible constant name for early callers.
DEFAULT_MAX_UNCOMPRESSED_SIZE = DEFAULT_MAX_UNCOMPRESSED_BYTES
_MANIFEST_LINE = re.compile(r"^([0-9a-f]{64})  \./(.+)$")
_PRIVATE_PATH_TOKENS = frozenset(
    {
        "answer_key",
        "evaluator",
        "evaluator_only",
        "grader",
        "grading",
        "hidden",
        "private",
        "reference",
        "reference_output",
        "test_targets",
    }
)


@dataclass(frozen=True, slots=True, order=True)
class ValidationIssue:
    """One deterministic, machine-readable validation finding."""

    code: str
    message: str
    path: str | None = None


class PackageValidationError(ValueError):
    """Raised when an archive or package fails a rejecting validation API."""

    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(sorted(issues, key=_issue_sort_key))
        rendered = "; ".join(
            f"{issue.code}{f' [{issue.path}]' if issue.path else ''}: {issue.message}"
            for issue in self.issues
        )
        super().__init__(rendered or "package validation failed")


def _issue_sort_key(issue: ValidationIssue) -> tuple[str, str, str]:
    return (issue.path or "", issue.code, issue.message)


def _issue(code: str, message: str, path: str | None = None) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, path=path)


def _normalized_private_sentinels(
    sentinels: Iterable[bytes | str],
) -> tuple[bytes, ...]:
    normalized: list[bytes] = []
    for sentinel in sentinels:
        if isinstance(sentinel, str):
            value = sentinel.encode("utf-8")
        elif isinstance(sentinel, bytes):
            value = sentinel
        else:
            raise TypeError("private sentinels must be bytes or strings")
        if not value:
            raise ValueError("private sentinels must not be empty")
        normalized.append(value)
    return tuple(normalized)


def _looks_private(path: str) -> bool:
    for part in path.split("/"):
        stem = part.rsplit(".", 1)[0]
        token = re.sub(r"[^a-z0-9]+", "_", stem.casefold()).strip("_")
        if token in _PRIVATE_PATH_TOKENS:
            return True
        if token.startswith("reference_") or token.startswith("evaluator_"):
            return True
    return False


def audit_visibility(
    files: Iterable[BuildFile], private_sentinels: Iterable[bytes | str] = ()
) -> tuple[ValidationIssue, ...]:
    """Audit build-file partitioning and return structured findings."""

    materialized = tuple(files)
    for file in materialized:
        if not isinstance(file, BuildFile):
            raise TypeError("visibility audit inputs must be BuildFile instances")
    sentinels = _normalized_private_sentinels(private_sentinels)

    issues: list[ValidationIssue] = []
    seen: dict[str, BuildFile] = {}
    for file in materialized:
        folded = file.path.casefold()
        previous = seen.get(folded)
        if previous is not None:
            issues.append(
                _issue(
                    "conflicting_path",
                    f"path conflicts with {previous.path!r}; package paths must be unique case-insensitively",
                    file.path,
                )
            )
        else:
            seen[folded] = file

        if not file.data:
            issues.append(_issue("empty_data", "required build file has no data", file.path))
        if file.visibility == "agent" and _looks_private(file.path):
            issues.append(
                _issue(
                    "private_path_visible_to_agent",
                    "evaluator/reference-looking path is marked agent-visible",
                    file.path,
                )
            )
        if file.visibility == "agent":
            for index, sentinel in enumerate(sentinels):
                if sentinel in file.data:
                    issues.append(
                        _issue(
                            "private_sentinel_leak",
                            f"agent-visible data contains private sentinel #{index + 1}",
                            file.path,
                        )
                    )
    return tuple(sorted(issues, key=_issue_sort_key))


def _zip_member_path(name: str, is_directory: bool) -> str:
    candidate = name[:-1] if is_directory and name.endswith("/") else name
    return _validate_relative_posix_path(candidate)


def inspect_zip(
    archive_path: str | os.PathLike[str],
    *,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> tuple[ValidationIssue, ...]:
    """Return all detectable structural ZIP safety findings."""

    if not isinstance(max_uncompressed_bytes, int) or max_uncompressed_bytes < 0:
        raise ValueError("max_uncompressed_bytes must be a non-negative integer")

    path = Path(archive_path)
    issues: list[ValidationIssue] = []
    if not path.is_file():
        return (_issue("zip_missing", "ZIP archive does not exist", str(path)),)

    try:
        archive = zipfile.ZipFile(path, mode="r")
    except (OSError, zipfile.BadZipFile) as error:
        return (_issue("invalid_zip", str(error), str(path)),)

    seen: dict[str, str] = {}
    total_size = 0
    try:
        for info in archive.infolist():
            is_directory = info.is_dir() or info.filename.endswith("/")
            try:
                member_path = _zip_member_path(info.filename, is_directory)
            except (TypeError, ValueError) as error:
                issues.append(_issue("unsafe_zip_path", str(error), info.filename))
                member_path = info.filename

            folded = member_path.casefold()
            previous = seen.get(folded)
            if previous is not None:
                issues.append(
                    _issue(
                        "duplicate_zip_member",
                        f"member conflicts with {previous!r}",
                        info.filename,
                    )
                )
            else:
                seen[folded] = info.filename

            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(unix_mode):
                issues.append(
                    _issue("zip_symlink", "symbolic links are not allowed", info.filename)
                )
            elif unix_mode:
                file_type = stat.S_IFMT(unix_mode)
                allowed_type = stat.S_IFDIR if is_directory else stat.S_IFREG
                if file_type not in {0, allowed_type}:
                    issues.append(
                        _issue(
                            "zip_special_file",
                            "non-regular archive members are not allowed",
                            info.filename,
                        )
                    )

            total_size += info.file_size
        if total_size > max_uncompressed_bytes:
            issues.append(
                _issue(
                    "zip_too_large",
                    f"total uncompressed size {total_size} exceeds limit {max_uncompressed_bytes}",
                    str(path),
                )
            )
    finally:
        archive.close()
    return tuple(sorted(issues, key=_issue_sort_key))


def validate_zip(
    path: str | os.PathLike[str],
    *,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> tuple[ValidationIssue, ...]:
    """Return structured findings for an unsafe or malformed ZIP archive."""

    return inspect_zip(
        path, max_uncompressed_bytes=max_uncompressed_bytes
    )


def assert_valid_zip(
    path: str | os.PathLike[str],
    *,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> None:
    """Reject an unsafe ZIP archive by raising ``PackageValidationError``."""

    issues = validate_zip(
        path, max_uncompressed_bytes=max_uncompressed_bytes
    )
    if issues:
        raise PackageValidationError(issues)


validate_zip_archive = validate_zip


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_package_files(root: Path) -> tuple[dict[str, Path], list[ValidationIssue]]:
    files: dict[str, Path] = {}
    issues: list[ValidationIssue] = []
    casefolded: dict[str, str] = {}
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory_name in list(directory_names):
            candidate = current_path / directory_name
            if candidate.is_symlink():
                relative = candidate.relative_to(root).as_posix()
                issues.append(_issue("package_symlink", "symbolic links are not allowed", relative))
                directory_names.remove(directory_name)
        for file_name in file_names:
            candidate = current_path / file_name
            relative = candidate.relative_to(root).as_posix()
            try:
                _validate_relative_posix_path(relative)
            except (TypeError, ValueError) as error:
                issues.append(_issue("unsafe_package_path", str(error), relative))
                continue
            if candidate.is_symlink():
                issues.append(_issue("package_symlink", "symbolic links are not allowed", relative))
                continue
            if not candidate.is_file():
                issues.append(
                    _issue("package_special_file", "non-regular files are not allowed", relative)
                )
                continue
            folded = relative.casefold()
            if folded in casefolded:
                issues.append(
                    _issue(
                        "conflicting_package_path",
                        f"path conflicts with {casefolded[folded]!r}",
                        relative,
                    )
                )
            else:
                casefolded[folded] = relative
            files[relative] = candidate
    return files, issues


def validate_package_dir(
    root: str | os.PathLike[str],
) -> tuple[ValidationIssue, ...]:
    """Validate path safety and every hash in ``MANIFEST.sha256``."""

    root_path = Path(root)
    if not root_path.exists():
        return (_issue("package_missing", "package directory does not exist", str(root_path)),)
    if root_path.is_symlink():
        return (_issue("package_symlink", "package root must not be a symlink", str(root_path)),)
    if not root_path.is_dir():
        return (_issue("package_not_directory", "package root is not a directory", str(root_path)),)

    actual, issues = _collect_package_files(root_path)
    manifest_path = root_path / MANIFEST_NAME
    if MANIFEST_NAME not in actual:
        issues.append(_issue("manifest_missing", f"missing {MANIFEST_NAME}", MANIFEST_NAME))
        return tuple(sorted(issues, key=_issue_sort_key))

    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        issues.append(_issue("manifest_unreadable", str(error), MANIFEST_NAME))
        return tuple(sorted(issues, key=_issue_sort_key))

    expected: dict[str, str] = {}
    expected_casefold: dict[str, str] = {}
    listed_order: list[str] = []
    for line_number, line in enumerate(manifest_text.splitlines(), start=1):
        match = _MANIFEST_LINE.fullmatch(line)
        if not match:
            issues.append(
                _issue(
                    "manifest_format",
                    f"invalid manifest line {line_number}",
                    MANIFEST_NAME,
                )
            )
            continue
        digest, relative = match.groups()
        try:
            _validate_relative_posix_path(relative)
        except (TypeError, ValueError) as error:
            issues.append(_issue("unsafe_manifest_path", str(error), relative))
            continue
        if relative == MANIFEST_NAME:
            issues.append(
                _issue("manifest_self_reference", "manifest must not hash itself", relative)
            )
            continue
        folded = relative.casefold()
        if folded in expected_casefold:
            issues.append(
                _issue(
                    "duplicate_manifest_path",
                    f"path conflicts with {expected_casefold[folded]!r}",
                    relative,
                )
            )
            continue
        expected_casefold[folded] = relative
        expected[relative] = digest
        listed_order.append(relative)

    if listed_order != sorted(listed_order):
        issues.append(
            _issue("manifest_order", "manifest entries are not sorted", MANIFEST_NAME)
        )

    actual_without_manifest = {
        relative: path for relative, path in actual.items() if relative != MANIFEST_NAME
    }
    for relative, expected_digest in expected.items():
        path = actual_without_manifest.get(relative)
        if path is None:
            issues.append(_issue("manifest_file_missing", "listed file is missing", relative))
            continue
        try:
            actual_digest = _sha256_file(path)
        except OSError as error:
            issues.append(_issue("package_file_unreadable", str(error), relative))
            continue
        if actual_digest != expected_digest:
            issues.append(
                _issue(
                    "checksum_mismatch",
                    f"expected {expected_digest}, got {actual_digest}",
                    relative,
                )
            )

    for relative in sorted(set(actual_without_manifest) - set(expected)):
        issues.append(_issue("unmanifested_file", "file is not listed in manifest", relative))

    return tuple(sorted(issues, key=_issue_sort_key))


def assert_valid_package_dir(root: str | os.PathLike[str]) -> None:
    """Reject a package directory when ``validate_package_dir`` finds issues."""

    issues = validate_package_dir(root)
    if issues:
        raise PackageValidationError(issues)


__all__ = [
    "DEFAULT_MAX_UNCOMPRESSED_BYTES",
    "DEFAULT_MAX_UNCOMPRESSED_SIZE",
    "PackageValidationError",
    "ValidationIssue",
    "assert_valid_package_dir",
    "assert_valid_zip",
    "audit_visibility",
    "inspect_zip",
    "validate_package_dir",
    "validate_zip",
    "validate_zip_archive",
]
