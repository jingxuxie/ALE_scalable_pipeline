from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.packaging import BuildFile  # noqa: E402
from paper2ale.pipeline import _build_task_in_memory  # noqa: E402
from paper2ale.task_families.hnn import build_task_files  # noqa: E402
from paper2ale.verification import (  # noqa: E402
    _run_bounded_subprocess,
    registered_task_ids,
    verify_task_publication,
)


class HNNPublicationVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project = json.loads(
            (ROOT / "examples" / "hnn" / "project.json").read_text(encoding="utf-8")
        )
        cls.seed = cls.project["defaults"]["master_seed"]
        cls.verified = {}
        for task in cls.project["tasks"]:
            _, files, qa = _build_task_in_memory(cls.project, task, cls.seed, None)
            cls.verified[task["id"]] = (files, qa)

    def test_all_registered_tasks_and_instances_are_publication_ready(self) -> None:
        self.assertEqual(set(registered_task_ids("hnn")), set(self.verified))
        for task_id, (files, qa) in self.verified.items():
            with self.subTest(task_id=task_id):
                self.assertTrue(qa["preflight_passed"])
                self.assertTrue(qa["publication_ready"])
                for gate in (
                    "provenance",
                    "runtime_reference",
                    "mutation_resistance",
                    "resource_budget",
                    "reproducibility",
                ):
                    self.assertEqual(qa["checks"][gate]["status"], "passed")

                references = qa["checks"]["runtime_reference"]["details"]
                mutants = qa["checks"]["mutation_resistance"]["details"]
                self.assertEqual(references["discovered_instances"], ["000", "001", "002"])
                self.assertTrue(all(item["passed"] for item in references["instances"]))
                self.assertEqual(len(mutants["instances"]), 3)
                self.assertTrue(all(item["rejected"] for item in mutants["instances"]))
                self.assertTrue(all(item["mutant_id"] for item in mutants["instances"]))

                resources = qa["checks"]["resource_budget"]["details"]
                self.assertEqual(resources["evidence_kind"], "publication_smoke_test")
                self.assertTrue(resources["wall_time_measured"])
                self.assertGreater(resources["measured_package_bytes"], 0)
                self.assertTrue(resources["within_cpu_seconds_budget"])
                self.assertTrue(resources["within_disk_budget"])
                self.assertIsNone(resources["peak_memory_bytes"])
                self.assertIn("peak memory is not measured", resources["limitations"])

                reproduction = qa["checks"]["reproducibility"]["details"]
                self.assertTrue(reproduction["byte_identical"])
                self.assertTrue(reproduction["archive_byte_identical"])
                self.assertEqual(
                    reproduction["original_archive_sha256"],
                    reproduction["repeated_archive_sha256"],
                )
                self.assertEqual(reproduction["mismatch_paths"], [])
                report = json.loads(
                    next(item.data for item in files if item.path == "author/qa_report.json")
                )
                self.assertEqual(report, qa)

    def test_registered_mutant_that_escapes_is_a_failed_gate(self) -> None:
        task = dict(
            next(
                item
                for item in self.project["tasks"]
                if item["id"] == "hnn-two-body-audit"
            )
        )
        task["instances"] = 1
        original = build_task_files(self.project, task, master_seed=self.seed, instances=1)
        always_pass = b'''import argparse\nimport json\nparser=argparse.ArgumentParser()\nparser.add_argument("--submission")\nparser.add_argument("--instance")\nparser.parse_args()\nprint(json.dumps({"passed": True}))\n'''
        broken = [
            BuildFile(item.path, always_pass, item.visibility, item.executable)
            if item.path == "reference/grader.py"
            else item
            for item in original
        ]

        def repeated_builder(project, task, *, master_seed, instances=None):
            return broken

        report = verify_task_publication(
            self.project,
            task,
            broken,
            builder=repeated_builder,
            master_seed=self.seed,
            instances=1,
        )
        self.assertIsNotNone(report)
        self.assertEqual(report["checks"]["runtime_reference"]["status"], "passed")
        self.assertEqual(report["checks"]["mutation_resistance"]["status"], "failed")
        self.assertFalse(
            report["checks"]["mutation_resistance"]["details"]["instances"][0][
                "rejected"
            ]
        )

    def test_reproducibility_and_smoke_budget_fail_closed(self) -> None:
        task = dict(
            next(
                item
                for item in self.project["tasks"]
                if item["id"] == "hnn-symplectic-gradient"
            )
        )
        task["instances"] = 1
        task["resource_budget"] = dict(task["resource_budget"], disk_mb=1e-9)
        files = build_task_files(self.project, task, master_seed=self.seed, instances=1)

        def changed_builder(project, task, *, master_seed, instances=None):
            return [*files, BuildFile("software/nondeterministic.txt", b"changed", "agent")]

        report = verify_task_publication(
            self.project,
            task,
            files,
            builder=changed_builder,
            master_seed=self.seed,
            instances=1,
        )
        self.assertEqual(report["checks"]["reproducibility"]["status"], "failed")
        self.assertIn(
            "software/nondeterministic.txt",
            report["checks"]["reproducibility"]["details"]["mismatch_paths"],
        )
        self.assertEqual(report["checks"]["resource_budget"]["status"], "failed")
        self.assertFalse(
            report["checks"]["resource_budget"]["details"]["within_disk_budget"]
        )

    def test_unregistered_task_has_no_dynamic_verifier(self) -> None:
        task = {"id": "custom-task", "family": "custom"}
        files = [BuildFile("main.py", b"pass\n", "agent")]
        called = False

        def builder(*args, **kwargs):
            nonlocal called
            called = True
            return files

        self.assertIsNone(
            verify_task_publication(
                {}, task, files, builder=builder, master_seed=0, instances=1
            )
        )
        self.assertFalse(called)


class BoundedSubprocessTests(unittest.TestCase):
    def test_stdout_overflow_and_timeout_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            overflow = _run_bounded_subprocess(
                (sys.executable, "-c", "print('x' * 4096)"),
                cwd=root,
                timeout_seconds=5,
                max_stdout_bytes=64,
                max_stderr_bytes=64,
            )
            self.assertTrue(overflow.stdout_overflow)
            self.assertLessEqual(len(overflow.stdout), 64)

            timeout = _run_bounded_subprocess(
                (sys.executable, "-c", "import time; time.sleep(2)"),
                cwd=root,
                timeout_seconds=0.05,
                max_stdout_bytes=64,
                max_stderr_bytes=64,
            )
            self.assertTrue(timeout.timed_out)
            self.assertLess(timeout.wall_time_seconds, 1.5)


if __name__ == "__main__":
    unittest.main()
