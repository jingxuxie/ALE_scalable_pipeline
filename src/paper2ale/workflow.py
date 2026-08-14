"""A declarative, evidence-linked workflow intermediate representation.

The IR describes *what* a research workflow does without granting generated
content authority to execute commands.  It contains no shell, Python, URL
fetch, or plugin fields.  Downstream task-family code remains responsible for
turning reviewed operations into trusted generators and evaluators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence


WORKFLOW_SCHEMA_VERSION = "paper2ale.workflow/v2"
ARTIFACT_ROLES = frozenset({"input", "intermediate", "output", "reference"})
ARTIFACT_AVAILABILITY = frozenset({"provided", "generated", "hidden", "external"})
ARTIFACT_ORIGINS = frozenset(
    {"asset", "trusted_generator", "participant", "trusted_evaluator", "external"}
)
OPERATION_TYPES = frozenset(
    {
        "acquire",
        "preprocess",
        "transform",
        "simulate",
        "train",
        "infer",
        "analyze",
        "aggregate",
        "visualize",
        "evaluate",
        "validate",
    }
)
OPERATION_AUTHORITIES = frozenset({"participant", "constructor", "trusted_evaluator"})

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_DESCRIPTION_CHARS = 8_000
_MAX_PARAMETERS_BYTES = 64 * 1024
_EXECUTABLE_PARAMETER_KEYS = frozenset(
    {
        "argv",
        "binary",
        "cmd",
        "code",
        "command",
        "container",
        "dockerfile",
        "endpoint",
        "entrypoint",
        "executable",
        "image",
        "module",
        "plugin",
        "python",
        "script",
        "shell",
        "url",
    }
)


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} must match {_IDENTIFIER.pattern}")
    return value


def _bounded_text(value: Any, name: str, *, maximum: int = _MAX_DESCRIPTION_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds the {maximum}-character limit")
    return value


def _strict_json(value: Any, name: str) -> Any:
    def reject_constant(token: str) -> None:
        raise ValueError(f"{name} contains non-finite number {token}")

    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must contain only strict JSON values") from error
    return json.loads(encoded, parse_constant=reject_constant)


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


def _reject_executable_parameters(value: Any, path: str = "operation.parameters") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key.casefold() in _EXECUTABLE_PARAMETER_KEYS:
                raise ValueError(
                    f"{path}.{key} is an executable field; workflow IR is declarative only"
                )
            _reject_executable_parameters(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_executable_parameters(item, f"{path}[{index}]")


def _id_tuple(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be an array of identifiers")
    result = tuple(_identifier(item, f"{name}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        raise ValueError(f"{name} contains duplicate identifiers")
    return result


def _asset_reference(value: Any) -> Mapping[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"asset_id", "relative_path"}:
        raise ValueError(
            "artifact.asset_ref must contain exactly asset_id and relative_path"
        )
    asset_id = _identifier(value["asset_id"], "artifact.asset_ref.asset_id")
    relative_path = _bounded_text(
        value["relative_path"],
        "artifact.asset_ref.relative_path",
        maximum=2_000,
    )
    parts = relative_path.split("/")
    if (
        relative_path.startswith("/")
        or "\\" in relative_path
        or ":" in relative_path
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("artifact.asset_ref.relative_path must be safe relative POSIX")
    return MappingProxyType(
        {"asset_id": asset_id, "relative_path": relative_path}
    )


@dataclass(frozen=True, slots=True)
class ArtifactNode:
    id: str
    role: str
    availability: str
    media_type: str
    description: str
    origin: str
    evidence_ids: tuple[str, ...] = ()
    asset_ref: Mapping[str, str] | None = None
    capability_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "artifact.id"))
        if self.role not in ARTIFACT_ROLES:
            raise ValueError(f"artifact.role must be one of {sorted(ARTIFACT_ROLES)}")
        if self.availability not in ARTIFACT_AVAILABILITY:
            raise ValueError(
                "artifact.availability must be one of "
                f"{sorted(ARTIFACT_AVAILABILITY)}"
            )
        object.__setattr__(self, "media_type", _bounded_text(self.media_type, "artifact.media_type", maximum=256))
        object.__setattr__(self, "description", _bounded_text(self.description, "artifact.description"))
        if self.origin not in ARTIFACT_ORIGINS:
            raise ValueError(
                f"artifact.origin must be one of {sorted(ARTIFACT_ORIGINS)}"
            )
        object.__setattr__(self, "evidence_ids", _id_tuple(self.evidence_ids, "artifact.evidence_ids"))
        object.__setattr__(self, "asset_ref", _asset_reference(self.asset_ref))
        if self.capability_ref is not None:
            object.__setattr__(
                self,
                "capability_ref",
                _identifier(self.capability_ref, "artifact.capability_ref"),
            )
        if self.role == "input" and self.availability not in {"provided", "external"}:
            raise ValueError("input artifacts must be provided or external")
        if self.role == "output" and self.availability != "generated":
            raise ValueError("output artifacts must have generated availability")
        if self.availability == "external" and self.origin != "external":
            raise ValueError("external artifacts must have external origin")
        if self.origin == "external" and self.availability != "external":
            raise ValueError("external origin requires external availability")
        if self.availability == "provided" and self.origin not in {
            "asset",
            "trusted_generator",
        }:
            raise ValueError(
                "provided artifacts require asset or trusted_generator origin"
            )
        if self.origin == "asset" and (
            self.asset_ref is None
            or self.role not in {"input", "reference"}
            or self.availability not in {"provided", "hidden"}
        ):
            raise ValueError(
                "asset origin requires asset_ref on a provided/hidden input or reference artifact"
            )
        if self.origin != "asset" and self.asset_ref is not None:
            raise ValueError("artifact.asset_ref is valid only for asset origin")
        if self.origin == "trusted_generator" and self.capability_ref is None:
            raise ValueError("trusted_generator origin requires capability_ref")
        if self.origin != "trusted_generator" and self.capability_ref is not None:
            raise ValueError(
                "artifact.capability_ref is valid only for trusted_generator origin"
            )
        if self.origin == "participant" and (
            self.availability != "generated"
            or self.role not in {"intermediate", "output"}
        ):
            raise ValueError(
                "participant origin requires a generated intermediate/output artifact"
            )
        if self.origin == "trusted_evaluator" and (
            self.availability not in {"generated", "hidden"}
            or self.role not in {"intermediate", "output", "reference"}
        ):
            raise ValueError(
                "trusted_evaluator origin requires a generated/hidden evaluator artifact"
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactNode":
        if not isinstance(value, Mapping):
            raise TypeError("artifact must be an object")
        allowed = {
            "id",
            "role",
            "availability",
            "media_type",
            "description",
            "origin",
            "evidence_ids",
            "asset_ref",
            "capability_ref",
        }
        required = allowed - {"evidence_ids", "asset_ref", "capability_ref"}
        unknown = set(value) - allowed
        missing = required - set(value)
        if unknown or missing:
            raise ValueError(
                f"artifact fields mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        return cls(
            id=value["id"],
            role=value["role"],
            availability=value["availability"],
            media_type=value["media_type"],
            description=value["description"],
            origin=value["origin"],
            evidence_ids=value.get("evidence_ids", ()),
            asset_ref=value.get("asset_ref"),
            capability_ref=value.get("capability_ref"),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "role": self.role,
            "availability": self.availability,
            "media_type": self.media_type,
            "description": self.description,
            "origin": self.origin,
            "evidence_ids": list(self.evidence_ids),
        }
        if self.asset_ref is not None:
            result["asset_ref"] = dict(self.asset_ref)
        if self.capability_ref is not None:
            result["capability_ref"] = self.capability_ref
        return result


@dataclass(frozen=True, slots=True)
class OperationNode:
    id: str
    operation_type: str
    authority: str
    description: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "operation.id"))
        if self.operation_type not in OPERATION_TYPES:
            raise ValueError(
                f"operation.operation_type must be one of {sorted(OPERATION_TYPES)}"
            )
        if self.authority not in OPERATION_AUTHORITIES:
            raise ValueError(
                f"operation.authority must be one of {sorted(OPERATION_AUTHORITIES)}"
            )
        object.__setattr__(self, "description", _bounded_text(self.description, "operation.description"))
        object.__setattr__(self, "inputs", _id_tuple(self.inputs, "operation.inputs"))
        object.__setattr__(self, "outputs", _id_tuple(self.outputs, "operation.outputs"))
        object.__setattr__(self, "evidence_ids", _id_tuple(self.evidence_ids, "operation.evidence_ids"))
        if not self.outputs:
            raise ValueError("operation.outputs must not be empty")
        if set(self.inputs) & set(self.outputs):
            raise ValueError("an operation cannot list the same artifact as input and output")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("operation.parameters must be an object")
        parameters = _strict_json(dict(self.parameters), "operation.parameters")
        if not isinstance(parameters, dict):
            raise TypeError("operation.parameters must be an object")
        _reject_executable_parameters(parameters)
        encoded = json.dumps(parameters, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(encoded) > _MAX_PARAMETERS_BYTES:
            raise ValueError(
                f"operation.parameters exceeds the {_MAX_PARAMETERS_BYTES}-byte limit"
            )
        object.__setattr__(self, "parameters", _freeze(parameters))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationNode":
        if not isinstance(value, Mapping):
            raise TypeError("operation must be an object")
        allowed = {
            "id",
            "operation_type",
            "authority",
            "description",
            "inputs",
            "outputs",
            "evidence_ids",
            "parameters",
        }
        required = allowed - {"evidence_ids", "parameters"}
        unknown = set(value) - allowed
        missing = required - set(value)
        if unknown or missing:
            raise ValueError(
                f"operation fields mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        return cls(
            id=value["id"],
            operation_type=value["operation_type"],
            authority=value["authority"],
            description=value["description"],
            inputs=value["inputs"],
            outputs=value["outputs"],
            evidence_ids=value.get("evidence_ids", ()),
            parameters=value.get("parameters", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operation_type": self.operation_type,
            "authority": self.authority,
            "description": self.description,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "evidence_ids": list(self.evidence_ids),
            "parameters": _thaw(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class WorkflowIR:
    id: str
    title: str
    artifacts: tuple[ArtifactNode, ...]
    operations: tuple[OperationNode, ...]
    outputs: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    schema_version: str = WORKFLOW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != WORKFLOW_SCHEMA_VERSION:
            raise ValueError(f"workflow schema_version must be {WORKFLOW_SCHEMA_VERSION!r}")
        object.__setattr__(self, "id", _identifier(self.id, "workflow.id"))
        object.__setattr__(self, "title", _bounded_text(self.title, "workflow.title", maximum=500))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "operations", tuple(self.operations))
        if any(not isinstance(item, ArtifactNode) for item in self.artifacts):
            raise TypeError("workflow.artifacts must contain ArtifactNode values")
        if any(not isinstance(item, OperationNode) for item in self.operations):
            raise TypeError("workflow.operations must contain OperationNode values")
        object.__setattr__(self, "outputs", _id_tuple(self.outputs, "workflow.outputs"))
        object.__setattr__(self, "evidence_ids", _id_tuple(self.evidence_ids, "workflow.evidence_ids"))
        if not self.artifacts or not self.operations or not self.outputs:
            raise ValueError("workflow requires artifacts, operations, and declared outputs")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowIR":
        if not isinstance(value, Mapping):
            raise TypeError("workflow must be an object")
        allowed = {
            "schema_version",
            "id",
            "title",
            "artifacts",
            "operations",
            "outputs",
            "evidence_ids",
        }
        required = allowed - {"evidence_ids"}
        unknown = set(value) - allowed
        missing = required - set(value)
        if unknown or missing:
            raise ValueError(
                f"workflow fields mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        artifacts = value["artifacts"]
        operations = value["operations"]
        if isinstance(artifacts, (str, bytes)) or not isinstance(artifacts, Sequence):
            raise TypeError("workflow.artifacts must be an array")
        if isinstance(operations, (str, bytes)) or not isinstance(operations, Sequence):
            raise TypeError("workflow.operations must be an array")
        return cls(
            schema_version=value["schema_version"],
            id=value["id"],
            title=value["title"],
            artifacts=tuple(ArtifactNode.from_dict(item) for item in artifacts),
            operations=tuple(OperationNode.from_dict(item) for item in operations),
            outputs=value["outputs"],
            evidence_ids=value.get("evidence_ids", ()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "title": self.title,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "operations": [item.to_dict() for item in self.operations],
            "outputs": list(self.outputs),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class WorkflowClosureReport:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    topological_order: tuple[str, ...]
    required_inputs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "topological_order": list(self.topological_order),
            "required_inputs": list(self.required_inputs),
        }


def validate_workflow_closure(
    workflow: WorkflowIR,
    *,
    require_self_contained: bool = True,
) -> WorkflowClosureReport:
    """Validate references, producer closure, acyclicity, and supplied inputs."""

    errors: list[str] = []
    warnings: list[str] = []
    artifacts: dict[str, ArtifactNode] = {}
    for artifact in workflow.artifacts:
        if artifact.id in artifacts:
            errors.append(f"duplicate artifact id {artifact.id!r}")
        else:
            artifacts[artifact.id] = artifact
    operations: dict[str, OperationNode] = {}
    for operation in workflow.operations:
        if operation.id in operations:
            errors.append(f"duplicate operation id {operation.id!r}")
        else:
            operations[operation.id] = operation

    producers: dict[str, str] = {}
    consumers: dict[str, set[str]] = {artifact_id: set() for artifact_id in artifacts}
    for operation in workflow.operations:
        for artifact_id in operation.inputs:
            if artifact_id not in artifacts:
                errors.append(
                    f"operation {operation.id!r} references unknown input {artifact_id!r}"
                )
            else:
                consumers[artifact_id].add(operation.id)
        for artifact_id in operation.outputs:
            if artifact_id not in artifacts:
                errors.append(
                    f"operation {operation.id!r} references unknown output {artifact_id!r}"
                )
            elif artifact_id in producers:
                errors.append(
                    f"artifact {artifact_id!r} has multiple producers: "
                    f"{producers[artifact_id]!r} and {operation.id!r}"
                )
            else:
                producers[artifact_id] = operation.id

    for artifact in workflow.artifacts:
        has_producer = artifact.id in producers
        if artifact.availability == "generated" and not has_producer:
            errors.append(f"generated artifact {artifact.id!r} has no producer")
        if artifact.availability in {"provided", "external"} and has_producer:
            errors.append(
                f"{artifact.availability} artifact {artifact.id!r} must not have a producer"
            )
        if artifact.role == "input" and consumers.get(artifact.id) == set():
            warnings.append(f"input artifact {artifact.id!r} is unused")
        producer_id = producers.get(artifact.id)
        producer = operations.get(producer_id) if producer_id is not None else None
        expected_authority = {
            "participant": "participant",
            "trusted_evaluator": "trusted_evaluator",
            "trusted_generator": "constructor",
        }.get(artifact.origin)
        if producer is not None and expected_authority is not None and (
            producer.authority != expected_authority
        ):
            errors.append(
                f"artifact {artifact.id!r} origin {artifact.origin!r} does not match "
                f"producer authority {producer.authority!r}"
            )
        if artifact.origin in {"asset", "external"} and producer is not None:
            errors.append(
                f"artifact {artifact.id!r} with {artifact.origin!r} origin must not have a producer"
            )
        if artifact.origin in {"participant", "trusted_evaluator"} and (
            artifact.availability == "generated" and producer is None
        ):
            errors.append(
                f"artifact {artifact.id!r} with {artifact.origin!r} origin requires a matching producer"
            )

    declared_outputs = set(workflow.outputs)
    for artifact_id in workflow.outputs:
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            errors.append(f"workflow references unknown declared output {artifact_id!r}")
        elif artifact.role != "output":
            errors.append(f"declared output {artifact_id!r} must have role 'output'")
        elif artifact_id not in producers:
            errors.append(f"declared output {artifact_id!r} has no producer")
    undeclared = sorted(
        artifact.id
        for artifact in workflow.artifacts
        if artifact.role == "output" and artifact.id not in declared_outputs
    )
    if undeclared:
        errors.append(f"output artifacts are not declared: {', '.join(undeclared)}")

    required_inputs = tuple(
        sorted(
            artifact.id
            for artifact in workflow.artifacts
            if artifact.role == "input"
        )
    )
    external = sorted(
        artifact.id
        for artifact in workflow.artifacts
        if artifact.availability == "external"
    )
    if external:
        message = f"workflow has external dependencies: {', '.join(external)}"
        (errors if require_self_contained else warnings).append(message)

    # Kahn's algorithm over producer-to-consumer operation dependencies.
    dependencies: dict[str, set[str]] = {operation_id: set() for operation_id in operations}
    followers: dict[str, set[str]] = {operation_id: set() for operation_id in operations}
    for operation in workflow.operations:
        for artifact_id in operation.inputs:
            producer = producers.get(artifact_id)
            if producer is not None and producer != operation.id:
                dependencies[operation.id].add(producer)
                followers[producer].add(operation.id)
    ready = sorted(operation_id for operation_id, deps in dependencies.items() if not deps)
    order: list[str] = []
    while ready:
        operation_id = ready.pop(0)
        order.append(operation_id)
        for follower in sorted(followers[operation_id]):
            dependencies[follower].discard(operation_id)
            if not dependencies[follower] and follower not in order and follower not in ready:
                ready.append(follower)
        ready.sort()
    if len(order) != len(operations):
        cyclic = sorted(set(operations) - set(order))
        errors.append(f"workflow contains an operation cycle: {', '.join(cyclic)}")

    # All participant work should contribute to a declared output or its
    # trusted evaluation.  Dead nodes remain warnings, because constructor
    # workflows can legitimately create hidden references.
    relevant_artifacts = set(workflow.outputs)
    relevant_operations: set[str] = set()
    queue = list(workflow.outputs)
    while queue:
        artifact_id = queue.pop()
        producer = producers.get(artifact_id)
        if producer is None or producer in relevant_operations:
            continue
        relevant_operations.add(producer)
        for dependency in operations[producer].inputs:
            if dependency not in relevant_artifacts:
                relevant_artifacts.add(dependency)
                queue.append(dependency)
    dead_participant = sorted(
        operation.id
        for operation in workflow.operations
        if operation.authority == "participant" and operation.id not in relevant_operations
        and operation.operation_type not in {"evaluate", "validate"}
    )
    if dead_participant:
        warnings.append(
            "participant operations do not contribute to declared outputs: "
            + ", ".join(dead_participant)
        )

    return WorkflowClosureReport(
        valid=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        topological_order=tuple(order),
        required_inputs=required_inputs,
    )


def require_closed_workflow(
    workflow: WorkflowIR | Mapping[str, Any],
    *,
    require_self_contained: bool = True,
) -> WorkflowIR:
    parsed = workflow if isinstance(workflow, WorkflowIR) else WorkflowIR.from_dict(workflow)
    report = validate_workflow_closure(parsed, require_self_contained=require_self_contained)
    if not report.valid:
        raise ValueError("workflow closure failed: " + "; ".join(report.errors))
    return parsed


def workflow_json_schema() -> dict[str, Any]:
    """Return the strict provider-facing schema for one declarative workflow."""

    identifier = {"type": "string", "pattern": _IDENTIFIER.pattern, "maxLength": 128}
    string_array = {
        "type": "array",
        "items": identifier,
        "uniqueItems": True,
        "maxItems": 512,
    }
    artifact = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "role",
            "availability",
            "media_type",
            "description",
            "origin",
            "evidence_ids",
        ],
        "properties": {
            "id": identifier,
            "role": {"enum": sorted(ARTIFACT_ROLES)},
            "availability": {"enum": sorted(ARTIFACT_AVAILABILITY)},
            "media_type": {"type": "string", "minLength": 1, "maxLength": 256},
            "description": {"type": "string", "minLength": 1, "maxLength": _MAX_DESCRIPTION_CHARS},
            "origin": {"enum": sorted(ARTIFACT_ORIGINS)},
            "evidence_ids": string_array,
            "asset_ref": {
                "type": "object",
                "additionalProperties": False,
                "required": ["asset_id", "relative_path"],
                "properties": {
                    "asset_id": identifier,
                    "relative_path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2_000,
                        "pattern": "^(?!/)(?!.*(?:^|/)\\.\\.(?:/|$))(?!.*\\\\)(?!.*:).+$",
                    },
                },
            },
            "capability_ref": identifier,
        },
        "allOf": [
            {
                "if": {"properties": {"origin": {"const": "asset"}}},
                "then": {"required": ["asset_ref"]},
                "else": {"not": {"required": ["asset_ref"]}},
            },
            {
                "if": {
                    "properties": {"origin": {"const": "trusted_generator"}}
                },
                "then": {"required": ["capability_ref"]},
                "else": {"not": {"required": ["capability_ref"]}},
            },
        ],
    }
    operation = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "operation_type",
            "authority",
            "description",
            "inputs",
            "outputs",
            "evidence_ids",
            "parameters",
        ],
        "properties": {
            "id": identifier,
            "operation_type": {"enum": sorted(OPERATION_TYPES)},
            "authority": {"enum": sorted(OPERATION_AUTHORITIES)},
            "description": {"type": "string", "minLength": 1, "maxLength": _MAX_DESCRIPTION_CHARS},
            "inputs": string_array,
            "outputs": {**string_array, "minItems": 1},
            "evidence_ids": string_array,
            "parameters": {"type": "object", "maxProperties": 128},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "id",
            "title",
            "artifacts",
            "operations",
            "outputs",
            "evidence_ids",
        ],
        "properties": {
            "schema_version": {"const": WORKFLOW_SCHEMA_VERSION},
            "id": identifier,
            "title": {"type": "string", "minLength": 1, "maxLength": 500},
            "artifacts": {"type": "array", "items": artifact, "minItems": 1, "maxItems": 1024},
            "operations": {"type": "array", "items": operation, "minItems": 1, "maxItems": 1024},
            "outputs": {**string_array, "minItems": 1},
            "evidence_ids": string_array,
        },
    }


__all__ = [
    "ARTIFACT_AVAILABILITY",
    "ARTIFACT_ORIGINS",
    "ARTIFACT_ROLES",
    "OPERATION_AUTHORITIES",
    "OPERATION_TYPES",
    "WORKFLOW_SCHEMA_VERSION",
    "ArtifactNode",
    "OperationNode",
    "WorkflowClosureReport",
    "WorkflowIR",
    "require_closed_workflow",
    "validate_workflow_closure",
    "workflow_json_schema",
]
