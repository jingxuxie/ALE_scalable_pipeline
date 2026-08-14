"""Validated probabilistic generation before deterministic compilation.

This module is intentionally upstream of :mod:`paper2ale.pipeline`.  It turns
bounded local-source extractions into one provider-neutral completion request,
rejects untrusted output unless it is a compilable project candidate, and
publishes canonical JSON atomically.  It never compiles or packages a task.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import resources
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from .difficulty import LEVEL_NAMES, apply_difficulty_override
from .extraction import build_extraction_request
from .providers import CompletionProvider, CompletionRequest
from .schema import canonical_json_bytes, require_valid_project, validate_project
from .source_ingest import IngestedSource, load_json_object, source_bundle
from .task_families import (
    registered_capability_catalog,
    registered_task_families,
    task_family,
)


_SOURCE_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
_INSTALLED_SCHEMA_DIR = Path(str(resources.files("paper2ale").joinpath("schemas")))
DEFAULT_SCHEMA_DIR = (
    _SOURCE_SCHEMA_DIR
    if (_SOURCE_SCHEMA_DIR / "project.schema.json").is_file()
    else _INSTALLED_SCHEMA_DIR
)
_SUCCESSFUL_FINISH_REASONS = frozenset(
    {"complete", "completed", "end_turn", "replay", "stop", "success"}
)


class GenerationProviderError(RuntimeError):
    """A provider failed without exposing adapter stderr or credentials."""


@dataclass(frozen=True, slots=True)
class GenerationResult:
    project: Mapping[str, Any]
    output_path: str
    project_sha256: str
    request_id: str
    response_data_sha256: str
    provider_raw_digest: str
    finish_reason: str
    usage: Mapping[str, int]
    source_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "paper2ale.generation/v1",
            "project_id": self.project["project_id"],
            "output_path": self.output_path,
            "project_sha256": self.project_sha256,
            "request_id": self.request_id,
            "response_data_sha256": self.response_data_sha256,
            "provider_raw_digest": self.provider_raw_digest,
            "finish_reason": self.finish_reason,
            "usage": dict(self.usage),
            "source_count": self.source_count,
            "status": "validated_candidate",
        }


def _strict_json_copy(value: Any, *, name: str) -> Any:
    try:
        return json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must contain only strict JSON values") from error


def _rewrite_refs(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                rewritten[key] = replacements.get(item, item)
            else:
                rewritten[key] = _rewrite_refs(item, replacements)
        return rewritten
    if isinstance(value, list):
        return [_rewrite_refs(item, replacements) for item in value]
    return value


def _namespace_schema(
    document: Mapping[str, Any], namespace: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    schema = _strict_json_copy(document, name=f"{namespace} schema")
    schema.pop("$schema", None)
    schema.pop("$id", None)
    definitions = schema.pop("$defs", {})
    if not isinstance(definitions, dict):
        raise ValueError(f"{namespace} schema $defs must be an object")
    replacements = {
        f"#/$defs/{name}": f"#/$defs/{namespace}_{name}"
        for name in definitions
    }
    core = _rewrite_refs(schema, replacements)
    namespaced = {
        f"{namespace}_{name}": _rewrite_refs(definition, replacements)
        for name, definition in definitions.items()
    }
    return core, namespaced


def load_project_output_schema(
    schema_dir: str | os.PathLike[str] = DEFAULT_SCHEMA_DIR,
) -> dict[str, Any]:
    """Load project schemas and return one provider-portable schema document."""

    root = Path(schema_dir)
    project = load_json_object(root / "project.schema.json", name="project schema")
    evidence = load_json_object(
        root / "evidence_graph.schema.json", name="evidence graph schema"
    )
    task = load_json_object(root / "task_blueprint.schema.json", name="task schema")
    difficulty = load_json_object(
        root / "difficulty_profile.schema.json", name="difficulty schema"
    )

    evidence_core, evidence_defs = _namespace_schema(evidence, "evidence")
    task_core, task_defs = _namespace_schema(task, "task")
    difficulty_core, difficulty_defs = _namespace_schema(difficulty, "difficulty")
    project_core, project_defs = _namespace_schema(project, "project")
    project_core = _rewrite_refs(
        project_core,
        {
            "evidence_graph.schema.json": "#/$defs/evidence_graph",
            "task_blueprint.schema.json": "#/$defs/task_blueprint",
            "difficulty_profile.schema.json": "#/$defs/difficulty_profile",
        },
    )
    task_core = _rewrite_refs(
        task_core,
        {
            "difficulty_profile.schema.json#/$defs/selection": (
                "#/$defs/difficulty_selection"
            )
        },
    )
    # One-shot generation may propose only families with a reviewed candidate
    # compiler.  Fixed families are authored-project fixtures: letting a model
    # select one would attach canned executable semantics to arbitrary model-
    # authored evidence.  The provider also may not author workflow_binding;
    # generate_project attaches a caller-supplied, locally trusted binding only
    # after the response has crossed the provider trust boundary.
    capabilities = _generation_capabilities()
    task_properties = task_core.get("properties")
    if not isinstance(task_properties, dict):
        raise ValueError("task schema must define object properties")
    task_properties["family"] = {"enum": sorted(capabilities)}
    task_properties["protocol"] = {"type": "object"}
    task_properties["workflow_binding"] = False
    family_specs = registered_task_families()
    conditions: list[dict[str, Any]] = []
    for family_name, capability in sorted(capabilities.items()):
        then: dict[str, Any] = {}
        task_ids = capability.get("task_ids", [])
        if task_ids:
            then.setdefault("properties", {})["id"] = {"enum": task_ids}
        family_schema = family_specs[family_name].protocol_schema()
        if family_schema is not None:
            then.setdefault("properties", {})["protocol"] = family_schema
            then["required"] = ["protocol"]
        else:
            then["not"] = {"required": ["protocol"]}
        conditions.append(
            {
                "if": {
                    "properties": {"family": {"const": family_name}},
                    "required": ["family"],
                },
                "then": then,
            }
        )
    existing_conditions = task_core.get("allOf", [])
    if not isinstance(existing_conditions, list):
        raise ValueError("task schema allOf must be an array")
    # The shipped publication schema requires a persisted generic binding.
    # That is correct for a finished project but impossible at the untrusted
    # provider boundary, where bindings are explicitly forbidden.  Remove only
    # that requirement in the provider-facing copy.
    for condition in existing_conditions:
        if not isinstance(condition, dict):
            continue
        then = condition.get("then")
        if not isinstance(then, dict):
            continue
        required = then.get("required")
        if isinstance(required, list):
            then["required"] = [
                item for item in required if item != "workflow_binding"
            ]
    task_core["allOf"] = [*existing_conditions, *conditions]
    definitions = {
        **project_defs,
        "evidence_graph": evidence_core,
        **evidence_defs,
        "task_blueprint": task_core,
        **task_defs,
        "difficulty_profile": difficulty_core,
        **difficulty_defs,
    }
    project_core["$defs"] = definitions
    return project_core


def _generation_capabilities() -> dict[str, dict[str, Any]]:
    """Capabilities an untrusted one-shot provider is allowed to propose."""

    families = registered_task_families()
    capabilities = registered_capability_catalog()
    supported = {
        name: capability
        for name, capability in capabilities.items()
        if families[name].candidate_validator is not None
    }
    if not supported:
        raise ValueError(
            "one-shot generation has no registered reviewed candidate compiler; "
            "use 'paper2ale orchestrate' to mine and bind workflow candidates"
        )
    return supported


def _evidence_document(
    sources: Sequence[IngestedSource],
    *,
    project_id: str,
    difficulty: str | None,
) -> str:
    document = {
        "schema_version": "paper2ale.extracted-sources/v1",
        "requested_project_id": project_id,
        "requested_difficulty": difficulty,
        "trusted_compiler_capabilities": _generation_capabilities(),
        "documents": [
            {
                "source_id": source.source_ref["id"],
                "sha256": source.source_ref["sha256"],
                "media_type": source.media_type,
                "extractor": source.extractor,
                "size_bytes": source.size_bytes,
                "chunks": [chunk.to_dict() for chunk in source.chunks],
            }
            for source in sources
        ],
    }
    return canonical_json_bytes(document).decode("utf-8")


def _bound_output_schema(
    output_schema: Mapping[str, Any],
    *,
    project_id: str,
    sources: Sequence[IngestedSource],
    require_tasks: bool,
) -> dict[str, Any]:
    schema = _strict_json_copy(output_schema, name="output schema")
    if not isinstance(schema, dict):
        raise TypeError("output schema must be an object")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("project output schema must define object properties")
    properties["project_id"] = {"const": project_id}
    properties["source_bundle"] = {"const": source_bundle(sources)}
    tasks = properties.get("tasks")
    if require_tasks:
        if not isinstance(tasks, dict):
            raise ValueError("project output schema must define tasks as an array")
        tasks["minItems"] = max(1, int(tasks.get("minItems", 0)))
    return schema


def prepare_generation_request(
    sources: Sequence[IngestedSource],
    *,
    project_id: str,
    output_schema: Mapping[str, Any] | None = None,
    schema_dir: str | os.PathLike[str] = DEFAULT_SCHEMA_DIR,
    parameters: Mapping[str, Any] | None = None,
    timeout_s: float = 120.0,
    require_tasks: bool = True,
    difficulty: str | None = None,
) -> CompletionRequest:
    """Construct the exact provider-neutral request used by generation."""

    if not sources:
        raise ValueError("generation requires at least one ingested source")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be a nonempty string")
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise TypeError("timeout_s must be a number")
    timeout = float(timeout_s)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_s must be positive and finite")
    if difficulty is not None and difficulty not in LEVEL_NAMES:
        raise ValueError(f"difficulty must be one of {', '.join(LEVEL_NAMES)}")
    # Validate the caller-controlled project identity and pinned source bundle
    # without treating this request-construction placeholder as a completed
    # project.  Finished provider output is still required to contain a task.
    placeholder_issues = validate_project(
        {
            "schema_version": "paper2ale.project/v1",
            "project_id": project_id,
            "source_bundle": source_bundle(sources),
            "evidence_graph": {"records": [], "nodes": [], "edges": [], "claims": []},
            "tasks": [],
        }
    )
    identity_issues = tuple(
        issue
        for issue in placeholder_issues
        if not (issue.path == "/tasks" and issue.code == "invalid_value")
    )
    if identity_issues:
        details = "\n".join(
            f"- {issue.path or '/'}: [{issue.code}] {issue.message}"
            for issue in identity_issues
        )
        raise ValueError(f"invalid generation identity or source bundle:\n{details}")
    schema = load_project_output_schema(schema_dir) if output_schema is None else output_schema
    bound_schema = _bound_output_schema(
        schema,
        project_id=project_id,
        sources=sources,
        require_tasks=require_tasks,
    )
    base = build_extraction_request(
        source_bundle(sources),
        _evidence_document(
            sources,
            project_id=project_id,
            difficulty=difficulty,
        ),
        output_schema=bound_schema,
        parameters=parameters,
    )
    return CompletionRequest(
        messages=base.messages,
        output_schema=base.output_schema,
        parameters=base.parameters,
        timeout_s=timeout,
        idempotency_key=base.idempotency_key,
    )


def _validate_generated_project(
    data: Mapping[str, Any],
    *,
    expected_project_id: str,
    expected_sources: Sequence[IngestedSource],
    require_tasks: bool,
    trusted_workflow_bindings: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    prepared = _strict_json_copy(data, name="provider response")
    if not isinstance(prepared, dict):
        raise TypeError("provider response must be a project object")
    if prepared.get("project_id") != expected_project_id:
        raise ValueError(
            f"generated project_id must equal requested project id {expected_project_id!r}"
        )
    if canonical_json_bytes(prepared.get("source_bundle")) != canonical_json_bytes(
        source_bundle(expected_sources)
    ):
        raise ValueError("generated project source_bundle must exactly match pinned sources")
    raw_tasks = prepared.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ValueError("generated project tasks must be an array")
    if require_tasks and not raw_tasks:
        raise ValueError("generated project must contain at least one task")
    trusted = {} if trusted_workflow_bindings is None else dict(
        trusted_workflow_bindings
    )
    task_ids: list[str] = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            raise ValueError("generated project tasks must contain only objects")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("generated task id must be a nonempty string")
        task_ids.append(task_id)
        if "workflow_binding" in task:
            raise ValueError(
                "one-shot providers may not supply workflow_binding; use "
                "'paper2ale orchestrate' to mine and bind workflow candidates locally"
            )
        spec = task_family(str(task.get("family", "")))
        if spec.candidate_validator is None:
            raise ValueError(
                f"one-shot generation rejects authored-only task family {spec.name!r}; "
                "use a reviewed authored project for that family or run "
                "'paper2ale orchestrate'"
            )
        binding = trusted.get(task_id)
        if not isinstance(binding, Mapping):
            raise ValueError(
                f"generated task {task_id!r} lacks a locally trusted workflow binding; "
                "use 'paper2ale orchestrate' to mine and bind candidates end to end"
            )
        task["workflow_binding"] = _strict_json_copy(
            binding, name=f"trusted workflow binding for {task_id!r}"
        )
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("generated task IDs must be unique")
    unused_bindings = sorted(set(trusted) - set(task_ids))
    if unused_bindings:
        raise ValueError(
            "trusted workflow bindings contain unknown task IDs: "
            + ", ".join(unused_bindings)
        )
    project = require_valid_project(prepared)
    for task in project["tasks"]:
        task_family(str(task["family"])).validate_task(task, require_binding=True)
    return project


def apply_supported_difficulty(
    project: Mapping[str, Any], level: str
) -> dict[str, Any]:
    """Apply a concrete profile only when every trusted family supports it."""

    if level not in LEVEL_NAMES:
        raise ValueError(f"difficulty must be one of {', '.join(LEVEL_NAMES)}")
    for task in project.get("tasks", []):
        spec = task_family(str(task["family"]))
        if level not in spec.supported_difficulty_levels:
            supported = ", ".join(spec.supported_difficulty_levels) or "none"
            raise ValueError(
                f"task family {spec.name!r} does not support difficulty {level!r}; "
                f"supported levels: {supported}"
            )
    transformed = apply_difficulty_override(project, level)
    return require_valid_project(transformed)


def _check_destination(
    destination: Path,
    *,
    sources: Sequence[IngestedSource],
    overwrite: bool,
) -> None:
    if destination.is_symlink():
        raise ValueError(f"generation output must not be a symbolic link: {destination}")
    destination_resolved = destination.resolve(strict=False)
    for source in sources:
        if destination_resolved == Path(source.local_path).resolve():
            raise ValueError("generation output must not overwrite a local source file")
    if destination.exists():
        if not destination.is_file():
            raise ValueError(f"generation output is not a regular file: {destination}")
        if not overwrite:
            raise FileExistsError(
                f"generation output already exists: {destination}; use --overwrite"
            )


def _publish_project_bytes(destination: Path, data: bytes, *, overwrite: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.chmod(temporary_name, 0o644)
        if overwrite:
            os.replace(temporary_name, destination)
            temporary_name = None
        else:
            try:
                os.link(temporary_name, destination)
            except FileExistsError as error:
                raise FileExistsError(
                    f"generation output appeared concurrently: {destination}"
                ) from error
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def generate_project(
    sources: Sequence[IngestedSource],
    provider: CompletionProvider,
    destination: str | os.PathLike[str],
    *,
    project_id: str,
    output_schema: Mapping[str, Any] | None = None,
    schema_dir: str | os.PathLike[str] = DEFAULT_SCHEMA_DIR,
    parameters: Mapping[str, Any] | None = None,
    timeout_s: float = 120.0,
    require_tasks: bool = True,
    overwrite: bool = False,
    difficulty: str | None = None,
    trusted_workflow_bindings: Mapping[str, Mapping[str, Any]] | None = None,
) -> GenerationResult:
    """Generate and publish only locally bound compiler input.

    The completion provider is untrusted and cannot author workflow bindings or
    select fixed authored-only families.  A caller must supply bindings produced
    by a trusted local workflow/candidate stage.  The CLI deliberately does not
    accept such bindings; use ``paper2ale orchestrate`` for the supported end-to-
    end path.
    """

    output_path = Path(destination)
    _check_destination(output_path, sources=sources, overwrite=overwrite)
    if require_tasks and trusted_workflow_bindings is None:
        raise ValueError(
            "one-shot generate cannot establish trusted workflow bindings; use "
            "'paper2ale orchestrate' for end-to-end task generation"
        )
    request = prepare_generation_request(
        sources,
        project_id=project_id,
        output_schema=output_schema,
        schema_dir=schema_dir,
        parameters=parameters,
        timeout_s=timeout_s,
        require_tasks=require_tasks,
        difficulty=difficulty,
    )
    try:
        response = provider.complete(request)
    except Exception as error:
        raise GenerationProviderError(
            f"completion provider {type(provider).__name__} failed for request "
            f"{request.idempotency_key} ({type(error).__name__}); adapter details suppressed"
        ) from error
    if response.finish_reason.strip().casefold() not in _SUCCESSFUL_FINISH_REASONS:
        raise ValueError(
            f"provider did not complete generation successfully: {response.finish_reason}"
        )
    project = _validate_generated_project(
        response.data,
        expected_project_id=project_id,
        expected_sources=sources,
        require_tasks=require_tasks,
        trusted_workflow_bindings=trusted_workflow_bindings,
    )
    if difficulty is not None:
        project = apply_supported_difficulty(project, difficulty)
    project_bytes = canonical_json_bytes(project) + b"\n"
    project_digest = hashlib.sha256(project_bytes).hexdigest()
    response_digest = hashlib.sha256(canonical_json_bytes(response.data)).hexdigest()
    _publish_project_bytes(output_path, project_bytes, overwrite=overwrite)

    # Treat publication as complete only after a strict read-back validation.
    published = load_json_object(output_path, name="generated project")
    require_valid_project(published)
    if canonical_json_bytes(published) != canonical_json_bytes(project):
        raise RuntimeError("generated project changed during atomic publication")
    return GenerationResult(
        project=project,
        output_path=str(output_path.resolve()),
        project_sha256=project_digest,
        request_id=request.idempotency_key,
        response_data_sha256=response_digest,
        provider_raw_digest=response.raw_digest,
        finish_reason=response.finish_reason,
        usage=dict(response.usage),
        source_count=len(sources),
    )


__all__ = [
    "DEFAULT_SCHEMA_DIR",
    "GenerationProviderError",
    "GenerationResult",
    "apply_supported_difficulty",
    "generate_project",
    "load_project_output_schema",
    "prepare_generation_request",
]
