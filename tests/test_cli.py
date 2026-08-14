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
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from paper2ale.cli import _calibration_report, _parser, main  # noqa: E402
from paper2ale import __version__  # noqa: E402
from paper2ale.build_context import BuildContext  # noqa: E402
from paper2ale.difficulty import (  # noqa: E402
    derive_task_calibration_id,
    pin_agent_system,
    resolve_difficulty_v2,
)
from paper2ale.packaging import (  # noqa: E402
    BuildFile,
    write_deterministic_zip_from_files,
    write_manifest,
)
from paper2ale.ids import stable_id  # noqa: E402
from paper2ale.task_families import registered_compiler_identity  # noqa: E402
from paper2ale.verification import verification_catalog_identity  # noqa: E402


class ParserTests(unittest.TestCase):
    def assert_parse_error(self, *arguments: str) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            _parser().parse_args(arguments)
        self.assertEqual(raised.exception.code, 2)

    def test_positive_numeric_arguments_are_enforced(self) -> None:
        invalid_commands = (
            ("build", "project.json", "--jobs", "0"),
            ("build", "project.json", "--jobs", "-1"),
            ("build", "project.json", "--instances", "0"),
            ("audit", "project.json", "--instances", "-1"),
            ("validate", "package.zip", "--max-uncompressed-mb", "0"),
        )
        for arguments in invalid_commands:
            with self.subTest(arguments=arguments):
                self.assert_parse_error(*arguments)

        parsed = _parser().parse_args(
            ("build", "project.json", "--jobs", "2", "--instances", "3")
        )
        self.assertEqual(parsed.jobs, 2)
        self.assertEqual(parsed.instances, 3)

    def test_force_and_no_resume_are_mutually_exclusive(self) -> None:
        self.assert_parse_error(
            "build", "project.json", "--force", "--no-resume"
        )
        self.assert_parse_error(
            "publish", "project.json", "--force", "--no-resume"
        )
        self.assert_parse_error(
            "orchestrate",
            "manifest.json",
            "--replay",
            "replay.json",
            "--force",
            "--no-resume",
        )
        self.assert_parse_error(
            "generate",
            "paper.pdf",
            "--metadata",
            "paper.json",
            "--project-id",
            "project",
            "--out",
            "project.json",
            "--replay",
            "response.jsonl",
            "--build",
            "--publish",
        )

    def test_calibrate_accepts_explicit_project_catalog_pair(self) -> None:
        parsed = _parser().parse_args(
            (
                "calibrate",
                "trials.json",
                "--project",
                "project.lock.json",
                "--catalog",
                "catalog.json",
            )
        )
        self.assertEqual(parsed.project, Path("project.lock.json"))
        self.assertEqual(parsed.catalog, Path("catalog.json"))


class CommandDispatchTests(unittest.TestCase):
    def invoke_build(self, *flags: str) -> tuple[int, dict]:
        result = SimpleNamespace(to_dict=lambda: {"build_id": "test-build"})
        output = io.StringIO()
        with patch("paper2ale.cli.build_project", return_value=result) as build, redirect_stdout(
            output
        ):
            status = main(("build", "project.json", *flags))
        self.assertEqual(json.loads(output.getvalue()), {"build_id": "test-build"})
        return status, build.call_args.kwargs

    def test_default_build_resumes(self) -> None:
        status, arguments = self.invoke_build()
        self.assertEqual(status, 0)
        self.assertTrue(arguments["resume"])
        self.assertFalse(arguments["force"])

    def test_no_resume_refuses_reuse_without_forcing_replacement(self) -> None:
        status, arguments = self.invoke_build("--no-resume")
        self.assertEqual(status, 0)
        self.assertFalse(arguments["resume"])
        self.assertFalse(arguments["force"])

    def test_force_disables_resume_and_requests_quarantine_rebuild(self) -> None:
        status, arguments = self.invoke_build("--force")
        self.assertEqual(status, 0)
        self.assertFalse(arguments["resume"])
        self.assertTrue(arguments["force"])

    def test_publish_uses_fail_closed_release_builder(self) -> None:
        result = SimpleNamespace(
            to_dict=lambda: {
                "build_id": "release-build",
                "publication_ready": True,
            }
        )
        output = io.StringIO()
        with patch(
            "paper2ale.cli.publish_project", return_value=result
        ) as publish, redirect_stdout(output):
            status = main(("publish", "project.json", "--jobs", "2"))
        self.assertEqual(status, 0)
        self.assertTrue(publish.called)
        self.assertEqual(json.loads(output.getvalue())["publication_ready"], True)

    def test_audit_requires_publication_readiness_by_default(self) -> None:
        report = {"preflight_passed": True, "publication_ready": False}
        with patch("paper2ale.cli.audit_project", return_value=report), redirect_stdout(
            io.StringIO()
        ):
            self.assertEqual(main(("audit", "project.json")), 2)
        with patch("paper2ale.cli.audit_project", return_value=report), redirect_stdout(
            io.StringIO()
        ):
            self.assertEqual(
                main(("audit", "project.json", "--preflight-only")), 0
            )

    def test_resolve_difficulty_exposes_separate_axes(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(("resolve-difficulty", "hard"))
        report = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertIn(
            "instance_count", report["difficulty"]["benchmark_sampling"]
        )
        self.assertNotIn("instance_count", report["difficulty"]["challenge"])
        self.assertIn("hidden_case_count", report["difficulty"]["evaluation_power"])
        self.assertEqual(
            report["calibration_validity"]["status"], "uncalibrated"
        )
        self.assertEqual(report["calibration_identity_scope"], "difficulty_only")

        task_build_id = "task-build_" + "c" * 64
        semantic_id = derive_task_calibration_id(
            resolve_difficulty_v2("hard"),
            task_id="task-a",
            task_build_id=task_build_id,
        )
        bound_output = io.StringIO()
        with redirect_stdout(bound_output):
            bound_status = main(
                (
                    "resolve-difficulty",
                    "hard",
                    "--task-id",
                    "task-a",
                    "--task-build-id",
                    task_build_id,
                    "--calibrated-semantic-id",
                    semantic_id,
                )
            )
        bound = json.loads(bound_output.getvalue())
        self.assertEqual(bound_status, 0)
        self.assertEqual(bound["calibration_identity_scope"], "task_build")
        self.assertTrue(bound["calibration_validity"]["valid"])

        with redirect_stderr(io.StringIO()):
            self.assertEqual(
                main(
                    (
                        "resolve-difficulty",
                        "hard",
                        "--calibrated-semantic-id",
                        semantic_id,
                    )
                ),
                2,
            )

    def test_orchestrate_runs_audit_and_returns_a_candidate_receipt(self) -> None:
        manifest = SimpleNamespace(release=False, output_path=Path("project.json"))
        receipt = SimpleNamespace(
            to_dict=lambda: {
                "project_id": "paper-project",
                "publication": {"status": "publication_ready_candidate"},
            }
        )

        def run_orchestration(_manifest, _provider, **kwargs):
            audited = kwargs["audit_callback"](Path("staged-project.json"))
            self.assertTrue(audited["publication_ready"])
            return receipt

        output = io.StringIO()
        with (
            patch("paper2ale.cli.load_orchestration_manifest", return_value=manifest),
            patch("paper2ale.cli.ReplayProvider", return_value=object()),
            patch(
                "paper2ale.cli.audit_project",
                return_value={"publication_ready": True},
            ) as audit,
            patch(
                "paper2ale.cli.orchestrate_project",
                side_effect=run_orchestration,
            ) as orchestrate,
            redirect_stdout(output),
        ):
            status = main(
                (
                    "orchestrate",
                    "manifest.json",
                    "--replay",
                    "replay.json",
                )
            )
        self.assertEqual(status, 0)
        self.assertTrue(orchestrate.called)
        self.assertIsNone(audit.call_args.kwargs["master_seed"])
        self.assertIsNone(audit.call_args.kwargs["instances"])
        self.assertNotIn("build", json.loads(output.getvalue()))

    def test_orchestrate_rejects_seed_and_instance_overrides_before_provider_use(self) -> None:
        for flag, value in (("--seed", "7"), ("--instances", "3")):
            with (
                self.subTest(flag=flag),
                patch("paper2ale.cli.ReplayProvider") as replay,
                patch("paper2ale.cli.orchestrate_project") as orchestrate,
                redirect_stderr(io.StringIO()) as error,
            ):
                status = main(
                    (
                        "orchestrate",
                        "manifest.json",
                        "--replay",
                        "replay.json",
                        flag,
                        value,
                    )
                )
                self.assertEqual(status, 2)
                self.assertIn("pinned defaults are authoritative", error.getvalue())
                replay.assert_not_called()
                orchestrate.assert_not_called()

    def test_orchestrate_release_uses_fail_closed_package_builder(self) -> None:
        manifest = SimpleNamespace(release=True, output_path=Path("project.json"))
        receipt = SimpleNamespace(
            to_dict=lambda: {
                "project_id": "paper-project",
                "publication": {"status": "publication_ready"},
            }
        )
        build_result = SimpleNamespace(
            to_dict=lambda: {"build_id": "release-build", "publication_ready": True}
        )
        output = io.StringIO()
        with (
            patch("paper2ale.cli.load_orchestration_manifest", return_value=manifest),
            patch("paper2ale.cli.ReplayProvider", return_value=object()),
            patch("paper2ale.cli.orchestrate_project", return_value=receipt),
            patch("paper2ale.cli.publish_project", return_value=build_result) as publish,
            redirect_stdout(output),
        ):
            status = main(
                (
                    "orchestrate",
                    "manifest.json",
                    "--replay",
                    "replay.json",
                    "--build-out",
                    "release-dist",
                    "--force",
                )
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(publish.called)
        self.assertIsNone(publish.call_args.kwargs["master_seed"])
        self.assertIsNone(publish.call_args.kwargs["instances"])
        self.assertEqual(payload["build"]["publication_ready"], True)
        self.assertFalse(publish.call_args.kwargs["resume"])
        self.assertTrue(publish.call_args.kwargs["force"])


class ValidateCommandTests(unittest.TestCase):
    def invoke_validate(self, path: Path) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(("validate", str(path)))
        return status, json.loads(output.getvalue())

    def test_validate_checks_embedded_manifest_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "package.zip"
            expected = hashlib.sha256(b"expected").hexdigest()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "MANIFEST.sha256", f"{expected}  ./payload.txt\n"
                )
                archive.writestr("payload.txt", b"actual")

            status, report = self.invoke_validate(archive_path)
            self.assertEqual(status, 2)
            self.assertFalse(report["passed"])
            self.assertIn(
                "checksum_mismatch", {issue["code"] for issue in report["issues"]}
            )

    def test_validate_accepts_matching_embedded_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "package.zip"
            payload = b"actual"
            expected = hashlib.sha256(payload).hexdigest()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "MANIFEST.sha256", f"{expected}  ./payload.txt\n"
                )
                archive.writestr("payload.txt", payload)

            status, report = self.invoke_validate(archive_path)
            self.assertEqual(status, 0)
            self.assertTrue(report["passed"])
            self.assertEqual(report["issues"], [])


class UpstreamCommandTests(unittest.TestCase):
    def test_resolve_assets_emits_path_free_content_locks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "private-repository" / "method.py"
            source.parent.mkdir()
            source.write_text("def method(x):\n    return x\n", encoding="utf-8")
            spec = root / "assets.json"
            spec.write_text(
                json.dumps(
                    [
                        {
                            "asset_id": "code.asset",
                            "path": str(source.parent),
                            "kind": "repository",
                            "metadata": {"license": "test-only"},
                        }
                    ]
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(("resolve-assets", str(spec)))
            report = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertNotIn(str(source.parent), json.dumps(report))
        self.assertEqual(
            report["assets"][0]["files"][0]["relative_path"], "method.py"
        )

    def test_triage_paper_can_fail_closed_on_ineligible_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(
                json.dumps(
                    {
                        "paper_id": "bad-paper",
                        "title": "Unverifiable paper",
                        "readable": True,
                        "provenance_complete": True,
                        "license_status": "known",
                        "scientific_quality": 0.9,
                        "evidence_coverage": 0.9,
                        "independent_verification_possible": False,
                        "workflow_reconstructable": True,
                        "contradictions_resolved": True,
                        "resources_bounded": True,
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(("triage-paper", str(path), "--require-eligible"))
            report = json.loads(output.getvalue())
        self.assertEqual(status, 2)
        self.assertEqual(report["decision"], "no_viable_task")


class CalibrationV1IdentityTests(unittest.TestCase):
    @staticmethod
    def report(rows: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trials.json"
            path.write_text(json.dumps(rows), encoding="utf-8")
            return _calibration_report(path, None)

    @staticmethod
    def trial(trial_id: str, **overrides: object) -> dict:
        row: dict[str, object] = {
            "trial_id": trial_id,
            "task_id": "task-a",
            "level": "hard",
            "passed": True,
            "seed": 0,
            "attempt": 0,
        }
        row.update(overrides)
        return row

    def test_consistent_legacy_identity_is_reported_with_v2_migration_note(self) -> None:
        report = self.report(
            [
                self.trial("trial-a", model="model-a", agent="harness-a"),
                self.trial(
                    "trial-b",
                    model="model-a",
                    agent="harness-a",
                    passed=False,
                    seed=1,
                ),
            ]
        )
        self.assertEqual(
            report["groups"][0]["legacy_identity"],
            {"model": "model-a", "agent": "harness-a"},
        )
        self.assertTrue(report["notes"]["deprecated"])
        self.assertIn("calibration-trials/v2", report["notes"]["migration"])

    def test_partial_or_mixed_legacy_identities_fail_closed(self) -> None:
        invalid_groups = (
            [self.trial("trial-a", model="model-a")],
            [
                self.trial("trial-a", model="model-a", agent="harness-a"),
                self.trial("trial-b", model="model-b", agent="harness-a"),
            ],
            [
                self.trial("trial-a", model="model-a", agent="harness-a"),
                self.trial("trial-b"),
            ],
        )
        for rows in invalid_groups:
            with self.subTest(rows=rows), self.assertRaisesRegex(
                ValueError, "identi"
            ):
                self.report(rows)

    def test_different_groups_may_have_different_consistent_identities(self) -> None:
        report = self.report(
            [
                self.trial("trial-a", model="model-a", agent="harness-a"),
                self.trial(
                    "trial-b",
                    task_id="task-b",
                    model="model-b",
                    agent="harness-b",
                ),
            ]
        )
        identities = {
            group["task_id"]: group["legacy_identity"] for group in report["groups"]
        }
        self.assertEqual(identities["task-a"]["model"], "model-a")
        self.assertEqual(identities["task-b"]["model"], "model-b")

    def test_v1_requires_strict_trial_identity_fields(self) -> None:
        baseline = self.trial("trial-a")
        for field in ("trial_id", "seed", "attempt"):
            row = dict(baseline)
            del row[field]
            with self.subTest(missing=field), self.assertRaisesRegex(
                ValueError, "missing"
            ):
                self.report([row])

        invalid = (
            ("trial_id", "bad/trial", "trial_id"),
            ("trial_id", "CON.json", "trial_id"),
            ("seed", True, "seed"),
            ("seed", -1, "seed"),
            ("attempt", 1.0, "attempt"),
            ("attempt", -1, "attempt"),
        )
        for field, value, message in invalid:
            row = dict(baseline)
            row[field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(
                ValueError, message
            ):
                self.report([row])

    def test_v1_rejects_global_duplicate_trial_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicates trial_id"):
            self.report(
                [
                    self.trial("trial-a"),
                    self.trial("trial-a", task_id="task-b", seed=1),
                ]
            )

    def test_v1_rejects_duplicate_unidentified_run_coordinates(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicates run coordinates"):
            self.report(
                [
                    self.trial("trial-a"),
                    self.trial("trial-b", passed=False),
                ]
            )


class CalibrationV2Tests(unittest.TestCase):
    def pinned(self, model_revision: str) -> dict:
        return pin_agent_system(
            {
                "provider": "example",
                "model_revision": model_revision,
                "harness_commit": "a" * 40,
                "tool_policy": {"shell": True, "browser": False},
                "budgets": {"tokens": 100_000, "timeout_s": 3_600},
                "network_policy": {"enabled": False},
                "evaluation_date": "2026-08-13",
            }
        )

    def hard_project(self) -> dict:
        return json.loads(
            (REPOSITORY_ROOT / "examples" / "hnn_hard" / "project.json").read_text(
                encoding="utf-8"
            )
        )

    def verified_catalog(
        self, root: Path, project: dict
    ) -> tuple[Path, Path, dict[str, str]]:
        build_root = root / "verified-build"
        build_root.mkdir()
        project_lock = build_root / "project.lock.json"
        project_lock.write_text(json.dumps(project, sort_keys=True), encoding="utf-8")
        task_build_ids: dict[str, str] = {}
        catalog_tasks: list[dict] = []
        compatibility_names = {
            "agent": "ALE_Input_Materials",
            "evaluator": "ALE_Reference_Output",
            "author": "ALE_Complete_Package",
        }
        for task in sorted(project["tasks"], key=lambda item: item["id"]):
            task_id = task["id"]
            physical_id = task_id
            task_root = build_root / "tasks" / physical_id
            bundles = task_root / "bundles"
            bundles.mkdir(parents=True)
            task_build_id = "task-build_" + hashlib.sha256(
                ("calibration:" + task_id).encode()
            ).hexdigest()
            task_build_ids[task_id] = task_build_id
            archives: dict[str, dict] = {}
            for profile in ("agent", "evaluator", "author"):
                archive = bundles / f"{physical_id}.{profile}.zip"
                digest = write_deterministic_zip_from_files(
                    [
                        BuildFile(
                            "payload.txt",
                            f"{task_id}:{profile}\n".encode(),
                            "author",
                        )
                    ],
                    archive,
                )
                compatibility = bundles / (
                    f"{physical_id}_{compatibility_names[profile]}.zip"
                )
                compatibility.write_bytes(archive.read_bytes())
                archives[profile] = {
                    "path": archive.relative_to(task_root).as_posix(),
                    "sha256": digest,
                    "size_bytes": archive.stat().st_size,
                    "compatibility_path": compatibility.relative_to(
                        task_root
                    ).as_posix(),
                    "compatibility_sha256": digest,
                    "compatibility_size_bytes": compatibility.stat().st_size,
                }
            qa = {
                "schema_version": "paper2ale.qa/v1",
                "task_id": task_id,
                "task_build_id": task_build_id,
                "preflight_passed": True,
                "publication_ready": True,
            }
            nested = {
                "schema_version": "paper2ale.task-build/v1",
                "task_id": task_id,
                "task_build_id": task_build_id,
                "archives": archives,
                "qa": qa,
            }
            (task_root / "task_build.json").write_text(
                json.dumps(nested, sort_keys=True), encoding="utf-8"
            )
            catalog_tasks.append(
                {
                    "task_id": task_id,
                    "task_build_id": task_build_id,
                    "directory": physical_id,
                    "archives": archives,
                    "file_count": 1,
                    "qa": qa,
                }
            )
        compiler_identity = registered_compiler_identity()
        verification_identity = verification_catalog_identity()
        asset_digest = BuildContext.from_project(project).asset_bundle_digest
        master_seed = project.get("defaults", {}).get("master_seed", 0)
        build_id = stable_id(
            "build",
            {
                "compiler_version": __version__,
                "compiler_registry": compiler_identity,
                "verification": verification_identity,
                "asset_bundle_digest": asset_digest,
                "project": project,
                "master_seed": master_seed,
                "instances_override": None,
                "difficulty_override": None,
                "publication_mode": "release",
            },
        )
        catalog = build_root / "catalog.json"
        catalog.write_text(
            json.dumps(
                {
                    "schema_version": "paper2ale.build/v1",
                    "compiler_version": __version__,
                    "compiler_registry": compiler_identity,
                    "verification": verification_identity,
                    "asset_bundle_digest": asset_digest,
                    "project_id": project["project_id"],
                    "build_id": build_id,
                    "master_seed": master_seed,
                    "instances_override": None,
                    "difficulty_override": None,
                    "publication_mode": "release",
                    "tasks": catalog_tasks,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        write_manifest(build_root)
        return project_lock, catalog, task_build_ids

    def v2_payload(
        self,
        *,
        task_id: str,
        task_build_id: str,
        level: str = "hard",
    ) -> dict:
        system = self.pinned("model-a@1")
        semantic_id = derive_task_calibration_id(
            resolve_difficulty_v2(level),
            task_id=task_id,
            task_build_id=task_build_id,
        )
        return {
            "schema_version": "paper2ale.calibration-trials/v2",
            "agent_systems": [system],
            "trials": [
                {
                    "trial_id": "trial-a",
                    "task_id": task_id,
                    "task_build_id": task_build_id,
                    "level": level,
                    "agent_system_id": system["agent_system_id"],
                    "semantic_id": semantic_id,
                    "passed": True,
                    "score": 1.0,
                    "seed": 0,
                    "attempt": 0,
                }
            ],
        }

    def test_v2_project_requires_verified_catalog(self) -> None:
        project = self.hard_project()
        task_id = project["tasks"][0]["id"]
        task_build_id = "task-build_" + "b" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path = root / "project.json"
            trials_path = root / "trials.json"
            project_path.write_text(json.dumps(project), encoding="utf-8")
            trials_path.write_text(
                json.dumps(
                    self.v2_payload(
                        task_id=task_id, task_build_id=task_build_id
                    )
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "requires the verified build"):
                _calibration_report(trials_path, project_path)

    def test_v2_catalog_binds_exact_project_and_task_build(self) -> None:
        project = self.hard_project()
        task_id = project["tasks"][0]["id"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path, catalog_path, task_build_ids = self.verified_catalog(
                root, project
            )
            trials_path = root / "trials.json"
            trials_path.write_text(
                json.dumps(
                    self.v2_payload(
                        task_id=task_id,
                        task_build_id=task_build_ids[task_id],
                    )
                ),
                encoding="utf-8",
            )
            report = _calibration_report(
                trials_path, project_path, catalog_path
            )
        self.assertTrue(report["notes"]["build_catalog_verified"])
        self.assertEqual(report["build_catalog"]["project_id"], project["project_id"])
        self.assertEqual(
            report["groups"][0]["task_build_id"], task_build_ids[task_id]
        )

    def test_v2_catalog_rejects_fabricated_or_stale_task_build_id(self) -> None:
        project = self.hard_project()
        task_id = project["tasks"][0]["id"]
        fabricated = "task-build_" + "f" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path, catalog_path, _ = self.verified_catalog(root, project)
            trials_path = root / "trials.json"
            trials_path.write_text(
                json.dumps(
                    self.v2_payload(
                        task_id=task_id, task_build_id=fabricated
                    )
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "fabricated, stale, or belongs"
            ):
                _calibration_report(trials_path, project_path, catalog_path)

    def test_v2_catalog_rejects_stale_project_and_tampered_build(self) -> None:
        project = self.hard_project()
        task_id = project["tasks"][0]["id"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path, catalog_path, task_build_ids = self.verified_catalog(
                root, project
            )
            trials_path = root / "trials.json"
            trials_path.write_text(
                json.dumps(
                    self.v2_payload(
                        task_id=task_id,
                        task_build_id=task_build_ids[task_id],
                    )
                ),
                encoding="utf-8",
            )
            stale = json.loads(project_path.read_text(encoding="utf-8"))
            stale["defaults"] = {**stale.get("defaults", {}), "master_seed": 999}
            stale_path = root / "stale-project.json"
            stale_path.write_text(json.dumps(stale), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly match"):
                _calibration_report(trials_path, stale_path, catalog_path)

            catalog_path.write_text(
                catalog_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "stale, tampered"):
                _calibration_report(trials_path, project_path, catalog_path)

    def test_v2_catalog_rejects_unsupported_or_mislabeled_level(self) -> None:
        project = self.hard_project()
        task_id = project["tasks"][0]["id"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_path, catalog_path, task_build_ids = self.verified_catalog(
                root, project
            )
            trials_path = root / "trials.json"
            for level, message in (
                ("easy", "unsupported task/level pair"),
                ("medium", "verified build binds it to 'hard'"),
            ):
                with self.subTest(level=level):
                    trials_path.write_text(
                        json.dumps(
                            self.v2_payload(
                                task_id=task_id,
                                task_build_id=task_build_ids[task_id],
                                level=level,
                            )
                        ),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, message):
                        _calibration_report(
                            trials_path, project_path, catalog_path
                        )

    def test_catalog_is_v2_only_and_requires_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / "catalog.json"
            catalog.write_text("{}", encoding="utf-8")
            v1 = root / "v1.json"
            v1.write_text(
                json.dumps(
                    [
                        {
                            "trial_id": "trial-a",
                            "task_id": "task-a",
                            "level": "hard",
                            "passed": True,
                            "seed": 0,
                            "attempt": 0,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "only.*v2"):
                _calibration_report(v1, None, catalog)

            v2 = root / "v2.json"
            v2.write_text(
                json.dumps(
                    self.v2_payload(
                        task_id="task-a",
                        task_build_id="task-build_" + "b" * 64,
                    )
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "requires --project"):
                _calibration_report(v2, None, catalog)

    def test_v2_calibration_never_pools_agent_systems(self) -> None:
        systems = [self.pinned("model-a@1"), self.pinned("model-b@1")]
        resolved = resolve_difficulty_v2("hard")
        task_build_id = "task-build_" + "b" * 64
        semantic_id = derive_task_calibration_id(
            resolved,
            task_id="task-a",
            task_build_id=task_build_id,
        )
        trials = [
            {
                "trial_id": f"trial-{index}",
                "task_id": "task-a",
                "task_build_id": task_build_id,
                "level": "hard",
                "agent_system_id": system["agent_system_id"],
                "semantic_id": semantic_id,
                "passed": outcome,
                "score": 0.8 if outcome else 0.1,
                "seed": index,
                "attempt": 0,
            }
            for index, (system, outcome) in enumerate(
                zip(systems, (True, False), strict=True)
            )
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trials.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "paper2ale.calibration-trials/v2",
                        "agent_systems": systems,
                        "trials": trials,
                    }
                ),
                encoding="utf-8",
            )
            report = _calibration_report(path, None)
        self.assertEqual(report["schema_version"], "paper2ale.calibration-report/v2")
        self.assertFalse(report["notes"]["systems_pooled"])
        self.assertFalse(report["verified_claim_ready"])
        self.assertEqual(len(report["groups"][0]["agent_systems"]), 2)

    def test_v2_calibration_rejects_stale_semantics(self) -> None:
        system = self.pinned("model-a@1")
        payload = {
            "schema_version": "paper2ale.calibration-trials/v2",
            "agent_systems": [system],
            "trials": [
                {
                    "trial_id": "trial-a",
                    "task_id": "task-a",
                    "task_build_id": "task-build_" + "b" * 64,
                    "level": "hard",
                    "agent_system_id": system["agent_system_id"],
                    "semantic_id": "difficulty_semantic_stale",
                    "passed": True,
                    "score": 1.0,
                    "seed": 0,
                    "attempt": 0,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trials.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "semantic_id is stale"):
                _calibration_report(path, None)

    def test_v2_requires_strict_trial_identity_fields(self) -> None:
        system = self.pinned("model-a@1")
        task_build_id = "task-build_" + "b" * 64
        semantic_id = derive_task_calibration_id(
            resolve_difficulty_v2("hard"),
            task_id="task-a",
            task_build_id=task_build_id,
        )
        baseline = {
            "trial_id": "trial-a",
            "task_id": "task-a",
            "task_build_id": task_build_id,
            "level": "hard",
            "agent_system_id": system["agent_system_id"],
            "semantic_id": semantic_id,
            "passed": True,
            "score": 1.0,
            "seed": 0,
            "attempt": 0,
        }

        def report(row: dict) -> dict:
            payload = {
                "schema_version": "paper2ale.calibration-trials/v2",
                "agent_systems": [system],
                "trials": [row],
            }
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "trials.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                return _calibration_report(path, None)

        for field in ("trial_id", "seed", "attempt"):
            row = dict(baseline)
            del row[field]
            with self.subTest(missing=field), self.assertRaisesRegex(
                ValueError, "missing"
            ):
                report(row)

        for field, value in (
            ("trial_id", "bad/trial"),
            ("seed", True),
            ("attempt", -1),
        ):
            row = dict(baseline)
            row[field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(
                ValueError, field
            ):
                report(row)

    def test_v2_rejects_duplicate_trial_ids_and_run_coordinates(self) -> None:
        system = self.pinned("model-a@1")
        task_build_id = "task-build_" + "b" * 64
        semantic_id = derive_task_calibration_id(
            resolve_difficulty_v2("hard"),
            task_id="task-a",
            task_build_id=task_build_id,
        )

        def trial(trial_id: str, seed: int) -> dict:
            return {
                "trial_id": trial_id,
                "task_id": "task-a",
                "task_build_id": task_build_id,
                "level": "hard",
                "agent_system_id": system["agent_system_id"],
                "semantic_id": semantic_id,
                "passed": True,
                "score": 1.0,
                "seed": seed,
                "attempt": 0,
            }

        def report(rows: list[dict]) -> dict:
            payload = {
                "schema_version": "paper2ale.calibration-trials/v2",
                "agent_systems": [system],
                "trials": rows,
            }
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "trials.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                return _calibration_report(path, None)

        with self.assertRaisesRegex(ValueError, "duplicates trial_id"):
            report([trial("trial-a", 0), trial("trial-a", 1)])
        with self.assertRaisesRegex(ValueError, "duplicates run coordinates"):
            report([trial("trial-a", 0), trial("trial-b", 0)])


if __name__ == "__main__":
    unittest.main()
