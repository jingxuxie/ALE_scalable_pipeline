"""Deterministic project compiler.

The upstream extraction layer may be probabilistic.  From a validated project
manifest onward, this module is deliberately deterministic: task instances,
visibility projections, manifests, archives, and build identity are functions
of pinned inputs and a master seed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import uuid
from typing import Any, Iterable, Mapping
import zipfile

from . import __version__
from .difficulty import (
    apply_difficulty_override,
    resolve_task_difficulty,
    verify_consumption_manifest,
)
from .ids import sha256_bytes, sha256_file, stable_id, stage_key
from .packaging import (
    BuildFile,
    MANIFEST_NAME,
    ale_local_deployment_files,
    projection_files,
    write_deterministic_zip,
    write_manifest,
    write_projection,
)
from .schema import canonical_json_bytes, load_project, require_valid_project, validate_project
from .state import StageStateStore
from .task_families import task_family
from .validation import (
    DEFAULT_MAX_UNCOMPRESSED_BYTES,
    audit_visibility,
    validate_package_dir,
    validate_zip,
)
from .verification import verification_catalog_identity, verify_task_publication


PROFILE_NAMES = ("agent", "evaluator", "author")
_MANIFEST_LINE = re.compile(r"^([0-9a-f]{64})  \./(.+)$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def _build_directory_name(build_id: str) -> str:
    """Return a short physical directory while retaining the full ID in metadata.

    Content IDs are 64-hex SHA-256 values, but repeating the full value in a
    deep task-data tree crosses the legacy Windows path limit.  A 96-bit prefix
    is used only for the physical directory; catalogs, manifests, state keys,
    and archive records retain and verify the complete build ID.
    """

    digest = build_id.rsplit("_", 1)[-1]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"invalid build ID: {build_id!r}")
    return f"b-{digest[:24]}"


@dataclass(frozen=True)
class TaskBuild:
    task_id: str
    task_build_id: str
    directory: str
    archives: Mapping[str, Mapping[str, Any]]
    file_count: int
    qa: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_build_id": self.task_build_id,
            "directory": self.directory,
            "archives": {key: dict(value) for key, value in self.archives.items()},
            "file_count": self.file_count,
            "qa": dict(self.qa),
        }


@dataclass(frozen=True)
class BuildResult:
    project_id: str
    build_id: str
    root: str
    tasks: tuple[TaskBuild, ...]
    resumed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "paper2ale.build/v1",
            "project_id": self.project_id,
            "build_id": self.build_id,
            "root": self.root,
            "resumed": self.resumed,
            "tasks": [task.to_dict() for task in self.tasks],
        }


def _issue_dict(issue: Any) -> dict[str, Any]:
    if isinstance(issue, dict):
        return dict(issue)
    if hasattr(issue, "to_dict"):
        return dict(issue.to_dict())
    if hasattr(issue, "code") and hasattr(issue, "message"):
        return {
            "code": str(issue.code),
            "message": str(issue.message),
            "severity": str(getattr(issue, "severity", "error")),
            "path": "" if getattr(issue, "path", None) is None else str(issue.path),
        }
    return {"code": "unknown", "message": str(issue), "severity": "error", "path": ""}


def _has_errors(issues: Iterable[Any]) -> bool:
    return any(_issue_dict(issue).get("severity", "error") == "error" for issue in issues)


def _archive_issue(code: str, message: str, path: str = "") -> dict[str, str]:
    return {"code": code, "message": message, "path": path, "severity": "error"}


def _safe_manifest_member(path: str) -> bool:
    if (
        not path
        or path.startswith("/")
        or path.endswith("/")
        or "\\" in path
        or "\x00" in path
        or _WINDOWS_DRIVE.match(path)
        or any(ord(character) < 32 for character in path)
    ):
        return False
    return all(part not in {"", ".", ".."} for part in path.split("/"))


def validate_archive(
    path: str | Path,
    *,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> tuple[dict[str, str], ...]:
    """Validate ZIP structure and recompute every embedded manifest digest."""

    archive_path = Path(path)
    issues = [_issue_dict(issue) for issue in validate_zip(
        archive_path,
        max_uncompressed_bytes=max_uncompressed_bytes,
    )]
    if _has_errors(issues):
        return tuple(sorted(issues, key=lambda item: (item.get("path", ""), item["code"])))

    try:
        with zipfile.ZipFile(archive_path, mode="r") as archive:
            file_infos = {
                info.filename: info
                for info in archive.infolist()
                if not info.is_dir() and not info.filename.endswith("/")
            }
            manifest_info = file_infos.get(MANIFEST_NAME)
            if manifest_info is None:
                issues.append(
                    _archive_issue(
                        "manifest_missing",
                        f"archive is missing {MANIFEST_NAME}",
                        MANIFEST_NAME,
                    )
                )
                return tuple(
                    sorted(issues, key=lambda item: (item.get("path", ""), item["code"]))
                )

            try:
                manifest_text = archive.read(manifest_info).decode("utf-8")
            except UnicodeError as error:
                issues.append(_archive_issue("manifest_unreadable", str(error), MANIFEST_NAME))
                return tuple(
                    sorted(issues, key=lambda item: (item.get("path", ""), item["code"]))
                )

            expected: dict[str, str] = {}
            expected_casefold: dict[str, str] = {}
            listed_order: list[str] = []
            for line_number, line in enumerate(manifest_text.splitlines(), start=1):
                match = _MANIFEST_LINE.fullmatch(line)
                if match is None:
                    issues.append(
                        _archive_issue(
                            "manifest_format",
                            f"invalid manifest line {line_number}",
                            MANIFEST_NAME,
                        )
                    )
                    continue
                digest, relative = match.groups()
                if not _safe_manifest_member(relative):
                    issues.append(
                        _archive_issue(
                            "unsafe_manifest_path",
                            "manifest path is not a safe POSIX relative file path",
                            relative,
                        )
                    )
                    continue
                if relative == MANIFEST_NAME:
                    issues.append(
                        _archive_issue(
                            "manifest_self_reference",
                            "manifest must not hash itself",
                            relative,
                        )
                    )
                    continue
                folded = relative.casefold()
                if folded in expected_casefold:
                    issues.append(
                        _archive_issue(
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
                    _archive_issue(
                        "manifest_order",
                        "manifest entries are not sorted",
                        MANIFEST_NAME,
                    )
                )

            actual_names = set(file_infos) - {MANIFEST_NAME}
            for relative, expected_digest in expected.items():
                info = file_infos.get(relative)
                if info is None:
                    issues.append(
                        _archive_issue("manifest_file_missing", "listed file is missing", relative)
                    )
                    continue
                digest = hashlib.sha256()
                with archive.open(info, mode="r") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                actual_digest = digest.hexdigest()
                if actual_digest != expected_digest:
                    issues.append(
                        _archive_issue(
                            "checksum_mismatch",
                            f"expected {expected_digest}, got {actual_digest}",
                            relative,
                        )
                    )

            for relative in sorted(actual_names - set(expected)):
                issues.append(
                    _archive_issue("unmanifested_file", "file is not listed in manifest", relative)
                )
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        issues.append(_archive_issue("archive_read_error", str(error), str(archive_path)))

    return tuple(sorted(issues, key=lambda item: (item.get("path", ""), item["code"])))


def _builder_for(task: Mapping[str, Any]):
    family = str(task.get("family", ""))
    return task_family(family).builder


def _effective_project(
    project: Mapping[str, Any],
    *,
    difficulty_level: str | None,
    instances: int | None,
) -> dict[str, Any]:
    """Apply CLI controls to a canonical project without mutating the source."""

    effective = json.loads(canonical_json_bytes(project))
    if difficulty_level is not None:
        effective = apply_difficulty_override(effective, difficulty_level)
    if instances is not None:
        for task in effective.get("tasks", []):
            task["instances"] = instances
            selection = task.get("difficulty")
            if isinstance(selection, dict):
                generator = selection.setdefault("generator_overrides", {})
                if not isinstance(generator, dict):
                    raise ValueError("difficulty generator_overrides must be an object")
                generator["instance_count"] = instances
    return require_valid_project(effective)


def _difficulty_preflight(
    project: Mapping[str, Any],
    task: Mapping[str, Any],
    files: Iterable[BuildFile],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Require exact proof that a family consumed its resolved difficulty."""

    resolved = resolve_task_difficulty(project, task)
    if resolved is None:
        return [], {"status": "not_applicable"}
    family = task_family(str(task.get("family", "")))
    if resolved.level not in family.supported_difficulty_levels:
        return [
            {
                "code": "difficulty_unsupported",
                "message": (
                    f"family {family.name!r} does not support difficulty level "
                    f"{resolved.level!r}; supported levels: "
                    f"{', '.join(family.supported_difficulty_levels) or 'none'}"
                ),
                "path": "author/difficulty_manifest.json",
                "severity": "error",
            }
        ], {
            "status": "failed",
            "resolution_id": resolved.resolution_id,
        }
    manifests = [
        item
        for item in files
        if item.path == "author/difficulty_manifest.json"
        and item.visibility == "author"
    ]
    if len(manifests) != 1:
        return [
            {
                "code": "difficulty_manifest_missing",
                "message": "difficulty-aware family must emit exactly one author difficulty manifest",
                "path": "author/difficulty_manifest.json",
                "severity": "error",
            }
        ], {
            "status": "failed",
            "resolution_id": resolved.resolution_id,
        }
    try:
        manifest = json.loads(manifests[0].data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [
            {
                "code": "difficulty_manifest_invalid",
                "message": f"difficulty manifest is not strict UTF-8 JSON: {error}",
                "path": "author/difficulty_manifest.json",
                "severity": "error",
            }
        ], {
            "status": "failed",
            "resolution_id": resolved.resolution_id,
        }
    if not verify_consumption_manifest(resolved, manifest):
        return [
            {
                "code": "difficulty_manifest_mismatch",
                "message": "difficulty manifest does not exactly match the resolved controls",
                "path": "author/difficulty_manifest.json",
                "severity": "error",
            }
        ], {
            "status": "failed",
            "resolution_id": resolved.resolution_id,
        }
    return [], {
        "status": "passed",
        "resolution_id": resolved.resolution_id,
        "profile_id": resolved.profile_id,
        "profile_version": resolved.profile_version,
        "level": resolved.level,
    }


def _syntax_issues(files: Iterable[BuildFile]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for item in files:
        if not item.path.endswith(".py"):
            continue
        try:
            source = item.data.decode("utf-8")
            compile(source, item.path, "exec")
        except (UnicodeDecodeError, SyntaxError) as exc:
            issues.append(
                {
                    "code": "python_syntax",
                    "message": str(exc),
                    "path": item.path,
                    "severity": "error",
                }
            )
    return issues


def _participant_leak_sentinels(project: Mapping[str, Any]) -> tuple[bytes, ...]:
    """Return source identifiers specific enough to safely scan participant files."""

    sentinels: set[bytes] = set()
    sources = project.get("source_bundle", [])
    if not isinstance(sources, list):
        return ()
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in ("id", "uri", "version", "citation"):
            value = source.get(key)
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            encoded = normalized.encode("utf-8")
            if len(encoded) >= 8:
                sentinels.add(encoded)
    return tuple(sorted(sentinels))


def _build_task_in_memory(
    project: Mapping[str, Any],
    task: Mapping[str, Any],
    master_seed: int,
    instances: int | None,
) -> tuple[Mapping[str, Any], list[BuildFile], dict[str, Any]]:
    builder = _builder_for(task)
    files = sorted(
        builder(dict(project), dict(task), master_seed=master_seed, instances=instances),
        key=lambda item: item.path,
    )
    task_fingerprint = {
        "compiler": __version__,
        "verification": verification_catalog_identity(),
        "task": dict(task),
        "master_seed": master_seed,
        "instances": instances,
        "files": [
            {
                "path": item.path,
                "visibility": item.visibility,
                "executable": item.executable,
                "sha256": sha256_bytes(item.data),
            }
            for item in files
        ],
    }
    task_build_id = stable_id("task-build", task_fingerprint)
    schema_issues: list[dict[str, Any]] = []
    visibility_issues = [
        _issue_dict(issue)
        for issue in audit_visibility(
            files,
            private_sentinels=_participant_leak_sentinels(project),
        )
    ]
    syntax_issues = _syntax_issues(files)
    difficulty_issues, difficulty_check = _difficulty_preflight(project, task, files)
    issues = schema_issues + visibility_issues + syntax_issues + difficulty_issues
    preflight_passed = not _has_errors(issues)
    checks: dict[str, Any] = {
        "project_schema": {
            "status": "passed" if not _has_errors(schema_issues) else "failed"
        },
        "visibility": {
            "status": "passed" if not _has_errors(visibility_issues) else "failed"
        },
        "python_syntax": {
            "status": "passed" if not _has_errors(syntax_issues) else "failed"
        },
        "difficulty": difficulty_check,
        "provenance": {"status": "not_run"},
        "runtime_reference": {"status": "not_run"},
        "mutation_resistance": {"status": "not_run"},
        "resource_budget": {"status": "not_run"},
        "reproducibility": {"status": "not_run"},
    }
    verification = None
    if preflight_passed:
        verification = verify_task_publication(
            project,
            task,
            files,
            builder=builder,
            master_seed=master_seed,
            instances=instances,
        )
        if verification is not None:
            checks.update(verification["checks"])
            issues.extend(verification["issues"])
    publication_gates = (
        "provenance",
        "runtime_reference",
        "mutation_resistance",
        "resource_budget",
        "reproducibility",
    )
    publication_ready = (
        preflight_passed
        and verification is not None
        and all(checks[name]["status"] == "passed" for name in publication_gates)
    )
    qa = {
        "schema_version": "paper2ale.qa/v1",
        "task_id": task["id"],
        "task_build_id": task_build_id,
        "checks": checks,
        "issues": issues,
        "preflight_passed": preflight_passed,
        "publication_ready": publication_ready,
    }
    if not qa["preflight_passed"]:
        messages = "; ".join(f"{issue['path']}: {issue['message']}" for issue in issues)
        raise ValueError(f"task {task['id']} failed pre-package QA: {messages}")
    files.append(
        BuildFile(
            path="author/qa_report.json",
            data=canonical_json_bytes(qa),
            visibility="author",
        )
    )
    return task, files, qa


def _materialize_task(
    task: Mapping[str, Any],
    files: list[BuildFile],
    qa: Mapping[str, Any],
    task_root: Path,
) -> TaskBuild:
    profiles_root = task_root / "profiles"
    bundles_root = task_root / "bundles"
    bundles_root.mkdir(parents=True, exist_ok=True)
    archives: dict[str, dict[str, Any]] = {}
    for profile in PROFILE_NAMES:
        profile_root = profiles_root / profile
        write_projection(files, profile_root, profile)
        write_manifest(profile_root)
        package_issues = [_issue_dict(issue) for issue in validate_package_dir(profile_root)]
        if _has_errors(package_issues):
            raise ValueError(f"generated {profile} package for {task['id']} failed validation: {package_issues}")
        zip_path = bundles_root / f"{task['id']}.{profile}.zip"
        executable_paths = [
            item.path for item in projection_files(files, profile) if item.executable
        ]
        digest = write_deterministic_zip(
            profile_root,
            zip_path,
            executable_paths=executable_paths,
        )
        archive_issues = validate_archive(zip_path)
        if _has_errors(archive_issues):
            raise ValueError(
                f"generated {profile} archive for {task['id']} failed validation: "
                f"{list(archive_issues)}"
            )
        archives[profile] = {
            "path": zip_path.relative_to(task_root).as_posix(),
            "sha256": digest,
            "size_bytes": zip_path.stat().st_size,
        }

    # HNN and other current task families that expose the canonical
    # input/instances + task_card contract also receive a directly deployable
    # local-ALE tree.  This is operator material: ALE stages input/software
    # before the agent and reference only during evaluation.
    inventory_paths = {item.path for item in files}
    if "task_card.json" in inventory_paths and any(
        path.startswith("input/instances/") for path in inventory_paths
    ):
        deployment_files = ale_local_deployment_files(
            files,
            expected_task_id=str(task["id"]),
        )
        deployment_root = task_root / "deploy" / "ale-local"
        write_projection(deployment_files, deployment_root, "author")
        write_manifest(deployment_root)
        deployment_issues = [
            _issue_dict(issue) for issue in validate_package_dir(deployment_root)
        ]
        if _has_errors(deployment_issues):
            raise ValueError(
                f"generated ALE deployment for {task['id']} failed validation: "
                f"{deployment_issues}"
            )
        deployment_zip = bundles_root / f"{task['id']}.ale-local.zip"
        deployment_executables = [
            item.path for item in deployment_files if item.executable
        ]
        deployment_digest = write_deterministic_zip(
            deployment_root,
            deployment_zip,
            executable_paths=deployment_executables,
        )
        deployment_archive_issues = validate_archive(deployment_zip)
        if _has_errors(deployment_archive_issues):
            raise ValueError(
                f"generated ALE deployment archive for {task['id']} failed validation: "
                f"{list(deployment_archive_issues)}"
            )
        archives["ale_local"] = {
            "path": deployment_zip.relative_to(task_root).as_posix(),
            "sha256": deployment_digest,
            "size_bytes": deployment_zip.stat().st_size,
        }

    compatibility = {
        "agent": f"{task['id']}_ALE_Input_Materials.zip",
        "evaluator": f"{task['id']}_ALE_Reference_Output.zip",
        "author": f"{task['id']}_ALE_Complete_Package.zip",
    }
    for profile, name in compatibility.items():
        source = bundles_root / f"{task['id']}.{profile}.zip"
        destination = bundles_root / name
        shutil.copyfile(source, destination)
        archives[profile]["compatibility_path"] = destination.relative_to(task_root).as_posix()
        archives[profile]["compatibility_sha256"] = sha256_file(destination)
        archives[profile]["compatibility_size_bytes"] = destination.stat().st_size

    task_build_id = str(qa["task_build_id"])
    (task_root / "task_build.json").write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "paper2ale.task-build/v1",
                "task_id": task["id"],
                "task_build_id": task_build_id,
                "archives": archives,
                "qa": qa,
            }
        )
    )
    return TaskBuild(
        task_id=str(task["id"]),
        task_build_id=task_build_id,
        directory=task_root.name,
        archives=archives,
        file_count=len(files),
        qa=dict(qa),
    )


def _load_existing(
    build_root: Path,
    *,
    expected_project_id: str,
    expected_build_id: str,
    expected_task_ids: Iterable[str],
) -> BuildResult | None:
    catalog_path = build_root / "catalog.json"
    if not catalog_path.is_file():
        return None
    if _has_errors(validate_package_dir(build_root)):
        return None
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if (
            data.get("schema_version") != "paper2ale.build/v1"
            or data.get("compiler_version") != __version__
            or data.get("project_id") != expected_project_id
            or data.get("build_id") != expected_build_id
        ):
            return None
        raw_tasks = data["tasks"]
        if not isinstance(raw_tasks, list):
            return None
        expected_ids = tuple(sorted(str(task_id) for task_id in expected_task_ids))
        if tuple(item.get("task_id") for item in raw_tasks if isinstance(item, dict)) != expected_ids:
            return None
        for item in raw_tasks:
            if not isinstance(item, dict):
                return None
            if item.get("directory") != item.get("task_id"):
                return None
            task_root = (build_root / "tasks" / item["directory"]).resolve()
            task_root.relative_to((build_root / "tasks").resolve())
            if not task_root.is_dir():
                return None
            archives = item.get("archives")
            allowed_archive_sets = (
                set(PROFILE_NAMES),
                set(PROFILE_NAMES) | {"ale_local"},
            )
            if not isinstance(archives, dict) or set(archives) not in allowed_archive_sets:
                return None
            for profile in PROFILE_NAMES:
                archive = archives[profile]
                if not isinstance(archive, dict):
                    return None
                relative = archive["path"]
                expected_relative = f"bundles/{item['task_id']}.{profile}.zip"
                if relative != expected_relative:
                    return None
                archive_path = (task_root / relative).resolve()
                archive_path.relative_to(task_root)
                if not archive_path.is_file():
                    return None
                if archive_path.stat().st_size != int(archive["size_bytes"]):
                    return None
                if sha256_file(archive_path) != archive["sha256"]:
                    return None
                if _has_errors(validate_archive(archive_path)):
                    return None

                compatibility_relative = archive.get("compatibility_path")
                expected_compatibility = {
                    "agent": f"bundles/{item['task_id']}_ALE_Input_Materials.zip",
                    "evaluator": f"bundles/{item['task_id']}_ALE_Reference_Output.zip",
                    "author": f"bundles/{item['task_id']}_ALE_Complete_Package.zip",
                }[profile]
                if compatibility_relative != expected_compatibility:
                    return None
                compatibility_path = (task_root / compatibility_relative).resolve()
                compatibility_path.relative_to(task_root)
                if not compatibility_path.is_file():
                    return None
                if compatibility_path.stat().st_size != int(
                    archive["compatibility_size_bytes"]
                ):
                    return None
                compatibility_digest = sha256_file(compatibility_path)
                if (
                    compatibility_digest != archive["compatibility_sha256"]
                    or compatibility_digest != archive["sha256"]
                ):
                    return None
            if "ale_local" in archives:
                deployment = archives["ale_local"]
                if not isinstance(deployment, dict):
                    return None
                expected_relative = f"bundles/{item['task_id']}.ale-local.zip"
                if deployment.get("path") != expected_relative:
                    return None
                deployment_path = (task_root / expected_relative).resolve()
                deployment_path.relative_to(task_root)
                if not deployment_path.is_file():
                    return None
                if deployment_path.stat().st_size != int(deployment["size_bytes"]):
                    return None
                if sha256_file(deployment_path) != deployment["sha256"]:
                    return None
                if _has_errors(validate_archive(deployment_path)):
                    return None
        tasks = tuple(
            TaskBuild(
                task_id=item["task_id"],
                task_build_id=item["task_build_id"],
                directory=item["directory"],
                archives=item["archives"],
                file_count=int(item["file_count"]),
                qa=item["qa"],
            )
            for item in data["tasks"]
        )
        return BuildResult(data["project_id"], data["build_id"], str(build_root), tasks, resumed=True)
    except (AttributeError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def build_project(
    project_path: str | Path,
    out_dir: str | Path,
    *,
    jobs: int = 4,
    master_seed: int | None = None,
    instances: int | None = None,
    difficulty_level: str | None = None,
    resume: bool = True,
    force: bool = False,
) -> BuildResult:
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ValueError("jobs must be a positive integer")
    if instances is not None and (
        not isinstance(instances, int) or isinstance(instances, bool) or instances < 1
    ):
        raise ValueError("instances must be a positive integer when provided")
    if force:
        resume = False

    project = require_valid_project(load_project(project_path))
    project = _effective_project(
        project,
        difficulty_level=difficulty_level,
        instances=instances,
    )
    seed = int(project.get("defaults", {}).get("master_seed", 0) if master_seed is None else master_seed)
    build_payload = {
        "compiler_version": __version__,
        "verification": verification_catalog_identity(),
        "project": project,
        "master_seed": seed,
        "instances_override": instances,
        "difficulty_override": difficulty_level,
    }
    build_id = stable_id("build", build_payload)
    project_id = str(project["project_id"])
    output = Path(out_dir).resolve()
    project_root = output / project_id
    build_directory = _build_directory_name(build_id)
    build_root = project_root / build_directory
    expected_task_ids = tuple(sorted(str(task["id"]) for task in project["tasks"]))
    project_root.mkdir(parents=True, exist_ok=True)

    if resume:
        existing = _load_existing(
            build_root,
            expected_project_id=project_id,
            expected_build_id=build_id,
            expected_task_ids=expected_task_ids,
        )
        if existing is not None:
            return existing
    if build_root.exists():
        if not force:
            raise FileExistsError(
                f"build directory exists but is not resumable: {build_root}; use --force to preserve it as a quarantined build and rebuild"
            )
        quarantine = project_root / f"{build_id}.quarantined-{uuid.uuid4().hex}"
        build_root.replace(quarantine)

    state = StageStateStore(output / ".paper2ale" / "state.sqlite")
    state_key = stage_key(
        "build_project",
        "2",
        {
            "project": project,
            "compiler_version": __version__,
            "verification": verification_catalog_identity(),
            "build_id": build_id,
        },
        {"seed": seed, "instances": instances, "difficulty": difficulty_level},
    )
    owner = str(uuid.uuid4())
    if not state.claim(state_key, "build_project", owner, lease_s=1800.0):
        existing = _load_existing(
            build_root,
            expected_project_id=project_id,
            expected_build_id=build_id,
            expected_task_ids=expected_task_ids,
        )
        if existing is not None:
            return existing
        status = state.get(state_key)
        if status is not None and status["status"] != "running":
            state.invalidate(stage_key=state_key)
            if not state.claim(state_key, "build_project", owner, lease_s=1800.0):
                raise RuntimeError(f"could not reclaim stale build stage: {state_key}")
        else:
            raise RuntimeError(f"build stage is already leased by another worker: {state_key}")

    temporary: Path | None = None
    try:
        temporary = Path(
            tempfile.mkdtemp(prefix=f".tmp-{build_directory[2:10]}-", dir=project_root)
        )
        tasks = list(project["tasks"])
        in_memory: dict[str, tuple[Mapping[str, Any], list[BuildFile], dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=max(1, min(int(jobs), len(tasks) or 1))) as executor:
            futures = {
                executor.submit(_build_task_in_memory, project, task, seed, instances): str(task["id"])
                for task in tasks
            }
            for future in as_completed(futures):
                in_memory[futures[future]] = future.result()

        task_builds: list[TaskBuild] = []
        tasks_root = temporary / "tasks"
        for task_id in sorted(in_memory):
            task, files, qa = in_memory[task_id]
            task_root = tasks_root / task_id
            task_root.mkdir(parents=True, exist_ok=False)
            task_builds.append(_materialize_task(task, files, qa, task_root))

        catalog = {
            "schema_version": "paper2ale.build/v1",
            "compiler_version": __version__,
            "project_id": project_id,
            "build_id": build_id,
            "master_seed": seed,
            "tasks": [task.to_dict() for task in task_builds],
        }
        (temporary / "catalog.json").write_bytes(canonical_json_bytes(catalog))
        (temporary / "project.lock.json").write_bytes(canonical_json_bytes(project))
        write_manifest(temporary)
        build_issues = validate_package_dir(temporary)
        if _has_errors(build_issues):
            raise ValueError(f"generated build failed manifest validation: {list(build_issues)}")
        temporary.replace(build_root)
        temporary = None
        result = BuildResult(project_id, build_id, str(build_root), tuple(task_builds), resumed=False)
        state.finish(state_key, owner, result.to_dict())
        return result
    except Exception as exc:
        state.fail(state_key, owner, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if temporary is not None and temporary.exists():
            if temporary.resolve().parent != project_root.resolve():
                raise RuntimeError(
                    f"refusing to remove temporary build outside project root: {temporary}"
                )
            shutil.rmtree(temporary)


def audit_project(
    project_path: str | Path,
    *,
    master_seed: int | None = None,
    instances: int | None = None,
    difficulty_level: str | None = None,
) -> dict[str, Any]:
    project = load_project(project_path)
    schema_issues = [_issue_dict(issue) for issue in validate_project(project)]
    if _has_errors(schema_issues):
        return {
            "schema_version": "paper2ale.audit/v1",
            "preflight_passed": False,
            "publication_ready": False,
            "schema_issues": schema_issues,
            "tasks": [],
        }
    project = _effective_project(
        project,
        difficulty_level=difficulty_level,
        instances=instances,
    )
    seed = int(project.get("defaults", {}).get("master_seed", 0) if master_seed is None else master_seed)
    task_reports = []
    for task in project["tasks"]:
        _, files, qa = _build_task_in_memory(project, task, seed, instances)
        task_reports.append(
            {
                "task_id": task["id"],
                "file_count": len(files),
                "visibility_counts": {
                    profile: sum(1 for item in files if item.visibility == profile)
                    for profile in ("agent", "evaluator", "author")
                },
                "qa": qa,
            }
        )
    return {
        "schema_version": "paper2ale.audit/v1",
        "preflight_passed": all(
            report["qa"]["preflight_passed"] for report in task_reports
        ),
        "publication_ready": all(
            report["qa"]["publication_ready"] for report in task_reports
        ),
        "schema_issues": schema_issues,
        "tasks": task_reports,
    }


def inspect_project(project_path: str | Path) -> dict[str, Any]:
    project = require_valid_project(load_project(project_path))
    evidence = project["evidence_graph"]
    conflicts = [record for record in evidence.get("records", []) if record.get("conflict_set")]
    return {
        "project_id": project["project_id"],
        "sources": len(project["source_bundle"]),
        "evidence_records": len(evidence.get("records", [])),
        "workflow_nodes": len(evidence.get("nodes", [])),
        "workflow_edges": len(evidence.get("edges", [])),
        "claims": len(evidence.get("claims", [])),
        "conflicts": [
            {
                "id": item["id"],
                "conflict_set": item.get("conflict_set"),
                "status": item.get("status"),
                "impact": item.get("impact"),
            }
            for item in conflicts
        ],
        "tasks": [
            {
                "id": task["id"],
                "mode": task["mode"],
                "family": task["family"],
                "instances": task["instances"],
                "evidence_ids": task["evidence_ids"],
                "difficulty": (
                    None
                    if resolve_task_difficulty(project, task) is None
                    else resolve_task_difficulty(project, task).to_dict()
                ),
            }
            for task in project["tasks"]
        ],
    }
