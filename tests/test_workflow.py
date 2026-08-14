from __future__ import annotations

import unittest

from paper2ale.workflow import (
    ArtifactNode,
    OperationNode,
    WorkflowIR,
    require_closed_workflow,
    validate_workflow_closure,
    workflow_json_schema,
)


def valid_workflow() -> WorkflowIR:
    return WorkflowIR(
        id="workflow.test",
        title="Fit and independently score a model",
        artifacts=(
            ArtifactNode("observations", "input", "provided", "application/json", "Observed samples", "trusted_generator", ("e1",), capability_ref="fixture.synthetic.observations"),
            ArtifactNode("predictions", "output", "generated", "application/json", "Predicted values", "participant", ("e2",)),
            ArtifactNode("hidden_score", "reference", "hidden", "application/json", "Evaluator score", "trusted_evaluator", ("e3",)),
        ),
        operations=(
            OperationNode(
                "fit",
                "train",
                "participant",
                "Fit the model and emit predictions",
                ("observations",),
                ("predictions",),
                ("e2",),
                {"epochs": 10},
            ),
            OperationNode(
                "score",
                "evaluate",
                "trusted_evaluator",
                "Compare predictions with hidden truth",
                ("predictions",),
                ("hidden_score",),
                ("e3",),
                {"metric": "relative_error"},
            ),
        ),
        outputs=("predictions",),
        evidence_ids=("e1", "e2", "e3"),
    )


class WorkflowTests(unittest.TestCase):
    def test_valid_workflow_is_closed_and_scheduled(self) -> None:
        workflow = valid_workflow()
        report = validate_workflow_closure(workflow)
        self.assertTrue(report.valid, report.errors)
        self.assertEqual(report.topological_order, ("fit", "score"))
        self.assertEqual(report.required_inputs, ("observations",))
        self.assertEqual(WorkflowIR.from_dict(workflow.to_dict()), workflow)

    def test_schema_is_strict_and_has_no_executable_fields(self) -> None:
        schema = workflow_json_schema()
        self.assertFalse(schema["additionalProperties"])
        operation = schema["properties"]["operations"]["items"]
        self.assertFalse(operation["additionalProperties"])
        self.assertNotIn("command", operation["properties"])
        self.assertNotIn("executor", operation["properties"])

    def test_asset_references_are_explicit_safe_and_role_scoped(self) -> None:
        artifact = ArtifactNode(
            "observations",
            "input",
            "provided",
            "application/json",
            "Observed samples",
            "asset",
            ("e1",),
            {"asset_id": "dataset.v1", "relative_path": "folds/train.json"},
        )
        self.assertEqual(ArtifactNode.from_dict(artifact.to_dict()), artifact)
        with self.assertRaisesRegex(ValueError, "safe relative POSIX"):
            ArtifactNode(
                "bad",
                "input",
                "provided",
                "application/json",
                "Unsafe path",
                "asset",
                asset_ref={"asset_id": "dataset.v1", "relative_path": "../truth.json"},
            )
        with self.assertRaisesRegex(ValueError, "valid only"):
            ArtifactNode(
                "generated",
                "output",
                "generated",
                "application/json",
                "Generated output",
                "participant",
                asset_ref={"asset_id": "dataset.v1", "relative_path": "truth.json"},
            )

    def test_model_parameters_cannot_smuggle_executable_authority(self) -> None:
        for field, value in (
            ("command", "rm -rf something"),
            ("argv", ["python", "unsafe.py"]),
            ("url", "https://untrusted.invalid/payload"),
            ("container", {"image": "untrusted/latest"}),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "declarative only"
            ):
                OperationNode(
                    "run",
                    "transform",
                    "participant",
                    "Unsafe generated operation",
                    ("input",),
                    ("output",),
                    parameters={"nested": {field: value}},
                )

    def test_unknown_fields_are_rejected(self) -> None:
        value = valid_workflow().to_dict()
        value["operations"][0]["executor"] = "python"
        with self.assertRaisesRegex(ValueError, "unknown=.*executor"):
            WorkflowIR.from_dict(value)

    def test_external_input_breaks_self_contained_closure(self) -> None:
        value = valid_workflow().to_dict()
        value["artifacts"][0]["availability"] = "external"
        value["artifacts"][0]["origin"] = "external"
        value["artifacts"][0].pop("capability_ref")
        workflow = WorkflowIR.from_dict(value)
        strict = validate_workflow_closure(workflow)
        relaxed = validate_workflow_closure(workflow, require_self_contained=False)
        self.assertFalse(strict.valid)
        self.assertIn("external dependencies", strict.errors[0])
        self.assertTrue(relaxed.valid)
        self.assertTrue(any("external dependencies" in item for item in relaxed.warnings))

    def test_cycles_and_duplicate_producers_are_rejected(self) -> None:
        workflow = WorkflowIR(
            id="cyclic",
            title="Cyclic workflow",
            artifacts=(
                ArtifactNode("a", "intermediate", "generated", "text/plain", "A", "participant"),
                ArtifactNode("b", "output", "generated", "text/plain", "B", "participant"),
            ),
            operations=(
                OperationNode("one", "transform", "participant", "B to A", ("b",), ("a",)),
                OperationNode("two", "transform", "participant", "A to B", ("a",), ("b",)),
            ),
            outputs=("b",),
        )
        report = validate_workflow_closure(workflow)
        self.assertFalse(report.valid)
        self.assertTrue(any("cycle" in item for item in report.errors))
        with self.assertRaisesRegex(ValueError, "closure failed"):
            require_closed_workflow(workflow)

        value = valid_workflow().to_dict()
        duplicate = dict(value["operations"][0])
        duplicate["id"] = "second_fit"
        value["operations"].append(duplicate)
        report = validate_workflow_closure(WorkflowIR.from_dict(value))
        self.assertTrue(any("multiple producers" in item for item in report.errors))

    def test_unknown_artifacts_and_undeclared_outputs_are_reported(self) -> None:
        value = valid_workflow().to_dict()
        value["operations"][0]["inputs"] = ["missing"]
        value["artifacts"].append(
            ArtifactNode("extra", "output", "generated", "text/plain", "Extra output", "participant").to_dict()
        )
        value["operations"].append(
            OperationNode("extra_op", "analyze", "participant", "Extra", (), ("extra",)).to_dict()
        )
        report = validate_workflow_closure(WorkflowIR.from_dict(value))
        self.assertFalse(report.valid)
        self.assertTrue(any("unknown input" in item for item in report.errors))
        self.assertTrue(any("not declared" in item for item in report.errors))


if __name__ == "__main__":
    unittest.main()
