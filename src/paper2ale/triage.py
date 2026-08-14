"""Deterministic paper suitability triage and workflow candidate mining.

Public code and data are useful signals, not unconditional admission gates.  A
paper without either can still yield a task when an independent analytic or
synthetic oracle is possible.  Conversely, artifacts do not rescue a task
whose outputs cannot be verified.  Triage never installs code or promotes a
model-authored evaluator to trusted status.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .ids import stable_id
from .workflow import WorkflowIR, validate_workflow_closure


SUITABILITY_SCHEMA_VERSION = "paper2ale.suitability/v1"
DECISIONS = frozenset(
    {"eligible", "manual_review", "missing_artifacts", "no_viable_task", "rejected"}
)
LICENSE_STATUSES = frozenset({"known", "unknown", "restricted", "incompatible"})


def _nonempty(value: Any, name: str, maximum: int = 1_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds the {maximum}-character limit")
    return value


def _score(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0 <= numeric <= 1:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return numeric


def _unique_strings(values: Iterable[str], name: str) -> tuple[str, ...]:
    result = tuple(values)
    for item in result:
        _nonempty(item, name, maximum=2_000)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} contains duplicates")
    return result


def _strict_signals(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("suitability signals must be an object")
    try:
        encoded = json.dumps(
            dict(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("suitability signals must contain strict JSON values") from error
    if len(encoded.encode("utf-8")) > 64 * 1024:
        raise ValueError("suitability signals exceed the 65536-byte limit")
    decoded = json.loads(encoded)

    def freeze(item: Any) -> Any:
        if isinstance(item, dict):
            return MappingProxyType({key: freeze(child) for key, child in item.items()})
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    return freeze(decoded)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class PaperProfile:
    paper_id: str
    title: str
    readable: bool
    provenance_complete: bool
    license_status: str
    scientific_quality: float
    evidence_coverage: float
    independent_verification_possible: bool
    analytic_oracle_possible: bool = False
    synthetic_data_possible: bool = False
    public_code: bool = False
    public_data: bool = False
    code_license_known: bool = False
    data_license_known: bool = False
    workflow_reconstructable: bool = True
    contradictions_resolved: bool = True
    resources_bounded: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "paper_id", _nonempty(self.paper_id, "paper_id", 128))
        object.__setattr__(self, "title", _nonempty(self.title, "paper title", 1_000))
        if self.license_status not in LICENSE_STATUSES:
            raise ValueError(f"license_status must be one of {sorted(LICENSE_STATUSES)}")
        object.__setattr__(self, "scientific_quality", _score(self.scientific_quality, "scientific_quality"))
        object.__setattr__(self, "evidence_coverage", _score(self.evidence_coverage, "evidence_coverage"))
        boolean_fields = (
            "readable",
            "provenance_complete",
            "independent_verification_possible",
            "analytic_oracle_possible",
            "synthetic_data_possible",
            "public_code",
            "public_data",
            "code_license_known",
            "data_license_known",
            "workflow_reconstructable",
            "contradictions_resolved",
            "resources_bounded",
        )
        for name in boolean_fields:
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class TriagePolicy:
    minimum_scientific_quality: float = 0.55
    minimum_evidence_coverage: float = 0.60
    require_known_paper_license: bool = True
    require_independent_verification: bool = True
    require_bounded_resources: bool = True
    require_public_code_or_data: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "minimum_scientific_quality",
            _score(self.minimum_scientific_quality, "minimum_scientific_quality"),
        )
        object.__setattr__(
            self,
            "minimum_evidence_coverage",
            _score(self.minimum_evidence_coverage, "minimum_evidence_coverage"),
        )
        for name in (
            "require_known_paper_license",
            "require_independent_verification",
            "require_bounded_resources",
            "require_public_code_or_data",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class SuitabilityReport:
    subject_id: str
    subject_kind: str
    decision: str
    score: float
    hard_failures: tuple[str, ...]
    review_flags: tuple[str, ...]
    warnings: tuple[str, ...]
    signals: Mapping[str, Any]
    schema_version: str = SUITABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SUITABILITY_SCHEMA_VERSION:
            raise ValueError(
                f"suitability schema_version must be {SUITABILITY_SCHEMA_VERSION!r}"
            )
        object.__setattr__(self, "subject_id", _nonempty(self.subject_id, "subject_id", 256))
        if self.subject_kind not in {"paper", "task_candidate"}:
            raise ValueError("subject_kind must be 'paper' or 'task_candidate'")
        if self.decision not in DECISIONS:
            raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
        object.__setattr__(self, "score", _score(self.score, "suitability score"))
        object.__setattr__(self, "hard_failures", _unique_strings(self.hard_failures, "hard failure"))
        object.__setattr__(self, "review_flags", _unique_strings(self.review_flags, "review flag"))
        object.__setattr__(self, "warnings", _unique_strings(self.warnings, "warning"))
        object.__setattr__(self, "signals", _strict_signals(self.signals))

    @property
    def accepted(self) -> bool:
        return self.decision == "eligible"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
            "subject_kind": self.subject_kind,
            "decision": self.decision,
            "accepted": self.accepted,
            "score": self.score,
            "hard_failures": list(self.hard_failures),
            "review_flags": list(self.review_flags),
            "warnings": list(self.warnings),
            "signals": _thaw(self.signals),
        }


def triage_paper(
    profile: PaperProfile,
    *,
    policy: TriagePolicy | None = None,
) -> SuitabilityReport:
    """Classify one paper before costly task generation."""

    selected = policy or TriagePolicy()
    hard: list[str] = []
    review: list[str] = []
    warnings: list[str] = []
    missing_artifacts = False

    if not profile.readable:
        hard.append("paper_not_readable")
    if profile.license_status == "incompatible":
        hard.append("paper_license_incompatible")
    elif selected.require_known_paper_license and profile.license_status != "known":
        review.append("paper_license_requires_review")
    if profile.scientific_quality < selected.minimum_scientific_quality:
        hard.append("scientific_quality_below_threshold")
    if profile.evidence_coverage < selected.minimum_evidence_coverage:
        review.append("evidence_coverage_below_threshold")
    if not profile.provenance_complete:
        review.append("source_provenance_incomplete")
    if not profile.workflow_reconstructable:
        hard.append("workflow_not_reconstructable")
    if not profile.contradictions_resolved:
        review.append("source_contradictions_unresolved")
    if selected.require_bounded_resources and not profile.resources_bounded:
        hard.append("resource_requirements_unbounded")

    if selected.require_independent_verification and not profile.independent_verification_possible:
        hard.append("no_independent_verification")
    if not profile.public_code and not profile.public_data:
        if profile.analytic_oracle_possible or profile.synthetic_data_possible:
            warnings.append("no_public_artifacts_but_independent_construction_is_possible")
        else:
            missing_artifacts = True
            warnings.append("no_public_code_or_data")
    if selected.require_public_code_or_data and not (profile.public_code or profile.public_data):
        missing_artifacts = True
    if profile.public_code and not profile.code_license_known:
        review.append("code_license_unknown")
    if profile.public_data and not profile.data_license_known:
        review.append("data_license_unknown")

    score = (
        0.30 * profile.scientific_quality
        + 0.25 * profile.evidence_coverage
        + 0.25 * float(profile.independent_verification_possible)
        + 0.10 * float(profile.workflow_reconstructable)
        + 0.10 * float(profile.resources_bounded)
    )
    if "paper_not_readable" in hard or "paper_license_incompatible" in hard or "scientific_quality_below_threshold" in hard:
        decision = "rejected"
    elif hard:
        decision = "no_viable_task"
    elif missing_artifacts:
        decision = "missing_artifacts"
    elif review:
        decision = "manual_review"
    else:
        decision = "eligible"
    return SuitabilityReport(
        subject_id=profile.paper_id,
        subject_kind="paper",
        decision=decision,
        score=score,
        hard_failures=tuple(sorted(set(hard))),
        review_flags=tuple(sorted(set(review))),
        warnings=tuple(sorted(set(warnings))),
        signals={
            "public_code": profile.public_code,
            "public_data": profile.public_data,
            "analytic_oracle_possible": profile.analytic_oracle_possible,
            "synthetic_data_possible": profile.synthetic_data_possible,
            "independent_verification_possible": profile.independent_verification_possible,
            "scientific_quality": profile.scientific_quality,
            "evidence_coverage": profile.evidence_coverage,
        },
    )


@dataclass(frozen=True, slots=True)
class TaskCandidate:
    candidate_id: str
    workflow_id: str
    title: str
    target_artifact_id: str
    operation_ids: tuple[str, ...]
    input_artifact_ids: tuple[str, ...]
    output_artifact_ids: tuple[str, ...]
    verifier_operation_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    self_contained: bool
    verification_plan_present: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _nonempty(self.candidate_id, "candidate_id", 128))
        object.__setattr__(self, "workflow_id", _nonempty(self.workflow_id, "workflow_id", 128))
        object.__setattr__(self, "title", _nonempty(self.title, "candidate title", 1_000))
        object.__setattr__(self, "target_artifact_id", _nonempty(self.target_artifact_id, "target_artifact_id", 128))
        for name in (
            "operation_ids",
            "input_artifact_ids",
            "output_artifact_ids",
            "verifier_operation_ids",
            "evidence_ids",
        ):
            object.__setattr__(self, name, _unique_strings(getattr(self, name), name))
        if self.target_artifact_id not in self.output_artifact_ids:
            raise ValueError("target_artifact_id must be one of output_artifact_ids")
        if not isinstance(self.self_contained, bool) or not isinstance(
            self.verification_plan_present, bool
        ):
            raise TypeError("candidate readiness flags must be booleans")
        if self.verification_plan_present != bool(self.verifier_operation_ids):
            raise ValueError(
                "verification_plan_present must match verifier_operation_ids"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "workflow_id": self.workflow_id,
            "title": self.title,
            "target_artifact_id": self.target_artifact_id,
            "operation_ids": list(self.operation_ids),
            "input_artifact_ids": list(self.input_artifact_ids),
            "output_artifact_ids": list(self.output_artifact_ids),
            "verifier_operation_ids": list(self.verifier_operation_ids),
            "evidence_ids": list(self.evidence_ids),
            "self_contained": self.self_contained,
            "verification_plan_present": self.verification_plan_present,
        }


def _mine_one(workflow: WorkflowIR, target_id: str) -> TaskCandidate | None:
    artifacts = {artifact.id: artifact for artifact in workflow.artifacts}
    operations = {operation.id: operation for operation in workflow.operations}
    producer = {
        output: operation.id
        for operation in workflow.operations
        for output in operation.outputs
    }
    target_producer = producer.get(target_id)
    if target_producer is None or operations[target_producer].authority != "participant":
        return None

    selected_operations: set[str] = set()
    selected_artifacts: set[str] = {target_id}
    queue = [target_id]
    while queue:
        artifact_id = queue.pop()
        operation_id = producer.get(artifact_id)
        if operation_id is None or operation_id in selected_operations:
            continue
        operation = operations[operation_id]
        if operation.authority == "trusted_evaluator":
            continue
        selected_operations.add(operation_id)
        for dependency in operation.inputs:
            if dependency not in selected_artifacts:
                selected_artifacts.add(dependency)
                queue.append(dependency)

    produced_by_slice = {
        output
        for operation_id in selected_operations
        for output in operations[operation_id].outputs
    }
    inputs = tuple(
        sorted(
            {
                dependency
                for operation_id in selected_operations
                for dependency in operations[operation_id].inputs
                if dependency not in produced_by_slice
            }
        )
    )
    verifiers = tuple(
        sorted(
            operation.id
            for operation in workflow.operations
            if operation.authority == "trusted_evaluator"
            and operation.operation_type in {"evaluate", "validate"}
            and target_id in operation.inputs
        )
    )
    evidence = set(workflow.evidence_ids)
    evidence.update(artifacts[target_id].evidence_ids)
    for operation_id in selected_operations | set(verifiers):
        evidence.update(operations[operation_id].evidence_ids)
    self_contained = all(
        artifacts[artifact_id].role == "input"
        and artifacts[artifact_id].availability == "provided"
        for artifact_id in inputs
    )
    semantic = {
        "workflow_id": workflow.id,
        "target_artifact_id": target_id,
        "operation_ids": sorted(selected_operations),
        "input_artifact_ids": inputs,
        "verifier_operation_ids": verifiers,
    }
    return TaskCandidate(
        candidate_id=stable_id("candidate", semantic),
        workflow_id=workflow.id,
        title=f"{workflow.title}: produce {target_id}",
        target_artifact_id=target_id,
        operation_ids=tuple(sorted(selected_operations)),
        input_artifact_ids=inputs,
        output_artifact_ids=(target_id,),
        verifier_operation_ids=verifiers,
        evidence_ids=tuple(sorted(evidence)),
        self_contained=self_contained,
        verification_plan_present=bool(verifiers),
    )


def mine_task_candidates(
    workflows: Sequence[WorkflowIR],
    *,
    max_candidates: int = 1_024,
) -> tuple[TaskCandidate, ...]:
    """Mine one bounded participant task candidate per declared output."""

    if not isinstance(max_candidates, int) or isinstance(max_candidates, bool) or max_candidates < 1:
        raise ValueError("max_candidates must be a positive integer")
    candidates: list[TaskCandidate] = []
    for workflow in sorted(workflows, key=lambda item: item.id):
        report = validate_workflow_closure(workflow, require_self_contained=False)
        if not report.valid:
            continue
        for target_id in sorted(workflow.outputs):
            candidate = _mine_one(workflow, target_id)
            if candidate is not None:
                candidates.append(candidate)
                if len(candidates) > max_candidates:
                    raise ValueError(f"candidate mining exceeds the {max_candidates}-candidate limit")
    return tuple(candidates)


@dataclass(frozen=True, slots=True)
class TaskReadiness:
    candidate: TaskCandidate
    evaluator_implemented: bool
    trusted_family_available: bool
    output_machine_checkable: bool
    resources_bounded: bool
    evidence_coverage: float

    def __post_init__(self) -> None:
        for name in (
            "evaluator_implemented",
            "trusted_family_available",
            "output_machine_checkable",
            "resources_bounded",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")
        object.__setattr__(self, "evidence_coverage", _score(self.evidence_coverage, "task evidence_coverage"))


def triage_task(
    readiness: TaskReadiness,
    *,
    minimum_evidence_coverage: float = 0.70,
) -> SuitabilityReport:
    """Gate a mined proposal before it enters deterministic compilation."""

    minimum = _score(minimum_evidence_coverage, "minimum_evidence_coverage")
    candidate = readiness.candidate
    hard: list[str] = []
    review: list[str] = []
    if not candidate.self_contained:
        hard.append("task_has_external_inputs")
    if not candidate.verification_plan_present:
        hard.append("no_independent_verification_plan")
    if not readiness.output_machine_checkable:
        hard.append("output_not_machine_checkable")
    if not readiness.resources_bounded:
        hard.append("resource_requirements_unbounded")
    if readiness.evidence_coverage < minimum:
        review.append("task_evidence_coverage_below_threshold")
    if candidate.verification_plan_present and not readiness.evaluator_implemented:
        review.append("trusted_evaluator_not_implemented")
    if not readiness.trusted_family_available:
        review.append("trusted_task_family_not_available")

    score = (
        0.25 * float(candidate.self_contained)
        + 0.25 * float(candidate.verification_plan_present)
        + 0.20 * float(readiness.output_machine_checkable)
        + 0.15 * float(readiness.resources_bounded)
        + 0.15 * readiness.evidence_coverage
    )
    if hard:
        decision = "missing_artifacts" if hard == ["task_has_external_inputs"] else "no_viable_task"
    elif review:
        decision = "manual_review"
    else:
        decision = "eligible"
    return SuitabilityReport(
        subject_id=candidate.candidate_id,
        subject_kind="task_candidate",
        decision=decision,
        score=score,
        hard_failures=tuple(sorted(hard)),
        review_flags=tuple(sorted(review)),
        warnings=(),
        signals={
            "self_contained": candidate.self_contained,
            "verification_plan_present": candidate.verification_plan_present,
            "evaluator_implemented": readiness.evaluator_implemented,
            "trusted_family_available": readiness.trusted_family_available,
            "output_machine_checkable": readiness.output_machine_checkable,
            "resources_bounded": readiness.resources_bounded,
            "evidence_coverage": readiness.evidence_coverage,
        },
    )


__all__ = [
    "DECISIONS",
    "LICENSE_STATUSES",
    "SUITABILITY_SCHEMA_VERSION",
    "PaperProfile",
    "SuitabilityReport",
    "TaskCandidate",
    "TaskReadiness",
    "TriagePolicy",
    "mine_task_candidates",
    "triage_paper",
    "triage_task",
]
