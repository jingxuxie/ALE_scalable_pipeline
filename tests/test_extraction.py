from __future__ import annotations

import copy
from unittest import mock
import unittest

from paper2ale.extraction import build_extraction_request, extract_project
from paper2ale.providers import MockProvider


def source_bundle() -> list[dict]:
    return [
        {
            "id": "source.paper",
            "kind": "paper",
            "uri": "https://example.test/paper.pdf",
            "version": "v1",
            "license": "test-only",
            "visibility": "author",
            "sha256": "a" * 64,
        }
    ]


def project() -> dict:
    return {
        "schema_version": "paper2ale.project/v1",
        "project_id": "extracted-project",
        "source_bundle": source_bundle(),
        "evidence_graph": {
            "records": [
                {
                    "id": "evidence.method",
                    "kind": "method",
                    "statement": "A bounded method is described.",
                    "source_refs": ["source.paper"],
                    "confidence": 1.0,
                    "status": "supported",
                }
            ],
            "nodes": [
                {
                    "id": "workflow.run",
                    "kind": "inference",
                    "evidence_ids": ["evidence.method"],
                }
            ],
            "edges": [],
            "claims": [
                {
                    "id": "claim.result",
                    "statement": "The bounded workflow has a measurable result.",
                    "evidence_ids": ["evidence.method"],
                    "status": "supported",
                    "impact": "medium",
                }
            ],
        },
        "tasks": [
            {
                "id": "extracted-task",
                "title": "Extracted task",
                "mode": "specification_preserving",
                "family": "fixture",
                "summary": "A schema-valid extraction fixture.",
                "evidence_ids": ["claim.result"],
                "workflow_nodes": ["workflow.run"],
                "instances": 1,
                "resource_budget": {
                    "cpu_cores": 1,
                    "memory_mb": 128,
                    "wall_time_seconds": 30,
                },
                "output_contract": {"required_files": ["result.json"]},
                "evaluation": {
                    "weights": {"correctness": 1.0},
                    "gates": ["trusted_check"],
                },
                "tags": ["fixture"],
            }
        ],
    }


class ExtractionTests(unittest.TestCase):
    def test_request_key_covers_prompts_schema_payload_and_parameters(self) -> None:
        base = build_extraction_request(
            source_bundle(),
            "evidence",
            output_schema={"type": "object"},
            parameters={"temperature": 0},
        )
        changed_schema = build_extraction_request(
            source_bundle(),
            "evidence",
            output_schema={"type": "object", "required": ["project_id"]},
            parameters={"temperature": 0},
        )
        changed_evidence = build_extraction_request(
            source_bundle(),
            "different evidence",
            output_schema={"type": "object"},
            parameters={"temperature": 0},
        )
        changed_parameters = build_extraction_request(
            source_bundle(),
            "evidence",
            output_schema={"type": "object"},
            parameters={"temperature": 0.1},
        )
        with mock.patch("paper2ale.extraction.SYSTEM_PROMPT", "different prompt"):
            changed_prompt = build_extraction_request(
                source_bundle(),
                "evidence",
                output_schema={"type": "object"},
                parameters={"temperature": 0},
            )
        keys = {
            base.idempotency_key,
            changed_schema.idempotency_key,
            changed_evidence.idempotency_key,
            changed_parameters.idempotency_key,
            changed_prompt.idempotency_key,
        }
        self.assertEqual(len(keys), 5)

    def test_extract_project_preserves_exact_source_provenance(self) -> None:
        expected = project()
        result = extract_project(
            source_bundle(),
            "evidence",
            MockProvider([expected]),
            output_schema={"type": "object"},
        )
        self.assertEqual(result, expected)

    def test_extract_project_rejects_provenance_rewrite(self) -> None:
        rewritten = copy.deepcopy(project())
        rewritten["source_bundle"][0]["version"] = "latest"
        with self.assertRaisesRegex(ValueError, "exactly match requested provenance"):
            extract_project(
                source_bundle(),
                "evidence",
                MockProvider([rewritten]),
                output_schema={"type": "object"},
            )


if __name__ == "__main__":
    unittest.main()
