#!/usr/bin/env python3
"""Trusted parser, runner, and behavioral scoring for the private suite."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

import numpy as np


GRADER_ROOT = Path(__file__).resolve().parent
TASK_ROOT = GRADER_ROOT.parents[1]
HIDDEN_ROOT = TASK_ROOT / "private" / "hidden_inputs"
REFERENCE_ROOT = TASK_ROOT / "private" / "reference"
RUNNER = GRADER_ROOT / "guarded_runner.py"
REQUIRED_FILES = {
    "aggregated.csv",
    "spectra.csv",
    "decays.csv",
    "distribution.csv",
    "dependence.csv",
    "summary.json",
}
HEADERS = {
    "aggregated.csv": ["length", "error_mask", "corrected_count", "probability"],
    "spectra.csv": ["length", "mode_mask", "coefficient"],
    "decays.csv": ["mode_mask", "amplitude", "eigenvalue", "fit_rmse"],
    "distribution.csv": ["error_mask", "raw_probability", "probability", "local_probability"],
    "dependence.csv": [
        "unit_i",
        "unit_j",
        "mutual_information",
        "conditional_mutual_information",
        "pearson_correlation",
        "co_local",
    ],
}
MAX_SOURCE_BYTES = 150_000
MAX_OUTPUT_BYTES = 8_000_000
MAX_CONSOLE_BYTES = 40_000
CASE_TIMEOUT_SECONDS = 45
SIGNED_INT64_MIN = -(1 << 63)
SIGNED_INT64_MAX = (1 << 63) - 1
_FIT_MINIMUM_CACHE: dict[str, np.ndarray] = {}


class GateFailure(Exception):
    pass


def strict_json(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )


def regular_file(path: Path, maximum: int) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise GateFailure(f"required regular non-link file missing: {path.name}") from error
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
        raise GateFailure(f"required regular non-link file missing: {path.name}")
    if info.st_size > maximum:
        raise GateFailure(f"file exceeds size limit: {path.name}")


def linked_path(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def validate_source(submission_dir: Path) -> tuple[Path, bytes]:
    try:
        root_info = submission_dir.lstat()
        root_reparse = bool(getattr(root_info, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(root_info.st_mode) or root_reparse or not stat.S_ISDIR(root_info.st_mode):
            raise GateFailure("submission must be a regular directory")
        entries = list(submission_dir.iterdir())
    except GateFailure:
        raise
    except OSError as error:
        raise GateFailure("submission must be a regular directory") from error
    if {entry.name for entry in entries} != {"analyze.py"}:
        raise GateFailure("submission must contain exactly analyze.py")
    source_path = submission_dir / "analyze.py"
    regular_file(source_path, MAX_SOURCE_BYTES)
    try:
        with source_path.open("rb") as handle:
            opened_info = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened_info.st_mode) or opened_info.st_nlink > 1:
                raise GateFailure("analyze.py changed during source validation")
            source_bytes = handle.read(MAX_SOURCE_BYTES + 1)
        if len(source_bytes) > MAX_SOURCE_BYTES:
            raise GateFailure("file exceeds size limit: analyze.py")
        source = source_bytes.decode("utf-8-sig")
        tree = ast.parse(source, filename="analyze.py")
    except GateFailure:
        raise
    except (OSError, UnicodeError, SyntaxError) as error:
        raise GateFailure(f"analyze.py does not parse: {error}") from error
    return source_path, source_bytes


def clean_environment(output_root: Path) -> dict[str, str]:
    environment: dict[str, str] = {
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMP": str(output_root),
        "TEMP": str(output_root),
        "PYTHONNOUSERSITE": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    for name in ("SYSTEMROOT", "WINDIR"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def digest_tree(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
        if stat.S_ISREG(info.st_mode) and not reparse:
            snapshot[relative] = f"file:{info.st_mode}:{info.st_nlink}:{info.st_size}:{digest_file(path)}"
        elif stat.S_ISDIR(info.st_mode) and not reparse:
            snapshot[relative] = f"directory:{info.st_mode}:{info.st_nlink}"
        elif stat.S_ISLNK(info.st_mode) or reparse:
            snapshot[relative] = "link-or-reparse"
        else:
            snapshot[relative] = f"other:{info.st_mode}:{info.st_nlink}"
    return snapshot


def run_analyzer(submission_dir: Path, input_dir: Path) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    _source_path, source_bytes = validate_source(submission_dir)
    temporary = tempfile.TemporaryDirectory(prefix="spectral-audit-case-")
    root = Path(temporary.name)
    isolated_submission = root / "submission"
    isolated_input = root / "input"
    isolated_output = root / "runtime-output"
    isolated_submission.mkdir()
    (isolated_submission / "analyze.py").write_bytes(source_bytes)
    shutil.copytree(input_dir, isolated_input)
    source_digest_before = digest_tree(isolated_submission)
    input_digest_before = digest_tree(isolated_input)
    stdout_path = root / "runner.stdout"
    stderr_path = root / "runner.stderr"
    command = [
        sys.executable,
        "-I",
        "-B",
        str(RUNNER),
        str(isolated_submission / "analyze.py"),
        str(isolated_input),
        str(isolated_output),
    ]
    console_exceeded = False
    timed_out = False
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=clean_environment(isolated_output),
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            close_fds=True,
        )
        deadline = time.monotonic() + CASE_TIMEOUT_SECONDS
        while process.poll() is None:
            stdout_handle.flush()
            stderr_handle.flush()
            if stdout_path.stat().st_size + stderr_path.stat().st_size > MAX_CONSOLE_BYTES:
                console_exceeded = True
                process.terminate()
                break
            if time.monotonic() >= deadline:
                timed_out = True
                process.terminate()
                break
            time.sleep(0.01)
        if process.poll() is None:
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        stdout_handle.flush()
        stderr_handle.flush()

    protected_unchanged = (
        digest_tree(isolated_submission) == source_digest_before
        and digest_tree(isolated_input) == input_digest_before
    )
    root_inventory = {path.name for path in root.iterdir()}
    allowed_root_inventory = {"submission", "input", "runtime-output", "runner.stdout", "runner.stderr"}
    unexpected_root_entries = root_inventory - allowed_root_inventory
    if not protected_unchanged or unexpected_root_entries:
        temporary.cleanup()
        raise GateFailure("analyzer mutated protected source/input or wrote outside runtime output")
    if timed_out:
        temporary.cleanup()
        raise GateFailure("analyzer exceeded the per-case time limit")
    if console_exceeded or stdout_path.stat().st_size + stderr_path.stat().st_size > MAX_CONSOLE_BYTES:
        temporary.cleanup()
        raise GateFailure("analyzer exceeded the console output limit")
    if process.returncode != 0:
        message = stderr_path.read_bytes().decode("utf-8", errors="replace")[-1200:]
        temporary.cleanup()
        raise GateFailure(f"analyzer execution failed: {message}")
    return isolated_output, temporary


def float_value(raw: str, field: str) -> float:
    try:
        value = float(raw)
    except ValueError as error:
        raise GateFailure(f"non-numeric value in {field}") from error
    if not math.isfinite(value) or abs(value) > 1.0e6:
        raise GateFailure(f"unsafe numeric value in {field}")
    return value


def integer_value(raw: str, field: str) -> int:
    try:
        value = int(raw)
    except ValueError as error:
        raise GateFailure(f"non-integer value in {field}") from error
    if value < SIGNED_INT64_MIN or value > SIGNED_INT64_MAX:
        raise GateFailure(f"integer value in {field} exceeds signed 64-bit range")
    return value


def json_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateFailure(f"{field} must be a JSON number")
    return float_value(str(value), field)


def json_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GateFailure(f"{field} must be a JSON integer")
    return value


def read_csv_exact(path: Path, expected_header: list[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected_header:
            raise GateFailure(f"header mismatch in {path.name}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise GateFailure(f"malformed row in {path.name}")
    return rows


def inspect_output(output_dir: Path) -> None:
    try:
        root_info = output_dir.lstat()
        root_reparse = bool(getattr(root_info, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(root_info.st_mode) or root_reparse or not stat.S_ISDIR(root_info.st_mode):
            raise GateFailure("runtime output directory missing")
        entries = list(output_dir.iterdir())
    except GateFailure:
        raise
    except OSError as error:
        raise GateFailure("runtime output directory missing") from error
    if {entry.name for entry in entries} != REQUIRED_FILES:
        raise GateFailure("runtime output inventory mismatch")
    total = 0
    for entry in entries:
        regular_file(entry, MAX_OUTPUT_BYTES)
        total += entry.stat().st_size
    if total > MAX_OUTPUT_BYTES:
        raise GateFailure("runtime output exceeds total size limit")


def parse_output(output_dir: Path, manifest: dict) -> dict[str, Any]:
    inspect_output(output_dir)
    bit_count = int(manifest["bit_count"])
    state_count = 1 << bit_count
    lengths = [int(length) for length in manifest["sequence_lengths"]]
    parsed: dict[str, Any] = {}

    aggregated_rows = read_csv_exact(output_dir / "aggregated.csv", HEADERS["aggregated.csv"])
    if len(aggregated_rows) != len(lengths) * state_count:
        raise GateFailure("aggregated.csv row count mismatch")
    counts = np.empty((len(lengths), state_count), dtype=np.int64)
    probabilities = np.empty((len(lengths), state_count), dtype=np.float64)
    for index, row in enumerate(aggregated_rows):
        length_index, mask = divmod(index, state_count)
        if integer_value(row["length"], "length") != lengths[length_index] or integer_value(row["error_mask"], "error_mask") != mask:
            raise GateFailure("aggregated.csv identities or ordering mismatch")
        count = integer_value(row["corrected_count"], "corrected_count")
        if count < 0:
            raise GateFailure("negative corrected count")
        counts[length_index, mask] = count
        probabilities[length_index, mask] = float_value(row["probability"], "probability")
    if np.any(probabilities < -1e-12) or np.any(np.abs(probabilities.sum(axis=1) - 1.0) > 1e-8):
        raise GateFailure("aggregated probabilities are not normalized")
    parsed["counts"] = counts
    parsed["aggregated_probabilities"] = probabilities

    spectra_rows = read_csv_exact(output_dir / "spectra.csv", HEADERS["spectra.csv"])
    if len(spectra_rows) != len(lengths) * state_count:
        raise GateFailure("spectra.csv row count mismatch")
    spectra = np.empty((len(lengths), state_count), dtype=np.float64)
    for index, row in enumerate(spectra_rows):
        length_index, mode = divmod(index, state_count)
        if integer_value(row["length"], "length") != lengths[length_index] or integer_value(row["mode_mask"], "mode_mask") != mode:
            raise GateFailure("spectra.csv identities or ordering mismatch")
        spectra[length_index, mode] = float_value(row["coefficient"], "coefficient")
    parsed["spectra"] = spectra

    decay_rows = read_csv_exact(output_dir / "decays.csv", HEADERS["decays.csv"])
    if len(decay_rows) != state_count:
        raise GateFailure("decays.csv row count mismatch")
    decays = np.empty((state_count, 3), dtype=np.float64)
    for mode, row in enumerate(decay_rows):
        if integer_value(row["mode_mask"], "mode_mask") != mode:
            raise GateFailure("decays.csv mode ordering mismatch")
        decays[mode] = [
            float_value(row["amplitude"], "amplitude"),
            float_value(row["eigenvalue"], "eigenvalue"),
            float_value(row["fit_rmse"], "fit_rmse"),
        ]
    if np.any(decays[:, 0] < -1e-12) or np.any(decays[:, 0] > 1.0 + 1e-8):
        raise GateFailure("amplitudes leave the disclosed bounds")
    if np.any(decays[:, 1] < -1e-12) or np.any(decays[:, 1] > 1.0 + 1e-8) or np.any(decays[:, 2] < 0.0):
        raise GateFailure("decay parameters leave the disclosed bounds")
    parsed["decays"] = decays

    distribution_rows = read_csv_exact(output_dir / "distribution.csv", HEADERS["distribution.csv"])
    if len(distribution_rows) != state_count:
        raise GateFailure("distribution.csv row count mismatch")
    distributions = np.empty((state_count, 3), dtype=np.float64)
    for mask, row in enumerate(distribution_rows):
        if integer_value(row["error_mask"], "error_mask") != mask:
            raise GateFailure("distribution.csv mask ordering mismatch")
        distributions[mask] = [
            float_value(row["raw_probability"], "raw_probability"),
            float_value(row["probability"], "probability"),
            float_value(row["local_probability"], "local_probability"),
        ]
    if np.any(distributions[:, 1:] < -1e-12) or np.any(np.abs(distributions[:, 1:].sum(axis=0) - 1.0) > 1e-8):
        raise GateFailure("submitted distributions are not simplex-valid")
    parsed["raw_distribution"] = distributions[:, 0]
    parsed["distribution"] = distributions[:, 1]
    parsed["local_distribution"] = distributions[:, 2]

    dependence_rows = read_csv_exact(output_dir / "dependence.csv", HEADERS["dependence.csv"])
    expected_pairs = [(unit_i, unit_j) for unit_i in range(bit_count) for unit_j in range(unit_i + 1, bit_count)]
    if len(dependence_rows) != len(expected_pairs):
        raise GateFailure("dependence.csv row count mismatch")
    dependence = np.empty((len(expected_pairs), 4), dtype=np.float64)
    for index, (row, pair) in enumerate(zip(dependence_rows, expected_pairs)):
        if (integer_value(row["unit_i"], "unit_i"), integer_value(row["unit_j"], "unit_j")) != pair:
            raise GateFailure("dependence.csv pair ordering mismatch")
        co_local = integer_value(row["co_local"], "co_local")
        if co_local not in (0, 1):
            raise GateFailure("co_local must be 0 or 1")
        dependence[index] = [
            float_value(row["mutual_information"], "mutual_information"),
            float_value(row["conditional_mutual_information"], "conditional_mutual_information"),
            float_value(row["pearson_correlation"], "pearson_correlation"),
            co_local,
        ]
    if np.any(dependence[:, :2] < -1e-10) or np.any(np.abs(dependence[:, 2]) > 1.0 + 1e-8):
        raise GateFailure("dependence values leave mathematical bounds")
    parsed["pairs"] = expected_pairs
    parsed["dependence"] = dependence

    summary = strict_json(output_dir / "summary.json")
    expected_summary_keys = {
        "schema_version",
        "experiment_id",
        "bit_count",
        "simplex_adjustment_l2",
        "jensen_shannon_distance",
        "total_variation_distance",
        "nonlocal_ranking",
    }
    if not isinstance(summary, dict) or set(summary) != expected_summary_keys:
        raise GateFailure("summary.json key mismatch")
    if (
        summary["schema_version"] != "spectral-correlation-audit-result/v1"
        or summary["experiment_id"] != manifest["experiment_id"]
        or json_integer(summary["bit_count"], "bit_count") != bit_count
    ):
        raise GateFailure("summary.json identity mismatch")
    for field in ("simplex_adjustment_l2", "jensen_shannon_distance", "total_variation_distance"):
        summary[field] = json_number(summary[field], field)
        if summary[field] < 0.0:
            raise GateFailure(f"negative summary metric: {field}")
    ranking = summary["nonlocal_ranking"]
    top_k = int(manifest["local_model"]["top_k_nonlocal"])
    if not isinstance(ranking, list) or len(ranking) != top_k:
        raise GateFailure("nonlocal ranking length mismatch")
    seen: set[tuple[int, int]] = set()
    for rank, record in enumerate(ranking, start=1):
        if not isinstance(record, dict) or set(record) != {"rank", "unit_i", "unit_j", "conditional_mutual_information"}:
            raise GateFailure("nonlocal ranking schema mismatch")
        pair = (json_integer(record["unit_i"], "unit_i"), json_integer(record["unit_j"], "unit_j"))
        if json_integer(record["rank"], "rank") != rank or pair not in expected_pairs or pair in seen:
            raise GateFailure("nonlocal ranking identity mismatch")
        record["conditional_mutual_information"] = json_number(
            record["conditional_mutual_information"], "conditional_mutual_information"
        )
        pair_index = expected_pairs.index(pair)
        if int(dependence[pair_index, 3]) != 0:
            raise GateFailure("ranking contains a co-local pair")
        expected_cmi = float(dependence[pair_index, 1])
        if abs(record["conditional_mutual_information"] - expected_cmi) > max(5e-8, 5e-6 * abs(expected_cmi)):
            raise GateFailure("ranking CMI does not match dependence.csv")
        seen.add(pair)
    expected_ranking = [
        expected_pairs[index]
        for index in sorted(
            (index for index in range(len(expected_pairs)) if int(dependence[index, 3]) == 0),
            key=lambda index: (-float(dependence[index, 1]), expected_pairs[index]),
        )[:top_k]
    ]
    observed_ranking = [(record["unit_i"], record["unit_j"]) for record in ranking]
    if observed_ranking != expected_ranking:
        raise GateFailure("ranking is not the global top-k from dependence.csv")
    parsed["summary"] = summary
    return parsed


def character_matrix(bit_count: int) -> np.ndarray:
    size = 1 << bit_count
    result = np.empty((size, size), dtype=np.float64)
    for mode in range(size):
        for mask in range(size):
            result[mode, mask] = -1.0 if (mode & mask).bit_count() % 2 else 1.0
    return result


def expected_pipeline(input_dir: Path, manifest: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bit_count = int(manifest["bit_count"])
    state_count = 1 << bit_count
    lengths = [int(length) for length in manifest["sequence_lengths"]]
    length_index = {length: index for index, length in enumerate(lengths)}
    counts = np.zeros((len(lengths), state_count), dtype=np.int64)
    with (input_dir / "raw_counts.csv").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["length", "sequence_id", "target_mask", "observed_mask", "count"]:
            raise GateFailure("hidden raw-count schema invalid")
        for row in reader:
            length = integer_value(row["length"], "length")
            target = integer_value(row["target_mask"], "target_mask")
            observed = integer_value(row["observed_mask"], "observed_mask")
            count = integer_value(row["count"], "count")
            if length not in length_index or not (0 <= target < state_count) or not (0 <= observed < state_count):
                raise GateFailure("hidden raw-count identity leaves the disclosed bounds")
            if not (1 <= count <= 10_000):
                raise GateFailure("hidden raw count leaves the disclosed bounds")
            if counts[length_index[length], target ^ observed] > SIGNED_INT64_MAX - count:
                raise GateFailure("hidden pooled count exceeds signed 64-bit range")
            counts[length_index[length], target ^ observed] += count
    probabilities = counts / counts.sum(axis=1)[:, None]
    transform = character_matrix(bit_count)
    spectra = probabilities @ transform.T
    return counts, probabilities, spectra


def elementwise_close(observed: np.ndarray, reference: np.ndarray, absolute: float, relative: float) -> bool:
    tolerance = np.maximum(absolute, relative * np.abs(reference))
    return bool(np.all(np.abs(observed - reference) <= tolerance))


def canonical_fit_minimum_losses(input_dir: Path, lengths: np.ndarray, spectra: np.ndarray) -> np.ndarray:
    cache_key = str(input_dir.resolve())
    cached = _FIT_MINIMUM_CACHE.get(cache_key)
    if cached is not None:
        return cached
    grid = np.linspace(0.0, 1.0, 2001, dtype=np.float64)
    powers = grid[:, None] ** lengths[None, :]
    denominators = np.sum(powers * powers, axis=1)
    safe = np.where(denominators > 0.0, denominators, 1.0)
    amplitudes = np.clip((powers @ spectra) / safe[:, None], 0.0, 1.0)
    residuals = powers[:, :, None] * amplitudes[:, None, :] - spectra[None, :, :]
    grid_losses = np.sum(residuals * residuals, axis=1)
    grid_losses[denominators == 0.0, :] = np.inf
    minima = np.empty(spectra.shape[1], dtype=np.float64)
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    for mode in range(spectra.shape[1]):
        if mode == 0:
            minima[mode] = float(np.sum((spectra[:, mode] - 1.0) ** 2))
            continue
        best = int(np.argmin(grid_losses[:, mode]))
        lower = float(grid[max(0, best - 1)])
        upper = float(grid[min(grid.size - 1, best + 1)])

        def profile(value: float) -> float:
            basis = value**lengths
            denominator = float(np.dot(basis, basis))
            if denominator == 0.0:
                return math.inf
            amplitude = float(np.clip(np.dot(basis, spectra[:, mode]) / denominator, 0.0, 1.0))
            delta = amplitude * basis - spectra[:, mode]
            return float(np.dot(delta, delta))

        x1 = upper - ratio * (upper - lower)
        x2 = lower + ratio * (upper - lower)
        f1 = profile(x1)
        f2 = profile(x2)
        for _ in range(50):
            if f1 <= f2:
                upper, x2, f2 = x2, x1, f1
                x1 = upper - ratio * (upper - lower)
                f1 = profile(x1)
            else:
                lower, x1, f1 = x1, x2, f2
                x2 = lower + ratio * (upper - lower)
                f2 = profile(x2)
        minima[mode] = profile(0.5 * (lower + upper))
    _FIT_MINIMUM_CACHE[cache_key] = minima
    return minima


def subset_index(mask: int, subset: list[int]) -> int:
    result = 0
    for position, unit in enumerate(subset):
        result |= ((mask >> unit) & 1) << position
    return result


def marginal(distribution: np.ndarray, subset: list[int]) -> np.ndarray:
    result = np.zeros(1 << len(subset), dtype=np.float64)
    for mask, probability in enumerate(distribution):
        result[subset_index(mask, subset)] += probability
    return result


def reconstruct_local(distribution: np.ndarray, manifest: dict) -> np.ndarray:
    cliques = [[int(unit) for unit in clique] for clique in manifest["local_model"]["cliques"]]
    tree_edges = [[int(endpoint) for endpoint in edge] for edge in manifest["local_model"]["tree_edges"]]
    clique_marginals = [(clique, marginal(distribution, clique)) for clique in cliques]
    separator_marginals = []
    for left, right in tree_edges:
        separator = sorted(set(cliques[left]).intersection(cliques[right]))
        separator_marginals.append((separator, marginal(distribution, separator)))
    result = np.zeros_like(distribution)
    for mask in range(distribution.size):
        numerator = math.prod(values[subset_index(mask, scope)] for scope, values in clique_marginals)
        denominator = math.prod(values[subset_index(mask, scope)] for scope, values in separator_marginals)
        result[mask] = numerator / denominator if denominator > 0.0 else 0.0
    return result / result.sum()


def dependence_values(distribution: np.ndarray, bit_count: int, manifest: dict) -> tuple[list[tuple[int, int]], np.ndarray]:
    states = np.arange(distribution.size, dtype=np.int64)
    cliques = [[int(unit) for unit in clique] for clique in manifest["local_model"]["cliques"]]
    pairs: list[tuple[int, int]] = []
    values: list[list[float]] = []
    for unit_i in range(bit_count):
        bit_i = ((states >> unit_i) & 1).astype(np.int64)
        mean_i = float(distribution @ bit_i)
        for unit_j in range(unit_i + 1, bit_count):
            bit_j = ((states >> unit_j) & 1).astype(np.int64)
            mean_j = float(distribution @ bit_j)
            joint = np.zeros((2, 2), dtype=np.float64)
            for mask, probability in enumerate(distribution):
                joint[bit_i[mask], bit_j[mask]] += probability
            first = joint.sum(axis=1)
            second = joint.sum(axis=0)
            mutual = 0.0
            for value_i in range(2):
                for value_j in range(2):
                    probability = joint[value_i, value_j]
                    if probability > 0.0:
                        mutual += probability * math.log(probability / (first[value_i] * second[value_j]))
            remaining = [unit for unit in range(bit_count) if unit not in (unit_i, unit_j)]
            z_size = 1 << len(remaining)
            p_z = np.zeros(z_size, dtype=np.float64)
            p_iz = np.zeros((2, z_size), dtype=np.float64)
            p_jz = np.zeros((2, z_size), dtype=np.float64)
            z_indices = [subset_index(mask, remaining) for mask in range(distribution.size)]
            for mask, probability in enumerate(distribution):
                z_index = z_indices[mask]
                p_z[z_index] += probability
                p_iz[bit_i[mask], z_index] += probability
                p_jz[bit_j[mask], z_index] += probability
            conditional = 0.0
            for mask, probability in enumerate(distribution):
                if probability <= 0.0:
                    continue
                z_index = z_indices[mask]
                denominator = p_iz[bit_i[mask], z_index] * p_jz[bit_j[mask], z_index]
                if denominator > 0.0:
                    conditional += probability * math.log(probability * p_z[z_index] / denominator)
            covariance = float(distribution @ (bit_i * bit_j) - mean_i * mean_j)
            variance = mean_i * (1.0 - mean_i) * mean_j * (1.0 - mean_j)
            pearson = covariance / math.sqrt(variance) if variance > 0.0 else 0.0
            co_local = int(any(unit_i in clique and unit_j in clique for clique in cliques))
            pairs.append((unit_i, unit_j))
            values.append([mutual, max(0.0, conditional), pearson, co_local])
    return pairs, np.asarray(values, dtype=np.float64)


def divergence_metrics(left: np.ndarray, right: np.ndarray) -> tuple[float, float]:
    mixture = 0.5 * (left + right)

    def relative(first: np.ndarray, second: np.ndarray) -> float:
        keep = first > 0.0
        return float(np.sum(first[keep] * np.log(first[keep] / second[keep])))

    divergence = 0.5 * relative(left, mixture) + 0.5 * relative(right, mixture)
    return math.sqrt(max(0.0, divergence)), 0.5 * float(np.sum(np.abs(left - right)))


def simplex_projection(values: np.ndarray) -> np.ndarray:
    ordered = np.sort(values)[::-1]
    cumulative = np.cumsum(ordered) - 1.0
    eligible = ordered - cumulative / np.arange(1, values.size + 1) > 0.0
    rho = int(np.flatnonzero(eligible)[-1])
    theta = cumulative[rho] / (rho + 1)
    projected = np.maximum(values - theta, 0.0)
    return projected / projected.sum()


def tolerance_score(observed: np.ndarray, reference: np.ndarray, absolute: float, relative: float, bad_ratio: float = 25.0) -> tuple[float, float]:
    scale = np.maximum(absolute, relative * np.abs(reference))
    ratio = float(np.sqrt(np.mean(((observed - reference) / scale) ** 2)))
    if ratio <= 1.0:
        return 1.0, ratio
    if ratio >= bad_ratio:
        return 0.0, ratio
    return (bad_ratio - ratio) / (bad_ratio - 1.0), ratio


def lower_error_score(error: float, excellent: float, bad: float) -> float:
    if error <= excellent:
        return 1.0
    if error >= bad:
        return 0.0
    return (bad - error) / (bad - excellent)


def ranking_score(summary: dict, pairs: list[tuple[int, int]], truth_dependence: np.ndarray) -> tuple[float, dict[str, float]]:
    pair_to_index = {pair: index for index, pair in enumerate(pairs)}
    nonlocal_indices = [index for index in range(len(pairs)) if truth_dependence[index, 3] == 0]
    ideal = sorted(nonlocal_indices, key=lambda index: (-truth_dependence[index, 1], pairs[index]))
    top_k = len(summary["nonlocal_ranking"])
    ideal = ideal[:top_k]
    submitted_pairs = [(int(record["unit_i"]), int(record["unit_j"])) for record in summary["nonlocal_ranking"]]
    if any(pair_to_index[pair] not in nonlocal_indices for pair in submitted_pairs):
        return 0.0, {"ndcg": 0.0, "overlap": 0.0}
    gains = {pairs[index]: float(truth_dependence[index, 1]) for index in nonlocal_indices}
    ideal_dcg = sum(gains[pairs[index]] / math.log2(rank + 1.0) for rank, index in enumerate(ideal, start=1))
    observed_dcg = sum(gains[pair] / math.log2(rank + 1.0) for rank, pair in enumerate(submitted_pairs, start=1))
    ndcg = observed_dcg / ideal_dcg if ideal_dcg > 0.0 else 1.0
    overlap = len(set(submitted_pairs).intersection(pairs[index] for index in ideal)) / top_k
    return 0.7 * ndcg + 0.3 * overlap, {"ndcg": ndcg, "overlap": overlap}


def score_case(
    parsed: dict[str, Any], input_dir: Path, truth_path: Path, manifest: dict
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    expected_counts, expected_probabilities, expected_spectra = expected_pipeline(input_dir, manifest)
    mandatory_failures: list[str] = []
    if not np.array_equal(parsed["counts"], expected_counts):
        mandatory_failures.append("exact-corrected-counts")
    if not elementwise_close(parsed["aggregated_probabilities"], expected_probabilities, 2e-10, 2e-9):
        mandatory_failures.append("aggregate-probability-consistency")
    if not elementwise_close(parsed["spectra"], expected_spectra, 2e-10, 2e-9):
        mandatory_failures.append("walsh-spectrum-consistency")
    count_fraction = float(np.mean(parsed["counts"] == expected_counts))
    aggregate_score, aggregate_ratio = tolerance_score(
        parsed["aggregated_probabilities"], expected_probabilities, 2e-10, 2e-9
    )
    spectra_score, spectra_ratio = tolerance_score(parsed["spectra"], expected_spectra, 2e-10, 2e-9)
    pipeline_score = min(count_fraction, aggregate_score, spectra_score)

    with np.load(truth_path, allow_pickle=False) as truth_archive:
        truth_distribution = np.asarray(truth_archive["distribution"], dtype=np.float64)
        truth_eigenvalues = np.asarray(truth_archive["eigenvalues"], dtype=np.float64)
        truth_amplitudes = np.asarray(truth_archive["amplitudes"], dtype=np.float64)
    decays = parsed["decays"]
    eigen_rmse = float(np.sqrt(np.mean((decays[:, 1] - truth_eigenvalues) ** 2)))
    amplitude_rmse = float(np.sqrt(np.mean((decays[:, 0] - truth_amplitudes) ** 2)))
    lengths = np.asarray(manifest["sequence_lengths"], dtype=np.float64)
    fitted = decays[:, 0][None, :] * decays[:, 1][None, :] ** lengths[:, None]
    submitted_losses = np.sum((fitted - parsed["spectra"]) ** 2, axis=0)
    minimum_losses = canonical_fit_minimum_losses(input_dir, lengths, expected_spectra)
    loss_allowance = np.maximum(2e-12, 2e-8 * np.maximum(minimum_losses, 1e-12))
    if np.any(submitted_losses - minimum_losses > loss_allowance):
        mandatory_failures.append("bounded-decay-global-minimum")
    if abs(float(decays[0, 0]) - 1.0) > 2e-10 or abs(float(decays[0, 1]) - 1.0) > 2e-10:
        mandatory_failures.append("identity-mode-fixed")
    reported_rmse = np.sqrt(np.mean((fitted - parsed["spectra"]) ** 2, axis=0))
    if not elementwise_close(decays[:, 2], reported_rmse, 2e-9, 2e-7):
        mandatory_failures.append("fit-rmse-consistency")
    rmse_consistency, rmse_ratio = tolerance_score(decays[:, 2], reported_rmse, 2e-9, 2e-7)
    transform = character_matrix(int(manifest["bit_count"]))
    prediction_distances = []
    for probe_length in (int(max(lengths)) + 2, int(max(lengths)) + 5):
        submitted_spectrum = decays[:, 0] * decays[:, 1] ** probe_length
        truth_spectrum = truth_amplitudes * truth_eigenvalues ** probe_length
        submitted_prediction = np.maximum((transform @ submitted_spectrum) / transform.shape[0], 0.0)
        truth_prediction = np.maximum((transform @ truth_spectrum) / transform.shape[0], 0.0)
        submitted_total = float(submitted_prediction.sum())
        truth_total = float(truth_prediction.sum())
        if (
            not np.all(np.isfinite(submitted_prediction))
            or not math.isfinite(submitted_total)
            or submitted_total <= 0.0
            or not np.all(np.isfinite(truth_prediction))
            or not math.isfinite(truth_total)
            or truth_total <= 0.0
        ):
            raise GateFailure("held-out prediction is non-finite or has zero mass")
        submitted_prediction /= submitted_total
        truth_prediction /= truth_total
        prediction_distances.append(
            math.sqrt(max(0.0, 1.0 - float(np.sum(np.sqrt(submitted_prediction * truth_prediction)))))
        )
    prediction_error = float(np.mean(prediction_distances))
    spectral_score = (
        0.35 * lower_error_score(eigen_rmse, 0.010, 0.070)
        + 0.20 * lower_error_score(amplitude_rmse, 0.015, 0.090)
        + 0.30 * lower_error_score(prediction_error, 0.012, 0.080)
        + 0.15 * rmse_consistency
    )

    raw_from_eigenvalues = (transform @ decays[:, 1]) / transform.shape[0]
    projected_from_eigenvalues = simplex_projection(raw_from_eigenvalues)
    raw_consistency, raw_ratio = tolerance_score(parsed["raw_distribution"], raw_from_eigenvalues, 5e-9, 5e-7)
    projection_consistency, projection_ratio = tolerance_score(
        parsed["distribution"], projected_from_eigenvalues, 5e-9, 5e-7
    )
    if not elementwise_close(parsed["raw_distribution"], raw_from_eigenvalues, 5e-9, 5e-7):
        mandatory_failures.append("raw-inverse-consistency")
    if not elementwise_close(parsed["distribution"], projected_from_eigenvalues, 5e-9, 5e-7):
        mandatory_failures.append("simplex-projection-consistency")
    distribution_tv = 0.5 * float(np.sum(np.abs(parsed["distribution"] - truth_distribution)))
    distribution_score = (
        0.65 * lower_error_score(distribution_tv, 0.025, 0.115)
        + 0.15 * raw_consistency
        + 0.20 * projection_consistency
    )

    truth_pairs, truth_dependence = dependence_values(
        truth_distribution, int(manifest["bit_count"]), manifest
    )
    submitted_pairs, recomputed_dependence = dependence_values(
        parsed["distribution"], int(manifest["bit_count"]), manifest
    )
    if submitted_pairs != parsed["pairs"] or truth_pairs != submitted_pairs:
        raise GateFailure("internal dependence pair mismatch")
    dependence_consistency, dependence_ratio = tolerance_score(
        parsed["dependence"], recomputed_dependence, 5e-8, 5e-6
    )
    if not elementwise_close(parsed["dependence"], recomputed_dependence, 5e-8, 5e-6):
        mandatory_failures.append("dependence-consistency")
    mutual_error = float(np.mean(np.abs(parsed["dependence"][:, 0] - truth_dependence[:, 0])))
    conditional_error = float(np.mean(np.abs(parsed["dependence"][:, 1] - truth_dependence[:, 1])))
    pearson_error = float(np.sqrt(np.mean((parsed["dependence"][:, 2] - truth_dependence[:, 2]) ** 2)))
    topology_fraction = float(np.mean(parsed["dependence"][:, 3] == truth_dependence[:, 3]))
    dependence_score = (
        0.22 * lower_error_score(mutual_error, 0.0015, 0.012)
        + 0.24 * lower_error_score(conditional_error, 0.0010, 0.009)
        + 0.24 * lower_error_score(pearson_error, 0.025, 0.18)
        + 0.20 * dependence_consistency
        + 0.10 * topology_fraction
    )

    recomputed_local = reconstruct_local(parsed["distribution"], manifest)
    local_consistency, local_ratio = tolerance_score(
        parsed["local_distribution"], recomputed_local, 5e-8, 5e-6
    )
    if not elementwise_close(parsed["local_distribution"], recomputed_local, 5e-8, 5e-6):
        mandatory_failures.append("local-model-consistency")
    recomputed_js, recomputed_tv = divergence_metrics(parsed["distribution"], recomputed_local)
    summary_values = np.asarray(
        [
            parsed["summary"]["simplex_adjustment_l2"],
            parsed["summary"]["jensen_shannon_distance"],
            parsed["summary"]["total_variation_distance"],
        ]
    )
    summary_reference = np.asarray(
        [
            float(np.linalg.norm(parsed["distribution"] - parsed["raw_distribution"])),
            recomputed_js,
            recomputed_tv,
        ]
    )
    summary_consistency, summary_ratio = tolerance_score(summary_values, summary_reference, 5e-8, 5e-6)
    if not elementwise_close(summary_values, summary_reference, 5e-8, 5e-6):
        mandatory_failures.append("summary-metric-consistency")
    truth_local = reconstruct_local(truth_distribution, manifest)
    local_truth_tv = 0.5 * float(np.sum(np.abs(parsed["local_distribution"] - truth_local)))
    local_score = (
        0.55 * local_consistency
        + 0.25 * summary_consistency
        + 0.20 * lower_error_score(local_truth_tv, 0.030, 0.130)
    )
    rank_score, rank_details = ranking_score(parsed["summary"], truth_pairs, truth_dependence)

    components = {
        "pipeline": pipeline_score,
        "spectral_fit_and_prediction": spectral_score,
        "distribution": distribution_score,
        "dependence": dependence_score,
        "local_model": local_score,
        "nonlocal_ranking": rank_score,
    }
    diagnostics = {
        "aggregate_tolerance_ratio": aggregate_ratio,
        "spectra_tolerance_ratio": spectra_ratio,
        "eigenvalue_rmse": eigen_rmse,
        "amplitude_rmse": amplitude_rmse,
        "unseen_prediction_hellinger": prediction_error,
        "fit_rmse_tolerance_ratio": rmse_ratio,
        "raw_inverse_tolerance_ratio": raw_ratio,
        "projection_tolerance_ratio": projection_ratio,
        "distribution_total_variation": distribution_tv,
        "dependence_tolerance_ratio": dependence_ratio,
        "mean_mi_absolute_error": mutual_error,
        "mean_cmi_absolute_error": conditional_error,
        "pearson_rmse": pearson_error,
        "local_tolerance_ratio": local_ratio,
        "summary_tolerance_ratio": summary_ratio,
        "local_truth_total_variation": local_truth_tv,
        "ranking_ndcg": rank_details["ndcg"],
        "ranking_overlap": rank_details["overlap"],
    }
    return components, diagnostics, mandatory_failures


def aggregate_components(per_case: list[dict[str, float]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for component in per_case[0]:
        values = np.asarray([record[component] for record in per_case], dtype=np.float64)
        result[component] = float(0.75 * values.mean() + 0.25 * values.min())
    return result


def grade_submission(submission_dir: Path) -> dict[str, Any]:
    try:
        validate_source(submission_dir)
        suite = strict_json(REFERENCE_ROOT / "suite.json")
        per_case_components: list[dict[str, float]] = []
        case_records = []
        mandatory_failures: list[str] = []
        for case in suite["cases"]:
            case_id = case["case_id"]
            input_dir = HIDDEN_ROOT / case_id
            manifest = strict_json(input_dir / "manifest.json")
            output_dir, temporary = run_analyzer(submission_dir, input_dir)
            try:
                parsed = parse_output(output_dir, manifest)
                components, diagnostics, case_mandatory_failures = score_case(
                    parsed,
                    input_dir,
                    REFERENCE_ROOT / case_id / "truth.npz",
                    manifest,
                )
            finally:
                temporary.cleanup()
            per_case_components.append(components)
            mandatory_failures.extend(f"{case_id}:{failure}" for failure in case_mandatory_failures)
            case_records.append(
                {
                    "case_id": case_id,
                    "components": components,
                    "diagnostics": diagnostics,
                    "mandatory_failures": case_mandatory_failures,
                }
            )
        components = aggregate_components(per_case_components)
        weights = {
            "pipeline": 0.15,
            "spectral_fit_and_prediction": 0.20,
            "distribution": 0.20,
            "dependence": 0.20,
            "local_model": 0.15,
            "nonlocal_ranking": 0.10,
        }
        score = float(sum(components[name] * weight for name, weight in weights.items()))
        mandatory = {
            "pipeline": 0.98,
            "spectral_fit_and_prediction": 0.90,
            "distribution": 0.70,
            "dependence": 0.86,
            "local_model": 0.88,
            "nonlocal_ranking": 0.45,
        }
        passed = (
            score >= 0.84
            and all(components[name] >= threshold for name, threshold in mandatory.items())
            and not mandatory_failures
        )
        return {
            "schema_version": "spectral-correlation-audit-grade/v1",
            "task_id": "spectral-correlation-audit-v1",
            "hard_gate_failures": [],
            "score": score,
            "passed": passed,
            "components": components,
            "mandatory_failures": mandatory_failures,
            "cases": case_records,
        }
    except (GateFailure, OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, csv.Error, json.JSONDecodeError) as error:
        return {
            "schema_version": "spectral-correlation-audit-grade/v1",
            "task_id": "spectral-correlation-audit-v1",
            "hard_gate_failures": [str(error)],
            "score": 0.0,
            "passed": False,
            "components": {},
            "mandatory_failures": [],
            "cases": [],
        }
