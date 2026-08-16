#!/usr/bin/env python3
"""Public structural runner. This does not expose private scoring."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time


TASK_PARTICIPANT = Path(__file__).resolve().parents[1]
EXPECTED_FILES = {
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
    "dependence.csv": ["unit_i", "unit_j", "mutual_information", "conditional_mutual_information", "pearson_correlation", "co_local"],
}
IDENTIFIER_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
MAX_SOURCE_BYTES = 150_000
MAX_OUTPUT_BYTES = 8_000_000
MAX_CONSOLE_BYTES = 40_000
TIME_LIMIT_SECONDS = 45.0


def fail(message: str) -> None:
    raise ValueError(message)


def finite(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value) or abs(value) > 1e6:
        fail("non-finite or unsafe numeric value")
    return value


def json_number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{field} must be a JSON number")
    if not math.isfinite(float(value)) or abs(float(value)) > 1e6:
        fail(f"non-finite or unsafe JSON number in {field}")
    return float(value)


def json_integer(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        fail(f"{field} must be a JSON integer")
    return value


def valid_identifier(value) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and all(character in IDENTIFIER_CHARACTERS for character in value)
    )


def inspect_public_input(manifest: dict) -> None:
    input_dir = TASK_PARTICIPANT / "input"
    inventory = {path.name for path in input_dir.iterdir()}
    if inventory != {"manifest.json", "raw_counts.csv"}:
        fail("public input inventory mismatch")
    if (input_dir / "manifest.json").stat().st_size > 16_384:
        fail("public manifest exceeds the disclosed byte limit")
    if manifest.get("count_file") != "raw_counts.csv":
        fail("public count_file is not the disclosed authoritative filename")
    if not valid_identifier(manifest.get("experiment_id")):
        fail("public experiment_id is outside the disclosed identifier envelope")
    count_path = input_dir / "raw_counts.csv"
    if count_path.stat().st_size > 12_000_000:
        fail("public raw_counts.csv exceeds the disclosed byte limit")
    with count_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["length", "sequence_id", "target_mask", "observed_mask", "count"]:
            fail("public raw_counts.csv header mismatch")
        row_count = 0
        for row in reader:
            row_count += 1
            if row_count > 60_000:
                fail("public raw_counts.csv exceeds the disclosed row limit")
            if not valid_identifier(row.get("sequence_id")):
                fail("public sequence_id is outside the disclosed identifier envelope")


def inspect_source(submission: Path) -> bytes:
    try:
        root_info = submission.lstat()
        root_reparse = bool(getattr(root_info, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(root_info.st_mode) or root_reparse or not stat.S_ISDIR(root_info.st_mode):
            fail("submission must be a regular directory containing exactly analyze.py")
        if {path.name for path in submission.iterdir()} != {"analyze.py"}:
            fail("submission must be a regular directory containing exactly analyze.py")
    except ValueError:
        raise
    except OSError as error:
        raise ValueError("submission must be a regular directory containing exactly analyze.py") from error
    source = submission / "analyze.py"
    try:
        source_info = source.lstat()
        source_reparse = bool(getattr(source_info, "st_file_attributes", 0) & 0x400)
    except OSError as error:
        raise ValueError("analyze.py is missing, linked, or oversized") from error
    if (
        stat.S_ISLNK(source_info.st_mode)
        or source_reparse
        or not stat.S_ISREG(source_info.st_mode)
        or source_info.st_nlink > 1
        or source_info.st_size > MAX_SOURCE_BYTES
    ):
        fail("analyze.py is missing, linked, or oversized")
    try:
        with source.open("rb") as handle:
            opened_info = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened_info.st_mode) or opened_info.st_nlink > 1:
                fail("analyze.py changed during source validation")
            source_bytes = handle.read(MAX_SOURCE_BYTES + 1)
        if len(source_bytes) > MAX_SOURCE_BYTES:
            fail("analyze.py is missing, linked, or oversized")
        source_text = source_bytes.decode("utf-8-sig")
        ast.parse(source_text, filename="analyze.py")
    except ValueError:
        raise
    except (OSError, UnicodeError, SyntaxError) as error:
        raise ValueError(f"analyze.py must be valid UTF-8 Python syntax: {error}") from error
    return source_bytes


def runtime_output_bytes(output: Path) -> int:
    """Bound generated bytes during execution without following links."""
    total = 0
    try:
        paths = list(output.rglob("*"))
    except FileNotFoundError:
        return 0
    except OSError:
        return MAX_OUTPUT_BYTES + 1
    for path in paths:
        try:
            info = path.lstat()
        except FileNotFoundError:
            # Atomic-output writers may rename a temporary entry after rglob.
            # The next poll (and final strict inventory) observes its replacement.
            continue
        except OSError:
            return MAX_OUTPUT_BYTES + 1
        try:
            reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
            if stat.S_ISLNK(info.st_mode) or reparse:
                return MAX_OUTPUT_BYTES + 1
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > MAX_OUTPUT_BYTES:
                    return total
        except OSError:
            return MAX_OUTPUT_BYTES + 1
    return total


def read_rows(path: Path, header: list[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != header:
            fail(f"header mismatch in {path.name}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        fail(f"malformed row in {path.name}")
    return rows


def inspect_runtime(output: Path, manifest: dict) -> None:
    try:
        root_info = output.lstat()
        root_reparse = bool(getattr(root_info, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(root_info.st_mode) or root_reparse or not stat.S_ISDIR(root_info.st_mode):
            fail("runtime output inventory mismatch")
        entries = list(output.iterdir())
    except ValueError:
        raise
    except OSError as error:
        raise ValueError("runtime output inventory mismatch") from error
    if {path.name for path in entries} != EXPECTED_FILES:
        fail("runtime output inventory mismatch")
    infos = []
    for path in entries:
        info = path.lstat()
        reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            fail("runtime artifacts must be regular non-link files")
        infos.append(info)
    if sum(info.st_size for info in infos) > 8000000:
        fail("runtime artifacts exceed size limit")
    n = int(manifest["bit_count"])
    state_count = 1 << n
    lengths = [int(value) for value in manifest["sequence_lengths"]]
    expected_counts = {
        "aggregated.csv": len(lengths) * state_count,
        "spectra.csv": len(lengths) * state_count,
        "decays.csv": state_count,
        "distribution.csv": state_count,
        "dependence.csv": n * (n - 1) // 2,
    }
    aggregated = read_rows(output / "aggregated.csv", HEADERS["aggregated.csv"])
    spectra = read_rows(output / "spectra.csv", HEADERS["spectra.csv"])
    decays = read_rows(output / "decays.csv", HEADERS["decays.csv"])
    distribution = read_rows(output / "distribution.csv", HEADERS["distribution.csv"])
    dependence = read_rows(output / "dependence.csv", HEADERS["dependence.csv"])
    tables = {
        "aggregated.csv": aggregated,
        "spectra.csv": spectra,
        "decays.csv": decays,
        "distribution.csv": distribution,
        "dependence.csv": dependence,
    }
    for name, rows in tables.items():
        if len(rows) != expected_counts[name]:
            fail(f"row count mismatch in {name}")

    for index, row in enumerate(aggregated):
        length_index, mask = divmod(index, state_count)
        if int(row["length"]) != lengths[length_index] or int(row["error_mask"]) != mask or int(row["corrected_count"]) < 0:
            fail("aggregated.csv identities or integer fields mismatch")
    aggregate_probabilities = [finite(row["probability"]) for row in aggregated]
    for length_index in range(len(lengths)):
        block = aggregate_probabilities[length_index * state_count : (length_index + 1) * state_count]
        if min(block) < -1e-12 or abs(sum(block) - 1.0) > 1e-8:
            fail("aggregated probability block is not normalized")

    for index, row in enumerate(spectra):
        length_index, mode = divmod(index, state_count)
        if int(row["length"]) != lengths[length_index] or int(row["mode_mask"]) != mode:
            fail("spectra.csv identities mismatch")
        finite(row["coefficient"])
    for mode, row in enumerate(decays):
        if int(row["mode_mask"]) != mode:
            fail("decays.csv mode identity mismatch")
        amplitude = finite(row["amplitude"])
        eigenvalue = finite(row["eigenvalue"])
        rmse = finite(row["fit_rmse"])
        if not (-1e-12 <= amplitude <= 1.0 + 1e-8 and -1e-12 <= eigenvalue <= 1.0 + 1e-8 and rmse >= 0.0):
            fail("decay values leave public bounds")

    submitted_probability = []
    submitted_local = []
    for mask, row in enumerate(distribution):
        if int(row["error_mask"]) != mask:
            fail("distribution.csv mask identity mismatch")
        finite(row["raw_probability"])
        submitted_probability.append(finite(row["probability"]))
        submitted_local.append(finite(row["local_probability"]))
    for values in (submitted_probability, submitted_local):
        if min(values) < -1e-12 or abs(sum(values) - 1.0) > 1e-8:
            fail("submitted distribution is not simplex-valid")

    expected_pairs = [(unit_i, unit_j) for unit_i in range(n) for unit_j in range(unit_i + 1, n)]
    dependence_cmi = {}
    nonlocal_pairs = set()
    cliques = manifest["local_model"]["cliques"]
    for row, pair in zip(dependence, expected_pairs):
        if (int(row["unit_i"]), int(row["unit_j"])) != pair:
            fail("dependence.csv pair identity mismatch")
        mutual = finite(row["mutual_information"])
        conditional = finite(row["conditional_mutual_information"])
        pearson = finite(row["pearson_correlation"])
        co_local = int(row["co_local"])
        expected_local = int(any(pair[0] in clique and pair[1] in clique for clique in cliques))
        if co_local != expected_local or mutual < -1e-10 or conditional < -1e-10 or abs(pearson) > 1.0 + 1e-8:
            fail("dependence value or clique membership outside public bounds")
        dependence_cmi[pair] = conditional
        if not co_local:
            nonlocal_pairs.add(pair)

    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail(f"duplicate JSON key {key}")
            result[key] = value
        return result

    summary = json.loads(
        (output / "summary.json").read_text(encoding="utf-8"),
        parse_constant=lambda value: fail(f"invalid JSON constant {value}"),
        object_pairs_hook=reject_duplicates,
    )
    required = {"schema_version", "experiment_id", "bit_count", "simplex_adjustment_l2", "jensen_shannon_distance", "total_variation_distance", "nonlocal_ranking"}
    if not isinstance(summary, dict) or set(summary) != required:
        fail("summary.json key mismatch")
    if summary["schema_version"] != "spectral-correlation-audit-result/v1" or summary["experiment_id"] != manifest["experiment_id"] or json_integer(summary["bit_count"], "bit_count") != n:
        fail("summary.json identity mismatch")
    for field in ("simplex_adjustment_l2", "jensen_shannon_distance", "total_variation_distance"):
        if json_number(summary[field], field) < 0.0:
            fail("negative summary metric")
    ranking = summary["nonlocal_ranking"]
    if not isinstance(ranking, list) or len(ranking) != int(manifest["local_model"]["top_k_nonlocal"]):
        fail("summary ranking length mismatch")
    seen = set()
    previous_key = None
    for expected_rank, record in enumerate(ranking, start=1):
        if not isinstance(record, dict) or set(record) != {"rank", "unit_i", "unit_j", "conditional_mutual_information"}:
            fail("summary ranking record schema mismatch")
        pair = (
            json_integer(record["unit_i"], "unit_i"),
            json_integer(record["unit_j"], "unit_j"),
        )
        value = json_number(record["conditional_mutual_information"], "conditional_mutual_information")
        if json_integer(record["rank"], "rank") != expected_rank or pair not in nonlocal_pairs or pair in seen:
            fail("summary ranking identity mismatch")
        if abs(value - dependence_cmi[pair]) > max(5e-8, 5e-6 * abs(dependence_cmi[pair])):
            fail("summary ranking value does not match dependence.csv")
        key = (-value, pair[0], pair[1])
        if previous_key is not None and key < previous_key:
            fail("summary ranking order mismatch")
        previous_key = key
        seen.add(pair)
    expected_ranking = sorted(nonlocal_pairs, key=lambda pair: (-dependence_cmi[pair], pair[0], pair[1]))[: len(ranking)]
    observed_ranking = [(record["unit_i"], record["unit_j"]) for record in ranking]
    if observed_ranking != expected_ranking:
        fail("summary ranking is not the global top-k from dependence.csv")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", type=Path)
    arguments = parser.parse_args()
    submission = Path(os.path.abspath(arguments.submission))
    source_bytes = inspect_source(submission)
    manifest = json.loads((TASK_PARTICIPANT / "input" / "manifest.json").read_text(encoding="utf-8"))
    inspect_public_input(manifest)
    with tempfile.TemporaryDirectory(prefix="spectral-public-check-") as temporary:
        root = Path(temporary)
        source = root / "analyze.py"
        source.write_bytes(source_bytes)
        output = root / "runtime-output"
        stdout_path = root / "runner.stdout"
        stderr_path = root / "runner.stderr"
        environment = dict(os.environ)
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1",
            }
        )
        timed_out = False
        console_exceeded = False
        output_exceeded = False
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(
                [sys.executable, "-I", "-B", str(source), "--input", str(TASK_PARTICIPANT / "input"), "--output", str(output)],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                close_fds=True,
            )
            deadline = time.monotonic() + TIME_LIMIT_SECONDS
            while process.poll() is None:
                stdout_handle.flush()
                stderr_handle.flush()
                if stdout_path.stat().st_size + stderr_path.stat().st_size > MAX_CONSOLE_BYTES:
                    console_exceeded = True
                    process.terminate()
                    break
                if runtime_output_bytes(output) > MAX_OUTPUT_BYTES:
                    output_exceeded = True
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
        if timed_out:
            fail("analyzer exceeded the 45 second public-check limit")
        if console_exceeded or stdout_path.stat().st_size + stderr_path.stat().st_size > MAX_CONSOLE_BYTES:
            fail("console output exceeds limit")
        if output_exceeded or runtime_output_bytes(output) > MAX_OUTPUT_BYTES:
            fail("runtime artifacts exceed size limit")
        if process.returncode != 0:
            stderr = stderr_path.read_bytes()[-800:].decode("utf-8", errors="replace")
            fail("analyzer failed on the public input: " + stderr)
        inspect_runtime(output, manifest)
    print("public structural validation: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
