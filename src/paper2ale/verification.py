"""Dynamic publication verification for registered task families.

The static compiler checks are necessary but not sufficient for publication.
This module exercises trusted reference artifacts and registered realistic
mutants through the same evaluator-only grader that will score participants.
Only explicitly registered tasks are run; unknown families and task IDs remain
outside this trust boundary and therefore retain ``not_run`` publication gates.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import CodeType
from typing import Any, BinaryIO

from .packaging import (
    BuildFile,
    write_deterministic_zip,
    write_manifest,
    write_projection,
)
from .schema import SOURCE_KINDS


MAX_SUBPROCESS_SECONDS = 30.0
MAX_STDOUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 64 * 1024
_MEBIBYTE = 1024 * 1024
VERIFICATION_VERSION = "paper2ale.verification/v4"


def _stable_identity_value(value: Any) -> Any:
    """Return a path-free JSON value for callable implementation hashing."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return {"float_hex": value.hex()}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, CodeType):
        return {
            "argcount": value.co_argcount,
            "posonlyargcount": value.co_posonlyargcount,
            "kwonlyargcount": value.co_kwonlyargcount,
            "nlocals": value.co_nlocals,
            "stacksize": value.co_stacksize,
            "flags": value.co_flags,
            "code": value.co_code.hex(),
            "consts": [_stable_identity_value(item) for item in value.co_consts],
            "names": list(value.co_names),
            "varnames": list(value.co_varnames),
            "freevars": list(value.co_freevars),
            "cellvars": list(value.co_cellvars),
        }
    if isinstance(value, (tuple, list)):
        return [_stable_identity_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _stable_identity_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    return {
        "type_module": type(value).__module__,
        "type_qualname": type(value).__qualname__,
    }


def _callable_implementation_identity(value: Callable[..., Any]) -> dict[str, str]:
    """Identify trusted callable code without recording local filesystem paths."""

    module = str(getattr(value, "__module__", type(value).__module__))
    qualname = str(getattr(value, "__qualname__", type(value).__qualname__))
    source_file = inspect.getsourcefile(value)
    module_sha256: str | None = None
    if source_file:
        try:
            module_bytes = Path(source_file).read_bytes()
            normalized_module = module_bytes.replace(b"\r\n", b"\n").replace(
                b"\r", b"\n"
            )
            module_sha256 = hashlib.sha256(normalized_module).hexdigest()
        except OSError:
            module_sha256 = None
    try:
        callable_source = inspect.getsource(value)
    except (OSError, TypeError):
        callable_source = None
    target = value if hasattr(value, "__code__") else getattr(value, "__call__", None)
    code = getattr(target, "__code__", None)
    if callable_source is None and code is None:
        raise TypeError(
            f"callable {module}.{qualname} has no stable inspectable implementation"
        )
    closure = getattr(target, "__closure__", None)
    closure_values: list[Any] = []
    for cell in closure or ():
        try:
            closure_values.append(_stable_identity_value(cell.cell_contents))
        except ValueError:
            closure_values.append({"empty_cell": True})
    payload = {
        "module_sha256": module_sha256,
        "callable_source": callable_source,
        "code": _stable_identity_value(code),
        "defaults": _stable_identity_value(getattr(target, "__defaults__", None)),
        "kwdefaults": _stable_identity_value(getattr(target, "__kwdefaults__", None)),
        "closure": closure_values,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "module": module,
        "qualname": qualname,
        "implementation_sha256": hashlib.sha256(encoded).hexdigest(),
    }


@dataclass(frozen=True, slots=True)
class BoundedProcessResult:
    """Result of a subprocess whose time and output were strictly bounded."""

    returncode: int | None
    stdout: bytes
    stderr: bytes
    wall_time_seconds: float
    timed_out: bool
    stdout_overflow: bool
    stderr_overflow: bool
    reader_error: str | None = None

    def summary(self) -> dict[str, Any]:
        """Return stable evidence suitable for content-addressed QA bundles.

        Wall-clock measurements are deliberately excluded: including them in
        ``author/qa_report.json`` made otherwise identical package archives
        differ from build to build.
        """

        return {
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "stdout_bytes": len(self.stdout),
            "stderr_bytes": len(self.stderr),
            "stdout_sha256": hashlib.sha256(self.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(self.stderr).hexdigest(),
            "stdout_overflow": self.stdout_overflow,
            "stderr_overflow": self.stderr_overflow,
            "reader_error": self.reader_error,
        }


def _run_bounded_subprocess(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    max_stdout_bytes: int = MAX_STDOUT_BYTES,
    max_stderr_bytes: int = MAX_STDERR_BYTES,
) -> BoundedProcessResult:
    """Run *command* without a shell while bounding time, stdout, and stderr."""

    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("verification command must contain nonempty strings")
    if timeout_seconds <= 0:
        raise ValueError("verification timeout must be positive")
    if max_stdout_bytes <= 0 or max_stderr_bytes <= 0:
        raise ValueError("verification output bounds must be positive")

    # Verification is not an OS sandbox, but it must not inherit Python import
    # hooks, user package paths, or nondeterministic BLAS thread settings.
    inherited = ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")
    environment = {key: os.environ[key] for key in inherited if key in os.environ}
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    started = time.perf_counter()
    process = subprocess.Popen(
        tuple(command),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        env=environment,
    )
    stdout = bytearray()
    stderr = bytearray()
    overflow: set[str] = set()
    reader_errors: list[str] = []

    def read_stream(
        stream: BinaryIO,
        destination: bytearray,
        limit: int,
        name: str,
    ) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                remaining = max(0, limit - len(destination))
                if remaining:
                    destination.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.add(name)
                    try:
                        process.kill()
                    except OSError:
                        pass
                    break
        except BaseException as error:  # surfaced in the result on the caller thread
            reader_errors.append(f"{type(error).__name__}: {error}")
            try:
                process.kill()
            except OSError:
                pass
        finally:
            stream.close()

    assert process.stdout is not None and process.stderr is not None
    readers = [
        threading.Thread(
            target=read_stream,
            args=(process.stdout, stdout, max_stdout_bytes, "stdout"),
            daemon=True,
        ),
        threading.Thread(
            target=read_stream,
            args=(process.stderr, stderr, max_stderr_bytes, "stderr"),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    for reader in readers:
        reader.join()
    elapsed = time.perf_counter() - started
    return BoundedProcessResult(
        returncode=process.returncode,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
        wall_time_seconds=elapsed,
        timed_out=timed_out,
        stdout_overflow="stdout" in overflow,
        stderr_overflow="stderr" in overflow,
        reader_error="; ".join(reader_errors) or None,
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _strict_json(text: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant {value!r}")

    return json.loads(text, parse_constant=reject_constant)


def _grader_payload(result: BoundedProcessResult) -> Mapping[str, Any] | None:
    if result.timed_out or result.stdout_overflow or result.reader_error:
        return None
    text = result.stdout.decode("utf-8", errors="replace")
    begin = text.find("{")
    end = text.rfind("}")
    if begin < 0 or end < begin:
        return None
    try:
        value = _strict_json(text[begin : end + 1])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _declared_weights(task: Mapping[str, Any]) -> dict[str, float]:
    evaluation = task.get("evaluation", {})
    if not isinstance(evaluation, Mapping):
        return {}
    raw_weights = evaluation.get("weights")
    if isinstance(raw_weights, Mapping):
        return {str(name): float(value) for name, value in raw_weights.items()}
    raw_metrics = evaluation.get("metrics")
    if isinstance(raw_metrics, Sequence) and not isinstance(raw_metrics, (str, bytes)):
        return {
            str(item["id"]): float(item["weight"])
            for item in raw_metrics
            if isinstance(item, Mapping) and "id" in item and "weight" in item
        }
    return {}


def _score_contract(
    payload: Mapping[str, Any] | None,
    task: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Verify that grader output implements the blueprint's weighted score."""

    weights = _declared_weights(task)
    failures: list[str] = []
    if payload is None:
        return False, {"failures": ["grader did not emit a JSON object"]}
    score = payload.get("score")
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(float(score))
        or not 0.0 <= float(score) <= 1.0
    ):
        failures.append("score must be a finite number in [0, 1]")
        numeric_score = None
    else:
        numeric_score = float(score)
    raw_components = payload.get("metric_scores")
    components: dict[str, float] = {}
    if not isinstance(raw_components, Mapping):
        failures.append("metric_scores must be an object")
    else:
        if set(raw_components) != set(weights):
            failures.append("metric_scores keys must exactly match declared weights")
        for name, value in raw_components.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 1.0
            ):
                failures.append(f"metric score {name!r} must be finite and in [0, 1]")
            else:
                components[str(name)] = float(value)
    passed = payload.get("passed") is True
    hard_gates_passed = payload.get("hard_gates_passed", passed)
    if not isinstance(hard_gates_passed, bool):
        failures.append("hard_gates_passed must be boolean when reported")
        hard_gates_passed = False
    expected = (
        sum(weights[name] * components.get(name, 0.0) for name in weights)
        if hard_gates_passed
        else 0.0
    )
    if numeric_score is not None and not math.isclose(
        numeric_score, expected, rel_tol=1e-9, abs_tol=1e-9
    ):
        failures.append("score does not equal the gate-conditioned weighted metric sum")
    return not failures, {
        "declared_weights": weights,
        "reported_score": numeric_score,
        "recomputed_score": expected,
        "hard_gates_passed": hard_gates_passed,
        "failures": failures,
    }


def _instance_ids(files: Sequence[BuildFile]) -> tuple[str, ...]:
    identifiers: set[str] = set()
    for item in files:
        parts = item.path.split("/")
        if len(parts) >= 4 and parts[:2] == ["input", "instances"]:
            identifiers.add(parts[2])
    return tuple(sorted(identifiers))


@dataclass(frozen=True, slots=True)
class _PreparedCase:
    reference_submission: Path
    mutant_submission: Path
    preparation: BoundedProcessResult | None = None
    alternative_submissions: tuple[tuple[str, Path], ...] = ()
    additional_mutants: tuple[tuple[str, Path], ...] = ()


class _PreparationError(RuntimeError):
    def __init__(self, message: str, process: BoundedProcessResult | None = None):
        super().__init__(message)
        self.process = process


_SYMPLECTIC_MUTANT = '''
"""Registered mutant: the canonical sign convention is globally reversed."""

import numpy as np


def symplectic_gradient(grad_h):
    values = np.asarray(grad_h)
    if values.ndim == 0 or values.shape[-1] <= 0 or values.shape[-1] % 2:
        raise ValueError("the last dimension must be positive and even")
    half = values.shape[-1] // 2
    return np.concatenate((-values[..., half:], values[..., :half]), axis=-1)
'''


_AUDIT_SOLVER_DRIVER = '''
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def main() -> int:
    solver_path = Path(sys.argv[1])
    case_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3])
    spec = importlib.util.spec_from_file_location("paper2ale_reference_solver", solver_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {solver_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    case = json.loads(case_path.read_text(encoding="utf-8"))
    answer = module.audit_case(case)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(answer, indent=2, sort_keys=True, allow_nan=False) + "\\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _prepare_symplectic(root: Path, instance_id: str, _: float) -> _PreparedCase:
    source = root / "example" / "reference_solution.py"
    if not source.is_file():
        raise _PreparationError("bundled symplectic reference solution is missing")
    reference = root / ".verification" / instance_id / "reference"
    mutant = root / ".verification" / instance_id / "mutant"
    (reference / "software").mkdir(parents=True, exist_ok=True)
    (mutant / "software").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, reference / "software" / "solution.py")
    (mutant / "software" / "solution.py").write_text(
        _SYMPLECTIC_MUTANT,
        encoding="utf-8",
    )
    return _PreparedCase(reference, mutant)


def _prepare_mass_spring(root: Path, instance_id: str, _: float) -> _PreparedCase:
    reference = (
        root
        / "example"
        / "instances"
        / instance_id
        / "reference_model.json"
    )
    if not reference.is_file():
        raise _PreparationError("bundled scalar reference model is missing")
    try:
        mutant_model = _strict_json(reference.read_text(encoding="utf-8"))
        output_layer = mutant_model["layers"][-1]
        output_layer["weight"] = [
            [-float(value) for value in row] for row in output_layer["weight"]
        ]
        output_layer["bias"] = [-float(value) for value in output_layer["bias"]]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _PreparationError(f"cannot construct mass-spring mutant: {error}") from error
    mutant = root / ".verification" / instance_id / "mutant_model.json"
    _write_json(mutant, mutant_model)
    return _PreparedCase(reference, mutant)


def _prepare_two_body(root: Path, instance_id: str, timeout: float) -> _PreparedCase:
    solver = root / "example" / "reference_solver.py"
    case = root / "input" / "instances" / instance_id / "case.json"
    if not solver.is_file() or not case.is_file():
        raise _PreparationError("bundled two-body solver or public case is missing")
    driver = root / ".verification" / "run_audit_solver.py"
    if not driver.exists():
        driver.parent.mkdir(parents=True, exist_ok=True)
        driver.write_text(_AUDIT_SOLVER_DRIVER, encoding="utf-8")
    reference = root / ".verification" / instance_id / "reference_audit.json"
    preparation = _run_bounded_subprocess(
        (sys.executable, "-I", str(driver), str(solver), str(case), str(reference)),
        cwd=root,
        timeout_seconds=timeout,
    )
    if (
        preparation.returncode != 0
        or preparation.timed_out
        or preparation.stdout_overflow
        or preparation.stderr_overflow
        or preparation.reader_error
        or not reference.is_file()
    ):
        raise _PreparationError(
            "bundled two-body reference solver did not produce an answer",
            preparation,
        )
    try:
        mutant_answer = _strict_json(reference.read_text(encoding="utf-8"))
        candidate = mutant_answer["candidate"]
        candidate["direction"] = "attractive"
        candidate["force_on_body_1"] = [
            -float(value) for value in candidate["force_on_body_1"]
        ]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _PreparationError(
            f"cannot construct two-body mutant: {error}", preparation
        ) from error
    mutant = root / ".verification" / instance_id / "mutant_audit.json"
    _write_json(mutant, mutant_answer)
    return _PreparedCase(reference, mutant, preparation)


def _prepare_bundled_json(root: Path, instance_id: str, _: float) -> _PreparedCase:
    """Use independently generated golden and realistic-mutant JSON fixtures."""

    directory = root / "example" / "instances" / instance_id
    reference = directory / "golden.json"
    mutant = directory / "mutant.json"
    if not reference.is_file() or not mutant.is_file():
        raise _PreparationError(
            "bundled hard-task golden or mutant JSON artifact is missing"
        )
    mutant_directory = directory / "mutants"
    additional = (
        tuple(
            (path.stem, path)
            for path in sorted(mutant_directory.glob("*.json"))
            if path.is_file() and not path.is_symlink()
        )
        if mutant_directory.is_dir() and not mutant_directory.is_symlink()
        else ()
    )
    visible_baseline = directory / "visible_baseline.json"
    alternatives = (
        (("visible-information-baseline", visible_baseline),)
        if visible_baseline.is_file() and not visible_baseline.is_symlink()
        else ()
    )
    return _PreparedCase(
        reference,
        mutant,
        alternative_submissions=alternatives,
        additional_mutants=additional,
    )


@dataclass(frozen=True, slots=True)
class _VerificationSpec:
    mutant_id: str
    prepare: Callable[[Path, str, float], _PreparedCase]


_REGISTERED: dict[tuple[str, str], _VerificationSpec] = {
    ("hnn", "hnn-symplectic-gradient"): _VerificationSpec(
        "symplectic-sign-reversed",
        _prepare_symplectic,
    ),
    ("hnn", "hnn-mass-spring"): _VerificationSpec(
        "scalar-output-sign-reversed",
        _prepare_mass_spring,
    ),
    ("hnn", "hnn-two-body-audit"): _VerificationSpec(
        "candidate-force-sign-reversed",
        _prepare_two_body,
    ),
    ("hnn_hard", "hnn-hard-coupled-identification"): _VerificationSpec(
        "remove-all-pair-couplings",
        _prepare_bundled_json,
    ),
    ("hnn_hard", "hnn-hard-variable-nbody"): _VerificationSpec(
        "reverse-all-pair-force-signs",
        _prepare_bundled_json,
    ),
    ("hnn_hard", "hnn-hard-canonical-recovery"): _VerificationSpec(
        "assume-observed-coordinates-are-canonical",
        _prepare_bundled_json,
    ),
}

# Declarative generic task IDs are intentionally dynamic.  They are still
# publication-verifiable because every accepted template compiles the same
# trusted evaluator/golden/mutant contract and cannot inject executable code.
_FAMILY_DEFAULTS: dict[str, _VerificationSpec] = {
    "generic": _VerificationSpec(
        "template-specific-realistic-mutant",
        _prepare_bundled_json,
    )
}


def register_task_verification(
    family: str,
    task_id: str,
    mutant_id: str,
    prepare: Callable[[Path, str, float], _PreparedCase],
    *,
    replace: bool = False,
) -> None:
    """Register a trusted golden/mutant preparation hook for a family task."""

    values = (family, task_id, mutant_id)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("family, task ID, and mutant ID must be nonempty strings")
    if not callable(prepare):
        raise TypeError("verification prepare hook must be callable")
    key = (family, task_id)
    if key in _REGISTERED and not replace:
        raise ValueError(f"verification hook for {family}/{task_id} is already registered")
    _REGISTERED[key] = _VerificationSpec(mutant_id, prepare)


def registered_task_ids(family: str | None = None) -> tuple[str, ...]:
    """Return task IDs with trusted reference and mutant verification hooks."""

    return tuple(
        sorted(
            task_id
            for (registered_family, task_id) in _REGISTERED
            if family is None or registered_family == family
        )
    )


def verification_catalog_identity() -> dict[str, Any]:
    """Stable verification-plan identity included in content build IDs."""

    return {
        "version": VERIFICATION_VERSION,
        "runtime": {
            "publication_verifier": _callable_implementation_identity(
                verify_task_publication
            ),
            "bounded_subprocess": _callable_implementation_identity(
                _run_bounded_subprocess
            ),
            "grader_runner": _callable_implementation_identity(_run_grader),
            "grader_payload": _callable_implementation_identity(_grader_payload),
            "score_contract": _callable_implementation_identity(_score_contract),
        },
        "tasks": [
            {
                "family": family,
                "task_id": task_id,
                "mutant_id": spec.mutant_id,
                "prepare": _callable_implementation_identity(spec.prepare),
            }
            for (family, task_id), spec in sorted(_REGISTERED.items())
        ],
        "family_defaults": [
            {
                "family": family,
                "mutant_id": spec.mutant_id,
                "prepare": _callable_implementation_identity(spec.prepare),
            }
            for family, spec in sorted(_FAMILY_DEFAULTS.items())
        ],
    }


def _run_grader(
    root: Path,
    submission: Path,
    instance_id: str,
    timeout: float,
) -> BoundedProcessResult:
    grader = root / "reference" / "grader.py"
    if not grader.is_file():
        raise _PreparationError("bundled evaluator grader is missing")
    return _run_bounded_subprocess(
        (
            sys.executable,
            "-I",
            str(grader),
            "--submission",
            str(submission),
            "--instance",
            instance_id,
        ),
        cwd=root,
        timeout_seconds=timeout,
    )


def _payload_sha256(payload: Mapping[str, Any] | None) -> str | None:
    if payload is None:
        return None
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_repeated_grader(
    root: Path,
    submission: Path,
    instance_id: str,
    timeout: float,
) -> tuple[BoundedProcessResult, Mapping[str, Any] | None, dict[str, Any]]:
    """Run a grader twice and compare stable process bytes and JSON payloads."""

    first = _run_grader(root, submission, instance_id, timeout)
    repeated = _run_grader(root, submission, instance_id, timeout)
    first_payload = _grader_payload(first)
    repeated_payload = _grader_payload(repeated)
    first_summary = first.summary()
    repeated_summary = repeated.summary()
    byte_identical = first.stdout == repeated.stdout and first.stderr == repeated.stderr
    process_state_identical = first_summary == repeated_summary
    first_payload_sha256 = _payload_sha256(first_payload)
    repeated_payload_sha256 = _payload_sha256(repeated_payload)
    payload_identical = first_payload_sha256 == repeated_payload_sha256
    identical = byte_identical and process_state_identical and payload_identical
    return first, first_payload, {
        "runs_compared": 2,
        "identical": identical,
        "byte_identical": byte_identical,
        "process_state_identical": process_state_identical,
        "payload_identical": payload_identical,
        "first_payload_sha256": first_payload_sha256,
        "repeated_payload_sha256": repeated_payload_sha256,
        "first_run": first_summary,
        "repeated_run": repeated_summary,
    }


def _snapshot(files: Sequence[BuildFile]) -> tuple[tuple[str, str, bool, str], ...]:
    return tuple(
        sorted(
            (
                item.path,
                item.visibility,
                item.executable,
                hashlib.sha256(item.data).hexdigest(),
            )
            for item in files
        )
    )


def _projection_archive_digest(files: Sequence[BuildFile]) -> str:
    """Exercise projection, manifest, modes, and ZIP determinism end to end."""

    with tempfile.TemporaryDirectory(prefix="paper2ale-reproduction-") as temporary:
        root = Path(temporary)
        projection = root / "author"
        write_projection(files, projection, "author")
        write_manifest(projection)
        archive = root / "author.zip"
        executable_paths = [item.path for item in files if item.executable]
        return write_deterministic_zip(
            projection,
            archive,
            executable_paths=executable_paths,
        )


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number > 0 else None


def _provenance_check(project: Mapping[str, Any]) -> dict[str, Any]:
    """Require exact, citable locks for registered publication fixtures."""

    sources = project.get("source_bundle")
    failures: list[dict[str, str]] = []
    snapshots = project.get("asset_snapshots", [])
    asset_ids = {
        str(snapshot.get("asset_id"))
        for snapshot in snapshots
        if isinstance(snapshot, Mapping) and snapshot.get("asset_id")
    } if isinstance(snapshots, list) else set()
    if not isinstance(sources, list) or not sources:
        failures.append({"source_id": "", "reason": "source_bundle is empty"})
        sources = []
    required = ("id", "kind", "uri", "version", "license", "citation", "retrieved_at")
    for index, source in enumerate(sources):
        if not isinstance(source, Mapping):
            failures.append(
                {"source_id": f"index-{index}", "reason": "source is not an object"}
            )
            continue
        source_id = str(source.get("id", f"index-{index}"))
        for field in required:
            value = source.get(field)
            if not isinstance(value, str) or not value.strip():
                failures.append(
                    {"source_id": source_id, "reason": f"missing exact {field}"}
                )
        kind = source.get("kind")
        if kind not in SOURCE_KINDS:
            failures.append(
                {
                    "source_id": source_id,
                    "reason": (
                        f"unknown source kind {kind!r}; expected one of "
                        f"{sorted(SOURCE_KINDS)}"
                    ),
                }
            )
        elif kind == "paper" and not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", ""))):
            failures.append(
                {"source_id": source_id, "reason": "paper bytes lack a lowercase SHA-256 lock"}
            )
        elif kind == "code" and not re.fullmatch(r"[0-9a-f]{40}", str(source.get("version", ""))):
            failures.append(
                {"source_id": source_id, "reason": "code version is not an exact Git commit"}
            )
        elif kind in {"document", "file"} and not re.fullmatch(
            r"[0-9a-f]{64}", str(source.get("sha256", ""))
        ):
            failures.append(
                {
                    "source_id": source_id,
                    "reason": f"{kind} bytes lack a lowercase SHA-256 lock",
                }
            )
        elif kind in {"dataset", "repository"}:
            asset_id = source.get("asset_id")
            if not isinstance(asset_id, str) or asset_id not in asset_ids:
                failures.append(
                    {
                        "source_id": source_id,
                        "reason": f"{kind} source lacks a linked verified asset snapshot",
                    }
                )
    return {
        "status": "passed" if not failures else "failed",
        "details": {
            "source_count": len(sources),
            "requirements": [
                f"source kind is exactly one of {sorted(SOURCE_KINDS)}",
                "nonempty URI, version, license, citation, and retrieval date",
                "paper byte SHA-256",
                "exact 40-hex code commit",
                "document/file byte SHA-256",
                "dataset/repository linkage to a verified file-tree snapshot",
            ],
            "resolved_asset_count": len(asset_ids),
            "failures": failures,
        },
    }


def verify_task_publication(
    project: Mapping[str, Any],
    task: Mapping[str, Any],
    files: Sequence[BuildFile],
    *,
    builder: Callable[..., Sequence[BuildFile]],
    master_seed: int,
    instances: int | None,
    build_context: Any | None = None,
) -> dict[str, Any] | None:
    """Run publication gates for a registered task, or return ``None``.

    Publication-smoke results intentionally measure only this
    verifier's wall clock and the generated in-memory file bytes; they do not
    measure peak memory and are not a full participant-training benchmark.
    """

    task_id = str(task.get("id", ""))
    family = str(task.get("family", ""))
    key = (family, task_id)
    spec = _REGISTERED.get(key, _FAMILY_DEFAULTS.get(family))
    if spec is None:
        return None
    started = time.perf_counter()
    materialized = tuple(files)
    identifiers = _instance_ids(materialized)
    package_bytes = sum(len(item.data) for item in materialized)

    reproduction_error: str | None = None
    mismatch_paths: list[str] = []
    repeated_count: int | None = None
    original_archive_sha256: str | None = None
    repeated_archive_sha256: str | None = None
    try:
        builder_keywords: dict[str, Any] = {
            "master_seed": master_seed,
            "instances": instances,
        }
        if build_context is not None:
            builder_keywords["build_context"] = build_context
        repeated = tuple(
            builder(
                dict(project),
                dict(task),
                **builder_keywords,
            )
        )
        repeated_count = len(repeated)
        original_snapshot = _snapshot(materialized)
        repeated_snapshot = _snapshot(repeated)
        original_by_path = {entry[0]: entry for entry in original_snapshot}
        repeated_by_path = {entry[0]: entry for entry in repeated_snapshot}
        mismatch_paths = sorted(
            path
            for path in set(original_by_path) | set(repeated_by_path)
            if original_by_path.get(path) != repeated_by_path.get(path)
        )
        original_archive_sha256 = _projection_archive_digest(materialized)
        repeated_archive_sha256 = _projection_archive_digest(repeated)
        reproducible = (
            not mismatch_paths
            and len(original_snapshot) == len(repeated_snapshot)
            and original_archive_sha256 == repeated_archive_sha256
        )
    except Exception as error:  # a failed repeat is a failed publication gate
        repeated = ()
        reproducible = False
        reproduction_error = f"{type(error).__name__}: {error}"
    budget = task.get("resource_budget", {})
    cpu_seconds = _positive_number(budget.get("cpu_seconds")) if isinstance(budget, Mapping) else None
    disk_mb = _positive_number(budget.get("disk_mb")) if isinstance(budget, Mapping) else None
    timeout = min(MAX_SUBPROCESS_SECONDS, cpu_seconds or MAX_SUBPROCESS_SECONDS)

    reference_results: list[dict[str, Any]] = []
    mutant_results: list[dict[str, Any]] = []
    runtime_execution_pairs = 0
    runtime_mismatches: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix=f"paper2ale-verify-{task_id}-") as temporary:
        root = Path(temporary)
        try:
            write_projection(materialized, root, "evaluator")
            projection_error: str | None = None
        except Exception as error:
            projection_error = f"{type(error).__name__}: {error}"

        for instance_id in identifiers:
            if projection_error is not None:
                failure = {
                    "instance_id": instance_id,
                    "passed": False,
                    "error": projection_error,
                }
                reference_results.append(failure)
                mutant_results.append(
                    {
                        "instance_id": instance_id,
                        "mutant_id": spec.mutant_id,
                        "rejected": False,
                        "error": projection_error,
                    }
                )
                continue
            try:
                prepared = spec.prepare(root, instance_id, timeout)
                reference_process, reference_payload, reference_reproduction = (
                    _run_repeated_grader(
                        root,
                        prepared.reference_submission,
                        instance_id,
                        timeout,
                    )
                )
                runtime_execution_pairs += 1
                if not reference_reproduction["identical"]:
                    runtime_mismatches.append(
                        {"instance_id": instance_id, "role": "reference"}
                    )
                reference_score_valid, reference_score_details = _score_contract(
                    reference_payload, task
                )
                reference_passed = (
                    reference_process.returncode == 0
                    and reference_payload is not None
                    and reference_payload.get("passed") is True
                    and reference_score_valid
                    and not reference_process.stderr_overflow
                    and reference_reproduction["identical"]
                )
                alternative_results: list[dict[str, Any]] = []
                for alternative_id, alternative_submission in prepared.alternative_submissions:
                    (
                        alternative_process,
                        alternative_payload,
                        alternative_reproduction,
                    ) = _run_repeated_grader(
                        root, alternative_submission, instance_id, timeout
                    )
                    runtime_execution_pairs += 1
                    if not alternative_reproduction["identical"]:
                        runtime_mismatches.append(
                            {
                                "instance_id": instance_id,
                                "role": "alternative",
                                "submission_id": alternative_id,
                            }
                        )
                    alternative_score_valid, alternative_score_details = _score_contract(
                        alternative_payload, task
                    )
                    alternative_passed = (
                        alternative_process.returncode == 0
                        and alternative_payload is not None
                        and alternative_payload.get("passed") is True
                        and alternative_score_valid
                        and not alternative_process.timed_out
                        and not alternative_process.stdout_overflow
                        and not alternative_process.stderr_overflow
                        and alternative_process.reader_error is None
                        and alternative_reproduction["identical"]
                    )
                    alternative_results.append(
                        {
                            "alternative_id": alternative_id,
                            "passed": alternative_passed,
                            "grader": alternative_process.summary(),
                            "score_contract": alternative_score_details,
                            "reproducibility": alternative_reproduction,
                        }
                    )
                reference_passed = reference_passed and all(
                    item["passed"] for item in alternative_results
                )
                reference_entry: dict[str, Any] = {
                    "instance_id": instance_id,
                    "passed": reference_passed,
                    "grader": reference_process.summary(),
                    "score_contract": reference_score_details,
                    "reproducibility": reference_reproduction,
                    "alternative_implementations": alternative_results,
                }
                if prepared.preparation is not None:
                    reference_entry["reference_preparation"] = prepared.preparation.summary()
                reference_results.append(reference_entry)

                mutant_suite = (
                    (spec.mutant_id, prepared.mutant_submission),
                    *prepared.additional_mutants,
                )
                for mutant_id, mutant_submission in mutant_suite:
                    mutant_process, mutant_payload, mutant_reproduction = (
                        _run_repeated_grader(
                            root,
                            mutant_submission,
                            instance_id,
                            timeout,
                        )
                    )
                    runtime_execution_pairs += 1
                    if not mutant_reproduction["identical"]:
                        runtime_mismatches.append(
                            {
                                "instance_id": instance_id,
                                "role": "mutant",
                                "submission_id": mutant_id,
                            }
                        )
                    mutant_score_valid, mutant_score_details = _score_contract(
                        mutant_payload, task
                    )
                    rejected = (
                        mutant_process.returncode not in (None, 0)
                        and mutant_payload is not None
                        and mutant_payload.get("passed") is False
                        and mutant_score_valid
                        and not mutant_process.timed_out
                        and not mutant_process.stdout_overflow
                        and not mutant_process.stderr_overflow
                        and mutant_process.reader_error is None
                        and mutant_reproduction["identical"]
                    )
                    mutant_results.append(
                        {
                            "instance_id": instance_id,
                            "mutant_id": mutant_id,
                            "rejected": rejected,
                            "grader": mutant_process.summary(),
                            "score_contract": mutant_score_details,
                            "reproducibility": mutant_reproduction,
                        }
                    )
            except _PreparationError as error:
                preparation = None if error.process is None else error.process.summary()
                reference_results.append(
                    {
                        "instance_id": instance_id,
                        "passed": False,
                        "error": str(error),
                        "reference_preparation": preparation,
                    }
                )
                mutant_results.append(
                    {
                        "instance_id": instance_id,
                        "mutant_id": spec.mutant_id,
                        "rejected": False,
                        "error": str(error),
                        "reference_preparation": preparation,
                    }
                )
            except Exception as error:
                message = f"{type(error).__name__}: {error}"
                reference_results.append(
                    {"instance_id": instance_id, "passed": False, "error": message}
                )
                mutant_results.append(
                    {
                        "instance_id": instance_id,
                        "mutant_id": spec.mutant_id,
                        "rejected": False,
                        "error": message,
                    }
                )

    configured_count = task.get("instances") if instances is None else instances
    expected_identifiers = (
        tuple(f"{index:03d}" for index in range(configured_count))
        if isinstance(configured_count, int)
        and not isinstance(configured_count, bool)
        and configured_count > 0
        else ()
    )
    instance_set_complete = bool(identifiers) and identifiers == expected_identifiers
    reference_passed = (
        instance_set_complete
        and len(reference_results) == len(identifiers)
        and all(result["passed"] for result in reference_results)
    )
    mutants_rejected = (
        instance_set_complete
        and len(mutant_results) >= len(identifiers)
        and {result["instance_id"] for result in mutant_results} == set(identifiers)
        and all(result["rejected"] for result in mutant_results)
    )
    runtime_outputs_reproducible = not runtime_mismatches
    all_reproducible = reproducible and runtime_outputs_reproducible

    total_elapsed = time.perf_counter() - started
    disk_budget_bytes = None if disk_mb is None else int(disk_mb * _MEBIBYTE)
    resource_measured = cpu_seconds is not None and disk_budget_bytes is not None
    within_cpu = cpu_seconds is not None and total_elapsed <= cpu_seconds
    within_disk = disk_budget_bytes is not None and package_bytes <= disk_budget_bytes
    resource_status = "passed" if resource_measured and within_cpu and within_disk else "failed"

    checks = {
        "provenance": _provenance_check(project),
        "runtime_reference": {
            "status": "passed" if reference_passed else "failed",
            "details": {
                "configured_instance_count": configured_count,
                "expected_instances": list(expected_identifiers),
                "discovered_instances": list(identifiers),
                "all_instances_discovered": instance_set_complete,
                "instances": reference_results,
                "subprocess_timeout_seconds": timeout,
                "stdout_limit_bytes": MAX_STDOUT_BYTES,
                "stderr_limit_bytes": MAX_STDERR_BYTES,
            },
        },
        "mutation_resistance": {
            "status": "passed" if mutants_rejected else "failed",
            "details": {
                "registered_mutant": spec.mutant_id,
                "registered_mutants": sorted(
                    {result["mutant_id"] for result in mutant_results}
                ),
                "required_rejections": len(mutant_results),
                "instances": mutant_results,
            },
        },
        "publication_smoke_budget": {
            "status": resource_status,
            "details": {
                "evidence_kind": "publication_smoke_test",
                "wall_time_measured": True,
                "cpu_seconds_budget": cpu_seconds,
                "within_cpu_seconds_budget": within_cpu,
                "measured_package_bytes": package_bytes,
                "package_measurement_scope": "generated BuildFile payload bytes before QA report, manifests, and archives",
                "disk_bytes_budget": disk_budget_bytes,
                "within_disk_budget": within_disk,
                "peak_memory_bytes": None,
                "limitations": "Publication smoke only: wall time covers trusted reference/mutant verification and a repeated builder run; peak memory is not measured. This is not a claim about participant solve time, CPU utilization, training cost, or temporary solve disk usage.",
            },
        },
        "reproducibility": {
            "status": "passed" if all_reproducible else "failed",
            "details": {
                "builder_runs_compared": 2,
                "byte_identical": reproducible,
                "archive_byte_identical": (
                    original_archive_sha256 is not None
                    and original_archive_sha256 == repeated_archive_sha256
                ),
                "original_archive_sha256": original_archive_sha256,
                "repeated_archive_sha256": repeated_archive_sha256,
                "original_file_count": len(materialized),
                "repeated_file_count": repeated_count,
                "mismatch_paths": mismatch_paths,
                "error": reproduction_error,
                "grader_runs_per_submission": 2,
                "grader_execution_pairs_compared": runtime_execution_pairs,
                "runtime_output_reproducible": runtime_outputs_reproducible,
                "runtime_mismatches": runtime_mismatches,
            },
        },
    }
    issues = []
    for gate, check in checks.items():
        if check["status"] != "passed":
            issues.append(
                {
                    "code": "publication_gate_failed",
                    "message": f"dynamic publication gate {gate!r} did not pass",
                    "path": f"verification/{gate}",
                    "severity": "warning",
                }
            )
    return {"checks": checks, "issues": issues, "applicable": True}


__all__ = [
    "BoundedProcessResult",
    "MAX_STDERR_BYTES",
    "MAX_STDOUT_BYTES",
    "MAX_SUBPROCESS_SECONDS",
    "VERIFICATION_VERSION",
    "register_task_verification",
    "registered_task_ids",
    "verification_catalog_identity",
    "verify_task_publication",
]
