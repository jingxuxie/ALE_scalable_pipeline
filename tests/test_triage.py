from __future__ import annotations

import unittest

from paper2ale.triage import (
    PaperProfile,
    TaskReadiness,
    TriagePolicy,
    mine_task_candidates,
    triage_paper,
    triage_task,
)
from paper2ale.workflow import ArtifactNode, OperationNode, WorkflowIR


def paper(**overrides: object) -> PaperProfile:
    values: dict[str, object] = {
        "paper_id": "paper-1",
        "title": "A useful scientific paper",
        "readable": True,
        "provenance_complete": True,
        "license_status": "known",
        "scientific_quality": 0.9,
        "evidence_coverage": 0.9,
        "independent_verification_possible": True,
        "analytic_oracle_possible": True,
        "synthetic_data_possible": True,
        "public_code": False,
        "public_data": False,
        "workflow_reconstructable": True,
        "contradictions_resolved": True,
        "resources_bounded": True,
    }
    values.update(overrides)
    return PaperProfile(**values)  # type: ignore[arg-type]


def workflow(*, external: bool = False, verifier: bool = True) -> WorkflowIR:
    artifacts = [
        ArtifactNode(
            "input_data",
            "input",
            "external" if external else "provided",
            "application/json",
            "Input samples",
            "external" if external else "trusted_generator",
            ("e1",),
            capability_ref=None if external else "fixture.synthetic.input",
        ),
        ArtifactNode(
            "result",
            "output",
            "generated",
            "application/json",
            "Participant result",
            "participant",
            ("e2",),
        ),
    ]
    operations = [
        OperationNode(
            "solve",
            "analyze",
            "participant",
            "Analyze the samples",
            ("input_data",),
            ("result",),
            ("e2",),
        )
    ]
    if verifier:
        artifacts.append(
            ArtifactNode(
                "score",
                "reference",
                "hidden",
                "application/json",
                "Hidden score",
                "trusted_evaluator",
                ("e3",),
            )
        )
        operations.append(
            OperationNode(
                "verify",
                "validate",
                "trusted_evaluator",
                "Independently validate the result",
                ("result",),
                ("score",),
                ("e3",),
            )
        )
    return WorkflowIR(
        id="workflow-1",
        title="Scientific analysis",
        artifacts=tuple(artifacts),
        operations=tuple(operations),
        outputs=("result",),
        evidence_ids=("e1", "e2", "e3") if verifier else ("e1", "e2"),
    )


class TriageTests(unittest.TestCase):
    def test_no_public_code_or_data_is_allowed_with_constructible_oracle(self) -> None:
        report = triage_paper(paper())
        self.assertEqual(report.decision, "eligible")
        self.assertTrue(report.accepted)
        self.assertIn(
            "no_public_artifacts_but_independent_construction_is_possible",
            report.warnings,
        )

    def test_low_quality_and_unreadable_papers_are_rejected(self) -> None:
        report = triage_paper(paper(readable=False, scientific_quality=0.2))
        self.assertEqual(report.decision, "rejected")
        self.assertIn("paper_not_readable", report.hard_failures)
        self.assertIn("scientific_quality_below_threshold", report.hard_failures)

    def test_no_verification_is_no_viable_task(self) -> None:
        report = triage_paper(
            paper(
                independent_verification_possible=False,
                analytic_oracle_possible=False,
                synthetic_data_possible=False,
            )
        )
        self.assertEqual(report.decision, "no_viable_task")
        self.assertIn("no_independent_verification", report.hard_failures)

    def test_missing_artifacts_is_distinct_from_bad_science(self) -> None:
        report = triage_paper(
            paper(analytic_oracle_possible=False, synthetic_data_possible=False)
        )
        self.assertEqual(report.decision, "missing_artifacts")
        self.assertFalse(report.hard_failures)

    def test_license_and_evidence_uncertainty_route_to_manual_review(self) -> None:
        report = triage_paper(
            paper(
                license_status="unknown",
                provenance_complete=False,
                evidence_coverage=0.5,
            )
        )
        self.assertEqual(report.decision, "manual_review")
        self.assertIn("paper_license_requires_review", report.review_flags)
        self.assertIn("source_provenance_incomplete", report.review_flags)

    def test_strict_policy_can_require_public_artifacts(self) -> None:
        report = triage_paper(
            paper(), policy=TriagePolicy(require_public_code_or_data=True)
        )
        self.assertEqual(report.decision, "missing_artifacts")

    def test_candidate_mining_finds_bounded_backward_slice_and_verifier(self) -> None:
        candidates = mine_task_candidates([workflow()])
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.operation_ids, ("solve",))
        self.assertEqual(candidate.input_artifact_ids, ("input_data",))
        self.assertEqual(candidate.verifier_operation_ids, ("verify",))
        self.assertTrue(candidate.self_contained)
        self.assertTrue(candidate.verification_plan_present)
        self.assertEqual(candidate.to_dict()["target_artifact_id"], "result")

    def test_candidate_without_verifier_fails_task_triage(self) -> None:
        candidate = mine_task_candidates([workflow(verifier=False)])[0]
        report = triage_task(
            TaskReadiness(
                candidate=candidate,
                evaluator_implemented=False,
                trusted_family_available=True,
                output_machine_checkable=True,
                resources_bounded=True,
                evidence_coverage=0.9,
            )
        )
        self.assertEqual(report.decision, "no_viable_task")
        self.assertIn("no_independent_verification_plan", report.hard_failures)

    def test_model_plan_requires_trusted_implementation_before_eligibility(self) -> None:
        candidate = mine_task_candidates([workflow()])[0]
        pending = triage_task(
            TaskReadiness(candidate, False, False, True, True, 0.9)
        )
        self.assertEqual(pending.decision, "manual_review")
        self.assertIn("trusted_evaluator_not_implemented", pending.review_flags)
        ready = triage_task(
            TaskReadiness(candidate, True, True, True, True, 0.9)
        )
        self.assertEqual(ready.decision, "eligible")

    def test_external_inputs_are_reported_as_missing(self) -> None:
        candidate = mine_task_candidates([workflow(external=True)])[0]
        self.assertFalse(candidate.self_contained)
        report = triage_task(TaskReadiness(candidate, True, True, True, True, 0.9))
        self.assertEqual(report.decision, "missing_artifacts")

    def test_hidden_participant_dependency_is_not_self_contained(self) -> None:
        hidden = WorkflowIR(
            id="hidden-dependency",
            title="Invalid participant dependency",
            artifacts=(
                ArtifactNode(
                    "secret",
                    "reference",
                    "hidden",
                    "application/json",
                    "Evaluator-only secret",
                    "trusted_evaluator",
                    ("e1",),
                ),
                ArtifactNode(
                    "result",
                    "output",
                    "generated",
                    "application/json",
                    "Participant output",
                    "participant",
                    ("e2",),
                ),
                ArtifactNode(
                    "score",
                    "reference",
                    "hidden",
                    "application/json",
                    "Hidden score",
                    "trusted_evaluator",
                    ("e3",),
                ),
            ),
            operations=(
                OperationNode(
                    "solve",
                    "analyze",
                    "participant",
                    "Illegally consume hidden truth",
                    ("secret",),
                    ("result",),
                    ("e2",),
                ),
                OperationNode(
                    "verify",
                    "validate",
                    "trusted_evaluator",
                    "Score output",
                    ("result",),
                    ("score",),
                    ("e3",),
                ),
            ),
            outputs=("result",),
            evidence_ids=("e1", "e2", "e3"),
        )
        candidate = mine_task_candidates([hidden])[0]
        self.assertEqual(candidate.input_artifact_ids, ("secret",))
        self.assertFalse(candidate.self_contained)


if __name__ == "__main__":
    unittest.main()
