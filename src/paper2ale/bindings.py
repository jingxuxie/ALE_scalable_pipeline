"""Persisted, content-derived workflow-to-task compiler bindings."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .triage import TaskCandidate, mine_task_candidates
from .workflow import WorkflowIR, require_closed_workflow, workflow_json_schema


BINDING_SCHEMA_VERSION = "paper2ale.workflow-binding/v1"
_BINDING_ID = re.compile(r"^binding_[0-9a-f]{64}$")
_CANDIDATE_FIELDS = {
    "candidate_id",
    "workflow_id",
    "title",
    "target_artifact_id",
    "operation_ids",
    "input_artifact_ids",
    "output_artifact_ids",
    "verifier_operation_ids",
    "evidence_ids",
    "self_contained",
    "verification_plan_present",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _binding_id(family: str, workflow: Mapping[str, Any], candidate: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        _canonical({"family": family, "workflow": workflow, "candidate": candidate})
    ).hexdigest()
    return f"binding_{digest}"


def _require_mined_candidate(
    workflow: WorkflowIR, candidate: TaskCandidate
) -> TaskCandidate:
    matches = [
        item
        for item in mine_task_candidates((workflow,))
        if item.target_artifact_id == candidate.target_artifact_id
    ]
    if len(matches) != 1 or matches[0].to_dict() != candidate.to_dict():
        raise ValueError(
            "workflow_binding candidate is not the canonical candidate mined from its workflow"
        )
    return matches[0]


def make_workflow_binding(
    family: str,
    workflow: WorkflowIR,
    candidate: TaskCandidate,
) -> dict[str, Any]:
    if not isinstance(family, str) or not family.strip():
        raise ValueError("binding family must be nonempty")
    closed = require_closed_workflow(workflow)
    if candidate.workflow_id != closed.id:
        raise ValueError("candidate workflow_id does not match workflow")
    candidate = _require_mined_candidate(closed, candidate)
    workflow_value = closed.to_dict()
    candidate_value = candidate.to_dict()
    return {
        "schema_version": BINDING_SCHEMA_VERSION,
        "binding_id": _binding_id(family, workflow_value, candidate_value),
        "family": family,
        "workflow": workflow_value,
        "candidate": candidate_value,
    }


def parse_workflow_binding(
    value: Mapping[str, Any],
    *,
    expected_family: str | None = None,
) -> tuple[WorkflowIR, TaskCandidate]:
    if not isinstance(value, Mapping):
        raise TypeError("workflow_binding must be an object")
    required = {"schema_version", "binding_id", "family", "workflow", "candidate"}
    if set(value) != required:
        raise ValueError(
            "workflow_binding fields mismatch; "
            f"missing={sorted(required - set(value))}, unknown={sorted(set(value) - required)}"
        )
    if value["schema_version"] != BINDING_SCHEMA_VERSION:
        raise ValueError("workflow_binding has an unsupported schema version")
    family = value["family"]
    if not isinstance(family, str) or not family.strip():
        raise ValueError("workflow_binding family must be nonempty")
    if expected_family is not None and family != expected_family:
        raise ValueError("workflow_binding family does not match the task family")
    workflow_raw = value["workflow"]
    candidate_raw = value["candidate"]
    if not isinstance(workflow_raw, Mapping) or not isinstance(candidate_raw, Mapping):
        raise TypeError("workflow_binding workflow and candidate must be objects")
    if set(candidate_raw) != _CANDIDATE_FIELDS:
        raise ValueError("workflow_binding candidate fields mismatch")
    workflow = require_closed_workflow(workflow_raw)
    candidate = TaskCandidate(**dict(candidate_raw))
    if candidate.workflow_id != workflow.id:
        raise ValueError("workflow_binding candidate points to a different workflow")
    candidate = _require_mined_candidate(workflow, candidate)
    binding_id = value["binding_id"]
    if not isinstance(binding_id, str) or _BINDING_ID.fullmatch(binding_id) is None:
        raise ValueError("workflow_binding binding_id is malformed")
    expected_id = _binding_id(family, workflow.to_dict(), candidate.to_dict())
    if binding_id != expected_id:
        raise ValueError("workflow_binding binding_id does not match its content")
    return workflow, candidate


def workflow_binding_json_schema() -> dict[str, Any]:
    workflow_schema = workflow_json_schema()
    workflow_schema.pop("$schema", None)
    candidate_array = {
        "type": "array",
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
        },
        "uniqueItems": True,
        "maxItems": 512,
    }
    candidate = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_CANDIDATE_FIELDS),
        "properties": {
            "candidate_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "workflow_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "title": {"type": "string", "minLength": 1, "maxLength": 1000},
            "target_artifact_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "operation_ids": candidate_array,
            "input_artifact_ids": candidate_array,
            "output_artifact_ids": candidate_array,
            "verifier_operation_ids": candidate_array,
            "evidence_ids": candidate_array,
            "self_contained": {"type": "boolean"},
            "verification_plan_present": {"type": "boolean"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "binding_id", "family", "workflow", "candidate"],
        "properties": {
            "schema_version": {"const": BINDING_SCHEMA_VERSION},
            "binding_id": {"type": "string", "pattern": _BINDING_ID.pattern},
            "family": {"type": "string", "minLength": 1},
            "workflow": workflow_schema,
            "candidate": candidate,
        },
    }


__all__ = [
    "BINDING_SCHEMA_VERSION",
    "make_workflow_binding",
    "parse_workflow_binding",
    "workflow_binding_json_schema",
]
