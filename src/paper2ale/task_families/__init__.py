"""Trusted task-family registry.

Task families are executable compiler plugins: they own deterministic instance
generation and trusted evaluator construction.  Keeping registration here
lets the CLI/extraction layer discover capabilities without hard-coding them
in the compiler pipeline.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import inspect
import json
from pathlib import Path
import re
from types import CodeType, MappingProxyType
from typing import Any

from ..bindings import parse_workflow_binding
from ..packaging import BuildFile
from .generic import (
    GENERIC_CAPABILITIES,
    SUPPORTED_TEMPLATES as GENERIC_TEMPLATES,
    build_task_files as build_generic_task_files,
    protocol_json_schema as generic_protocol_json_schema,
    validate_protocol as validate_generic_protocol,
)
from .hnn import (
    SUPPORTED_TASKS as HNN_TASKS,
    build_task_files as build_hnn_task_files,
)
from .hnn_hard import (
    SUPPORTED_TASKS as HNN_HARD_TASKS,
    build_task_files as build_hnn_hard_task_files,
)


TaskBuilder = Callable[..., Sequence[BuildFile]]
ProtocolValidator = Callable[[Mapping[str, Any]], Mapping[str, Any]]
CandidateValidator = Callable[[Mapping[str, Any], Any, Any], None]
ProjectTaskValidator = Callable[[Mapping[str, Any], Mapping[str, Any]], None]
ProtocolSchemaFactory = Callable[[], Mapping[str, Any]]
_COMPILER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/v[1-9][0-9]*$")


def _stable_identity_value(value: Any) -> Any:
    """Encode callable state without paths, addresses, or hash-order drift."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return {"float_hex": value.hex()}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if value is Ellipsis:
        return {"ellipsis": True}
    if isinstance(value, CodeType):
        return {
            "argcount": value.co_argcount,
            "posonlyargcount": value.co_posonlyargcount,
            "kwonlyargcount": value.co_kwonlyargcount,
            "nlocals": value.co_nlocals,
            "stacksize": value.co_stacksize,
            "flags": value.co_flags,
            "code": value.co_code.hex(),
            "consts": [_stable_identity_value(item) for item in value.co_consts],
            "names": list(value.co_names),
            "varnames": list(value.co_varnames),
            "freevars": list(value.co_freevars),
            "cellvars": list(value.co_cellvars),
        }
    if isinstance(value, (tuple, list)):
        return [_stable_identity_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        encoded = [_stable_identity_value(item) for item in value]
        return {
            "set": sorted(
                encoded,
                key=lambda item: json.dumps(
                    item, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ),
            )
        }
    if isinstance(value, Mapping):
        encoded = [
            [_stable_identity_value(key), _stable_identity_value(item)]
            for key, item in value.items()
        ]
        return {
            "mapping": sorted(
                encoded,
                key=lambda item: json.dumps(
                    item[0],
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        }
    if isinstance(value, type):
        return {"type": f"{value.__module__}.{value.__qualname__}"}
    raise TypeError(
        "compiler callable contains unsupported non-portable state of type "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _callable_identity(value: Callable[..., Any] | None) -> dict[str, str] | None:
    if value is None:
        return None
    module = str(getattr(value, "__module__", type(value).__module__))
    qualname = str(getattr(value, "__qualname__", type(value).__qualname__))
    source_file = inspect.getsourcefile(value)
    module_sha256: str | None = None
    if source_file:
        try:
            module_bytes = Path(source_file).read_bytes()
            module_sha256 = hashlib.sha256(
                module_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            ).hexdigest()
        except OSError:
            module_sha256 = None
    try:
        callable_source = inspect.getsource(value)
    except (OSError, TypeError):
        callable_source = None
    target = value if hasattr(value, "__code__") else getattr(value, "__call__", None)
    code = getattr(target, "__code__", None)
    if callable_source is None and code is None:
        raise TypeError(
            f"callable {module}.{qualname} has no stable inspectable implementation"
        )
    payload = {
        "module_sha256": module_sha256,
        "callable_source": callable_source,
        "code": _stable_identity_value(code),
        "defaults": _stable_identity_value(getattr(target, "__defaults__", None)),
        "kwdefaults": _stable_identity_value(
            getattr(target, "__kwdefaults__", None)
        ),
        "closure": [
            _stable_identity_value(cell.cell_contents)
            for cell in (getattr(target, "__closure__", None) or ())
        ],
    }
    source_bytes = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return {
        "module": module,
        "qualname": qualname,
        "implementation_sha256": hashlib.sha256(source_bytes).hexdigest(),
    }


@dataclass(frozen=True, slots=True)
class TaskFamily:
    """One trusted, deterministic task-family compiler plugin."""

    name: str
    compiler_id: str
    builder: TaskBuilder
    supported_difficulty_levels: tuple[str, ...] = ()
    supported_task_ids: tuple[str, ...] = ()
    supported_templates: tuple[str, ...] = ()
    protocol_validator: ProtocolValidator | None = None
    protocol_schema_factory: ProtocolSchemaFactory | None = None
    candidate_validator: CandidateValidator | None = None
    project_task_validator: ProjectTaskValidator | None = None
    capabilities: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("task family name must be nonempty")
        if not isinstance(self.compiler_id, str) or _COMPILER_ID.fullmatch(
            self.compiler_id
        ) is None:
            raise ValueError(
                "task family compiler_id must be a stable name/version like family.name/v1"
            )
        if not callable(self.builder):
            raise TypeError("task family builder must be callable")
        if len(set(self.supported_difficulty_levels)) != len(
            self.supported_difficulty_levels
        ):
            raise ValueError("supported difficulty levels must be unique")
        if any(
            not isinstance(task_id, str) or not task_id.strip()
            for task_id in self.supported_task_ids
        ):
            raise ValueError("supported task IDs must be nonempty strings")
        if len(set(self.supported_task_ids)) != len(self.supported_task_ids):
            raise ValueError("supported task IDs must be unique")
        if any(
            not isinstance(template, str) or not template.strip()
            for template in self.supported_templates
        ):
            raise ValueError("supported templates must be nonempty strings")
        if len(set(self.supported_templates)) != len(self.supported_templates):
            raise ValueError("supported templates must be unique")
        if self.protocol_validator is not None and not callable(self.protocol_validator):
            raise TypeError("protocol validator must be callable")
        if self.supported_templates and self.protocol_validator is None:
            raise ValueError("families with declarative templates require a protocol validator")
        if self.protocol_validator is not None and self.protocol_schema_factory is None:
            raise ValueError(
                "families with declarative protocols require a provider-facing protocol schema"
            )
        if self.protocol_schema_factory is not None and not callable(
            self.protocol_schema_factory
        ):
            raise TypeError("protocol schema factory must be callable")
        if self.candidate_validator is not None and not callable(self.candidate_validator):
            raise TypeError("candidate validator must be callable")
        if self.project_task_validator is not None and not callable(
            self.project_task_validator
        ):
            raise TypeError("project task validator must be callable")

        normalized_capabilities: dict[str, tuple[str, ...]] = {}
        if not isinstance(self.capabilities, Mapping):
            raise TypeError("task family capabilities must be a mapping")
        for category, primitive_ids in self.capabilities.items():
            if not isinstance(category, str) or not category.strip():
                raise ValueError("capability categories must be nonempty strings")
            if isinstance(primitive_ids, (str, bytes)) or not isinstance(
                primitive_ids, Sequence
            ):
                raise TypeError("capability primitive IDs must be a sequence of strings")
            values = tuple(primitive_ids)
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError("capability primitive IDs must be nonempty strings")
            if len(set(values)) != len(values):
                raise ValueError("capability primitive IDs must be unique per category")
            normalized_capabilities[category] = values
        object.__setattr__(
            self,
            "capabilities",
            MappingProxyType(dict(sorted(normalized_capabilities.items()))),
        )

    def validate_protocol(self, protocol: Mapping[str, Any]) -> Mapping[str, Any]:
        """Validate and normalize a declarative protocol through trusted code."""

        if self.protocol_validator is None:
            raise ValueError(
                f"task family {self.name!r} does not accept declarative protocols"
            )
        normalized = self.protocol_validator(protocol)
        if not isinstance(normalized, Mapping):
            raise TypeError("protocol validator must return a mapping")
        template_id = normalized.get("template_id")
        if template_id not in self.supported_templates:
            supported = ", ".join(self.supported_templates) or "none"
            raise ValueError(
                f"family {self.name!r} does not support template {template_id!r}; "
                f"supported templates: {supported}"
            )
        return normalized

    def protocol_schema(self) -> dict[str, Any] | None:
        """Return a strict defensive provider schema for this family."""

        if self.protocol_schema_factory is None:
            return None
        value = self.protocol_schema_factory()
        if not isinstance(value, Mapping):
            raise TypeError("protocol schema factory must return a mapping")
        copied = json.loads(
            json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
        )
        if not isinstance(copied, dict):
            raise TypeError("protocol schema factory must return an object")
        copied.pop("$schema", None)
        copied.pop("$id", None)
        return copied

    def identity(self) -> dict[str, Any]:
        """Return content identity for build/resume invalidation."""

        return {
            "family": self.name,
            "compiler_id": self.compiler_id,
            "supported_difficulty_levels": list(self.supported_difficulty_levels),
            "supported_task_ids": list(self.supported_task_ids),
            "supported_templates": list(self.supported_templates),
            "capabilities": {
                key: list(values) for key, values in sorted(self.capabilities.items())
            },
            "builder": _callable_identity(self.builder),
            "protocol_validator": _callable_identity(self.protocol_validator),
            "protocol_schema_factory": _callable_identity(
                self.protocol_schema_factory
            ),
            "candidate_validator": _callable_identity(self.candidate_validator),
            "project_task_validator": _callable_identity(
                self.project_task_validator
            ),
        }

    def validate_task(
        self,
        task: Mapping[str, Any],
        *,
        require_binding: bool = False,
    ) -> Mapping[str, Any] | None:
        """Reject task IDs and declarative protocols outside trusted capabilities."""

        if not isinstance(task, Mapping):
            raise TypeError("task must be an object")
        family = task.get("family")
        if family != self.name:
            raise ValueError(
                f"task family {family!r} does not match registry family {self.name!r}"
            )
        task_id = task.get("id")
        if self.supported_task_ids and task_id not in self.supported_task_ids:
            supported = ", ".join(self.supported_task_ids)
            raise ValueError(
                f"family {self.name!r} does not support task ID {task_id!r}; "
                f"supported task IDs: {supported}"
            )
        protocol = task.get("protocol")
        if self.protocol_validator is None:
            if protocol is not None:
                raise ValueError(
                    f"task family {self.name!r} does not accept a declarative protocol"
                )
            return None
        if not isinstance(protocol, Mapping):
            raise ValueError(
                f"task family {self.name!r} requires a declarative protocol object"
            )
        normalized = self.validate_protocol(protocol)
        self._validate_outer_contract(task, normalized)
        if require_binding or task.get("workflow_binding") is not None:
            self._validate_persisted_binding(task)
        return normalized

    def _validate_persisted_binding(self, task: Mapping[str, Any]) -> None:
        if self.candidate_validator is None:
            if task.get("workflow_binding") is not None:
                raise ValueError(
                    f"task family {self.name!r} does not accept workflow_binding"
                )
            return
        binding = task.get("workflow_binding")
        if not isinstance(binding, Mapping):
            raise ValueError(
                f"task family {self.name!r} requires a persisted workflow_binding"
            )
        workflow, candidate = parse_workflow_binding(
            binding, expected_family=self.name
        )
        if set(task.get("evidence_ids", ())) != set(candidate.evidence_ids):
            raise ValueError(
                "task evidence_ids do not match the persisted workflow candidate"
            )
        if set(task.get("workflow_nodes", ())) != set(candidate.operation_ids):
            raise ValueError(
                "task workflow_nodes do not match the persisted workflow candidate"
            )
        self.validate_candidate(task, candidate, workflow)

    def _validate_outer_contract(
        self,
        task: Mapping[str, Any],
        protocol: Mapping[str, Any],
    ) -> None:
        """Bind generic blueprint claims to the executable trusted protocol."""

        outer_output = task.get("output_contract")
        expected_output = protocol.get("output")
        if not isinstance(outer_output, Mapping) or not isinstance(
            expected_output, Mapping
        ):
            raise ValueError(
                "declarative tasks require matching outer and protocol output contracts"
            )
        for key, protocol_key in (("format", "primitive"), ("filename", "filename")):
            if outer_output.get(key) != expected_output.get(protocol_key):
                raise ValueError(
                    f"outer output_contract.{key} must equal protocol.output.{protocol_key}"
                )

        outer_evaluation = task.get("evaluation")
        protocol_evaluation = protocol.get("evaluation")
        if not isinstance(outer_evaluation, Mapping) or not isinstance(
            protocol_evaluation, Mapping
        ):
            raise ValueError(
                "declarative tasks require matching outer and protocol evaluation contracts"
            )
        outer_metrics = outer_evaluation.get("metrics")
        protocol_metrics = protocol_evaluation.get("metrics")
        if not isinstance(outer_metrics, Sequence) or isinstance(
            outer_metrics, (str, bytes)
        ):
            raise ValueError(
                "generic task evaluation must declare weighted metrics, not only a weights map"
            )
        expected_metrics = {
            str(metric["id"]): (
                float(metric["weight"]),
                float(metric["threshold"]),
            )
            for metric in protocol_metrics
            if isinstance(metric, Mapping)
        }
        actual_metrics: dict[str, tuple[float, float]] = {}
        for metric in outer_metrics:
            if not isinstance(metric, Mapping) or "threshold" not in metric:
                raise ValueError(
                    "generic outer metrics require id, weight, and threshold"
                )
            try:
                actual_metrics[str(metric["id"])] = (
                    float(metric["weight"]),
                    float(metric["threshold"]),
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("generic outer metric is malformed") from error
        if actual_metrics != expected_metrics:
            raise ValueError(
                "outer evaluation metrics must exactly match protocol metric IDs, weights, and thresholds"
            )

        def gate_id(value: Any) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, Mapping) and isinstance(value.get("id"), str):
                return str(value["id"])
            raise ValueError("generic outer evaluation gates must have string IDs")

        outer_gates = outer_evaluation.get("gates")
        if not isinstance(outer_gates, Sequence) or isinstance(
            outer_gates, (str, bytes)
        ):
            raise ValueError("generic outer evaluation gates must be an array")
        if tuple(gate_id(gate) for gate in outer_gates) != tuple(
            protocol_evaluation["gates"]
        ):
            raise ValueError(
                "outer evaluation gates must exactly match protocol evaluation gates"
            )

    def validate_candidate(
        self,
        task: Mapping[str, Any],
        candidate: Any,
        workflow: Any,
    ) -> None:
        """Bind a compiled task to one mined workflow through trusted code."""

        if self.candidate_validator is None:
            raise ValueError(
                f"task family {self.name!r} has no reviewed candidate compiler; "
                "it may be built from authored projects but not selected by orchestration"
            )
        self.candidate_validator(task, candidate, workflow)

    def validate_project_task(
        self,
        project: Mapping[str, Any],
        task: Mapping[str, Any],
        *,
        require_binding: bool = False,
    ) -> None:
        """Apply task-local and project/provenance compiler preconditions."""

        self.validate_task(task, require_binding=require_binding)
        if self.project_task_validator is not None:
            self.project_task_validator(project, task)

    def capability_catalog(self) -> dict[str, Any]:
        """Return a JSON-serializable defensive capability description."""

        return {
            "family": self.name,
            "compiler_id": self.compiler_id,
            "difficulty_levels": list(self.supported_difficulty_levels),
            "task_ids": list(self.supported_task_ids),
            "templates": list(self.supported_templates),
            "trusted_primitives": {
                category: list(values)
                for category, values in sorted(self.capabilities.items())
            },
            "accepts_declarative_protocols": self.protocol_validator is not None,
            "supports_candidate_compilation": self.candidate_validator is not None,
            "requires_project_validation": self.project_task_validator is not None,
        }


_FAMILY_SPECS: dict[str, TaskFamily] = {}
# Backwards-compatible public builder map.  Register through
# ``register_task_family`` so specs and builders cannot drift.
TASK_FAMILIES: dict[str, TaskBuilder] = {}


def register_task_family(
    name: str,
    builder: TaskBuilder,
    *,
    compiler_id: str,
    supported_difficulty_levels: Sequence[str] = (),
    supported_task_ids: Sequence[str] = (),
    supported_templates: Sequence[str] = (),
    protocol_validator: ProtocolValidator | None = None,
    protocol_schema_factory: ProtocolSchemaFactory | None = None,
    candidate_validator: CandidateValidator | None = None,
    project_task_validator: ProjectTaskValidator | None = None,
    capabilities: Mapping[str, Sequence[str]] | None = None,
    replace: bool = False,
) -> TaskFamily:
    """Register trusted family code explicitly.

    Registration is intentionally process-local.  Importing a paper or model
    response never loads executable plugins; an operator must install/import
    trusted family code first.
    """

    normalized = name.strip() if isinstance(name, str) else ""
    if not normalized:
        raise ValueError("task family name must be a nonempty string")
    if normalized in _FAMILY_SPECS and not replace:
        raise ValueError(f"task family {normalized!r} is already registered")
    levels = tuple(str(level).strip() for level in supported_difficulty_levels)
    if any(not level for level in levels):
        raise ValueError("supported difficulty levels must be nonempty strings")
    task_ids = tuple(str(task_id).strip() for task_id in supported_task_ids)
    if any(not task_id for task_id in task_ids):
        raise ValueError("supported task IDs must be nonempty strings")
    templates = tuple(str(template).strip() for template in supported_templates)
    if any(not template for template in templates):
        raise ValueError("supported templates must be nonempty strings")
    capability_values = {} if capabilities is None else capabilities
    spec = TaskFamily(
        name=normalized,
        compiler_id=compiler_id,
        builder=builder,
        supported_difficulty_levels=levels,
        supported_task_ids=task_ids,
        supported_templates=templates,
        protocol_validator=protocol_validator,
        protocol_schema_factory=protocol_schema_factory,
        candidate_validator=candidate_validator,
        project_task_validator=project_task_validator,
        capabilities=capability_values,
    )
    _FAMILY_SPECS[normalized] = spec
    TASK_FAMILIES[normalized] = builder
    return spec


def task_family(name: str) -> TaskFamily:
    """Return a registered family or fail with an actionable error."""

    try:
        return _FAMILY_SPECS[name]
    except KeyError as error:
        available = ", ".join(sorted(_FAMILY_SPECS)) or "none"
        raise ValueError(
            f"unsupported task family {name!r}; registered families: {available}. "
            "Install or register a trusted deterministic family before compiling."
        ) from error


def registered_task_families() -> Mapping[str, TaskFamily]:
    """Return a defensive snapshot of available trusted family plugins."""

    return dict(sorted(_FAMILY_SPECS.items()))


def registered_capability_catalog() -> Mapping[str, dict[str, Any]]:
    """Return the stable capabilities generation front ends may target."""

    return {
        name: spec.capability_catalog()
        for name, spec in sorted(_FAMILY_SPECS.items())
    }


def registered_compiler_identity() -> dict[str, Any]:
    """Return the complete immutable compiler registry identity."""

    return {
        "schema_version": "paper2ale.compiler-registry/v1",
        "families": [
            spec.identity() for _name, spec in sorted(_FAMILY_SPECS.items())
        ],
    }


def validate_task_protocol(
    family: str, protocol: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Validate one model-authored protocol without loading executable code."""

    return task_family(family).validate_protocol(protocol)


_GENERIC_TEMPLATE_OPERATION = {
    "numeric-affine-v1": "infer",
    "table-filter-sort-v1": "transform",
    "json-group-aggregate-v1": "aggregate",
}
_GENERIC_INPUT_CAPABILITY = {
    template_id: f"generic.{template_id}.input"
    for template_id in _GENERIC_TEMPLATE_OPERATION
}


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    return value


def _validate_generic_candidate(
    task: Mapping[str, Any], candidate: Any, workflow: Any
) -> None:
    """Exact, reviewed compiler binding for the three generic v1 templates."""

    normalized = validate_generic_protocol(task.get("protocol"))
    template_id = str(normalized["template_id"])
    expected_operation = _GENERIC_TEMPLATE_OPERATION[template_id]
    selected_ids = set(candidate.operation_ids)
    selected = [item for item in workflow.operations if item.id in selected_ids]
    if len(selected) != 1 or {item.id for item in selected} != selected_ids:
        raise ValueError("generic templates require exactly one bound participant operation")
    operation = selected[0]
    if operation.authority != "participant" or operation.operation_type != expected_operation:
        raise ValueError(
            f"generic template {template_id!r} does not match the participant operation"
        )
    expected_parameters = {"protocol": _plain_json(normalized)}
    if _plain_json(operation.parameters) != expected_parameters:
        raise ValueError(
            "participant operation parameters must contain exactly the compiled protocol"
        )
    if tuple(sorted(operation.inputs)) != tuple(sorted(candidate.input_artifact_ids)):
        raise ValueError("generic candidate inputs do not match its participant operation")
    if candidate.target_artifact_id not in operation.outputs:
        raise ValueError("generic candidate target is not produced by its participant operation")

    artifacts = {item.id: item for item in workflow.artifacts}
    expected_capability = _GENERIC_INPUT_CAPABILITY[template_id]
    for identifier in candidate.input_artifact_ids:
        artifact = artifacts[identifier]
        if (
            artifact.origin != "trusted_generator"
            or artifact.capability_ref != expected_capability
            or artifact.availability != "provided"
        ):
            raise ValueError(
                f"generic {template_id!r} inputs require capability {expected_capability!r}"
            )
    target = artifacts[candidate.target_artifact_id]
    if target.origin != "participant" or not target.media_type.startswith(
        "application/json"
    ):
        raise ValueError("generic templates require a participant-authored JSON target")

    verifier_ids = set(candidate.verifier_operation_ids)
    verifiers = [item for item in workflow.operations if item.id in verifier_ids]
    if {item.id for item in verifiers} != verifier_ids or not verifiers:
        raise ValueError("generic candidate lacks its trusted verifier operation")
    expected_verifier = {
        "output": _plain_json(normalized["output"]),
        "evaluation": _plain_json(normalized["evaluation"]),
    }
    for verifier in verifiers:
        if (
            verifier.authority != "trusted_evaluator"
            or verifier.operation_type not in {"evaluate", "validate"}
            or _plain_json(verifier.parameters) != expected_verifier
        ):
            raise ValueError(
                "trusted verifier parameters must exactly match protocol output and evaluation"
            )


_FIXED_HNN_PROJECT_BINDINGS = {
    "hnn": {
        "source_bundle_sha256": "7c2573020c355c44ef92a3be6ca925eeed846717b4605af9d36e11b500dadd74",
        "evidence_graph_sha256": "6c8e38990d5b834569730c1b056b0fac3889ce14971213bcd8f0f99203d15fac",
        "task_contracts": {
            "hnn-symplectic-gradient": "39761ee9560495b2f80e9cb7bcbc19e0d87cf58e69e60233b146b91b331d07ca",
            "hnn-mass-spring": "bd555b312d919f4cc7844daa6c8cd26d8d8ef10ee126c3383bd8cd8d52335867",
            "hnn-two-body-audit": "a42b36ccabea56a03a5a080740559b5726a5c8c813944c8e04db6f63c333ff9e",
        },
    },
    "hnn_hard": {
        "source_bundle_sha256": "7c2573020c355c44ef92a3be6ca925eeed846717b4605af9d36e11b500dadd74",
        "evidence_graph_sha256": "3af478cf629a395f5ba76278dd31bbcb670b0b5dce2dac0a57d89f2b3f2b1124",
        "task_contracts": {
            "hnn-hard-coupled-identification": "fe0c6e6aaa651467364635976ba542f93b50a1bf57eada18c7129ec8fcb4f8a7",
            "hnn-hard-variable-nbody": "5a8a0c06152920fa53af74345f2580466f873d9d1aca52dc9f50af2f489e5190",
            "hnn-hard-canonical-recovery": "a5aab618f51e5d469bf3acb94aedf46f5c7facbc55ed29747d322a58a581dda5",
        },
    },
}
_FIXED_TASK_CONTRACT_FIELDS = (
    "mode",
    "evidence_ids",
    "workflow_nodes",
    "output_contract",
    "evaluation",
)


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _validate_fixed_hnn_project_task(
    project: Mapping[str, Any], task: Mapping[str, Any]
) -> None:
    """Bind authored HNN fixtures to their reviewed sources and contracts."""

    family = str(task.get("family", ""))
    binding = _FIXED_HNN_PROJECT_BINDINGS.get(family)
    if binding is None:
        raise ValueError("fixed HNN project validator received the wrong family")
    if _canonical_digest(project.get("source_bundle")) != binding[
        "source_bundle_sha256"
    ]:
        raise ValueError(
            f"family {family!r} requires its exact reviewed paper/code source lock"
        )
    if _canonical_digest(project.get("evidence_graph")) != binding[
        "evidence_graph_sha256"
    ]:
        raise ValueError(
            f"family {family!r} requires its exact reviewed evidence graph"
        )
    task_id = str(task.get("id", ""))
    expected = binding["task_contracts"].get(task_id)
    actual = _canonical_digest(
        {key: task.get(key) for key in _FIXED_TASK_CONTRACT_FIELDS}
    )
    if expected is None or actual != expected:
        raise ValueError(
            f"fixed family task {task_id!r} does not match its reviewed semantic contract"
        )


register_task_family(
    "hnn",
    build_hnn_task_files,
    compiler_id="paper2ale.hnn/v1",
    supported_task_ids=HNN_TASKS,
    project_task_validator=_validate_fixed_hnn_project_task,
)
register_task_family(
    "hnn_hard",
    build_hnn_hard_task_files,
    compiler_id="paper2ale.hnn-hard/v1",
    supported_difficulty_levels=("medium", "hard", "frontier"),
    supported_task_ids=HNN_HARD_TASKS,
    project_task_validator=_validate_fixed_hnn_project_task,
)
register_task_family(
    "generic",
    build_generic_task_files,
    compiler_id="paper2ale.generic/v1",
    supported_difficulty_levels=("easy", "medium", "hard", "frontier"),
    supported_templates=GENERIC_TEMPLATES,
    protocol_validator=validate_generic_protocol,
    protocol_schema_factory=generic_protocol_json_schema,
    candidate_validator=_validate_generic_candidate,
    capabilities=GENERIC_CAPABILITIES,
)


__all__ = [
    "TASK_FAMILIES",
    "TaskBuilder",
    "CandidateValidator",
    "ProtocolSchemaFactory",
    "TaskFamily",
    "ProtocolValidator",
    "build_generic_task_files",
    "generic_protocol_json_schema",
    "build_hnn_task_files",
    "build_hnn_hard_task_files",
    "register_task_family",
    "registered_capability_catalog",
    "registered_compiler_identity",
    "registered_task_families",
    "task_family",
    "validate_task_protocol",
]
