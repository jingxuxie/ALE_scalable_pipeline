#!/usr/bin/env python3
"""Run every local release gate for the spinful packet task package."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np


sys.dont_write_bytecode = True
TASK_ROOT = Path(__file__).resolve().parents[1]
PARTICIPANT = TASK_ROOT / "participant"
GRADER = TASK_ROOT / "private" / "grader" / "grade.py"
REFERENCE = TASK_ROOT / "private" / "reference"
GENERATOR = TASK_ROOT / "author" / "generate_instance.py"
ORACLE = TASK_ROOT / "author" / "oracle.py"
REFERENCE_SOLVER = TASK_ROOT / "author" / "reference_solver" / "solve.py"
ALTERNATIVE_SOLVER = TASK_ROOT / "author" / "alternative_solver" / "solve.py"
METAMORPHIC = TASK_ROOT / "author" / "metamorphic_tests.py"
ISOLATED_RUNNER = TASK_ROOT / "scripts" / "isolated_runner.py"
MUTANT_BUILDER = TASK_ROOT / "private" / "mutants" / "make_structural.py"
MUTANT_MANIFEST = TASK_ROOT / "private" / "mutants" / "manifest.json"
REQUIRED_OUTPUTS = ["basis.npz", "trajectories.csv", "ensemble.csv", "analysis.json"]


class VerificationFailure(RuntimeError):
    pass


def command(
    arguments: list[str | Path],
    *,
    cwd: Path | None = None,
    expected_returncode: int = 0,
    timeout: float = 60.0,
) -> tuple[subprocess.CompletedProcess[str], float]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONHASHSEED"] = "0"
    environment["OPENBLAS_NUM_THREADS"] = "1"
    environment["OMP_NUM_THREADS"] = "1"
    environment["MKL_NUM_THREADS"] = "1"
    environment["NUMEXPR_NUM_THREADS"] = "1"
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONSTARTUP", None)
    started = time.perf_counter()
    process = subprocess.run(
        [str(value) for value in arguments],
        cwd=str(cwd or TASK_ROOT),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if process.returncode != expected_returncode:
        raise VerificationFailure(
            f"command returned {process.returncode}, expected {expected_returncode}: "
            f"{' '.join(str(value) for value in arguments)}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return process, elapsed


def parse_grade(process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        parsed = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise VerificationFailure(f"grader did not emit JSON: {process.stdout!r}") from error
    if not isinstance(parsed, dict) or "passed" not in parsed or "score" not in parsed:
        raise VerificationFailure("grader JSON does not match its result schema")
    return parsed


def grade(path: Path, expected_pass: bool) -> tuple[dict[str, Any], float, str]:
    expected_code = 0 if expected_pass else 1
    process, elapsed = command(
        [sys.executable, GRADER, path], expected_returncode=expected_code, timeout=30.0
    )
    parsed = parse_grade(process)
    if bool(parsed["passed"]) is not expected_pass:
        raise VerificationFailure(f"grader pass flag disagrees for {path}")
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return parsed, elapsed, canonical


def grade_twice(path: Path, expected_pass: bool) -> tuple[dict[str, Any], list[float]]:
    first, first_time, first_canonical = grade(path, expected_pass)
    second, second_time, second_canonical = grade(path, expected_pass)
    if first_canonical != second_canonical:
        raise VerificationFailure(f"repeated evaluator results differ for {path}")
    return first, [first_time, second_time]


def syntax_audit() -> None:
    python_files = sorted(TASK_ROOT.rglob("*.py"))
    for path in python_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as error:
            raise VerificationFailure(f"Python syntax audit failed for {path}: {error}") from error


def package_audit() -> dict[str, Any]:
    expected = {
        PARTICIPANT / "TASK.md",
        PARTICIPANT / "input" / "config.json",
        PARTICIPANT / "input" / "sites.csv",
        PARTICIPANT / "input" / "bonds.csv",
        PARTICIPANT / "input" / "realizations.csv",
        PARTICIPANT / "input" / "onsite.csv",
        PARTICIPANT / "input" / "times.csv",
        PARTICIPANT / "software" / "bessel.py",
    }
    actual = {path for path in PARTICIPANT.rglob("*") if path.is_file()}
    if actual != expected:
        raise VerificationFailure(
            f"participant projection mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )
    for path in PARTICIPANT.rglob("*"):
        if path.is_symlink():
            raise VerificationFailure(f"participant package contains symlink: {path}")
        if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
            raise VerificationFailure(f"participant package contains bytecode/cache: {path}")
    forbidden = ["1910.05194", "arxiv", "quantum-kite", "quantum_kite", "kite:"]
    text_files = [path for path in actual if path.suffix.lower() in {".md", ".json", ".csv", ".py"}]
    for path in text_files:
        lowered = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            if token in lowered:
                raise VerificationFailure(f"source identifier {token!r} leaked into {path}")

    hidden = json.loads(
        (TASK_ROOT / "private" / "hidden_inputs" / "private_times.json").read_text(
            encoding="utf-8"
        )
    )["times"]
    import csv

    with (PARTICIPANT / "input" / "times.csv").open("r", encoding="utf-8", newline="") as handle:
        public = [float(row["time"]) for row in csv.DictReader(handle)]
    if any(any(abs(float(h) - p) < 1e-14 for p in public) for h in hidden):
        raise VerificationFailure("private and public contraction times overlap")

    solver_text = REFERENCE_SOLVER.read_text(encoding="utf-8").lower()
    for forbidden_import in ("socket", "requests", "urllib", "http.client", "subprocess"):
        if f"import {forbidden_import}" in solver_text or f"from {forbidden_import}" in solver_text:
            raise VerificationFailure(f"clean-room solver imports network/process module {forbidden_import}")
    for forbidden_path in ("private/", "private\\", "author/", "author\\", "1910.05194"):
        if forbidden_path in solver_text:
            raise VerificationFailure(f"clean-room solver embeds forbidden path {forbidden_path}")

    review = TASK_ROOT / "author" / "paper_blind_review.md"
    if not review.is_file() or "Status: pass" not in review.read_text(encoding="utf-8"):
        raise VerificationFailure("paper-blind specification review is absent or not marked pass")

    required_package_files = [
        TASK_ROOT / "author" / "task_spec.yaml",
        TASK_ROOT / "author" / "verification_report.md",
        TASK_ROOT / "author" / "release_checklist.md",
        TASK_ROOT / "private" / "evaluation_spec.yaml",
        GRADER,
        GENERATOR,
        ORACLE,
        REFERENCE_SOLVER,
        ALTERNATIVE_SOLVER,
        METAMORPHIC,
        ISOLATED_RUNNER,
        MUTANT_MANIFEST,
    ]
    missing = [str(path) for path in required_package_files if not path.is_file()]
    if missing:
        raise VerificationFailure(f"package files missing: {missing}")
    return {
        "participant_file_count": len(actual),
        "source_identifier_scan": "pass",
        "hidden_time_disjointness": "pass",
        "clean_room_solver_static_audit": "pass",
        "paper_blind_review": "pass",
    }


def bessel_audit() -> dict[str, float]:
    import importlib.util

    helper_path = PARTICIPANT / "software" / "bessel.py"
    spec = importlib.util.spec_from_file_location("verify_public_bessel", helper_path)
    if spec is None or spec.loader is None:
        raise VerificationFailure("cannot load public Bessel helper")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    nodes, weights = np.polynomial.legendre.leggauss(360)
    theta = 0.5 * np.pi * (nodes + 1.0)
    worst = 0.0
    for argument in (0.0, 0.37, 2.8, 6.4, 10.7):
        observed = helper.bessel_j_sequence(argument, 52)
        orders = np.arange(52)[:, None]
        truth = 0.5 * (
            np.cos(orders * theta[None, :] - argument * np.sin(theta)[None, :]) @ weights
        )
        worst = max(worst, float(np.max(np.abs(observed - truth))))
    if worst > 3.0e-13:
        raise VerificationFailure(f"public Bessel helper failed independent quadrature: {worst}")
    return {"max_abs_disagreement": worst}


def build_identity() -> str:
    digest = hashlib.sha256()
    included: list[Path] = []
    for subtree in (PARTICIPANT, TASK_ROOT / "private"):
        included.extend(path for path in subtree.rglob("*") if path.is_file())
    included.extend(
        [
            GENERATOR,
            ORACLE,
            REFERENCE_SOLVER,
            ALTERNATIVE_SOLVER,
            METAMORPHIC,
            ISOLATED_RUNNER,
            Path(__file__).resolve(),
        ]
    )
    for path in sorted(set(included), key=lambda item: item.relative_to(TASK_ROOT).as_posix()):
        if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
            continue
        relative = path.relative_to(TASK_ROOT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return "sha256:" + digest.hexdigest()


def _numeric_close(observed: float, reference: float, absolute: float, relative: float) -> bool:
    if not math.isfinite(observed) or not math.isfinite(reference):
        return False
    return abs(observed - reference) <= max(absolute, relative * abs(reference))


def _json_equivalent(
    observed: Any,
    reference: Any,
    absolute: float,
    relative: float,
    location: str = "$",
) -> None:
    if isinstance(reference, bool) or isinstance(observed, bool):
        if observed is not reference:
            raise VerificationFailure(f"regenerated JSON differs at {location}")
        return
    if isinstance(reference, int) and isinstance(observed, int):
        if observed != reference:
            raise VerificationFailure(f"regenerated JSON integer differs at {location}")
        return
    if isinstance(reference, (int, float)) and isinstance(observed, (int, float)):
        if not _numeric_close(float(observed), float(reference), absolute, relative):
            raise VerificationFailure(f"regenerated JSON numeric value differs at {location}")
        return
    if isinstance(reference, dict) and isinstance(observed, dict):
        if set(observed) != set(reference):
            raise VerificationFailure(f"regenerated JSON keys differ at {location}")
        for key in sorted(reference):
            _json_equivalent(
                observed[key], reference[key], absolute, relative, f"{location}.{key}"
            )
        return
    if isinstance(reference, list) and isinstance(observed, list):
        if len(observed) != len(reference):
            raise VerificationFailure(f"regenerated JSON list length differs at {location}")
        for index, (left, right) in enumerate(zip(observed, reference)):
            _json_equivalent(left, right, absolute, relative, f"{location}[{index}]")
        return
    if observed != reference:
        raise VerificationFailure(f"regenerated JSON value differs at {location}")


def _compare_csv(
    generated: Path, checked: Path, absolute: float, relative: float
) -> None:
    with generated.open("r", encoding="utf-8", newline="") as handle:
        observed_rows = list(csv.reader(handle))
    with checked.open("r", encoding="utf-8", newline="") as handle:
        reference_rows = list(csv.reader(handle))
    if len(observed_rows) != len(reference_rows):
        raise VerificationFailure(f"regenerated CSV row count differs: {checked}")
    for row_index, (observed_row, reference_row) in enumerate(
        zip(observed_rows, reference_rows)
    ):
        if len(observed_row) != len(reference_row):
            raise VerificationFailure(f"regenerated CSV width differs: {checked}:{row_index}")
        for column_index, (observed, reference) in enumerate(
            zip(observed_row, reference_row)
        ):
            try:
                observed_number = float(observed)
                reference_number = float(reference)
            except ValueError:
                if observed != reference:
                    raise VerificationFailure(
                        f"regenerated CSV text differs: {checked}:{row_index}:{column_index}"
                    )
            else:
                if not _numeric_close(
                    observed_number, reference_number, absolute, relative
                ):
                    raise VerificationFailure(
                        f"regenerated CSV numeric value differs: {checked}:{row_index}:{column_index}"
                    )


def _compare_npz(
    generated: Path, checked: Path, absolute: float, relative: float
) -> None:
    with np.load(generated, allow_pickle=False) as observed_archive, np.load(
        checked, allow_pickle=False
    ) as reference_archive:
        if set(observed_archive.files) != set(reference_archive.files):
            raise VerificationFailure(f"regenerated NPZ members differ: {checked}")
        for key in sorted(reference_archive.files):
            observed = observed_archive[key]
            reference = reference_archive[key]
            if observed.shape != reference.shape or observed.dtype != reference.dtype:
                raise VerificationFailure(f"regenerated NPZ schema differs: {checked}:{key}")
            if np.issubdtype(reference.dtype, np.number):
                if not np.all(np.isfinite(observed)) or not np.all(np.isfinite(reference)):
                    raise VerificationFailure(f"regenerated NPZ contains non-finite data: {checked}:{key}")
                allowed = np.maximum(absolute, relative * np.abs(reference))
                if np.any(np.abs(observed - reference) > allowed):
                    raise VerificationFailure(f"regenerated NPZ values differ: {checked}:{key}")
            elif not np.array_equal(observed, reference):
                raise VerificationFailure(f"regenerated NPZ metadata differs: {checked}:{key}")


def require_equivalent_files(
    generated_root: Path,
    checked_root: Path,
    expected_names: list[str],
    tolerances: dict[str, tuple[float, float]] | None = None,
) -> None:
    generated_names = sorted(
        path.relative_to(generated_root).as_posix()
        for path in generated_root.rglob("*")
        if path.is_file()
    )
    checked_names = sorted(
        path.relative_to(checked_root).as_posix()
        for path in checked_root.rglob("*")
        if path.is_file()
    )
    expected = sorted(expected_names)
    if generated_names != expected or checked_names != expected:
        raise VerificationFailure(
            "regenerated artifact inventory differs from the checked package: "
            f"generated={generated_names}, checked={checked_names}, expected={expected}"
        )
    for name in expected:
        generated = generated_root / name
        checked = checked_root / name
        absolute, relative = (tolerances or {}).get(name, (0.0, 0.0))
        if generated.suffix == ".json":
            _json_equivalent(
                json.loads(generated.read_text(encoding="utf-8")),
                json.loads(checked.read_text(encoding="utf-8")),
                absolute,
                relative,
            )
        elif generated.suffix == ".csv":
            _compare_csv(generated, checked, absolute, relative)
        elif generated.suffix == ".npz":
            _compare_npz(generated, checked, absolute, relative)
        elif generated.read_bytes() != checked.read_bytes():
            raise VerificationFailure(f"checked artifact is stale or corrupted: {checked}")


def main() -> None:
    results_path = TASK_ROOT / "author" / "verification_results.json"
    result: dict[str, Any] = {
        "schema_version": "spinful-packet-verification/v1",
        "python": sys.version.split()[0],
        "numpy": np.__version__,
    }
    try:
        syntax_audit()
        result["syntax_audit"] = "pass"
        result["package_audit"] = package_audit()
        result["bessel_audit"] = bessel_audit()

        with tempfile.TemporaryDirectory(prefix="spinful-packet-regenerate-") as regenerated:
            regenerated_root = Path(regenerated)
            generated_task = regenerated_root / "task"
            generation, generation_time = command(
                [sys.executable, GENERATOR, "--task-root", generated_task], timeout=30.0
            )
            require_equivalent_files(
                generated_task / "participant" / "input",
                PARTICIPANT / "input",
                [
                    "bonds.csv",
                    "config.json",
                    "onsite.csv",
                    "realizations.csv",
                    "sites.csv",
                    "times.csv",
                ],
            )
            require_equivalent_files(
                generated_task / "private" / "hidden_inputs",
                TASK_ROOT / "private" / "hidden_inputs",
                ["private_times.json"],
            )
            result["instance_generation"] = {
                "status": "pass",
                "runtime_seconds": generation_time,
                "message": generation.stdout.strip(),
                "mode": "temporary regeneration matched checked artifacts semantically",
            }

            generated_reference = regenerated_root / "reference"
            generated_hidden = regenerated_root / "reference_hidden" / "hidden_trajectories.csv"
            oracle_process, oracle_time = command(
                [
                    sys.executable,
                    ORACLE,
                    PARTICIPANT,
                    generated_reference,
                    TASK_ROOT / "private" / "hidden_inputs" / "private_times.json",
                    generated_hidden,
                ],
                timeout=60.0,
            )
            require_equivalent_files(
                generated_reference,
                REFERENCE,
                REQUIRED_OUTPUTS,
                {
                    "basis.npz": (2.0e-10, 2.0e-8),
                    "trajectories.csv": (2.0e-8, 1.0e-7),
                    "ensemble.csv": (3.0e-8, 2.0e-7),
                    "analysis.json": (5.0e-8, 3.0e-7),
                },
            )
            require_equivalent_files(
                generated_hidden.parent,
                TASK_ROOT / "private" / "reference_hidden",
                ["hidden_trajectories.csv"],
                {"hidden_trajectories.csv": (2.0e-8, 1.0e-7)},
            )
            result["oracle_generation"] = {
                "status": "pass",
                "runtime_seconds": oracle_time,
                "message": oracle_process.stdout.strip(),
                "mode": "temporary regeneration matched checked artifacts semantically",
            }

        manifest = json.loads(MUTANT_MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="spinful-packet-verify-") as temporary:
            work = Path(temporary)

            oracle_submission = work / "oracle-submission"
            oracle_submission.mkdir()
            for name in REQUIRED_OUTPUTS:
                shutil.copy2(REFERENCE / name, oracle_submission / name)
            oracle_grade, oracle_grade_times = grade_twice(oracle_submission, True)
            result["oracle_grade"] = {
                "status": "pass",
                "score": oracle_grade["score"],
                "runtime_seconds": oracle_grade_times,
                "metrics": oracle_grade["metrics"],
            }

            clean_room = work / "clean-room"
            clean_participant = clean_room / "participant"
            clean_output = clean_room / "output"
            shutil.copytree(PARTICIPANT, clean_participant)
            clean_solver = clean_room / "solve.py"
            shutil.copy2(REFERENCE_SOLVER, clean_solver)
            probe = clean_room / "isolation_probe.py"
            probe.write_text(
                "import socket, sys\n"
                "file_denied = False\n"
                "network_denied = False\n"
                "try:\n"
                "    open(sys.argv[1], 'rb').close()\n"
                "except PermissionError:\n"
                "    file_denied = True\n"
                "try:\n"
                "    socket.socket()\n"
                "except PermissionError:\n"
                "    network_denied = True\n"
                "if not (file_denied and network_denied):\n"
                "    raise SystemExit(3)\n",
                encoding="utf-8",
            )
            _, isolation_probe_time = command(
                [
                    sys.executable,
                    ISOLATED_RUNNER,
                    clean_room,
                    probe,
                    TASK_ROOT / "private" / "evaluation_spec.yaml",
                ],
                cwd=clean_room,
                timeout=30.0,
            )
            _, clean_solve_time = command(
                [
                    sys.executable,
                    ISOLATED_RUNNER,
                    clean_room,
                    clean_solver,
                    clean_participant,
                    clean_output,
                ],
                cwd=clean_room,
                timeout=60.0,
            )
            clean_grade_1, clean_grade_time_1, canonical_1 = grade(clean_output, True)
            clean_grade_2, clean_grade_time_2, canonical_2 = grade(clean_output, True)
            if canonical_1 != canonical_2:
                raise VerificationFailure("repeated evaluator results are not identical")
            result["clean_room_reference"] = {
                "status": "pass",
                "solver_command": "python solve.py participant output",
                "runtime_seconds": clean_solve_time,
                "grader_runtime_seconds": [clean_grade_time_1, clean_grade_time_2],
                "score": clean_grade_1["score"],
                "metrics": clean_grade_1["metrics"],
                "output_bytes": {
                    name: (clean_output / name).stat().st_size for name in REQUIRED_OUTPUTS
                },
                "network": "denied by Python audit hook; denial probe passed",
                "hidden_access": "file reads outside clean root and runtime denied by audit hook",
                "isolation_probe_runtime_seconds": isolation_probe_time,
                "deterministic_repeated_grade": True,
            }

            root_link = work / "submission-root-link"
            try:
                os.symlink(clean_output, root_link, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                result["root_symlink_test"] = {
                    "status": "platform_unavailable",
                    "reason": str(error),
                    "static_gate_present": True,
                }
            else:
                linked_grade, linked_grade_times = grade_twice(root_link, False)
                if not linked_grade["hard_gate_failures"]:
                    raise VerificationFailure("root symlink was not rejected by a hard gate")
                result["root_symlink_test"] = {
                    "status": "pass",
                    "grader_runtime_seconds": linked_grade_times,
                    "hard_gate_failures": linked_grade["hard_gate_failures"],
                }

            alternative_output = work / "alternative-output"
            _, alternative_time = command(
                [sys.executable, ALTERNATIVE_SOLVER, PARTICIPANT, alternative_output],
                timeout=60.0,
            )
            alternative_grade, alternative_grade_times = grade_twice(alternative_output, True)
            result["alternative_solver"] = {
                "status": "pass",
                "runtime_seconds": alternative_time,
                "grader_runtime_seconds": alternative_grade_times,
                "score": alternative_grade["score"],
                "metrics": alternative_grade["metrics"],
                "independence": "edge-accumulated operator recurrence; no dense Hamiltonian in propagation",
            }

            scientific_results: list[dict[str, Any]] = []
            for record in manifest["scientific"]:
                mutant_id = record["id"]
                output = work / f"scientific-{mutant_id}"
                _, solve_time = command(
                    [
                        sys.executable,
                        REFERENCE_SOLVER,
                        PARTICIPANT,
                        output,
                        "--mutation",
                        mutant_id,
                    ],
                    timeout=60.0,
                )
                mutant_grade, grade_times = grade_twice(output, False)
                if mutant_grade["hard_gate_failures"]:
                    raise VerificationFailure(
                        f"scientific mutant {mutant_id} failed structurally rather than scientifically"
                    )
                scientific_results.append(
                    {
                        "id": mutant_id,
                        "category": record["category"],
                        "score": mutant_grade["score"],
                        "solver_runtime_seconds": solve_time,
                        "grader_runtime_seconds": grade_times,
                        "status": "rejected_as_expected",
                    }
                )
            result["scientific_mutants"] = scientific_results

            structural_results: list[dict[str, Any]] = []
            for record in manifest["structural"]:
                mutant_id = record["id"]
                output = work / f"structural-{mutant_id}"
                command(
                    [sys.executable, MUTANT_BUILDER, mutant_id, REFERENCE, output],
                    timeout=30.0,
                )
                mutant_grade, grade_times = grade_twice(output, False)
                structural_results.append(
                    {
                        "id": mutant_id,
                        "category": record["category"],
                        "score": mutant_grade["score"],
                        "hard_gate_failures": mutant_grade["hard_gate_failures"],
                        "grader_runtime_seconds": grade_times,
                        "status": "rejected_as_expected",
                    }
                )
            result["structural_and_adversarial_mutants"] = structural_results

        metamorphic_process, metamorphic_time = command(
            [sys.executable, METAMORPHIC, PARTICIPANT], timeout=60.0
        )
        metamorphic_results = json.loads(metamorphic_process.stdout)
        if any(record.get("status") != "pass" for record in metamorphic_results.values()):
            raise VerificationFailure("a metamorphic check did not pass")
        result["metamorphic_tests"] = {
            "status": "pass",
            "runtime_seconds": metamorphic_time,
            "results": metamorphic_results,
        }
        result["final_package_audit"] = package_audit()
        result["build_identity"] = build_identity()
        result["status"] = "pass"
    except Exception as error:
        result["status"] = "fail"
        result["failure"] = str(error)
        results_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        raise SystemExit(1)

    results_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
