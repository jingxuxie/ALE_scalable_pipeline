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
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MANIFEST_NAME = "MANIFEST.sha256"


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
    return path


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
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str]] = []
    for file in files:
        key = file.path.casefold()
        if key in seen:
            duplicates.append((seen[key], file.path))
        else:
            seen[key] = file.path
    return duplicates


def _write_bytes_atomically(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
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
    if root_path.exists() and root_path.is_symlink():
        raise ValueError(f"projection root must not be a symlink: {root_path}")
    root_path.mkdir(parents=True, exist_ok=True)
    if not root_path.is_dir():
        raise ValueError(f"projection root is not a directory: {root_path}")

    written: list[Path] = []
    for file in selected:
        destination = root_path.joinpath(*file.path.split("/"))
        _ensure_destination_is_contained(root_path, destination)

        current = root_path
        for part in file.path.split("/")[:-1]:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError(f"projection path traverses a symlink: {current}")
            current.mkdir(exist_ok=True)
            if not current.is_dir():
                raise ValueError(f"projection parent is not a directory: {current}")
        if destination.exists() and destination.is_symlink():
            raise ValueError(f"projection destination is a symlink: {destination}")
        if destination.exists() and not destination.is_file():
            raise ValueError(f"projection destination is not a file: {destination}")

        _write_bytes_atomically(destination, file.data)
        os.chmod(destination, 0o755 if file.executable else 0o644)
        written.append(destination)
    return tuple(written)


def _iter_regular_files(root: Path, *, exclude: frozenset[str] = frozenset()) -> Iterator[tuple[str, Path]]:
    if root.is_symlink():
        raise ValueError(f"package root must not be a symlink: {root}")
    if not root.is_dir():
        raise ValueError(f"package root is not a directory: {root}")

    discovered: list[tuple[str, Path]] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(directory_names):
            candidate = current_path / name
            if candidate.is_symlink():
                raise ValueError(f"package tree contains a symlink: {candidate}")
        for name in file_names:
            candidate = current_path / name
            if candidate.is_symlink():
                raise ValueError(f"package tree contains a symlink: {candidate}")
            if not candidate.is_file():
                raise ValueError(f"package tree contains a non-regular file: {candidate}")
            relative = candidate.relative_to(root).as_posix()
            _validate_relative_posix_path(relative)
            if relative not in exclude:
                discovered.append((relative, candidate))
    discovered.sort(key=lambda item: item[0])
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
    if destination_path.exists() and destination_path.is_symlink():
        raise ValueError(f"ZIP destination must not be a symlink: {destination_path}")

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination_path.parent,
            prefix=f".{destination_path.name}.",
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
    "write_manifest",
    "write_projection",
]
