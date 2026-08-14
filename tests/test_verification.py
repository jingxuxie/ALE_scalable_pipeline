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
import paper2ale.verification as verification_module  # noqa: E402
from paper2ale.verification import (  # noqa: E402
    _provenance_check,
    _run_bounded_subprocess,
    register_task_verification,
    registered_task_ids,
    verification_catalog_identity,
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
                    "publication_smoke_budget",
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

                resources = qa["checks"]["publication_smoke_budget"]["details"]
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
                self.assertTrue(reproduction["runtime_output_reproducible"])
                self.assertEqual(reproduction["grader_runs_per_submission"], 2)
                self.assertGreater(reproduction["grader_execution_pairs_compared"], 0)
                self.assertEqual(reproduction["runtime_mismatches"], [])
                self.assertEqual(
                    reproduction["original_archive_sha256"],
                    reproduction["repeated_archive_sha256"],
                )
                self.assertEqual(reproduction["mismatch_paths"], [])
                report = json.loads(
                    next(item.data for item in files if item.path == "author/qa_report.json")
                )
                self.assertEqual(report, qa)
                self.assertNotIn("wall_time_seconds", json.dumps(qa, sort_keys=True))

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
        weights = task["evaluation"]["weights"]
        always_pass = (
            "import argparse\n"
            "import json\n"
            "parser=argparse.ArgumentParser()\n"
            "parser.add_argument('--submission')\n"
            "parser.add_argument('--instance')\n"
            "parser.parse_args()\n"
            f"print(json.dumps({{'passed': True, 'score': 1.0, "
            f"'metric_scores': {dict.fromkeys(weights, 1.0)!r}}}))\n"
        ).encode("utf-8")
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

        observed_contexts = []

        def changed_builder(
            project,
            task,
            *,
            master_seed,
            instances=None,
            build_context=None,
        ):
            observed_contexts.append(build_context)
            return [*files, BuildFile("software/nondeterministic.txt", b"changed", "agent")]

        build_context = object()
        report = verify_task_publication(
            self.project,
            task,
            files,
            builder=changed_builder,
            master_seed=self.seed,
            instances=1,
            build_context=build_context,
        )
        self.assertEqual(observed_contexts, [build_context])
        self.assertEqual(report["checks"]["reproducibility"]["status"], "failed")
        self.assertIn(
            "software/nondeterministic.txt",
            report["checks"]["reproducibility"]["details"]["mismatch_paths"],
        )
        self.assertEqual(
            report["checks"]["publication_smoke_budget"]["status"], "failed"
        )
        self.assertFalse(
            report["checks"]["publication_smoke_budget"]["details"][
                "within_disk_budget"
            ]
        )

    def test_stdout_changing_grader_fails_runtime_reproducibility(self) -> None:
        task = dict(
            next(
                item
                for item in self.project["tasks"]
                if item["id"] == "hnn-symplectic-gradient"
            )
        )
        task["instances"] = 1
        original = build_task_files(self.project, task, master_seed=self.seed, instances=1)
        marker = "import sys\n"
        counter_output = (
            "import sys\n\n"
            "_counter_path = Path('.verification/grader-run-counter.txt')\n"
            "_counter_path.parent.mkdir(parents=True, exist_ok=True)\n"
            "_counter = (int(_counter_path.read_text()) + 1 "
            "if _counter_path.exists() else 1)\n"
            "_counter_path.write_text(str(_counter))\n"
            "print(f'grader-run={_counter}')\n"
        )
        changed = []
        for item in original:
            if item.path == "reference/grader.py":
                source = item.data.decode("utf-8")
                self.assertIn(marker, source)
                source = source.replace(marker, counter_output, 1)
                changed.append(
                    BuildFile(item.path, source.encode("utf-8"), item.visibility, item.executable)
                )
            else:
                changed.append(item)

        def repeated_builder(project, task, *, master_seed, instances=None):
            return changed

        report = verify_task_publication(
            self.project,
            task,
            changed,
            builder=repeated_builder,
            master_seed=self.seed,
            instances=1,
        )
        self.assertIsNotNone(report)
        reproduction = report["checks"]["reproducibility"]
        self.assertEqual(reproduction["status"], "failed")
        self.assertTrue(reproduction["details"]["byte_identical"])
        self.assertFalse(reproduction["details"]["runtime_output_reproducible"])
        self.assertTrue(
            any(
                item["role"] == "reference"
                for item in reproduction["details"]["runtime_mismatches"]
            )
        )
        reference = report["checks"]["runtime_reference"]["details"]["instances"][0]
        self.assertFalse(reference["passed"])
        self.assertFalse(reference["reproducibility"]["byte_identical"])
        self.assertTrue(reference["reproducibility"]["payload_identical"])

    def test_verification_catalog_hashes_registered_implementation_code(self) -> None:
        namespace_one = {"__name__": "verification_identity_fixture"}
        namespace_two = {"__name__": "verification_identity_fixture"}
        exec(
            compile(
                "def prepare(root, instance_id, timeout):\n    return 1\n",
                "<verification-identity>",
                "exec",
            ),
            namespace_one,
        )
        exec(
            compile(
                "def prepare(root, instance_id, timeout):\n    return 2\n",
                "<verification-identity>",
                "exec",
            ),
            namespace_two,
        )
        key = ("verification_identity_test", "implementation-change")
        try:
            register_task_verification(
                key[0], key[1], "mutant", namespace_one["prepare"]
            )
            first = next(
                item
                for item in verification_catalog_identity()["tasks"]
                if (item["family"], item["task_id"]) == key
            )
            register_task_verification(
                key[0],
                key[1],
                "mutant",
                namespace_two["prepare"],
                replace=True,
            )
            second_catalog = verification_catalog_identity()
            second = next(
                item
                for item in second_catalog["tasks"]
                if (item["family"], item["task_id"]) == key
            )
            self.assertEqual(first["prepare"]["module"], second["prepare"]["module"])
            self.assertEqual(first["prepare"]["qualname"], second["prepare"]["qualname"])
            self.assertNotEqual(
                first["prepare"]["implementation_sha256"],
                second["prepare"]["implementation_sha256"],
            )
            self.assertIn("publication_verifier", second_catalog["runtime"])
            serialized = json.dumps(second_catalog, sort_keys=True)
            self.assertNotIn(str(ROOT), serialized)
            self.assertNotIn(str(ROOT).replace("\\", "\\\\"), serialized)
        finally:
            verification_module._REGISTERED.pop(key, None)

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

    def test_provenance_rejects_unknown_source_kinds_by_default(self) -> None:
        for invalid_kind in ("paper ", "data", "unknown"):
            with self.subTest(kind=invalid_kind):
                project = json.loads(json.dumps(self.project))
                project["source_bundle"][0]["kind"] = invalid_kind
                project["source_bundle"][0].pop("sha256", None)
                report = _provenance_check(project)
                self.assertEqual(report["status"], "failed")
                self.assertTrue(
                    any(
                        "unknown source kind" in failure["reason"]
                        for failure in report["details"]["failures"]
                    )
                )


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
