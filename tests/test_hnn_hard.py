from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.difficulty import (  # noqa: E402
    resolve_task_difficulty,
    verify_consumption_manifest,
)
from paper2ale.packaging import (  # noqa: E402
    ale_local_deployment_files,
    projection_files,
    write_projection,
)
from paper2ale.schema import validate_project  # noqa: E402
from paper2ale.task_families.hnn_hard import (  # noqa: E402
    PAPER_PDF_SHA256,
    REPO_REVISION,
    SUPPORTED_TASKS,
    build_task_files,
)


class HNNHardTaskFamilyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project = json.loads(
            (ROOT / "examples" / "hnn_hard" / "project.json").read_text(
                encoding="utf-8"
            )
        )
        cls.seed = int(cls.project["defaults"]["master_seed"])
        cls.tasks = {task["id"]: task for task in cls.project["tasks"]}
        cls.builds = {
            task_id: build_task_files(cls.project, task, master_seed=cls.seed)
            for task_id, task in cls.tasks.items()
        }

    @staticmethod
    def by_path(files) -> dict[str, object]:
        return {item.path: item for item in files}

    @staticmethod
    def project_at_level(project: dict, level: str) -> dict:
        changed = deepcopy(project)
        for task in changed["tasks"]:
            task["difficulty"]["level"] = level
        return changed

    def test_fixture_schema_source_locks_and_task_set(self) -> None:
        self.assertEqual(validate_project(self.project), [])
        self.assertEqual(tuple(self.tasks), SUPPORTED_TASKS)
        self.assertTrue(all(task["family"] == "hnn_hard" for task in self.tasks.values()))
        self.assertTrue(all(task["instances"] == 2 for task in self.tasks.values()))
        sources = {source["id"]: source for source in self.project["source_bundle"]}
        paper = sources["src-hnn-paper-v3"]
        code = sources["src-hnn-code-master"]
        self.assertEqual(paper["sha256"], PAPER_PDF_SHA256)
        self.assertEqual(code["version"], REPO_REVISION)
        for source in sources.values():
            self.assertTrue(source["citation"])
            self.assertEqual(source["retrieved_at"], "2026-08-13")

    def test_builds_are_sorted_byte_deterministic_and_seed_sensitive(self) -> None:
        for task_id, task in self.tasks.items():
            with self.subTest(task_id=task_id):
                first = self.builds[task_id]
                repeated = build_task_files(self.project, task, master_seed=self.seed)
                self.assertEqual(first, repeated)
                paths = [item.path for item in first]
                self.assertEqual(paths, sorted(paths))
                self.assertEqual(len(paths), len(set(path.casefold() for path in paths)))
                other = build_task_files(self.project, task, master_seed=self.seed + 1)
                first_inputs = [item.data for item in first if item.path.startswith("input/")]
                other_inputs = [item.data for item in other if item.path.startswith("input/")]
                self.assertNotEqual(first_inputs, other_inputs)

    def test_agent_projection_is_paper_blind_and_truth_is_private(self) -> None:
        forbidden = (
            b"hamiltonian neural networks",
            b"1906.01563",
            b"arxiv",
            b"github.com/greydanus",
            b"greydanus",
            b"neurips",
            b"https://",
            b"http://",
        )
        for task_id, files in self.builds.items():
            with self.subTest(task_id=task_id):
                agent = projection_files(files, "agent")
                self.assertTrue(agent)
                self.assertTrue(all(item.visibility == "agent" for item in agent))
                self.assertFalse(
                    any(
                        item.path.startswith(("reference/", "example/", "author/"))
                        for item in agent
                    )
                )
                payload = b"\n".join(item.data.lower() for item in agent)
                for token in forbidden:
                    self.assertNotIn(token, payload)
                self.assertIn("reference/grader.py", self.by_path(files))
                self.assertIn("author/difficulty_manifest.json", self.by_path(files))
                self.assertIn("author/difficulty_parameters.json", self.by_path(files))

    def test_current_ale_assets_and_safe_contracts_are_complete(self) -> None:
        output_formats = {
            "hnn-hard-coupled-identification": "coupled-periodic-hamiltonian-v1",
            "hnn-hard-variable-nbody": "nbody-query-results-v1",
            "hnn-hard-canonical-recovery": "latent-canonical-hamiltonian-v1",
        }
        for task_id, files in self.builds.items():
            with self.subTest(task_id=task_id):
                paths = self.by_path(files)
                for required in (
                    "description.md",
                    "task_card.json",
                    "main.py",
                    "reference/grader.py",
                    "author/provenance.json",
                    "author/evidence_graph.json",
                    "author/qa_notes.md",
                ):
                    self.assertIn(required, paths)
                card = json.loads(paths["task_card.json"].data)
                self.assertEqual(card["taskId"], f"physical_sciences/{task_id}")
                self.assertEqual(card["category"], "physical_sciences")
                self.assertEqual(card["paper2ale"]["family"], "hnn_hard")
                self.assertEqual(card["paper2ale"]["difficulty"], "hard")
                self.assertEqual(
                    card["paper2ale"]["submission"]["format"], output_formats[task_id]
                )
                self.assertFalse(card["paper2ale"]["submission"]["executable"])
                self.assertEqual(
                    set(card["vm"]),
                    {"snapshot", "vcpus", "memory_gb", "disk_gb", "timeout_s"},
                )
                main = paths["main.py"].data.decode("utf-8")
                for fragment in (
                    "import cua_bench as cb",
                    "from tasks.linux_runtime import LinuxTaskConfig",
                    "class TaskConfig(LinuxTaskConfig)",
                    '@cb.tasks_config(split="train")',
                    '@cb.setup_task(split="train")',
                    '@cb.evaluate_task(split="train")',
                    "cfg.input_dir",
                    "cfg.reference_dir",
                    "cfg.remote_output_dir",
                    'metadata["grader_path"]',
                ):
                    self.assertIn(fragment, main)
                for instance_id in ("000", "001"):
                    self.assertIn(repr(instance_id), main)
                    self.assertTrue(
                        any(
                            path.startswith(f"input/instances/{instance_id}/")
                            for path in paths
                        )
                    )
                    self.assertTrue(
                        any(
                            path.startswith(f"reference/instances/{instance_id}/")
                            for path in paths
                        )
                    )
                    self.assertIn(
                        f"example/instances/{instance_id}/golden.json", paths
                    )
                    self.assertIn(
                        f"example/instances/{instance_id}/mutant.json", paths
                    )

    def test_every_generated_python_file_compiles(self) -> None:
        for task_id, files in self.builds.items():
            for item in files:
                if item.path.endswith(".py"):
                    with self.subTest(task_id=task_id, path=item.path):
                        compile(item.data.decode("utf-8"), item.path, "exec")

    def test_standard_manifest_and_concrete_parameters_match_resolution(self) -> None:
        for task_id, task in self.tasks.items():
            with self.subTest(task_id=task_id):
                paths = self.by_path(self.builds[task_id])
                manifest = json.loads(paths["author/difficulty_manifest.json"].data)
                parameters = json.loads(paths["author/difficulty_parameters.json"].data)
                resolved = resolve_task_difficulty(self.project, task)
                self.assertIsNotNone(resolved)
                self.assertTrue(verify_consumption_manifest(resolved, manifest))
                self.assertEqual(
                    manifest["schema_version"], "paper2ale.difficulty-consumption/v1"
                )
                self.assertEqual(parameters["resolution_id"], manifest["resolution_id"])
                self.assertEqual(parameters["instance_count"], 2)
                self.assertEqual(len(parameters["instance_seeds"]), 2)
                self.assertTrue(parameters["generator_parameters"])
                self.assertTrue(parameters["grader_parameters"])
                self.assertEqual(len(parameters["registered_mutants"]), 1)

    def test_medium_hard_frontier_change_real_generator_and_grader_knobs(self) -> None:
        projects = {
            level: self.project_at_level(self.project, level)
            for level in ("medium", "hard", "frontier")
        }
        for task_id in SUPPORTED_TASKS:
            builds = {}
            for level, project in projects.items():
                task = next(item for item in project["tasks"] if item["id"] == task_id)
                builds[level] = self.by_path(
                    build_task_files(project, task, master_seed=self.seed)
                )
                card = json.loads(builds[level]["task_card.json"].data)
                manifest = json.loads(
                    builds[level]["author/difficulty_manifest.json"].data
                )
                self.assertEqual(card["paper2ale"]["difficulty"], level)
                self.assertEqual(manifest["level"], level)
            with self.subTest(task_id=task_id):
                self.assertEqual(
                    len(
                        {
                            builds[level]["author/difficulty_parameters.json"].data
                            for level in builds
                        }
                    ),
                    3,
                )
                self.assertEqual(
                    len(
                        {
                            builds[level]["input/instances/000/" + {
                                "hnn-hard-coupled-identification": "data.json",
                                "hnn-hard-variable-nbody": "problems.json",
                                "hnn-hard-canonical-recovery": "observations.json",
                            }[task_id]].data
                            for level in builds
                        }
                    ),
                    3,
                )
                self.assertEqual(
                    len(
                        {
                            next(
                                item.data
                                for path, item in builds[level].items()
                                if path.startswith("reference/instances/000/")
                            )
                            for level in builds
                        }
                    ),
                    3,
                )

    def test_variable_nbody_queries_have_no_agent_visible_answers(self) -> None:
        files = self.by_path(self.builds["hnn-hard-variable-nbody"])
        for instance_id in ("000", "001"):
            public = json.loads(
                files[f"input/instances/{instance_id}/problems.json"].data
            )
            self.assertGreaterEqual(len({len(item["masses"]) for item in public["queries"]}), 3)
            self.assertTrue(all("expected" not in query for query in public["queries"]))
            self.assertTrue(all("hamiltonian" not in query for query in public["queries"]))
            self.assertTrue(all("field" not in query for query in public["queries"]))
            policy = files[f"reference/instances/{instance_id}/policy.json"]
            self.assertEqual(policy.visibility, "evaluator")

    def test_golden_artifacts_pass_and_registered_mutants_fail(self) -> None:
        for task_id, files in self.builds.items():
            with self.subTest(task_id=task_id):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    write_projection(files, root, "evaluator")
                    grader = root / "reference" / "grader.py"
                    for instance_id in ("000", "001"):
                        golden = root / "example" / "instances" / instance_id / "golden.json"
                        mutant = root / "example" / "instances" / instance_id / "mutant.json"
                        passed = subprocess.run(
                            [
                                sys.executable,
                                str(grader),
                                "--submission",
                                str(golden),
                                "--instance",
                                instance_id,
                            ],
                            cwd=root,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=30,
                        )
                        self.assertEqual(
                            passed.returncode, 0, passed.stdout + passed.stderr
                        )
                        self.assertTrue(json.loads(passed.stdout)["passed"])
                        rejected = subprocess.run(
                            [
                                sys.executable,
                                str(grader),
                                "--submission",
                                str(mutant),
                                "--instance",
                                instance_id,
                            ],
                            cwd=root,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=30,
                        )
                        self.assertNotEqual(
                            rejected.returncode, 0, rejected.stdout + rejected.stderr
                        )
                        self.assertFalse(json.loads(rejected.stdout)["passed"])

    def test_local_ale_deployment_is_variant_scoped(self) -> None:
        for task_id, files in self.builds.items():
            with self.subTest(task_id=task_id):
                deployed = ale_local_deployment_files(
                    files, expected_task_id=task_id
                )
                paths = {item.path for item in deployed}
                self.assertIn(
                    f"tasks/physical_sciences/{task_id}/main.py", paths
                )
                for instance_id in ("000", "001"):
                    root = (
                        f"task-data/physical_sciences/{task_id}/{instance_id}"
                    )
                    self.assertTrue(
                        any(path.startswith(f"{root}/input/") for path in paths)
                    )
                    self.assertIn(f"{root}/reference/grader.py", paths)
                    self.assertTrue(
                        any(
                            path.startswith(
                                f"{root}/reference/instances/{instance_id}/"
                            )
                            for path in paths
                        )
                    )

    def test_missing_or_invalid_difficulty_fails_closed(self) -> None:
        task = deepcopy(next(iter(self.tasks.values())))
        task.pop("difficulty")
        project = deepcopy(self.project)
        project["tasks"] = [task]
        with self.assertRaisesRegex(ValueError, "explicit task difficulty"):
            build_task_files(project, task, master_seed=self.seed)

        task["difficulty"] = {
            "profile_id": "core",
            "profile_version": 1,
            "level": "impossible",
        }
        project["tasks"] = [task]
        with self.assertRaisesRegex(ValueError, "invalid task difficulty"):
            build_task_files(project, task, master_seed=self.seed)


if __name__ == "__main__":
    unittest.main()
