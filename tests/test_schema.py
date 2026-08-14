from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.ids import sha256_bytes, sha256_file, stable_id, stage_key
from paper2ale.schema import (
    Issue,
    canonical_json_bytes,
    load_project,
    require_valid_project,
    validate_project,
)


def valid_project() -> dict:
    return {
        "schema_version": "paper2ale.project/v1",
        "project_id": "project.hnn",
        "source_bundle": [
            {
                "id": "source.paper",
                "kind": "paper",
                "uri": "https://arxiv.org/abs/1906.01563",
                "version": "v3",
                "license": "arXiv",
                "visibility": "agent",
                "sha256": "a" * 64,
                "citation": "Greydanus, Dzamba, and Yosinski (2019)",
                "retrieved_at": "2026-08-13T00:00:00Z",
            }
        ],
        "evidence_graph": {
            "records": [
                {
                    "id": "evidence.hnn",
                    "kind": "method",
                    "statement": "The model predicts a scalar Hamiltonian.",
                    "source_refs": ["source.paper"],
                    "confidence": 1.0,
                    "status": "supported",
                }
            ],
            "nodes": [
                {
                    "id": "workflow.train",
                    "kind": "training",
                    "label": "Train the model",
                    "evidence_ids": ["evidence.hnn"],
                }
            ],
            "edges": [],
            "claims": [
                {
                    "id": "claim.energy",
                    "statement": "Hamiltonian structure reduces energy drift.",
                    "evidence_ids": ["evidence.hnn"],
                    "status": "supported",
                    "impact": "high",
                }
            ],
        },
        "tasks": [
            {
                "id": "task.hnn",
                "title": "Reproduce HNN energy conservation",
                "mode": "specification_preserving",
                "family": "hnn",
                "summary": "Train baseline and Hamiltonian models.",
                "evidence_ids": ["claim.energy"],
                "workflow_nodes": ["workflow.train"],
                "instances": 1,
                "resource_budget": {
                    "cpu_cores": 2,
                    "memory_mb": 2048,
                    "wall_time_seconds": 300,
                },
                "output_contract": {"required_files": ["metrics.json"]},
                "evaluation": {
                    "weights": {"accuracy": 0.4, "conservation": 0.6},
                    "gates": ["reference_rerun_passes"],
                },
                "tags": ["physics", "reproduction"],
            }
        ],
        "defaults": {"seed": 0},
    }


class IssueTests(unittest.TestCase):
    def test_issue_is_frozen_and_serializable(self) -> None:
        issue = Issue("bad", "A useful message", "/tasks/0")
        self.assertEqual(
            issue.to_dict(),
            {
                "code": "bad",
                "message": "A useful message",
                "path": "/tasks/0",
                "severity": "error",
            },
        )
        with self.assertRaises(FrozenInstanceError):
            issue.code = "changed"  # type: ignore[misc]


class ProjectValidationTests(unittest.TestCase):
    def test_valid_project_and_loader(self) -> None:
        project = valid_project()
        self.assertEqual(validate_project(project), [])
        self.assertIs(require_valid_project(project), project)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            path.write_text(json.dumps(project), encoding="utf-8")
            self.assertEqual(load_project(path), project)

    def test_project_requires_at_least_one_task(self) -> None:
        project = valid_project()
        project["tasks"] = []
        issues = validate_project(project)
        self.assertTrue(
            any(
                issue.code == "invalid_value" and issue.path == "/tasks"
                for issue in issues
            )
        )
        with self.assertRaisesRegex(ValueError, "tasks must contain at least one"):
            require_valid_project(project)

    def test_resolved_asset_snapshots_are_content_bound(self) -> None:
        project = valid_project()
        files = [
            {
                "relative_path": "data/train.csv",
                "size_bytes": 3,
                "sha256": hashlib.sha256(b"a,b").hexdigest(),
                "media_type": "text/csv",
                "extraction_status": "extracted",
                "extractor": "utf-8-text/v1",
            }
        ]
        tree = [
            {
                "relative_path": item["relative_path"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
            }
            for item in files
        ]
        project["asset_snapshots"] = [
            {
                "schema_version": "paper2ale.asset-snapshot/v1",
                "asset_id": "dataset.snapshot",
                "kind": "dataset",
                "content_sha256": hashlib.sha256(
                    canonical_json_bytes(tree)
                ).hexdigest(),
                "size_bytes": 3,
                "metadata": {"license": "test-only"},
                "files": files,
            }
        ]
        project["source_bundle"][0]["asset_id"] = "dataset.snapshot"
        self.assertEqual(validate_project(project), [])

        project["asset_snapshots"][0]["files"][0]["sha256"] = "0" * 64
        codes = {issue.code for issue in validate_project(project)}
        self.assertIn("asset_digest_mismatch", codes)

    def test_asset_snapshot_rejects_local_paths_and_unknown_links(self) -> None:
        project = valid_project()
        project["source_bundle"][0]["asset_id"] = "missing.snapshot"
        self.assertIn(
            "unknown_reference", {issue.code for issue in validate_project(project)}
        )

    def test_top_level_is_strict(self) -> None:
        project = valid_project()
        project["surprise"] = True
        issues = validate_project(project)
        self.assertTrue(
            any(
                issue.code == "additional_property" and issue.path == "/surprise"
                for issue in issues
            )
        )
        with self.assertRaisesRegex(ValueError, "unexpected property"):
            require_valid_project(project)

    def test_schema_version_and_mode_are_exact(self) -> None:
        project = valid_project()
        project["schema_version"] = "paper2ale.project/v2"
        project["tasks"][0]["mode"] = "free_form"
        codes = {issue.code for issue in validate_project(project)}
        self.assertIn("schema_version", codes)
        self.assertIn("invalid_mode", codes)

    def test_source_sha256_must_be_lowercase_hex(self) -> None:
        project = valid_project()
        project["source_bundle"][0]["sha256"] = "A" * 64
        issues = validate_project(project)
        self.assertTrue(any(issue.code == "invalid_sha256" for issue in issues))

    def test_source_kind_is_a_strict_enum(self) -> None:
        for invalid_kind in ("paper ", "data", "unknown", 1):
            with self.subTest(kind=invalid_kind):
                project = valid_project()
                project["source_bundle"][0]["kind"] = invalid_kind
                issues = validate_project(project)
                self.assertTrue(
                    any(
                        issue.code == "invalid_source_kind"
                        and issue.path == "/source_bundle/0/kind"
                        for issue in issues
                    )
                )

    def test_referential_integrity(self) -> None:
        project = valid_project()
        project["evidence_graph"]["records"][0]["source_refs"] = ["source.missing"]
        project["evidence_graph"]["edges"] = [
            {"source": "workflow.train", "target": "workflow.missing", "kind": "next"}
        ]
        project["tasks"][0]["evidence_ids"] = ["evidence.missing"]
        project["tasks"][0]["workflow_nodes"] = ["workflow.missing"]
        issues = validate_project(project)
        messages = "\n".join(issue.message for issue in issues)
        self.assertIn("source.missing", messages)
        self.assertIn("evidence.missing", messages)
        self.assertIn("workflow.missing", messages)
        self.assertGreaterEqual(sum(issue.code == "unknown_reference" for issue in issues), 4)

    def test_ids_are_globally_unique(self) -> None:
        project = valid_project()
        project["tasks"][0]["id"] = "workflow.train"
        issues = validate_project(project)
        self.assertTrue(any(issue.code == "duplicate_id" for issue in issues))

    def test_project_and_task_ids_are_safe_path_components(self) -> None:
        project = valid_project()
        project["project_id"] = "../outside"
        project["tasks"][0]["id"] = "CON"
        issues = validate_project(project)
        unsafe_paths = {issue.path for issue in issues if issue.code == "unsafe_id"}
        self.assertEqual(unsafe_paths, {"/project_id", "/tasks/0/id"})

    def test_unreferenced_conflict_is_allowed_but_task_usage_is_rejected(self) -> None:
        project = valid_project()
        conflict = {
            "id": "evidence.protocol-conflict",
            "kind": "source_conflict",
            "statement": "Paper prose and official code specify different dynamics.",
            "source_refs": ["source.paper"],
            "confidence": 1.0,
            "status": "unresolved",
            "conflict_set": "conflict.mass-spring-scale",
            "impact": "high",
        }
        project["evidence_graph"]["records"].append(conflict)
        self.assertFalse(
            any(
                issue.code == "unresolved_high_impact_conflict"
                for issue in validate_project(project)
            )
        )

        project["tasks"][0]["evidence_ids"].append(conflict["id"])
        issues = validate_project(project)
        conflict_issue = next(
            issue
            for issue in issues
            if issue.code == "unresolved_high_impact_conflict"
        )
        self.assertEqual(conflict_issue.path, "/tasks/0/evidence_ids")
        self.assertIn(conflict["id"], conflict_issue.message)

    def test_conflict_reached_through_claim_is_rejected(self) -> None:
        project = valid_project()
        project["evidence_graph"]["records"].append(
            {
                "id": "evidence.conflict",
                "kind": "conflict",
                "statement": "Two sources disagree.",
                "source_refs": ["source.paper"],
                "confidence": 0.9,
                "status": "unresolved",
                "conflict_set": "conflict.protocol",
                "impact": "high",
            }
        )
        project["evidence_graph"]["claims"][0]["evidence_ids"].append(
            "evidence.conflict"
        )
        self.assertTrue(
            any(
                issue.code == "unresolved_high_impact_conflict"
                for issue in validate_project(project)
            )
        )

    def test_resources_instances_weights_and_gates(self) -> None:
        project = valid_project()
        task = project["tasks"][0]
        task["instances"] = -1
        task["resource_budget"]["memory_mb"] = -5
        task["evaluation"] = {"weights": {"one": 0.2, "two": 0.2}, "gates": []}
        issues = validate_project(project)
        self.assertTrue(any(issue.path == "/tasks/0/instances" for issue in issues))
        self.assertTrue(any(issue.path.endswith("/memory_mb") for issue in issues))
        self.assertTrue(any(issue.code == "weight_sum" for issue in issues))
        self.assertTrue(
            any(issue.path == "/tasks/0/evaluation/gates" for issue in issues)
        )

    def test_zero_instances_is_rejected(self) -> None:
        project = valid_project()
        project["tasks"][0]["instances"] = 0
        issues = validate_project(project)
        self.assertTrue(any(issue.path == "/tasks/0/instances" for issue in issues))

    def test_existing_v1_project_needs_no_difficulty_metadata(self) -> None:
        project = valid_project()
        self.assertNotIn("difficulty", project["tasks"][0])
        self.assertNotIn("difficulty_profiles", project)
        self.assertEqual(validate_project(project), [])

    def test_builtin_difficulty_selection_is_enforced(self) -> None:
        project = valid_project()
        project["tasks"][0]["difficulty"] = {
            "profile_id": "core",
            "profile_version": 1,
            "level": "hard",
        }
        project["tasks"][0]["instances"] = 5
        self.assertEqual(validate_project(project), [])

        project["tasks"][0]["instances"] = 1
        issues = validate_project(project)
        mismatch = next(issue for issue in issues if issue.code == "difficulty_instance_mismatch")
        self.assertEqual(mismatch.path, "/tasks/0/instances")

    def test_difficulty_profile_reference_and_ranges_are_checked(self) -> None:
        project = valid_project()
        project["tasks"][0]["difficulty"] = {
            "profile_id": "missing",
            "profile_version": 1,
            "level": "hard",
        }
        issues = validate_project(project)
        self.assertTrue(any(issue.code == "difficulty_reference" for issue in issues))

        project = valid_project()
        project["tasks"][0]["difficulty"] = {
            "profile_id": "core",
            "profile_version": 1,
            "level": "easy",
            "generator_overrides": {"masked_fraction": 2},
        }
        issues = validate_project(project)
        self.assertTrue(any(issue.code == "difficulty_range" for issue in issues))

    def test_custom_profile_cannot_use_cosmetic_labels(self) -> None:
        from paper2ale.difficulty import builtin_profiles

        project = valid_project()
        profile = builtin_profiles()[0]
        profile["id"] = "custom"
        profile["levels"][1]["generator"] = copy.deepcopy(profile["levels"][0]["generator"])
        profile["levels"][1]["evaluator"] = copy.deepcopy(profile["levels"][0]["evaluator"])
        project["difficulty_profiles"] = [profile]
        issues = validate_project(project)
        self.assertTrue(any(issue.code == "difficulty_cosmetic_level" for issue in issues))

    def test_valid_custom_profile_resolves_for_a_task(self) -> None:
        from paper2ale.difficulty import builtin_profiles

        project = valid_project()
        profile = builtin_profiles()[0]
        profile["id"] = "hnn-calibrated"
        profile["version"] = 2
        project["difficulty_profiles"] = [profile]
        project["tasks"][0]["difficulty"] = {
            "profile_id": "hnn-calibrated",
            "profile_version": 2,
            "level": "medium",
        }
        project["tasks"][0]["instances"] = 3
        self.assertEqual(validate_project(project), [])

    def test_metrics_are_an_alternative_weight_form(self) -> None:
        project = valid_project()
        project["tasks"][0]["evaluation"] = {
            "metrics": [
                {"id": "mse", "weight": 0.75, "direction": "minimize"},
                {"id": "report", "weight": 0.25},
            ],
            "gates": [{"id": "finite_outputs", "critical": True}],
        }
        self.assertEqual(validate_project(project), [])


class IdentityTests(unittest.TestCase):
    def test_canonical_json_and_stable_ids_ignore_mapping_order(self) -> None:
        first = {"b": 2, "a": {"y": [2, 1], "x": True}}
        second = {"a": {"x": True, "y": [2, 1]}, "b": 2}
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(stable_id("candidate", first), stable_id("candidate", second))
        self.assertEqual(
            stage_key("extract", 1, {"paper": first}, {"mode": "strict", "jobs": 2}),
            stage_key("extract", 1, {"paper": second}, {"jobs": 2, "mode": "strict"}),
        )

    def test_content_changes_identity(self) -> None:
        self.assertNotEqual(stable_id("x", {"value": 1}), stable_id("x", {"value": 2}))
        self.assertNotEqual(
            stage_key("extract", 1, [], {}), stage_key("extract", 2, [], {})
        )

    def test_sha256_helpers(self) -> None:
        payload = b"paper2ale\n"
        expected = hashlib.sha256(payload).hexdigest()
        self.assertEqual(sha256_bytes(payload), expected)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(payload)
            self.assertEqual(sha256_file(path), expected)


if __name__ == "__main__":
    unittest.main()
