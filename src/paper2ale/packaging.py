"""Deterministic, visibility-aware package construction helpers.

The functions in this module intentionally use only the Python standard
library.  They form the small trusted core that turns generated task assets
into the agent, evaluator, and author projections used by ALE.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Iterable, Iterator, Sequence
import zipfile


VISIBILITIES = frozenset({"agent", "evaluator", "author"})
_PROFILE_VISIBILITIES = {
    "agent": frozenset({"agent"}),
    "evaluator": frozenset({"agent", "evaluator"}),
    "author": VISIBILITIES,
}
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
    | {f"com{index}" for index in "¹²³"}
    | {f"lpt{index}" for index in "¹²³"}
)
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MANIFEST_NAME = "MANIFEST.sha256"
_WINDOWS_PORTABLE_MAX_PATH = 259
_ATOMIC_TEMP_NAME_BUDGET = len(".p2a-xxxxxxxx.tmp")


def _validate_relative_posix_path(path: str) -> str:
    """Return *path* after enforcing a strict portable relative-path form."""

    if not isinstance(path, str):
        raise TypeError("package paths must be strings")
    if not path:
        raise ValueError("package paths must not be empty")
    if "\\" in path:
        raise ValueError(f"package path must use POSIX separators: {path!r}")
    if "\x00" in path or any(ord(character) < 32 for character in path):
        raise ValueError(f"package path contains a control character: {path!r}")
    if path.startswith("/") or _WINDOWS_DRIVE.match(path):
        raise ValueError(f"package path must be relative: {path!r}")
    if path.endswith("/"):
        raise ValueError(f"package path must name a file: {path!r}")

    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"package path contains an unsafe component: {path!r}")
    for part in parts:
        if ":" in part:
            raise ValueError(
                f"package path contains a Windows drive/ADS separator: {path!r}"
            )
        if part.endswith((".", " ")):
            raise ValueError(
                f"package path component ends with a Windows-ignored dot or space: {path!r}"
            )
        stem = part.split(".", 1)[0].casefold()
        if stem in _WINDOWS_RESERVED_STEMS:
            raise ValueError(
                f"package path contains a reserved Windows device name: {path!r}"
            )
    return path


def _windows_path_key(path: str) -> str:
    """Return the collision key used by portable Windows package paths."""

    validated = _validate_relative_posix_path(path)
    return "/".join(part.rstrip(". ").casefold() for part in validated.split("/"))


def _windows_path_collisions(
    entries: Iterable[tuple[str, bool]],
) -> list[tuple[str, str]]:
    """Return collisions between Win32-normalized path components.

    Each entry is ``(path, leaf_is_file)``.  Tracking every prefix catches
    case aliases in directory components as well as file-versus-directory
    conflicts, while allowing ordinary siblings in the same directory.
    """

    seen: dict[str, tuple[str, str, bool, bool]] = {}
    collisions: list[tuple[str, str]] = []
    for path, leaf_is_file in entries:
        validated = _validate_relative_posix_path(path)
        parts = validated.split("/")
        conflict: tuple[str, str] | None = None
        for index in range(1, len(parts) + 1):
            literal = "/".join(parts[:index])
            key = "/".join(part.rstrip(". ").casefold() for part in parts[:index])
            component_is_leaf = index == len(parts)
            component_is_file = leaf_is_file and index == len(parts)
            previous = seen.get(key)
            if previous is None:
                seen[key] = (
                    literal,
                    validated,
                    component_is_file,
                    component_is_leaf,
                )
                continue
            (
                previous_literal,
                previous_path,
                previous_is_file,
                previous_is_leaf,
            ) = previous
            if (
                previous_literal != literal
                or previous_is_file
                or component_is_file
                or (previous_is_leaf and component_is_leaf)
            ):
                conflict = (previous_path, validated)
                break
        if conflict is not None:
            collisions.append(conflict)
    return collisions


def _is_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink, junction, or other reparse point."""

    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _ensure_resolved_contained(root_resolved: Path, candidate: Path) -> None:
    """Reject a discovered path whose resolved target escapes *root_resolved*."""

    try:
        candidate.resolve(strict=True).relative_to(root_resolved)
    except (OSError, ValueError) as error:
        raise ValueError(f"path resolves outside package root: {candidate}") from error


def _ensure_windows_path_budget(
    path: Path,
    *,
    context: str,
    reserve_name_chars: int = 0,
) -> None:
    """Fail before a portable build crosses the legacy Win32 path budget."""

    if os.name != "nt":
        return
    rendered = os.path.abspath(os.fspath(path))
    if rendered.startswith("\\\\?\\"):
        return
    length = len(rendered) + reserve_name_chars
    if length > _WINDOWS_PORTABLE_MAX_PATH:
        raise ValueError(
            f"{context} exceeds the portable Windows path budget "
            f"({length} > {_WINDOWS_PORTABLE_MAX_PATH} characters): {rendered}. "
            "Use a shorter --out directory or enable and use extended-length Windows paths."
        )


@dataclass(frozen=True, slots=True)
class BuildFile:
    """One immutable file in a generated task build."""

    path: str
    data: bytes
    visibility: str
    executable: bool = False

    def __post_init__(self) -> None:
        _validate_relative_posix_path(self.path)
        if not isinstance(self.data, bytes):
            raise TypeError("BuildFile.data must be bytes")
        if self.visibility not in VISIBILITIES:
            choices = ", ".join(sorted(VISIBILITIES))
            raise ValueError(f"visibility must be one of: {choices}")
        if not isinstance(self.executable, bool):
            raise TypeError("BuildFile.executable must be bool")


def projection_files(
    files: Iterable[BuildFile], profile: str
) -> tuple[BuildFile, ...]:
    """Return the deterministically ordered files visible to *profile*."""

    try:
        allowed = _PROFILE_VISIBILITIES[profile]
    except KeyError as error:
        choices = ", ".join(sorted(_PROFILE_VISIBILITIES))
        raise ValueError(f"unknown projection profile {profile!r}; use {choices}") from error

    selected: list[BuildFile] = []
    for file in files:
        if not isinstance(file, BuildFile):
            raise TypeError("projection inputs must be BuildFile instances")
        if file.visibility in allowed:
            selected.append(file)
    return tuple(sorted(selected, key=lambda item: item.path))


def ale_local_deployment_files(
    files: Iterable[BuildFile],
    *,
    expected_task_id: str | None = None,
) -> tuple[BuildFile, ...]:
    """Map one task inventory to ALE's local task-source/data layout.

    The returned tree is ready to extract beside an ALE checkout:

    ``tasks/<domain>/<task>/{main.py,task_card.json,README.md}``
        Task discovery source checked into or copied into the ALE repository.

    ``task-data/<domain>/<task>/<variant>/{input,software,reference}``
        Host task data for ``task_data_source: local:<root>/task-data``.  ALE's
        local provider stages ``input`` and ``software`` before the agent and
        ``reference`` only during evaluation.

    Common software and graders are duplicated per variant deliberately.  The
    mapping is deterministic and contains evaluator data, so this deployment
    bundle must be held by the benchmark operator rather than given directly
    to a participant.
    """

    inventory = tuple(files)
    for item in inventory:
        if not isinstance(item, BuildFile):
            raise TypeError("ALE deployment inputs must be BuildFile instances")
    by_path = {item.path: item for item in inventory}
    if len(by_path) != len(inventory):
        raise ValueError("ALE deployment inputs contain duplicate paths")

    try:
        card = json.loads(by_path["task_card.json"].data.decode("utf-8"))
    except KeyError as error:
        raise ValueError("ALE deployment requires task_card.json") from error
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError(f"invalid task_card.json: {error}") from error
    task_identifier = card.get("taskId") if isinstance(card, dict) else None
    if not isinstance(task_identifier, str) or task_identifier.count("/") != 1:
        raise ValueError("task_card.json taskId must be '<domain>/<task>'")
    domain, task_id = task_identifier.split("/", 1)
    _validate_relative_posix_path(f"{domain}/{task_id}")
    if expected_task_id is not None and task_id != expected_task_id:
        raise ValueError(
            f"task-card ID {task_id!r} does not match expected task ID {expected_task_id!r}"
        )

    input_prefix = "input/instances/"
    variants: set[str] = set()
    for path in by_path:
        if path.startswith(input_prefix):
            suffix = path[len(input_prefix) :]
            if "/" in suffix:
                variants.add(suffix.split("/", 1)[0])
    if not variants:
        raise ValueError("ALE deployment requires input/instances/<variant>/ files")

    mapped: list[BuildFile] = []
    mapping: list[dict[str, str]] = []

    def add(source: BuildFile, destination: str) -> None:
        mapped.append(
            BuildFile(
                path=destination,
                data=source.data,
                visibility=source.visibility,
                executable=source.executable,
            )
        )
        mapping.append({"source": source.path, "destination": destination})

    task_source_root = f"tasks/{domain}/{task_id}"
    for source_name, destination_name in (
        ("main.py", "main.py"),
        ("task_card.json", "task_card.json"),
        ("description.md", "README.md"),
    ):
        source = by_path.get(source_name)
        if source is None:
            raise ValueError(f"ALE deployment requires {source_name}")
        add(source, f"{task_source_root}/{destination_name}")

    for variant in sorted(variants):
        variant_root = f"task-data/{domain}/{task_id}/{variant}"
        variant_input_prefix = f"input/instances/{variant}/"
        for source in sorted(inventory, key=lambda item: item.path):
            if source.path.startswith(variant_input_prefix):
                remainder = source.path[len(variant_input_prefix) :]
                add(source, f"{variant_root}/input/{remainder}")
            elif source.path.startswith("software/"):
                add(source, f"{variant_root}/{source.path}")
            elif source.path.startswith(f"reference/instances/{variant}/"):
                # Generated graders use reference/instances/<variant>/... so
                # retain that subpath inside each variant's reference tree.
                add(source, f"{variant_root}/{source.path}")
            elif source.path.startswith("reference/") and not source.path.startswith(
                "reference/instances/"
            ):
                add(source, f"{variant_root}/{source.path}")

    deployment = {
        "schema_version": "paper2ale.ale-local-deployment/v1",
        "task_id": task_identifier,
        "variants": sorted(variants),
        "task_source_root": task_source_root,
        "task_data_root": f"task-data/{domain}/{task_id}",
        "task_data_source": "local:<extracted-root>/task-data",
        "contains_evaluator_reference": True,
        "mapping": sorted(mapping, key=lambda item: (item["destination"], item["source"])),
    }
    mapped.append(
        BuildFile(
            path="DEPLOYMENT.json",
            data=(
                json.dumps(deployment, indent=2, sort_keys=True, allow_nan=False) + "\n"
            ).encode("utf-8"),
            visibility="author",
        )
    )

    duplicates = _casefold_duplicates(mapped)
    if duplicates:
        rendered = ", ".join(f"{first!r}/{second!r}" for first, second in duplicates)
        raise ValueError(f"ALE deployment contains duplicate or case-colliding paths: {rendered}")
    return tuple(sorted(mapped, key=lambda item: item.path))


def _casefold_duplicates(files: Sequence[BuildFile]) -> list[tuple[str, str]]:
    return _windows_path_collisions((file.path, True) for file in files)


def _write_bytes_atomically(path: Path, data: bytes) -> None:
    _ensure_windows_path_budget(path, context="package destination")
    _ensure_windows_path_budget(
        path.parent,
        context="atomic package temporary path",
        reserve_name_chars=1 + _ATOMIC_TEMP_NAME_BUDGET,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=".p2a-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _ensure_destination_is_contained(root: Path, destination: Path) -> None:
    root_resolved = root.resolve()
    destination_resolved = destination.resolve(strict=False)
    try:
        destination_resolved.relative_to(root_resolved)
    except ValueError as error:
        raise ValueError(f"destination escapes projection root: {destination}") from error


def write_projection(
    files: Iterable[BuildFile], root: str | os.PathLike[str], profile: str
) -> tuple[Path, ...]:
    """Write a visibility projection below *root* and return written paths.

    Existing unrelated files are left untouched.  Callers should normally use
    a fresh staging directory; duplicate or case-colliding projected paths are
    rejected instead of being overwritten.
    """

    selected = projection_files(files, profile)
    duplicates = _casefold_duplicates(selected)
    if duplicates:
        rendered = ", ".join(f"{first!r}/{second!r}" for first, second in duplicates)
        raise ValueError(f"projection contains duplicate or case-colliding paths: {rendered}")

    root_path = Path(root)
    if _is_reparse_point(root_path):
        raise ValueError(
            f"projection root must not be a symlink, junction, or reparse point: {root_path}"
        )
    root_path.mkdir(parents=True, exist_ok=True)
    if not root_path.is_dir():
        raise ValueError(f"projection root is not a directory: {root_path}")
    root_resolved = root_path.resolve(strict=True)

    written: list[Path] = []
    for file in selected:
        destination = root_path.joinpath(*file.path.split("/"))
        _ensure_destination_is_contained(root_path, destination)

        current = root_path
        for part in file.path.split("/")[:-1]:
            current = current / part
            if _is_reparse_point(current):
                raise ValueError(
                    f"projection path traverses a symlink, junction, or reparse point: {current}"
                )
            current.mkdir(exist_ok=True)
            if not current.is_dir():
                raise ValueError(f"projection parent is not a directory: {current}")
            _ensure_resolved_contained(root_resolved, current)
        if _is_reparse_point(destination):
            raise ValueError(
                f"projection destination is a symlink, junction, or reparse point: {destination}"
            )
        if destination.exists() and not destination.is_file():
            raise ValueError(f"projection destination is not a file: {destination}")

        _write_bytes_atomically(destination, file.data)
        os.chmod(destination, 0o755 if file.executable else 0o644)
        written.append(destination)
    return tuple(written)


def _iter_regular_files(root: Path, *, exclude: frozenset[str] = frozenset()) -> Iterator[tuple[str, Path]]:
    if _is_reparse_point(root):
        raise ValueError(
            f"package root must not be a symlink, junction, or reparse point: {root}"
        )
    if not root.is_dir():
        raise ValueError(f"package root is not a directory: {root}")
    root_resolved = root.resolve(strict=True)

    discovered: list[tuple[str, Path]] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        if _is_reparse_point(current_path):
            raise ValueError(
                f"package tree traverses a symlink, junction, or reparse point: {current_path}"
            )
        _ensure_resolved_contained(root_resolved, current_path)
        for name in list(directory_names):
            candidate = current_path / name
            if _is_reparse_point(candidate):
                raise ValueError(
                    f"package tree contains a symlink, junction, or reparse point: {candidate}"
                )
            _ensure_resolved_contained(root_resolved, candidate)
        for name in file_names:
            candidate = current_path / name
            if _is_reparse_point(candidate):
                raise ValueError(
                    f"package tree contains a symlink, junction, or reparse point: {candidate}"
                )
            if not candidate.is_file():
                raise ValueError(f"package tree contains a non-regular file: {candidate}")
            _ensure_resolved_contained(root_resolved, candidate)
            relative = candidate.relative_to(root).as_posix()
            _validate_relative_posix_path(relative)
            if relative not in exclude:
                discovered.append((relative, candidate))
    discovered.sort(key=lambda item: item[0])
    collisions = _windows_path_collisions((relative, True) for relative, _ in discovered)
    if collisions:
        rendered = ", ".join(
            f"{first!r}/{second!r}" for first, second in collisions
        )
        raise ValueError(f"package tree contains Win32-colliding paths: {rendered}")
    yield from discovered


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(root: str | os.PathLike[str]) -> str:
    """Write and return a deterministic ``MANIFEST.sha256`` document."""

    root_path = Path(root)
    entries = list(_iter_regular_files(root_path, exclude=frozenset({MANIFEST_NAME})))
    lines = [f"{_sha256_file(path)}  ./{relative}" for relative, path in entries]
    document = "\n".join(lines)
    if lines:
        document += "\n"
    _write_bytes_atomically(root_path / MANIFEST_NAME, document.encode("utf-8"))
    os.chmod(root_path / MANIFEST_NAME, 0o644)
    return document


def write_deterministic_zip(
    source_dir: str | os.PathLike[str],
    zip_path: str | os.PathLike[str],
    *,
    executable_paths: Iterable[str] = (),
) -> str:
    """Archive *source_dir* reproducibly and return the ZIP's SHA-256 digest."""

    root_path = Path(source_dir)
    destination_path = Path(zip_path)
    root_resolved = root_path.resolve()
    destination_resolved = destination_path.resolve(strict=False)
    try:
        destination_resolved.relative_to(root_resolved)
    except ValueError:
        pass
    else:
        raise ValueError("ZIP destination must be outside the archived root")

    executable_set = {_validate_relative_posix_path(path) for path in executable_paths}
    entries = list(_iter_regular_files(root_path))
    entry_names = {relative for relative, _ in entries}
    unknown_executables = executable_set - entry_names
    if unknown_executables:
        names = ", ".join(sorted(unknown_executables))
        raise ValueError(f"executable paths do not exist in package root: {names}")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse_point(destination_path):
        raise ValueError(
            f"ZIP destination must not be a symlink, junction, or reparse point: {destination_path}"
        )
    _ensure_windows_path_budget(destination_path, context="ZIP destination")
    _ensure_windows_path_budget(
        destination_path.parent,
        context="ZIP temporary path",
        reserve_name_chars=1 + _ATOMIC_TEMP_NAME_BUDGET,
    )

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination_path.parent,
            prefix=".p2a-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name

        with zipfile.ZipFile(
            temporary_name,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            for relative, source in entries:
                source_mode = source.stat().st_mode
                executable = relative in executable_set or bool(source_mode & 0o111)
                permissions = 0o755 if executable else 0o644
                info = zipfile.ZipInfo(relative, date_time=_FIXED_ZIP_TIMESTAMP)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | permissions) << 16
                info.internal_attr = 0
                info.extra = b""
                info.comment = b""
                info.file_size = source.stat().st_size
                with source.open("rb") as reader, archive.open(info, mode="w") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)

        os.replace(temporary_name, destination_path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return _sha256_file(destination_path)


def write_deterministic_zip_from_files(
    files: Iterable[BuildFile],
    zip_path: str | os.PathLike[str],
) -> str:
    """Archive an already projected inventory without materializing deep paths.

    This is used for ALE layouts whose portable archive member names may exceed
    legacy Windows host-path limits.  The embedded manifest and ZIP metadata are
    identical in form to directory-backed packages.
    """

    inventory = tuple(files)
    if any(not isinstance(item, BuildFile) for item in inventory):
        raise TypeError("ZIP inventory must contain only BuildFile values")
    if not inventory:
        raise ValueError("ZIP inventory must contain at least one file")
    if any(item.path == MANIFEST_NAME for item in inventory):
        raise ValueError(f"ZIP inventory must not supply {MANIFEST_NAME}")
    duplicates = _casefold_duplicates(inventory)
    if duplicates:
        rendered = ", ".join(f"{first!r}/{second!r}" for first, second in duplicates)
        raise ValueError(f"ZIP inventory contains duplicate or case-colliding paths: {rendered}")

    ordered = tuple(sorted(inventory, key=lambda item: item.path))
    manifest_lines = [
        f"{hashlib.sha256(item.data).hexdigest()}  ./{item.path}"
        for item in ordered
    ]
    manifest = ("\n".join(manifest_lines) + ("\n" if manifest_lines else "")).encode(
        "utf-8"
    )
    entries = (*ordered, BuildFile(MANIFEST_NAME, manifest, "author"))

    destination_path = Path(zip_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse_point(destination_path):
        raise ValueError(
            f"ZIP destination must not be a symlink, junction, or reparse point: {destination_path}"
        )
    _ensure_windows_path_budget(destination_path, context="ZIP destination")
    _ensure_windows_path_budget(
        destination_path.parent,
        context="ZIP temporary path",
        reserve_name_chars=1 + _ATOMIC_TEMP_NAME_BUDGET,
    )
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination_path.parent,
            prefix=".p2a-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
        with zipfile.ZipFile(
            temporary_name,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            for item in sorted(entries, key=lambda entry: entry.path):
                permissions = 0o755 if item.executable else 0o644
                info = zipfile.ZipInfo(item.path, date_time=_FIXED_ZIP_TIMESTAMP)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | permissions) << 16
                info.internal_attr = 0
                info.extra = b""
                info.comment = b""
                info.file_size = len(item.data)
                archive.writestr(info, item.data)
        os.replace(temporary_name, destination_path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return _sha256_file(destination_path)


# Discoverable aliases for callers that prefer a build-oriented name.
build_deterministic_zip = write_deterministic_zip
build_zip = write_deterministic_zip


__all__ = [
    "BuildFile",
    "MANIFEST_NAME",
    "VISIBILITIES",
    "ale_local_deployment_files",
    "build_deterministic_zip",
    "build_zip",
    "projection_files",
    "write_deterministic_zip",
    "write_deterministic_zip_from_files",
    "write_manifest",
    "write_projection",
]
