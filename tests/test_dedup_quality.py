from __future__ import annotations

import unittest

from paper2ale.dedup import CandidateIndex, hamming_distance, protocol_fingerprint
from paper2ale.quality import QUALITY_WEIGHTS, score_quality


def candidate(identifier: str, title: str = "Energy audit") -> dict:
    return {
        "id": identifier,
        "title": title,
        "summary": "Audit conserved energy over hidden trajectories",
        "family": "hnn",
        "mode": "specification_preserving",
        "evidence_ids": ["e1"],
        "workflow_nodes": ["n1"],
        "output_contract": {"files": ["audit.json"]},
        "evaluation": {"gates": ["schema"], "weights": {"correctness": 1.0}},
        "resource_budget": {"timeout_s": 60},
    }


class DedupQualityTests(unittest.TestCase):
    def test_protocol_fingerprint_ignores_display_text(self) -> None:
        first = candidate("a", "One title")
        second = candidate("b", "Another title")
        self.assertEqual(protocol_fingerprint(first), protocol_fingerprint(second))

    def test_exact_duplicate(self) -> None:
        index = CandidateIndex()
        self.assertIsNone(index.add(candidate("a")))
        match = index.add(candidate("b", "Different wording"))
        self.assertEqual(match.kind, "exact_protocol")
        self.assertEqual(hamming_distance(1, 3), 1)

    def test_hard_gate_cannot_be_overridden(self) -> None:
        dimensions = {name: 1.0 for name in QUALITY_WEIGHTS}
        report = score_quality({"reference_passes": True, "no_leakage": False}, dimensions)
        self.assertFalse(report.passed)
        self.assertIn("no_leakage", report.failed_gates)


if __name__ == "__main__":
    unittest.main()
