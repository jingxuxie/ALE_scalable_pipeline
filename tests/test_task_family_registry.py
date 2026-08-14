from __future__ import annotations

from pathlib import Path
import copy
import json
import os
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.packaging import BuildFile  # noqa: E402
from paper2ale.task_families import (  # noqa: E402
    TASK_FAMILIES,
    TaskFamily,
    register_task_family,
    registered_compiler_identity,
    registered_task_families,
    task_family,
)


class TaskFamilyRegistryTests(unittest.TestCase):
    def test_builtin_hnn_is_registered(self) -> None:
        self.assertIs(TASK_FAMILIES["hnn"], task_family("hnn").builder)
        self.assertIn("hnn", registered_task_families())
        self.assertIn(
            "hnn-symplectic-gradient", task_family("hnn").supported_task_ids
        )

    def test_known_family_rejects_unknown_task_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not support task ID"):
            task_family("hnn").validate_task(
                {"family": "hnn", "id": "model-invented-task"}
            )

    def test_fixed_hnn_family_requires_reviewed_project_provenance_and_contract(self) -> None:
        project = json.loads(
            (ROOT / "examples" / "hnn" / "project.json").read_text(
                encoding="utf-8"
            )
        )
        task = project["tasks"][0]
        task_family("hnn").validate_project_task(project, task)

        changed_source = copy.deepcopy(project)
        changed_source["source_bundle"][0]["version"] = "unreviewed"
        with self.assertRaisesRegex(ValueError, "exact reviewed paper/code"):
            task_family("hnn").validate_project_task(
                changed_source, changed_source["tasks"][0]
            )

        changed_evidence = copy.deepcopy(project)
        changed_evidence["evidence_graph"]["records"][0]["statement"] = "unrelated"
        with self.assertRaisesRegex(ValueError, "reviewed evidence graph"):
            task_family("hnn").validate_project_task(
                changed_evidence, changed_evidence["tasks"][0]
            )

        changed_contract = copy.deepcopy(project)
        changed_contract["tasks"][0]["output_contract"]["path"] = "wrong.py"
        with self.assertRaisesRegex(ValueError, "semantic contract"):
            task_family("hnn").validate_project_task(
                changed_contract, changed_contract["tasks"][0]
            )

    def test_generic_family_requires_a_protocol(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a declarative protocol"):
            task_family("generic").validate_task(
                {"family": "generic", "id": "generic-task"}
            )

    def test_generic_family_rejects_outer_contract_drift(self) -> None:
        from tests.test_generic_family import numeric_protocol

        protocol = numeric_protocol()
        task = {
            "family": "generic",
            "id": "generic-task",
            "protocol": protocol,
            "output_contract": {
                "format": "numeric_predictions_json",
                "filename": "submission.json",
            },
            "evaluation": {
                "metrics": [
                    {
                        "id": metric["id"],
                        "weight": metric["weight"],
                        "threshold": metric["threshold"],
                    }
                    for metric in protocol["evaluation"]["metrics"]
                ],
                "gates": list(protocol["evaluation"]["gates"]),
            },
        }
        task_family("generic").validate_task(task)
        task["evaluation"]["metrics"][0]["weight"] = 0.1
        with self.assertRaisesRegex(ValueError, "exactly match"):
            task_family("generic").validate_task(task)

    def test_explicit_registration_records_capabilities(self) -> None:
        def builder(*args, **kwargs):
            return [BuildFile("main.py", b"pass\n", "agent")]

        name = "unit-test-family"
        register_task_family(
            name,
            builder,
            compiler_id="unit-test-family/v1",
            supported_difficulty_levels=("easy", "hard"),
            replace=True,
        )
        self.assertIs(task_family(name).builder, builder)
        self.assertEqual(
            task_family(name).supported_difficulty_levels,
            ("easy", "hard"),
        )
        identities = registered_compiler_identity()["families"]
        registered = next(item for item in identities if item["family"] == name)
        self.assertEqual(registered["compiler_id"], "unit-test-family/v1")
        self.assertRegex(
            registered["builder"]["implementation_sha256"], r"^[0-9a-f]{64}$"
        )

    def test_declarative_family_owns_its_provider_schema(self) -> None:
        def builder(*args, **kwargs):
            return [BuildFile("main.py", b"pass\n", "agent")]

        def validator(value):
            return value

        def schema():
            return {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": ["kind"],
                "properties": {"kind": {"const": "unit"}},
            }

        family = TaskFamily(
            name="declarative-unit",
            compiler_id="declarative-unit/v1",
            builder=builder,
            supported_templates=("unit",),
            protocol_validator=validator,
            protocol_schema_factory=schema,
        )
        self.assertEqual(family.protocol_schema()["properties"]["kind"]["const"], "unit")
        with self.assertRaisesRegex(ValueError, "provider-facing protocol schema"):
            TaskFamily(
                name="missing-schema",
                compiler_id="missing-schema/v1",
                builder=builder,
                supported_templates=("unit",),
                protocol_validator=validator,
            )

    def test_compiler_identity_is_cross_process_stable_and_closure_sensitive(self) -> None:
        command = [
            sys.executable,
            "-c",
            (
                "import json; "
                "from paper2ale.task_families import registered_compiler_identity; "
                "print(json.dumps(registered_compiler_identity(),sort_keys=True))"
            ),
        ]
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        first = subprocess.check_output(command, cwd=ROOT, env=environment)
        second = subprocess.check_output(command, cwd=ROOT, env=environment)
        self.assertEqual(first, second)

        def factory(marker):
            def builder(*args, **kwargs):
                return [BuildFile("marker.txt", str(marker).encode(), "agent")]

            return builder

        first_family = TaskFamily(
            name="closure-a",
            compiler_id="closure-a/v1",
            builder=factory({"value": 1}),
        )
        second_family = TaskFamily(
            name="closure-b",
            compiler_id="closure-b/v1",
            builder=factory({"value": 2}),
        )
        self.assertNotEqual(
            first_family.identity()["builder"]["implementation_sha256"],
            second_family.identity()["builder"]["implementation_sha256"],
        )

    def test_unknown_family_error_lists_available_plugins(self) -> None:
        with self.assertRaisesRegex(ValueError, "registered families"):
            task_family("does-not-exist")


if __name__ == "__main__":
    unittest.main()
