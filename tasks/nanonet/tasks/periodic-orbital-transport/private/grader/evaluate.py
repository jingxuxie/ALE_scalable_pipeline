#!/usr/bin/env python3
"""Private behavioral evaluator for periodic orbital transport submissions.

Direct ``--submission`` execution is a trusted-author calibration convenience,
not a hostile-code sandbox.  Production runners must execute participant code
in an outer OS sandbox and pass the resulting files to ``--artifacts-only``.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

try:
    from . import science
except ImportError:  # Direct script execution.
    import science


TASK_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUTS = TASK_ROOT / "private" / "hidden_inputs"
DEFAULT_REFERENCES = TASK_ROOT / "private" / "reference"

SCHEMA_VERSION = "periodic-orbital-transport-evaluation/v1"
REQUIRED_OUTPUTS = {
    "hamiltonian.npz",
    "self_energies.npz",
    "spectra.npz",
    "diagnostics.json",
}
NPZ_MEMBERS = {
    "hamiltonian.npz": {"h0.npy", "h1.npy", "basis_site.npy"},
    "self_energies.npz": {
        "energies.npy",
        "sigma_left.npy",
        "sigma_right.npy",
    },
    "spectra.npz": {
        "phases.npy",
        "bands.npy",
        "energies.npy",
        "dos_total.npy",
        "ldos_cells.npy",
        "transmission.npy",
    },
}

MAX_SOURCE_BYTES = 200 * 1024
MAX_AGGREGATE_OUTPUT_BYTES = 50 * 1024 * 1024
MAX_CONSOLE_BYTES = 1024 * 1024
MAX_DIAGNOSTICS_BYTES = 64 * 1024
CASE_TIMEOUT_SECONDS = 120.0
SUITE_TIMEOUT_SECONDS = 30.0 * 60.0
PROCESS_POLL_SECONDS = 0.05

# These values are private calibration parameters. They allow independent
# double-precision surface solvers to disagree slightly near band edges.
TOLERANCES = {
    "hamiltonian": (2.0e-12, 2.0e-11),
    "bands": (2.0e-9, 2.0e-9),
    "self_energy": (5.0e-8, 2.0e-7),
    "dos": (5.0e-8, 3.0e-7),
    "ldos": (5.0e-8, 3.0e-7),
    "transmission": (5.0e-8, 5.0e-7),
    "consistency_bands": (3.0e-10, 2.0e-10),
    "consistency_dos": (3.0e-9, 3.0e-8),
    "consistency_transmission": (3.0e-9, 3.0e-8),
    "diagnostic_hermiticity": (1.0e-12, 1.0e-5),
}
METRIC_WEIGHTS = {
    "assembly": 0.18,
    "bands": 0.12,
    "self_energies": 0.24,
    "dos_ldos": 0.20,
    "transmission": 0.18,
    "evidence_consistency": 0.08,
}
MANDATORY_MINIMA = {
    "assembly": 0.90,
    "bands": 0.90,
    "self_energies": 0.82,
    "dos_ldos": 0.85,
    "transmission": 0.80,
    "evidence_consistency": 0.75,
}
TOTAL_PASS_THRESHOLD = 0.90

FORBIDDEN_IMPORT_ROOTS = {
    "_socket",
    "aiohttp",
    "asyncio",
    "concurrent",
    "ctypes",
    "ftplib",
    "http",
    "importlib",
    "joblib",
    "marshal",
    "multiprocessing",
    "paramiko",
    "pickle",
    "psutil",
    "requests",
    "shelve",
    "smtplib",
    "socket",
    "ssl",
    "subprocess",
    "telnetlib",
    "urllib",
    "webbrowser",
    "pty",
}
FORBIDDEN_OS_CALLS = {
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "fork",
    "forkpty",
    "kill",
    "killpg",
    "popen",
    "posix_spawn",
    "posix_spawnp",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "startfile",
    "system",
}
FORBIDDEN_DYNAMIC_CALLS = {"__import__", "compile", "eval", "exec"}
FORBIDDEN_SOURCE_MARKERS = {
    "2010.07463",
    "author/reference",
    "authoring/sources",
    "arxiv.org",
    "evaluation_spec",
    "hidden_inputs",
    "nanonet",
    "paper2ale",
    "private/grader",
    "private/reference",
    "reference_solver",
    "source_manifest",
}


class GateFailure(ValueError):
    """A structural, size, execution, or security failure."""


class ConfigurationFailure(RuntimeError):
    """The private input/reference suite is inconsistent."""


def _clamp_score(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def _is_link_like(path: Path) -> bool:
    """Reject symlinks and Windows directory junction/reparse indirections."""

    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        try:
            if is_junction():
                return True
        except OSError:
            return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _check_submission_source(path: Path) -> bytes:
    if _is_link_like(path) or not path.exists():
        raise GateFailure("submission must be an existing non-symlink file")
    try:
        mode = path.lstat().st_mode
        size = path.stat().st_size
    except OSError as exc:
        raise GateFailure(f"cannot inspect submission: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise GateFailure("submission must be a regular file")
    if size > MAX_SOURCE_BYTES:
        raise GateFailure(f"submission source exceeds {MAX_SOURCE_BYTES} bytes")
    try:
        source_bytes = path.read_bytes()
        source_text = source_bytes.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise GateFailure(f"submission is not readable UTF-8 Python source: {exc}") from exc

    normalized = source_text.lower().replace("\\", "/")
    present_markers = sorted(marker for marker in FORBIDDEN_SOURCE_MARKERS if marker in normalized)
    if present_markers:
        raise GateFailure(
            "submission contains forbidden source/private indicators: "
            + ", ".join(present_markers)
        )
    try:
        tree = ast.parse(source_text, filename="solution.py")
    except SyntaxError as exc:
        raise GateFailure(f"submission is not valid Python syntax: {exc.msg}") from exc

    aliases: dict[str, str] = {}
    violations: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                aliases[alias.asname or root] = alias.name
                if root in FORBIDDEN_IMPORT_ROOTS:
                    violations.add(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                violations.add(f"from {module} import ...")
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{module}.{alias.name}".strip(".")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted_name(node.func)
        if name is None:
            continue
        first, separator, rest = name.partition(".")
        resolved = aliases.get(first, first) + (separator + rest if separator else "")
        if resolved in FORBIDDEN_DYNAMIC_CALLS or name in FORBIDDEN_DYNAMIC_CALLS:
            violations.add(f"dynamic call {name}")
        if resolved.startswith("os.") and resolved.rsplit(".", 1)[-1] in FORBIDDEN_OS_CALLS:
            violations.add(f"process call {resolved}")
        if resolved.startswith("asyncio.") and "subprocess" in resolved:
            violations.add(f"process call {resolved}")

    if violations:
        raise GateFailure(
            "submission uses forbidden network/process/dynamic facilities: "
            + ", ".join(sorted(violations))
        )
    return source_bytes


def _scrubbed_environment(temporary_root: Path) -> dict[str, str]:
    allowed = {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "WINDIR",
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "TEMP": str(temporary_root),
            "TMP": str(temporary_root),
            "TMPDIR": str(temporary_root),
        }
    )
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONSTARTUP", None)
    environment.pop("PYTHONINSPECT", None)
    return environment


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    leader_running = process.poll() is None
    if os.name == "nt":
        # CREATE_NEW_PROCESS_GROUP alone does not recursively terminate children.
        # taskkill /T is the standard-library-accessible process-tree fallback on
        # Windows; the direct process methods remain a defensive fallback.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5.0,
            )
        except (OSError, subprocess.SubprocessError):
            if leader_running:
                process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            if leader_running:
                process.terminate()
    if leader_running:
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3.0)
    if os.name != "nt":
        # The group can outlive a normally exiting leader.  Kill any remaining
        # descendants before the isolated directory is released.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass


def _run_solver(
    source: bytes,
    input_path: Path,
    temporary_root: Path,
    *,
    suite_deadline: float,
) -> Path:
    solver_path = temporary_root / "solver.py"
    model_path = temporary_root / "model.json"
    output_path = temporary_root / "output"
    stdout_path = temporary_root / "stdout.log"
    stderr_path = temporary_root / "stderr.log"
    solver_path.write_bytes(source)
    shutil.copyfile(input_path, model_path)

    command = [
        sys.executable,
        "solver.py",
        "--input",
        "model.json",
        "--output",
        "output",
    ]
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        try:
            process_options: dict[str, Any] = {}
            if os.name == "nt":
                process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                process_options["start_new_session"] = True
            process = subprocess.Popen(
                command,
                cwd=temporary_root,
                env=_scrubbed_environment(temporary_root),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                shell=False,
                **process_options,
            )
        except OSError as exc:
            raise GateFailure(f"could not start submission: {exc}") from exc

        try:
            case_deadline = time.monotonic() + CASE_TIMEOUT_SECONDS
            deadline = min(case_deadline, suite_deadline)
            while process.poll() is None:
                stdout_handle.flush()
                stderr_handle.flush()
                try:
                    console_bytes = stdout_path.stat().st_size + stderr_path.stat().st_size
                except OSError as exc:
                    raise GateFailure("submission tampered with evaluator console files") from exc
                if console_bytes > MAX_CONSOLE_BYTES:
                    raise GateFailure(
                        f"submission console output exceeds {MAX_CONSOLE_BYTES} bytes"
                    )
                if time.monotonic() >= deadline:
                    if deadline == suite_deadline:
                        raise GateFailure(
                            f"submission suite exceeded {SUITE_TIMEOUT_SECONDS:g} seconds"
                        )
                    raise GateFailure(
                        f"submission exceeded {CASE_TIMEOUT_SECONDS:g} seconds"
                    )
                time.sleep(PROCESS_POLL_SECONDS)
            return_code = process.returncode
            _terminate_process(process)
        except BaseException:
            if process.poll() is None:
                _terminate_process(process)
            raise

    if stdout_path.stat().st_size + stderr_path.stat().st_size > MAX_CONSOLE_BYTES:
        raise GateFailure(f"submission console output exceeds {MAX_CONSOLE_BYTES} bytes")
    if return_code != 0:
        raise GateFailure(f"submission exited with status {return_code}")
    return output_path


def _expected_npz_arrays(
    instance: Mapping[str, Any],
) -> dict[str, dict[str, tuple[np.dtype[Any], tuple[int, ...]]]]:
    _h0, _h1, basis_site = science.assemble_blocks(instance)
    basis_size = int(basis_site.size)
    energy_count = len(instance["energy_grid"])
    phase_count = len(instance["phase_grid"])
    cells = int(instance["device"]["cells"])
    complex_dtype = np.dtype(np.complex128)
    float_dtype = np.dtype(np.float64)
    integer_dtype = np.dtype(np.int64)
    return {
        "hamiltonian.npz": {
            "h0.npy": (complex_dtype, (basis_size, basis_size)),
            "h1.npy": (complex_dtype, (basis_size, basis_size)),
            "basis_site.npy": (integer_dtype, (basis_size,)),
        },
        "self_energies.npz": {
            "energies.npy": (float_dtype, (energy_count,)),
            "sigma_left.npy": (
                complex_dtype,
                (energy_count, basis_size, basis_size),
            ),
            "sigma_right.npy": (
                complex_dtype,
                (energy_count, basis_size, basis_size),
            ),
        },
        "spectra.npz": {
            "phases.npy": (float_dtype, (phase_count,)),
            "bands.npy": (float_dtype, (phase_count, basis_size)),
            "energies.npy": (float_dtype, (energy_count,)),
            "dos_total.npy": (float_dtype, (energy_count,)),
            "ldos_cells.npy": (float_dtype, (energy_count, cells)),
            "transmission.npy": (float_dtype, (energy_count,)),
        },
    }


def _inspect_npz_archive(
    path: Path,
    expected_arrays: Mapping[str, tuple[np.dtype[Any], tuple[int, ...]]],
) -> int:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                raise GateFailure(f"{path.name} contains duplicate archive members")
            if set(names) != set(expected_arrays):
                raise GateFailure(
                    f"{path.name} archive members do not match the output contract"
                )
            for member in members:
                if (
                    member.is_dir()
                    or member.flag_bits & 0x1
                    or "/" in member.filename
                    or "\\" in member.filename
                ):
                    raise GateFailure(f"{path.name} contains an unsafe archive member")
                with archive.open(member, "r") as stream:
                    version = np.lib.format.read_magic(stream)
                    if version == (1, 0):
                        shape, fortran_order, dtype = np.lib.format.read_array_header_1_0(
                            stream, max_header_size=4096
                        )
                    elif version in {(2, 0), (3, 0)}:
                        shape, fortran_order, dtype = np.lib.format.read_array_header_2_0(
                            stream, max_header_size=4096
                        )
                    else:
                        raise GateFailure(
                            f"{path.name}:{member.filename} uses unsupported NPY version {version}"
                        )
                    expected_dtype, expected_shape = expected_arrays[member.filename]
                    if np.dtype(dtype) != expected_dtype or tuple(shape) != expected_shape:
                        raise GateFailure(
                            f"{path.name}:{member.filename} dtype/shape does not match the input"
                        )
                    if bool(fortran_order):
                        raise GateFailure(
                            f"{path.name}:{member.filename} must use C array order"
                        )
                    payload_bytes = math.prod(expected_shape) * expected_dtype.itemsize
                    if member.file_size - stream.tell() != payload_bytes:
                        raise GateFailure(
                            f"{path.name}:{member.filename} has an invalid NPY payload size"
                        )
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise GateFailure(
                    f"{path.name} has a corrupt archive member: {corrupt_member}"
                )
            return int(sum(member.file_size for member in members))
    except GateFailure:
        raise
    except (
        OSError,
        EOFError,
        ValueError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        raise GateFailure(f"{path.name} is not a safe NPZ archive: {exc}") from exc


def _validate_output_tree(
    output_dir: Path,
    instance: Mapping[str, Any],
    *,
    allowed_root: Path | None = None,
) -> tuple[int, int]:
    if _is_link_like(output_dir) or not output_dir.is_dir():
        raise GateFailure("output is missing or is not a regular directory")
    try:
        output_resolved = output_dir.resolve(strict=True)
        if allowed_root is not None:
            allowed_resolved = allowed_root.resolve(strict=True)
            if output_resolved != allowed_resolved and output_resolved.parent != allowed_resolved:
                raise GateFailure("output directory escapes the isolated case directory")
    except OSError as exc:
        raise GateFailure(f"cannot resolve output directory: {exc}") from exc
    try:
        entries = list(output_dir.iterdir())
    except OSError as exc:
        raise GateFailure(f"cannot inspect output directory: {exc}") from exc
    names = {entry.name for entry in entries}
    if names != REQUIRED_OUTPUTS:
        missing = sorted(REQUIRED_OUTPUTS - names)
        unexpected = sorted(names - REQUIRED_OUTPUTS)
        raise GateFailure(f"output artifact set mismatch; missing={missing}, unexpected={unexpected}")

    expected_npz_arrays = _expected_npz_arrays(instance)
    disk_bytes = 0
    expanded_bytes = 0
    for entry in entries:
        try:
            mode = entry.lstat().st_mode
            resolved = entry.resolve(strict=True)
        except OSError as exc:
            raise GateFailure(f"cannot inspect output artifact {entry.name}: {exc}") from exc
        if _is_link_like(entry) or not stat.S_ISREG(mode) or resolved.parent != output_resolved:
            raise GateFailure(f"output artifact is not a regular file: {entry.name}")
        disk_bytes += entry.stat().st_size
        if entry.name in NPZ_MEMBERS:
            expanded_bytes += _inspect_npz_archive(
                entry, expected_npz_arrays[entry.name]
            )
        else:
            if entry.stat().st_size > MAX_DIAGNOSTICS_BYTES:
                raise GateFailure(
                    f"diagnostics.json exceeds {MAX_DIAGNOSTICS_BYTES} bytes"
                )
            expanded_bytes += entry.stat().st_size
    return int(disk_bytes), int(expanded_bytes)


def _read_submitted_outputs(
    output_dir: Path, instance: Mapping[str, Any]
) -> dict[str, Any]:
    """Translate malformed-container failures at the untrusted parse boundary."""

    try:
        return science.read_outputs(output_dir, instance)
    except (
        OSError,
        EOFError,
        ValueError,
        RecursionError,
        MemoryError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        science.ScienceError,
    ) as exc:
        raise GateFailure(
            f"malformed output artifact: {type(exc).__name__}: {exc}"
        ) from exc


def _error_stats(
    actual: np.ndarray,
    expected: np.ndarray,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, float]:
    observed = np.asarray(actual)
    truth = np.asarray(expected)
    if observed.shape != truth.shape:
        raise ValueError(f"shape mismatch in metric: {observed.shape} != {truth.shape}")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        difference = np.abs(observed - truth)
        scale = absolute_tolerance + relative_tolerance * np.abs(truth)
        ratio = difference / scale
        relative = difference / np.maximum(np.abs(truth), absolute_tolerance)
    ratio = np.nan_to_num(ratio, nan=1.0e12, posinf=1.0e12, neginf=1.0e12)
    relative = np.nan_to_num(relative, nan=1.0e12, posinf=1.0e12, neginf=1.0e12)
    bounded = np.minimum(ratio, 1.0e12)
    rms = float(np.sqrt(np.mean(np.square(bounded))))
    maximum = float(np.max(bounded))
    # Retain RMS sensitivity without allowing a single bad band edge or
    # transmission point to disappear in a long grid.
    combined = float(max(rms, 0.25 * maximum))
    safe_difference = np.nan_to_num(
        difference,
        nan=np.finfo(np.float64).max,
        posinf=np.finfo(np.float64).max,
        neginf=np.finfo(np.float64).max,
    )
    max_absolute = float(np.max(safe_difference))
    max_relative = float(np.max(relative))
    return {
        "normalized_error": combined,
        "normalized_rms_error": rms,
        "max_normalized_error": maximum,
        "max_absolute_error": max_absolute,
        "max_relative_error": max_relative,
    }


def _quality_score(normalized_error: float) -> float:
    if not math.isfinite(normalized_error):
        return 0.0
    if normalized_error <= 1.0:
        return 1.0
    if normalized_error >= 100.0:
        return 0.0
    return _clamp_score(1.0 - math.log10(normalized_error) / 2.0)


def _score_arrays(
    actual: np.ndarray,
    expected: np.ndarray,
    tolerance: tuple[float, float],
) -> tuple[float, dict[str, float]]:
    stats = _error_stats(actual, expected, *tolerance)
    return _quality_score(stats["normalized_error"]), stats


def _residual_score(value: float, *, excellent: float, unacceptable: float) -> float:
    if not math.isfinite(value) or value >= unacceptable:
        return 0.0
    if value <= excellent:
        return 1.0
    log_span = math.log10(unacceptable) - math.log10(excellent)
    return _clamp_score((math.log10(unacceptable) - math.log10(value)) / log_span)


def _frobenius(matrix: np.ndarray) -> float:
    return float(np.linalg.norm(matrix, ord="fro"))


def _hermiticity_residual(matrix: np.ndarray) -> float:
    return _frobenius(matrix - matrix.conj().T) / max(1.0, _frobenius(matrix))


def _surface_quality(
    instance: Mapping[str, Any],
    submitted: Mapping[str, Any],
    trusted_h0: np.ndarray,
    trusted_h1: np.ndarray,
) -> tuple[float, float]:
    identity = np.eye(trusted_h0.shape[0], dtype=np.complex128)
    energies = np.asarray(instance["energy_grid"], dtype=np.float64)
    eta = float(instance["eta"])
    cases = (
        (
            np.asarray(submitted["sigma_left"], dtype=np.complex128),
            trusted_h1.conj().T,
            float(instance["device"]["contact_scale_left"]),
        ),
        (
            np.asarray(submitted["sigma_right"], dtype=np.complex128),
            trusted_h1,
            float(instance["device"]["contact_scale_right"]),
        ),
    )
    max_dyson = 0.0
    max_causality = 0.0
    for sigmas, outward, contact_scale in cases:
        for index, energy in enumerate(energies):
            sigma = sigmas[index]
            lead_sigma = sigma / (contact_scale * contact_scale)
            effective = complex(float(energy), eta) * identity - trusted_h0 - lead_sigma
            try:
                g_surface = np.linalg.solve(effective, identity)
                fixed_value = outward @ g_surface @ outward.conj().T
                residual = _frobenius(lead_sigma - fixed_value) / max(
                    1.0, _frobenius(lead_sigma), _frobenius(fixed_value)
                )
            except np.linalg.LinAlgError:
                residual = math.inf
            if not math.isfinite(residual):
                residual = math.inf
            max_dyson = max(max_dyson, residual)

            gamma = 1.0j * (sigma - sigma.conj().T)
            hermitian_gamma = 0.5 * (gamma + gamma.conj().T)
            try:
                eigenvalues = np.linalg.eigvalsh(hermitian_gamma)
                negative = max(0.0, -float(np.min(eigenvalues)))
                causality = negative / max(1.0, float(np.max(np.abs(eigenvalues))))
            except np.linalg.LinAlgError:
                causality = math.inf
            if not math.isfinite(causality):
                causality = math.inf
            max_causality = max(max_causality, causality)
    if not math.isfinite(max_dyson):
        max_dyson = 1.0e300
    if not math.isfinite(max_causality):
        max_causality = 1.0e300
    return float(max_dyson), float(max_causality)


def _submitted_device_hamiltonian(
    instance: Mapping[str, Any],
    h0: np.ndarray,
    h1: np.ndarray,
    basis_site: np.ndarray,
) -> np.ndarray:
    cells = int(instance["device"]["cells"])
    basis_size = h0.shape[0]
    device = np.zeros((cells * basis_size, cells * basis_size), dtype=np.complex128)
    site_potential = np.asarray(instance["device"]["site_potential"], dtype=np.float64)
    bond_scale = np.asarray(instance["device"]["bond_scale"], dtype=np.float64)
    for cell in range(cells):
        current = slice(cell * basis_size, (cell + 1) * basis_size)
        device[current, current] = h0
        diagonal = site_potential[cell, basis_site]
        device[current, current] += np.diag(diagonal)
        if cell + 1 < cells:
            following = slice((cell + 1) * basis_size, (cell + 2) * basis_size)
            coupling = bond_scale[cell] * h1
            device[current, following] = coupling
            device[following, current] = coupling.conj().T
    return device


def _recompute_from_submission(
    instance: Mapping[str, Any], submitted: Mapping[str, Any]
) -> dict[str, Any]:
    h0 = np.asarray(submitted["h0"], dtype=np.complex128)
    h1 = np.asarray(submitted["h1"], dtype=np.complex128)
    basis_site = np.asarray(submitted["basis_site"], dtype=np.int64)
    phases = np.asarray(instance["phase_grid"], dtype=np.float64)
    energies = np.asarray(instance["energy_grid"], dtype=np.float64)
    eta = float(instance["eta"])
    cells = int(instance["device"]["cells"])
    basis_size = h0.shape[0]

    recomputed_bands = np.empty((len(phases), basis_size), dtype=np.float64)
    for index, phase in enumerate(phases):
        bloch = h0 + h1 * np.exp(1.0j * phase) + h1.conj().T * np.exp(-1.0j * phase)
        recomputed_bands[index] = np.linalg.eigvalsh(bloch)

    h_device = _submitted_device_hamiltonian(instance, h0, h1, basis_site)
    device_identity = np.eye(h_device.shape[0], dtype=np.complex128)
    first = slice(0, basis_size)
    last = slice((cells - 1) * basis_size, cells * basis_size)
    dos_total = np.empty(len(energies), dtype=np.float64)
    ldos_cells = np.empty((len(energies), cells), dtype=np.float64)
    transmission = np.empty(len(energies), dtype=np.float64)
    sigma_left = np.asarray(submitted["sigma_left"], dtype=np.complex128)
    sigma_right = np.asarray(submitted["sigma_right"], dtype=np.complex128)

    for energy_index, energy in enumerate(energies):
        inverse_green = complex(float(energy), eta) * device_identity - h_device
        inverse_green[first, first] -= sigma_left[energy_index]
        inverse_green[last, last] -= sigma_right[energy_index]
        green = np.linalg.solve(inverse_green, device_identity)
        dos_total[energy_index] = -float(np.imag(np.trace(green))) / math.pi
        for cell in range(cells):
            block = slice(cell * basis_size, (cell + 1) * basis_size)
            ldos_cells[energy_index, cell] = (
                -float(np.imag(np.trace(green[block, block]))) / math.pi
            )
        gamma_left = 1.0j * (sigma_left[energy_index] - sigma_left[energy_index].conj().T)
        gamma_right = 1.0j * (
            sigma_right[energy_index] - sigma_right[energy_index].conj().T
        )
        green_first_last = green[first, last]
        transmission[energy_index] = float(
            np.real(
                np.trace(
                    gamma_left
                    @ green_first_last
                    @ gamma_right
                    @ green_first_last.conj().T
                )
            )
        )

    arrays = (recomputed_bands, dos_total, ldos_cells, transmission)
    if not all(np.all(np.isfinite(array)) for array in arrays):
        raise np.linalg.LinAlgError("recomputed submission observables are non-finite")
    max_hermiticity = max(_hermiticity_residual(h0), _hermiticity_residual(h_device))
    if not math.isfinite(max_hermiticity):
        raise np.linalg.LinAlgError("recomputed Hermiticity residual is non-finite")
    return {
        "bands": recomputed_bands,
        "dos_total": dos_total,
        "ldos_cells": ldos_cells,
        "transmission": transmission,
        "max_hermiticity_residual": max_hermiticity,
    }


def _evidence_consistency(
    instance: Mapping[str, Any],
    submitted: Mapping[str, Any],
) -> tuple[float, dict[str, Any]]:
    try:
        recomputed = _recompute_from_submission(instance, submitted)
        band_score, band_error = _score_arrays(
            submitted["bands"], recomputed["bands"], TOLERANCES["consistency_bands"]
        )
        dos_score, dos_error = _score_arrays(
            submitted["dos_total"],
            recomputed["dos_total"],
            TOLERANCES["consistency_dos"],
        )
        ldos_score, ldos_error = _score_arrays(
            submitted["ldos_cells"],
            recomputed["ldos_cells"],
            TOLERANCES["consistency_dos"],
        )
        transmission_score, transmission_error = _score_arrays(
            submitted["transmission"],
            recomputed["transmission"],
            TOLERANCES["consistency_transmission"],
        )
        identity_score, identity_error = _score_arrays(
            np.sum(np.asarray(submitted["ldos_cells"]), axis=1),
            np.asarray(submitted["dos_total"]),
            TOLERANCES["consistency_dos"],
        )
        diagnostic = submitted["diagnostics"]
        hermiticity_score, hermiticity_error = _score_arrays(
            np.asarray([float(diagnostic["max_hermiticity_residual"])]),
            np.asarray([float(recomputed["max_hermiticity_residual"])]),
            TOLERANCES["diagnostic_hermiticity"],
        )
        surface_claim_score = _residual_score(
            float(diagnostic["max_surface_residual"]),
            excellent=1.0e-9,
            unacceptable=1.0e-5,
        )
        recomputed_hermiticity_score = _residual_score(
            float(recomputed["max_hermiticity_residual"]),
            excellent=2.0e-12,
            unacceptable=2.0e-5,
        )

        observable_score = (dos_score + ldos_score + transmission_score) / 3.0
        # Both public diagnostic claims must carry evidence.  A correct
        # algorithm may converge farther than another, so the surface claim is
        # evaluated against an absolute quality range rather than the oracle's
        # stopping depth.  The submitted Sigma is independently checked by its
        # fixed-point residual above.
        diagnostic_score = min(hermiticity_score, surface_claim_score)
        score = (
            0.12 * band_score
            + 0.23 * observable_score
            + 0.15 * identity_score
            + 0.35 * diagnostic_score
            + 0.15 * recomputed_hermiticity_score
        )
        return _clamp_score(score), {
            "band_recompute_score": band_score,
            "band_recompute_error": band_error["normalized_error"],
            "dos_recompute_score": dos_score,
            "dos_recompute_error": dos_error["normalized_error"],
            "ldos_recompute_score": ldos_score,
            "ldos_recompute_error": ldos_error["normalized_error"],
            "transmission_recompute_score": transmission_score,
            "transmission_recompute_error": transmission_error["normalized_error"],
            "ldos_sum_score": identity_score,
            "ldos_sum_error": identity_error["normalized_error"],
            "diagnostic_hermiticity_score": hermiticity_score,
            "diagnostic_hermiticity_error": hermiticity_error["normalized_error"],
            "diagnostic_surface_order_score": surface_claim_score,
            "recomputed_max_hermiticity_residual": float(
                recomputed["max_hermiticity_residual"]
            ),
        }
    except (ValueError, np.linalg.LinAlgError, OverflowError) as exc:
        return 0.0, {"recomputation_failure": f"{type(exc).__name__}: {exc}"}


def _score_case(
    instance: Mapping[str, Any],
    submitted: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> tuple[dict[str, Any], float, bool]:
    h0_score, h0_error = _score_arrays(
        submitted["h0"], reference["h0"], TOLERANCES["hamiltonian"]
    )
    h1_score, h1_error = _score_arrays(
        submitted["h1"], reference["h1"], TOLERANCES["hamiltonian"]
    )
    assembly_score = 0.5 * (h0_score + h1_score)

    band_score, band_error = _score_arrays(
        submitted["bands"], reference["bands"], TOLERANCES["bands"]
    )

    sigma_left_score, sigma_left_error = _score_arrays(
        submitted["sigma_left"],
        reference["sigma_left"],
        TOLERANCES["self_energy"],
    )
    sigma_right_score, sigma_right_error = _score_arrays(
        submitted["sigma_right"],
        reference["sigma_right"],
        TOLERANCES["self_energy"],
    )
    sigma_accuracy_score = 0.5 * (sigma_left_score + sigma_right_score)
    max_dyson, max_causality = _surface_quality(
        instance,
        submitted,
        np.asarray(reference["h0"], dtype=np.complex128),
        np.asarray(reference["h1"], dtype=np.complex128),
    )
    dyson_score = _residual_score(max_dyson, excellent=2.0e-9, unacceptable=2.0e-4)
    causality_score = _residual_score(
        max_causality, excellent=2.0e-10, unacceptable=2.0e-5
    )
    self_energy_score = (
        0.75 * sigma_accuracy_score + 0.15 * dyson_score + 0.10 * causality_score
    )

    dos_score, dos_error = _score_arrays(
        submitted["dos_total"], reference["dos_total"], TOLERANCES["dos"]
    )
    ldos_score, ldos_error = _score_arrays(
        submitted["ldos_cells"], reference["ldos_cells"], TOLERANCES["ldos"]
    )
    dos_ldos_score = 0.4 * dos_score + 0.6 * ldos_score

    transmission_score, transmission_error = _score_arrays(
        submitted["transmission"],
        reference["transmission"],
        TOLERANCES["transmission"],
    )

    evidence_score, evidence_details = _evidence_consistency(instance, submitted)
    component_scores = {
        "assembly": _clamp_score(assembly_score),
        "bands": _clamp_score(band_score),
        "self_energies": _clamp_score(self_energy_score),
        "dos_ldos": _clamp_score(dos_ldos_score),
        "transmission": _clamp_score(transmission_score),
        "evidence_consistency": _clamp_score(evidence_score),
    }
    total = float(
        sum(METRIC_WEIGHTS[name] * component_scores[name] for name in METRIC_WEIGHTS)
    )
    mandatory = all(
        component_scores[name] >= MANDATORY_MINIMA[name] for name in MANDATORY_MINIMA
    ) and dyson_score >= 0.50 and causality_score >= 0.50
    passed = bool(total >= TOTAL_PASS_THRESHOLD and mandatory)
    metrics = {
        "assembly": {
            "score": component_scores["assembly"],
            "h0_score": h0_score,
            "h0_error": h0_error,
            "h1_score": h1_score,
            "h1_error": h1_error,
        },
        "bands": {
            "score": component_scores["bands"],
            "error": band_error,
        },
        "self_energies": {
            "score": component_scores["self_energies"],
            "reference_accuracy_score": sigma_accuracy_score,
            "left_error": sigma_left_error,
            "right_error": sigma_right_error,
            "dyson_score": dyson_score,
            "max_dyson_residual": max_dyson,
            "causality_score": causality_score,
            "max_causality_violation": max_causality,
        },
        "dos_ldos": {
            "score": component_scores["dos_ldos"],
            "dos_score": dos_score,
            "dos_error": dos_error,
            "ldos_score": ldos_score,
            "ldos_error": ldos_error,
        },
        "transmission": {
            "score": component_scores["transmission"],
            "error": transmission_error,
        },
        "evidence_consistency": {
            "score": component_scores["evidence_consistency"],
            **evidence_details,
        },
    }
    return metrics, total, passed


def _case_failure(model_id: str, message: str) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "hard_gates": {"passed": False, "failures": [message]},
        "metrics": {},
        "total_score": 0.0,
        "passed": False,
    }


def _discover_cases(input_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    if _is_link_like(input_dir) or not input_dir.is_dir():
        raise ConfigurationFailure(f"hidden input directory is missing or unsafe: {input_dir}")
    paths = sorted(input_dir.glob("*.json"), key=lambda item: item.name)
    if not paths:
        raise ConfigurationFailure(f"hidden input directory contains no JSON cases: {input_dir}")
    result: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    for path in paths:
        if _is_link_like(path) or not path.is_file():
            raise ConfigurationFailure(f"hidden input is not a regular file: {path.name}")
        try:
            instance = science.load_instance(path)
        except (OSError, science.ScienceError) as exc:
            raise ConfigurationFailure(f"invalid hidden input {path.name}: {exc}") from exc
        model_id = str(instance["model_id"])
        if path.stem != model_id:
            raise ConfigurationFailure(
                f"hidden input stem {path.stem!r} does not match model_id {model_id!r}"
            )
        if model_id in seen:
            raise ConfigurationFailure(f"duplicate hidden model_id: {model_id}")
        seen.add(model_id)
        result.append((path, instance))
    return result


def _reference_for_case(
    reference_root: Path, model_id: str, instance: Mapping[str, Any]
) -> dict[str, Any]:
    reference_dir = reference_root / model_id
    try:
        root_resolved = reference_root.resolve(strict=True)
        reference_resolved = reference_dir.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationFailure(f"missing reference for {model_id}: {exc}") from exc
    if reference_resolved.parent != root_resolved:
        raise ConfigurationFailure(f"reference path escapes its root for {model_id}")
    if _is_link_like(reference_dir) or not reference_dir.is_dir():
        raise ConfigurationFailure(f"reference directory is missing or unsafe for {model_id}")
    try:
        _validate_output_tree(reference_dir, instance, allowed_root=reference_root)
        return science.read_outputs(reference_dir, instance)
    except (
        GateFailure,
        OSError,
        EOFError,
        ValueError,
        RecursionError,
        MemoryError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        science.ScienceError,
    ) as exc:
        raise ConfigurationFailure(f"invalid reference for {model_id}: {exc}") from exc


def _artifact_directory(root: Path, model_id: str, case_count: int) -> Path:
    if case_count == 1 and REQUIRED_OUTPUTS.issubset(
        {entry.name for entry in root.iterdir()} if root.is_dir() else set()
    ):
        return root
    return root / model_id


def evaluate(
    *,
    submission: Path | None,
    artifacts_only: Path | None,
    input_dir: Path,
    reference_dir: Path,
) -> dict[str, Any]:
    suite_deadline = time.monotonic() + SUITE_TIMEOUT_SECONDS
    mode = "execute" if submission is not None else "artifacts_only"
    if (submission is None) == (artifacts_only is None):
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": "invalid",
            "evaluator_error": "exactly one evaluation mode must be selected",
            "hard_gates": {"passed": False, "failures": []},
            "cases": [],
            "metrics": {},
            "total_score": 0.0,
            "passed": False,
        }

    # Validate the complete private suite before participant code runs.  A bad
    # input or reference is an evaluator fault, never a participant hard gate.
    try:
        cases = _discover_cases(input_dir)
        if _is_link_like(reference_dir) or not reference_dir.is_dir():
            raise ConfigurationFailure(
                f"reference root is missing or unsafe: {reference_dir}"
            )
        references = {
            str(instance["model_id"]): _reference_for_case(
                reference_dir, str(instance["model_id"]), instance
            )
            for _path, instance in cases
        }
    except ConfigurationFailure as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": mode,
            "evaluator_error": str(exc),
            "hard_gates": {"passed": False, "failures": []},
            "cases": [],
            "metrics": {},
            "total_score": 0.0,
            "passed": False,
        }

    try:
        source = _check_submission_source(submission) if submission is not None else None
        if artifacts_only is not None and (
            _is_link_like(artifacts_only) or not artifacts_only.is_dir()
        ):
            raise GateFailure("artifacts-only root must be a regular non-symlink directory")
    except GateFailure as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": mode,
            "evaluator_error": None,
            "hard_gates": {"passed": False, "failures": [str(exc)]},
            "cases": [],
            "metrics": {},
            "total_score": 0.0,
            "passed": False,
        }

    case_results: list[dict[str, Any]] = []
    hard_gate_failures: list[str] = []
    aggregate_disk_bytes = 0
    aggregate_expanded_bytes = 0

    for input_path, instance in cases:
        model_id = str(instance["model_id"])
        try:
            reference = references[model_id]
            if source is not None:
                with tempfile.TemporaryDirectory(prefix="periodic-transport-") as temporary:
                    temporary_root = Path(temporary)
                    output_dir = _run_solver(
                        source,
                        input_path,
                        temporary_root,
                        suite_deadline=suite_deadline,
                    )
                    disk_bytes, expanded_bytes = _validate_output_tree(
                        output_dir, instance, allowed_root=temporary_root
                    )
                    aggregate_disk_bytes += disk_bytes
                    aggregate_expanded_bytes += expanded_bytes
                    if (
                        aggregate_disk_bytes > MAX_AGGREGATE_OUTPUT_BYTES
                        or aggregate_expanded_bytes > MAX_AGGREGATE_OUTPUT_BYTES
                    ):
                        raise GateFailure(
                            f"aggregate outputs exceed {MAX_AGGREGATE_OUTPUT_BYTES} bytes"
                        )
                    submitted = _read_submitted_outputs(output_dir, instance)
            else:
                assert artifacts_only is not None
                output_dir = _artifact_directory(artifacts_only, model_id, len(cases))
                disk_bytes, expanded_bytes = _validate_output_tree(
                    output_dir, instance, allowed_root=artifacts_only
                )
                aggregate_disk_bytes += disk_bytes
                aggregate_expanded_bytes += expanded_bytes
                if (
                    aggregate_disk_bytes > MAX_AGGREGATE_OUTPUT_BYTES
                    or aggregate_expanded_bytes > MAX_AGGREGATE_OUTPUT_BYTES
                ):
                    raise GateFailure(
                        f"aggregate outputs exceed {MAX_AGGREGATE_OUTPUT_BYTES} bytes"
                    )
                submitted = _read_submitted_outputs(output_dir, instance)

            metrics, total, scientific_pass = _score_case(instance, submitted, reference)
            case_results.append(
                {
                    "model_id": model_id,
                    "hard_gates": {"passed": True, "failures": []},
                    "metrics": metrics,
                    "total_score": total,
                    "passed": scientific_pass,
                    "output_bytes": disk_bytes,
                    "expanded_output_bytes": expanded_bytes,
                }
            )
        except (GateFailure, science.ScienceError, OSError) as exc:
            failure = f"{model_id}: {exc}"
            hard_gate_failures.append(failure)
            case_results.append(_case_failure(model_id, failure))
        except Exception as exc:
            return {
                "schema_version": SCHEMA_VERSION,
                "mode": mode,
                "evaluator_error": (
                    f"{model_id}: internal {type(exc).__name__}: {exc}"
                ),
                "hard_gates": {"passed": False, "failures": hard_gate_failures},
                "cases": case_results,
                "metrics": {},
                "total_score": 0.0,
                "passed": False,
                "aggregate_output_bytes": aggregate_disk_bytes,
                "aggregate_expanded_output_bytes": aggregate_expanded_bytes,
            }

    if hard_gate_failures:
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": mode,
            "evaluator_error": None,
            "hard_gates": {"passed": False, "failures": hard_gate_failures},
            "cases": case_results,
            "metrics": {},
            "total_score": 0.0,
            "passed": False,
            "aggregate_output_bytes": aggregate_disk_bytes,
            "aggregate_expanded_output_bytes": aggregate_expanded_bytes,
        }

    aggregate_metrics = {
        name: float(
            np.mean([case["metrics"][name]["score"] for case in case_results])
        )
        for name in METRIC_WEIGHTS
    }
    total_score = float(np.mean([case["total_score"] for case in case_results]))
    passed = bool(
        total_score >= TOTAL_PASS_THRESHOLD
        and all(case["passed"] for case in case_results)
        and all(
            aggregate_metrics[name] >= MANDATORY_MINIMA[name]
            for name in MANDATORY_MINIMA
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "evaluator_error": None,
        "hard_gates": {"passed": True, "failures": []},
        "cases": case_results,
        "metrics": {
            name: {"score": aggregate_metrics[name], "weight": METRIC_WEIGHTS[name]}
            for name in METRIC_WEIGHTS
        },
        "total_score": total_score,
        "passed": passed,
        "aggregate_output_bytes": aggregate_disk_bytes,
        "aggregate_expanded_output_bytes": aggregate_expanded_bytes,
    }


def _write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--submission",
        type=Path,
        help="trusted-local calibration of a submitted solution.py",
    )
    mode.add_argument(
        "--artifacts-only",
        type=Path,
        metavar="DIR",
        help="grade existing per-model artifact directories without execution",
    )
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--references", type=Path, default=DEFAULT_REFERENCES)
    parser.add_argument("--json-out", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    result = evaluate(
        submission=arguments.submission,
        artifacts_only=arguments.artifacts_only,
        input_dir=arguments.inputs,
        reference_dir=arguments.references,
    )
    payload = json.dumps(
        result,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    ) + "\n"
    if arguments.json_out is not None:
        _write_json(arguments.json_out, payload)
    sys.stdout.write(payload)
    if result.get("evaluator_error") is not None:
        return 2
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
