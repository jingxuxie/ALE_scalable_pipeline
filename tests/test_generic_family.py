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
from paper2ale.packaging import projection_files, write_projection  # noqa: E402
from paper2ale.pipeline import audit_project  # noqa: E402
from paper2ale.task_families import (  # noqa: E402
    generic_protocol_json_schema,
    registered_capability_catalog,
    task_family,
    validate_task_protocol,
)
from paper2ale.task_families.generic import (  # noqa: E402
    PROTOCOL_SCHEMA_VERSION,
    ProtocolValidationError,
    TEMPLATE_DIFFICULTY_CONTROLS,
    build_task_files,
)


def numeric_protocol() -> dict:
    return {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "template_id": "numeric-affine-v1",
        "generator": {
            "primitive": "uniform_numeric_matrix",
            "input_dimension": 2,
            "output_dimension": 2,
            "query_count": 7,
            "public_example_count": 8,
            "low": -2,
            "high": 2,
            "decimals": 6,
            "public_noise_std": 0,
        },
        "reference_solver": {
            "primitive": "affine_transform",
            "weights": [[2.0, -0.5], [0.25, 1.5]],
            "bias": [0.5, -1.0],
        },
        "output": {
            "primitive": "numeric_predictions_json",
            "filename": "submission.json",
        },
        "evaluation": {
            "metrics": [
                {
                    "id": "rmse",
                    "primitive": "numeric_rmse",
                    "threshold": 1e-9,
                    "weight": 0.7,
                },
                {
                    "id": "maximum_error",
                    "primitive": "numeric_max_abs",
                    "threshold": 1e-8,
                    "weight": 0.3,
                },
            ],
            "gates": [
                "strict_json",
                "max_bytes",
                "shape_match",
                "finite_numbers",
                "query_id_match",
            ],
            "max_submission_bytes": 65536,
            "required_pass_fraction": 1.0,
        },
    }


def table_protocol() -> dict:
    return {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "template_id": "table-filter-sort-v1",
        "generator": {
            "primitive": "typed_record_table",
            "row_count": 9,
            "columns": [
                {
                    "name": "record_id",
                    "primitive": "sequence_integer",
                    "start": 100,
                    "step": 1,
                },
                {
                    "name": "score",
                    "primitive": "uniform_number",
                    "low": 0,
                    "high": 10,
                    "decimals": 3,
                },
                {
                    "name": "group",
                    "primitive": "choice",
                    "values": ["alpha", "beta"],
                },
            ],
        },
        "reference_solver": {
            "primitive": "filter_sort_project",
            "filter": {"column": "score", "operator": "gte", "value": 4.0},
            "sort": [
                {"column": "score", "direction": "descending"},
                {"column": "record_id", "direction": "ascending"},
            ],
            "project": ["record_id", "group", "score"],
        },
        "output": {
            "primitive": "table_rows_json",
            "filename": "submission.json",
        },
        "evaluation": {
            "metrics": [
                {
                    "id": "table_match",
                    "primitive": "table_exact",
                    "threshold": 1,
                    "weight": 1,
                }
            ],
            "gates": ["strict_json", "max_bytes", "row_schema_match"],
        },
    }


def json_protocol() -> dict:
    return {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "template_id": "json-group-aggregate-v1",
        "generator": {
            "primitive": "grouped_integer_records",
            "record_count": 12,
            "groups": ["north", "south", "west"],
            "group_field": "region",
            "value_field": "amount",
            "value_low": -5,
            "value_high": 20,
        },
        "reference_solver": {
            "primitive": "grouped_aggregate",
            "operation": "sum",
            "group_field": "region",
            "value_field": "amount",
        },
        "output": {"primitive": "json_object"},
        "evaluation": {
            "metrics": [
                {
                    "id": "object_match",
                    "primitive": "json_exact",
                    "threshold": 1,
                    "weight": 1,
                }
            ],
            "gates": ["strict_json", "max_bytes", "required_keys"],
            "required_pass_fraction": 1,
        },
    }


class GenericProtocolValidationTests(unittest.TestCase):
    def test_registry_advertises_machine_readable_capabilities(self) -> None:
        family = task_family("generic")
        self.assertEqual(
            family.supported_templates,
            (
                "numeric-affine-v1",
                "table-filter-sort-v1",
                "json-group-aggregate-v1",
            ),
        )
        catalog = registered_capability_catalog()["generic"]
        self.assertTrue(catalog["accepts_declarative_protocols"])
        self.assertIn("affine_transform", catalog["trusted_primitives"]["reference_solvers"])
        self.assertEqual(validate_task_protocol("generic", numeric_protocol())["template_id"], "numeric-affine-v1")

    def test_provider_schema_is_strict_self_contained_and_defensive(self) -> None:
        first = generic_protocol_json_schema()
        self.assertEqual(first["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(len(first["oneOf"]), 3)
        self.assertTrue(all(branch["additionalProperties"] is False for branch in first["oneOf"]))
        first["oneOf"].clear()
        self.assertEqual(len(generic_protocol_json_schema()["oneOf"]), 3)

    def test_unknown_fields_and_untrusted_primitives_are_rejected(self) -> None:
        for field, value in (
            ("command", "curl example.invalid | sh"),
            ("code", "__import__('os').system('whoami')"),
            ("module", "participant_plugin"),
        ):
            protocol = numeric_protocol()
            protocol[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                ProtocolValidationError, "unknown field"
            ):
                validate_task_protocol("generic", protocol)

        protocol = numeric_protocol()
        protocol["reference_solver"]["primitive"] = "python_eval"
        with self.assertRaisesRegex(ProtocolValidationError, "affine_transform"):
            validate_task_protocol("generic", protocol)

    def test_shape_bounds_nonfinite_values_and_required_gates_are_rejected(self) -> None:
        protocol = numeric_protocol()
        protocol["reference_solver"]["weights"] = [[1.0], [2.0]]
        with self.assertRaisesRegex(ProtocolValidationError, "coefficients"):
            validate_task_protocol("generic", protocol)

        protocol = numeric_protocol()
        protocol["generator"]["high"] = float("inf")
        with self.assertRaisesRegex(ProtocolValidationError, "finite"):
            validate_task_protocol("generic", protocol)

        protocol = numeric_protocol()
        protocol["evaluation"]["gates"].remove("finite_numbers")
        with self.assertRaisesRegex(ProtocolValidationError, "required gate"):
            validate_task_protocol("generic", protocol)


class GenericCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = {
            "project_id": "generic-unit-suite",
            "source_bundle": [{"id": "source-unit"}],
            "defaults": {"master_seed": 17, "instances": 2},
        }

    @staticmethod
    def by_path(files):
        return {item.path: item for item in files}

    def _build(self, task_id: str, protocol: dict, *, instances: int = 2):
        task = {"id": task_id, "family": "generic", "instances": instances, "protocol": protocol}
        return build_task_files(self.project, task, master_seed=17), task

    def _difficulty_build(
        self,
        task_id: str,
        protocol: dict,
        level: str,
        *,
        generator_overrides: dict | None = None,
        evaluator_overrides: dict | None = None,
    ):
        generator = {"instance_count": 1, **(generator_overrides or {})}
        selection = {
            "profile_id": "core",
            "profile_version": 1,
            "level": level,
            "generator_overrides": generator,
        }
        if evaluator_overrides:
            selection["evaluator_overrides"] = evaluator_overrides
        task = {
            "id": task_id,
            "family": "generic",
            "instances": 1,
            "protocol": protocol,
            "difficulty": selection,
        }
        project = {**self.project, "tasks": [task]}
        return build_task_files(project, task, master_seed=17), project, task

    def test_all_templates_build_complete_deterministic_partitioned_inventories(self) -> None:
        protocols = {
            "numeric": numeric_protocol(),
            "table": table_protocol(),
            "json": json_protocol(),
        }
        for suffix, protocol in protocols.items():
            with self.subTest(template=suffix):
                files, task = self._build(f"generic-{suffix}", protocol)
                repeated = build_task_files(self.project, task, master_seed=17)
                self.assertEqual(files, repeated)
                paths = self.by_path(files)
                for required in (
                    "description.md",
                    "task_card.json",
                    "main.py",
                    "reference/grader.py",
                    "author/protocol.json",
                    "author/protocol_validation.json",
                    "author/reference_solver.json",
                    "author/generation_parameters.json",
                ):
                    self.assertIn(required, paths)
                for instance_id in ("000", "001"):
                    self.assertIn(f"input/instances/{instance_id}/input.json", paths)
                    self.assertIn(f"reference/instances/{instance_id}/evaluation.json", paths)
                    self.assertIn(f"example/instances/{instance_id}/golden.json", paths)
                    self.assertIn(
                        f"example/instances/{instance_id}/visible_baseline.json", paths
                    )
                    self.assertIn(f"example/instances/{instance_id}/mutant.json", paths)
                    self.assertIn(
                        f"example/instances/{instance_id}/mutants/contract-extra-key.json",
                        paths,
                    )
                    self.assertIn(
                        f"example/instances/{instance_id}/mutants/contract-missing-output.json",
                        paths,
                    )
                agent = projection_files(files, "agent")
                self.assertTrue(agent)
                self.assertFalse(
                    any(item.path.startswith(("reference/", "example/", "author/")) for item in agent)
                )
                validation = json.loads(paths["author/protocol_validation.json"].data)
                self.assertFalse(validation["executes_protocol_code"])
                compile(paths["main.py"].data.decode("utf-8"), "main.py", "exec")
                compile(paths["reference/grader.py"].data.decode("utf-8"), "grader.py", "exec")

    def test_generated_grader_accepts_golden_and_rejects_mutant_for_each_template(self) -> None:
        protocols = (numeric_protocol(), table_protocol(), json_protocol())
        for index, protocol in enumerate(protocols):
            with self.subTest(template=protocol["template_id"]):
                files, _ = self._build(f"generic-grade-{index}", protocol, instances=1)
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    write_projection(files, root, "evaluator")
                    grader = root / "reference" / "grader.py"
                    golden = root / "example" / "instances" / "000" / "golden.json"
                    mutant = root / "example" / "instances" / "000" / "mutant.json"
                    accepted = subprocess.run(
                        [sys.executable, "-I", str(grader), "--submission", str(golden), "--instance", "000"],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    rejected = subprocess.run(
                        [sys.executable, "-I", str(grader), "--submission", str(mutant), "--instance", "000"],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                accepted_payload = json.loads(accepted.stdout)
                rejected_payload = json.loads(rejected.stdout)
                self.assertEqual(accepted.returncode, 0, accepted.stderr)
                self.assertTrue(accepted_payload["passed"])
                self.assertEqual(accepted_payload["score"], 1.0)
                self.assertEqual(set(accepted_payload["metric_scores"]), {metric["id"] for metric in protocol["evaluation"]["metrics"]})
                self.assertNotEqual(rejected.returncode, 0)
                self.assertFalse(rejected_payload["passed"])
                self.assertIn("hard_gates_passed", rejected_payload)

    def test_strict_json_rejects_duplicate_object_keys_even_if_last_value_is_golden(self) -> None:
        files, _ = self._build("generic-duplicate-json", numeric_protocol(), instances=1)
        paths = self.by_path(files)
        golden = json.loads(paths["example/instances/000/golden.json"].data)
        duplicate = (
            b'{"predictions":[],"predictions":'
            + json.dumps(
                golden["predictions"],
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"}"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_projection(files, root, "evaluator")
            submission = root / "duplicate.json"
            submission.write_bytes(duplicate)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(root / "reference" / "grader.py"),
                    "--submission",
                    str(submission),
                    "--instance",
                    "000",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        payload = json.loads(completed.stdout)
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(payload["passed"])
        self.assertTrue(
            any("duplicate JSON object key 'predictions'" in error for error in payload["errors"])
        )

    def test_difficulty_consumption_audit_is_exact_per_template(self) -> None:
        protocols = (numeric_protocol(), table_protocol(), json_protocol())
        expected = {
            "numeric-affine-v1": {
                "generator": {
                    "instance_count",
                    "input_complexity_scale",
                    "masked_fraction",
                    "constraint_count",
                },
                "evaluator": {
                    "hidden_case_count",
                    "threshold_scale",
                    "rollout_horizon_scale",
                    "required_pass_fraction",
                    "adversarial_case_count",
                },
                "unsupported_generator": {"noise_scale"},
                "unsupported_evaluator": set(),
            },
            "table-filter-sort-v1": {
                "generator": {
                    "instance_count",
                    "input_complexity_scale",
                    "constraint_count",
                },
                "evaluator": {"hidden_case_count", "adversarial_case_count"},
                "unsupported_generator": {"noise_scale", "masked_fraction"},
                "unsupported_evaluator": {
                    "threshold_scale",
                    "rollout_horizon_scale",
                    "required_pass_fraction",
                },
            },
            "json-group-aggregate-v1": {
                "generator": {
                    "instance_count",
                    "input_complexity_scale",
                    "constraint_count",
                },
                "evaluator": {"hidden_case_count", "adversarial_case_count"},
                "unsupported_generator": {"noise_scale", "masked_fraction"},
                "unsupported_evaluator": {
                    "threshold_scale",
                    "rollout_horizon_scale",
                    "required_pass_fraction",
                },
            },
        }
        self.assertEqual(set(TEMPLATE_DIFFICULTY_CONTROLS), set(expected))
        for index, protocol in enumerate(protocols):
            template = protocol["template_id"]
            with self.subTest(template=template):
                files, project, task = self._difficulty_build(
                    f"generic-audit-{index}", protocol, "hard"
                )
                paths = self.by_path(files)
                audit = json.loads(paths["author/difficulty_control_audit.json"].data)
                manifest = json.loads(paths["author/difficulty_manifest.json"].data)
                resolved = resolve_task_difficulty(project, task)
                self.assertTrue(verify_consumption_manifest(resolved, manifest))
                self.assertEqual(
                    audit["schema_version"],
                    "paper2ale.generic-difficulty-control-audit/v1",
                )
                self.assertEqual(audit["resolution_id"], manifest["resolution_id"])
                self.assertEqual(set(audit["consumed"]["generator"]), expected[template]["generator"])
                self.assertEqual(set(audit["consumed"]["evaluator"]), expected[template]["evaluator"])
                self.assertEqual(set(audit["unsupported"]["generator"]), expected[template]["unsupported_generator"])
                self.assertEqual(set(audit["unsupported"]["evaluator"]), expected[template]["unsupported_evaluator"])
                self.assertEqual(
                    set(audit["effects"]),
                    {
                        f"{section}.{control}"
                        for section in ("generator", "evaluator")
                        for control in audit["consumed"][section]
                    },
                )

    def test_difficulty_levels_have_monotonic_material_effects(self) -> None:
        protocols = (numeric_protocol(), table_protocol(), json_protocol())
        protocols[0]["generator"]["public_noise_std"] = 0.1
        count_key = {
            "numeric-affine-v1": "queries",
            "table-filter-sort-v1": "rows",
            "json-group-aggregate-v1": "records",
        }
        levels = ("easy", "medium", "hard", "frontier")
        for protocol_index, protocol in enumerate(protocols):
            template = protocol["template_id"]
            public_payloads = []
            evaluation_payloads = []
            counts = []
            decoy_counts = []
            settings = []
            for level in levels:
                files, _, _ = self._difficulty_build(
                    f"generic-monotonic-{protocol_index}", protocol, level
                )
                paths = self.by_path(files)
                public_payloads.append(paths["input/instances/000/input.json"].data)
                evaluation_payloads.append(
                    paths["reference/instances/000/evaluation.json"].data
                )
                public = json.loads(public_payloads[-1])
                values = public[count_key[template]]
                counts.append(len(values))
                sample = values[0]
                if template == "numeric-affine-v1":
                    decoy_counts.append(len(sample["context"]))
                else:
                    decoy_counts.append(
                        len([key for key in sample if key.startswith("context_")])
                    )
                parameters = json.loads(
                    paths["author/generation_parameters.json"].data
                )
                settings.append(parameters["derived_difficulty_settings"])
            with self.subTest(template=template):
                self.assertEqual(counts, sorted(counts))
                self.assertEqual(len(set(counts)), len(levels))
                self.assertEqual(decoy_counts, [1, 2, 4, 6])
                self.assertEqual(len(set(public_payloads)), len(levels))
                if template == "numeric-affine-v1":
                    self.assertEqual(
                        [item["public_noise_scale"] for item in settings],
                        [0.5, 1.0, 1.25, 1.5],
                    )
                    self.assertEqual(
                        [item["threshold_scale"] for item in settings],
                        [1.5, 1.0, 0.75, 0.5],
                    )
                    self.assertEqual(len(set(evaluation_payloads)), len(levels))
                else:
                    self.assertTrue(
                        all("public_noise_scale" not in item for item in settings)
                    )
                    self.assertTrue(
                        all("threshold_scale" not in item for item in settings)
                    )
                    required = [
                        json.loads(payload)["required_pass_fraction"]
                        for payload in evaluation_payloads
                    ]
                    self.assertEqual(required, [1.0] * len(levels))

    def test_unsupported_nondefault_overrides_fail_closed(self) -> None:
        cases = []
        table = table_protocol()
        cases.append((table, {"noise_scale": 1.3}, None, "generator.noise_scale"))
        grouped = json_protocol()
        cases.append((grouped, None, {"threshold_scale": 0.7}, "evaluator.threshold_scale"))
        zero_noise = numeric_protocol()
        cases.append((zero_noise, {"noise_scale": 1.3}, None, "generator.noise_scale"))
        one_metric = numeric_protocol()
        one_metric["evaluation"]["metrics"] = one_metric["evaluation"]["metrics"][:1]
        cases.append((one_metric, None, {"required_pass_fraction": 0.85}, "evaluator.required_pass_fraction"))
        for index, (protocol, generator, evaluator, control) in enumerate(cases):
            with self.subTest(template=protocol["template_id"], control=control):
                with self.assertRaisesRegex(ValueError, control.replace(".", r"\.")):
                    self._difficulty_build(
                        f"generic-reject-{index}",
                        protocol,
                        "hard",
                        generator_overrides=generator,
                        evaluator_overrides=evaluator,
                    )

        noisy = numeric_protocol()
        noisy["generator"]["public_noise_std"] = 0.1
        baseline, _, _ = self._difficulty_build(
            "generic-supported-noise", noisy, "hard"
        )
        changed, _, _ = self._difficulty_build(
            "generic-supported-noise",
            noisy,
            "hard",
            generator_overrides={"noise_scale": 1.3},
        )
        baseline_input = self.by_path(baseline)["input/instances/000/input.json"].data
        changed_input = self.by_path(changed)["input/instances/000/input.json"].data
        self.assertNotEqual(baseline_input, changed_input)

    def test_difficulty_changes_materialized_data_and_is_manifest_bound(self) -> None:
        task = {
            "id": "generic-difficulty",
            "family": "generic",
            "instances": 1,
            "protocol": numeric_protocol(),
            "difficulty": {"profile_id": "core", "profile_version": 1, "level": "easy"},
        }
        project = dict(self.project)
        project["tasks"] = [task]
        files = build_task_files(project, task, master_seed=17)
        paths = self.by_path(files)
        manifest = json.loads(paths["author/difficulty_manifest.json"].data)
        resolved = resolve_task_difficulty(project, task)
        self.assertIsNotNone(resolved)
        self.assertTrue(verify_consumption_manifest(resolved, manifest))
        parameters = json.loads(paths["author/generation_parameters.json"].data)
        self.assertEqual(parameters["derived_difficulty_settings"]["level"], "easy")
        public = json.loads(paths["input/instances/000/input.json"].data)
        self.assertGreaterEqual(len(public["queries"]), int(resolved.evaluator["hidden_case_count"]))

    def test_generic_fixture_passes_release_gates_with_a_mutant_suite(self) -> None:
        report = audit_project(ROOT / "examples" / "generic" / "project.json")
        self.assertTrue(report["publication_ready"])
        mutation = report["tasks"][0]["qa"]["checks"]["mutation_resistance"]
        self.assertEqual(mutation["status"], "passed")
        self.assertEqual(
            set(mutation["details"]["registered_mutants"]),
            {
                "template-specific-realistic-mutant",
                "contract-extra-key",
                "contract-missing-output",
            },
        )
        self.assertEqual(len(mutation["details"]["instances"]), 15)


if __name__ == "__main__":
    unittest.main()
