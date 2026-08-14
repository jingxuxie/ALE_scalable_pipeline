from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from paper2ale.packaging import BuildFile  # noqa: E402
from paper2ale.pipeline import (  # noqa: E402
    _build_task_in_memory,
    build_project,
    validate_archive,
)


def project_document(task_ids: tuple[str, ...] = ("task-a", "task-b", "task-c")) -> dict:
    tasks = []
    for task_id in task_ids:
        tasks.append(
            {
                "id": task_id,
                "title": f"Generated task {task_id}",
                "mode": "specification_preserving",
                "family": "hnn",
                "summary": "A deterministic test task.",
                "evidence_ids": ["claim.energy"],
                "workflow_nodes": ["workflow.train"],
                "instances": 1,
                "resource_budget": {
                    "cpu_cores": 1,
                    "memory_mb": 128,
                    "wall_time_seconds": 30,
                },
                "output_contract": {"required_files": ["result.json"]},
                "evaluation": {
                    "weights": {"correctness": 1.0},
                    "gates": ["trusted_grader_passes"],
                },
                "tags": ["test"],
            }
        )
    return {
        "schema_version": "paper2ale.project/v1",
        "project_id": "pipeline-test",
        "source_bundle": [
            {
                "id": "source.paper.hnn",
                "kind": "paper",
                "uri": "https://example.test/private-paper-v3",
                "version": "paper-version-v3",
                "license": "test-only",
                "visibility": "author",
                "citation": "Private Paper Citation 2019",
            }
        ],
        "evidence_graph": {
            "records": [
                {
                    "id": "evidence.method",
                    "kind": "method",
                    "statement": "A scalar induces a vector field.",
                    "source_refs": ["source.paper.hnn"],
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
                    "id": "claim.energy",
                    "statement": "Structure improves conservation.",
                    "evidence_ids": ["evidence.method"],
                    "status": "supported",
                    "impact": "medium",
                }
            ],
        },
        "tasks": tasks,
        "defaults": {"master_seed": 17},
    }


def fake_builder(
    project: dict,
    task: dict,
    *,
    master_seed: int,
    instances: int | None = None,
) -> list[BuildFile]:
    task_id = str(task["id"])
    count = task["instances"] if instances is None else instances
    return [
        BuildFile(
            "input/task.txt",
            f"{task_id}|seed={master_seed}|instances={count}\n".encode(),
            "agent",
        ),
        BuildFile("main.py", f'print("{task_id}")\n'.encode(), "agent", True),
        BuildFile("reference/answer.json", b'{"answer":42}\n', "evaluator"),
        BuildFile("reference/grader.py", b"raise SystemExit(0)\n", "evaluator", True),
        BuildFile("author/provenance.json", b'{"trusted":true}\n', "author"),
    ]


class PipelineBuildTests(unittest.TestCase):
    def write_project(self, root: Path, task_ids: tuple[str, ...] = ("task-a",)) -> Path:
        path = root / "project.json"
        path.write_text(
            json.dumps(project_document(task_ids), sort_keys=True), encoding="utf-8"
        )
        return path

    def build(
        self,
        project_path: Path,
        output: Path,
        *,
        jobs: int = 2,
        resume: bool = True,
        force: bool = False,
    ):
        with patch("paper2ale.pipeline._builder_for", return_value=fake_builder):
            return build_project(
                project_path,
                output,
                jobs=jobs,
                resume=resume,
                force=force,
            )

    def test_builds_are_identical_across_worker_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root, ("task-a", "task-b", "task-c"))
            serial = self.build(project_path, root / "serial", jobs=1, resume=False)
            parallel = self.build(project_path, root / "parallel", jobs=4, resume=False)

            self.assertEqual(serial.build_id, parallel.build_id)
            serial_root = Path(serial.root)
            parallel_root = Path(parallel.root)
            serial_files = sorted(
                path.relative_to(serial_root).as_posix()
                for path in serial_root.rglob("*")
                if path.is_file()
            )
            parallel_files = sorted(
                path.relative_to(parallel_root).as_posix()
                for path in parallel_root.rglob("*")
                if path.is_file()
            )
            self.assertEqual(serial_files, parallel_files)
            for relative in serial_files:
                self.assertEqual(
                    (serial_root / relative).read_bytes(),
                    (parallel_root / relative).read_bytes(),
                    relative,
                )

    def test_profiles_permissions_manifests_and_truthful_qa(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            result = self.build(project_path, root / "out", resume=False)
            task = result.tasks[0]
            task_root = Path(result.root) / "tasks" / task.directory
            expected_names = {
                "agent": {"MANIFEST.sha256", "input/task.txt", "main.py"},
                "evaluator": {
                    "MANIFEST.sha256",
                    "input/task.txt",
                    "main.py",
                    "reference/answer.json",
                    "reference/grader.py",
                },
                "author": {
                    "MANIFEST.sha256",
                    "input/task.txt",
                    "main.py",
                    "reference/answer.json",
                    "reference/grader.py",
                    "author/provenance.json",
                    "author/qa_report.json",
                },
            }

            for profile, archive_record in task.archives.items():
                archive_path = task_root / archive_record["path"]
                self.assertEqual(validate_archive(archive_path), ())
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertEqual(set(archive.namelist()), expected_names[profile])
                    self.assertEqual(
                        (archive.getinfo("main.py").external_attr >> 16) & 0o777,
                        0o755,
                    )
                    self.assertEqual(
                        (archive.getinfo("input/task.txt").external_attr >> 16)
                        & 0o777,
                        0o644,
                    )
                    if profile != "agent":
                        self.assertEqual(
                            (archive.getinfo("reference/grader.py").external_attr >> 16)
                            & 0o777,
                            0o755,
                        )
                compatibility = task_root / archive_record["compatibility_path"]
                self.assertEqual(archive_path.read_bytes(), compatibility.read_bytes())
                self.assertEqual(
                    hashlib.sha256(compatibility.read_bytes()).hexdigest(),
                    archive_record["compatibility_sha256"],
                )

            self.assertTrue(task.qa["preflight_passed"])
            self.assertFalse(task.qa["publication_ready"])
            for check in (
                "runtime_reference",
                "mutation_resistance",
                "resource_budget",
                "reproducibility",
            ):
                self.assertEqual(task.qa["checks"][check]["status"], "not_run")

    def test_task_fingerprint_includes_executable_mode(self) -> None:
        project = project_document(("task-a",))
        task = project["tasks"][0]

        def builder_with_mode(executable: bool):
            def builder(project, task, *, master_seed, instances=None):
                return [BuildFile("main.py", b"pass\n", "agent", executable)]

            return builder

        with patch(
            "paper2ale.pipeline._builder_for", return_value=builder_with_mode(False)
        ):
            _, _, non_executable = _build_task_in_memory(project, task, 0, 1)
        with patch(
            "paper2ale.pipeline._builder_for", return_value=builder_with_mode(True)
        ):
            _, _, executable = _build_task_in_memory(project, task, 0, 1)
        self.assertNotEqual(
            non_executable["task_build_id"], executable["task_build_id"]
        )

    def test_source_metadata_leak_fails_preflight(self) -> None:
        project = project_document(("task-a",))
        task = project["tasks"][0]

        def leaking_builder(project, task, *, master_seed, instances=None):
            return [
                BuildFile(
                    "description.md",
                    b"Read https://example.test/private-paper-v3",
                    "agent",
                )
            ]

        with patch("paper2ale.pipeline._builder_for", return_value=leaking_builder):
            with self.assertRaisesRegex(ValueError, "private sentinel"):
                _build_task_in_memory(project, task, 0, 1)

    def test_tampered_or_missing_archive_is_not_resumed_and_force_rebuilds(self) -> None:
        for mutation in ("tamper", "missing"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                project_path = self.write_project(root)
                first = self.build(project_path, root / "out")
                task = first.tasks[0]
                task_root = Path(first.root) / "tasks" / task.directory
                archive = task_root / task.archives["agent"]["path"]
                if mutation == "tamper":
                    archive.write_bytes(archive.read_bytes() + b"tamper")
                else:
                    archive.unlink()

                with self.assertRaises(FileExistsError):
                    self.build(project_path, root / "out")
                rebuilt = self.build(project_path, root / "out", force=True)
                self.assertFalse(rebuilt.resumed)
                self.assertEqual(
                    validate_archive(
                        Path(rebuilt.root)
                        / "tasks"
                        / rebuilt.tasks[0].directory
                        / rebuilt.tasks[0].archives["agent"]["path"]
                    ),
                    (),
                )
                quarantines = list(
                    Path(rebuilt.root).parent.glob(f"{rebuilt.build_id}.quarantined-*")
                )
                self.assertEqual(len(quarantines), 1)

    def test_missing_build_recovers_succeeded_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            first = self.build(project_path, root / "out")
            shutil.rmtree(first.root)
            rebuilt = self.build(project_path, root / "out")
            self.assertFalse(rebuilt.resumed)
            self.assertTrue(Path(rebuilt.root).is_dir())

    def test_compiler_version_has_distinct_build_and_state_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            with patch("paper2ale.pipeline.__version__", "test-v1"):
                first = self.build(project_path, root / "out")
            with patch("paper2ale.pipeline.__version__", "test-v2"):
                second = self.build(project_path, root / "out")
            self.assertNotEqual(first.build_id, second.build_id)
            self.assertTrue(Path(first.root).is_dir())
            self.assertTrue(Path(second.root).is_dir())

    def test_no_resume_refuses_existing_and_force_quarantines_valid_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            first = self.build(project_path, root / "out")
            with self.assertRaises(FileExistsError):
                self.build(project_path, root / "out", resume=False)
            forced = self.build(project_path, root / "out", force=True)
            self.assertFalse(forced.resumed)
            self.assertEqual(first.build_id, forced.build_id)
            self.assertEqual(
                len(
                    list(
                        Path(forced.root).parent.glob(
                            f"{forced.build_id}.quarantined-*"
                        )
                    )
                ),
                1,
            )

    def test_post_write_archive_validation_blocks_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            issue = {
                "code": "manifest_missing",
                "message": "simulated failure",
                "path": "MANIFEST.sha256",
                "severity": "error",
            }
            with patch("paper2ale.pipeline._builder_for", return_value=fake_builder), patch(
                "paper2ale.pipeline.validate_archive", return_value=(issue,)
            ):
                with self.assertRaisesRegex(ValueError, "archive.*failed validation"):
                    build_project(project_path, root / "out", resume=False)


class ArchiveManifestTests(unittest.TestCase):
    def test_embedded_manifest_checksum_and_presence_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stale = root / "stale.zip"
            expected = hashlib.sha256(b"expected").hexdigest()
            with zipfile.ZipFile(stale, "w") as archive:
                archive.writestr("MANIFEST.sha256", f"{expected}  ./payload.txt\n")
                archive.writestr("payload.txt", b"actual")
            self.assertIn(
                "checksum_mismatch", {issue["code"] for issue in validate_archive(stale)}
            )

            missing = root / "missing.zip"
            with zipfile.ZipFile(missing, "w") as archive:
                archive.writestr("payload.txt", b"actual")
            self.assertIn(
                "manifest_missing", {issue["code"] for issue in validate_archive(missing)}
            )


if __name__ == "__main__":
    unittest.main()
