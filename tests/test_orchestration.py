from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.assets import AssetSpec, resolve_assets  # noqa: E402
from paper2ale.ids import stable_id  # noqa: E402
from paper2ale.orchestration import (  # noqa: E402
    ORCHESTRATION_MANIFEST_SCHEMA_VERSION,
    OrchestrationGateError,
    OrchestrationManifest,
    SourceSpec,
    _PathGuardProvider,
    load_orchestration_manifest,
    orchestration_manifest_json_schema,
    orchestrate_project,
)
from paper2ale.providers import (  # noqa: E402
    CompletionRequest,
    MockProvider,
    ReplayProvider,
)
from paper2ale.source_ingest import ingest_sources, source_bundle  # noqa: E402
from paper2ale.staged_generation import (  # noqa: E402
    MAP_SCHEMA_VERSION,
    REDUCE_SCHEMA_VERSION,
    SYNTHESIS_SCHEMA_VERSION,
    StagedGenerationConfig,
    build_evidence_units,
)
from paper2ale.task_families.generic import PROTOCOL_SCHEMA_VERSION  # noqa: E402
from paper2ale.triage import PaperProfile  # noqa: E402


SOURCE_TEXT = (
    "The workflow reads a numeric input table, applies a fixed affine "
    "transformation, and verifies predictions against hidden reference values.\n"
)
SUPPORT_QUOTE = "verifies predictions against hidden reference values"


def numeric_protocol() -> dict:
    return {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "template_id": "numeric-affine-v1",
        "generator": {
            "primitive": "uniform_numeric_matrix",
            "input_dimension": 2,
            "output_dimension": 2,
            "query_count": 4,
            "public_example_count": 6,
            "low": -2,
            "high": 2,
            "decimals": 6,
            "public_noise_std": 0,
        },
        "reference_solver": {
            "primitive": "affine_transform",
            "weights": [[2.0, -0.5], [0.25, 1.5]],
            "bias": [0.5, -1.0],
        },
        "output": {
            "primitive": "numeric_predictions_json",
            "filename": "submission.json",
        },
        "evaluation": {
            "metrics": [
                {
                    "id": "rmse",
                    "primitive": "numeric_rmse",
                    "threshold": 1e-9,
                    "weight": 0.7,
                },
                {
                    "id": "maximum_error",
                    "primitive": "numeric_max_abs",
                    "threshold": 1e-8,
                    "weight": 0.3,
                },
            ],
            "gates": [
                "strict_json",
                "max_bytes",
                "shape_match",
                "finite_numbers",
                "query_id_match",
            ],
            "max_submission_bytes": 65536,
            "required_pass_fraction": 1.0,
        },
    }


class EndToEndFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source_path = root / "paper.txt"
        self.source_path.write_text(SOURCE_TEXT, encoding="utf-8")
        self.asset_path = root / "repository.bin"
        self.asset_path.write_bytes(b"\x00\x01trusted-binary-snapshot")
        self.metadata = {
            "id": "paper-source",
            "kind": "paper",
            "uri": "https://example.invalid/paper",
            "version": "v1",
            "license": "CC-BY-4.0",
            "visibility": "public",
        }
        self.paper = PaperProfile(
            paper_id="paper-source",
            title="Affine workflow",
            readable=True,
            provenance_complete=True,
            license_status="known",
            scientific_quality=0.95,
            evidence_coverage=0.95,
            independent_verification_possible=True,
            public_code=True,
            code_license_known=True,
            workflow_reconstructable=True,
            contradictions_resolved=True,
            resources_bounded=True,
        )
        self.config = StagedGenerationConfig(
            require_workflows=True,
            max_units=8,
            reduce_batch_size=8,
            max_reductions=2,
            max_workflows=2,
        )

    def manifest(
        self,
        output_name: str = "project.json",
        *,
        paper: PaperProfile | None = None,
        release: bool = False,
    ) -> OrchestrationManifest:
        return OrchestrationManifest(
            project_id="orchestration-e2e",
            paper=paper or self.paper,
            sources=(SourceSpec(self.source_path, self.metadata),),
            assets=(
                AssetSpec(
                    "repo-snapshot",
                    self.asset_path,
                    "repository",
                    {"visibility": "public", "license": "MIT"},
                ),
            ),
            output_path=self.root / output_name,
            staged_config=self.config,
            release=release,
        )

    def responses(self, *, unsupported_protocol: bool = False) -> list[dict]:
        sources = ingest_sources([self.source_path], [self.metadata])
        assets = resolve_assets(
            (
                AssetSpec(
                    "repo-snapshot",
                    self.asset_path,
                    "repository",
                    {"visibility": "public", "license": "MIT"},
                ),
            )
        )
        unit = build_evidence_units(sources=sources, assets=assets)[0]
        map_finding = {
            "kind": "verification",
            "statement": "The workflow has an independently checkable numeric output.",
            "support_quote": SUPPORT_QUOTE,
            "confidence": 0.95,
        }
        finding_id = stable_id(
            "finding",
            {
                "unit_id": unit.unit_id,
                "index": 0,
                **map_finding,
            },
        )
        mapped_finding = {
            "finding_id": finding_id,
            "unit_id": unit.unit_id,
            **map_finding,
        }
        batch_id = stable_id(
            "reduction",
            {
                "unit_ids": (unit.unit_id,),
                "findings": [mapped_finding],
            },
        )
        protocol = numeric_protocol()
        workflow = {
            "schema_version": "paper2ale.workflow/v2",
            "id": "affine-workflow",
            "title": "Affine prediction and verification",
            "artifacts": [
                {
                    "id": "input-data",
                    "role": "input",
                    "availability": "provided",
                    "media_type": "application/json",
                    "description": "Bounded numeric examples and query inputs.",
                    "origin": "trusted_generator",
                    "capability_ref": "generic.numeric-affine-v1.input",
                    "evidence_ids": [finding_id],
                },
                {
                    "id": "predictions",
                    "role": "output",
                    "availability": "generated",
                    "media_type": "application/json",
                    "description": "Predicted numeric outputs.",
                    "origin": "participant",
                    "evidence_ids": [finding_id],
                },
                {
                    "id": "verification-report",
                    "role": "intermediate",
                    "availability": "generated",
                    "media_type": "application/json",
                    "description": "Trusted metric result.",
                    "origin": "trusted_evaluator",
                    "evidence_ids": [finding_id],
                },
            ],
            "operations": [
                {
                    "id": "solve",
                    "operation_type": "infer",
                    "authority": "participant",
                    "description": "Infer the affine map and predict queries.",
                    "inputs": ["input-data"],
                    "outputs": ["predictions"],
                    "evidence_ids": [finding_id],
                    "parameters": {"protocol": protocol},
                },
                {
                    "id": "verify",
                    "operation_type": "evaluate",
                    "authority": "trusted_evaluator",
                    "description": "Compare predictions to hidden reference values.",
                    "inputs": ["predictions"],
                    "outputs": ["verification-report"],
                    "evidence_ids": [finding_id],
                    "parameters": {
                        "output": protocol["output"],
                        "evaluation": protocol["evaluation"],
                    },
                },
            ],
            "outputs": ["predictions"],
            "evidence_ids": [finding_id],
        }
        if unsupported_protocol:
            protocol["reference_solver"]["primitive"] = "python_eval"
        project = {
            "schema_version": "paper2ale.project/v1",
            "project_id": "orchestration-e2e",
            "source_bundle": source_bundle(sources),
            "asset_snapshots": [item.to_dict(include_text=False) for item in assets],
            "evidence_graph": {
                "records": [
                    {
                        "id": finding_id,
                        "kind": "verification",
                        "statement": map_finding["statement"],
                        "source_refs": ["paper-source"],
                        "confidence": 0.95,
                        "status": "supported",
                    }
                ],
                "nodes": [
                    {
                        "id": "solve",
                        "kind": "participant_operation",
                        "label": "Solve",
                        "evidence_ids": [finding_id],
                    },
                    {
                        "id": "verify",
                        "kind": "trusted_evaluator_operation",
                        "label": "Verify",
                        "evidence_ids": [finding_id],
                    },
                ],
                "edges": [
                    {
                        "source": "solve",
                        "target": "verify",
                        "kind": "evaluated_by",
                        "evidence_ids": [finding_id],
                    }
                ],
                "claims": [],
            },
            "tasks": [
                {
                    "id": "affine-recovery",
                    "title": "Recover a hidden affine transformation",
                    "mode": "method_masked_rediscovery",
                    "family": "generic",
                    "summary": "Infer a numeric transformation from bounded examples.",
                    "evidence_ids": [finding_id],
                    "workflow_nodes": ["solve"],
                    "instances": 1,
                    "resource_budget": {"cpu_seconds": 30, "memory_mb": 512},
                    "output_contract": {
                        "format": "numeric_predictions_json",
                        "filename": "submission.json",
                    },
                    "protocol": protocol,
                    "evaluation": {
                        "metrics": [
                            {
                                "id": "rmse",
                                "weight": 0.7,
                                "direction": "lower_is_better",
                                "threshold": 1e-9,
                            },
                            {
                                "id": "maximum_error",
                                "weight": 0.3,
                                "direction": "lower_is_better",
                                "threshold": 1e-8,
                            },
                        ],
                        "gates": [
                            "strict_json",
                            "max_bytes",
                            "shape_match",
                            "finite_numbers",
                            "query_id_match",
                        ],
                    },
                    "tags": ["numeric", "paper-blind"],
                }
            ],
        }
        return [
            {
                "schema_version": MAP_SCHEMA_VERSION,
                "unit_id": unit.unit_id,
                "findings": [map_finding],
            },
            {
                "schema_version": REDUCE_SCHEMA_VERSION,
                "batch_id": batch_id,
                "unit_ids": [unit.unit_id],
                "summary": "A bounded affine workflow has a hidden numeric verifier.",
                "facts": [
                    {
                        "statement": "Predictions can be checked against hidden references.",
                        "finding_ids": [finding_id],
                    }
                ],
            },
            {
                "schema_version": SYNTHESIS_SCHEMA_VERSION,
                "reduction_ids": [batch_id],
                "workflows": [workflow],
                "unresolved": [],
            },
            project,
        ]


class OrchestrationTests(unittest.TestCase):
    @staticmethod
    def json_strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [
                text
                for key, child in value.items()
                for text in [key, *OrchestrationTests.json_strings(child)]
            ]
        if isinstance(value, (list, tuple)):
            return [
                text
                for child in value
                for text in OrchestrationTests.json_strings(child)
            ]
        return []

    def test_checked_in_offline_replay_fixture_runs_without_credentials(self) -> None:
        fixture_root = ROOT / "examples" / "orchestration"
        manifest = load_orchestration_manifest(fixture_root / "manifest.json")
        with tempfile.TemporaryDirectory() as directory:
            isolated = replace(
                manifest,
                output_path=str(Path(directory) / "project.json"),
                overwrite=False,
            )
            receipt = orchestrate_project(
                isolated,
                ReplayProvider(fixture_root / "replay.json"),
            ).to_dict()
        self.assertEqual(receipt["project_id"], "orchestration-offline-demo")
        self.assertEqual(receipt["triage"]["paper"]["decision"], "eligible")
        self.assertEqual(len(receipt["candidates"]), 1)
        self.assertEqual(receipt["publication"]["status"], "validated_candidate")

    def test_manifest_round_trip_schema_and_relative_path_loading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            document = fixture.manifest().to_dict()
            document["sources"][0]["path"] = "paper.txt"
            document["assets"][0]["path"] = "repository.bin"
            document["output_path"] = "output/project.json"

            parsed = OrchestrationManifest.from_dict(document)
            self.assertEqual(parsed.to_dict(), document)
            self.assertEqual(parsed.sources[0].path, "paper.txt")
            self.assertEqual(parsed.output_path, "output/project.json")

            schema = orchestration_manifest_json_schema()
            self.assertEqual(
                schema["$schema"],
                "https://json-schema.org/draft/2020-12/schema",
            )
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(
                schema["properties"]["schema_version"]["const"],
                ORCHESTRATION_MANIFEST_SCHEMA_VERSION,
            )
            self.assertIn("paper_profile", schema["$defs"])

            config_dir = fixture.root / "config"
            config_dir.mkdir()
            load_document = copy.deepcopy(document)
            load_document["sources"][0]["path"] = "../paper.txt"
            load_document["assets"][0]["path"] = "../repository.bin"
            load_document["output_path"] = "../loaded-project.json"
            manifest_path = config_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(load_document, sort_keys=True), encoding="utf-8"
            )
            loaded = load_orchestration_manifest(manifest_path)
            self.assertEqual(Path(loaded.sources[0].path), fixture.source_path.resolve())
            self.assertEqual(Path(loaded.assets[0].path), fixture.asset_path.resolve())
            self.assertEqual(
                Path(loaded.output_path),
                (fixture.root / "loaded-project.json").resolve(),
            )

            override_document = copy.deepcopy(document)
            override_path = config_dir / "override.json"
            override_path.write_text(
                json.dumps(override_document, sort_keys=True), encoding="utf-8"
            )
            overridden = load_orchestration_manifest(
                override_path, base_dir=fixture.root
            )
            self.assertEqual(Path(overridden.sources[0].path), fixture.source_path.resolve())
            self.assertEqual(
                Path(overridden.output_path),
                (fixture.root / "output" / "project.json").resolve(),
            )

            document["sources"][0]["metadata"]["asset_id"] = "repo-snapshot"
            linked = OrchestrationManifest.from_dict(document)
            self.assertEqual(linked.sources[0].metadata["asset_id"], "repo-snapshot")
            metadata_schema = orchestration_manifest_json_schema()["$defs"][
                "source_spec"
            ]["properties"]["metadata"]["properties"]
            self.assertIn("asset_id", metadata_schema)

    def test_source_metadata_rejects_file_uris_and_absolute_local_paths(self) -> None:
        base = {
            "id": "paper-source",
            "kind": "paper",
            "uri": "https://example.invalid/paper",
            "version": "v1",
            "license": "CC-BY-4.0",
            "visibility": "public",
        }
        invalid = (
            {**base, "uri": "file:///C:/private/paper.pdf"},
            {**base, "citation": "/srv/private/paper.pdf"},
            {**base, "version": r"C:\private\paper.pdf"},
            {**base, "version": r"C:private\paper.pdf"},
            {**base, "uri": r"\\server\share\paper.pdf"},
            {**base, "citation": "~/private/paper.pdf"},
        )
        for metadata in invalid:
            with self.subTest(metadata=metadata), self.assertRaisesRegex(
                ValueError, "local filesystem path"
            ):
                SourceSpec("operator-input.txt", metadata)

    def test_path_guard_detects_windows_path_before_json_escaping(self) -> None:
        provider = MockProvider([{}])
        guarded = _PathGuardProvider(provider, (r"C:\private\paper.txt",))
        request = CompletionRequest(
            messages=(
                {
                    "role": "user",
                    "content": r"Read C:\private\paper.txt and summarize it.",
                },
            ),
            output_schema={"type": "object"},
        )
        with self.assertRaisesRegex(
            OrchestrationGateError, "local filesystem path"
        ):
            guarded.complete(request)
        self.assertEqual(provider.requests, [])

    def test_manifest_rejects_missing_and_unknown_fields_at_every_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = EndToEndFixture(Path(directory)).manifest().to_dict()
            missing = copy.deepcopy(document)
            del missing["output_path"]
            with self.assertRaisesRegex(ValueError, "missing=.*output_path"):
                OrchestrationManifest.from_dict(missing)

            unknown = copy.deepcopy(document)
            unknown["unexpected"] = True
            with self.assertRaisesRegex(ValueError, "unknown=.*unexpected"):
                OrchestrationManifest.from_dict(unknown)

            nested = copy.deepcopy(document)
            nested["paper"]["model_decision"] = "eligible"
            with self.assertRaisesRegex(ValueError, "unknown=.*model_decision"):
                OrchestrationManifest.from_dict(nested)

    def test_rejected_paper_stops_before_any_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            rejected = PaperProfile(
                paper_id="rejected",
                title="Rejected paper",
                readable=True,
                provenance_complete=True,
                license_status="known",
                scientific_quality=0.1,
                evidence_coverage=0.95,
                independent_verification_possible=True,
            )
            provider = MockProvider([])
            with self.assertRaisesRegex(OrchestrationGateError, "paper triage"):
                orchestrate_project(fixture.manifest(paper=rejected), provider)
            self.assertEqual(provider.requests, [])

    def test_public_artifact_claims_require_resolved_content_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            provider = MockProvider([])
            with self.assertRaisesRegex(
                OrchestrationGateError, "no resolved public repository asset"
            ):
                orchestrate_project(
                    replace(fixture.manifest(), assets=()),
                    provider,
                )
            self.assertEqual(provider.requests, [])

            unlicensed = AssetSpec(
                "repo-snapshot",
                fixture.asset_path,
                "repository",
                {"visibility": "public"},
            )
            with self.assertRaisesRegex(
                OrchestrationGateError, "not supported by asset metadata"
            ):
                orchestrate_project(
                    replace(fixture.manifest(), assets=(unlicensed,)),
                    provider,
                )
            self.assertEqual(provider.requests, [])

    def test_happy_path_is_path_free_bound_and_replayable_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            responses = fixture.responses()
            provider = MockProvider(responses)
            first = orchestrate_project(fixture.manifest(), provider).to_dict()

            self.assertEqual(first["publication"]["status"], "validated_candidate")
            self.assertEqual(
                first["project_ref"],
                {"kind": "paper2ale.project", "id": "orchestration-e2e"},
            )
            self.assertNotIn("project_path", first)
            self.assertTrue((fixture.root / "project.json").is_file())
            self.assertEqual(first["triage"]["paper"]["decision"], "eligible")
            self.assertEqual(first["triage"]["candidates"][0]["decision"], "eligible")
            self.assertEqual(len(first["candidates"]), 1)
            self.assertEqual(
                first["source_extractions"][0]["extractor"], "utf-8-text/v1"
            )
            self.assertRegex(
                first["source_extractions"][0]["extraction_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertNotIn("local_path", first["source_extractions"][0])
            self.assertEqual(len(provider.requests), 4)
            self.assertEqual(
                provider.requests[-1].output_schema["properties"]["asset_snapshots"]["const"],
                first["asset_snapshots"],
            )
            local_root = str(fixture.root.resolve()).casefold()
            for value in self.json_strings(first):
                self.assertNotIn(local_root, value.casefold())
            for request in provider.requests:
                for value in self.json_strings(request.normalized()):
                    self.assertNotIn(local_root, value.casefold())
                self.assertTrue(request.idempotency_key)

            replay_path = fixture.root / "replay.json"
            replay_path.write_text(
                json.dumps(
                    {
                        request.idempotency_key: response
                        for request, response in zip(provider.requests, responses, strict=True)
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            second = orchestrate_project(
                fixture.manifest("project-replayed.json"),
                ReplayProvider(replay_path),
            ).to_dict()
            self.assertEqual(second["project_sha256"], first["project_sha256"])
            self.assertEqual(
                second["final_provider"]["request_id"],
                first["final_provider"]["request_id"],
            )
            self.assertEqual(
                [item["request_id"] for item in second["stages"]["provider_trace"]],
                [item["request_id"] for item in first["stages"]["provider_trace"]],
            )

    def test_unsupported_declarative_protocol_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            provider = MockProvider(fixture.responses(unsupported_protocol=True))
            with self.assertRaisesRegex(OrchestrationGateError, "unsupported family"):
                orchestrate_project(fixture.manifest(), provider)
            self.assertFalse((fixture.root / "project.json").exists())

    def test_valid_protocol_cannot_be_attached_to_unrelated_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            responses = fixture.responses()
            responses[2]["workflows"][0]["operations"][0][
                "operation_type"
            ] = "transform"
            with self.assertRaisesRegex(
                OrchestrationGateError, "not semantically bound"
            ):
                orchestrate_project(
                    fixture.manifest(),
                    MockProvider(responses),
                )
            self.assertFalse((fixture.root / "project.json").exists())

    def test_asset_origin_requires_cited_materialization_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            responses = fixture.responses()
            artifact = responses[2]["workflows"][0]["artifacts"][0]
            artifact["origin"] = "asset"
            artifact.pop("capability_ref")
            artifact["asset_ref"] = {
                "asset_id": "repo-snapshot",
                "relative_path": "repository.bin",
            }
            with self.assertRaisesRegex(
                ValueError,
                "asset origin without citing evidence",
            ):
                orchestrate_project(
                    fixture.manifest(),
                    MockProvider(responses),
                )
            self.assertFalse((fixture.root / "project.json").exists())

    def test_final_protocol_must_equal_workflow_bound_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            responses = fixture.responses()
            changed = numeric_protocol()
            changed["reference_solver"]["weights"][0][0] = 7.0
            responses[3]["tasks"][0]["protocol"] = changed
            with self.assertRaisesRegex(
                OrchestrationGateError, "not semantically bound"
            ):
                orchestrate_project(fixture.manifest(), MockProvider(responses))

    def test_authored_only_family_cannot_be_selected_by_orchestration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            with self.assertRaisesRegex(ValueError, "candidate compilers"):
                replace(fixture.manifest(), allowed_families=("hnn",))

    def test_release_requires_publication_ready_callback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            provider = MockProvider(fixture.responses())
            with self.assertRaisesRegex(OrchestrationGateError, "publication_ready"):
                orchestrate_project(
                    fixture.manifest(release=True),
                    provider,
                    audit_callback=lambda _path: {"publication_ready": False},
                )
            self.assertFalse((fixture.root / "project.json").exists())

    def test_candidate_mode_never_invokes_publish_callback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            calls: list[Path] = []

            def publish(path: Path) -> dict:
                calls.append(path)
                raise AssertionError("candidate publication must not run")

            receipt = orchestrate_project(
                fixture.manifest(),
                MockProvider(fixture.responses()),
                publish_callback=publish,
            ).to_dict()
            self.assertEqual(calls, [])
            self.assertIsNone(receipt["publication"]["publish"])
            self.assertTrue((fixture.root / "project.json").is_file())

    def test_release_publish_runs_after_commit_on_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            destination = fixture.root / "project.json"
            calls: list[Path] = []

            def publish(path: Path) -> dict:
                calls.append(path)
                self.assertEqual(path, destination)
                self.assertTrue(path.is_file())
                return {"publication_ready": True, "release_id": "release-1"}

            receipt = orchestrate_project(
                fixture.manifest(release=True),
                MockProvider(fixture.responses()),
                publish_callback=publish,
            ).to_dict()
            self.assertEqual(calls, [destination])
            self.assertEqual(receipt["publication"]["status"], "publication_ready")
            self.assertEqual(
                receipt["publication"]["publish"]["release_id"], "release-1"
            )

    def test_postcommit_publish_failure_preserves_project_and_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EndToEndFixture(Path(directory))
            destination = fixture.root / "project.json"

            def publish(path: Path) -> dict:
                self.assertEqual(path, destination)
                self.assertTrue(path.is_file())
                raise RuntimeError("external publisher unavailable")

            with self.assertRaisesRegex(
                OrchestrationGateError, "project was committed.*publish callback failed"
            ):
                orchestrate_project(
                    fixture.manifest(release=True),
                    MockProvider(fixture.responses()),
                    publish_callback=publish,
                )
            self.assertTrue(destination.is_file())


if __name__ == "__main__":
    unittest.main()
