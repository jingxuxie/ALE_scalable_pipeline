"""Project loading and validation for the paper2ale project format.

The validator intentionally uses only the Python standard library.  The JSON
Schema files in ``schemas/`` describe the interchange format; this module adds
the cross-reference and policy checks that JSON Schema cannot express neatly.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from .difficulty import (
    builtin_profiles,
    validate_difficulty_selection,
    validate_profile_definition,
)


PROJECT_SCHEMA_VERSION = "paper2ale.project/v1"
TASK_MODES = frozenset(
    {
        "specification_preserving",
        "masked_workflow_completion",
        "method_masked_rediscovery",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9_-])?$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


@dataclass(frozen=True)
class Issue:
    """One actionable project-validation finding."""

    code: str
    message: str
    path: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
        }


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON-compatible value deterministically as UTF-8 bytes."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def load_project(path: str | Path) -> dict[str, Any]:
    """Load a project JSON file and require an object at its root."""

    project_path = Path(path)
    try:
        value = json.loads(project_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{project_path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(f"{project_path}: project root must be a JSON object")
    return value


def _pointer(parent: str, token: str | int) -> str:
    encoded = str(token).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{encoded}" if parent else f"/{encoded}"


def _display_path(path: str) -> str:
    return path or "/"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class _Validator:
    def __init__(self) -> None:
        self.issues: list[Issue] = []
        self._ids: dict[str, str] = {}
        self.source_ids: set[str] = set()
        self.evidence_ids: set[str] = set()
        self.node_ids: set[str] = set()
        self.claim_ids: set[str] = set()
        self.claim_evidence: dict[str, set[str]] = {}
        self.node_evidence: dict[str, set[str]] = {}
        self.high_impact_unresolved: set[str] = set()
        builtins = builtin_profiles()
        self.difficulty_profiles: dict[tuple[str, int], Mapping[str, Any]] = {
            (profile["id"], profile["version"]): profile for profile in builtins
        }

    def add(self, code: str, message: str, path: str, severity: str = "error") -> None:
        self.issues.append(Issue(code, message, _display_path(path), severity))

    def expect_mapping(self, value: Any, path: str) -> Mapping[str, Any] | None:
        if not isinstance(value, Mapping):
            self.add("type", f"expected object, got {type(value).__name__}", path)
            return None
        return value

    def expect_list(self, value: Any, path: str) -> list[Any] | None:
        if not isinstance(value, list):
            self.add("type", f"expected array, got {type(value).__name__}", path)
            return None
        return value

    def require_keys(
        self, value: Mapping[str, Any], required: set[str], path: str
    ) -> None:
        for key in sorted(required - set(value)):
            self.add("required", f"missing required property {key!r}", _pointer(path, key))

    def reject_unknown_keys(
        self, value: Mapping[str, Any], allowed: set[str], path: str
    ) -> None:
        for key in sorted(set(value) - allowed, key=str):
            self.add(
                "additional_property",
                f"unexpected property {key!r}",
                _pointer(path, key),
            )

    def nonempty_string(self, value: Any, path: str) -> str | None:
        if not isinstance(value, str):
            self.add("type", f"expected string, got {type(value).__name__}", path)
            return None
        if not value.strip():
            self.add("invalid_value", "string must not be empty", path)
            return None
        return value

    def register_id(self, value: Any, path: str, category: str) -> str | None:
        identifier = self.nonempty_string(value, path)
        if identifier is None:
            return None
        previous = self._ids.get(identifier)
        if previous is not None:
            self.add(
                "duplicate_id",
                f"{category} id {identifier!r} duplicates id at {previous}",
                path,
            )
            return identifier
        self._ids[identifier] = _display_path(path)
        return identifier

    def safe_path_id(self, value: Any, path: str, category: str) -> str | None:
        identifier = self.register_id(value, path, category)
        if identifier is None:
            return None
        reserved_stem = identifier.split(".", 1)[0].upper()
        if (
            len(identifier) > 128
            or _SAFE_COMPONENT_RE.fullmatch(identifier) is None
            or reserved_stem in _WINDOWS_RESERVED_NAMES
        ):
            self.add(
                "unsafe_id",
                f"{category} id must be one portable filesystem path component",
                path,
            )
        return identifier

    def string_ids(self, value: Any, path: str, *, nonempty: bool = False) -> list[str]:
        items = self.expect_list(value, path)
        if items is None:
            return []
        if nonempty and not items:
            self.add("invalid_value", "array must contain at least one item", path)
        result: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(items):
            item_path = _pointer(path, index)
            item_id = self.nonempty_string(item, item_path)
            if item_id is None:
                continue
            if item_id in seen:
                self.add("duplicate_reference", f"duplicate reference {item_id!r}", item_path)
            else:
                seen.add(item_id)
                result.append(item_id)
        return result

    def validate(self, data: Any) -> list[Issue]:
        root = self.expect_mapping(data, "")
        if root is None:
            return self.issues

        required = {
            "schema_version",
            "project_id",
            "source_bundle",
            "evidence_graph",
            "tasks",
        }
        self.require_keys(root, required, "")
        self.reject_unknown_keys(root, required | {"defaults", "difficulty_profiles"}, "")

        if "schema_version" in root:
            version = root["schema_version"]
            if version != PROJECT_SCHEMA_VERSION:
                self.add(
                    "schema_version",
                    f"expected {PROJECT_SCHEMA_VERSION!r}",
                    "/schema_version",
                )
        if "project_id" in root:
            self.safe_path_id(root["project_id"], "/project_id", "project")
        if "defaults" in root:
            self.expect_mapping(root["defaults"], "/defaults")
        if "difficulty_profiles" in root:
            self.validate_difficulty_profiles(root["difficulty_profiles"], "/difficulty_profiles")

        if "source_bundle" in root:
            self.validate_sources(root["source_bundle"], "/source_bundle")
        if "evidence_graph" in root:
            self.validate_evidence_graph(root["evidence_graph"], "/evidence_graph")
        if "tasks" in root:
            self.validate_tasks(root["tasks"], "/tasks")

        return self.issues

    def validate_difficulty_profiles(self, value: Any, path: str) -> None:
        profiles = self.expect_list(value, path)
        if profiles is None:
            return
        seen: set[tuple[str, int]] = set(self.difficulty_profiles)
        for index, item in enumerate(profiles):
            item_path = _pointer(path, index)
            profile = self.expect_mapping(item, item_path)
            if profile is None:
                continue
            problems = validate_profile_definition(profile)
            for problem in problems:
                self.add(
                    f"difficulty_{problem.code}",
                    problem.message,
                    item_path + problem.path,
                )
            profile_id = profile.get("id")
            version = profile.get("version")
            if (
                isinstance(profile_id, str)
                and isinstance(version, int)
                and not isinstance(version, bool)
            ):
                key = (profile_id, version)
                if key in seen:
                    self.add(
                        "duplicate_difficulty_profile",
                        f"difficulty profile {profile_id!r} version {version} is duplicate or reserved",
                        _pointer(item_path, "id"),
                    )
                else:
                    seen.add(key)
                    if not problems:
                        self.difficulty_profiles[key] = profile

    def validate_sources(self, value: Any, path: str) -> None:
        sources = self.expect_list(value, path)
        if sources is None:
            return
        if not sources:
            self.add("invalid_value", "source_bundle must contain at least one source", path)
        required = {"id", "kind", "uri", "version", "license", "visibility"}
        allowed = required | {"sha256", "citation", "retrieved_at"}
        for index, item in enumerate(sources):
            item_path = _pointer(path, index)
            source = self.expect_mapping(item, item_path)
            if source is None:
                continue
            self.require_keys(source, required, item_path)
            self.reject_unknown_keys(source, allowed, item_path)
            source_id = None
            if "id" in source:
                source_id = self.register_id(source["id"], _pointer(item_path, "id"), "source")
            for key in ("kind", "uri", "version", "license", "visibility"):
                if key in source:
                    self.nonempty_string(source[key], _pointer(item_path, key))
            for key in ("citation", "retrieved_at"):
                if key in source:
                    self.nonempty_string(source[key], _pointer(item_path, key))
            if "sha256" in source:
                digest_path = _pointer(item_path, "sha256")
                digest = self.nonempty_string(source["sha256"], digest_path)
                if digest is not None and _SHA256_RE.fullmatch(digest) is None:
                    self.add(
                        "invalid_sha256",
                        "sha256 must contain exactly 64 lowercase hexadecimal characters",
                        digest_path,
                    )
            if source_id is not None:
                self.source_ids.add(source_id)

    def validate_evidence_graph(self, value: Any, path: str) -> None:
        graph = self.expect_mapping(value, path)
        if graph is None:
            return
        required = {"records", "nodes", "edges", "claims"}
        self.require_keys(graph, required, path)
        self.reject_unknown_keys(graph, required, path)

        if "records" in graph:
            self.validate_evidence_records(graph["records"], _pointer(path, "records"))
        if "claims" in graph:
            self.validate_claims(graph["claims"], _pointer(path, "claims"))
        if "nodes" in graph:
            self.validate_nodes(graph["nodes"], _pointer(path, "nodes"))
        if "edges" in graph:
            self.validate_edges(graph["edges"], _pointer(path, "edges"))

    def validate_evidence_records(self, value: Any, path: str) -> None:
        records = self.expect_list(value, path)
        if records is None:
            return
        required = {"id", "kind", "statement", "source_refs", "confidence", "status"}
        allowed = required | {"conflict_set", "interpretation", "impact"}
        pending_source_refs: list[tuple[str, str]] = []
        for index, item in enumerate(records):
            item_path = _pointer(path, index)
            record = self.expect_mapping(item, item_path)
            if record is None:
                continue
            self.require_keys(record, required, item_path)
            self.reject_unknown_keys(record, allowed, item_path)
            evidence_id = None
            kind = None
            status = None
            if "id" in record:
                evidence_id = self.register_id(
                    record["id"], _pointer(item_path, "id"), "evidence"
                )
            if "kind" in record:
                kind = self.nonempty_string(record["kind"], _pointer(item_path, "kind"))
            if "statement" in record:
                self.nonempty_string(record["statement"], _pointer(item_path, "statement"))
            if "status" in record:
                status = self.nonempty_string(record["status"], _pointer(item_path, "status"))
            if "source_refs" in record:
                for ref in self.string_ids(
                    record["source_refs"], _pointer(item_path, "source_refs"), nonempty=True
                ):
                    pending_source_refs.append((ref, _pointer(item_path, "source_refs")))
            if "confidence" in record:
                confidence = record["confidence"]
                confidence_path = _pointer(item_path, "confidence")
                if not _is_number(confidence):
                    self.add("type", "confidence must be a number", confidence_path)
                else:
                    try:
                        numeric_confidence = float(confidence)
                    except OverflowError:
                        numeric_confidence = math.inf
                    if not math.isfinite(numeric_confidence) or not 0.0 <= numeric_confidence <= 1.0:
                        self.add("invalid_value", "confidence must be between 0 and 1", confidence_path)
            conflict_set = record.get("conflict_set")
            if "conflict_set" in record:
                self.nonempty_string(conflict_set, _pointer(item_path, "conflict_set"))
            if "interpretation" in record:
                self.nonempty_string(record["interpretation"], _pointer(item_path, "interpretation"))
            impact = record.get("impact")
            if "impact" in record:
                impact_path = _pointer(item_path, "impact")
                if impact not in {"low", "medium", "high"}:
                    self.add(
                        "invalid_value",
                        "impact must be one of 'low', 'medium', or 'high'",
                        impact_path,
                    )
            if evidence_id is not None:
                self.evidence_ids.add(evidence_id)
                is_conflict = conflict_set is not None or (
                    isinstance(kind, str) and "conflict" in kind.lower()
                )
                if is_conflict and status == "unresolved" and impact == "high":
                    self.high_impact_unresolved.add(evidence_id)

        for source_ref, ref_path in pending_source_refs:
            if source_ref not in self.source_ids:
                self.add(
                    "unknown_reference",
                    f"unknown source reference {source_ref!r}",
                    ref_path,
                )

    def validate_nodes(self, value: Any, path: str) -> None:
        nodes = self.expect_list(value, path)
        if nodes is None:
            return
        required = {"id", "kind"}
        allowed = required | {"label", "summary", "evidence_ids"}
        pending: list[tuple[str, str]] = []
        for index, item in enumerate(nodes):
            item_path = _pointer(path, index)
            node = self.expect_mapping(item, item_path)
            if node is None:
                continue
            self.require_keys(node, required, item_path)
            self.reject_unknown_keys(node, allowed, item_path)
            node_id = None
            if "id" in node:
                node_id = self.register_id(node["id"], _pointer(item_path, "id"), "node")
            if "kind" in node:
                self.nonempty_string(node["kind"], _pointer(item_path, "kind"))
            for key in ("label", "summary"):
                if key in node:
                    self.nonempty_string(node[key], _pointer(item_path, key))
            refs: set[str] = set()
            if "evidence_ids" in node:
                refs.update(self.string_ids(node["evidence_ids"], _pointer(item_path, "evidence_ids")))
                pending.extend((ref, _pointer(item_path, "evidence_ids")) for ref in refs)
            if node_id is not None:
                self.node_ids.add(node_id)
                self.node_evidence[node_id] = refs
        self._check_evidence_refs(pending)

    def validate_edges(self, value: Any, path: str) -> None:
        edges = self.expect_list(value, path)
        if edges is None:
            return
        required = {"source", "target", "kind"}
        allowed = required | {"id", "evidence_ids"}
        pending_nodes: list[tuple[str, str]] = []
        pending_evidence: list[tuple[str, str]] = []
        for index, item in enumerate(edges):
            item_path = _pointer(path, index)
            edge = self.expect_mapping(item, item_path)
            if edge is None:
                continue
            self.require_keys(edge, required, item_path)
            self.reject_unknown_keys(edge, allowed, item_path)
            if "id" in edge:
                self.register_id(edge["id"], _pointer(item_path, "id"), "edge")
            for key in ("source", "target"):
                if key in edge:
                    ref_path = _pointer(item_path, key)
                    node_ref = self.nonempty_string(edge[key], ref_path)
                    if node_ref is not None:
                        pending_nodes.append((node_ref, ref_path))
            if "kind" in edge:
                self.nonempty_string(edge["kind"], _pointer(item_path, "kind"))
            if "evidence_ids" in edge:
                pending_evidence.extend(
                    (ref, _pointer(item_path, "evidence_ids"))
                    for ref in self.string_ids(edge["evidence_ids"], _pointer(item_path, "evidence_ids"))
                )
        for node_ref, ref_path in pending_nodes:
            if node_ref not in self.node_ids:
                self.add("unknown_reference", f"unknown node reference {node_ref!r}", ref_path)
        self._check_evidence_refs(pending_evidence)

    def validate_claims(self, value: Any, path: str) -> None:
        claims = self.expect_list(value, path)
        if claims is None:
            return
        required = {"id", "statement", "evidence_ids"}
        allowed = required | {"status", "impact", "conflict_set", "interpretation"}
        pending: list[tuple[str, str]] = []
        for index, item in enumerate(claims):
            item_path = _pointer(path, index)
            claim = self.expect_mapping(item, item_path)
            if claim is None:
                continue
            self.require_keys(claim, required, item_path)
            self.reject_unknown_keys(claim, allowed, item_path)
            claim_id = None
            if "id" in claim:
                claim_id = self.register_id(claim["id"], _pointer(item_path, "id"), "claim")
            if "statement" in claim:
                self.nonempty_string(claim["statement"], _pointer(item_path, "statement"))
            refs: set[str] = set()
            if "evidence_ids" in claim:
                refs.update(
                    self.string_ids(
                        claim["evidence_ids"], _pointer(item_path, "evidence_ids"), nonempty=True
                    )
                )
                pending.extend((ref, _pointer(item_path, "evidence_ids")) for ref in refs)
            status = claim.get("status")
            if "status" in claim:
                self.nonempty_string(status, _pointer(item_path, "status"))
            impact = claim.get("impact")
            if "impact" in claim and impact not in {"low", "medium", "high"}:
                self.add(
                    "invalid_value",
                    "impact must be one of 'low', 'medium', or 'high'",
                    _pointer(item_path, "impact"),
                )
            conflict_set = claim.get("conflict_set")
            if "conflict_set" in claim:
                self.nonempty_string(conflict_set, _pointer(item_path, "conflict_set"))
            if "interpretation" in claim:
                self.nonempty_string(claim["interpretation"], _pointer(item_path, "interpretation"))
            if claim_id is not None:
                self.claim_ids.add(claim_id)
                self.claim_evidence[claim_id] = refs
                if conflict_set is not None and status == "unresolved" and impact == "high":
                    self.high_impact_unresolved.add(claim_id)
        self._check_evidence_refs(pending, records_only=True)

    def _check_evidence_refs(
        self, refs: list[tuple[str, str]], *, records_only: bool = False
    ) -> None:
        valid = self.evidence_ids if records_only else self.evidence_ids | self.claim_ids
        for evidence_ref, ref_path in refs:
            if evidence_ref not in valid:
                self.add(
                    "unknown_reference",
                    f"unknown evidence reference {evidence_ref!r}",
                    ref_path,
                )

    def validate_tasks(self, value: Any, path: str) -> None:
        tasks = self.expect_list(value, path)
        if tasks is None:
            return
        required = {
            "id",
            "title",
            "mode",
            "family",
            "summary",
            "evidence_ids",
            "workflow_nodes",
            "instances",
            "resource_budget",
            "output_contract",
            "evaluation",
            "tags",
        }
        for index, item in enumerate(tasks):
            item_path = _pointer(path, index)
            task = self.expect_mapping(item, item_path)
            if task is None:
                continue
            self.require_keys(task, required, item_path)
            self.reject_unknown_keys(task, required | {"difficulty"}, item_path)
            if "id" in task:
                self.safe_path_id(task["id"], _pointer(item_path, "id"), "task")
            for key in ("title", "family", "summary"):
                if key in task:
                    self.nonempty_string(task[key], _pointer(item_path, key))
            if "mode" in task:
                mode_path = _pointer(item_path, "mode")
                mode = self.nonempty_string(task["mode"], mode_path)
                if mode is not None and mode not in TASK_MODES:
                    self.add(
                        "invalid_mode",
                        "mode must be one of " + ", ".join(sorted(TASK_MODES)),
                        mode_path,
                    )

            task_evidence: list[str] = []
            if "evidence_ids" in task:
                task_evidence = self.string_ids(
                    task["evidence_ids"], _pointer(item_path, "evidence_ids"), nonempty=True
                )
                self._check_evidence_refs(
                    [(ref, _pointer(item_path, "evidence_ids")) for ref in task_evidence]
                )

            task_nodes: list[str] = []
            if "workflow_nodes" in task:
                node_path = _pointer(item_path, "workflow_nodes")
                task_nodes = self.string_ids(task["workflow_nodes"], node_path, nonempty=True)
                for node_ref in task_nodes:
                    if node_ref not in self.node_ids:
                        self.add(
                            "unknown_reference",
                            f"unknown workflow node {node_ref!r}",
                            node_path,
                        )

            if "instances" in task:
                instances_path = _pointer(item_path, "instances")
                instances = task["instances"]
                if not isinstance(instances, int) or isinstance(instances, bool):
                    self.add("type", "instances must be an integer", instances_path)
                elif instances < 1:
                    self.add("invalid_value", "instances must be at least 1", instances_path)
            if "difficulty" in task:
                self.validate_task_difficulty(
                    task["difficulty"],
                    _pointer(item_path, "difficulty"),
                    task.get("instances"),
                    _pointer(item_path, "instances"),
                )
            if "resource_budget" in task:
                self.validate_resources(task["resource_budget"], _pointer(item_path, "resource_budget"))
            if "output_contract" in task:
                self.expect_mapping(task["output_contract"], _pointer(item_path, "output_contract"))
            if "evaluation" in task:
                self.validate_evaluation(task["evaluation"], _pointer(item_path, "evaluation"))
            if "tags" in task:
                self.string_ids(task["tags"], _pointer(item_path, "tags"))

            used_evidence = set(task_evidence)
            for claim_id in set(task_evidence) & self.claim_ids:
                used_evidence.update(self.claim_evidence.get(claim_id, set()))
            for node_id in task_nodes:
                used_evidence.update(self.node_evidence.get(node_id, set()))
            conflicts = sorted(used_evidence & self.high_impact_unresolved)
            if conflicts:
                self.add(
                    "unresolved_high_impact_conflict",
                    "task references unresolved high-impact conflict(s): " + ", ".join(conflicts),
                    _pointer(item_path, "evidence_ids"),
                )

    def validate_task_difficulty(
        self,
        value: Any,
        path: str,
        instances: Any,
        instances_path: str,
    ) -> None:
        problems = validate_difficulty_selection(value, self.difficulty_profiles)
        for problem in problems:
            self.add(
                f"difficulty_{problem.code}",
                problem.message,
                path + problem.path,
            )
        if problems or not isinstance(value, Mapping):
            return
        profile = self.difficulty_profiles[(value["profile_id"], value["profile_version"])]
        level = next(item for item in profile["levels"] if item["name"] == value["level"])
        resolved_instances = value.get("generator_overrides", {}).get(
            "instance_count", level["generator"]["instance_count"]
        )
        if (
            isinstance(instances, int)
            and not isinstance(instances, bool)
            and instances != resolved_instances
        ):
            self.add(
                "difficulty_instance_mismatch",
                f"instances must equal resolved difficulty generator.instance_count ({resolved_instances})",
                instances_path,
            )

    def validate_resources(self, value: Any, path: str) -> None:
        resources = self.expect_mapping(value, path)
        if resources is None:
            return
        for key, amount in resources.items():
            amount_path = _pointer(path, key)
            if not isinstance(key, str) or not key.strip():
                self.add("invalid_value", "resource name must be a nonempty string", amount_path)
            if not _is_number(amount):
                self.add("type", "resource amount must be a number", amount_path)
            elif not math.isfinite(float(amount)) or float(amount) < 0:
                self.add("invalid_value", "resource amount must be nonnegative", amount_path)

    def validate_evaluation(self, value: Any, path: str) -> None:
        evaluation = self.expect_mapping(value, path)
        if evaluation is None:
            return
        allowed = {"weights", "metrics", "gates", "grader", "description"}
        self.reject_unknown_keys(evaluation, allowed, path)
        self.require_keys(evaluation, {"gates"}, path)
        if "weights" not in evaluation and "metrics" not in evaluation:
            self.add(
                "required",
                "evaluation must define either weights or weighted metrics",
                path,
            )
        if "grader" in evaluation:
            self.nonempty_string(evaluation["grader"], _pointer(path, "grader"))
        if "description" in evaluation:
            self.nonempty_string(evaluation["description"], _pointer(path, "description"))
        if "weights" in evaluation:
            self.validate_weights(evaluation["weights"], _pointer(path, "weights"))
        if "metrics" in evaluation:
            self.validate_metrics(evaluation["metrics"], _pointer(path, "metrics"))
        if "gates" in evaluation:
            gates_path = _pointer(path, "gates")
            gates = self.expect_list(evaluation["gates"], gates_path)
            if gates is not None:
                if not gates:
                    self.add("invalid_value", "evaluation must include at least one gate", gates_path)
                for index, gate in enumerate(gates):
                    gate_path = _pointer(gates_path, index)
                    if isinstance(gate, str):
                        self.nonempty_string(gate, gate_path)
                    elif isinstance(gate, Mapping):
                        if not gate:
                            self.add("invalid_value", "gate object must not be empty", gate_path)
                        elif "id" in gate:
                            self.nonempty_string(gate["id"], _pointer(gate_path, "id"))
                    else:
                        self.add("type", "gate must be a string or object", gate_path)

    def validate_weights(self, value: Any, path: str) -> None:
        weights = self.expect_mapping(value, path)
        if weights is None:
            return
        if not weights:
            self.add("invalid_value", "weights must not be empty", path)
            return
        values: list[float] = []
        for name, weight in weights.items():
            weight_path = _pointer(path, name)
            if not isinstance(name, str) or not name.strip():
                self.add("invalid_value", "weight name must be a nonempty string", weight_path)
            if not _is_number(weight):
                self.add("type", "weight must be a number", weight_path)
            elif not math.isfinite(float(weight)) or float(weight) < 0:
                self.add("invalid_value", "weight must be nonnegative", weight_path)
            else:
                values.append(float(weight))
        self.check_weight_sum(values, path)

    def validate_metrics(self, value: Any, path: str) -> None:
        metrics = self.expect_list(value, path)
        if metrics is None:
            return
        if not metrics:
            self.add("invalid_value", "metrics must not be empty", path)
            return
        values: list[float] = []
        metric_ids: set[str] = set()
        allowed = {"id", "weight", "direction", "threshold", "description"}
        for index, item in enumerate(metrics):
            item_path = _pointer(path, index)
            metric = self.expect_mapping(item, item_path)
            if metric is None:
                continue
            self.require_keys(metric, {"id", "weight"}, item_path)
            self.reject_unknown_keys(metric, allowed, item_path)
            if "id" in metric:
                metric_id = self.nonempty_string(metric["id"], _pointer(item_path, "id"))
                if metric_id is not None:
                    if metric_id in metric_ids:
                        self.add("duplicate_id", f"duplicate metric id {metric_id!r}", _pointer(item_path, "id"))
                    metric_ids.add(metric_id)
            if "weight" in metric:
                weight = metric["weight"]
                weight_path = _pointer(item_path, "weight")
                if not _is_number(weight):
                    self.add("type", "weight must be a number", weight_path)
                elif not math.isfinite(float(weight)) or float(weight) < 0:
                    self.add("invalid_value", "weight must be nonnegative", weight_path)
                else:
                    values.append(float(weight))
            if "direction" in metric:
                self.nonempty_string(metric["direction"], _pointer(item_path, "direction"))
            if "threshold" in metric:
                threshold_path = _pointer(item_path, "threshold")
                threshold = metric["threshold"]
                if not _is_number(threshold):
                    self.add("type", "threshold must be a number", threshold_path)
                elif not math.isfinite(float(threshold)):
                    self.add("invalid_value", "threshold must be finite", threshold_path)
            if "description" in metric:
                self.nonempty_string(metric["description"], _pointer(item_path, "description"))
        self.check_weight_sum(values, path)

    def check_weight_sum(self, values: list[float], path: str) -> None:
        if values and not math.isclose(sum(values), 1.0, rel_tol=1e-6, abs_tol=1e-6):
            self.add(
                "weight_sum",
                f"evaluation weights must sum to 1 (got {sum(values):.12g})",
                path,
            )


def validate_project(data: Any) -> list[Issue]:
    """Return all structural, reference, and publication-policy issues."""

    return _Validator().validate(data)


def require_valid_project(data: dict[str, Any]) -> dict[str, Any]:
    """Return *data* when valid, otherwise raise ``ValueError`` with all errors."""

    issues = [issue for issue in validate_project(data) if issue.severity == "error"]
    if issues:
        details = "\n".join(
            f"- {issue.path}: [{issue.code}] {issue.message}" for issue in issues
        )
        raise ValueError(f"invalid paper2ale project:\n{details}")
    return data


__all__ = [
    "Issue",
    "PROJECT_SCHEMA_VERSION",
    "TASK_MODES",
    "canonical_json_bytes",
    "load_project",
    "require_valid_project",
    "validate_project",
]
