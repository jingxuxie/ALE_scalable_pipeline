"""Command-line interface for the deterministic compiler and audits."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Sequence

from .assets import AssetCache, AssetLimits, AssetSpec, asset_bundle_digest, resolve_assets
from .difficulty import (
    LEVEL_NAMES,
    assess_calibration_validity,
    assess_task_calibration_validity,
    check_cross_level_behavioral_monotonicity,
    derive_task_calibration_id,
    pin_agent_system,
    resolve_difficulty_v2,
    resolve_task_difficulty,
    summarize_calibration,
    summarize_calibration_by_agent_system,
)
from .generation import (
    DEFAULT_SCHEMA_DIR,
    generate_project,
)
from .orchestration import load_orchestration_manifest, orchestrate_project
from .pipeline import (
    _load_existing,
    audit_project,
    build_project,
    inspect_project,
    publish_project,
    validate_archive,
)
from .providers import CommandProvider, ReplayProvider
from .schema import canonical_json_bytes, load_project, require_valid_project
from .source_ingest import (
    ingest_sources,
    load_json_object,
    load_json_value,
    load_source_metadata,
)
from .triage import PaperProfile, TriagePolicy, triage_paper
from .task_families import task_family
from .validation import validate_package_dir


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


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive number") from error
    if not parsed > 0 or parsed == float("inf"):
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


_PORTABLE_TRIAL_ID = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9_-])?$"
)
_WINDOWS_RESERVED_COMPONENTS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_BUILD_ID = re.compile(r"^build_[0-9a-f]{64}$")
_TASK_BUILD_ID = re.compile(r"^task-build_[0-9a-f]{64}$")


def _validate_trial_identity(row: dict[str, Any], index: int) -> tuple[str, int, int]:
    """Return a strict portable trial ID and its nonnegative run coordinates."""

    trial_id = row["trial_id"]
    reserved_stem = (
        trial_id.split(".", 1)[0].upper() if isinstance(trial_id, str) else ""
    )
    if (
        not isinstance(trial_id, str)
        or len(trial_id) > 128
        or _PORTABLE_TRIAL_ID.fullmatch(trial_id) is None
        or reserved_stem in _WINDOWS_RESERVED_COMPONENTS
    ):
        raise ValueError(
            f"calibration trial {index} trial_id must be one portable path component"
        )
    coordinates: list[int] = []
    for field in ("seed", "attempt"):
        value = row[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                f"calibration trial {index} {field} must be a nonnegative integer"
            )
        coordinates.append(value)
    return trial_id, coordinates[0], coordinates[1]


def _claim_unique_trial(
    *,
    index: int,
    trial_id: str,
    run_coordinate: tuple[Any, ...],
    seen_trial_ids: dict[str, int],
    seen_run_coordinates: dict[tuple[Any, ...], int],
) -> None:
    previous_id = seen_trial_ids.get(trial_id)
    if previous_id is not None:
        raise ValueError(
            f"calibration trial {index} duplicates trial_id {trial_id!r} "
            f"from trial {previous_id}"
        )
    previous_run = seen_run_coordinates.get(run_coordinate)
    if previous_run is not None:
        raise ValueError(
            f"calibration trial {index} duplicates run coordinates "
            f"from trial {previous_run}"
        )
    seen_trial_ids[trial_id] = index
    seen_run_coordinates[run_coordinate] = index


def _verified_calibration_catalog(
    catalog_path: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    """Load one manifest-covered build catalog and bind it to *project*.

    A bare catalog JSON is not sufficient provenance: the enclosing build must
    pass the compiler's normal resume validation, its project lock must exactly
    match the supplied project, and every catalog task must agree with its
    nested task-build record.
    """

    path = Path(catalog_path)
    if path.name != "catalog.json":
        raise ValueError("v2 calibration --catalog must name a build catalog.json")
    catalog = load_json_object(path, name="build catalog")
    if catalog.get("schema_version") != "paper2ale.build/v1":
        raise ValueError("v2 calibration requires a paper2ale.build/v1 catalog")
    project_id = project.get("project_id")
    if catalog.get("project_id") != project_id:
        raise ValueError(
            "build catalog project_id does not match the calibration project"
        )
    build_id = catalog.get("build_id")
    if not isinstance(build_id, str) or _BUILD_ID.fullmatch(build_id) is None:
        raise ValueError("build catalog has an invalid content-derived build_id")
    raw_tasks = catalog.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ValueError("build catalog tasks must be an array")
    expected_task_ids = tuple(sorted(str(task["id"]) for task in project["tasks"]))
    verified = _load_existing(
        path.parent,
        expected_project_id=str(project_id),
        expected_build_id=build_id,
        expected_task_ids=expected_task_ids,
    )
    if verified is None:
        raise ValueError(
            "build catalog is stale, tampered, or not a complete verified build"
        )

    lock_path = path.parent / "project.lock.json"
    locked_project = require_valid_project(
        load_json_object(lock_path, name="build project lock")
    )
    if canonical_json_bytes(locked_project) != canonical_json_bytes(project):
        raise ValueError(
            "calibration project does not exactly match the build project lock; "
            "use that build's project.lock.json"
        )

    task_build_ids: dict[str, str] = {}
    for item in verified.tasks:
        if _TASK_BUILD_ID.fullmatch(item.task_build_id) is None:
            raise ValueError(
                f"build catalog task {item.task_id!r} has an invalid task_build_id"
            )
        nested_path = path.parent / "tasks" / item.directory / "task_build.json"
        nested = load_json_object(nested_path, name="nested task build")
        expected_nested = {
            "schema_version": "paper2ale.task-build/v1",
            "task_id": item.task_id,
            "task_build_id": item.task_build_id,
            "archives": dict(item.archives),
            "qa": dict(item.qa),
        }
        if nested != expected_nested:
            raise ValueError(
                f"nested task build for {item.task_id!r} disagrees with catalog.json"
            )
        if item.qa.get("task_id") != item.task_id or item.qa.get(
            "task_build_id"
        ) != item.task_build_id:
            raise ValueError(
                f"catalog QA identity for {item.task_id!r} is inconsistent"
            )
        task_build_ids[item.task_id] = item.task_build_id
    if set(task_build_ids) != set(expected_task_ids):
        raise ValueError("build catalog task set does not match the calibration project")

    return {
        "schema_version": "paper2ale.calibration-build-binding/v1",
        "project_id": str(project_id),
        "build_id": build_id,
        "compiler_version": str(catalog.get("compiler_version", "")),
        "publication_mode": str(catalog.get("publication_mode", "")),
        "task_build_ids": task_build_ids,
    }


def _calibration_report(
    trials_path: Path,
    project_path: Path | None,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    payload = load_json_value(trials_path, name="calibration trials")
    if (
        isinstance(payload, dict)
        and payload.get("schema_version") == "paper2ale.calibration-trials/v2"
    ):
        return _calibration_report_v2(payload, project_path, catalog_path)
    if catalog_path is not None:
        raise ValueError("--catalog is supported only for calibration-trials/v2")
    if isinstance(payload, dict):
        allowed = {"schema_version", "trials"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"calibration trials contain unknown fields: {', '.join(unknown)}")
        if payload.get("schema_version", "paper2ale.calibration-trials/v1") != (
            "paper2ale.calibration-trials/v1"
        ):
            raise ValueError("unsupported calibration trials schema_version")
        rows = payload.get("trials")
    else:
        rows = payload
    if not isinstance(rows, list) or not rows:
        raise ValueError("calibration trials must be a nonempty JSON array")

    required = {"trial_id", "task_id", "level", "passed", "seed", "attempt"}
    allowed_row = required | {"score", "model", "agent"}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    seen_trial_ids: dict[str, int] = {}
    seen_run_coordinates: dict[tuple[Any, ...], int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"calibration trial {index} must be an object")
        missing = sorted(required - set(row))
        unknown = sorted(set(row) - allowed_row)
        if missing or unknown:
            detail = (
                f"missing {missing}" if missing else f"unknown fields {unknown}"
            )
            raise ValueError(f"calibration trial {index} has {detail}")
        task_id = row["task_id"]
        level = row["level"]
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(f"calibration trial {index} task_id must be nonempty")
        if level not in LEVEL_NAMES:
            raise ValueError(
                f"calibration trial {index} level must be one of {', '.join(LEVEL_NAMES)}"
            )
        if not isinstance(row["passed"], bool):
            raise ValueError(f"calibration trial {index} passed must be boolean")
        if "score" in row and (
            isinstance(row["score"], bool)
            or not isinstance(row["score"], (int, float))
            or not math.isfinite(float(row["score"]))
        ):
            raise ValueError(f"calibration trial {index} score must be finite")
        for label in ("model", "agent"):
            if label in row and (
                not isinstance(row[label], str) or not row[label].strip()
            ):
                raise ValueError(
                    f"calibration trial {index} {label} must be a nonempty string"
                )
        if ("model" in row) != ("agent" in row):
            raise ValueError(
                f"calibration trial {index} legacy identity must include both model "
                "and agent; use calibration-trials/v2 for a fully pinned agent system"
            )
        trial_id, seed, attempt = _validate_trial_identity(row, index)
        _claim_unique_trial(
            index=index,
            trial_id=trial_id,
            run_coordinate=(
                task_id,
                level,
                str(row.get("model", "")),
                str(row.get("agent", "")),
                seed,
                attempt,
            ),
            seen_trial_ids=seen_trial_ids,
            seen_run_coordinates=seen_run_coordinates,
        )
        grouped.setdefault((task_id, level), []).append(row)

    legacy_identities: dict[tuple[str, str], tuple[str, str] | None] = {}
    for group, outcomes in grouped.items():
        identity_presence = ["model" in outcome for outcome in outcomes]
        if any(identity_presence) and not all(identity_presence):
            raise ValueError(
                f"legacy calibration group {group[0]!r}/{group[1]!r} mixes "
                "identified and unidentified trials; use calibration-trials/v2 "
                "for a fully pinned agent system"
            )
        identities = {
            (str(outcome["model"]), str(outcome["agent"]))
            for outcome in outcomes
            if "model" in outcome
        }
        if len(identities) > 1:
            raise ValueError(
                f"legacy calibration group {group[0]!r}/{group[1]!r} mixes "
                "multiple model/agent identities; split the trials or use "
                "calibration-trials/v2"
            )
        legacy_identities[group] = next(iter(identities), None)

    project = None
    if project_path is not None:
        project = require_valid_project(load_project(project_path))
    reports: list[dict[str, Any]] = []
    for (task_id, level), outcomes in sorted(grouped.items()):
        difficulty_project = (
            project
            if project is not None
            else {"tasks": [{"id": task_id, "instances": 1}]}
        )
        resolved = resolve_task_difficulty(
            difficulty_project,
            task_id,
            override=level,
        )
        summary = summarize_calibration(outcomes, resolved.target_band)
        legacy_identity = legacy_identities[(task_id, level)]
        reports.append(
            {
                "task_id": task_id,
                "level": level,
                "legacy_identity": (
                    None
                    if legacy_identity is None
                    else {
                        "model": legacy_identity[0],
                        "agent": legacy_identity[1],
                    }
                ),
                "profile_id": resolved.profile_id,
                "profile_version": resolved.profile_version,
                "resolution_id": resolved.resolution_id,
                "target_band": resolved.target_band.to_dict(),
                "summary": summary.to_dict(),
            }
        )
    return {
        "schema_version": "paper2ale.calibration-report/v1",
        "all_calibrated": all(report["summary"]["meets_target"] for report in reports),
        "groups": reports,
        "notes": {
            "deprecated": True,
            "identity_policy": (
                "Legacy model/agent labels are accepted only when every task-level "
                "group has one complete, consistent pair; unlabeled groups remain unpinned."
            ),
            "migration": (
                "Use paper2ale.calibration-trials/v2 with pinned agent_systems, "
                "semantic IDs, and numeric scores for publication-grade calibration."
            ),
        },
    }


def _calibration_report_v2(
    payload: dict[str, Any],
    project_path: Path | None,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Calibrate without pooling different model/harness/tool systems."""

    allowed_top = {"schema_version", "agent_systems", "trials"}
    unknown_top = sorted(set(payload) - allowed_top)
    if unknown_top:
        raise ValueError(
            "v2 calibration trials contain unknown fields: "
            + ", ".join(unknown_top)
        )
    systems = payload.get("agent_systems")
    rows = payload.get("trials")
    if not isinstance(systems, list) or not systems:
        raise ValueError("v2 calibration requires a nonempty agent_systems array")
    if not isinstance(rows, list) or not rows:
        raise ValueError("v2 calibration requires a nonempty trials array")

    pinned_systems: dict[str, dict[str, Any]] = {}
    for index, envelope in enumerate(systems):
        if not isinstance(envelope, dict) or set(envelope) != {
            "schema_version",
            "agent_system_id",
            "descriptor",
        }:
            raise ValueError(
                f"agent_systems[{index}] must be a strict pinned descriptor envelope"
            )
        if envelope["schema_version"] != "paper2ale.agent-system/v1":
            raise ValueError(f"agent_systems[{index}] has an unsupported schema_version")
        expected = pin_agent_system(envelope["descriptor"])
        if envelope != expected:
            raise ValueError(
                f"agent_systems[{index}] ID does not match its canonical descriptor"
            )
        system_id = envelope["agent_system_id"]
        if system_id in pinned_systems:
            raise ValueError(f"duplicate agent system {system_id!r}")
        pinned_systems[system_id] = expected

    if project_path is None and catalog_path is not None:
        raise ValueError("v2 calibration --catalog requires --project")
    if project_path is not None and catalog_path is None:
        raise ValueError(
            "v2 calibration with --project requires the verified build --catalog"
        )
    project = None
    catalog_binding = None
    project_tasks: dict[str, dict[str, Any]] = {}
    if project_path is not None:
        project = require_valid_project(load_project(project_path))
        assert catalog_path is not None
        catalog_binding = _verified_calibration_catalog(catalog_path, project)
        project_tasks = {
            str(task["id"]): task for task in project["tasks"]
        }

    required = {
        "trial_id",
        "task_id",
        "task_build_id",
        "level",
        "agent_system_id",
        "semantic_id",
        "passed",
        "score",
        "seed",
        "attempt",
    }
    allowed_row = required
    normalized: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    resolved_by_group: dict[tuple[str, str, str], Any] = {}
    seen_trial_ids: dict[str, int] = {}
    seen_run_coordinates: dict[tuple[Any, ...], int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"calibration trial {index} must be an object")
        missing = sorted(required - set(row))
        unknown = sorted(set(row) - allowed_row)
        if missing or unknown:
            detail = f"missing {missing}" if missing else f"unknown fields {unknown}"
            raise ValueError(f"calibration trial {index} has {detail}")
        task_id = row["task_id"]
        task_build_id = row["task_build_id"]
        level = row["level"]
        system_id = row["agent_system_id"]
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(f"calibration trial {index} task_id must be nonempty")
        if level not in LEVEL_NAMES:
            raise ValueError(
                f"calibration trial {index} level must be one of {', '.join(LEVEL_NAMES)}"
            )
        if catalog_binding is not None:
            task = project_tasks.get(task_id)
            if task is None:
                raise ValueError(
                    f"calibration trial {index} references task {task_id!r} "
                    "absent from the build project"
                )
            expected_task_build_id = catalog_binding["task_build_ids"][task_id]
            if task_build_id != expected_task_build_id:
                raise ValueError(
                    f"calibration trial {index} task_build_id is fabricated, stale, "
                    f"or belongs to a different build of task {task_id!r}"
                )
            family = task_family(str(task.get("family", "")))
            if level not in family.supported_difficulty_levels:
                supported = ", ".join(family.supported_difficulty_levels) or "none"
                raise ValueError(
                    f"calibration trial {index} requests unsupported task/level pair "
                    f"{task_id!r}/{level!r} for family {family.name!r}; "
                    f"supported levels: {supported}"
                )
            built_difficulty = resolve_task_difficulty(project, task)
            if built_difficulty is None:
                raise ValueError(
                    f"calibration task {task_id!r} has no build-bound difficulty level"
                )
            if built_difficulty.level != level:
                raise ValueError(
                    f"calibration trial {index} labels task {task_id!r} as {level!r}, "
                    f"but the verified build binds it to {built_difficulty.level!r}"
                )
        if system_id not in pinned_systems:
            raise ValueError(
                f"calibration trial {index} references an unpinned agent_system_id"
            )
        if not isinstance(row["passed"], bool):
            raise ValueError(f"calibration trial {index} passed must be boolean")
        if (
            isinstance(row["score"], bool)
            or not isinstance(row["score"], (int, float))
            or not math.isfinite(float(row["score"]))
            or not 0.0 <= float(row["score"]) <= 1.0
        ):
            raise ValueError(f"calibration trial {index} score must be finite and in [0, 1]")
        group = (task_id, task_build_id, level)
        resolved = resolved_by_group.setdefault(group, resolve_difficulty_v2(level))
        expected_semantic_id = derive_task_calibration_id(
            resolved,
            task_id=task_id,
            task_build_id=task_build_id,
        )
        if row["semantic_id"] != expected_semantic_id:
            raise ValueError(
                f"calibration trial {index} semantic_id is stale or belongs to a "
                "different task build or challenge/evaluation profile"
            )
        trial_id, seed, attempt = _validate_trial_identity(row, index)
        _claim_unique_trial(
            index=index,
            trial_id=trial_id,
            run_coordinate=(
                task_id,
                task_build_id,
                level,
                system_id,
                seed,
                attempt,
            ),
            seen_trial_ids=seen_trial_ids,
            seen_run_coordinates=seen_run_coordinates,
        )
        copied = dict(row)
        copied["score"] = float(row["score"])
        normalized.append(copied)
        grouped.setdefault(group, []).append(copied)

    group_reports: list[dict[str, Any]] = []
    for group, outcomes in sorted(grouped.items()):
        resolved = resolved_by_group[group]
        summaries = summarize_calibration_by_agent_system(
            outcomes,
            resolved.target_band,
            expected_semantic_id=derive_task_calibration_id(
                resolved,
                task_id=group[0],
                task_build_id=group[1],
            ),
            require_scores=True,
        )
        group_reports.append(
            {
                "task_id": group[0],
                "task_build_id": group[1],
                "level": group[2],
                "difficulty": resolved.to_dict(),
                "agent_systems": [summary.to_dict() for summary in summaries],
            }
        )

    monotonicity: list[dict[str, Any]] = []
    for task_id in sorted({row["task_id"] for row in normalized}):
        task_trials = [row for row in normalized if row["task_id"] == task_id]
        if len({row["level"] for row in task_trials}) < 2:
            continue
        monotonicity.append(
            {
                "task_id": task_id,
                "agent_systems": [
                    report.to_dict()
                    for report in check_cross_level_behavioral_monotonicity(
                        task_trials,
                        compare_scores=True,
                    )
                ],
            }
        )
    calibrated = all(
        system["calibration"]["meets_target"]
        for group in group_reports
        for system in group["agent_systems"]
    )
    monotone = all(
        system["status"] == "supported"
        for task in monotonicity
        for system in task["agent_systems"]
    )
    return {
        "schema_version": "paper2ale.calibration-report/v2",
        "all_calibrated": calibrated and monotone,
        "verified_claim_ready": (
            catalog_binding is not None and calibrated and monotone
        ),
        "build_catalog": catalog_binding,
        "agent_systems": [pinned_systems[key] for key in sorted(pinned_systems)],
        "groups": group_reports,
        "behavioral_monotonicity": monotonicity,
        "notes": {
            "systems_pooled": False,
            "scores_used": True,
            "benchmark_sampling_changes_invalidate_calibration": False,
            "challenge_or_evaluation_changes_invalidate_calibration": True,
            "task_build_changes_invalidate_calibration": True,
            "build_catalog_verified": catalog_binding is not None,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper2ale",
        description=(
            "Generate validated paper-grounded project documents and compile them "
            "into paper-blind, verifiable ALE tasks."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser(
        "generate",
        help="extract local pinned sources into a validated project JSON candidate",
    )
    generate.add_argument("sources", nargs="+", type=Path)
    generate.add_argument(
        "--metadata",
        action="append",
        required=True,
        type=Path,
        help="strict source-ref JSON paired positionally with each local source",
    )
    generate.add_argument("--project-id", required=True)
    generate.add_argument("--out", required=True, type=Path)
    provider_group = generate.add_mutually_exclusive_group(required=True)
    provider_group.add_argument("--replay", type=Path)
    provider_group.add_argument(
        "--command",
        dest="provider_command",
        help="adapter executable invoked directly (never through a shell)",
    )
    generate.add_argument(
        "--command-arg",
        action="append",
        default=[],
        help="one adapter argv item; use --command-arg=--flag for leading dashes",
    )
    generate.add_argument("--command-cwd", type=Path)
    generate.add_argument("--parameters", type=Path, help="provider parameters JSON object")
    generate.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR)
    generate.add_argument("--timeout-seconds", type=_positive_float, default=120.0)
    generate.add_argument("--max-source-mb", type=_positive_int, default=64)
    generate.add_argument("--max-total-source-mb", type=_positive_int, default=128)
    generate.add_argument("--max-evidence-chars", type=_positive_int, default=2_000_000)
    generate.add_argument(
        "--max-total-evidence-chars", type=_positive_int, default=4_000_000
    )
    generate.add_argument("--max-pdf-pages", type=_positive_int, default=1_000)
    generate.add_argument("--chunk-chars", type=_positive_int, default=20_000)
    generate.add_argument("--max-provider-output-mb", type=_positive_int, default=4)
    generate.add_argument("--max-provider-error-kb", type=_positive_int, default=64)
    generate.add_argument(
        "--overwrite",
        action="store_true",
        help="atomically replace an existing project only after successful validation",
    )
    generation_action = generate.add_mutually_exclusive_group()
    generation_action.add_argument(
        "--build",
        action="store_true",
        help="create a candidate build after publishing the validated project",
    )
    generation_action.add_argument(
        "--publish",
        action="store_true",
        help="create a release build and fail unless every publication gate passes",
    )
    generate.add_argument("--build-out", type=Path, default=Path("dist"))
    generate.add_argument("--jobs", type=_positive_int, default=4)
    generate.add_argument("--seed", type=int)
    generate.add_argument("--instances", type=_positive_int)
    generate.add_argument("--difficulty", choices=LEVEL_NAMES)
    generate_resume = generate.add_mutually_exclusive_group()
    generate_resume.add_argument("--build-no-resume", action="store_true")
    generate_resume.add_argument("--build-force", action="store_true")

    build = sub.add_parser(
        "build",
        help="compile candidate packages and report (but do not require) publication readiness",
    )
    build.add_argument("project", type=Path)
    build.add_argument("--out", type=Path, default=Path("dist"))
    build.add_argument("--jobs", type=_positive_int, default=4)
    build.add_argument("--seed", type=int)
    build.add_argument("--instances", type=_positive_int)
    build.add_argument("--difficulty", choices=LEVEL_NAMES)
    build.add_argument(
        "--asset-cache",
        type=Path,
        help="content-addressed cache containing bytes pinned by asset_snapshots",
    )
    resume_group = build.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--no-resume",
        action="store_true",
        help="build only when no output with the same content ID exists",
    )

    publish = sub.add_parser(
        "publish",
        help="compile release packages and fail unless every publication gate passes",
    )
    publish.add_argument("project", type=Path)
    publish.add_argument("--out", type=Path, default=Path("dist"))
    publish.add_argument("--jobs", type=_positive_int, default=4)
    publish.add_argument("--seed", type=int)
    publish.add_argument("--instances", type=_positive_int)
    publish.add_argument("--difficulty", choices=LEVEL_NAMES)
    publish.add_argument(
        "--asset-cache",
        type=Path,
        help="content-addressed cache containing bytes pinned by asset_snapshots",
    )
    publish_resume = publish.add_mutually_exclusive_group()
    publish_resume.add_argument("--no-resume", action="store_true")
    publish_resume.add_argument("--force", action="store_true")
    resume_group.add_argument(
        "--force",
        action="store_true",
        help="quarantine any existing build with the same content ID and rebuild",
    )

    audit = sub.add_parser("audit", help="run schema, visibility, and syntax QA without packaging")
    audit.add_argument("project", type=Path)
    audit.add_argument("--seed", type=int)
    audit.add_argument("--instances", type=_positive_int)
    audit.add_argument("--difficulty", choices=LEVEL_NAMES)
    audit.add_argument(
        "--asset-cache",
        type=Path,
        help="content-addressed cache containing bytes pinned by asset_snapshots",
    )
    audit.add_argument(
        "--preflight-only",
        action="store_true",
        help="return success after static preflight even when publication gates are unrun or fail",
    )

    inspect = sub.add_parser("inspect", help="summarize evidence lineage and task candidates")
    inspect.add_argument("project", type=Path)

    validate = sub.add_parser("validate", help="validate a generated package directory or ZIP")
    validate.add_argument("path", type=Path)
    validate.add_argument("--max-uncompressed-mb", type=_positive_int, default=512)

    calibrate = sub.add_parser(
        "calibrate",
        help="summarize pass-rate trials against resolved difficulty target bands",
    )
    calibrate.add_argument("trials", type=Path)
    calibrate.add_argument(
        "--project",
        type=Path,
        help=(
            "validate trials against a project; v2 requires the exact project.lock.json "
            "paired with --catalog, while legacy v1 reports use project profiles"
        ),
    )
    calibrate.add_argument(
        "--catalog",
        type=Path,
        help=(
            "manifest-covered catalog.json for the exact v2 task builds; requires "
            "--project and is rejected for legacy v1 trials"
        ),
    )

    resolve_difficulty = sub.add_parser(
        "resolve-difficulty",
        help="resolve challenge, evaluation power, and benchmark sampling separately",
    )
    resolve_difficulty.add_argument("level", choices=LEVEL_NAMES)
    resolve_difficulty.add_argument(
        "--profile", type=Path, help="optional paper2ale.difficulty/v2 profile JSON"
    )
    resolve_difficulty.add_argument("--challenge-overrides", type=Path)
    resolve_difficulty.add_argument("--evaluation-overrides", type=Path)
    resolve_difficulty.add_argument("--sampling-overrides", type=Path)
    resolve_difficulty.add_argument(
        "--calibrated-semantic-id",
        help="check a persisted task calibration; requires --task-id and --task-build-id",
    )
    resolve_difficulty.add_argument("--task-id")
    resolve_difficulty.add_argument("--task-build-id")

    resolve_assets_parser = sub.add_parser(
        "resolve-assets",
        help="snapshot local code/data/document assets into path-free content locks",
    )
    resolve_assets_parser.add_argument(
        "spec", type=Path, help="JSON array of {asset_id,path,kind?,metadata?} objects"
    )
    resolve_assets_parser.add_argument(
        "--cache", type=Path, help="optional content-addressed raw-byte cache"
    )
    resolve_assets_parser.add_argument("--max-assets", type=_positive_int, default=256)
    resolve_assets_parser.add_argument("--max-files", type=_positive_int, default=5000)
    resolve_assets_parser.add_argument("--max-file-mb", type=_positive_int, default=32)
    resolve_assets_parser.add_argument("--max-total-mb", type=_positive_int, default=256)

    triage = sub.add_parser(
        "triage-paper",
        help="apply deterministic suitability policy to an evidence-backed paper profile",
    )
    triage.add_argument("profile", type=Path)
    triage.add_argument("--policy", type=Path)
    triage.add_argument(
        "--require-eligible",
        action="store_true",
        help="return status 2 unless the decision is eligible",
    )

    orchestrate = sub.add_parser(
        "orchestrate",
        help=(
            "run fail-closed triage, staged evidence extraction, workflow synthesis, "
            "trusted task compilation, audit, and optional release packaging"
        ),
    )
    orchestrate.add_argument(
        "manifest", type=Path, help="paper2ale.orchestration-manifest/v1 JSON"
    )
    orchestration_provider = orchestrate.add_mutually_exclusive_group(required=True)
    orchestration_provider.add_argument("--replay", type=Path)
    orchestration_provider.add_argument(
        "--command",
        dest="provider_command",
        help="structured-completion adapter invoked directly (never through a shell)",
    )
    orchestrate.add_argument(
        "--command-arg",
        action="append",
        default=[],
        help="one adapter argv item; use --command-arg=--flag for leading dashes",
    )
    orchestrate.add_argument("--command-cwd", type=Path)
    orchestrate.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR)
    orchestrate.add_argument("--asset-cache", type=Path)
    orchestrate.add_argument("--max-asset-files", type=_positive_int, default=5_000)
    orchestrate.add_argument("--max-asset-file-mb", type=_positive_int, default=32)
    orchestrate.add_argument("--max-total-asset-mb", type=_positive_int, default=256)
    orchestrate.add_argument("--max-asset-depth", type=_positive_int, default=32)
    orchestrate.add_argument(
        "--max-asset-text-chars", type=_positive_int, default=2_000_000
    )
    orchestrate.add_argument(
        "--max-total-asset-text-chars", type=_positive_int, default=8_000_000
    )
    orchestrate.add_argument("--max-asset-pdf-pages", type=_positive_int, default=1_000)
    orchestrate.add_argument("--max-provider-output-mb", type=_positive_int, default=4)
    orchestrate.add_argument("--max-provider-error-kb", type=_positive_int, default=64)
    orchestrate.add_argument(
        "--build-out",
        type=Path,
        default=Path("dist"),
        help="release package destination when manifest.release is true",
    )
    orchestrate.add_argument("--jobs", type=_positive_int, default=4)
    orchestrate.add_argument(
        "--seed",
        type=int,
        help="reserved; orchestration uses the generated project's pinned defaults",
    )
    orchestrate.add_argument(
        "--instances",
        type=_positive_int,
        help="reserved; orchestration uses the generated project's pinned defaults",
    )
    orchestration_resume = orchestrate.add_mutually_exclusive_group()
    orchestration_resume.add_argument("--no-resume", action="store_true")
    orchestration_resume.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "generate":
            if args.replay is not None:
                if args.command_arg or args.command_cwd is not None:
                    raise ValueError(
                        "--command-arg and --command-cwd require --command, not --replay"
                    )
                provider = ReplayProvider(args.replay)
            else:
                provider = CommandProvider(
                    [args.provider_command, *args.command_arg],
                    cwd=args.command_cwd,
                    max_output_bytes=args.max_provider_output_mb * 1024 * 1024,
                    max_error_bytes=args.max_provider_error_kb * 1024,
                )
            metadata = [load_source_metadata(path) for path in args.metadata]
            sources = ingest_sources(
                args.sources,
                metadata,
                max_source_bytes=args.max_source_mb * 1024 * 1024,
                max_total_source_bytes=args.max_total_source_mb * 1024 * 1024,
                max_evidence_chars=args.max_evidence_chars,
                max_total_evidence_chars=args.max_total_evidence_chars,
                max_pdf_pages=args.max_pdf_pages,
                chunk_chars=args.chunk_chars,
            )
            parameters = (
                None
                if args.parameters is None
                else load_json_object(args.parameters, name="provider parameters")
            )
            generated = generate_project(
                sources,
                provider,
                args.out,
                project_id=args.project_id,
                schema_dir=args.schema_dir,
                parameters=parameters,
                timeout_s=args.timeout_seconds,
                overwrite=args.overwrite,
                difficulty=args.difficulty,
            )
            if not (args.build or args.publish):
                _print_json(generated.to_dict())
                return 0
            build_function = publish_project if args.publish else build_project
            built = build_function(
                generated.output_path,
                args.build_out,
                jobs=args.jobs,
                master_seed=args.seed,
                instances=args.instances,
                resume=not (args.build_no_resume or args.build_force),
                force=args.build_force,
                difficulty_level=args.difficulty,
            )
            _print_json({"generation": generated.to_dict(), "build": built.to_dict()})
            return 0
        if args.command == "build":
            result = build_project(
                args.project,
                args.out,
                jobs=args.jobs,
                master_seed=args.seed,
                instances=args.instances,
                difficulty_level=args.difficulty,
                asset_cache=args.asset_cache,
                resume=not (args.no_resume or args.force),
                force=args.force,
            )
            _print_json(result.to_dict())
            return 0
        if args.command == "publish":
            result = publish_project(
                args.project,
                args.out,
                jobs=args.jobs,
                master_seed=args.seed,
                instances=args.instances,
                difficulty_level=args.difficulty,
                asset_cache=args.asset_cache,
                resume=not (args.no_resume or args.force),
                force=args.force,
            )
            _print_json(result.to_dict())
            return 0
        if args.command == "audit":
            report = audit_project(
                args.project,
                master_seed=args.seed,
                instances=args.instances,
                difficulty_level=args.difficulty,
                asset_cache=args.asset_cache,
            )
            _print_json(report)
            gate = "preflight_passed" if args.preflight_only else "publication_ready"
            return 0 if report.get(gate) else 2
        if args.command == "inspect":
            _print_json(inspect_project(args.project))
            return 0
        if args.command == "validate":
            if args.path.is_dir():
                issues = validate_package_dir(args.path)
            else:
                issues = validate_archive(
                    args.path,
                    max_uncompressed_bytes=args.max_uncompressed_mb * 1024 * 1024,
                )
            normalized = [_issue_dict(issue) for issue in issues]
            passed = not any(issue.get("severity", "error") == "error" for issue in normalized)
            _print_json({"passed": passed, "path": str(args.path), "issues": normalized})
            return 0 if passed else 2
        if args.command == "calibrate":
            report = _calibration_report(args.trials, args.project, args.catalog)
            _print_json(report)
            gate = (
                "verified_claim_ready"
                if report.get("schema_version") == "paper2ale.calibration-report/v2"
                else "all_calibrated"
            )
            return 0 if report.get(gate) else 2
        if args.command == "resolve-difficulty":
            profile = (
                None
                if args.profile is None
                else load_json_object(args.profile, name="difficulty v2 profile")
            )
            challenge = (
                None
                if args.challenge_overrides is None
                else load_json_object(
                    args.challenge_overrides, name="challenge overrides"
                )
            )
            evaluation = (
                None
                if args.evaluation_overrides is None
                else load_json_object(
                    args.evaluation_overrides, name="evaluation overrides"
                )
            )
            sampling = (
                None
                if args.sampling_overrides is None
                else load_json_object(
                    args.sampling_overrides, name="sampling overrides"
                )
            )
            resolved = resolve_difficulty_v2(
                args.level,
                profile=profile,
                challenge_overrides=challenge,
                evaluation_power_overrides=evaluation,
                benchmark_sampling_overrides=sampling,
            )
            task_context = (args.task_id, args.task_build_id)
            if (args.task_id is None) != (args.task_build_id is None):
                raise ValueError("--task-id and --task-build-id must be supplied together")
            if args.calibrated_semantic_id is not None and args.task_id is None:
                raise ValueError(
                    "--calibrated-semantic-id requires --task-id and --task-build-id "
                    "so calibration is bound to exact task bytes"
                )
            if args.task_id is None:
                validity = assess_calibration_validity(resolved, None)
                identity_scope = "difficulty_only"
            else:
                validity = assess_task_calibration_validity(
                    resolved,
                    args.calibrated_semantic_id,
                    task_id=task_context[0],
                    task_build_id=task_context[1],
                )
                identity_scope = "task_build"
            _print_json(
                {
                    "schema_version": "paper2ale.difficulty-resolution/v2",
                    "difficulty": resolved.to_dict(),
                    "calibration_identity_scope": identity_scope,
                    "calibration_validity": validity.to_dict(),
                }
            )
            return 0
        if args.command == "resolve-assets":
            raw_specs = load_json_value(args.spec, name="asset specifications")
            if not isinstance(raw_specs, list) or not raw_specs:
                raise ValueError("asset specifications must be a nonempty JSON array")
            specs: list[AssetSpec] = []
            for index, value in enumerate(raw_specs):
                if not isinstance(value, dict):
                    raise ValueError(f"asset specification {index} must be an object")
                unknown = sorted(set(value) - {"asset_id", "path", "kind", "metadata"})
                missing = sorted({"asset_id", "path"} - set(value))
                if missing or unknown:
                    detail = f"missing {missing}" if missing else f"unknown fields {unknown}"
                    raise ValueError(f"asset specification {index} has {detail}")
                specs.append(
                    AssetSpec(
                        asset_id=value["asset_id"],
                        path=value["path"],
                        kind=value.get("kind", "auto"),
                        metadata=value.get("metadata", {}),
                    )
                )
            cache = None if args.cache is None else AssetCache(args.cache)
            snapshots = resolve_assets(
                specs,
                cache=cache,
                limits=AssetLimits(
                    max_files=args.max_files,
                    max_file_bytes=args.max_file_mb * 1024 * 1024,
                    max_total_bytes=args.max_total_mb * 1024 * 1024,
                ),
                max_assets=args.max_assets,
            )
            _print_json(
                {
                    "schema_version": "paper2ale.asset-bundle/v1",
                    "asset_bundle_digest": asset_bundle_digest(snapshots),
                    "assets": [snapshot.to_dict() for snapshot in snapshots],
                }
            )
            return 0
        if args.command == "triage-paper":
            profile_data = load_json_object(args.profile, name="paper profile")
            policy_data = (
                {}
                if args.policy is None
                else load_json_object(args.policy, name="triage policy")
            )
            try:
                profile = PaperProfile(**profile_data)
                policy = TriagePolicy(**policy_data)
            except TypeError as error:
                raise ValueError(f"invalid triage fields: {error}") from error
            report = triage_paper(profile, policy=policy)
            _print_json(report.to_dict())
            return 0 if report.accepted or not args.require_eligible else 2
        if args.command == "orchestrate":
            if args.seed is not None or args.instances is not None:
                raise ValueError(
                    "orchestrate does not accept --seed or --instances overrides; "
                    "the generated project's pinned defaults are authoritative"
                )
            if args.replay is not None:
                if args.command_arg or args.command_cwd is not None:
                    raise ValueError(
                        "--command-arg and --command-cwd require --command, not --replay"
                    )
                provider = ReplayProvider(args.replay)
            else:
                provider = CommandProvider(
                    [args.provider_command, *args.command_arg],
                    cwd=args.command_cwd,
                    max_output_bytes=args.max_provider_output_mb * 1024 * 1024,
                    max_error_bytes=args.max_provider_error_kb * 1024,
                )
            manifest = load_orchestration_manifest(args.manifest)
            orchestration_asset_cache = (
                None if args.asset_cache is None else AssetCache(args.asset_cache)
            )

            def audit_callback(path: Path) -> dict[str, Any]:
                return audit_project(
                    path,
                    master_seed=None,
                    instances=None,
                    asset_cache=orchestration_asset_cache,
                )

            receipt = orchestrate_project(
                manifest,
                provider,
                schema_dir=args.schema_dir,
                asset_cache=orchestration_asset_cache,
                asset_limits=AssetLimits(
                    max_files=args.max_asset_files,
                    max_file_bytes=args.max_asset_file_mb * 1024 * 1024,
                    max_total_bytes=args.max_total_asset_mb * 1024 * 1024,
                    max_depth=args.max_asset_depth,
                    max_text_chars_per_file=args.max_asset_text_chars,
                    max_total_text_chars=args.max_total_asset_text_chars,
                    max_pdf_pages=args.max_asset_pdf_pages,
                ),
                audit_callback=audit_callback,
            )
            result: dict[str, Any] = {"orchestration": receipt.to_dict()}
            if manifest.release:
                build = publish_project(
                    manifest.output_path,
                    args.build_out,
                    jobs=args.jobs,
                    master_seed=None,
                    instances=None,
                    resume=not (args.no_resume or args.force),
                    force=args.force,
                    asset_cache=orchestration_asset_cache,
                )
                result["build"] = build.to_dict()
            _print_json(result)
            return 0
    except (OSError, TypeError, ValueError, RuntimeError, KeyError) as exc:
        print(f"paper2ale: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 2
