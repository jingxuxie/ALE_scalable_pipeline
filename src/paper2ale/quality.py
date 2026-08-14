"""Publication gates and soft task-quality scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


QUALITY_WEIGHTS = {
    "evaluator_validity": 0.25,
    "paper_faithfulness": 0.20,
    "reproducibility": 0.15,
    "specification_clarity": 0.15,
    "resource_fit": 0.10,
    "novelty_diversity": 0.10,
    "professional_value": 0.05,
}


@dataclass(frozen=True)
class QualityReport:
    passed: bool
    score: float
    dimensions: Mapping[str, float]
    failed_gates: tuple[str, ...]
    failed_dimensions: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "score": self.score,
            "dimensions": dict(self.dimensions),
            "failed_gates": list(self.failed_gates),
            "failed_dimensions": list(self.failed_dimensions),
        }


def score_quality(
    hard_gates: Mapping[str, bool],
    dimensions: Mapping[str, float],
    *,
    overall_minimum: float = 0.82,
    dimension_minimums: Mapping[str, float] | None = None,
) -> QualityReport:
    missing = set(QUALITY_WEIGHTS) - set(dimensions)
    extra = set(dimensions) - set(QUALITY_WEIGHTS)
    if missing or extra:
        raise ValueError(f"quality dimensions mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    normalized: dict[str, float] = {}
    for name, value in dimensions.items():
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError(f"quality dimension {name} must be between 0 and 1")
        normalized[name] = numeric
    score = sum(QUALITY_WEIGHTS[name] * normalized[name] for name in QUALITY_WEIGHTS)
    minima = dict(dimension_minimums or {"evaluator_validity": 0.8, "paper_faithfulness": 0.75})
    failed_dimensions = tuple(sorted(name for name, minimum in minima.items() if normalized[name] < minimum))
    failed_gates = tuple(sorted(name for name, passed in hard_gates.items() if not bool(passed)))
    passed = not failed_gates and not failed_dimensions and score >= overall_minimum
    return QualityReport(passed, score, normalized, failed_gates, failed_dimensions)


__all__ = ["QUALITY_WEIGHTS", "QualityReport", "score_quality"]
