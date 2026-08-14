from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.difficulty import (
    LEVEL_NAMES,
    TargetBand,
    apply_difficulty_override,
    builtin_profiles,
    make_consumption_manifest,
    resolve_task_difficulty,
    summarize_calibration,
    validate_profile_definition,
    verify_consumption_manifest,
)


def small_project() -> dict:
    return {"tasks": [{"id": "task.one", "instances": 1}]}


class ResolutionTests(unittest.TestCase):
    def test_canonical_levels_resolve_to_real_monotone_controls(self) -> None:
        self.assertEqual(LEVEL_NAMES, ("easy", "medium", "hard", "frontier"))
        profile = builtin_profiles()[0]
        self.assertEqual(validate_profile_definition(profile), ())
        by_name = {level["name"]: level for level in profile["levels"]}
        instance_counts = [by_name[name]["generator"]["instance_count"] for name in LEVEL_NAMES]
        hidden_counts = [by_name[name]["evaluator"]["hidden_case_count"] for name in LEVEL_NAMES]
        thresholds = [by_name[name]["evaluator"]["threshold_scale"] for name in LEVEL_NAMES]
        self.assertEqual(instance_counts, sorted(instance_counts))
        self.assertEqual(hidden_counts, sorted(hidden_counts))
        self.assertEqual(thresholds, sorted(thresholds, reverse=True))
        self.assertEqual(len(set(instance_counts)), len(LEVEL_NAMES))

    def test_resolution_is_deterministic_and_override_is_literal(self) -> None:
        project = small_project()
        task = project["tasks"][0]
        task["difficulty"] = {
            "level": "medium",
            "profile_version": 1,
            "profile_id": "core",
            "generator_overrides": {"noise_scale": 1.1},
        }
        first = resolve_task_difficulty(project, "task.one")
        reordered = {
            "tasks": [
                {
                    "instances": 1,
                    "difficulty": {
                        "generator_overrides": {"noise_scale": 1.1},
                        "profile_id": "core",
                        "profile_version": 1,
                        "level": "medium",
                    },
                    "id": "task.one",
                }
            ]
        }
        second = resolve_task_difficulty(reordered, reordered["tasks"][0])
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        hard = resolve_task_difficulty(project, task, override="hard")
        self.assertEqual(hard.level, "hard")
        self.assertEqual(hard.generator["instance_count"], 5)
        self.assertNotEqual(first.resolution_id, hard.resolution_id)

    def test_apply_override_is_non_mutating_and_synchronizes_instances(self) -> None:
        project = small_project()
        original = copy.deepcopy(project)
        result = apply_difficulty_override(project, "frontier")
        self.assertEqual(project, original)
        self.assertEqual(result["tasks"][0]["difficulty"]["level"], "frontier")
        self.assertEqual(result["tasks"][0]["instances"], 8)
        resolved = resolve_task_difficulty(result, "task.one")
        self.assertEqual(result["tasks"][0]["instances"], resolved.generator["instance_count"])

    def test_selection_overrides_are_bounded_and_profile_scoped(self) -> None:
        project = small_project()
        task = project["tasks"][0]
        task["difficulty"] = {
            "profile_id": "core",
            "profile_version": 1,
            "level": "hard",
            "generator_overrides": {"noise_scale": 4},
        }
        with self.assertRaisesRegex(ValueError, "between 0 and 3"):
            resolve_task_difficulty(project, task)
        task["difficulty"]["generator_overrides"] = {"imaginary_knob": 1}
        with self.assertRaisesRegex(ValueError, "unknown difficulty knob"):
            resolve_task_difficulty(project, task)


class ProfileValidationTests(unittest.TestCase):
    def test_cosmetic_adjacent_level_is_rejected(self) -> None:
        profile = builtin_profiles()[0]
        profile["id"] = "cosmetic"
        profile["levels"][1]["generator"] = copy.deepcopy(profile["levels"][0]["generator"])
        profile["levels"][1]["evaluator"] = copy.deepcopy(profile["levels"][0]["evaluator"])
        problems = validate_profile_definition(profile)
        self.assertTrue(any(problem.code == "cosmetic_level" for problem in problems))

    def test_nonmonotone_and_inconsistent_profiles_are_rejected(self) -> None:
        profile = builtin_profiles()[0]
        profile["id"] = "bad"
        profile["levels"][1]["generator"]["instance_count"] = 0
        profile["levels"][2]["evaluator"].pop("hidden_case_count")
        problems = validate_profile_definition(profile)
        codes = {problem.code for problem in problems}
        self.assertIn("range", codes)
        self.assertIn("keys", codes)


class ConsumptionManifestTests(unittest.TestCase):
    def test_exact_consumption_is_hash_bound_and_tampering_fails(self) -> None:
        resolved = resolve_task_difficulty(small_project(), "task.one", override="hard")
        manifest = make_consumption_manifest(
            resolved,
            dict(resolved.generator),
            dict(resolved.evaluator),
        )
        self.assertTrue(verify_consumption_manifest(resolved, manifest))
        tampered = copy.deepcopy(manifest)
        tampered["generator"]["instance_count"] = 4
        self.assertFalse(verify_consumption_manifest(resolved, tampered))
        with self.assertRaisesRegex(ValueError, "do not exactly match"):
            make_consumption_manifest(
                resolved,
                tampered["generator"],
                resolved.evaluator,
            )
        wrong_numeric_type = dict(resolved.generator)
        wrong_numeric_type["instance_count"] = float(wrong_numeric_type["instance_count"])
        with self.assertRaisesRegex(ValueError, "do not exactly match"):
            make_consumption_manifest(resolved, wrong_numeric_type, resolved.evaluator)


class CalibrationTests(unittest.TestCase):
    def test_wilson_summary_reports_target_fit(self) -> None:
        band = TargetBand("pass_rate", 0.3, 0.7, 0.95, 20)
        summary = summarize_calibration([True] * 20 + [False] * 20, band)
        self.assertEqual(summary.status, "calibrated")
        self.assertTrue(summary.meets_target)
        self.assertLess(summary.interval_lower, summary.pass_rate)
        self.assertGreater(summary.interval_upper, summary.pass_rate)
        self.assertEqual(summary.to_dict()["trials"], 40)

    def test_calibration_distinguishes_hard_easy_and_insufficient(self) -> None:
        band = TargetBand("pass_rate", 0.3, 0.7, 0.95, 20)
        self.assertEqual(summarize_calibration([False] * 40, band).status, "too_hard")
        self.assertEqual(summarize_calibration([True] * 40, band).status, "too_easy")
        self.assertEqual(
            summarize_calibration([{"passed": True}] * 5, band).status,
            "insufficient_trials",
        )

    def test_calibration_rejects_bad_trials_and_bands(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            summarize_calibration([], TargetBand("pass_rate", 0.3, 0.7, 0.95, 1))
        with self.assertRaisesRegex(ValueError, "boolean"):
            summarize_calibration([1], TargetBand("pass_rate", 0.3, 0.7, 0.95, 1))
        with self.assertRaises(ValueError):
            summarize_calibration([True], {"metric": "pass_rate", "lower": 0.8, "upper": 0.2, "confidence": 0.95, "min_trials": 1})


if __name__ == "__main__":
    unittest.main()
