"""Deterministic, enforceable difficulty profiles and calibration helpers.

Difficulty is deliberately represented as concrete generator and evaluator
parameters.  A level name by itself is never accepted: it must resolve through
a versioned profile to bounded numeric controls that a builder can attest it
consumed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from statistics import NormalDist
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


DIFFICULTY_SCHEMA_VERSION = "paper2ale.difficulty/v1"
CONSUMPTION_SCHEMA_VERSION = "paper2ale.difficulty-consumption/v1"
LEVEL_NAMES = ("easy", "medium", "hard", "frontier")
BUILTIN_PROFILE_ID = "core"
BUILTIN_PROFILE_VERSION = 1


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

    def to_dict(self) -> dict[str, Any]:
        return {
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
    for index, outcome in enumerate(outcomes):
        value = outcome.get("passed") if isinstance(outcome, Mapping) else outcome
        if not isinstance(value, bool):
            raise ValueError(f"outcome {index} must be a boolean or an object with boolean 'passed'")
        passed_values.append(value)
    if not passed_values:
        raise ValueError("at least one calibration outcome is required")
    trials = len(passed_values)
    passed = sum(passed_values)
    rate = passed / trials
    z = NormalDist().inv_cdf(0.5 + band.confidence / 2)
    denominator = 1 + z * z / trials
    center = (rate + z * z / (2 * trials)) / denominator
    half_width = z * math.sqrt(rate * (1 - rate) / trials + z * z / (4 * trials * trials)) / denominator
    lower = max(0.0, center - half_width)
    upper = min(1.0, center + half_width)
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
    )


__all__ = [
    "BUILTIN_PROFILE_ID",
    "BUILTIN_PROFILE_VERSION",
    "CONSUMPTION_SCHEMA_VERSION",
    "CalibrationSummary",
    "DIFFICULTY_SCHEMA_VERSION",
    "DifficultyProblem",
    "EVALUATOR_KNOBS",
    "GENERATOR_KNOBS",
    "KnobSpec",
    "LEVEL_NAMES",
    "ResolvedDifficulty",
    "TargetBand",
    "apply_difficulty_override",
    "builtin_profiles",
    "difficulty_profile_index",
    "make_consumption_manifest",
    "resolve_task_difficulty",
    "summarize_calibration",
    "validate_difficulty_selection",
    "validate_profile_definition",
    "verify_consumption_manifest",
]
