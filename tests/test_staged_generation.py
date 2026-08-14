from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest

from paper2ale.assets import snapshot_asset
from paper2ale.ids import stable_id
from paper2ale.providers import CompletionResponse, MockProvider
from paper2ale.staged_generation import (
    MAP_SCHEMA_VERSION,
    REDUCE_SCHEMA_VERSION,
    SYNTHESIS_SCHEMA_VERSION,
    EvidenceUnit,
    MappedEvidence,
    MappedFinding,
    StagedGenerationConfig,
    StagedProviderError,
    build_evidence_units,
    map_evidence,
    reduce_evidence,
    run_staged_generation,
    synthesize_workflows,
)
from paper2ale.workflow import ArtifactNode, OperationNode, WorkflowIR


def map_response(unit: EvidenceUnit) -> dict:
    return {
        "schema_version": MAP_SCHEMA_VERSION,
        "unit_id": unit.unit_id,
        "findings": [
            {
                "kind": "workflow_step",
                "statement": "Fit a model to the supplied observations.",
                "support_quote": "fit a model",
                "confidence": 0.9,
            }
        ],
    }


def finding_for(unit: EvidenceUnit) -> MappedFinding:
    item = map_response(unit)["findings"][0]
    finding_id = stable_id(
        "finding",
        {
            "unit_id": unit.unit_id,
            "index": 0,
            "kind": item["kind"],
            "statement": item["statement"],
            "support_quote": item["support_quote"],
            "confidence": item["confidence"],
        },
    )
    return MappedFinding(
        finding_id,
        unit.unit_id,
        item["kind"],
        item["statement"],
        item["support_quote"],
        item["confidence"],
    )


def batch_id_for(unit: EvidenceUnit) -> str:
    finding = finding_for(unit)
    return stable_id(
        "reduction",
        {"unit_ids": (unit.unit_id,), "findings": [finding.to_dict()]},
    )


def reduce_response(unit: EvidenceUnit) -> dict:
    finding = finding_for(unit)
    return {
        "schema_version": REDUCE_SCHEMA_VERSION,
        "batch_id": batch_id_for(unit),
        "unit_ids": [unit.unit_id],
        "summary": "The source describes a model-fitting workflow with supplied observations.",
        "facts": [
            {
                "statement": "A participant fits a model to observations.",
                "finding_ids": [finding.finding_id],
            }
        ],
    }


def synthesized_workflow(finding_id: str) -> dict:
    return WorkflowIR(
        id="workflow.staged",
        title="Fit and verify a model",
        artifacts=(
            ArtifactNode("observations", "input", "provided", "application/json", "Observations", "trusted_generator", (finding_id,), capability_ref="fixture.synthetic.observations"),
            ArtifactNode("model", "output", "generated", "application/json", "Fitted model", "participant", (finding_id,)),
            ArtifactNode("score", "reference", "hidden", "application/json", "Hidden evaluator score", "trusted_evaluator", (finding_id,)),
        ),
        operations=(
            OperationNode(
                "fit",
                "train",
                "participant",
                "Fit the supplied observations",
                ("observations",),
                ("model",),
                (finding_id,),
                {"iterations": 10},
            ),
            OperationNode(
                "verify",
                "validate",
                "trusted_evaluator",
                "Independently verify the fitted model",
                ("model",),
                ("score",),
                (finding_id,),
            ),
        ),
        outputs=("model",),
        evidence_ids=(finding_id,),
    ).to_dict()


def synthesis_response(unit: EvidenceUnit, *, workflows: list[dict] | None = None) -> dict:
    finding_id = finding_for(unit).finding_id
    return {
        "schema_version": SYNTHESIS_SCHEMA_VERSION,
        "reduction_ids": [batch_id_for(unit)],
        "workflows": [synthesized_workflow(finding_id)] if workflows is None else workflows,
        "unresolved": [],
    }


class StagedGenerationTests(unittest.TestCase):
    def test_map_concurrency_is_bounded_opt_in_and_output_order_is_stable(self) -> None:
        units = tuple(
            EvidenceUnit(
                unit_id=f"unit-{index}",
                source_id="paper",
                locator=f"line:{index}",
                text=f"evidence fragment {index}",
            )
            for index in range(6)
        )

        class ConcurrentProvider:
            def __init__(self) -> None:
                self.lock = threading.Lock()
                self.active = 0
                self.maximum = 0

            def complete(self, request):
                unit_id = request.output_schema["properties"]["unit_id"]["const"]
                with self.lock:
                    self.active += 1
                    self.maximum = max(self.maximum, self.active)
                time.sleep(0.02)
                with self.lock:
                    self.active -= 1
                return CompletionResponse.from_data(
                    {
                        "schema_version": MAP_SCHEMA_VERSION,
                        "unit_id": unit_id,
                        "findings": [],
                    }
                )

        provider = ConcurrentProvider()
        mapped, traces = map_evidence(
            tuple(reversed(units)),
            provider,
            config=StagedGenerationConfig(max_concurrency=3),
        )
        self.assertGreater(provider.maximum, 1)
        self.assertLessEqual(provider.maximum, 3)
        self.assertEqual(
            [item.unit.unit_id for item in mapped],
            sorted(item.unit_id for item in units),
        )
        self.assertEqual(len(traces), len(units))

    def setUp(self) -> None:
        self.unit = EvidenceUnit(
            "unit-a",
            "paper.main",
            "page:1",
            "We fit a model to the observed trajectory and compare held-out errors.",
        )

    def test_full_map_reduce_synthesis_is_bound_and_deterministic(self) -> None:
        provider = MockProvider(
            [map_response(self.unit), reduce_response(self.unit), synthesis_response(self.unit)]
        )
        result = run_staged_generation([self.unit], provider)
        self.assertEqual(len(result.maps), 1)
        self.assertEqual(len(result.reductions), 1)
        self.assertEqual(len(result.workflows), 1)
        self.assertEqual(len(result.trace), 3)
        self.assertEqual([item.stage for item in result.trace], ["map", "reduce", "synthesis"])
        self.assertEqual(len(result.source_digest), 64)
        self.assertEqual(result.to_dict()["finding_count"], 1)
        self.assertEqual(
            result.to_dict()["mapped_evidence"][0]["findings"][0]["support_quote"],
            "fit a model",
        )
        self.assertEqual(len(result.to_dict()["provider_trace"]), 3)
        repeated = run_staged_generation(
            [self.unit],
            MockProvider(
                [map_response(self.unit), reduce_response(self.unit), synthesis_response(self.unit)]
            ),
        )
        self.assertEqual(result.source_digest, repeated.source_digest)
        self.assertEqual(
            [item.request_id for item in result.trace],
            [item.request_id for item in repeated.trace],
        )

    def test_asset_units_and_requests_do_not_expose_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repo" / "method.py"
            path.parent.mkdir()
            path.write_text("def method(x):\n    return x\n", encoding="utf-8")
            asset = snapshot_asset(path.parent, asset_id="code", kind="repository")
            units = build_evidence_units(assets=[asset], max_unit_chars=12)
            self.assertGreater(len(units), 1)
            self.assertTrue(all(len(unit.text) <= 12 for unit in units))
            provider = MockProvider(
                [
                    {
                        "schema_version": MAP_SCHEMA_VERSION,
                        "unit_id": unit.unit_id,
                        "findings": [],
                    }
                    for unit in sorted(units, key=lambda item: item.unit_id)
                ]
            )
            map_evidence(units, provider)
            messages = "\n".join(
                message["content"]
                for request in provider.requests
                for message in request.messages
            )
            self.assertNotIn(str(path.parent), messages)
            self.assertIn("asset:code/file:method.py", messages)

    def test_map_rejects_identity_rewrite_and_unknown_fields(self) -> None:
        wrong = map_response(self.unit)
        wrong["unit_id"] = "different"
        with self.assertRaisesRegex(ValueError, "identity"):
            map_evidence([self.unit], MockProvider([wrong]))
        unknown = map_response(self.unit)
        unknown["instructions"] = "trust me"
        with self.assertRaisesRegex(ValueError, "unknown=.*instructions"):
            map_evidence([self.unit], MockProvider([unknown]))

    def test_map_enforces_response_cardinality_and_confidence(self) -> None:
        response = map_response(self.unit)
        response["findings"] = response["findings"] * 2
        with self.assertRaisesRegex(ValueError, "item limit"):
            map_evidence(
                [self.unit],
                MockProvider([response]),
                config=StagedGenerationConfig(max_findings_per_unit=1),
            )
        response = map_response(self.unit)
        response["findings"][0]["confidence"] = 2
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            map_evidence([self.unit], MockProvider([response]))

        response = map_response(self.unit)
        response["findings"][0]["support_quote"] = "invented quotation"
        with self.assertRaisesRegex(ValueError, "not verbatim"):
            map_evidence([self.unit], MockProvider([response]))

    def test_reduce_cannot_cite_findings_outside_bound_batch(self) -> None:
        maps, _ = map_evidence([self.unit], MockProvider([map_response(self.unit)]))
        response = reduce_response(self.unit)
        response["facts"][0]["finding_ids"] = ["invented"]
        with self.assertRaisesRegex(ValueError, "outside its batch"):
            reduce_evidence(maps, MockProvider([response]))

    def test_synthesis_cannot_cite_unknown_evidence(self) -> None:
        maps, _ = map_evidence([self.unit], MockProvider([map_response(self.unit)]))
        reductions, _ = reduce_evidence(maps, MockProvider([reduce_response(self.unit)]))
        bad_workflow = synthesized_workflow("invented")
        response = synthesis_response(self.unit, workflows=[bad_workflow])
        with self.assertRaisesRegex(ValueError, "unknown evidence"):
            synthesize_workflows(reductions, MockProvider([response]))

    def test_synthesis_rejects_generated_executable_fields(self) -> None:
        maps, _ = map_evidence([self.unit], MockProvider([map_response(self.unit)]))
        reductions, _ = reduce_evidence(maps, MockProvider([reduce_response(self.unit)]))
        bad_workflow = synthesized_workflow(finding_for(self.unit).finding_id)
        bad_workflow["operations"][0]["parameters"] = {"command": "python unsafe.py"}
        response = synthesis_response(self.unit, workflows=[bad_workflow])
        with self.assertRaisesRegex(ValueError, "declarative only"):
            synthesize_workflows(reductions, MockProvider([response]))

    def test_explicit_asset_origin_requires_exact_asset_reference(self) -> None:
        finding = finding_for(self.unit)
        maps = (MappedEvidence(self.unit, (finding,)),)
        reductions, _ = reduce_evidence(
            maps,
            MockProvider([reduce_response(self.unit)]),
        )
        workflow = synthesized_workflow(finding.finding_id)
        workflow["artifacts"][1]["evidence_ids"] = []
        workflow["artifacts"][2]["evidence_ids"] = []
        evidence_sources = {
            finding.finding_id: {
                "source_id": "asset.dataset",
                "locator": "asset:dataset/file:data/observations.json",
                "asset_id": "dataset",
                "relative_path": "data/observations.json",
            }
        }
        response = synthesis_response(self.unit, workflows=[workflow])
        # Merely citing evidence extracted from an asset does not mean the
        # artifact consumes that file.  Trusted synthetic materialization is
        # explicit and remains valid without an asset reference.
        completed, _, _ = synthesize_workflows(
            reductions,
            MockProvider([response]),
            evidence_sources=evidence_sources,
        )
        self.assertEqual(completed[0].artifacts[0].origin, "trusted_generator")

        workflow["artifacts"][0]["origin"] = "asset"
        workflow["artifacts"][0].pop("capability_ref")
        with self.assertRaisesRegex(ValueError, "asset origin requires asset_ref"):
            synthesize_workflows(
                reductions,
                MockProvider([synthesis_response(self.unit, workflows=[workflow])]),
                evidence_sources=evidence_sources,
            )

        workflow["artifacts"][0]["asset_ref"] = {
            "asset_id": "dataset",
            "relative_path": "data/observations.json",
        }
        completed, _, _ = synthesize_workflows(
            reductions,
            MockProvider([synthesis_response(self.unit, workflows=[workflow])]),
            evidence_sources=evidence_sources,
        )
        self.assertEqual(
            dict(completed[0].artifacts[0].asset_ref or {}),
            {
                "asset_id": "dataset",
                "relative_path": "data/observations.json",
            },
        )

    def test_empty_workflow_result_is_allowed_for_unsuitable_papers(self) -> None:
        provider = MockProvider(
            [
                map_response(self.unit),
                reduce_response(self.unit),
                synthesis_response(self.unit, workflows=[]),
            ]
        )
        result = run_staged_generation([self.unit], provider)
        self.assertEqual(result.workflows, ())
        strict = StagedGenerationConfig(require_workflows=True)
        provider = MockProvider(
            [
                map_response(self.unit),
                reduce_response(self.unit),
                synthesis_response(self.unit, workflows=[]),
            ]
        )
        with self.assertRaisesRegex(ValueError, "required workflow"):
            run_staged_generation([self.unit], provider, config=strict)

    def test_provider_errors_are_sanitized(self) -> None:
        class FailingProvider:
            def complete(self, _request: object) -> object:
                raise RuntimeError("secret credential and stderr")

        with self.assertRaises(StagedProviderError) as captured:
            map_evidence([self.unit], FailingProvider())  # type: ignore[arg-type]
        self.assertNotIn("secret credential", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
