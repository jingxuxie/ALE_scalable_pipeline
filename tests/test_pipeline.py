from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from paper2ale.packaging import BuildFile  # noqa: E402
from paper2ale.assets import (  # noqa: E402
    AssetCache,
    asset_bundle_digest,
    snapshot_asset,
)
from paper2ale.pipeline import (  # noqa: E402
    _build_task_in_memory,
    audit_project,
    build_project,
    publish_project,
    validate_archive,
)
from paper2ale.state import (  # noqa: E402
    StageLeaseLostError,
    StageOwnershipError,
    StageStateStore,
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


def fake_ale_builder(
    project: dict,
    task: dict,
    *,
    master_seed: int,
    instances: int | None = None,
) -> list[BuildFile]:
    task_id = str(task["id"])
    return [
        BuildFile(
            "task_card.json",
            json.dumps({"taskId": f"research_workflows/{task_id}"}).encode(),
            "agent",
        ),
        BuildFile("main.py", b"print('task')\n", "agent", True),
        BuildFile("description.md", b"# Test task\n", "agent"),
        BuildFile("input/instances/000/input.json", b"{}\n", "agent"),
        BuildFile("software/runner.py", b"print('run')\n", "agent", True),
        BuildFile(
            "reference/instances/000/evaluation.json",
            b'{"expected":42}\n',
            "evaluator",
        ),
        BuildFile(
            "reference/grader.py",
            b"raise SystemExit(0)\n",
            "evaluator",
            True,
        ),
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

    def test_empty_project_fails_audit_and_release_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root, ())
            audit = audit_project(project_path)
            self.assertFalse(audit["preflight_passed"])
            self.assertFalse(audit["publication_ready"])
            self.assertEqual(audit["tasks"], [])
            with self.assertRaisesRegex(ValueError, "tasks must contain at least one"):
                publish_project(project_path, root / "out", jobs=1, resume=False)

    def test_maximum_length_ids_use_short_portable_physical_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = project_document(("t" * 128,))
            project["project_id"] = "p" * 128
            project_path = root / "project.json"
            project_path.write_text(json.dumps(project), encoding="utf-8")
            with patch(
                "paper2ale.pipeline._builder_for",
                return_value=fake_ale_builder,
            ):
                first = build_project(
                    project_path,
                    root / "out",
                    jobs=1,
                    resume=False,
                )
            task = first.tasks[0]
            self.assertRegex(Path(first.root).parent.name, r"^p-[0-9a-f]{24}$")
            self.assertRegex(task.directory, r"^t-[0-9a-f]{24}$")
            self.assertLessEqual(max(len(part) for part in Path(first.root).parts), 64)
            for archive in task.archives.values():
                self.assertEqual(
                    validate_archive(
                        Path(first.root) / "tasks" / task.directory / archive["path"]
                    ),
                    (),
                )
            self.assertIn("ale_local", task.archives)
            with patch(
                "paper2ale.pipeline._builder_for",
                return_value=fake_ale_builder,
            ):
                resumed = build_project(
                    project_path,
                    root / "out",
                    jobs=1,
                    resume=True,
                )
            self.assertTrue(resumed.resumed)
            self.assertEqual(resumed.tasks[0].directory, task.directory)

    def test_deep_ale_layout_is_validated_and_kept_as_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            with patch(
                "paper2ale.pipeline._builder_for",
                return_value=fake_ale_builder,
            ):
                result = build_project(
                    project_path,
                    root / "a-reasonably-long-publication-output-directory",
                    jobs=1,
                    resume=False,
                )
            task_root = Path(result.root) / "tasks" / "task-a"
            deployment_zip = task_root / "bundles" / "task-a.ale-local.zip"
            self.assertTrue(deployment_zip.is_file())
            self.assertFalse((task_root / "deploy").exists())
            self.assertEqual(validate_archive(deployment_zip), ())
            with zipfile.ZipFile(deployment_zip) as archive:
                self.assertIn(
                    "task-data/research_workflows/task-a/000/"
                    "reference/instances/000/evaluation.json",
                    archive.namelist(),
                )

    @unittest.skipUnless(sys.platform == "win32", "Windows path-length semantics")
    def test_long_output_root_fails_before_materialization_with_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            output = root / ("long-output-" + "x" * 140)
            with self.assertRaisesRegex(ValueError, "shorter --out"):
                self.build(project_path, output, jobs=1, resume=False)
            self.assertFalse(any(output.rglob("profiles")))

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
            self.assertTrue(result.preflight_passed)
            self.assertFalse(result.publication_ready)
            self.assertEqual(
                result.to_dict()["status"], "candidate_not_publication_ready"
            )
            for check in (
                "runtime_reference",
                "mutation_resistance",
                "publication_smoke_budget",
                "reproducibility",
            ):
                self.assertEqual(task.qa["checks"][check]["status"], "not_run")

    def test_publish_refuses_a_preflight_only_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            with patch("paper2ale.pipeline._builder_for", return_value=fake_builder):
                with self.assertRaisesRegex(ValueError, "not publication-ready"):
                    publish_project(
                        project_path,
                        root / "release",
                        jobs=1,
                        resume=False,
                    )

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

    def test_fixed_family_cannot_be_relabelled_with_unreviewed_sources(self) -> None:
        project = json.loads(
            (
                REPOSITORY_ROOT / "examples" / "hnn" / "project.json"
            ).read_text(encoding="utf-8")
        )
        project["source_bundle"][0]["version"] = "different-paper"
        with self.assertRaisesRegex(ValueError, "exact reviewed paper/code"):
            _build_task_in_memory(
                project,
                project["tasks"][0],
                int(project["defaults"]["master_seed"]),
                1,
            )

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

    def test_compiler_registry_implementation_changes_build_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            identity_v1 = {
                "schema_version": "paper2ale.compiler-registry/v1",
                "families": [{"family": "hnn", "implementation": "a" * 64}],
            }
            identity_v2 = {
                "schema_version": "paper2ale.compiler-registry/v1",
                "families": [{"family": "hnn", "implementation": "b" * 64}],
            }
            with patch(
                "paper2ale.pipeline._builder_for", return_value=fake_builder
            ), patch(
                "paper2ale.pipeline.registered_compiler_identity",
                return_value=identity_v1,
            ):
                first = build_project(
                    project_path, root / "out", jobs=1, resume=False
                )
            with patch(
                "paper2ale.pipeline._builder_for", return_value=fake_builder
            ), patch(
                "paper2ale.pipeline.registered_compiler_identity",
                return_value=identity_v2,
            ):
                second = build_project(
                    project_path, root / "out", jobs=1, resume=False
                )
            self.assertNotEqual(first.build_id, second.build_id)

    def test_snapshot_bound_asset_cache_reaches_trusted_builder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "dataset.json"
            source.write_bytes(b'{"paper_value":17}\n')
            cache = AssetCache(root / "cache")
            snapshot = snapshot_asset(
                source,
                asset_id="paper-dataset",
                kind="dataset",
                cache=cache,
            )
            project = project_document(("task-a",))
            project["asset_snapshots"] = [snapshot.to_dict()]
            project_path = root / "project.json"
            project_path.write_text(json.dumps(project), encoding="utf-8")

            def asset_builder(
                project,
                task,
                *,
                master_seed,
                instances=None,
                build_context,
            ):
                data = build_context.read_asset(
                    "paper-dataset", "dataset.json"
                )
                return [BuildFile("input/dataset.json", data, "agent")]

            with patch(
                "paper2ale.pipeline._builder_for", return_value=asset_builder
            ):
                result = build_project(
                    project_path,
                    root / "out",
                    jobs=1,
                    resume=False,
                    asset_cache=cache,
                )
            catalog = json.loads(
                (Path(result.root) / "catalog.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                catalog["asset_bundle_digest"],
                asset_bundle_digest((snapshot,)),
            )
            self.assertRegex(catalog["asset_bundle_digest"], r"^[0-9a-f]{64}$")
            agent_root = (
                Path(result.root)
                / "tasks"
                / result.tasks[0].directory
                / "profiles"
                / "agent"
            )
            self.assertEqual(
                (agent_root / "input" / "dataset.json").read_bytes(),
                b'{"paper_value":17}\n',
            )
            with patch(
                "paper2ale.pipeline._builder_for", return_value=asset_builder
            ):
                with self.assertRaisesRegex(RuntimeError, "no AssetCache"):
                    build_project(
                        project_path,
                        root / "without-cache",
                        jobs=1,
                        resume=False,
                    )

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

    def test_long_build_heartbeat_renews_before_worker_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            renewed = threading.Event()
            renewals: list[tuple[str, str]] = []
            original_renew = StageStateStore.renew

            def observed_renew(store, stage_key, owner, *, lease_s=300.0):
                result = original_renew(
                    store, stage_key, owner, lease_s=lease_s
                )
                renewals.append((stage_key, owner))
                renewed.set()
                return result

            def waits_for_heartbeat(project, task, *, master_seed, instances=None):
                if not renewed.wait(1.0):
                    raise AssertionError("worker completed without a lease renewal")
                return fake_builder(
                    project,
                    task,
                    master_seed=master_seed,
                    instances=instances,
                )

            with patch(
                "paper2ale.pipeline._builder_for",
                return_value=waits_for_heartbeat,
            ), patch(
                "paper2ale.pipeline._BUILD_HEARTBEAT_INTERVAL_SECONDS",
                0.01,
            ), patch(
                "paper2ale.pipeline._BUILD_HEARTBEAT_POLL_SECONDS",
                0.005,
            ), patch.object(
                StageStateStore,
                "renew",
                new=observed_renew,
            ):
                result = build_project(
                    project_path,
                    root / "out",
                    jobs=1,
                    resume=False,
                )

            self.assertTrue(Path(result.root).is_dir())
            # At least one background pulse plus the synchronous pre-commit
            # ownership check must have occurred under the same owner.
            self.assertGreaterEqual(len(renewals), 2)
            self.assertEqual(len({owner for _, owner in renewals}), 1)

    def test_lease_loss_aborts_without_waiting_and_fail_does_not_mask_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = self.write_project(root)
            worker_started = threading.Event()
            release_worker = threading.Event()
            renewal_attempted = threading.Event()
            build_finished = threading.Event()
            outcome: list[BaseException] = []

            def blocking_builder(project, task, *, master_seed, instances=None):
                worker_started.set()
                release_worker.wait(2.0)
                return fake_builder(
                    project,
                    task,
                    master_seed=master_seed,
                    instances=instances,
                )

            def lose_lease(store, stage_key, owner, *, lease_s=300.0):
                renewal_attempted.set()
                raise StageOwnershipError("simulated lease theft")

            def cannot_record_failure(store, stage_key, owner, error):
                raise StageOwnershipError("cannot fail stolen stage")

            def run_build() -> None:
                try:
                    build_project(
                        project_path,
                        root / "out",
                        jobs=1,
                        resume=False,
                    )
                except BaseException as error:
                    outcome.append(error)
                finally:
                    build_finished.set()

            with patch(
                "paper2ale.pipeline._builder_for",
                return_value=blocking_builder,
            ), patch(
                "paper2ale.pipeline._BUILD_HEARTBEAT_INTERVAL_SECONDS",
                0.01,
            ), patch(
                "paper2ale.pipeline._BUILD_HEARTBEAT_POLL_SECONDS",
                0.005,
            ), patch.object(
                StageStateStore,
                "renew",
                new=lose_lease,
            ), patch.object(
                StageStateStore,
                "fail",
                new=cannot_record_failure,
            ):
                thread = threading.Thread(target=run_build, daemon=True)
                thread.start()
                self.assertTrue(worker_started.wait(1.0))
                self.assertTrue(renewal_attempted.wait(1.0))
                # The build must unwind while its worker is still blocked.
                self.assertTrue(build_finished.wait(1.0))
                self.assertFalse(release_worker.is_set())
                release_worker.set()
                thread.join(1.0)

            self.assertFalse(thread.is_alive())
            self.assertEqual(len(outcome), 1)
            self.assertIsInstance(outcome[0], StageLeaseLostError)
            self.assertIn("simulated lease theft", str(outcome[0]))
            self.assertTrue(
                any(
                    "cannot fail stolen stage" in note
                    for note in getattr(outcome[0], "__notes__", ())
                )
            )
            self.assertEqual(list((root / "out").rglob("catalog.json")), [])


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
