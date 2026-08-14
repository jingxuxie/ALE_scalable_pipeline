from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from paper2ale.cli import _parser, main  # noqa: E402
from paper2ale.generation import (  # noqa: E402
    GenerationProviderError,
    apply_supported_difficulty,
    generate_project,
    load_project_output_schema,
    prepare_generation_request,
)
from paper2ale.providers import (  # noqa: E402
    CommandProvider,
    CompletionResponse,
    MockProvider,
    ReplayProvider,
)
from paper2ale.schema import canonical_json_bytes, load_project  # noqa: E402
from paper2ale.source_ingest import (  # noqa: E402
    EvidenceChunk,
    ingest_source,
    ingest_sources,
    normalize_source_metadata,
)


def source_metadata(*, sha256: str | None = None) -> dict:
    result = {
        "id": "source.paper",
        "kind": "paper",
        "uri": "https://example.test/papers/pinned-v3",
        "version": "version-3",
        "license": "test-only",
        "visibility": "author",
        "citation": "Pinned Paper Citation",
    }
    if sha256 is not None:
        result["sha256"] = sha256
    return result


def generated_project(
    source_ref: dict,
    *,
    project_id: str = "generated-project",
    family: str = "hnn",
    include_tasks: bool = True,
) -> dict:
    tasks = []
    if include_tasks:
        tasks.append(
            {
                "id": "hnn-symplectic-gradient",
                "title": "Generated task",
                "mode": "specification_preserving",
                "family": family,
                "summary": "A bounded generated candidate.",
                "evidence_ids": ["claim.result"],
                "workflow_nodes": ["workflow.train"],
                "instances": 1,
                "resource_budget": {
                    "cpu_cores": 1,
                    "memory_mb": 256,
                    "wall_time_seconds": 60,
                },
                "output_contract": {"required_files": ["result.json"]},
                "evaluation": {
                    "weights": {"correctness": 1.0},
                    "gates": ["trusted_grader_passes"],
                },
                "tags": ["generated"],
            }
        )
    return {
        "schema_version": "paper2ale.project/v1",
        "project_id": project_id,
        "source_bundle": [source_ref],
        "evidence_graph": {
            "records": [
                {
                    "id": "evidence.method",
                    "kind": "method",
                    "statement": "A bounded method is described.",
                    "source_refs": [source_ref["id"]],
                    "confidence": 1.0,
                    "status": "supported",
                }
            ],
            "nodes": [
                {
                    "id": "workflow.train",
                    "kind": "training",
                    "evidence_ids": ["evidence.method"],
                }
            ],
            "edges": [],
            "claims": [
                {
                    "id": "claim.result",
                    "statement": "The workflow has a measurable result.",
                    "evidence_ids": ["evidence.method"],
                    "status": "supported",
                    "impact": "medium",
                }
            ],
        },
        "tasks": tasks,
    }


def generated_compilable_project(
    source_ref: dict,
    *,
    include_provider_binding: bool = False,
) -> tuple[dict, dict]:
    """Return a generic proposal plus its separately trusted local binding."""

    project = json.loads(
        (REPOSITORY_ROOT / "examples" / "generic" / "project.json").read_text(
            encoding="utf-8"
        )
    )
    project["project_id"] = "generated-project"
    project["source_bundle"] = [source_ref]
    for record in project["evidence_graph"]["records"]:
        record["source_refs"] = [source_ref["id"]]
    task = project["tasks"][0]
    binding = task.pop("workflow_binding")
    if include_provider_binding:
        task["workflow_binding"] = binding
    return project, binding


class SourceIngestionTests(unittest.TestCase):
    def test_source_metadata_rejects_unknown_kind(self) -> None:
        for invalid_kind in ("paper ", "data", "unknown"):
            with self.subTest(kind=invalid_kind):
                metadata = source_metadata()
                metadata["kind"] = invalid_kind
                with self.assertRaisesRegex(ValueError, "kind must be one of"):
                    normalize_source_metadata(metadata)

    def test_text_is_hashed_chunked_and_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "paper.txt"
            content = b"line one\nline two\nline three\n"
            path.write_bytes(content)
            source = ingest_source(path, source_metadata(), chunk_chars=18)

            self.assertEqual(
                source.source_ref["sha256"], hashlib.sha256(content).hexdigest()
            )
            self.assertEqual(source.media_type, "text/plain; charset=utf-8")
            self.assertEqual(source.extractor, "utf-8-text/v1")
            self.assertEqual("".join(chunk.text for chunk in source.chunks), content.decode())
            self.assertEqual(
                [chunk.locator for chunk in source.chunks], ["lines:1-2", "lines:3"]
            )

    def test_digest_binary_size_and_pdf_magic_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "paper.txt"
            path.write_bytes(b"actual")
            with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
                ingest_source(path, source_metadata(sha256="0" * 64))
            with self.assertRaisesRegex(ValueError, "exceeds"):
                ingest_source(path, source_metadata(), max_source_bytes=2)

            binary = root / "binary.txt"
            binary.write_bytes(b"text\x00data")
            with self.assertRaisesRegex(ValueError, "NUL"):
                ingest_source(binary, source_metadata())

            fake_pdf = root / "paper.pdf"
            fake_pdf.write_text("not a pdf", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no PDF header"):
                ingest_source(fake_pdf, source_metadata())

    def test_pdf_dispatch_records_extractor_and_page_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "paper.pdf"
            path.write_bytes(b"%PDF-1.7\nminimal test fixture")
            chunks = (EvidenceChunk("source.paper", "page:1", "extracted"),)
            with patch(
                "paper2ale.source_ingest._extract_pdf",
                return_value=(chunks, "fake-pdf/1"),
            ):
                source = ingest_source(path, source_metadata())
            self.assertEqual(source.media_type, "application/pdf")
            self.assertEqual(source.extractor, "fake-pdf/1")
            self.assertEqual(source.chunks, chunks)

    def test_multiple_sources_require_metadata_and_unique_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one --metadata"):
                ingest_sources([first, second], [source_metadata()])
            with self.assertRaisesRegex(ValueError, "duplicate source"):
                ingest_sources(
                    [first, second], [source_metadata(), source_metadata()]
                )


class RequestTests(unittest.TestCase):
    def test_output_schema_is_self_contained(self) -> None:
        schema = load_project_output_schema(REPOSITORY_ROOT / "schemas")
        references: list[str] = []

        def collect(value) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "$ref":
                        references.append(item)
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(schema)
        self.assertTrue(references)
        self.assertTrue(all(reference.startswith("#/") for reference in references))
        self.assertFalse(any(".schema.json" in reference for reference in references))
        task_schema = schema["$defs"]["task_blueprint"]
        self.assertEqual(task_schema["properties"]["family"], {"enum": ["generic"]})
        self.assertFalse(task_schema["properties"]["workflow_binding"])
        self.assertNotIn(
            "workflow_binding",
            {
                required
                for condition in task_schema["allOf"]
                for required in condition.get("then", {}).get("required", [])
            },
        )

    def test_request_binds_project_sources_and_excludes_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private-local-name.txt"
            path.write_text("source evidence", encoding="utf-8")
            sources = (ingest_source(path, source_metadata()),)
            request = prepare_generation_request(
                sources,
                project_id="generated-project",
                schema_dir=REPOSITORY_ROOT / "schemas",
                parameters={"temperature": 0},
                timeout_s=9,
            )
            normalized = request.normalized()
            serialized = json.dumps(normalized)
            self.assertNotIn(str(path.resolve()), serialized)
            self.assertEqual(request.timeout_s, 9.0)
            self.assertEqual(
                request.output_schema["properties"]["project_id"]["const"],
                "generated-project",
            )
            self.assertEqual(
                request.output_schema["properties"]["source_bundle"]["const"],
                [sources[0].source_dict()],
            )
            repeated = prepare_generation_request(
                sources,
                project_id="generated-project",
                schema_dir=REPOSITORY_ROOT / "schemas",
                parameters={"temperature": 0},
                timeout_s=99,
            )
            self.assertEqual(request.idempotency_key, repeated.idempotency_key)
            difficult = prepare_generation_request(
                sources,
                project_id="generated-project",
                schema_dir=REPOSITORY_ROOT / "schemas",
                parameters={"temperature": 0},
                difficulty="hard",
            )
            self.assertNotEqual(request.idempotency_key, difficult.idempotency_key)


class GenerationTests(unittest.TestCase):
    def make_source(self, root: Path):
        path = root / "source.txt"
        path.write_text("bounded evidence\n", encoding="utf-8")
        return path, (ingest_source(path, source_metadata()),)

    def test_valid_project_is_written_canonically_and_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, sources = self.make_source(root)
            proposal, binding = generated_compilable_project(
                sources[0].source_dict()
            )
            project = json.loads(json.dumps(proposal))
            project["tasks"][0]["workflow_binding"] = binding
            output = root / "nested" / "project.json"
            provider = MockProvider([proposal])
            result = generate_project(
                sources,
                provider,
                output,
                project_id="generated-project",
                schema_dir=REPOSITORY_ROOT / "schemas",
                trusted_workflow_bindings={project["tasks"][0]["id"]: binding},
            )

            self.assertEqual(load_project(output), project)
            self.assertEqual(output.read_bytes(), canonical_json_bytes(project) + b"\n")
            self.assertEqual(result.request_id, provider.requests[0].idempotency_key)
            self.assertEqual(result.to_dict()["status"], "validated_candidate")
            self.assertEqual(list(output.parent.glob(".project.json.*.tmp")), [])

    def test_existing_output_is_not_clobbered_on_any_generation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, sources = self.make_source(root)
            output = root / "project.json"
            output.write_bytes(b"existing")
            provider = MockProvider([generated_project(sources[0].source_dict())])
            with self.assertRaises(FileExistsError):
                generate_project(
                    sources,
                    provider,
                    output,
                    project_id="generated-project",
                    schema_dir=REPOSITORY_ROOT / "schemas",
                )
            self.assertEqual(provider.requests, [])
            self.assertEqual(output.read_bytes(), b"existing")

            rewritten, binding = generated_compilable_project(
                sources[0].source_dict()
            )
            rewritten["source_bundle"][0]["version"] = "unrequested-latest"
            with self.assertRaisesRegex(ValueError, "exactly match"):
                generate_project(
                    sources,
                    MockProvider([rewritten]),
                    output,
                    project_id="generated-project",
                    schema_dir=REPOSITORY_ROOT / "schemas",
                    overwrite=True,
                    trusted_workflow_bindings={
                        rewritten["tasks"][0]["id"]: binding
                    },
                )
            self.assertEqual(output.read_bytes(), b"existing")

    def test_project_id_empty_tasks_family_and_finish_reason_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, sources = self.make_source(root)
            different, binding = generated_compilable_project(
                sources[0].source_dict()
            )
            different["project_id"] = "different-project"
            empty = generated_project(
                sources[0].source_dict(), include_tasks=False
            )
            unknown = generated_project(
                sources[0].source_dict(), family="unregistered-family"
            )
            cases = (
                (different, {different["tasks"][0]["id"]: binding}, "project_id"),
                (empty, {}, "at least one task"),
                (unknown, {unknown["tasks"][0]["id"]: {}}, "unsupported task family"),
            )
            for index, (project, bindings, message) in enumerate(cases):
                with self.subTest(message=message), self.assertRaisesRegex(
                    ValueError, message
                ):
                    generate_project(
                        sources,
                        MockProvider([project]),
                        root / f"project-{index}.json",
                        project_id="generated-project",
                        schema_dir=REPOSITORY_ROOT / "schemas",
                        trusted_workflow_bindings=bindings,
                    )

            proposal, binding = generated_compilable_project(
                sources[0].source_dict()
            )

            class LengthProvider:
                def complete(self, request):
                    return CompletionResponse(
                        data=proposal,
                        finish_reason="length",
                    )

            with self.assertRaisesRegex(ValueError, "did not complete"):
                generate_project(
                    sources,
                    LengthProvider(),
                    root / "length.json",
                    project_id="generated-project",
                    schema_dir=REPOSITORY_ROOT / "schemas",
                    trusted_workflow_bindings={
                        proposal["tasks"][0]["id"]: binding
                    },
                )

    def test_untrusted_binding_and_authored_only_family_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, sources = self.make_source(root)
            injected, binding = generated_compilable_project(
                sources[0].source_dict(), include_provider_binding=True
            )
            task_id = injected["tasks"][0]["id"]
            with self.assertRaisesRegex(ValueError, "may not supply workflow_binding"):
                generate_project(
                    sources,
                    MockProvider([injected]),
                    root / "injected.json",
                    project_id="generated-project",
                    schema_dir=REPOSITORY_ROOT / "schemas",
                    trusted_workflow_bindings={task_id: binding},
                )
            self.assertFalse((root / "injected.json").exists())

            fixed = generated_project(sources[0].source_dict())
            with self.assertRaisesRegex(ValueError, "authored-only task family 'hnn'"):
                generate_project(
                    sources,
                    MockProvider([fixed]),
                    root / "fixed.json",
                    project_id="generated-project",
                    schema_dir=REPOSITORY_ROOT / "schemas",
                    trusted_workflow_bindings={fixed["tasks"][0]["id"]: binding},
                )
            self.assertFalse((root / "fixed.json").exists())

            proposal, binding = generated_compilable_project(
                sources[0].source_dict()
            )
            tampered = json.loads(json.dumps(binding))
            tampered["binding_id"] = "binding_" + "0" * 64
            with self.assertRaisesRegex(ValueError, "binding_id"):
                generate_project(
                    sources,
                    MockProvider([proposal]),
                    root / "tampered.json",
                    project_id="generated-project",
                    schema_dir=REPOSITORY_ROOT / "schemas",
                    trusted_workflow_bindings={
                        proposal["tasks"][0]["id"]: tampered
                    },
                )
            self.assertFalse((root / "tampered.json").exists())

    def test_missing_local_binding_fails_before_calling_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, sources = self.make_source(root)
            proposal, _ = generated_compilable_project(sources[0].source_dict())
            provider = MockProvider([proposal])
            with self.assertRaisesRegex(ValueError, "paper2ale orchestrate"):
                generate_project(
                    sources,
                    provider,
                    root / "project.json",
                    project_id="generated-project",
                    schema_dir=REPOSITORY_ROOT / "schemas",
                )
            self.assertEqual(provider.requests, [])

    def test_provider_errors_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, sources = self.make_source(root)

            class SecretProvider:
                def complete(self, request):
                    raise RuntimeError("secret-token-123")

            proposal, binding = generated_compilable_project(
                sources[0].source_dict()
            )
            with self.assertRaises(GenerationProviderError) as raised:
                generate_project(
                    sources,
                    SecretProvider(),
                    root / "project.json",
                    project_id="generated-project",
                    schema_dir=REPOSITORY_ROOT / "schemas",
                    trusted_workflow_bindings={
                        proposal["tasks"][0]["id"]: binding
                    },
                )
            self.assertNotIn("secret-token-123", str(raised.exception))

    def test_difficulty_is_concrete_and_requires_family_support(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, sources = self.make_source(root)
            project = generated_project(sources[0].source_dict())
            with self.assertRaisesRegex(ValueError, "does not support difficulty"):
                apply_supported_difficulty(project, "hard")
            family = SimpleNamespace(
                name="hnn", supported_difficulty_levels=("easy", "hard")
            )
            with patch("paper2ale.generation.task_family", return_value=family):
                transformed = apply_supported_difficulty(project, "hard")
            self.assertEqual(transformed["tasks"][0]["difficulty"]["level"], "hard")
            self.assertEqual(transformed["tasks"][0]["instances"], 5)

    def test_replay_and_command_providers_work_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, sources = self.make_source(root)
            project, binding = generated_compilable_project(
                sources[0].source_dict()
            )
            request = prepare_generation_request(
                sources,
                project_id="generated-project",
                schema_dir=REPOSITORY_ROOT / "schemas",
            )
            replay_path = root / "replay.json"
            replay_path.write_text(
                json.dumps({request.idempotency_key: project}), encoding="utf-8"
            )
            replay_result = generate_project(
                sources,
                ReplayProvider(replay_path),
                root / "replay-project.json",
                project_id="generated-project",
                schema_dir=REPOSITORY_ROOT / "schemas",
                trusted_workflow_bindings={project["tasks"][0]["id"]: binding},
            )
            self.assertEqual(replay_result.finish_reason, "replay")

            envelope = json.dumps({"data": project}, separators=(",", ":"))
            command_result = generate_project(
                sources,
                CommandProvider([sys.executable, "-c", f"print({envelope!r})"]),
                root / "command-project.json",
                project_id="generated-project",
                schema_dir=REPOSITORY_ROOT / "schemas",
                trusted_workflow_bindings={project["tasks"][0]["id"]: binding},
            )
            self.assertEqual(command_result.finish_reason, "stop")


class GenerateCliTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, dict, str]:
        source_path = root / "source.txt"
        source_path.write_text("bounded evidence\n", encoding="utf-8")
        metadata_path = root / "source.json"
        metadata_path.write_text(json.dumps(source_metadata()), encoding="utf-8")
        sources = (ingest_source(source_path, source_metadata()),)
        project = generated_project(sources[0].source_dict())
        request = prepare_generation_request(
            sources,
            project_id="generated-project",
            schema_dir=REPOSITORY_ROOT / "schemas",
        )
        replay_path = root / "replay.json"
        replay_path.write_text(
            json.dumps({request.idempotency_key: project}), encoding="utf-8"
        )
        return source_path, metadata_path, project, str(replay_path)

    def test_cli_generate_fails_closed_and_recommends_orchestrate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, metadata, _, replay = self.fixture(root)
            output = root / "project.json"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                status = main(
                    (
                        "generate",
                        str(source),
                        "--metadata",
                        str(metadata),
                        "--project-id",
                        "generated-project",
                        "--out",
                        str(output),
                        "--replay",
                        replay,
                        "--schema-dir",
                        str(REPOSITORY_ROOT / "schemas"),
                    )
                )
            self.assertEqual(status, 2)
            self.assertIn("paper2ale orchestrate", stderr.getvalue())
            self.assertFalse(output.exists())

            built = SimpleNamespace(to_dict=lambda: {"build_id": "build-test"})
            second_output = root / "second-project.json"
            stderr = io.StringIO()
            with patch("paper2ale.cli.build_project", return_value=built) as build, redirect_stderr(
                stderr
            ):
                status = main(
                    (
                        "generate",
                        str(source),
                        "--metadata",
                        str(metadata),
                        "--project-id",
                        "generated-project",
                        "--out",
                        str(second_output),
                        "--replay",
                        replay,
                        "--schema-dir",
                        str(REPOSITORY_ROOT / "schemas"),
                        "--build",
                        "--build-force",
                    )
                )
            self.assertEqual(status, 2)
            self.assertIn("paper2ale orchestrate", stderr.getvalue())
            build.assert_not_called()
            self.assertFalse(second_output.exists())

    def test_cli_command_argv_and_positive_limits(self) -> None:
        parser = _parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                (
                    "generate",
                    "source.txt",
                    "--metadata",
                    "source.json",
                    "--project-id",
                    "project",
                    "--out",
                    "project.json",
                    "--replay",
                    "replay.json",
                    "--max-source-mb",
                    "0",
                )
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, metadata, project, _ = self.fixture(root)
            output = root / "command.json"
            envelope = json.dumps({"data": project}, separators=(",", ":"))
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                status = main(
                    (
                        "generate",
                        str(source),
                        "--metadata",
                        str(metadata),
                        "--project-id",
                        "generated-project",
                        "--out",
                        str(output),
                        "--command",
                        sys.executable,
                        "--command-arg=-c",
                        "--command-arg",
                        f"print({envelope!r})",
                        "--schema-dir",
                        str(REPOSITORY_ROOT / "schemas"),
                    )
                )
            self.assertEqual(status, 2)
            self.assertIn("paper2ale orchestrate", stderr.getvalue())
            self.assertFalse(output.exists())

    def test_cli_propagates_difficulty_and_calibrates_trials(self) -> None:
        built = SimpleNamespace(to_dict=lambda: {"build_id": "difficulty-build"})
        with patch("paper2ale.cli.build_project", return_value=built) as build, redirect_stdout(
            io.StringIO()
        ):
            status = main(
                (
                    "build",
                    "project.json",
                    "--difficulty",
                    "frontier",
                )
            )
        self.assertEqual(status, 0)
        self.assertEqual(build.call_args.kwargs["difficulty_level"], "frontier")

        with tempfile.TemporaryDirectory() as temporary:
            trials_path = Path(temporary) / "trials.json"
            trials = [
                {
                    "task_id": "generated-task",
                    "level": "hard",
                    "passed": index < 40,
                    "model": "test-model",
                    "agent": "test-agent",
                    "trial_id": f"trial-{index:03d}",
                    "seed": index,
                    "attempt": 0,
                }
                for index in range(100)
            ]
            trials_path.write_text(json.dumps(trials), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = main(("calibrate", str(trials_path)))
            report = json.loads(stdout.getvalue())
            self.assertEqual(status, 0)
            self.assertTrue(report["all_calibrated"])
            self.assertEqual(report["groups"][0]["summary"]["status"], "calibrated")


if __name__ == "__main__":
    unittest.main()
