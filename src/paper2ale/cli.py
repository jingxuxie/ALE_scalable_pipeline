"""Command-line interface for the deterministic compiler and audits."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence

from .difficulty import LEVEL_NAMES, resolve_task_difficulty, summarize_calibration
from .generation import (
    DEFAULT_SCHEMA_DIR,
    generate_project,
)
from .pipeline import audit_project, build_project, inspect_project, validate_archive
from .providers import CommandProvider, ReplayProvider
from .schema import load_project, require_valid_project
from .source_ingest import (
    ingest_sources,
    load_json_object,
    load_json_value,
    load_source_metadata,
)
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


def _calibration_report(trials_path: Path, project_path: Path | None) -> dict[str, Any]:
    payload = load_json_value(trials_path, name="calibration trials")
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

    required = {"task_id", "level", "passed"}
    allowed_row = required | {"score", "model", "agent"}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
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
        grouped.setdefault((task_id, level), []).append(row)

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
        reports.append(
            {
                "task_id": task_id,
                "level": level,
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
    generate.add_argument(
        "--build",
        action="store_true",
        help="run the deterministic compiler after publishing the validated project",
    )
    generate.add_argument("--build-out", type=Path, default=Path("dist"))
    generate.add_argument("--jobs", type=_positive_int, default=4)
    generate.add_argument("--seed", type=int)
    generate.add_argument("--instances", type=_positive_int)
    generate.add_argument("--difficulty", choices=LEVEL_NAMES)
    generate_resume = generate.add_mutually_exclusive_group()
    generate_resume.add_argument("--build-no-resume", action="store_true")
    generate_resume.add_argument("--build-force", action="store_true")

    build = sub.add_parser("build", help="compile and package every task in a project")
    build.add_argument("project", type=Path)
    build.add_argument("--out", type=Path, default=Path("dist"))
    build.add_argument("--jobs", type=_positive_int, default=4)
    build.add_argument("--seed", type=int)
    build.add_argument("--instances", type=_positive_int)
    build.add_argument("--difficulty", choices=LEVEL_NAMES)
    resume_group = build.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--no-resume",
        action="store_true",
        help="build only when no output with the same content ID exists",
    )
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
        help="project providing custom task difficulty profiles; defaults to core profile",
    )
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
            if not args.build:
                _print_json(generated.to_dict())
                return 0
            built = build_project(
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
            )
            _print_json(report)
            return 0 if report.get("preflight_passed") else 2
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
            report = _calibration_report(args.trials, args.project)
            _print_json(report)
            return 0 if report["all_calibrated"] else 2
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"paper2ale: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 2
