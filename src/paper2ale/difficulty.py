"""Deterministic, enforceable difficulty profiles and calibration helpers.

Difficulty is deliberately represented as concrete generator and evaluator
parameters.  A level name by itself is never accepted: it must resolve through
a versioned profile to bounded numeric controls that a builder can attest it
consumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import random
import re
from statistics import NormalDist, fmean, median, stdev
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


DIFFICULTY_SCHEMA_VERSION = "paper2ale.difficulty/v1"
DIFFICULTY_SCHEMA_VERSION_V2 = "paper2ale.difficulty/v2"
CONSUMPTION_SCHEMA_VERSION = "paper2ale.difficulty-consumption/v1"
CALIBRATION_SCHEMA_VERSION = "paper2ale.calibration/v2"
RNG_DERIVATION_VERSION = "paper2ale.rng-derivation/v1"
TASK_CALIBRATION_ID_VERSION = "paper2ale.task-calibration-identity/v1"
LEVEL_NAMES = ("easy", "medium", "hard", "frontier")
BUILTIN_PROFILE_ID = "core"
BUILTIN_PROFILE_VERSION = 1
BUILTIN_PROFILE_VERSION_V2 = 2


@dataclass(frozen=True)
class KnobSpec:
    minimum: float
    maximum: float
    integer: bool
    harder_when: str


GENERATOR_KNOBS: Mapping[str, KnobSpec] = MappingProxyType(
    {
        "instance_count": KnobSpec(1, 64, True, "higher"),
        "input_complexity_scale": KnobSpec(0.25, 4.0, False, "higher"),
        "noise_scale": KnobSpec(0.0, 3.0, False, "higher"),
        "masked_fraction": KnobSpec(0.0, 0.95, False, "higher"),
        "constraint_count": KnobSpec(0, 128, True, "higher"),
    }
)

EVALUATOR_KNOBS: Mapping[str, KnobSpec] = MappingProxyType(
    {
        "hidden_case_count": KnobSpec(1, 10_000, True, "higher"),
        "threshold_scale": KnobSpec(0.1, 4.0, False, "lower"),
        "rollout_horizon_scale": KnobSpec(0.25, 8.0, False, "higher"),
        "required_pass_fraction": KnobSpec(0.5, 1.0, False, "higher"),
        "adversarial_case_count": KnobSpec(0, 1_024, True, "higher"),
    }
)

# Version 1 used ``generator`` as a compatibility envelope and placed
# ``instance_count`` alongside controls that change an individual episode.
# Version 2 makes the distinction explicit.  Increasing the number of sampled
# instances improves benchmark coverage; it does not make any one episode more
# challenging and therefore must not be used as evidence of monotonic task
# difficulty.
CHALLENGE_KNOBS: Mapping[str, KnobSpec] = MappingProxyType(
    {key: spec for key, spec in GENERATOR_KNOBS.items() if key != "instance_count"}
)
EVALUATION_POWER_KNOBS: Mapping[str, KnobSpec] = EVALUATOR_KNOBS
BENCHMARK_SAMPLING_KNOBS: Mapping[str, KnobSpec] = MappingProxyType(
    {"instance_count": GENERATOR_KNOBS["instance_count"]}
)


_BUILTIN_PROFILE: dict[str, Any] = {
    "schema_version": DIFFICULTY_SCHEMA_VERSION,
    "id": BUILTIN_PROFILE_ID,
    "version": BUILTIN_PROFILE_VERSION,
    "description": "Portable baseline controls for task generation and evaluation.",
    "levels": [
        {
            "name": "easy",
            "generator": {
                "instance_count": 1,
                "input_complexity_scale": 0.75,
                "noise_scale": 0.5,
                "masked_fraction": 0.1,
                "constraint_count": 1,
            },
            "evaluator": {
                "hidden_case_count": 8,
                "threshold_scale": 1.5,
                "rollout_horizon_scale": 0.5,
                "required_pass_fraction": 0.7,
                "adversarial_case_count": 0,
            },
            "target_band": {
                "metric": "pass_rate",
                "lower": 0.55,
                "upper": 0.85,
                "confidence": 0.95,
                "min_trials": 20,
            },
        },
        {
            "name": "medium",
            "generator": {
                "instance_count": 3,
                "input_complexity_scale": 1.0,
                "noise_scale": 1.0,
                "masked_fraction": 0.3,
                "constraint_count": 2,
            },
            "evaluator": {
                "hidden_case_count": 16,
                "threshold_scale": 1.0,
                "rollout_horizon_scale": 1.0,
                "required_pass_fraction": 0.8,
                "adversarial_case_count": 2,
            },
            "target_band": {
                "metric": "pass_rate",
                "lower": 0.4,
                "upper": 0.7,
                "confidence": 0.95,
                "min_trials": 30,
            },
        },
        {
            "name": "hard",
            "generator": {
                "instance_count": 5,
                "input_complexity_scale": 1.5,
                "noise_scale": 1.25,
                "masked_fraction": 0.5,
                "constraint_count": 4,
            },
            "evaluator": {
                "hidden_case_count": 32,
                "threshold_scale": 0.75,
                "rollout_horizon_scale": 1.5,
                "required_pass_fraction": 0.9,
                "adversarial_case_count": 4,
            },
            "target_band": {
                "metric": "pass_rate",
                "lower": 0.24,
                "upper": 0.56,
                "confidence": 0.95,
                "min_trials": 40,
            },
        },
        {
            "name": "frontier",
            "generator": {
                "instance_count": 8,
                "input_complexity_scale": 2.0,
                "noise_scale": 1.5,
                "masked_fraction": 0.7,
                "constraint_count": 6,
            },
            "evaluator": {
                "hidden_case_count": 64,
                "threshold_scale": 0.5,
                "rollout_horizon_scale": 2.0,
                "required_pass_fraction": 0.95,
                "adversarial_case_count": 8,
            },
            "target_band": {
                "metric": "pass_rate",
                "lower": 0.1,
                "upper": 0.4,
                "confidence": 0.95,
                "min_trials": 50,
            },
        },
    ],
}


def _to_v2_level(level: Mapping[str, Any]) -> dict[str, Any]:
    """Translate the portable v1 controls into their purpose-separated form."""

    generator = dict(level["generator"])
    return {
        "name": level["name"],
        "challenge": {
            key: value for key, value in generator.items() if key != "instance_count"
        },
        "evaluation_power": dict(level["evaluator"]),
        "benchmark_sampling": {"instance_count": generator["instance_count"]},
        "target_band": dict(level["target_band"]),
    }


_BUILTIN_PROFILE_V2: dict[str, Any] = {
    "schema_version": DIFFICULTY_SCHEMA_VERSION_V2,
    "id": BUILTIN_PROFILE_ID,
    "version": BUILTIN_PROFILE_VERSION_V2,
    "description": (
        "Portable controls with per-episode challenge, evaluation power, and "
        "benchmark sampling separated."
    ),
    "levels": [_to_v2_level(level) for level in _BUILTIN_PROFILE["levels"]],
}


@dataclass(frozen=True)
class DifficultyProblem:
    code: str
    message: str
    path: str = ""


@dataclass(frozen=True)
class TargetBand:
    metric: str
    lower: float
    upper: float
    confidence: float
    min_trials: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TargetBand":
        return cls(
            metric=str(value["metric"]),
            lower=float(value["lower"]),
            upper=float(value["upper"]),
            confidence=float(value["confidence"]),
            min_trials=int(value["min_trials"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "lower": self.lower,
            "upper": self.upper,
            "confidence": self.confidence,
            "min_trials": self.min_trials,
        }


@dataclass(frozen=True)
class ScoreSummary:
    """Finite-score summary with an uncertainty interval for the mean."""

    trials: int
    mean: float
    median: float
    minimum: float
    maximum: float
    standard_deviation: float
    confidence: float
    interval_lower: float
    interval_upper: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "trials": self.trials,
            "mean": self.mean,
            "median": self.median,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "standard_deviation": self.standard_deviation,
            "confidence": self.confidence,
            "mean_confidence_interval": {
                "lower": self.interval_lower,
                "upper": self.interval_upper,
            },
        }


@dataclass(frozen=True)
class CalibrationValidity:
    """Whether calibration evidence describes the resolved task semantics."""

    status: str
    valid: bool
    calibrated_semantic_id: str | None
    resolved_semantic_id: str
    invalidated_by: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "valid": self.valid,
            "calibrated_semantic_id": self.calibrated_semantic_id,
            "resolved_semantic_id": self.resolved_semantic_id,
            "invalidated_by": list(self.invalidated_by),
        }


@dataclass(frozen=True)
class ResolvedDifficultyV2:
    """Purpose-separated difficulty resolution.

    ``semantic_id`` covers the per-episode challenge and evaluation semantics.
    ``sampling_id`` covers benchmark population and replication.  Consequently,
    changing only ``instance_count`` changes ``resolution_id`` but preserves
    ``semantic_id`` and does not invalidate calibration evidence.
    """

    profile_id: str
    profile_version: int
    level: str
    challenge: Mapping[str, int | float]
    evaluation_power: Mapping[str, int | float]
    benchmark_sampling: Mapping[str, int | float]
    target_band: TargetBand
    profile_semantic_id: str
    semantic_id: str
    sampling_id: str
    resolution_id: str
    semantic_overrides: tuple[str, ...]
    sampling_overrides: tuple[str, ...]
    baseline_calibration_invalidated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DIFFICULTY_SCHEMA_VERSION_V2,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "level": self.level,
            "challenge": dict(self.challenge),
            "evaluation_power": dict(self.evaluation_power),
            "benchmark_sampling": dict(self.benchmark_sampling),
            "target_band": self.target_band.to_dict(),
            "profile_semantic_id": self.profile_semantic_id,
            "semantic_id": self.semantic_id,
            "sampling_id": self.sampling_id,
            "resolution_id": self.resolution_id,
            "semantic_overrides": list(self.semantic_overrides),
            "sampling_overrides": list(self.sampling_overrides),
            "baseline_calibration_invalidated": self.baseline_calibration_invalidated,
        }


@dataclass(frozen=True)
class ResolvedDifficulty:
    profile_id: str
    profile_version: int
    level: str
    generator: Mapping[str, int | float]
    evaluator: Mapping[str, int | float]
    target_band: TargetBand
    resolution_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "level": self.level,
            "generator": dict(self.generator),
            "evaluator": dict(self.evaluator),
            "target_band": self.target_band.to_dict(),
            "resolution_id": self.resolution_id,
        }


@dataclass(frozen=True)
class CalibrationSummary:
    trials: int
    passed: int
    pass_rate: float
    confidence: float
    interval_lower: float
    interval_upper: float
    target_lower: float
    target_upper: float
    min_trials: int
    status: str
    meets_target: bool
    score_summary: ScoreSummary | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "trials": self.trials,
            "passed": self.passed,
            "pass_rate": self.pass_rate,
            "confidence": self.confidence,
            "confidence_interval": {
                "lower": self.interval_lower,
                "upper": self.interval_upper,
            },
            "target_band": {
                "lower": self.target_lower,
                "upper": self.target_upper,
            },
            "min_trials": self.min_trials,
            "status": self.status,
            "meets_target": self.meets_target,
        }
        if self.score_summary is not None:
            result["score_summary"] = self.score_summary.to_dict()
        return result


@dataclass(frozen=True)
class AgentSystemCalibrationSummary:
    """Calibration result for exactly one pinned agent-system configuration."""

    agent_system_id: str
    semantic_id: str | None
    calibration: CalibrationSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "agent_system_id": self.agent_system_id,
            "semantic_id": self.semantic_id,
            "calibration": self.calibration.to_dict(),
        }


@dataclass(frozen=True)
class BehavioralMonotonicityComparison:
    agent_system_id: str
    easier_level: str
    harder_level: str
    easier_trials: int
    harder_trials: int
    easier_pass_rate: float
    harder_pass_rate: float
    easier_interval: tuple[float, float]
    harder_interval: tuple[float, float]
    status: str
    score_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_system_id": self.agent_system_id,
            "easier_level": self.easier_level,
            "harder_level": self.harder_level,
            "easier": {
                "trials": self.easier_trials,
                "pass_rate": self.easier_pass_rate,
                "confidence_interval": {
                    "lower": self.easier_interval[0],
                    "upper": self.easier_interval[1],
                },
            },
            "harder": {
                "trials": self.harder_trials,
                "pass_rate": self.harder_pass_rate,
                "confidence_interval": {
                    "lower": self.harder_interval[0],
                    "upper": self.harder_interval[1],
                },
            },
            "status": self.status,
            "score_status": self.score_status,
        }


@dataclass(frozen=True)
class BehavioralMonotonicityReport:
    agent_system_id: str
    confidence: float
    min_trials_per_level: int
    status: str
    comparisons: tuple[BehavioralMonotonicityComparison, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_system_id": self.agent_system_id,
            "confidence": self.confidence,
            "min_trials_per_level": self.min_trials_per_level,
            "status": self.status,
            "comparisons": [item.to_dict() for item in self.comparisons],
        }


def _json_copy(value: Any) -> Any:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return json.loads(encoded)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def builtin_profiles() -> tuple[dict[str, Any], ...]:
    """Return independent copies of the built-in, versioned profiles."""

    return (_json_copy(_BUILTIN_PROFILE),)


def builtin_profiles_v2() -> tuple[dict[str, Any], ...]:
    """Return purpose-separated profiles for new pipeline integrations."""

    return (_json_copy(_BUILTIN_PROFILE_V2),)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_knob_map(
    value: Any,
    specs: Mapping[str, KnobSpec],
    path: str,
    *,
    require_instance_count: bool = False,
) -> list[DifficultyProblem]:
    problems: list[DifficultyProblem] = []
    if not isinstance(value, Mapping):
        return [DifficultyProblem("type", "must be an object", path)]
    if not value:
        problems.append(DifficultyProblem("required", "must contain at least one numeric control", path))
    for key in value:
        if key not in specs:
            problems.append(DifficultyProblem("unknown_key", f"unknown difficulty knob {key!r}", f"{path}/{key}"))
    if require_instance_count and "instance_count" not in value:
        problems.append(
            DifficultyProblem(
                "required",
                "generator controls must include instance_count so builders have an enforceable generation parameter",
                f"{path}/instance_count",
            )
        )
    for key, raw in value.items():
        spec = specs.get(key)
        if spec is None:
            continue
        item_path = f"{path}/{key}"
        if not _is_number(raw):
            problems.append(DifficultyProblem("type", "must be a finite number", item_path))
            continue
        if spec.integer and not isinstance(raw, int):
            problems.append(DifficultyProblem("type", "must be an integer", item_path))
            continue
        if raw < spec.minimum or raw > spec.maximum:
            problems.append(
                DifficultyProblem(
                    "range",
                    f"must be between {spec.minimum:g} and {spec.maximum:g}",
                    item_path,
                )
            )
    return problems


def _validate_target_band(value: Any, path: str) -> list[DifficultyProblem]:
    problems: list[DifficultyProblem] = []
    required = {"metric", "lower", "upper", "confidence", "min_trials"}
    if not isinstance(value, Mapping):
        return [DifficultyProblem("type", "must be an object", path)]
    unknown = set(value) - required
    missing = required - set(value)
    for key in sorted(unknown):
        problems.append(DifficultyProblem("unknown_key", "unknown field", f"{path}/{key}"))
    for key in sorted(missing):
        problems.append(DifficultyProblem("required", "field is required", f"{path}/{key}"))
    if value.get("metric") != "pass_rate":
        problems.append(DifficultyProblem("enum", "must be 'pass_rate'", f"{path}/metric"))
    lower = value.get("lower")
    upper = value.get("upper")
    confidence = value.get("confidence")
    min_trials = value.get("min_trials")
    if not _is_number(lower) or not 0 <= lower <= 1:
        problems.append(DifficultyProblem("range", "must be a finite number in [0, 1]", f"{path}/lower"))
    if not _is_number(upper) or not 0 <= upper <= 1:
        problems.append(DifficultyProblem("range", "must be a finite number in [0, 1]", f"{path}/upper"))
    if _is_number(lower) and _is_number(upper) and lower >= upper:
        problems.append(DifficultyProblem("range", "must be greater than lower", f"{path}/upper"))
    if not _is_number(confidence) or not 0 < confidence < 1:
        problems.append(DifficultyProblem("range", "must be a finite number strictly between 0 and 1", f"{path}/confidence"))
    if not isinstance(min_trials, int) or isinstance(min_trials, bool) or min_trials < 1:
        problems.append(DifficultyProblem("range", "must be a positive integer", f"{path}/min_trials"))
    return problems


def validate_profile_definition(profile: Any) -> tuple[DifficultyProblem, ...]:
    """Validate a profile including monotonicity and non-cosmetic levels."""

    problems: list[DifficultyProblem] = []
    required = {"schema_version", "id", "version", "levels"}
    allowed = required | {"description"}
    if not isinstance(profile, Mapping):
        return (DifficultyProblem("type", "difficulty profile must be an object"),)
    for key in sorted(set(profile) - allowed):
        problems.append(DifficultyProblem("unknown_key", "unknown field", f"/{key}"))
    for key in sorted(required - set(profile)):
        problems.append(DifficultyProblem("required", "field is required", f"/{key}"))
    if profile.get("schema_version") != DIFFICULTY_SCHEMA_VERSION:
        problems.append(
            DifficultyProblem(
                "schema_version",
                f"must be {DIFFICULTY_SCHEMA_VERSION!r}",
                "/schema_version",
            )
        )
    profile_id = profile.get("id")
    if not isinstance(profile_id, str) or not profile_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in profile_id):
        problems.append(DifficultyProblem("format", "must be a nonempty safe identifier", "/id"))
    version = profile.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        problems.append(DifficultyProblem("range", "must be a positive integer", "/version"))
    if "description" in profile and not isinstance(profile["description"], str):
        problems.append(DifficultyProblem("type", "must be a string", "/description"))
    levels = profile.get("levels")
    if not isinstance(levels, Sequence) or isinstance(levels, (str, bytes, bytearray)) or not levels:
        problems.append(DifficultyProblem("type", "must be a nonempty array", "/levels"))
        return tuple(problems)

    parsed: list[Mapping[str, Any]] = []
    names: list[str] = []
    level_allowed = {"name", "generator", "evaluator", "target_band"}
    for index, level in enumerate(levels):
        path = f"/levels/{index}"
        if not isinstance(level, Mapping):
            problems.append(DifficultyProblem("type", "level must be an object", path))
            continue
        for key in sorted(set(level) - level_allowed):
            problems.append(DifficultyProblem("unknown_key", "unknown field", f"{path}/{key}"))
        for key in sorted(level_allowed - set(level)):
            problems.append(DifficultyProblem("required", "field is required", f"{path}/{key}"))
        name = level.get("name")
        if name not in LEVEL_NAMES:
            problems.append(DifficultyProblem("enum", f"must be one of {', '.join(LEVEL_NAMES)}", f"{path}/name"))
        elif name in names:
            problems.append(DifficultyProblem("unique", "level names must be unique", f"{path}/name"))
        else:
            names.append(name)
        problems.extend(
            _validate_knob_map(
                level.get("generator"),
                GENERATOR_KNOBS,
                f"{path}/generator",
                require_instance_count=True,
            )
        )
        problems.extend(_validate_knob_map(level.get("evaluator"), EVALUATOR_KNOBS, f"{path}/evaluator"))
        problems.extend(_validate_target_band(level.get("target_band"), f"{path}/target_band"))
        parsed.append(level)

    valid_names = [name for name in names if name in LEVEL_NAMES]
    if valid_names != sorted(valid_names, key=LEVEL_NAMES.index):
        problems.append(DifficultyProblem("order", "levels must be ordered from easy to frontier", "/levels"))

    if parsed and all(isinstance(level.get("generator"), Mapping) for level in parsed):
        expected = set(parsed[0]["generator"])
        for index, level in enumerate(parsed[1:], 1):
            if set(level["generator"]) != expected:
                problems.append(DifficultyProblem("keys", "all levels must define the same generator knobs", f"/levels/{index}/generator"))
    if parsed and all(isinstance(level.get("evaluator"), Mapping) for level in parsed):
        expected = set(parsed[0]["evaluator"])
        for index, level in enumerate(parsed[1:], 1):
            if set(level["evaluator"]) != expected:
                problems.append(DifficultyProblem("keys", "all levels must define the same evaluator knobs", f"/levels/{index}/evaluator"))

    for index in range(1, len(parsed)):
        previous = parsed[index - 1]
        current = parsed[index]
        any_stricter = False
        comparable = True
        for section, specs in (("generator", GENERATOR_KNOBS), ("evaluator", EVALUATOR_KNOBS)):
            before = previous.get(section)
            after = current.get(section)
            if not isinstance(before, Mapping) or not isinstance(after, Mapping) or set(before) != set(after):
                comparable = False
                continue
            for key in before:
                left = before[key]
                right = after[key]
                if key not in specs or not _is_number(left) or not _is_number(right):
                    comparable = False
                    continue
                direction = specs[key].harder_when
                wrong = right < left if direction == "higher" else right > left
                if wrong:
                    problems.append(
                        DifficultyProblem(
                            "monotonic",
                            f"{key} must not become easier at a harder level",
                            f"/levels/{index}/{section}/{key}",
                        )
                    )
                if (direction == "higher" and right > left) or (direction == "lower" and right < left):
                    any_stricter = True
        if comparable and not any_stricter:
            problems.append(
                DifficultyProblem(
                    "cosmetic_level",
                    "adjacent levels must change at least one generator or evaluator control",
                    f"/levels/{index}",
                )
            )
    return tuple(problems)


def validate_profile_definition_v2(profile: Any) -> tuple[DifficultyProblem, ...]:
    """Validate a purpose-separated v2 profile.

    Structural monotonicity is checked independently for per-episode challenge
    and evaluation power.  Benchmark sampling is range-checked but intentionally
    excluded from monotonic difficulty evidence: more benchmark instances improve
    coverage, not the challenge presented in a single episode.
    """

    problems: list[DifficultyProblem] = []
    required = {"schema_version", "id", "version", "levels"}
    allowed = required | {"description"}
    if not isinstance(profile, Mapping):
        return (DifficultyProblem("type", "difficulty profile must be an object"),)
    for key in sorted(set(profile) - allowed):
        problems.append(DifficultyProblem("unknown_key", "unknown field", f"/{key}"))
    for key in sorted(required - set(profile)):
        problems.append(DifficultyProblem("required", "field is required", f"/{key}"))
    if profile.get("schema_version") != DIFFICULTY_SCHEMA_VERSION_V2:
        problems.append(
            DifficultyProblem(
                "schema_version",
                f"must be {DIFFICULTY_SCHEMA_VERSION_V2!r}",
                "/schema_version",
            )
        )
    profile_id = profile.get("id")
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if (
        not isinstance(profile_id, str)
        or not profile_id
        or any(ch not in safe for ch in profile_id)
    ):
        problems.append(DifficultyProblem("format", "must be a nonempty safe identifier", "/id"))
    version = profile.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        problems.append(DifficultyProblem("range", "must be a positive integer", "/version"))
    if "description" in profile and not isinstance(profile["description"], str):
        problems.append(DifficultyProblem("type", "must be a string", "/description"))
    levels = profile.get("levels")
    if not isinstance(levels, Sequence) or isinstance(levels, (str, bytes, bytearray)) or not levels:
        problems.append(DifficultyProblem("type", "must be a nonempty array", "/levels"))
        return tuple(problems)

    parsed: list[Mapping[str, Any]] = []
    names: list[str] = []
    level_required = {
        "name",
        "challenge",
        "evaluation_power",
        "benchmark_sampling",
        "target_band",
    }
    for index, level in enumerate(levels):
        path = f"/levels/{index}"
        if not isinstance(level, Mapping):
            problems.append(DifficultyProblem("type", "level must be an object", path))
            continue
        for key in sorted(set(level) - level_required):
            problems.append(DifficultyProblem("unknown_key", "unknown field", f"{path}/{key}"))
        for key in sorted(level_required - set(level)):
            problems.append(DifficultyProblem("required", "field is required", f"{path}/{key}"))
        name = level.get("name")
        if name not in LEVEL_NAMES:
            problems.append(DifficultyProblem("enum", f"must be one of {', '.join(LEVEL_NAMES)}", f"{path}/name"))
        elif name in names:
            problems.append(DifficultyProblem("unique", "level names must be unique", f"{path}/name"))
        else:
            names.append(name)
        problems.extend(_validate_knob_map(level.get("challenge"), CHALLENGE_KNOBS, f"{path}/challenge"))
        problems.extend(
            _validate_knob_map(
                level.get("evaluation_power"),
                EVALUATION_POWER_KNOBS,
                f"{path}/evaluation_power",
            )
        )
        problems.extend(
            _validate_knob_map(
                level.get("benchmark_sampling"),
                BENCHMARK_SAMPLING_KNOBS,
                f"{path}/benchmark_sampling",
                require_instance_count=True,
            )
        )
        problems.extend(_validate_target_band(level.get("target_band"), f"{path}/target_band"))
        parsed.append(level)

    valid_names = [name for name in names if name in LEVEL_NAMES]
    if valid_names != sorted(valid_names, key=LEVEL_NAMES.index):
        problems.append(DifficultyProblem("order", "levels must be ordered from easy to frontier", "/levels"))

    for section in ("challenge", "evaluation_power", "benchmark_sampling"):
        if parsed and all(isinstance(level.get(section), Mapping) for level in parsed):
            expected = set(parsed[0][section])
            for index, level in enumerate(parsed[1:], 1):
                if set(level[section]) != expected:
                    problems.append(
                        DifficultyProblem(
                            "keys",
                            f"all levels must define the same {section} knobs",
                            f"/levels/{index}/{section}",
                        )
                    )

    for index in range(1, len(parsed)):
        previous = parsed[index - 1]
        current = parsed[index]
        semantic_change = False
        comparable = True
        for section, specs, code in (
            ("challenge", CHALLENGE_KNOBS, "monotonic_challenge"),
            ("evaluation_power", EVALUATION_POWER_KNOBS, "monotonic_evaluation_power"),
        ):
            before = previous.get(section)
            after = current.get(section)
            if not isinstance(before, Mapping) or not isinstance(after, Mapping) or set(before) != set(after):
                comparable = False
                continue
            for key in before:
                left = before[key]
                right = after[key]
                if key not in specs or not _is_number(left) or not _is_number(right):
                    comparable = False
                    continue
                direction = specs[key].harder_when
                wrong = right < left if direction == "higher" else right > left
                if wrong:
                    problems.append(
                        DifficultyProblem(
                            code,
                            f"{key} must not weaken at a harder level",
                            f"/levels/{index}/{section}/{key}",
                        )
                    )
                if (direction == "higher" and right > left) or (direction == "lower" and right < left):
                    semantic_change = True
        if comparable and not semantic_change:
            problems.append(
                DifficultyProblem(
                    "cosmetic_level",
                    "adjacent levels must change challenge or evaluation semantics; sampling alone is not difficulty",
                    f"/levels/{index}",
                )
            )
    return tuple(problems)


def _profile_index(project: Mapping[str, Any]) -> dict[tuple[str, int], Mapping[str, Any]]:
    result: dict[tuple[str, int], Mapping[str, Any]] = {
        (BUILTIN_PROFILE_ID, BUILTIN_PROFILE_VERSION): _BUILTIN_PROFILE
    }
    profiles = project.get("difficulty_profiles", [])
    if profiles is None:
        profiles = []
    if not isinstance(profiles, Sequence) or isinstance(profiles, (str, bytes, bytearray)):
        raise ValueError("difficulty_profiles must be an array")
    for index, profile in enumerate(profiles):
        issues = validate_profile_definition(profile)
        if issues:
            first = issues[0]
            raise ValueError(f"invalid difficulty profile at /difficulty_profiles/{index}{first.path}: {first.message}")
        key = (profile["id"], profile["version"])
        if key in result:
            raise ValueError(f"duplicate or reserved difficulty profile {key[0]!r} version {key[1]}")
        result[key] = profile
    return result


def validate_difficulty_selection(
    selection: Any,
    profiles: Mapping[tuple[str, int], Mapping[str, Any]],
) -> tuple[DifficultyProblem, ...]:
    problems: list[DifficultyProblem] = []
    required = {"profile_id", "profile_version", "level"}
    allowed = required | {"generator_overrides", "evaluator_overrides"}
    if not isinstance(selection, Mapping):
        return (DifficultyProblem("type", "difficulty selection must be an object"),)
    for key in sorted(set(selection) - allowed):
        problems.append(DifficultyProblem("unknown_key", "unknown field", f"/{key}"))
    for key in sorted(required - set(selection)):
        problems.append(DifficultyProblem("required", "field is required", f"/{key}"))
    profile_id = selection.get("profile_id")
    profile_version = selection.get("profile_version")
    level_name = selection.get("level")
    if not isinstance(profile_id, str) or not profile_id:
        problems.append(DifficultyProblem("type", "must be a nonempty string", "/profile_id"))
    if not isinstance(profile_version, int) or isinstance(profile_version, bool) or profile_version < 1:
        problems.append(DifficultyProblem("range", "must be a positive integer", "/profile_version"))
    if level_name not in LEVEL_NAMES:
        problems.append(DifficultyProblem("enum", f"must be one of {', '.join(LEVEL_NAMES)}", "/level"))
    key = (profile_id, profile_version)
    profile = (
        profiles.get(key)
        if isinstance(profile_id, str)
        and isinstance(profile_version, int)
        and not isinstance(profile_version, bool)
        else None
    )
    if profile is None and isinstance(profile_id, str) and isinstance(profile_version, int):
        problems.append(DifficultyProblem("reference", "referenced difficulty profile/version does not exist", "/profile_id"))
    level: Mapping[str, Any] | None = None
    if profile is not None:
        level = next((item for item in profile["levels"] if item["name"] == level_name), None)
        if level is None and level_name in LEVEL_NAMES:
            problems.append(DifficultyProblem("reference", "selected level is not defined by the profile", "/level"))
    for field, specs, section in (
        ("generator_overrides", GENERATOR_KNOBS, "generator"),
        ("evaluator_overrides", EVALUATOR_KNOBS, "evaluator"),
    ):
        if field not in selection:
            continue
        problems.extend(_validate_knob_map(selection[field], specs, f"/{field}"))
        if level is not None and isinstance(selection[field], Mapping):
            for knob in selection[field]:
                if knob in specs and knob not in level[section]:
                    problems.append(
                        DifficultyProblem(
                            "reference",
                            "override is not defined by the selected profile",
                            f"/{field}/{knob}",
                        )
                    )
    return tuple(problems)


def difficulty_profile_index(project: Mapping[str, Any]) -> Mapping[tuple[str, int], Mapping[str, Any]]:
    """Return the validated profile index, including the built-in profile."""

    return MappingProxyType(_profile_index(project))


def _find_task(project: Mapping[str, Any], task_or_id: Mapping[str, Any] | str) -> Mapping[str, Any]:
    if isinstance(task_or_id, Mapping):
        return task_or_id
    if not isinstance(task_or_id, str):
        raise TypeError("task_or_id must be a task object or task id")
    tasks = project.get("tasks", [])
    for task in tasks if isinstance(tasks, Sequence) else ():
        if isinstance(task, Mapping) and task.get("id") == task_or_id:
            return task
    raise KeyError(f"unknown task id {task_or_id!r}")


def resolve_task_difficulty(
    project: Mapping[str, Any],
    task_or_id: Mapping[str, Any] | str,
    override: str | None = None,
) -> ResolvedDifficulty | None:
    """Resolve a task selection (and optional CLI level override) deterministically."""

    task = _find_task(project, task_or_id)
    raw = task.get("difficulty")
    if raw is None and override is None:
        return None
    if override is not None and override not in LEVEL_NAMES:
        raise ValueError(f"difficulty override must be one of {', '.join(LEVEL_NAMES)}")
    if raw is None:
        selection: dict[str, Any] = {
            "profile_id": BUILTIN_PROFILE_ID,
            "profile_version": BUILTIN_PROFILE_VERSION,
            "level": override,
        }
    elif isinstance(raw, Mapping):
        selection = _json_copy(raw)
        if override is not None:
            selection["level"] = override
    else:
        raise ValueError("task difficulty must be an object")

    profiles = _profile_index(project)
    problems = validate_difficulty_selection(selection, profiles)
    if problems:
        first = problems[0]
        raise ValueError(f"invalid task difficulty at {first.path or '/'}: {first.message}")
    profile = profiles[(selection["profile_id"], selection["profile_version"])]
    level = next(item for item in profile["levels"] if item["name"] == selection["level"])
    generator = dict(level["generator"])
    evaluator = dict(level["evaluator"])
    generator.update(selection.get("generator_overrides", {}))
    evaluator.update(selection.get("evaluator_overrides", {}))
    target_band = TargetBand.from_mapping(level["target_band"])
    resolved_payload = {
        "schema_version": DIFFICULTY_SCHEMA_VERSION,
        "profile_id": selection["profile_id"],
        "profile_version": selection["profile_version"],
        "level": selection["level"],
        "generator": generator,
        "evaluator": evaluator,
        "target_band": target_band.to_dict(),
    }
    resolution_id = "difficulty_" + hashlib.sha256(_canonical_bytes(resolved_payload)).hexdigest()
    return ResolvedDifficulty(
        profile_id=selection["profile_id"],
        profile_version=selection["profile_version"],
        level=selection["level"],
        generator=MappingProxyType(dict(sorted(generator.items()))),
        evaluator=MappingProxyType(dict(sorted(evaluator.items()))),
        target_band=target_band,
        resolution_id=resolution_id,
    )


def apply_difficulty_override(project: Mapping[str, Any], level: str) -> dict[str, Any]:
    """Return a deep-copied project with a CLI level override applied to tasks.

    Tasks without an explicit profile opt into the built-in ``core`` profile.
    ``instances`` is synchronized with the resolved generator parameter so the
    existing builder input cannot silently disagree with the difficulty plan.
    """

    if level not in LEVEL_NAMES:
        raise ValueError(f"difficulty override must be one of {', '.join(LEVEL_NAMES)}")
    result = _json_copy(project)
    if not isinstance(result, dict) or not isinstance(result.get("tasks"), list):
        raise ValueError("project must be an object with a tasks array")
    _profile_index(result)
    for task in result["tasks"]:
        if not isinstance(task, dict):
            raise ValueError("each task must be an object")
        raw = task.get("difficulty")
        if raw is None:
            task["difficulty"] = {
                "profile_id": BUILTIN_PROFILE_ID,
                "profile_version": BUILTIN_PROFILE_VERSION,
                "level": level,
            }
        elif isinstance(raw, dict):
            raw["level"] = level
        else:
            raise ValueError("task difficulty must be an object")
        resolved = resolve_task_difficulty(result, task)
        assert resolved is not None
        task["instances"] = int(resolved.generator["instance_count"])
    return result


def make_consumption_manifest(
    resolved: ResolvedDifficulty,
    consumed_generator: Mapping[str, int | float],
    consumed_evaluator: Mapping[str, int | float],
) -> dict[str, Any]:
    """Create an author-side proof that exact resolved settings were consumed."""

    generator = _json_copy(dict(consumed_generator))
    evaluator = _json_copy(dict(consumed_evaluator))
    if _canonical_bytes(generator) != _canonical_bytes(dict(resolved.generator)):
        raise ValueError("consumed generator parameters do not exactly match resolved difficulty")
    if _canonical_bytes(evaluator) != _canonical_bytes(dict(resolved.evaluator)):
        raise ValueError("consumed evaluator parameters do not exactly match resolved difficulty")
    return {
        "schema_version": CONSUMPTION_SCHEMA_VERSION,
        "resolution_id": resolved.resolution_id,
        "profile_id": resolved.profile_id,
        "profile_version": resolved.profile_version,
        "level": resolved.level,
        "generator": generator,
        "evaluator": evaluator,
    }


def verify_consumption_manifest(resolved: ResolvedDifficulty, manifest: Any) -> bool:
    """Return whether a builder manifest exactly proves consumption."""

    if not isinstance(manifest, Mapping):
        return False
    expected_keys = {
        "schema_version",
        "resolution_id",
        "profile_id",
        "profile_version",
        "level",
        "generator",
        "evaluator",
    }
    if set(manifest) != expected_keys:
        return False
    expected = make_consumption_manifest(resolved, resolved.generator, resolved.evaluator)
    try:
        return _canonical_bytes(manifest) == _canonical_bytes(expected)
    except (TypeError, ValueError):
        return False


def _fingerprint(prefix: str, value: Any) -> str:
    return prefix + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def resolve_difficulty_v2(
    level: str,
    *,
    profile: Mapping[str, Any] | None = None,
    challenge_overrides: Mapping[str, int | float] | None = None,
    evaluation_power_overrides: Mapping[str, int | float] | None = None,
    benchmark_sampling_overrides: Mapping[str, int | float] | None = None,
) -> ResolvedDifficultyV2:
    """Resolve a purpose-separated difficulty level.

    This API is intentionally independent of the legacy project schema so a
    caller can adopt v2 without silently interpreting ``instance_count`` as an
    episode-level challenge knob.
    """

    selected_profile = _BUILTIN_PROFILE_V2 if profile is None else profile
    problems = validate_profile_definition_v2(selected_profile)
    if problems:
        first = problems[0]
        raise ValueError(f"invalid v2 difficulty profile at {first.path or '/'}: {first.message}")
    if level not in LEVEL_NAMES:
        raise ValueError(f"difficulty level must be one of {', '.join(LEVEL_NAMES)}")
    selected = next(
        (item for item in selected_profile["levels"] if item["name"] == level),
        None,
    )
    if selected is None:
        raise ValueError(f"difficulty profile does not define level {level!r}")

    supplied = (
        ("challenge", challenge_overrides, CHALLENGE_KNOBS),
        ("evaluation_power", evaluation_power_overrides, EVALUATION_POWER_KNOBS),
        ("benchmark_sampling", benchmark_sampling_overrides, BENCHMARK_SAMPLING_KNOBS),
    )
    for section, overrides, specs in supplied:
        if overrides is None:
            continue
        override_problems = _validate_knob_map(overrides, specs, f"/{section}_overrides")
        if override_problems:
            first = override_problems[0]
            raise ValueError(f"invalid v2 difficulty override at {first.path}: {first.message}")
        undefined = set(overrides) - set(selected[section])
        if undefined:
            key = sorted(undefined)[0]
            raise ValueError(f"override {section}.{key} is not defined by the selected profile")

    base_challenge = dict(selected["challenge"])
    base_evaluation = dict(selected["evaluation_power"])
    base_sampling = dict(selected["benchmark_sampling"])
    challenge = dict(base_challenge)
    evaluation = dict(base_evaluation)
    sampling = dict(base_sampling)
    challenge.update(challenge_overrides or {})
    evaluation.update(evaluation_power_overrides or {})
    sampling.update(benchmark_sampling_overrides or {})

    semantic_overrides = tuple(
        sorted(
            [
                *(f"challenge.{key}" for key, value in challenge.items() if value != base_challenge[key]),
                *(
                    f"evaluation_power.{key}"
                    for key, value in evaluation.items()
                    if value != base_evaluation[key]
                ),
            ]
        )
    )
    sampling_overrides = tuple(
        sorted(
            f"benchmark_sampling.{key}"
            for key, value in sampling.items()
            if value != base_sampling[key]
        )
    )
    identity = {
        "schema_version": DIFFICULTY_SCHEMA_VERSION_V2,
        "profile_id": selected_profile["id"],
        "profile_version": selected_profile["version"],
        "level": level,
    }
    base_semantic_payload = {
        **identity,
        "challenge": base_challenge,
        "evaluation_power": base_evaluation,
    }
    semantic_payload = {
        **identity,
        "challenge": challenge,
        "evaluation_power": evaluation,
    }
    profile_semantic_id = _fingerprint("difficulty_semantic_", base_semantic_payload)
    semantic_id = _fingerprint("difficulty_semantic_", semantic_payload)
    sampling_id = _fingerprint(
        "difficulty_sampling_",
        {**identity, "benchmark_sampling": sampling},
    )
    target_band = TargetBand.from_mapping(selected["target_band"])
    resolution_id = _fingerprint(
        "difficulty_v2_",
        {
            **identity,
            "semantic_id": semantic_id,
            "sampling_id": sampling_id,
            "target_band": target_band.to_dict(),
        },
    )
    return ResolvedDifficultyV2(
        profile_id=selected_profile["id"],
        profile_version=selected_profile["version"],
        level=level,
        challenge=MappingProxyType(dict(sorted(challenge.items()))),
        evaluation_power=MappingProxyType(dict(sorted(evaluation.items()))),
        benchmark_sampling=MappingProxyType(dict(sorted(sampling.items()))),
        target_band=target_band,
        profile_semantic_id=profile_semantic_id,
        semantic_id=semantic_id,
        sampling_id=sampling_id,
        resolution_id=resolution_id,
        semantic_overrides=semantic_overrides,
        sampling_overrides=sampling_overrides,
        baseline_calibration_invalidated=semantic_id != profile_semantic_id,
    )


def assess_calibration_validity(
    resolved: ResolvedDifficultyV2,
    calibrated_semantic_id: str | None,
) -> CalibrationValidity:
    """Assess whether a calibration record is reusable for a resolution."""

    if calibrated_semantic_id is None:
        return CalibrationValidity(
            status="uncalibrated",
            valid=False,
            calibrated_semantic_id=None,
            resolved_semantic_id=resolved.semantic_id,
        )
    if not isinstance(calibrated_semantic_id, str) or not calibrated_semantic_id:
        raise ValueError("calibrated_semantic_id must be a nonempty string or None")
    if calibrated_semantic_id == resolved.semantic_id:
        return CalibrationValidity(
            status="valid",
            valid=True,
            calibrated_semantic_id=calibrated_semantic_id,
            resolved_semantic_id=resolved.semantic_id,
        )
    reasons = resolved.semantic_overrides or ("semantic_definition_changed",)
    return CalibrationValidity(
        status="invalidated",
        valid=False,
        calibrated_semantic_id=calibrated_semantic_id,
        resolved_semantic_id=resolved.semantic_id,
        invalidated_by=tuple(reasons),
    )


def derive_task_calibration_id(
    resolved: ResolvedDifficultyV2,
    *,
    task_id: str,
    task_build_id: str,
) -> str:
    """Bind difficulty semantics to one exact compiled task build.

    ``ResolvedDifficultyV2.semantic_id`` deliberately excludes benchmark
    sampling, but it also cannot identify task code, data, or evaluator bytes.
    Persisted agent calibration must therefore use this task-bound identity.
    Any compiler, protocol, generator, evaluator, or frozen-data change that
    changes ``task_build_id`` invalidates the resulting ID.
    """

    if not isinstance(resolved, ResolvedDifficultyV2):
        raise TypeError("resolved must be ResolvedDifficultyV2")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a nonempty string")
    if (
        not isinstance(task_build_id, str)
        or re.fullmatch(r"task-build_[0-9a-f]{64}", task_build_id) is None
    ):
        raise ValueError("task_build_id must be a content-derived task-build_<sha256> ID")
    return _fingerprint(
        "task_calibration_",
        {
            "schema_version": TASK_CALIBRATION_ID_VERSION,
            "difficulty_semantic_id": resolved.semantic_id,
            "task_id": task_id,
            "task_build_id": task_build_id,
        },
    )


def assess_task_calibration_validity(
    resolved: ResolvedDifficultyV2,
    calibrated_semantic_id: str | None,
    *,
    task_id: str,
    task_build_id: str,
) -> CalibrationValidity:
    """Validate persisted calibration against difficulty and task bytes."""

    expected = derive_task_calibration_id(
        resolved,
        task_id=task_id,
        task_build_id=task_build_id,
    )
    if calibrated_semantic_id is None:
        return CalibrationValidity(
            status="uncalibrated",
            valid=False,
            calibrated_semantic_id=None,
            resolved_semantic_id=expected,
        )
    if not isinstance(calibrated_semantic_id, str) or not calibrated_semantic_id:
        raise ValueError("calibrated_semantic_id must be a nonempty string or None")
    if calibrated_semantic_id == expected:
        return CalibrationValidity(
            status="valid",
            valid=True,
            calibrated_semantic_id=calibrated_semantic_id,
            resolved_semantic_id=expected,
        )
    reasons = resolved.semantic_overrides or ("task_build_or_semantics_changed",)
    return CalibrationValidity(
        status="invalidated",
        valid=False,
        calibrated_semantic_id=calibrated_semantic_id,
        resolved_semantic_id=expected,
        invalidated_by=tuple(reasons),
    )


def derive_purpose_seed(
    root_seed: int | str | bytes,
    *,
    purpose: str,
    coordinates: Sequence[str | int] = (),
    bits: int = 64,
) -> int:
    """Derive a deterministic, domain-separated seed.

    A mandatory purpose prevents generator, hidden-test, mutation, and sampling
    streams from accidentally sharing random state.  Coordinates should identify
    immutable locations such as task id, variant id, and replicate index.
    """

    if isinstance(root_seed, bool) or not isinstance(root_seed, (int, str, bytes)):
        raise TypeError("root_seed must be an integer, string, or bytes")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError("purpose must be a nonempty string")
    if not isinstance(bits, int) or isinstance(bits, bool) or bits < 32 or bits > 256 or bits % 8:
        raise ValueError("bits must be a multiple of 8 between 32 and 256")
    if isinstance(coordinates, (str, bytes, bytearray)) or not isinstance(coordinates, Sequence):
        raise TypeError("coordinates must be a sequence of strings and integers")
    normalized_coordinates: list[str | int] = []
    for index, coordinate in enumerate(coordinates):
        if isinstance(coordinate, bool) or not isinstance(coordinate, (str, int)):
            raise TypeError(f"coordinate {index} must be a string or integer")
        normalized_coordinates.append(coordinate)
    if isinstance(root_seed, bytes):
        normalized_root: Mapping[str, Any] = {"encoding": "hex", "value": root_seed.hex()}
    elif isinstance(root_seed, int):
        normalized_root = {"encoding": "integer", "value": str(root_seed)}
    else:
        normalized_root = {"encoding": "utf-8", "value": root_seed}
    digest = hashlib.sha256(
        _canonical_bytes(
            {
                "schema_version": RNG_DERIVATION_VERSION,
                "root_seed": normalized_root,
                "purpose": purpose,
                "coordinates": normalized_coordinates,
            }
        )
    ).digest()
    return int.from_bytes(digest[: bits // 8], "big")


def deterministic_rng(
    root_seed: int | str | bytes,
    *,
    purpose: str,
    coordinates: Sequence[str | int] = (),
) -> random.Random:
    """Return an isolated RNG seeded through :func:`derive_purpose_seed`."""

    return random.Random(
        derive_purpose_seed(root_seed, purpose=purpose, coordinates=coordinates, bits=256)
    )


_AGENT_SYSTEM_REQUIRED_FIELDS = {
    "provider",
    "model_revision",
    "harness_commit",
    "tool_policy",
    "budgets",
    "network_policy",
    "evaluation_date",
}


def derive_agent_system_id(descriptor: Mapping[str, Any]) -> str:
    """Hash a fully pinned agent-system descriptor.

    The descriptor must pin the model revision, harness commit, tool policy,
    budgets, network policy, and evaluation date.  Additional JSON fields are
    retained in the hash, allowing callers to pin provider and environment data.
    """

    if not isinstance(descriptor, Mapping):
        raise TypeError("agent system descriptor must be an object")
    missing = _AGENT_SYSTEM_REQUIRED_FIELDS - set(descriptor)
    if missing:
        raise ValueError(f"agent system descriptor is missing {sorted(missing)[0]!r}")
    for field in ("provider", "model_revision", "harness_commit"):
        if not isinstance(descriptor[field], str) or not descriptor[field].strip():
            raise ValueError(f"agent system {field} must be a nonempty string")
    if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", descriptor["harness_commit"]) is None:
        raise ValueError(
            "agent system harness_commit must be an exact 40- or 64-character "
            "lowercase hexadecimal commit"
        )
    if not isinstance(descriptor["tool_policy"], Mapping) or not descriptor["tool_policy"]:
        raise ValueError("agent system tool_policy must be a nonempty object")
    budgets = descriptor["budgets"]
    if not isinstance(budgets, Mapping) or not budgets:
        raise ValueError("agent system budgets must be a nonempty object")
    for key, value in budgets.items():
        if not isinstance(key, str) or not key or not _is_number(value) or value < 0:
            raise ValueError("agent system budgets must map nonempty names to finite nonnegative numbers")
    network = descriptor["network_policy"]
    if not isinstance(network, Mapping) or not isinstance(network.get("enabled"), bool):
        raise ValueError("agent system network_policy must be an object with boolean 'enabled'")
    evaluation_date = descriptor["evaluation_date"]
    if not isinstance(evaluation_date, str):
        raise ValueError("agent system evaluation_date must be an ISO date")
    try:
        date.fromisoformat(evaluation_date)
    except ValueError as exc:
        raise ValueError("agent system evaluation_date must be an ISO date") from exc
    try:
        canonical = _canonical_bytes(
            {
                "schema_version": "paper2ale.agent-system/v1",
                "descriptor": dict(descriptor),
            }
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("agent system descriptor must contain only finite JSON values") from exc
    return "agent_system_" + hashlib.sha256(canonical).hexdigest()


def pin_agent_system(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical descriptor envelope with its content-derived id."""

    copied = _json_copy(dict(descriptor))
    return {
        "schema_version": "paper2ale.agent-system/v1",
        "agent_system_id": derive_agent_system_id(copied),
        "descriptor": copied,
    }


def summarize_scores(scores: Iterable[int | float], confidence: float = 0.95) -> ScoreSummary:
    """Summarize finite numeric scores without assuming a particular scale."""

    if not _is_number(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be a finite number strictly between 0 and 1")
    values = list(scores)
    if not values:
        raise ValueError("at least one score is required")
    for index, value in enumerate(values):
        if not _is_number(value):
            raise ValueError(f"score {index} must be a finite number")
    numeric = [float(value) for value in values]
    mean_value = fmean(numeric)
    standard_deviation = stdev(numeric) if len(numeric) > 1 else 0.0
    z = NormalDist().inv_cdf(0.5 + float(confidence) / 2)
    half_width = z * standard_deviation / math.sqrt(len(numeric))
    return ScoreSummary(
        trials=len(numeric),
        mean=mean_value,
        median=float(median(numeric)),
        minimum=min(numeric),
        maximum=max(numeric),
        standard_deviation=standard_deviation,
        confidence=float(confidence),
        interval_lower=mean_value - half_width,
        interval_upper=mean_value + half_width,
    )


def _wilson_interval(passed: int, trials: int, confidence: float) -> tuple[float, float]:
    if trials < 1:
        raise ValueError("trials must be positive")
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    rate = passed / trials
    denominator = 1 + z * z / trials
    center = (rate + z * z / (2 * trials)) / denominator
    half_width = z * math.sqrt(
        rate * (1 - rate) / trials + z * z / (4 * trials * trials)
    ) / denominator
    return max(0.0, center - half_width), min(1.0, center + half_width)


def summarize_calibration(
    outcomes: Iterable[bool | Mapping[str, Any]],
    target_band: TargetBand | Mapping[str, Any],
) -> CalibrationSummary:
    """Summarize binary trials with a Wilson confidence interval."""

    if isinstance(target_band, TargetBand):
        band = target_band
    else:
        band_problems = _validate_target_band(target_band, "/target_band")
        if band_problems:
            raise ValueError(band_problems[0].message)
        band = TargetBand.from_mapping(target_band)
    band_problems = _validate_target_band(band.to_dict(), "/target_band")
    if band_problems:
        raise ValueError(band_problems[0].message)
    passed_values: list[bool] = []
    score_values: list[float] = []
    scored_count = 0
    agent_system_ids: set[str] = set()
    for index, outcome in enumerate(outcomes):
        value = outcome.get("passed") if isinstance(outcome, Mapping) else outcome
        if not isinstance(value, bool):
            raise ValueError(f"outcome {index} must be a boolean or an object with boolean 'passed'")
        passed_values.append(value)
        if isinstance(outcome, Mapping):
            if "agent_system_id" in outcome:
                agent_system_id = outcome["agent_system_id"]
                if not isinstance(agent_system_id, str) or not agent_system_id:
                    raise ValueError(f"outcome {index} agent_system_id must be a nonempty string")
                agent_system_ids.add(agent_system_id)
            if "score" in outcome:
                score = outcome["score"]
                if not _is_number(score):
                    raise ValueError(f"outcome {index} score must be a finite number")
                score_values.append(float(score))
                scored_count += 1
    if not passed_values:
        raise ValueError("at least one calibration outcome is required")
    if len(agent_system_ids) > 1:
        raise ValueError(
            "calibration outcomes contain multiple agent_system_id values; "
            "use summarize_calibration_by_agent_system instead of pooling"
        )
    if 0 < scored_count < len(passed_values):
        raise ValueError("calibration outcomes must either all include score or all omit it")
    trials = len(passed_values)
    passed = sum(passed_values)
    rate = passed / trials
    lower, upper = _wilson_interval(passed, trials, band.confidence)
    if trials < band.min_trials:
        status = "insufficient_trials"
    elif upper < band.lower:
        status = "too_hard"
    elif lower > band.upper:
        status = "too_easy"
    elif lower >= band.lower and upper <= band.upper:
        status = "calibrated"
    else:
        status = "inconclusive"
    return CalibrationSummary(
        trials=trials,
        passed=passed,
        pass_rate=rate,
        confidence=band.confidence,
        interval_lower=lower,
        interval_upper=upper,
        target_lower=band.lower,
        target_upper=band.upper,
        min_trials=band.min_trials,
        status=status,
        meets_target=status == "calibrated",
        score_summary=(summarize_scores(score_values, band.confidence) if score_values else None),
    )


def summarize_calibration_by_agent_system(
    trials: Iterable[Mapping[str, Any]],
    target_band: TargetBand | Mapping[str, Any],
    *,
    expected_semantic_id: str | None = None,
    require_scores: bool = True,
) -> tuple[AgentSystemCalibrationSummary, ...]:
    """Group calibration trials by pinned agent system; never pool systems.

    Each trial must contain ``agent_system_id`` and ``passed``.  V2 calibration
    uses numeric scores by default so pass/fail threshold effects remain visible.
    When ``expected_semantic_id`` is supplied, every trial must carry that exact
    semantic id; stale trials are rejected rather than silently pooled.
    """

    if expected_semantic_id is not None and (
        not isinstance(expected_semantic_id, str) or not expected_semantic_id
    ):
        raise ValueError("expected_semantic_id must be a nonempty string or None")
    grouped: dict[str, list[dict[str, Any]]] = {}
    semantic_ids: dict[str, set[str]] = {}
    for index, trial in enumerate(trials):
        if not isinstance(trial, Mapping):
            raise ValueError(f"trial {index} must be an object")
        agent_system_id = trial.get("agent_system_id")
        if not isinstance(agent_system_id, str) or not agent_system_id:
            raise ValueError(f"trial {index} must include a nonempty agent_system_id")
        passed = trial.get("passed")
        if not isinstance(passed, bool):
            raise ValueError(f"trial {index} must include boolean passed")
        score = trial.get("score")
        if require_scores and not _is_number(score):
            raise ValueError(f"trial {index} must include a finite numeric score")
        if score is not None and not _is_number(score):
            raise ValueError(f"trial {index} score must be a finite number")
        semantic_id = trial.get("semantic_id")
        if expected_semantic_id is not None:
            if semantic_id != expected_semantic_id:
                raise ValueError(
                    f"trial {index} semantic_id does not match the resolved difficulty; "
                    "calibration is invalidated"
                )
        elif semantic_id is not None and (
            not isinstance(semantic_id, str) or not semantic_id
        ):
            raise ValueError(f"trial {index} semantic_id must be a nonempty string")
        copied = {"passed": passed, "agent_system_id": agent_system_id}
        if score is not None:
            copied["score"] = score
        grouped.setdefault(agent_system_id, []).append(copied)
        if semantic_id is not None:
            semantic_ids.setdefault(agent_system_id, set()).add(semantic_id)
    if not grouped:
        raise ValueError("at least one calibration trial is required")

    result: list[AgentSystemCalibrationSummary] = []
    for agent_system_id in sorted(grouped):
        ids = semantic_ids.get(agent_system_id, set())
        if len(ids) > 1:
            raise ValueError(
                f"agent system {agent_system_id!r} has trials from multiple semantic_id values"
            )
        summary = summarize_calibration(grouped[agent_system_id], target_band)
        result.append(
            AgentSystemCalibrationSummary(
                agent_system_id=agent_system_id,
                semantic_id=next(iter(ids), expected_semantic_id),
                calibration=summary,
            )
        )
    return tuple(result)


def check_cross_level_behavioral_monotonicity(
    trials: Iterable[Mapping[str, Any]],
    *,
    confidence: float = 0.95,
    min_trials_per_level: int = 20,
    compare_scores: bool = False,
) -> tuple[BehavioralMonotonicityReport, ...]:
    """Test observed cross-level ordering separately for each agent system.

    A violation is reported only when the harder level's Wilson interval lies
    entirely above the easier level's interval.  Non-overlap in the intended
    direction is ``supported``; overlap is ``inconclusive``.  This avoids
    claiming monotonic difficulty from noisy point estimates.
    """

    if not _is_number(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be a finite number strictly between 0 and 1")
    if (
        not isinstance(min_trials_per_level, int)
        or isinstance(min_trials_per_level, bool)
        or min_trials_per_level < 1
    ):
        raise ValueError("min_trials_per_level must be a positive integer")
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    semantics: dict[tuple[str, str], set[str]] = {}
    task_ids: set[str] = set()
    rows_without_task_id = 0
    for index, trial in enumerate(trials):
        if not isinstance(trial, Mapping):
            raise ValueError(f"trial {index} must be an object")
        agent_system_id = trial.get("agent_system_id")
        level = trial.get("level")
        passed = trial.get("passed")
        if not isinstance(agent_system_id, str) or not agent_system_id:
            raise ValueError(f"trial {index} must include a nonempty agent_system_id")
        if level not in LEVEL_NAMES:
            raise ValueError(f"trial {index} level must be one of {', '.join(LEVEL_NAMES)}")
        if not isinstance(passed, bool):
            raise ValueError(f"trial {index} must include boolean passed")
        if "score" in trial and not _is_number(trial["score"]):
            raise ValueError(f"trial {index} score must be a finite number")
        if compare_scores and "score" not in trial:
            raise ValueError(f"trial {index} must include score when compare_scores is enabled")
        if "task_id" in trial:
            task_id = trial["task_id"]
            if not isinstance(task_id, str) or not task_id:
                raise ValueError(f"trial {index} task_id must be a nonempty string")
            task_ids.add(task_id)
        else:
            rows_without_task_id += 1
        key = (agent_system_id, str(level))
        grouped.setdefault(key, []).append(trial)
        semantic_id = trial.get("semantic_id")
        if semantic_id is not None:
            if not isinstance(semantic_id, str) or not semantic_id:
                raise ValueError(f"trial {index} semantic_id must be a nonempty string")
            semantics.setdefault(key, set()).add(semantic_id)
    if not grouped:
        raise ValueError("at least one behavioral trial is required")
    if len(task_ids) > 1 or (task_ids and rows_without_task_id):
        raise ValueError(
            "behavioral monotonicity must be checked for exactly one task at a time"
        )
    for key, ids in semantics.items():
        if len(ids) > 1:
            raise ValueError(
                f"agent system {key[0]!r} level {key[1]!r} mixes semantic_id values"
            )

    agent_ids = sorted({key[0] for key in grouped})
    reports: list[BehavioralMonotonicityReport] = []
    for agent_system_id in agent_ids:
        observed_levels = [
            level for level in LEVEL_NAMES if (agent_system_id, level) in grouped
        ]
        comparisons: list[BehavioralMonotonicityComparison] = []
        for easier, harder in zip(observed_levels, observed_levels[1:]):
            easier_trials = grouped[(agent_system_id, easier)]
            harder_trials = grouped[(agent_system_id, harder)]
            easier_passed = sum(bool(item["passed"]) for item in easier_trials)
            harder_passed = sum(bool(item["passed"]) for item in harder_trials)
            easier_interval = _wilson_interval(easier_passed, len(easier_trials), float(confidence))
            harder_interval = _wilson_interval(harder_passed, len(harder_trials), float(confidence))
            if (
                len(easier_trials) < min_trials_per_level
                or len(harder_trials) < min_trials_per_level
            ):
                status = "insufficient_trials"
            elif harder_interval[0] > easier_interval[1]:
                status = "violated"
            elif harder_interval[1] <= easier_interval[0]:
                status = "supported"
            else:
                status = "inconclusive"

            score_status: str | None = None
            if compare_scores:
                easier_score = summarize_scores(
                    (item["score"] for item in easier_trials), float(confidence)
                )
                harder_score = summarize_scores(
                    (item["score"] for item in harder_trials), float(confidence)
                )
                if (
                    len(easier_trials) < min_trials_per_level
                    or len(harder_trials) < min_trials_per_level
                ):
                    score_status = "insufficient_trials"
                elif harder_score.interval_lower > easier_score.interval_upper:
                    score_status = "violated"
                elif harder_score.interval_upper <= easier_score.interval_lower:
                    score_status = "supported"
                else:
                    score_status = "inconclusive"
                if score_status == "violated":
                    status = "violated"
                elif status == "supported" and score_status != "supported":
                    status = "inconclusive"
            comparisons.append(
                BehavioralMonotonicityComparison(
                    agent_system_id=agent_system_id,
                    easier_level=easier,
                    harder_level=harder,
                    easier_trials=len(easier_trials),
                    harder_trials=len(harder_trials),
                    easier_pass_rate=easier_passed / len(easier_trials),
                    harder_pass_rate=harder_passed / len(harder_trials),
                    easier_interval=easier_interval,
                    harder_interval=harder_interval,
                    status=status,
                    score_status=score_status,
                )
            )
        statuses = {item.status for item in comparisons}
        if "violated" in statuses:
            report_status = "violated"
        elif comparisons and statuses == {"supported"}:
            report_status = "supported"
        else:
            report_status = "inconclusive"
        reports.append(
            BehavioralMonotonicityReport(
                agent_system_id=agent_system_id,
                confidence=float(confidence),
                min_trials_per_level=min_trials_per_level,
                status=report_status,
                comparisons=tuple(comparisons),
            )
        )
    return tuple(reports)


__all__ = [
    "AgentSystemCalibrationSummary",
    "BENCHMARK_SAMPLING_KNOBS",
    "BUILTIN_PROFILE_VERSION_V2",
    "BehavioralMonotonicityComparison",
    "BehavioralMonotonicityReport",
    "BUILTIN_PROFILE_ID",
    "BUILTIN_PROFILE_VERSION",
    "CALIBRATION_SCHEMA_VERSION",
    "CHALLENGE_KNOBS",
    "CONSUMPTION_SCHEMA_VERSION",
    "CalibrationSummary",
    "CalibrationValidity",
    "DIFFICULTY_SCHEMA_VERSION",
    "DIFFICULTY_SCHEMA_VERSION_V2",
    "DifficultyProblem",
    "EVALUATION_POWER_KNOBS",
    "EVALUATOR_KNOBS",
    "GENERATOR_KNOBS",
    "KnobSpec",
    "LEVEL_NAMES",
    "RNG_DERIVATION_VERSION",
    "ResolvedDifficulty",
    "ResolvedDifficultyV2",
    "ScoreSummary",
    "TargetBand",
    "TASK_CALIBRATION_ID_VERSION",
    "apply_difficulty_override",
    "assess_calibration_validity",
    "assess_task_calibration_validity",
    "builtin_profiles",
    "builtin_profiles_v2",
    "check_cross_level_behavioral_monotonicity",
    "derive_agent_system_id",
    "derive_purpose_seed",
    "derive_task_calibration_id",
    "deterministic_rng",
    "difficulty_profile_index",
    "make_consumption_manifest",
    "pin_agent_system",
    "resolve_difficulty_v2",
    "resolve_task_difficulty",
    "summarize_calibration",
    "summarize_calibration_by_agent_system",
    "summarize_scores",
    "validate_difficulty_selection",
    "validate_profile_definition",
    "validate_profile_definition_v2",
    "verify_consumption_manifest",
]
