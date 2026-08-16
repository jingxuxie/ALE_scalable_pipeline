#!/usr/bin/env python3
"""Cross-platform release verification for the disordered-sector audit task."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np


sys.dont_write_bytecode = True
TASK_ROOT = Path(__file__).resolve().parents[1]
PARTICIPANT = TASK_ROOT / "participant"
GRADER = TASK_ROOT / "private" / "grader" / "grade.py"
RUNNER = TASK_ROOT / "private" / "grader" / "sandbox_runner.py"
ORACLE = TASK_ROOT / "author" / "oracle" / "generate.py"
REFERENCE = TASK_ROOT / "author" / "reference_solver" / "solution.py"
ALTERNATIVE = TASK_ROOT / "author" / "alternative_solver" / "solution.py"
MUTANT_BUILDER = TASK_ROOT / "private" / "mutants" / "build_mutants.py"
TASK_ID = "disordered-sector-audit-v1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GRADER_CORE = load_module("verify_grader_core", TASK_ROOT / "private" / "grader" / "core.py")
ORACLE_CORE = load_module("verify_oracle_core", TASK_ROOT / "private" / "trusted" / "oracle_core.py")


def environment(hash_seed: str = "0") -> dict[str, str]:
    result = dict(os.environ)
    for key in list(result):
        if key.upper() in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}:
            result.pop(key, None)
    result.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": hash_seed,
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    return result


def run(
    command: list[str],
    cwd: Path,
    timeout: float = 180.0,
    hash_seed: str = "0",
    custom_environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=custom_environment if custom_environment is not None else environment(hash_seed),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        check=False,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "runtime_seconds": time.perf_counter() - started,
    }


def guarded_environment(stage_root: Path, hash_seed: str) -> dict[str, str]:
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "LANG", "LC_ALL"}
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": hash_seed,
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "TEMP": str(stage_root),
            "TMP": str(stage_root),
            "TMPDIR": str(stage_root),
        }
    )
    return result


def require_process(process: dict[str, Any], label: str) -> None:
    if process["returncode"] != 0:
        raise AssertionError(
            f"{label} failed rc={process['returncode']}: {process['stderr'][-800:]}"
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(paths: list[Path]) -> dict[str, str]:
    output: dict[str, str] = {}
    for root in paths:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix not in {".pyc", ".pyo"} and "__pycache__" not in path.parts:
                output[path.relative_to(TASK_ROOT).as_posix()] = sha256(path)
    return output


def protected_snapshot(excluded_prefixes: tuple[str, ...]) -> dict[str, str]:
    output: dict[str, str] = {}
    for path in sorted(TASK_ROOT.rglob("*")):
        if not path.is_file() or path.suffix in {".pyc", ".pyo"} or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(TASK_ROOT).as_posix()
        if any(relative == prefix or relative.startswith(prefix + "/") for prefix in excluded_prefixes):
            continue
        output[relative] = sha256(path)
    return output


def parse_grade(process: dict[str, Any]) -> dict[str, Any]:
    require_process(process, "grader")
    try:
        value = json.loads(process["stdout"])
    except json.JSONDecodeError as exc:
        raise AssertionError(f"grader output is not one JSON document: {exc}") from exc
    if set(value) != {"hard_gates", "metrics", "total_score", "passed"}:
        raise AssertionError("grader top-level schema mismatch")
    if not math.isfinite(float(value["total_score"])) or not 0.0 <= float(value["total_score"]) <= 1.0:
        raise AssertionError("grader emitted an invalid score")
    if type(value["passed"]) is not bool:
        raise AssertionError("grader passed flag is not boolean")
    return value


def temporary_submission(solution: Path):
    temporary = tempfile.TemporaryDirectory(prefix="sector-audit-submission-")
    root = Path(temporary.name)
    shutil.copy2(solution, root / "solution.py")
    return temporary, root


def grade_submission(solution: Path, hash_seed: str = "0") -> tuple[dict[str, Any], float]:
    temporary, submission = temporary_submission(solution)
    try:
        process = run(
            [
                sys.executable,
                "-B",
                str(GRADER),
                "--participant",
                str(PARTICIPANT),
                "--submission",
                str(submission),
            ],
            Path(tempfile.gettempdir()),
            timeout=180.0,
            hash_seed=hash_seed,
        )
        return parse_grade(process), float(process["runtime_seconds"])
    finally:
        temporary.cleanup()


def grade_twice(solution: Path) -> tuple[dict[str, Any], dict[str, float]]:
    first_temp, first_submission = temporary_submission(solution)
    second_temp, second_submission = temporary_submission(solution)
    try:
        command_one = [
            sys.executable,
            "-B",
            str(GRADER),
            "--participant",
            str(PARTICIPANT),
            "--submission",
            str(first_submission),
        ]
        command_two = command_one[:-1] + [str(second_submission)]
        first = run(command_one, Path(tempfile.gettempdir()), timeout=180.0, hash_seed="17")
        second = run(command_two, TASK_ROOT / "scripts", timeout=180.0, hash_seed="991")
        first_value = parse_grade(first)
        second_value = parse_grade(second)
        if first["stdout"] != second["stdout"] or first["stderr"] != second["stderr"]:
            raise AssertionError("grader output is not byte deterministic")
        if first_value != second_value:
            raise AssertionError("grader parsed results are not deterministic")
        return first_value, {
            "first_seconds": float(first["runtime_seconds"]),
            "second_seconds": float(second["runtime_seconds"]),
        }
    finally:
        first_temp.cleanup()
        second_temp.cleanup()


def guarded_solver_output(
    solution: Path,
    experiment_dir: Path,
    hash_seed: str,
    timeout: float = 90.0,
) -> tuple[bytes, float]:
    normalized_seed = str(
        int.from_bytes(hashlib.sha256(hash_seed.encode("utf-8")).digest()[:4], "big")
    )
    with tempfile.TemporaryDirectory(prefix="sector-audit-solver-") as temporary:
        stage = Path(temporary)
        source_dir = stage / "source"
        input_dir = stage / "input"
        output_dir = stage / "output"
        source_dir.mkdir()
        output_dir.mkdir()
        copied_solution = source_dir / "solution.py"
        copied_guard = stage / "guard.py"
        shutil.copy2(solution, copied_solution)
        shutil.copy2(RUNNER, copied_guard)
        shutil.copytree(experiment_dir, input_dir)
        output = output_dir / "result.json"
        process = run(
            [
                sys.executable,
                "-I",
                "-B",
                str(copied_guard),
                str(copied_solution),
                str(input_dir),
                str(output),
                str(stage),
            ],
            stage,
            timeout=timeout,
            hash_seed=normalized_seed,
            custom_environment=guarded_environment(stage, normalized_seed),
        )
        require_process(process, "guarded solver")
        if [path.name for path in output_dir.iterdir()] != ["result.json"]:
            raise AssertionError("guarded solver did not create exactly result.json")
        GRADER_CORE.load_json_strict(output, GRADER_CORE.MAX_RESULT_BYTES)
        return output.read_bytes(), float(process["runtime_seconds"])


def clean_room_public_run(solution: Path) -> dict[str, Any]:
    outputs: list[bytes] = []
    runtimes: list[float] = []
    public_experiment = PARTICIPANT / "input" / "retired_experiment"
    for repeat in range(2):
        payload, runtime = guarded_solver_output(
            solution, public_experiment, str(31 + repeat)
        )
        outputs.append(payload)
        runtimes.append(runtime)
    if outputs[0] != outputs[1]:
        raise AssertionError("clean-room solver output is not byte deterministic")
    reference = GRADER_CORE.load_json_strict(
        TASK_ROOT / "private" / "reference" / "retired-demo-01.json",
        GRADER_CORE.MAX_RESULT_BYTES,
    )
    result = json.loads(outputs[0])
    parsed = GRADER_CORE.validate_result(result, reference)
    scores = GRADER_CORE.score_result(parsed, reference)
    if any(metric["score"] != 1.0 for metric in scores.values()):
        raise AssertionError("clean-room public result does not match the oracle")
    return {
        "runtime_seconds": runtimes,
        "result_bytes": len(outputs[0]),
        "sha256": hashlib.sha256(outputs[0]).hexdigest(),
        "metrics": scores,
    }


def compare_rows_by_key(
    base: list[dict],
    transformed: list[dict],
    key_fields: tuple[str, ...],
    relations: dict[str, Any],
    exact_fields: tuple[str, ...] = (),
) -> dict[str, float]:
    left_map = {tuple(row[field] for field in key_fields): row for row in base}
    right_map = {tuple(row[field] for field in key_fields): row for row in transformed}
    if len(left_map) != len(base) or len(right_map) != len(transformed):
        raise AssertionError("metamorphic rows contain duplicate keys")
    if set(left_map) != set(right_map):
        raise AssertionError("metamorphic row keys differ")
    maxima: dict[str, float] = {}
    for field, relation in relations.items():
        errors = []
        for key in sorted(left_map):
            left = left_map[key]
            right = right_map[key]
            for exact_field in exact_fields:
                if left[exact_field] != right[exact_field]:
                    raise AssertionError(
                        f"metamorphic exact field differs for {key}: {exact_field}"
                    )
            expected = relation(float(left[field])) if callable(relation) else float(left[field])
            errors.append(abs(float(right[field]) - expected))
        maxima[field] = max(errors, default=0.0)
    return maxima


def compare_record_rows(base: list[dict], transformed: list[dict], relations: dict[str, Any]) -> dict[str, float]:
    return compare_rows_by_key(
        base,
        transformed,
        ("record_id", "query_id", "state_rank"),
        relations,
        exact_fields=("condition_id",),
    )


def oracle_metamorphic_tests() -> dict[str, Any]:
    experiment = ORACLE_CORE.load_experiment(
        TASK_ROOT / "private" / "hidden_inputs" / "hidden_gamma"
    )
    record = json.loads(json.dumps(experiment["records"][0]))
    base = ORACLE_CORE.solve_record(record)
    invariant_fields = {
        "normalized_energy": None,
        "gap_ratio": None,
        "entanglement": None,
        "participation_s1": None,
        "participation_s2": None,
        "subsystem_mz_variance": None,
    }
    results: dict[str, Any] = {}

    shift = 3
    rotated = json.loads(json.dumps(record))
    rotated["fields"] = list(np.roll(np.asarray(record["fields"], dtype=float), shift))
    for query in rotated["queries"]:
        query["subsystem_start"] = (int(query["subsystem_start"]) + shift) % int(record["L"])
    rotated_rows = ORACLE_CORE.solve_record(rotated)
    results["site_relabeling"] = compare_record_rows(base, rotated_rows, invariant_fields)

    offset = 0.371
    shifted = json.loads(json.dumps(record))
    shifted["fields"] = [float(value) + offset for value in record["fields"]]
    energy_shift = -offset * (int(record["n_up"]) - 0.5 * int(record["L"]))
    shifted_relations = dict(invariant_fields)
    shifted_relations["eigenvalue"] = lambda value: value + energy_shift
    results["uniform_field_shift"] = compare_record_rows(
        base, ORACLE_CORE.solve_record(shifted), shifted_relations
    )

    alpha = 1.7
    scaled = json.loads(json.dumps(record))
    scaled["exchange"] = alpha * float(record["exchange"])
    scaled["fields"] = [alpha * float(value) for value in record["fields"]]
    scaled_relations = dict(invariant_fields)
    scaled_relations["eigenvalue"] = lambda value: alpha * value
    results["common_hamiltonian_scaling"] = compare_record_rows(
        base, ORACLE_CORE.solve_record(scaled), scaled_relations
    )

    flipped = json.loads(json.dumps(record))
    flipped["n_up"] = int(record["L"]) - int(record["n_up"])
    flipped["fields"] = [-float(value) for value in record["fields"]]
    flip_relations = dict(invariant_fields)
    flip_relations["eigenvalue"] = None
    flip_relations["subsystem_mz_mean"] = lambda value: -value
    results["global_spin_flip_nonzero_sector"] = compare_record_rows(
        base, ORACLE_CORE.solve_record(flipped), flip_relations
    )

    reversed_experiment = json.loads(json.dumps(experiment))
    reversed_experiment["records"] = list(reversed(reversed_experiment["records"]))
    original_result = ORACLE_CORE.solve_experiment(experiment)
    reversed_result = ORACLE_CORE.solve_experiment(reversed_experiment)
    if json.dumps(original_result, sort_keys=True) != json.dumps(reversed_result, sort_keys=True):
        raise AssertionError("record permutation changed the canonical result")
    results["record_permutation"] = {"max_error": 0.0}

    for name, fields in results.items():
        maximum = max(fields.values(), default=0.0)
        if maximum > 2.0e-10:
            raise AssertionError(f"metamorphic test {name} exceeded tolerance: {maximum}")
    return results


def synthetic_metamorphic_experiment() -> dict[str, Any]:
    rng = np.random.default_rng(0xA17E)
    length = 7
    n_up = 3
    exchange = 1.23
    queries = [
        {
            "query_id": "middle",
            "epsilon": 0.43,
            "packet_size": 5,
            "subsystem_start": 1,
            "subsystem_size": 3,
        },
        {
            "query_id": "offset",
            "epsilon": 0.71,
            "packet_size": 4,
            "subsystem_start": 5,
            "subsystem_size": 2,
        },
    ]
    records: list[dict[str, Any]] = []
    for condition, amplitude in (("weak", 0.8), ("strong", 5.6)):
        for realization in range(2):
            records.append(
                {
                    "record_id": f"{condition}-r{realization}",
                    "condition_id": condition,
                    "L": length,
                    "n_up": n_up,
                    "exchange": exchange,
                    "fields": [
                        float(value)
                        for value in rng.uniform(
                            -amplitude * exchange, amplitude * exchange, size=length
                        )
                    ],
                    "queries": json.loads(json.dumps(queries)),
                }
            )
    return {
        "schema_version": "sector-audit-experiment/v1",
        "experiment_id": "metamorphic-audit",
        "records": records,
        "comparisons": [
            {
                "comparison_id": f"weak-vs-strong-{query_id}",
                "weak_condition": "weak",
                "strong_condition": "strong",
                "query_id": query_id,
            }
            for query_id in ("middle", "offset")
        ],
    }


def solver_metamorphic_tests() -> dict[str, Any]:
    base = synthetic_metamorphic_experiment()
    variants: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    all_invariant = {
        "eigenvalue": None,
        "normalized_energy": None,
        "gap_ratio": None,
        "entanglement": None,
        "participation_s1": None,
        "participation_s2": None,
        "subsystem_mz_mean": None,
        "subsystem_mz_variance": None,
    }

    rotated = json.loads(json.dumps(base))
    shift = 2
    for record in rotated["records"]:
        record["fields"] = list(np.roll(np.asarray(record["fields"], dtype=float), shift))
        for query in record["queries"]:
            query["subsystem_start"] = (int(query["subsystem_start"]) + shift) % int(record["L"])
    variants["site_relabeling"] = (rotated, all_invariant)

    shifted = json.loads(json.dumps(base))
    offset = 0.317
    for record in shifted["records"]:
        record["fields"] = [float(value) + offset for value in record["fields"]]
    total_magnetization = int(base["records"][0]["n_up"]) - 0.5 * int(base["records"][0]["L"])
    shift_relations = dict(all_invariant)
    shift_relations["eigenvalue"] = lambda value: value - offset * total_magnetization
    variants["uniform_field_shift"] = (shifted, shift_relations)

    scaled = json.loads(json.dumps(base))
    alpha = 1.7
    for record in scaled["records"]:
        record["exchange"] = alpha * float(record["exchange"])
        record["fields"] = [alpha * float(value) for value in record["fields"]]
    scale_relations = dict(all_invariant)
    scale_relations["eigenvalue"] = lambda value: alpha * value
    variants["common_hamiltonian_scaling"] = (scaled, scale_relations)

    flipped = json.loads(json.dumps(base))
    for record in flipped["records"]:
        record["n_up"] = int(record["L"]) - int(record["n_up"])
        record["fields"] = [-float(value) for value in record["fields"]]
    flip_relations = dict(all_invariant)
    flip_relations["subsystem_mz_mean"] = lambda value: -value
    variants["global_spin_flip_nonzero_sector"] = (flipped, flip_relations)

    permuted = json.loads(json.dumps(base))
    permuted["records"] = list(reversed(permuted["records"]))
    variants["record_permutation"] = (permuted, all_invariant)

    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="sector-audit-metamorphic-") as temporary:
        root = Path(temporary)
        experiment_dirs: dict[str, Path] = {}
        for name, value in {"base": base, **{key: item[0] for key, item in variants.items()}}.items():
            directory = root / name
            directory.mkdir()
            (directory / "experiment.json").write_text(
                json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            ORACLE_CORE.load_experiment(directory)
            experiment_dirs[name] = directory

        for solver_name, solver in (("reference", REFERENCE), ("alternative", ALTERNATIVE)):
            base_payload, base_runtime = guarded_solver_output(
                solver, experiment_dirs["base"], f"{solver_name}-base"
            )
            base_result = json.loads(base_payload)
            base_reference = ORACLE_CORE.solve_experiment(base)
            parsed = GRADER_CORE.validate_result(base_result, base_reference)
            scores = GRADER_CORE.score_result(parsed, base_reference)
            if any(metric["score"] != 1.0 for metric in scores.values()):
                raise AssertionError(f"{solver_name} failed the synthetic baseline")
            solver_results: dict[str, Any] = {"base_runtime_seconds": base_runtime}
            for variant_name, (variant, relations) in variants.items():
                payload, runtime = guarded_solver_output(
                    solver,
                    experiment_dirs[variant_name],
                    f"{solver_name}-{variant_name}",
                )
                transformed = json.loads(payload)
                variant_reference = ORACLE_CORE.solve_experiment(variant)
                parsed = GRADER_CORE.validate_result(transformed, variant_reference)
                scores = GRADER_CORE.score_result(parsed, variant_reference)
                if any(metric["score"] != 1.0 for metric in scores.values()):
                    raise AssertionError(f"{solver_name} failed {variant_name} truth scoring")
                errors = compare_record_rows(
                    base_result["state_rows"], transformed["state_rows"], relations
                )
                aggregate_relations = {
                    field: None
                    for metric in (
                        "gap_ratio",
                        "entanglement",
                        "participation_s1",
                        "participation_s2",
                        "subsystem_mz_mean",
                        "subsystem_mz_variance",
                    )
                    for field in (f"mean_{metric}", f"sem_{metric}")
                }
                if variant_name == "global_spin_flip_nonzero_sector":
                    aggregate_relations["mean_subsystem_mz_mean"] = lambda value: -value
                aggregate_errors = compare_rows_by_key(
                    base_result["aggregate_rows"],
                    transformed["aggregate_rows"],
                    ("aggregate_id",),
                    aggregate_relations,
                    exact_fields=(
                        "condition_id",
                        "query_id",
                        "epsilon",
                        "subsystem_size",
                        "realization_count",
                        "state_count",
                    ),
                )
                conclusion_errors = compare_rows_by_key(
                    base_result["conclusions"],
                    transformed["conclusions"],
                    ("claim_id",),
                    {"effect": None},
                    exact_fields=(
                        "metric",
                        "direction",
                        "positive_effect",
                        "weak_aggregate_id",
                        "strong_aggregate_id",
                    ),
                )
                state_maximum = max(errors.values(), default=0.0)
                aggregate_maximum = max(aggregate_errors.values(), default=0.0)
                conclusion_maximum = max(conclusion_errors.values(), default=0.0)
                maximum = max(state_maximum, aggregate_maximum, conclusion_maximum)
                if maximum > 2.0e-10:
                    raise AssertionError(
                        f"{solver_name} metamorphic {variant_name} exceeded tolerance: {maximum}"
                    )
                if variant_name == "record_permutation" and payload != base_payload:
                    raise AssertionError(f"{solver_name} is not record-order deterministic")
                solver_results[variant_name] = {
                    "max_error": maximum,
                    "state_max_error": state_maximum,
                    "aggregate_max_error": aggregate_maximum,
                    "conclusion_max_error": conclusion_maximum,
                    "runtime_seconds": runtime,
                }
            results[solver_name] = solver_results
    return results


def metamorphic_tests() -> dict[str, Any]:
    return {
        "oracle_kernel": oracle_metamorphic_tests(),
        "participant_facing_solvers": solver_metamorphic_tests(),
    }


def analytic_fixtures() -> dict[str, Any]:
    length = 4
    n_up = 2
    coupling = 1.37
    fields = np.asarray([0.21, -0.47, 0.83, -0.16], dtype=np.float64)
    identity = np.eye(2, dtype=np.complex128)
    sx = np.asarray([[0.0, 0.5], [0.5, 0.0]], dtype=np.complex128)
    sy = np.asarray([[0.0, -0.5j], [0.5j, 0.0]], dtype=np.complex128)
    sz = np.asarray([[-0.5, 0.0], [0.0, 0.5]], dtype=np.complex128)

    def full_operator(operator: np.ndarray, site: int) -> np.ndarray:
        value = np.asarray([[1.0]], dtype=np.complex128)
        for factor_site in reversed(range(length)):
            value = np.kron(value, operator if factor_site == site else identity)
        return value

    operators = {
        axis: [full_operator(matrix, site) for site in range(length)]
        for axis, matrix in (("x", sx), ("y", sy), ("z", sz))
    }
    full = np.zeros((1 << length, 1 << length), dtype=np.complex128)
    for site in range(length):
        neighbor = (site + 1) % length
        full += coupling * sum(
            operators[axis][site] @ operators[axis][neighbor]
            for axis in ("x", "y", "z")
        )
        full -= fields[site] * operators["z"][site]
    record = {
        "L": length,
        "n_up": n_up,
        "exchange": coupling,
        "fields": fields.tolist(),
    }
    basis, sector = ORACLE_CORE.build_hamiltonian(record)
    projected = full[np.ix_(basis, basis)]
    hamiltonian_error = float(np.max(np.abs(projected.real - sector)))
    imaginary_error = float(np.max(np.abs(projected.imag)))
    if max(hamiltonian_error, imaginary_error) > 1.0e-12:
        raise AssertionError("Kronecker/projected Hamiltonian fixture failed")

    basis_positions = {int(mask): index for index, mask in enumerate(basis.tolist())}
    product = np.zeros(basis.size, dtype=np.float64)
    product[basis_positions[0b0011]] = 1.0
    product_observables = ORACLE_CORE.state_observables(product, basis, length, 0, 2)
    product_expected = {
        "entanglement": 0.0,
        "participation_s1": 0.0,
        "participation_s2": 0.0,
        "subsystem_mz_mean": 1.0,
        "subsystem_mz_variance": 0.0,
    }
    product_error = max(
        abs(float(product_observables[key]) - expected)
        for key, expected in product_expected.items()
    )

    bell = np.zeros(basis.size, dtype=np.float64)
    bell[basis_positions[0b0011]] = 1.0 / math.sqrt(2.0)
    bell[basis_positions[0b1100]] = 1.0 / math.sqrt(2.0)
    bell_observables = ORACLE_CORE.state_observables(bell, basis, length, 0, 2)
    bell_expected = {
        "entanglement": math.log(2.0),
        "participation_s1": math.log(2.0),
        "participation_s2": math.log(2.0),
        "subsystem_mz_mean": 0.0,
        "subsystem_mz_variance": 1.0,
    }
    bell_error = max(
        abs(float(bell_observables[key]) - expected)
        for key, expected in bell_expected.items()
    )
    if max(product_error, bell_error) > 1.0e-12:
        raise AssertionError("analytic observable fixture failed")
    return {
        "projected_kronecker_hamiltonian_max_error": hamiltonian_error,
        "projected_imaginary_max_error": imaginary_error,
        "product_state_max_error": product_error,
        "bell_state_max_error": bell_error,
    }


def input_suite_audit() -> dict[str, Any]:
    directories = [
        PARTICIPANT / "input" / "retired_experiment",
        *(sorted((TASK_ROOT / "private" / "hidden_inputs").iterdir())),
    ]
    summaries: list[dict[str, Any]] = []
    minimum_scaled_gap = math.inf
    minimum_scaled_packet_margin = math.inf
    hidden_exchanges: set[float] = set()
    hidden_lengths: set[int] = set()
    hidden_packet_sizes: set[int] = set()
    hidden_max_queries = 0
    hidden_interleaved_order = False
    hidden_record_count = 0
    hidden_query_packet_variation_records = 0
    checked_reference_query_counts = 0
    identifier_summaries: list[dict[str, Any]] = []
    for directory in directories:
        experiment = ORACLE_CORE.load_experiment(directory)
        is_hidden = directory.parent.name == "hidden_inputs"
        query_counts: list[int] = []
        query_packet_variation_records = 0
        identifiers = {
            "condition": {str(record["condition_id"]) for record in experiment["records"]},
            "record": {str(record["record_id"]) for record in experiment["records"]},
            "query": {
                str(query["query_id"])
                for record in experiment["records"]
                for query in record["queries"]
            },
            "comparison": {
                str(comparison["comparison_id"])
                for comparison in experiment["comparisons"]
            },
        }
        identifier_summaries.append(
            {
                "experiment_id": str(experiment["experiment_id"]),
                "is_hidden": is_hidden,
                "identifiers": identifiers,
            }
        )
        reference = ORACLE_CORE.load_json(
            TASK_ROOT / "private" / "reference" / f"{experiment['experiment_id']}.json"
        )
        reference_counts: dict[tuple[str, str], int] = {}
        for row in reference["state_rows"]:
            key = (str(row["record_id"]), str(row["query_id"]))
            reference_counts[key] = reference_counts.get(key, 0) + 1
        for record in experiment["records"]:
            _basis, matrix = ORACLE_CORE.build_hamiltonian(record)
            eigenvalues = np.linalg.eigvalsh(matrix)
            width = float(eigenvalues[-1] - eigenvalues[0])
            scale = max(1.0, width)
            minimum_scaled_gap = min(
                minimum_scaled_gap, float(np.min(np.diff(eigenvalues))) / scale
            )
            query_counts.append(len(record["queries"]))
            if len({int(query["packet_size"]) for query in record["queries"]}) > 1:
                query_packet_variation_records += 1
            for query in record["queries"]:
                key = (str(record["record_id"]), str(query["query_id"]))
                if reference_counts.get(key) != int(query["packet_size"]):
                    raise AssertionError(
                        "oracle/reference state-row count does not follow each query packet_size"
                    )
                checked_reference_query_counts += 1
                target = float(eigenvalues[-1]) + float(query["epsilon"]) * (
                    float(eigenvalues[0]) - float(eigenvalues[-1])
                )
                distances = sorted(
                    abs(float(eigenvalues[index]) - target)
                    for index in range(1, eigenvalues.size - 1)
                )
                packet_size = int(query["packet_size"])
                if packet_size < len(distances):
                    minimum_scaled_packet_margin = min(
                        minimum_scaled_packet_margin,
                        (distances[packet_size] - distances[packet_size - 1]) / scale,
                    )
                if is_hidden:
                    hidden_packet_sizes.add(packet_size)
            if is_hidden:
                hidden_exchanges.add(float(record["exchange"]))
                hidden_lengths.add(int(record["L"]))
                hidden_max_queries = max(hidden_max_queries, len(record["queries"]))
        summaries.append(
            {
                "experiment_id": experiment["experiment_id"],
                "record_count": len(experiment["records"]),
                "comparison_count": len(experiment["comparisons"]),
                "L": sorted({int(record["L"]) for record in experiment["records"]}),
                "n_up": sorted({int(record["n_up"]) for record in experiment["records"]}),
                "exchange": sorted(
                    {float(record["exchange"]) for record in experiment["records"]}
                ),
                "query_count_per_record": sorted(set(query_counts)),
                "records_with_query_packet_variation": query_packet_variation_records,
                "condition_sequence": [
                    str(record["condition_id"]) for record in experiment["records"]
                ],
            }
        )
        if is_hidden:
            hidden_record_count += len(experiment["records"])
            hidden_query_packet_variation_records += query_packet_variation_records
            sequence = [str(record["condition_id"]) for record in experiment["records"]]
            transitions = sum(left != right for left, right in zip(sequence, sequence[1:]))
            hidden_interleaved_order = hidden_interleaved_order or transitions > 1
    if not any(abs(value - 1.0) > 1.0e-12 for value in hidden_exchanges):
        raise AssertionError("hidden suite does not behaviorally vary exchange")
    if max(hidden_lengths) < 12 or hidden_max_queries < 3:
        raise AssertionError("hidden suite does not exercise the declared moderate/query envelope")
    if 2 not in hidden_packet_sizes or 15 not in hidden_packet_sizes:
        raise AssertionError("hidden suite does not exercise packet-size bounds")
    if not hidden_interleaved_order:
        raise AssertionError("hidden suite does not vary/interleave record order")
    if hidden_query_packet_variation_records != hidden_record_count:
        raise AssertionError("every hidden record must vary packet_size across its queries")
    public_identifiers = identifier_summaries[0]["identifiers"]
    hidden_identifier_summaries = identifier_summaries[1:]
    for category in ("condition", "record", "query", "comparison"):
        category_sets = [item["identifiers"][category] for item in hidden_identifier_summaries]
        if any(values & public_identifiers[category] for values in category_sets):
            raise AssertionError(f"hidden {category} IDs reuse retired public IDs")
        if any(
            left & right
            for index, left in enumerate(category_sets)
            for right in category_sets[index + 1 :]
        ):
            raise AssertionError(f"hidden {category} IDs are not suite-specific")
        if any(
            role in identifier.lower()
            for values in category_sets
            for identifier in values
            for role in ("weak", "strong")
        ):
            raise AssertionError(f"hidden {category} IDs leak public regime templates")
    if minimum_scaled_gap <= 1.0e-12 or minimum_scaled_packet_margin <= 1.0e-10:
        raise AssertionError("generated suite violates numerical conditioning guarantees")
    return {
        "experiments": summaries,
        "hidden_exchange_values": sorted(hidden_exchanges),
        "hidden_packet_size_min": min(hidden_packet_sizes),
        "hidden_packet_size_max": max(hidden_packet_sizes),
        "hidden_max_queries_per_record": hidden_max_queries,
        "hidden_interleaved_record_order": hidden_interleaved_order,
        "hidden_query_packet_variation_records": hidden_query_packet_variation_records,
        "hidden_record_count": hidden_record_count,
        "checked_reference_query_packet_counts": checked_reference_query_counts,
        "hidden_identifier_sets_are_public_disjoint_suite_specific_and_opaque": True,
        "minimum_scaled_eigengap": minimum_scaled_gap,
        "minimum_scaled_packet_cutoff_margin": minimum_scaled_packet_margin,
    }


def l12_resource_probe() -> dict[str, Any]:
    rng = np.random.default_rng(20260815)
    record = {
        "record_id": "resource-l12",
        "condition_id": "probe",
        "L": 12,
        "n_up": 6,
        "exchange": 1.0,
        "fields": [float(value) for value in rng.uniform(-3.0, 3.0, size=12)],
        "queries": [
            {"query_id": "a", "epsilon": 0.43, "packet_size": 7, "subsystem_start": 0, "subsystem_size": 6},
            {"query_id": "b", "epsilon": 0.71, "packet_size": 7, "subsystem_start": 9, "subsystem_size": 5},
        ],
    }
    started = time.perf_counter()
    rows = ORACLE_CORE.solve_record(record)
    elapsed = time.perf_counter() - started
    if len(rows) != 14 or elapsed > 90.0:
        raise AssertionError("L=12 resource probe failed its bound")
    return {
        "L": 12,
        "sector_dimension": math.comb(12, 6),
        "query_count": 2,
        "state_row_count": len(rows),
        "runtime_seconds": elapsed,
        "dense_matrix_bytes": math.comb(12, 6) ** 2 * 8,
    }


def grade_probe(
    source: str,
    extra_file: bool = False,
    extra_environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sector-audit-probe-") as temporary:
        root = Path(temporary)
        (root / "solution.py").write_text(source, encoding="utf-8")
        if extra_file:
            (root / "extra.txt").write_text("unexpected", encoding="utf-8")
        probe_environment = environment()
        if extra_environment:
            probe_environment.update(extra_environment)
        process = run(
            [
                sys.executable,
                "-B",
                str(GRADER),
                "--participant",
                str(PARTICIPANT),
                "--submission",
                str(root),
            ],
            Path(tempfile.gettempdir()),
            timeout=60.0,
            custom_environment=probe_environment,
        )
        return parse_grade(process)


def grade_existing_directory(directory: Path) -> dict[str, Any]:
    process = run(
        [
            sys.executable,
            "-B",
            str(GRADER),
            "--participant",
            str(PARTICIPANT),
            "--submission",
            str(directory),
        ],
        Path(tempfile.gettempdir()),
        timeout=60.0,
    )
    return parse_grade(process)


def robustness_probes() -> dict[str, Any]:
    boilerplate = """import argparse\nfrom pathlib import Path\np=argparse.ArgumentParser();p.add_argument('--experiment');p.add_argument('--output');a=p.parse_args()\n"""
    probes: dict[str, tuple[str, bool]] = {
        "malformed_json": (boilerplate + "Path(a.output).write_text('{',encoding='utf-8')\n", False),
        "nan_json": (boilerplate + "Path(a.output).write_text('{\"x\":NaN}',encoding='utf-8')\n", False),
        "partial_result": (boilerplate + "Path(a.output).write_text('{\"schema_version\":\"sector-audit-result/v1\"}',encoding='utf-8')\n", False),
        "stale_public_result": (boilerplate + "Path(a.output).write_text('{\"schema_version\":\"sector-audit-result/v1\",\"experiment_id\":\"retired-demo-01\",\"state_rows\":[],\"aggregate_rows\":[],\"conclusions\":[]}',encoding='utf-8')\n", False),
        "oversized_result": (boilerplate + "Path(a.output).write_text(' '*9000000,encoding='utf-8')\n", False),
        "network_access": (boilerplate + "import socket\nsocket.socket()\n", False),
        "subprocess_access": (boilerplate + "import subprocess\nsubprocess.run(['echo','bad'])\n", False),
        "frame_global_escape": (boilerplate + "import sys\nsys._getframe()\n", False),
        "link_creation": (
            boilerplate
            + "import os\nos.link(Path(a.experiment)/'experiment.json',Path(a.output))\n",
            False,
        ),
        "symlink_creation": (
            boilerplate
            + "import os\nos.symlink(Path(a.experiment)/'experiment.json',Path(a.output))\n",
            False,
        ),
        "rename_input": (
            boilerplate
            + "import os\nos.rename(Path(a.experiment)/'experiment.json',Path(a.experiment)/'moved.json')\n",
            False,
        ),
        "stdout_flood_fast": (
            boilerplate + "import os\nos.write(1,b'x'*1100000)\n",
            False,
        ),
        "stderr_flood_fast": (
            boilerplate + "import os\nos.write(2,b'x'*1100000)\n",
            False,
        ),
        "extra_submission_file": (boilerplate + "Path(a.output).write_text('{}',encoding='utf-8')\n", True),
    }
    private_target = TASK_ROOT / "private" / "reference" / "oracle_summary.json"
    probes["private_file_access"] = (
        boilerplate + f"Path({str(private_target)!r}).read_text(encoding='utf-8')\n",
        False,
    )
    probes["builtin_global_tamper"] = (
        boilerplate
        + f"target=Path({str(private_target)!r})\n"
        + "import builtins\nbuiltins.isinstance=lambda *args: False\n"
        + "target.read_text(encoding='utf-8')\n",
        False,
    )
    traversal_target = TASK_ROOT / "private" / "grader" / ".." / "reference" / "oracle_summary.json"
    probes["private_path_traversal"] = (
        boilerplate + f"Path({str(traversal_target)!r}).read_text(encoding='utf-8')\n",
        False,
    )
    retired_reference = (
        TASK_ROOT / "private" / "reference" / "retired-demo-01.json"
    ).read_text(encoding="utf-8")
    probes["hardcoded_retired_reference"] = (
        boilerplate + f"Path(a.output).write_text({retired_reference!r},encoding='utf-8')\n",
        False,
    )
    results: dict[str, Any] = {}

    def unavailable_link_status(exc: BaseException) -> str:
        status = f"platform_unavailable:{type(exc).__name__}"
        if not status.startswith("platform_unavailable:") or status.endswith(":"):
            raise AssertionError("link-unavailability status is not structured")
        return status

    simulated_status = unavailable_link_status(
        PermissionError("simulated unsupported hardlink branch")
    )
    if simulated_status != "platform_unavailable:PermissionError":
        raise AssertionError("unsupported hardlink simulation was not serialized")
    results["hardlink_unavailable_status_contract"] = simulated_status
    for name, (source, extra) in probes.items():
        result = grade_probe(source, extra_file=extra)
        if result["passed"] or result["hard_gates"]["passed"]:
            raise AssertionError(f"robustness probe unexpectedly crossed a hard gate: {name}")
        failure = result["hard_gates"]["failures"][0]
        if name in {"stdout_flood_fast", "stderr_flood_fast"} and "excessive console output" not in failure:
            raise AssertionError(f"console flood did not hit its size gate: {name}")
        results[name] = failure

    conditional_process_probes = {
        "os_startfile": (
            hasattr(os, "startfile"),
            boilerplate + "import os\nos.startfile(str(Path(a.experiment)/'missing'))\n",
        ),
        "os_posix_spawn": (
            hasattr(os, "posix_spawn"),
            boilerplate
            + "import os,sys\nos.posix_spawn(sys.executable,[sys.executable,'-c','pass'],os.environ)\n",
        ),
        "os_fork": (
            hasattr(os, "fork"),
            boilerplate + "import os\nos.fork()\n",
        ),
        "os_forkpty": (
            hasattr(os, "forkpty"),
            boilerplate + "import os\nos.forkpty()\n",
        ),
    }
    for name, (available, source) in conditional_process_probes.items():
        if not available:
            results[name] = "platform_unavailable"
            continue
        result = grade_probe(source)
        if result["passed"] or result["hard_gates"]["passed"]:
            raise AssertionError(f"process-creation probe unexpectedly crossed a hard gate: {name}")
        failure = result["hard_gates"]["failures"][0]
        if "evaluation guard denied" not in failure:
            raise AssertionError(f"process-creation probe was not audit-denied: {name}")
        results[name] = failure

    environment_probe = grade_probe(
        boilerplate
        + "import os\n"
        + "assert 'SECTOR_AUDIT_SECRET_CANARY' not in os.environ, 'environment leaked'\n"
        + "raise RuntimeError('environment allowlist confirmed')\n",
        extra_environment={"SECTOR_AUDIT_SECRET_CANARY": "must-not-reach-child"},
    )
    environment_failure = environment_probe["hard_gates"]["failures"][0]
    if "environment allowlist confirmed" not in environment_failure:
        raise AssertionError("environment allowlist probe did not reach the expected safe branch")
    results["environment_allowlist"] = environment_failure

    reference_source = REFERENCE.read_text(encoding="utf-8")
    for mutation, label in (
        ("wrong_state_condition", "state_condition_context"),
        ("wrong_aggregate_epsilon", "aggregate_epsilon_context"),
        ("inconsistent_conclusion", "conclusion_relation"),
    ):
        mutated = reference_source.replace(
            'MUTATION = "none"', f'MUTATION = "{mutation}"'
        )
        result = grade_probe(mutated)
        if result["hard_gates"]["passed"]:
            raise AssertionError(f"context-integrity probe crossed a hard gate: {label}")
        results[label] = result["hard_gates"]["failures"][0]

    syntax = grade_probe("this is not python !!!\n")
    if syntax["hard_gates"]["passed"]:
        raise AssertionError("syntax probe was not rejected")
    results["syntax_error"] = syntax["hard_gates"]["failures"][0]

    with tempfile.TemporaryDirectory(prefix="sector-audit-links-") as temporary:
        root = Path(temporary)
        hardlink_submission = root / "hardlink-submission"
        hardlink_submission.mkdir()
        hardlink_source = root / "hardlink-source.py"
        hardlink_source.write_text("raise SystemExit('must not execute')\n", encoding="utf-8")
        try:
            os.link(hardlink_source, hardlink_submission / "solution.py")
        except (OSError, NotImplementedError) as exc:
            results["hardlink_solution"] = unavailable_link_status(exc)
        else:
            hardlink_grade = grade_existing_directory(hardlink_submission)
            if hardlink_grade["hard_gates"]["passed"]:
                raise AssertionError("live hardlink submission probe was not rejected")
            results["hardlink_solution"] = hardlink_grade["hard_gates"]["failures"][0]

        result_source = root / "result-source.json"
        result_source.write_text("{}", encoding="utf-8")
        result_link = root / "result-hardlink.json"
        try:
            os.link(result_source, result_link)
        except (OSError, NotImplementedError) as exc:
            results["hardlink_result"] = unavailable_link_status(exc)
        else:
            try:
                GRADER_CORE.load_json_strict(result_link, GRADER_CORE.MAX_RESULT_BYTES)
            except GRADER_CORE.SubmissionError as exc:
                results["hardlink_result"] = str(exc)
            else:
                raise AssertionError("live hard-linked result probe was not rejected")

        oversized_submission = root / "oversized-submission"
        oversized_submission.mkdir()
        (oversized_submission / "solution.py").write_bytes(b"#" * 200_001)
        oversized_grade = grade_existing_directory(oversized_submission)
        if oversized_grade["hard_gates"]["passed"]:
            raise AssertionError("oversized solution probe was not rejected")
        results["oversized_solution"] = oversized_grade["hard_gates"]["failures"][0]

        file_link_submission = root / "file-link-submission"
        file_link_submission.mkdir()
        try:
            os.symlink(REFERENCE, file_link_submission / "solution.py", target_is_directory=False)
        except (OSError, NotImplementedError) as exc:
            results["symlink_solution"] = f"platform_unavailable:{type(exc).__name__}"
        else:
            file_link_grade = grade_existing_directory(file_link_submission)
            if file_link_grade["hard_gates"]["passed"]:
                raise AssertionError("live solution symlink probe was not rejected")
            results["symlink_solution"] = file_link_grade["hard_gates"]["failures"][0]

        real_submission = root / "real-submission"
        real_submission.mkdir()
        shutil.copy2(REFERENCE, real_submission / "solution.py")
        root_link = root / "root-link-submission"
        try:
            os.symlink(real_submission, root_link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            results["symlink_submission_root"] = f"platform_unavailable:{type(exc).__name__}"
        else:
            root_link_grade = grade_existing_directory(root_link)
            if root_link_grade["hard_gates"]["passed"]:
                raise AssertionError("live submission-root symlink probe was not rejected")
            results["symlink_submission_root"] = root_link_grade["hard_gates"]["failures"][0]
    return results


def package_audit() -> dict[str, Any]:
    allowed = {
        "TASK.md",
        "input/retired_experiment/experiment.json",
        "software/README.md",
        "software/validate_submission.py",
    }
    inventory = list(PARTICIPANT.rglob("*"))
    if any("__pycache__" in path.parts for path in inventory):
        raise AssertionError("participant package contains a bytecode cache")
    for path in [PARTICIPANT, *inventory]:
        info = path.lstat()
        reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(info.st_mode) or reparse:
            raise AssertionError("participant package contains a symlink or reparse point")
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise AssertionError("participant package contains a hard-linked file")
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise AssertionError("participant package contains a special filesystem entry")
    actual = {
        path.relative_to(PARTICIPANT).as_posix()
        for path in inventory
        if stat.S_ISREG(path.lstat().st_mode)
    }
    if actual != allowed:
        raise AssertionError(f"participant inventory mismatch: {sorted(actual ^ allowed)}")
    forbidden = (
        "1411.0660",
        "many-body localization edge in the random-field heisenberg chain",
        "david j. luitz",
        "nicolas laflorencie",
        "fabien alet",
        "arxiv",
    )
    corpus = "\n".join(path.read_text(encoding="utf-8", errors="ignore").lower() for path in PARTICIPANT.rglob("*") if path.is_file())
    leaks = [token for token in forbidden if token in corpus]
    if leaks:
        raise AssertionError(f"participant source identifier leak: {leaks}")
    byte_count = sum(path.stat().st_size for path in PARTICIPANT.rglob("*") if path.is_file())
    validator = PARTICIPANT / "software" / "validate_submission.py"
    with tempfile.TemporaryDirectory(prefix="sector-audit-validator-") as temporary:
        submission = Path(temporary) / "submission"
        submission.mkdir()
        shutil.copy2(REFERENCE, submission / "solution.py")
        accepted = run(
            [sys.executable, "-B", str(validator), str(submission)],
            Path(temporary),
            timeout=20.0,
        )
        require_process(accepted, "public validator valid case")
        (submission / "extra.txt").write_text("forbidden", encoding="utf-8")
        rejected = run(
            [sys.executable, "-B", str(validator), str(submission)],
            Path(temporary),
            timeout=20.0,
        )
        if rejected["returncode"] == 0:
            raise AssertionError("public validator accepted an extra file")
    return {
        "file_count": len(actual),
        "byte_count": byte_count,
        "no_bytecode_cache": True,
        "no_reparse_or_linked_files": True,
        "forbidden_hits": leaks,
        "validator_valid_case": accepted["stdout"].strip(),
        "validator_extra_file_rejected": rejected["stdout"].strip(),
    }


def contract_identity_audit(ledger_metric_ids: set[str]) -> dict[str, Any]:
    expected_metrics = {
        "spectral_packet",
        "entanglement_participation",
        "magnetization",
        "realization_aggregation",
        "evidence_consistency",
    }
    evaluation_text = (TASK_ROOT / "private" / "evaluation_spec.yaml").read_text(
        encoding="utf-8"
    )
    declared_metrics = set(
        re.findall(r"^\s*- metric_id: ([A-Za-z0-9_]+)\s*$", evaluation_text, re.MULTILINE)
    )
    try:
        mandatory_section = evaluation_text.split(
            "    mandatory_metric_thresholds:\n", 1
        )[1].split("    application:", 1)[0]
    except IndexError as exc:
        raise AssertionError("evaluation mandatory metric block is missing") from exc
    mandatory_metrics = set(
        re.findall(r"^\s{6}([A-Za-z0-9_]+):", mandatory_section, re.MULTILINE)
    )
    manifest = json.loads(
        (
            TASK_ROOT / "private" / "mutants" / "cases" / "mutant_manifest.json"
        ).read_text(encoding="utf-8")
    )
    mutant_metrics = {
        str(mutant["expected_metric"]) for mutant in manifest["mutants"]
    }
    if not (
        declared_metrics
        == mandatory_metrics
        == ledger_metric_ids
        == mutant_metrics
        == expected_metrics
    ):
        raise AssertionError(
            "evaluation metric IDs disagree across spec, mandatory gates, grader ledger, or mutants"
        )
    if f"task_id: {TASK_ID}" not in evaluation_text:
        raise AssertionError("evaluation spec task_id is not canonical")

    task_text = (TASK_ROOT / "author" / "task_spec.yaml").read_text(encoding="utf-8")
    if f"task_id: {TASK_ID}" not in task_text:
        raise AssertionError("task spec task_id is not canonical")
    try:
        subgraph_section = task_text.split(
            "  participant_output_artifact_ids:\n", 1
        )[1].split("  private_rubric_artifact_ids:\n", 1)[0]
        required_section = task_text.split("  required_outputs:\n", 1)[1].split(
            "  public_success_criteria:\n", 1
        )[0]
    except IndexError as exc:
        raise AssertionError("task output artifact blocks are missing") from exc
    expected_artifacts = {
        "artifact-dsa-solution-source",
        "artifact-dsa-states",
        "artifact-dsa-ensembles",
        "artifact-dsa-conclusion",
    }
    subgraph_artifacts = set(
        re.findall(r"^\s*- (artifact-dsa-[A-Za-z0-9-]+)\s*$", subgraph_section, re.MULTILINE)
    )
    required_artifacts = set(
        re.findall(r"^\s*- id: (artifact-dsa-[A-Za-z0-9-]+)\s*$", required_section, re.MULTILINE)
    )
    if subgraph_artifacts != expected_artifacts or required_artifacts != expected_artifacts:
        raise AssertionError("all four participant artifact IDs must resolve in required_outputs")
    if required_section.count("delivery: submitted_file") != 1:
        raise AssertionError("task spec must declare exactly one submitted artifact")
    if required_section.count("delivery: generated_at_evaluation_runtime") != 3:
        raise AssertionError("task spec must declare exactly three runtime result artifacts")
    return {
        "task_id": TASK_ID,
        "metric_ids": sorted(expected_metrics),
        "participant_output_artifact_ids": sorted(expected_artifacts),
        "submitted_artifact_count": 1,
        "runtime_result_artifact_count": 3,
    }


def build_identity() -> str:
    digest = hashlib.sha256()
    excluded = {"author/verification_results.json", "author/verification_report.md"}
    files = [path for path in TASK_ROOT.rglob("*") if path.is_file()]
    for path in sorted(files, key=lambda item: item.relative_to(TASK_ROOT).as_posix()):
        relative = path.relative_to(TASK_ROOT).as_posix()
        if relative in excluded or path.suffix in {".pyc", ".pyo"} or "__pycache__" in path.parts:
            continue
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative.encode("utf-8"))
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return "sha256:" + digest.hexdigest()


def main() -> int:
    started = time.perf_counter()
    results: dict[str, Any] = {
        "schema_version": "sector-audit-verification/v1",
        "task_id": TASK_ID,
        "status": "running",
        "checks": {},
    }
    output_path = TASK_ROOT / "author" / "verification_results.json"
    try:
        oracle_protected_before = protected_snapshot(
            (
                "participant/input",
                "private/hidden_inputs",
                "private/reference",
                "author/verification_results.json",
            )
        )
        oracle_first = run(
            [sys.executable, "-B", str(ORACLE), "--task-root", str(TASK_ROOT), "--check"],
            TASK_ROOT,
            timeout=180.0,
        )
        require_process(oracle_first, "oracle generation")
        first_snapshot = snapshot(
            [PARTICIPANT / "input", TASK_ROOT / "private" / "hidden_inputs", TASK_ROOT / "private" / "reference"]
        )
        oracle_second = run(
            [sys.executable, "-B", str(ORACLE), "--task-root", str(TASK_ROOT), "--check"],
            TASK_ROOT / "scripts",
            timeout=180.0,
        )
        require_process(oracle_second, "repeated oracle generation")
        second_snapshot = snapshot(
            [PARTICIPANT / "input", TASK_ROOT / "private" / "hidden_inputs", TASK_ROOT / "private" / "reference"]
        )
        if oracle_first["stdout"] != oracle_second["stdout"] or first_snapshot != second_snapshot:
            raise AssertionError("oracle generation is not byte deterministic")
        if oracle_protected_before != protected_snapshot(
            (
                "participant/input",
                "private/hidden_inputs",
                "private/reference",
                "author/verification_results.json",
            )
        ):
            raise AssertionError("oracle generation changed files outside its declared outputs")
        results["checks"]["oracle"] = {
            "runtime_seconds": [oracle_first["runtime_seconds"], oracle_second["runtime_seconds"]],
            "artifact_count": len(first_snapshot),
            "summary": json.loads(oracle_first["stdout"]),
        }

        builder_protected_before = protected_snapshot(
            ("private/mutants/cases", "author/verification_results.json")
        )
        builder = run(
            [sys.executable, "-B", str(MUTANT_BUILDER), "--task-root", str(TASK_ROOT)],
            TASK_ROOT,
            timeout=30.0,
        )
        require_process(builder, "mutant builder")
        if builder_protected_before != protected_snapshot(
            ("private/mutants/cases", "author/verification_results.json")
        ):
            raise AssertionError("mutant builder changed files outside mutant cases")

        results["checks"]["clean_room_public"] = clean_room_public_run(REFERENCE)
        results["checks"]["alternative_public_determinism"] = clean_room_public_run(
            ALTERNATIVE
        )
        reference_grade, deterministic_timings = grade_twice(REFERENCE)
        if not reference_grade["passed"] or reference_grade["total_score"] != 1.0:
            raise AssertionError(
                f"clean reference failed private evaluation: {reference_grade}"
            )
        results["checks"]["reference"] = {
            "grade": reference_grade,
            "grader_runtime_seconds": deterministic_timings,
        }
        alternative_grade, alternative_runtime = grade_twice(ALTERNATIVE)
        if not alternative_grade["passed"] or alternative_grade["total_score"] != 1.0:
            raise AssertionError("independent alternative failed private evaluation")
        results["checks"]["alternative"] = {
            "grade": alternative_grade,
            "grader_runtime_seconds": alternative_runtime,
        }

        manifest = json.loads(
            (TASK_ROOT / "private" / "mutants" / "cases" / "mutant_manifest.json").read_text(encoding="utf-8")
        )
        mutant_results: list[dict[str, Any]] = []
        categories: set[str] = set()
        for mutant in manifest["mutants"]:
            solution = TASK_ROOT / "private" / "mutants" / mutant["path"]
            grade, runtime = grade_submission(solution, hash_seed="71")
            if grade["passed"]:
                raise AssertionError(f"scientific mutant passed: {mutant['mutant_id']}")
            if not grade["hard_gates"]["passed"]:
                raise AssertionError(f"scientific mutant was not schema-valid: {mutant['mutant_id']}")
            expected_metric = mutant["expected_metric"]
            if grade["metrics"][expected_metric]["score"] >= 0.92:
                raise AssertionError(
                    f"scientific mutant did not fail its expected metric: {mutant['mutant_id']}"
                )
            if grade["total_score"] > 0.94:
                raise AssertionError(
                    f"scientific mutant lacks a release-margin rejection: {mutant['mutant_id']}"
                )
            categories.add(mutant["category"])
            mutant_results.append(
                {
                    "mutant_id": mutant["mutant_id"],
                    "category": mutant["category"],
                    "score": grade["total_score"],
                    "expected_metric": expected_metric,
                    "expected_metric_score": grade["metrics"][expected_metric]["score"],
                    "passed": grade["passed"],
                    "runtime_seconds": runtime,
                }
            )
        if len(mutant_results) < 8 or len(categories) < 5:
            raise AssertionError("mutation coverage is below the release floor")
        results["checks"]["mutants"] = {
            "count": len(mutant_results),
            "category_count": len(categories),
            "results": mutant_results,
        }

        results["checks"]["analytic_fixtures"] = analytic_fixtures()
        results["checks"]["input_suite"] = input_suite_audit()
        results["checks"]["metamorphic"] = metamorphic_tests()
        results["checks"]["resource_probe"] = l12_resource_probe()
        results["checks"]["robustness"] = robustness_probes()
        results["checks"]["package"] = package_audit()
        results["checks"]["contract_identity"] = contract_identity_audit(
            set(results["checks"]["reference"]["grade"]["metrics"])
        )
        results["build_identity"] = build_identity()
        results["status"] = "pass"
        results["runtime_seconds"] = time.perf_counter() - started
        output_path.write_text(
            json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(results, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except Exception as exc:
        results["status"] = "fail"
        results["runtime_seconds"] = time.perf_counter() - started
        results["failure"] = f"{type(exc).__name__}: {exc}"
        results["traceback"] = traceback.format_exc()
        output_path.write_text(
            json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(results["traceback"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
