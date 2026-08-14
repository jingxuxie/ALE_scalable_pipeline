from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.packaging import (  # noqa: E402
    ale_local_deployment_files,
    projection_files,
    write_projection,
)
from paper2ale.schema import validate_project  # noqa: E402
from paper2ale.task_families import TASK_FAMILIES  # noqa: E402
from paper2ale.task_families.hnn import (  # noqa: E402
    ALE_REPO_REVISION,
    OFFICIAL_REPO_REVISION,
    PAPER_PDF_SHA256,
    SUPPORTED_TASKS,
    build_task_files,
)


class HNNTaskFamilyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project = json.loads(
            (ROOT / "examples" / "hnn" / "project.json").read_text(encoding="utf-8")
        )
        cls.master_seed = int(cls.project["defaults"]["master_seed"])
        cls.tasks = {task["id"]: task for task in cls.project["tasks"]}
        cls.builds = {
            task_id: build_task_files(cls.project, task, master_seed=cls.master_seed)
            for task_id, task in cls.tasks.items()
        }

    @staticmethod
    def _by_path(files) -> dict[str, object]:
        return {item.path: item for item in files}

    def test_fixture_is_valid_and_registers_exactly_three_tasks(self) -> None:
        self.assertEqual(validate_project(self.project), [])
        self.assertEqual(tuple(self.tasks), SUPPORTED_TASKS)
        self.assertEqual(set(self.tasks), set(SUPPORTED_TASKS))
        self.assertIs(TASK_FAMILIES["hnn"], build_task_files)
        self.assertTrue(all(task["instances"] == 3 for task in self.tasks.values()))

    def test_builds_are_byte_deterministic_and_seed_sensitive(self) -> None:
        for task_id, task in self.tasks.items():
            with self.subTest(task_id=task_id):
                repeated = build_task_files(
                    self.project,
                    task,
                    master_seed=self.master_seed,
                )
                self.assertEqual(self.builds[task_id], repeated)
                paths = [item.path for item in repeated]
                self.assertEqual(paths, sorted(paths))
                self.assertEqual(len(paths), len(set(paths)))

                first = build_task_files(self.project, task, master_seed=7, instances=1)
                second = build_task_files(self.project, task, master_seed=8, instances=1)
                first_input = next(item.data for item in first if item.path.startswith("input/"))
                second_input = next(item.data for item in second if item.path.startswith("input/"))
                self.assertNotEqual(first_input, second_input)

    def test_agent_projection_is_paper_blind(self) -> None:
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
                self.assertFalse(any(item.path.startswith(("reference/", "example/", "author/")) for item in agent))
                payload = b"\n".join(item.data.lower() for item in agent)
                for token in forbidden:
                    self.assertNotIn(token, payload)

    def test_task_cards_and_current_ale_modules_are_present(self) -> None:
        required_card_keys = {"taskId", "title", "summary", "category", "vm"}
        required_vm_keys = {"snapshot", "vcpus", "memory_gb", "disk_gb", "timeout_s"}
        required_main_fragments = (
            "import cua_bench as cb",
            "from tasks.linux_runtime import LinuxTaskConfig",
            "@dataclass",
            "class TaskConfig(LinuxTaskConfig)",
            "def task_description(self)",
            "cfg.input_dir",
            "cfg.task_dir",
            "cfg.remote_output_dir",
            '@cb.tasks_config(split="train")',
            '@cb.setup_task(split="train")',
            '@cb.evaluate_task(split="train")',
            "cfg.reference_dir",
            'metadata["grader_path"]',
            "session.run_command",
        )
        for task_id, files in self.builds.items():
            with self.subTest(task_id=task_id):
                paths = self._by_path(files)
                self.assertIn("main.py", paths)
                self.assertIn("software/public_check.py", paths)
                card = json.loads(paths["task_card.json"].data)
                self.assertTrue(required_card_keys <= set(card))
                self.assertEqual(card["taskId"], f"physical_sciences/{task_id}")
                self.assertEqual(card["category"], "physical_sciences")
                self.assertTrue(required_vm_keys <= set(card["vm"]))
                self.assertEqual(card["vm"]["snapshot"], "cpu-free-ubuntu")
                self.assertEqual(card["paper2ale"]["instanceCount"], 3)
                main = paths["main.py"].data.decode("utf-8")
                for fragment in required_main_fragments:
                    self.assertIn(fragment, main)
                for instance_id in ("000", "001", "002"):
                    self.assertIn(repr(instance_id), main)

    def test_local_ale_deployment_uses_canonical_variant_layout(self) -> None:
        for task_id, files in self.builds.items():
            with self.subTest(task_id=task_id):
                deployed = ale_local_deployment_files(
                    files,
                    expected_task_id=task_id,
                )
                paths = {item.path for item in deployed}
                source_root = f"tasks/physical_sciences/{task_id}"
                self.assertIn(f"{source_root}/main.py", paths)
                self.assertIn(f"{source_root}/task_card.json", paths)
                self.assertIn("DEPLOYMENT.json", paths)
                for instance_id in ("000", "001", "002"):
                    data_root = (
                        f"task-data/physical_sciences/{task_id}/{instance_id}"
                    )
                    self.assertTrue(
                        any(path.startswith(f"{data_root}/input/") for path in paths)
                    )
                    self.assertIn(f"{data_root}/software/public_check.py", paths)
                    self.assertIn(f"{data_root}/reference/grader.py", paths)
                    own_reference = f"{data_root}/reference/instances/{instance_id}/"
                    self.assertTrue(any(path.startswith(own_reference) for path in paths))
                    for other in {"000", "001", "002"} - {instance_id}:
                        self.assertFalse(
                            any(
                                path.startswith(
                                    f"{data_root}/reference/instances/{other}/"
                                )
                                for path in paths
                            )
                        )

    def test_public_runner_works_from_canonical_ale_variant_layout(self) -> None:
        files = self.builds["hnn-symplectic-gradient"]
        deployed = ale_local_deployment_files(
            files,
            expected_task_id="hnn-symplectic-gradient",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_projection(deployed, root, "author")
            variant_root = (
                root
                / "task-data"
                / "physical_sciences"
                / "hnn-symplectic-gradient"
                / "000"
            )
            reference_solution = self._by_path(files)["example/reference_solution.py"]
            (variant_root / "software" / "solution.py").write_bytes(
                reference_solution.data
            )
            output = root / "public-output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(variant_root / "software" / "public_check.py"),
                    "--instance",
                    "000",
                    "--output",
                    str(output),
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertTrue(
                json.loads((output / "public_check.json").read_text(encoding="utf-8"))[
                    "passed"
                ]
            )

    def test_every_generated_python_file_is_syntactically_valid(self) -> None:
        for task_id, files in self.builds.items():
            for item in files:
                if item.path.endswith(".py"):
                    with self.subTest(task_id=task_id, path=item.path):
                        compile(item.data.decode("utf-8"), item.path, "exec")

    def test_generated_ale_load_hook_materializes_all_variant_metadata(self) -> None:
        class FakeTask:
            def __init__(self, *, description, metadata, computer):
                self.description = description
                self.metadata = metadata
                self.computer = computer

        class FakeLinuxTaskConfig:
            REMOTE_ROOT_DIR = "/media/user/data/agenthle"
            REMOTE_OUTPUT_DIR = "output"
            DOMAIN_NAME = ""
            TASK_NAME = ""
            VARIANT_NAME = ""
            OS_TYPE = "linux"

            @property
            def task_dir(self):
                return (
                    f"{self.REMOTE_ROOT_DIR}/{self.DOMAIN_NAME}/"
                    f"{self.TASK_NAME}/{self.VARIANT_NAME}"
                )

            @property
            def input_dir(self):
                return f"{self.task_dir}/input"

            @property
            def software_dir(self):
                return f"{self.task_dir}/software"

            @property
            def reference_dir(self):
                return f"{self.task_dir}/reference"

            @property
            def remote_output_dir(self):
                return f"{self.task_dir}/{self.REMOTE_OUTPUT_DIR}"

            def to_metadata(self):
                return {
                    "task_dir": self.task_dir,
                    "input_dir": self.input_dir,
                    "software_dir": self.software_dir,
                    "reference_dir": self.reference_dir,
                    "remote_output_dir": self.remote_output_dir,
                    "variant_name": self.VARIANT_NAME,
                }

        def decorator(**_kwargs):
            return lambda function: function

        fake_cb = types.ModuleType("cua_bench")
        fake_cb.Task = FakeTask
        fake_cb.tasks_config = decorator
        fake_cb.setup_task = decorator
        fake_cb.evaluate_task = decorator
        fake_cb.interact = lambda _path: None
        fake_tasks = types.ModuleType("tasks")
        fake_linux = types.ModuleType("tasks.linux_runtime")
        fake_linux.LinuxTaskConfig = FakeLinuxTaskConfig

        with patch.dict(
            sys.modules,
            {
                "cua_bench": fake_cb,
                "tasks": fake_tasks,
                "tasks.linux_runtime": fake_linux,
            },
        ):
            for task_id, files in self.builds.items():
                with self.subTest(task_id=task_id):
                    main = self._by_path(files)["main.py"].data.decode("utf-8")
                    module_name = f"generated_{task_id.replace('-', '_')}"
                    generated = types.ModuleType(module_name)
                    generated.__file__ = "main.py"
                    with patch.dict(sys.modules, {module_name: generated}):
                        exec(compile(main, "main.py", "exec"), generated.__dict__)
                        tasks = generated.load()
                    self.assertEqual(len(tasks), 3)
                    self.assertEqual(
                        [task.metadata["instance_id"] for task in tasks],
                        ["000", "001", "002"],
                    )
                    for task in tasks:
                        instance_id = task.metadata["instance_id"]
                        expected_root = (
                            f"/media/user/data/agenthle/physical_sciences/"
                            f"{task_id}/{instance_id}"
                        )
                        self.assertEqual(task.metadata["task_dir"], expected_root)
                        self.assertTrue(task.metadata["input_path"].startswith(expected_root))
                        self.assertEqual(
                            task.metadata["grader_path"],
                            f"{expected_root}/reference/grader.py",
                        )
                        self.assertIn(expected_root, task.description)

    def test_mass_spring_test_labels_are_evaluator_only(self) -> None:
        files = self._by_path(self.builds["hnn-mass-spring"])
        for instance_id in ("000", "001", "002"):
            public_path = f"input/instances/{instance_id}/data.json"
            target_path = f"reference/instances/{instance_id}/targets.json"
            public = json.loads(files[public_path].data)
            target = json.loads(files[target_path].data)
            self.assertEqual(set(public["test"]), {"states"})
            self.assertNotIn("derivatives", public["test"])
            self.assertEqual(public["test"]["states"], target["test_states"])
            self.assertIn("test_derivatives", target)
            self.assertEqual(files[public_path].visibility, "agent")
            self.assertEqual(files[target_path].visibility, "evaluator")
            model = json.loads(
                files[f"example/instances/{instance_id}/reference_model.json"].data
            )
            self.assertEqual(model["format"], "tanh-mlp-v1")
            self.assertEqual(model["input_dim"], 2)
            self.assertEqual(model["output_dim"], 1)
            self.assertTrue(all(layer["activation"] in {"tanh", "linear"} for layer in model["layers"]))

    def test_hidden_quadratics_and_two_body_targets_are_not_agent_visible(self) -> None:
        symplectic = self._by_path(self.builds["hnn-symplectic-gradient"])
        two_body = self._by_path(self.builds["hnn-two-body-audit"])
        for instance_id in ("000", "001", "002"):
            hidden = symplectic[f"reference/instances/{instance_id}/tests.json"]
            self.assertEqual(hidden.visibility, "evaluator")
            self.assertIn("quadratic_tests", json.loads(hidden.data))
            expected = json.loads(
                two_body[f"reference/instances/{instance_id}/expected.json"].data
            )["expected"]
            self.assertEqual(expected["verdict"], "conflict")
            self.assertEqual(expected["candidate"]["direction"], "repulsive")
            self.assertEqual(expected["candidate"]["force_vector_distance_power"], -4)
            self.assertEqual(expected["implementation"]["direction"], "attractive")
            self.assertEqual(expected["implementation"]["force_vector_distance_power"], -3)
            self.assertEqual(expected["correction"]["potential_distance_power"], -1)

    def test_author_provenance_pins_sources_and_records_all_conflicts(self) -> None:
        provenance = json.loads(
            self._by_path(self.builds["hnn-two-body-audit"])["author/provenance.json"].data
        )
        self.assertEqual(provenance["paper"]["pdf_sha256"], PAPER_PDF_SHA256)
        self.assertEqual(
            provenance["official_implementation"]["revision"],
            OFFICIAL_REPO_REVISION,
        )
        self.assertEqual(provenance["ale_runtime"]["revision"], ALE_REPO_REVISION)
        fact_ids = {fact["id"] for fact in provenance["grounded_facts"]}
        self.assertTrue(
            {
                "spring-scaling-conflict",
                "spring-protocol-conflict",
                "two-body-equation-conflict",
                "pixel-loss-sign-conflict",
            }
            <= fact_ids
        )
        conflicts = [
            record
            for record in self.project["evidence_graph"]["records"]
            if record["kind"] == "conflict"
        ]
        self.assertTrue(conflicts)
        self.assertTrue(all(record["status"] != "unresolved" for record in conflicts))
        self.assertIn(
            "disagreement is preserved",
            next(
                record["interpretation"]
                for record in conflicts
                if record["id"] == "ev-two-body-sign-power-conflict"
            ),
        )

    def test_reference_artifacts_pass_the_independent_graders(self) -> None:
        for task_id, files in self.builds.items():
            with self.subTest(task_id=task_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_projection(files, root, "evaluator")
                if task_id == "hnn-symplectic-gradient":
                    shutil.copyfile(
                        root / "example" / "reference_solution.py",
                        root / "software" / "solution.py",
                    )
                    submission = root
                elif task_id == "hnn-mass-spring":
                    destination = root / "output" / "000" / "model.json"
                    destination.parent.mkdir(parents=True)
                    shutil.copyfile(
                        root / "example" / "instances" / "000" / "reference_model.json",
                        destination,
                    )
                    submission = destination
                else:
                    solver_path = root / "example" / "reference_solver.py"
                    spec = importlib.util.spec_from_file_location("hnn_reference_solver", solver_path)
                    self.assertIsNotNone(spec)
                    self.assertIsNotNone(spec.loader if spec else None)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    case = json.loads(
                        (root / "input" / "instances" / "000" / "case.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    destination = root / "output" / "000" / "audit.json"
                    destination.parent.mkdir(parents=True)
                    destination.write_text(
                        json.dumps(module.audit_case(case), allow_nan=False),
                        encoding="utf-8",
                    )
                    submission = destination

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(root / "reference" / "grader.py"),
                        "--submission",
                        str(submission),
                        "--instance",
                        "000",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertTrue(json.loads(completed.stdout)["passed"])

    def test_builder_rejects_unknown_tasks_and_bad_instance_counts(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported HNN task"):
            build_task_files(self.project, {"id": "not-an-hnn-task"}, master_seed=0)
        with self.assertRaisesRegex(ValueError, "between 1 and 64"):
            build_task_files(
                self.project,
                self.tasks["hnn-two-body-audit"],
                master_seed=0,
                instances=0,
            )


if __name__ == "__main__":
    unittest.main()
