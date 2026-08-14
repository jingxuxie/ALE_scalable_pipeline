from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.difficulty import (
    BENCHMARK_SAMPLING_KNOBS,
    CHALLENGE_KNOBS,
    TargetBand,
    assess_calibration_validity,
    assess_task_calibration_validity,
    builtin_profiles_v2,
    check_cross_level_behavioral_monotonicity,
    derive_agent_system_id,
    derive_purpose_seed,
    derive_task_calibration_id,
    deterministic_rng,
    pin_agent_system,
    resolve_difficulty_v2,
    summarize_calibration,
    summarize_calibration_by_agent_system,
    validate_profile_definition_v2,
)


def agent_descriptor(model_revision: str = "frontier-model@2026-08-01") -> dict:
    return {
        "provider": "example",
        "model_revision": model_revision,
        "harness_commit": "0123456789abcdef0123456789abcdef01234567",
        "tool_policy": {"shell": True, "browser": False},
        "budgets": {"tokens": 100_000, "wall_seconds": 3_600},
        "network_policy": {"enabled": False, "allowlist": []},
        "evaluation_date": "2026-08-13",
    }


class PurposeSeparatedProfileTests(unittest.TestCase):
    def test_builtin_v2_is_valid_and_instance_count_is_sampling_only(self) -> None:
        profile = builtin_profiles_v2()[0]
        self.assertEqual(validate_profile_definition_v2(profile), ())
        self.assertNotIn("instance_count", CHALLENGE_KNOBS)
        self.assertIn("instance_count", BENCHMARK_SAMPLING_KNOBS)

        # Sampling need not increase with difficulty and is not treated as
        # structural challenge evidence.
        profile["levels"][1]["benchmark_sampling"]["instance_count"] = 1
        self.assertEqual(validate_profile_definition_v2(profile), ())

    def test_sampling_only_level_change_is_rejected_as_cosmetic(self) -> None:
        profile = builtin_profiles_v2()[0]
        profile["id"] = "sampling-is-not-difficulty"
        profile["levels"][1]["challenge"] = copy.deepcopy(profile["levels"][0]["challenge"])
        profile["levels"][1]["evaluation_power"] = copy.deepcopy(
            profile["levels"][0]["evaluation_power"]
        )
        profile["levels"][1]["benchmark_sampling"]["instance_count"] = 64
        problems = validate_profile_definition_v2(profile)
        self.assertTrue(any(problem.code == "cosmetic_level" for problem in problems))

    def test_challenge_and_evaluation_power_have_independent_monotonic_checks(self) -> None:
        profile = builtin_profiles_v2()[0]
        profile["id"] = "wrong-directions"
        profile["levels"][1]["challenge"]["noise_scale"] = 0.25
        profile["levels"][1]["evaluation_power"]["hidden_case_count"] = 2
        codes = {problem.code for problem in validate_profile_definition_v2(profile)}
        self.assertIn("monotonic_challenge", codes)
        self.assertIn("monotonic_evaluation_power", codes)


class SemanticIdentityTests(unittest.TestCase):
    def test_sampling_changes_resolution_but_preserves_calibration_semantics(self) -> None:
        baseline = resolve_difficulty_v2("hard")
        resampled = resolve_difficulty_v2(
            "hard", benchmark_sampling_overrides={"instance_count": 6}
        )
        self.assertEqual(baseline.semantic_id, resampled.semantic_id)
        self.assertNotEqual(baseline.sampling_id, resampled.sampling_id)
        self.assertNotEqual(baseline.resolution_id, resampled.resolution_id)
        self.assertFalse(resampled.baseline_calibration_invalidated)
        self.assertTrue(
            assess_calibration_validity(resampled, baseline.semantic_id).valid
        )

    def test_semantic_override_invalidates_prior_calibration(self) -> None:
        baseline = resolve_difficulty_v2("hard")
        changed = resolve_difficulty_v2(
            "hard", challenge_overrides={"noise_scale": 1.3}
        )
        self.assertNotEqual(baseline.semantic_id, changed.semantic_id)
        self.assertTrue(changed.baseline_calibration_invalidated)
        validity = assess_calibration_validity(changed, baseline.semantic_id)
        self.assertEqual(validity.status, "invalidated")
        self.assertFalse(validity.valid)
        self.assertEqual(validity.invalidated_by, ("challenge.noise_scale",))
        self.assertTrue(assess_calibration_validity(changed, changed.semantic_id).valid)

    def test_persisted_calibration_identity_binds_exact_task_build(self) -> None:
        resolved = resolve_difficulty_v2("hard")
        first = derive_task_calibration_id(
            resolved,
            task_id="task-a",
            task_build_id="task-build_" + "a" * 64,
        )
        changed_build = derive_task_calibration_id(
            resolved,
            task_id="task-a",
            task_build_id="task-build_" + "b" * 64,
        )
        self.assertNotEqual(first, changed_build)
        self.assertTrue(
            assess_task_calibration_validity(
                resolved,
                first,
                task_id="task-a",
                task_build_id="task-build_" + "a" * 64,
            ).valid
        )
        self.assertFalse(
            assess_task_calibration_validity(
                resolved,
                first,
                task_id="task-a",
                task_build_id="task-build_" + "b" * 64,
            ).valid
        )
        with self.assertRaisesRegex(ValueError, "content-derived"):
            derive_task_calibration_id(
                resolved,
                task_id="task-a",
                task_build_id="task-build_unpinned",
            )


class RandomnessTests(unittest.TestCase):
    def test_seed_derivation_is_deterministic_and_purpose_separated(self) -> None:
        first = derive_purpose_seed(
            42, purpose="public-instance", coordinates=("task.one", 3)
        )
        second = derive_purpose_seed(
            42, purpose="public-instance", coordinates=("task.one", 3)
        )
        hidden = derive_purpose_seed(
            42, purpose="hidden-evaluation", coordinates=("task.one", 3)
        )
        other_variant = derive_purpose_seed(
            42, purpose="public-instance", coordinates=("task.one", 4)
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, hidden)
        self.assertNotEqual(first, other_variant)
        self.assertEqual(
            deterministic_rng("root", purpose="mutation", coordinates=(1,)).random(),
            deterministic_rng("root", purpose="mutation", coordinates=(1,)).random(),
        )
        with self.assertRaisesRegex(ValueError, "purpose"):
            derive_purpose_seed(42, purpose="")


class AgentSystemCalibrationTests(unittest.TestCase):
    def test_agent_system_id_pins_all_relevant_configuration(self) -> None:
        descriptor = agent_descriptor()
        first = derive_agent_system_id(descriptor)
        self.assertEqual(first, derive_agent_system_id(copy.deepcopy(descriptor)))
        self.assertNotEqual(first, derive_agent_system_id(agent_descriptor("other-revision")))
        pinned = pin_agent_system(descriptor)
        self.assertEqual(pinned["agent_system_id"], first)
        missing = copy.deepcopy(descriptor)
        missing.pop("network_policy")
        with self.assertRaisesRegex(ValueError, "network_policy"):
            derive_agent_system_id(missing)
        missing_provider = copy.deepcopy(descriptor)
        missing_provider.pop("provider")
        with self.assertRaisesRegex(ValueError, "provider"):
            derive_agent_system_id(missing_provider)
        unpinned_harness = copy.deepcopy(descriptor)
        unpinned_harness["harness_commit"] = "main"
        with self.assertRaisesRegex(ValueError, "exact 40- or 64-character"):
            derive_agent_system_id(unpinned_harness)

    def test_trials_are_grouped_not_pooled_and_scores_are_summarized(self) -> None:
        semantic_id = resolve_difficulty_v2("medium").semantic_id
        system_a = derive_agent_system_id(agent_descriptor("model-a"))
        system_b = derive_agent_system_id(agent_descriptor("model-b"))
        trials = [
            {
                "agent_system_id": system_a,
                "semantic_id": semantic_id,
                "passed": index < 15,
                "score": 0.8 if index < 15 else 0.2,
            }
            for index in range(20)
        ] + [
            {
                "agent_system_id": system_b,
                "semantic_id": semantic_id,
                "passed": index < 5,
                "score": 0.7 if index < 5 else 0.1,
            }
            for index in range(20)
        ]
        band = TargetBand("pass_rate", 0.1, 0.9, 0.95, 10)
        summaries = summarize_calibration_by_agent_system(
            trials, band, expected_semantic_id=semantic_id
        )
        self.assertEqual(len(summaries), 2)
        self.assertEqual({item.agent_system_id for item in summaries}, {system_a, system_b})
        self.assertTrue(all(item.calibration.score_summary is not None for item in summaries))
        with self.assertRaisesRegex(ValueError, "multiple agent_system_id"):
            summarize_calibration(trials, band)

        stale = copy.deepcopy(trials)
        stale[0]["semantic_id"] = "difficulty_semantic_stale"
        with self.assertRaisesRegex(ValueError, "invalidated"):
            summarize_calibration_by_agent_system(
                stale, band, expected_semantic_id=semantic_id
            )


class BehavioralMonotonicityTests(unittest.TestCase):
    @staticmethod
    def _trials(system: str, level: str, passed: int, score: float) -> list[dict]:
        return [
            {
                "agent_system_id": system,
                "level": level,
                "semantic_id": f"semantic-{level}",
                "passed": index < passed,
                "score": score,
            }
            for index in range(100)
        ]

    def test_cross_level_checks_use_uncertainty_and_remain_system_specific(self) -> None:
        supported_system = "agent_system_supported"
        violating_system = "agent_system_violating"
        trials = (
            self._trials(supported_system, "easy", 90, 0.9)
            + self._trials(supported_system, "medium", 50, 0.5)
            + self._trials(supported_system, "hard", 10, 0.1)
            + self._trials(violating_system, "easy", 10, 0.1)
            + self._trials(violating_system, "hard", 90, 0.9)
        )
        reports = check_cross_level_behavioral_monotonicity(
            trials,
            min_trials_per_level=50,
            compare_scores=True,
        )
        by_system = {report.agent_system_id: report for report in reports}
        self.assertEqual(by_system[supported_system].status, "supported")
        self.assertEqual(by_system[violating_system].status, "violated")
        self.assertTrue(
            all(
                comparison.easier_interval[0] <= comparison.easier_pass_rate
                <= comparison.easier_interval[1]
                for comparison in by_system[supported_system].comparisons
            )
        )

    def test_overlapping_intervals_are_inconclusive(self) -> None:
        trials = self._trials("agent_system_one", "easy", 52, 0.52) + self._trials(
            "agent_system_one", "hard", 48, 0.48
        )
        report = check_cross_level_behavioral_monotonicity(
            trials, min_trials_per_level=50
        )[0]
        self.assertEqual(report.status, "inconclusive")


class SchemaShapeTests(unittest.TestCase):
    def test_schema_exposes_v2_without_removing_v1_selection(self) -> None:
        schema = json.loads((ROOT / "schemas" / "difficulty_profile.schema.json").read_text())
        self.assertIn("profile_v1", schema["$defs"])
        self.assertIn("profile_v2", schema["$defs"])
        self.assertIn("selection", schema["$defs"])
        self.assertIn("selection_v2", schema["$defs"])
        required = set(schema["$defs"]["level_v2"]["required"])
        self.assertEqual(
            required,
            {
                "name",
                "challenge",
                "evaluation_power",
                "benchmark_sampling",
                "target_band",
            },
        )


if __name__ == "__main__":
    unittest.main()
