#!/usr/bin/env python3
"""Run every local release gate for the periodic orbital transport task.

This script is intentionally self-contained and cross-platform.  It requires
only Python's standard library and NumPy, performs no network access, and never
uses a shell.  Detailed machine-readable results are written beneath
``author/verification_logs``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "periodic-orbital-transport-verification/v1"
EXPECTED_MUTANTS = {
    "mutant_advanced_branch.py",
    "mutant_caroli_no_dagger.py",
    "mutant_dos_factor.py",
    "mutant_eta_real_shift.py",
    "mutant_nan.py",
    "mutant_omit_periodic.py",
    "mutant_partial.py",
    "mutant_stale_public.py",
    "mutant_wrong_sp_sign.py",
}
SCIENTIFIC_MUTANTS = EXPECTED_MUTANTS - {
    "mutant_nan.py",
    "mutant_partial.py",
    "mutant_stale_public.py",
}
PARTICIPANT_FILES = {
    "TASK.md",
    "input/public_rotated_multispecies.json",
    "input/public_scalar_diatomic.json",
    "input/schema.json",
    "software/io_utils.py",
    "software/solution.py",
}
REQUIRED_TASK_FILES = {
    "author/alternative_solver/solve.py",
    "author/oracle/generate_assets.py",
    "author/oracle/manifest.json",
    "author/reference_solver/solve.py",
    "author/task_spec.yaml",
    "author/verification_report.md",
    "participant/TASK.md",
    "participant/input/schema.json",
    "participant/software/io_utils.py",
    "participant/software/solution.py",
    "private/evaluation_spec.yaml",
    "private/grader/__init__.py",
    "private/grader/evaluate.py",
    "private/grader/science.py",
    "scripts/verify.py",
}
FORBIDDEN_PARTICIPANT_TEXT = {
    "2010.07463",
    "arxiv.org",
    "author/reference",
    "authoring/sources",
    "evaluation_spec",
    "hidden_inputs",
    "nanonet",
    "paper2ale",
    "private/grader",
    "private/reference",
    "reference_solver",
    "source_manifest",
}
FORBIDDEN_SOLVER_IMPORTS = {
    "aiohttp",
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
}
PACKED_MUTANT_IMPORTS = {"base64", "gzip", "marshal"}
PACKED_MUTANT_CALLS = {"compile", "eval", "exec"}
EVALUATOR_TIMEOUT_SECONDS = 31.0 * 60.0
ORACLE_TIMEOUT_SECONDS = 10.0 * 60.0
MAX_CAPTURE_BYTES = 4 * 1024 * 1024


class VerificationFailure(RuntimeError):
    """A local release gate did not pass."""


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        try:
            return bool(is_junction())
        except OSError:
            return True
    return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _reject_json_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant {token!r}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise VerificationFailure(f"invalid JSON at {path}: {exc}") from exc


def _write_json(path: Path, document: Any) -> None:
    payload = (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
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
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _scrubbed_environment(temporary_root: Path | None = None) -> dict[str, str]:
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
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in allowed
    }
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
        }
    )
    if temporary_root is not None:
        environment["TEMP"] = str(temporary_root)
        environment["TMP"] = str(temporary_root)
        environment["TMPDIR"] = str(temporary_root)
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT"):
        environment.pop(name, None)
    return environment


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    expected_codes: set[int],
    environment_root: Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=_scrubbed_environment(environment_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerificationFailure(f"command could not complete: {exc}") from exc
    elapsed = time.perf_counter() - started
    stdout = completed.stdout[: MAX_CAPTURE_BYTES + 1]
    stderr = completed.stderr[: MAX_CAPTURE_BYTES + 1]
    if len(stdout) > MAX_CAPTURE_BYTES or len(stderr) > MAX_CAPTURE_BYTES:
        raise VerificationFailure("verification subprocess emitted excessive console output")
    try:
        stdout_text = stdout.decode("utf-8")
        stderr_text = stderr.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VerificationFailure("verification subprocess emitted non-UTF-8 text") from exc
    record = {
        "command": list(command),
        "cwd": str(cwd),
        "elapsed_seconds": elapsed,
        "return_code": completed.returncode,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }
    if completed.returncode not in expected_codes:
        raise VerificationFailure(
            f"unexpected return code {completed.returncode}; stderr={stderr_text[-2000:]!r}"
        )
    return record


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _parse_source(path: Path) -> tuple[str, ast.Module]:
    if _is_link_like(path) or not path.is_file():
        raise VerificationFailure(f"Python source is missing or link-like: {path}")
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise VerificationFailure(f"invalid Python source {path}: {exc}") from exc
    return source, tree


def _audit_solver_source(path: Path) -> dict[str, Any]:
    source, tree = _parse_source(path)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    forbidden = sorted(imports & FORBIDDEN_SOLVER_IMPORTS)
    if forbidden:
        raise VerificationFailure(f"{path.name} imports forbidden modules: {forbidden}")
    nondeclared = sorted(
        name for name in imports if name != "numpy" and name not in sys.stdlib_module_names
    )
    if nondeclared:
        raise VerificationFailure(f"{path.name} imports undeclared packages: {nondeclared}")
    normalized = source.lower().replace("\\", "/")
    markers = sorted(token for token in FORBIDDEN_PARTICIPANT_TEXT if token in normalized)
    if markers:
        raise VerificationFailure(f"{path.name} contains source/private markers: {markers}")
    return {
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "import_roots": sorted(imports),
    }


def _syntax_and_source_gate(task_root: Path) -> dict[str, Any]:
    parsed: list[str] = []
    for path in sorted(task_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        _parse_source(path)
        parsed.append(path.relative_to(task_root).as_posix())
    parsed_json: list[str] = []
    for path in sorted(task_root.rglob("*.json")):
        _read_json(path)
        parsed_json.append(path.relative_to(task_root).as_posix())

    placeholder_files: list[str] = []
    placeholder_tokens = (
        "<task ID>",
        "<task-id>",
        "<status>",
        "<paper citation",
        "<fill",
        "PLACEHOLDER",
    )
    for relative in (
        "author/task_spec.yaml",
        "author/verification_report.md",
        "private/evaluation_spec.yaml",
    ):
        path = task_root / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise VerificationFailure(f"metadata is not UTF-8 text: {relative}") from exc
        hits = [token for token in placeholder_tokens if token.lower() in text.lower()]
        if hits:
            raise VerificationFailure(f"metadata contains template placeholders: {relative}: {hits}")
        placeholder_files.append(relative)
    reference = _audit_solver_source(task_root / "author" / "reference_solver" / "solve.py")
    alternative = _audit_solver_source(
        task_root / "author" / "alternative_solver" / "solve.py"
    )
    return {
        "python_sources_parsed": parsed,
        "json_files_parsed": parsed_json,
        "metadata_placeholder_checks": placeholder_files,
        "reference_solver": reference,
        "alternative_solver": alternative,
    }


def _schema_bounds(schema: Mapping[str, Any]) -> dict[str, Any]:
    try:
        properties = schema["properties"]
        definitions = schema["$defs"]
        device = definitions["device_record"]["properties"]
        phase_grid = definitions.get("phase_grid", definitions.get("finite_grid"))
        energy_grid = definitions.get("energy_grid", definitions.get("finite_grid"))
        if not isinstance(phase_grid, Mapping) or not isinstance(energy_grid, Mapping):
            raise KeyError("bounded phase/energy grid definitions")
        result = {
            "species_max": properties["species"]["maxProperties"],
            "sites_max": properties["sites"]["maxItems"],
            "phase_grid_max": phase_grid["maxItems"],
            "energy_grid_max": energy_grid["maxItems"],
            "cells_max": device["cells"]["maximum"],
            "eta_max": properties["eta"]["maximum"],
        }
    except (KeyError, TypeError) as exc:
        raise VerificationFailure(
            "public schema must bound species, sites, grids, cells, and eta"
        ) from exc
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in result.values()):
        raise VerificationFailure("public schema resource bounds must be numeric")
    if any(float(value) <= 0.0 for value in result.values()):
        raise VerificationFailure("public schema resource bounds must be positive")
    return result


def _package_gate(task_root: Path) -> dict[str, Any]:
    missing = sorted(
        relative
        for relative in REQUIRED_TASK_FILES
        if not (task_root / Path(relative)).is_file()
    )
    if missing:
        raise VerificationFailure(f"required task files are missing: {missing}")

    unsafe_links = sorted(
        path.relative_to(task_root).as_posix()
        for path in task_root.rglob("*")
        if _is_link_like(path)
    )
    if unsafe_links:
        raise VerificationFailure(f"task package contains links/junctions: {unsafe_links}")

    cache_artifacts = sorted(
        path.relative_to(task_root).as_posix()
        for path in task_root.rglob("*")
        if path.name == "__pycache__" or path.suffix.lower() in {".pyc", ".pyo"}
    )
    if cache_artifacts:
        raise VerificationFailure(f"cache/bytecode artifacts are packaged: {cache_artifacts}")

    participant = task_root / "participant"
    relative_files: set[str] = set()
    total_bytes = 0
    participant_hashes: dict[str, str] = {}
    forbidden_hits: dict[str, list[str]] = {}
    for path in sorted(participant.rglob("*")):
        if _is_link_like(path):
            raise VerificationFailure(f"participant package contains a link: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(participant).as_posix()
        relative_files.add(relative)
        total_bytes += path.stat().st_size
        participant_hashes[relative] = _sha256(path)
        if path.suffix.lower() not in {".md", ".json", ".py"}:
            raise VerificationFailure(f"unexpected participant file type: {relative}")
        try:
            normalized = path.read_text(encoding="utf-8").lower().replace("\\", "/")
        except (OSError, UnicodeError) as exc:
            raise VerificationFailure(f"participant file is not UTF-8 text: {relative}") from exc
        hits = sorted(token for token in FORBIDDEN_PARTICIPANT_TEXT if token in normalized)
        if hits:
            forbidden_hits[relative] = hits
    if relative_files != PARTICIPANT_FILES:
        raise VerificationFailure(
            "participant projection mismatch; "
            f"missing={sorted(PARTICIPANT_FILES - relative_files)}, "
            f"unexpected={sorted(relative_files - PARTICIPANT_FILES)}"
        )
    if total_bytes > 2 * 1024 * 1024:
        raise VerificationFailure("participant projection exceeds 2 MiB")
    if forbidden_hits:
        raise VerificationFailure(f"participant text leaks source/private identifiers: {forbidden_hits}")

    private_author_hashes: set[str] = set()
    for zone in (task_root / "private", task_root / "author"):
        for path in zone.rglob("*"):
            if path.is_file() and not _is_link_like(path):
                private_author_hashes.add(_sha256(path))
    duplicated = sorted(
        relative for relative, digest in participant_hashes.items() if digest in private_author_hashes
    )
    if duplicated:
        raise VerificationFailure(
            f"participant files duplicate private/author artifacts: {duplicated}"
        )

    schema_document = _read_json(participant / "input" / "schema.json")
    if not isinstance(schema_document, Mapping):
        raise VerificationFailure("participant input schema must be a JSON object")
    bounds = _schema_bounds(schema_document)

    task_text = (participant / "TASK.md").read_text(encoding="utf-8")
    required_public_phrases = {
        "python output/solution.py --input INPUT.json --output OUTPUT_DIR",
        "hamiltonian.npz",
        "self_energies.npz",
        "spectra.npz",
        "diagnostics.json",
        "Public success criteria",
        "Environment and limits",
    }
    absent_phrases = sorted(phrase for phrase in required_public_phrases if phrase not in task_text)
    if absent_phrases:
        raise VerificationFailure(f"TASK.md omits public contract phrases: {absent_phrases}")

    return {
        "participant_files": sorted(relative_files),
        "participant_bytes": total_bytes,
        "schema_bounds": bounds,
        "private_author_hash_count": len(private_author_hashes),
        "forbidden_identifier_hits": {},
    }


def _oracle_gate(task_root: Path, logs: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(task_root / "author" / "oracle" / "generate_assets.py"),
        "--task-root",
        str(task_root),
        "--check",
    ]
    run = _run_command(
        command,
        cwd=task_root,
        timeout=ORACLE_TIMEOUT_SECONDS,
        expected_codes={0},
    )
    try:
        result = json.loads(run["stdout"])
    except json.JSONDecodeError as exc:
        raise VerificationFailure("oracle --check did not emit one JSON document") from exc
    if result.get("status") != "pass":
        raise VerificationFailure(f"oracle --check did not pass: {result}")
    log = {"run": run, "result": result}
    _write_json(logs / "oracle_check.json", log)
    return {
        "case_count": result.get("case_count"),
        "public_case_count": result.get("public_case_count"),
        "hidden_case_count": result.get("hidden_case_count"),
        "measured_total_oracle_seconds": result.get("measured_total_oracle_seconds"),
        "log": "author/verification_logs/oracle_check.json",
    }


def _manifest_gate(task_root: Path) -> dict[str, Any]:
    manifest_path = task_root / "author" / "oracle" / "manifest.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise VerificationFailure("oracle manifest must be a JSON object")
    if manifest.get("schema_version") != "periodic-orbital-assets-manifest/v1":
        raise VerificationFailure("oracle manifest schema version is wrong")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) < 9:
        raise VerificationFailure("oracle manifest needs a meaningful case suite")
    public = [case for case in cases if case.get("visibility") == "public"]
    hidden = [case for case in cases if case.get("visibility") == "hidden"]
    if len(public) != 2 or len(hidden) < 7:
        raise VerificationFailure(
            f"unexpected public/hidden inventory: public={len(public)}, hidden={len(hidden)}"
        )
    seeds = [case.get("seed") for case in cases]
    if len(set(seeds)) != len(seeds):
        raise VerificationFailure("case seeds are not pairwise distinct")

    limits = manifest.get("limits", {})
    invariant_maxima = {
        "max_surface_residual": 0.0,
        "max_hermiticity_residual": 0.0,
    }
    seen_models: set[str] = set()
    for case in cases:
        model_id = case.get("model_id")
        if not isinstance(model_id, str) or not model_id or model_id in seen_models:
            raise VerificationFailure(f"invalid or duplicate manifest model_id: {model_id!r}")
        seen_models.add(model_id)
        input_path = task_root / Path(str(case.get("input")))
        reference_path = task_root / Path(str(case.get("reference")))
        if not input_path.is_file() or not reference_path.is_dir():
            raise VerificationFailure(f"manifest path is missing for {model_id}")
        if _sha256(input_path) != case.get("input_sha256"):
            raise VerificationFailure(f"manifest input hash mismatch for {model_id}")
        checks = case.get("oracle_checks", {})
        rank_fraction = float(checks.get("h1_rank_fraction", -1.0))
        h1_norm = float(checks.get("h1_frobenius_norm", -1.0))
        surface = float(checks.get("max_surface_residual", math.inf))
        hermiticity = float(checks.get("max_hermiticity_residual", math.inf))
        if not all(math.isfinite(value) for value in (rank_fraction, h1_norm, surface, hermiticity)):
            raise VerificationFailure(f"non-finite oracle invariant for {model_id}")
        if rank_fraction < float(limits.get("minimum_h1_rank_fraction", 0.75)) or h1_norm <= 0.1:
            raise VerificationFailure(f"degenerate periodic coupling in {model_id}")
        if surface > 1.0e-10 or hermiticity > 1.0e-12:
            raise VerificationFailure(f"oracle residual too large in {model_id}")
        invariant_maxima["max_surface_residual"] = max(
            invariant_maxima["max_surface_residual"], surface
        )
        invariant_maxima["max_hermiticity_residual"] = max(
            invariant_maxima["max_hermiticity_residual"], hermiticity
        )

    generated = manifest.get("generated_files")
    if not isinstance(generated, list) or generated != sorted(set(generated)):
        raise VerificationFailure("generated file inventory must be sorted and unique")
    missing_generated = [relative for relative in generated if not (task_root / relative).is_file()]
    if missing_generated:
        raise VerificationFailure(f"generated files are missing: {missing_generated}")

    relations = manifest.get("metamorphic_pairs")
    if not isinstance(relations, list):
        raise VerificationFailure("metamorphic relation inventory is missing")
    relation_ids = {relation.get("id") for relation in relations}
    expected_relations = {"global_energy_shift", "site_list_permutation"}
    if relation_ids != expected_relations:
        raise VerificationFailure(f"metamorphic relation mismatch: {relation_ids}")
    metamorphic: dict[str, dict[str, float]] = {}
    for relation in relations:
        checks = relation.get("oracle_checks")
        if not isinstance(checks, Mapping) or not checks:
            raise VerificationFailure(f"metamorphic checks missing for {relation.get('id')}")
        converted = {str(name): float(value) for name, value in checks.items()}
        if not all(math.isfinite(value) and value <= 2.0e-9 for value in converted.values()):
            raise VerificationFailure(
                f"metamorphic relation {relation.get('id')} exceeds tolerance: {converted}"
            )
        metamorphic[str(relation["id"])] = converted
    return {
        "case_count": len(cases),
        "public_count": len(public),
        "hidden_count": len(hidden),
        "seed_count": len(set(seeds)),
        "invariant_maxima": invariant_maxima,
        "metamorphic_checks": metamorphic,
    }


def _run_evaluator(
    task_root: Path,
    logs: Path,
    log_name: str,
    *,
    submission: Path | None = None,
    artifacts_only: Path | None = None,
    inputs: Path | None = None,
    references: Path | None = None,
    expected_codes: set[int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (submission is None) == (artifacts_only is None):
        raise VerificationFailure("evaluator needs exactly one mode")
    log_path = logs / log_name
    command = [sys.executable, str(task_root / "private" / "grader" / "evaluate.py")]
    if submission is not None:
        command.extend(["--submission", str(submission)])
    else:
        assert artifacts_only is not None
        command.extend(["--artifacts-only", str(artifacts_only)])
    if inputs is not None:
        command.extend(["--inputs", str(inputs)])
    if references is not None:
        command.extend(["--references", str(references)])
    command.extend(["--json-out", str(log_path)])
    run = _run_command(
        command,
        cwd=task_root,
        timeout=EVALUATOR_TIMEOUT_SECONDS,
        expected_codes=expected_codes,
    )
    result = _read_json(log_path)
    if not isinstance(result, dict):
        raise VerificationFailure(f"evaluator log {log_name} is not a JSON object")
    try:
        stdout_result = json.loads(run["stdout"])
    except json.JSONDecodeError as exc:
        raise VerificationFailure(f"evaluator stdout for {log_name} is not JSON") from exc
    if stdout_result != result:
        raise VerificationFailure(f"evaluator stdout/log mismatch for {log_name}")
    return result, run


def _assert_passing_evaluation(result: Mapping[str, Any], label: str) -> None:
    if result.get("evaluator_error") is not None:
        raise VerificationFailure(f"{label} evaluator error: {result['evaluator_error']}")
    if result.get("hard_gates", {}).get("passed") is not True:
        raise VerificationFailure(f"{label} failed a hard gate")
    if result.get("passed") is not True or float(result.get("total_score", 0.0)) < 0.90:
        raise VerificationFailure(f"{label} did not pass: score={result.get('total_score')}")


def _oracle_artifact_evaluator_gate(task_root: Path, logs: Path) -> dict[str, Any]:
    result, run = _run_evaluator(
        task_root,
        logs,
        "oracle_artifacts_evaluation.json",
        artifacts_only=task_root / "private" / "reference",
        expected_codes={0},
    )
    _assert_passing_evaluation(result, "privileged oracle artifacts")
    return {
        "score": result["total_score"],
        "case_count": len(result["cases"]),
        "aggregate_output_bytes": result.get("aggregate_output_bytes"),
        "aggregate_expanded_output_bytes": result.get("aggregate_expanded_output_bytes"),
        "elapsed_seconds": run["elapsed_seconds"],
        "log": "author/verification_logs/oracle_artifacts_evaluation.json",
    }


def _public_clean_room_gate(task_root: Path, logs: Path) -> dict[str, Any]:
    manifest = _read_json(task_root / "author" / "oracle" / "manifest.json")
    public_cases = [case for case in manifest["cases"] if case["visibility"] == "public"]
    public_references = task_root / "author" / "oracle" / "public_reference"
    solvers = {
        "reference": task_root / "author" / "reference_solver" / "solve.py",
        "alternative": task_root / "author" / "alternative_solver" / "solve.py",
    }
    results: dict[str, Any] = {}
    for label, source in solvers.items():
        with tempfile.TemporaryDirectory(prefix=f"periodic-public-{label}-") as temporary:
            clean_root = Path(temporary)
            shutil.copytree(task_root / "participant", clean_root / "participant")
            submission = clean_root / "output" / "solution.py"
            submission.parent.mkdir(parents=True)
            shutil.copyfile(source, submission)
            input_root = clean_root / "public_inputs"
            input_root.mkdir()
            for case in public_cases:
                source_input = task_root / Path(case["input"])
                shutil.copyfile(source_input, input_root / source_input.name)

            inventory = sorted(
                path.relative_to(clean_root).as_posix()
                for path in clean_root.rglob("*")
                if path.is_file()
            )
            if any(
                any(token in relative.lower() for token in ("private", "author", "hidden"))
                for relative in inventory
            ):
                raise VerificationFailure(f"{label} clean room contains a non-public path")
            result, run = _run_evaluator(
                task_root,
                logs,
                f"public_{label}_evaluation.json",
                submission=submission,
                inputs=input_root,
                references=public_references,
                expected_codes={0},
            )
            _assert_passing_evaluation(result, f"public clean-room {label}")
            results[label] = {
                "score": result["total_score"],
                "case_count": len(result["cases"]),
                "aggregate_output_bytes": result.get("aggregate_output_bytes"),
                "aggregate_expanded_output_bytes": result.get(
                    "aggregate_expanded_output_bytes"
                ),
                "elapsed_seconds": run["elapsed_seconds"],
                "clean_room_inventory": inventory,
                "log": f"author/verification_logs/public_{label}_evaluation.json",
            }
    return results


def _hidden_evaluator_gate(task_root: Path, logs: Path) -> dict[str, Any]:
    solvers = {
        "reference": task_root / "author" / "reference_solver" / "solve.py",
        "alternative": task_root / "author" / "alternative_solver" / "solve.py",
    }
    summary: dict[str, Any] = {}
    for label, solver in solvers.items():
        first, first_run = _run_evaluator(
            task_root,
            logs,
            f"{label}_evaluation.json",
            submission=solver,
            expected_codes={0},
        )
        second, second_run = _run_evaluator(
            task_root,
            logs,
            f"{label}_evaluation_repeat.json",
            submission=solver,
            expected_codes={0},
        )
        _assert_passing_evaluation(first, f"hidden {label}")
        _assert_passing_evaluation(second, f"hidden {label} repeat")
        if first != second:
            raise VerificationFailure(f"hidden {label} evaluator result is not deterministic")
        summary[label] = {
            "score": first["total_score"],
            "case_count": len(first["cases"]),
            "aggregate_output_bytes": first.get("aggregate_output_bytes"),
            "aggregate_expanded_output_bytes": first.get(
                "aggregate_expanded_output_bytes"
            ),
            "deterministic_repeat": True,
            "elapsed_seconds": [
                first_run["elapsed_seconds"],
                second_run["elapsed_seconds"],
            ],
            "logs": [
                f"author/verification_logs/{label}_evaluation.json",
                f"author/verification_logs/{label}_evaluation_repeat.json",
            ],
        }
    return summary


def _mutant_source_gate(task_root: Path) -> dict[str, Any]:
    mutant_root = task_root / "private" / "mutants"
    actual = {path.name for path in mutant_root.glob("mutant_*.py") if path.is_file()}
    if actual != EXPECTED_MUTANTS:
        raise VerificationFailure(
            f"mutant inventory mismatch; missing={sorted(EXPECTED_MUTANTS - actual)}, "
            f"unexpected={sorted(actual - EXPECTED_MUTANTS)}"
        )
    clean_hash = _sha256(task_root / "author" / "reference_solver" / "solve.py")
    hashes: dict[str, str] = {}
    for name in sorted(actual):
        path = mutant_root / name
        source, tree = _parse_source(path)
        imports: set[str] = set()
        dynamic_calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call):
                name_part = _dotted_name(node.func)
                if name_part in PACKED_MUTANT_CALLS:
                    dynamic_calls.add(name_part)
        packed_markers = sorted(
            marker
            for marker in ("_CLEAN_SOLVER_GZIP", "b64decode", "gzip.decompress")
            if marker in source
        )
        if imports & PACKED_MUTANT_IMPORTS or dynamic_calls or packed_markers:
            raise VerificationFailure(
                f"{name} is a packed/dynamic wrapper rather than ordinary source; "
                f"imports={sorted(imports & PACKED_MUTANT_IMPORTS)}, "
                f"calls={sorted(dynamic_calls)}, markers={packed_markers}"
            )
        digest = _sha256(path)
        if digest == clean_hash:
            raise VerificationFailure(f"{name} is byte-identical to the clean solver")
        hashes[name] = digest
    if len(set(hashes.values())) != len(hashes):
        raise VerificationFailure("two or more mutant sources are byte-identical")
    return {"count": len(hashes), "source_sha256": hashes, "ordinary_unpacked": True}


def _mutant_evaluator_gate(task_root: Path, logs: Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name in sorted(EXPECTED_MUTANTS):
        result, run = _run_evaluator(
            task_root,
            logs,
            f"mutant_{Path(name).stem.removeprefix('mutant_')}_evaluation.json",
            submission=task_root / "private" / "mutants" / name,
            expected_codes={1},
        )
        if result.get("evaluator_error") is not None:
            raise VerificationFailure(f"{name} caused an evaluator error")
        if result.get("passed") is not False:
            raise VerificationFailure(f"{name} unexpectedly passed")
        hard_gate_passed = bool(result.get("hard_gates", {}).get("passed"))
        if name in SCIENTIFIC_MUTANTS and not hard_gate_passed:
            raise VerificationFailure(
                f"scientific mutant {name} failed structurally instead of being scored"
            )
        results[name] = {
            "passed": result["passed"],
            "total_score": result.get("total_score"),
            "hard_gates_passed": hard_gate_passed,
            "elapsed_seconds": run["elapsed_seconds"],
            "log": (
                "author/verification_logs/"
                f"mutant_{Path(name).stem.removeprefix('mutant_')}_evaluation.json"
            ),
        }
    return {"count": len(results), "all_rejected": True, "results": results}


def _security_probe_gate(task_root: Path, logs: Path) -> dict[str, Any]:
    probe_results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="periodic-security-probes-") as temporary:
        root = Path(temporary)
        sources = {
            "network": "import socket\nraise SystemExit(0)\n",
            "private_path": "TARGET = 'private/reference'\nraise SystemExit(0)\n",
        }
        expected_fragments = {
            "network": "forbidden network/process/dynamic facilities",
            "private_path": "forbidden source/private indicators",
        }
        for label, text in sources.items():
            source = root / f"{label}.py"
            source.write_text(text, encoding="utf-8", newline="\n")
            result, _run = _run_evaluator(
                task_root,
                logs,
                f"security_{label}_probe.json",
                submission=source,
                expected_codes={1},
            )
            failures = "\n".join(result.get("hard_gates", {}).get("failures", []))
            if result.get("passed") is not False or expected_fragments[label] not in failures:
                raise VerificationFailure(f"{label} security probe was not rejected correctly")
            probe_results[label] = {"rejected": True, "failure": failures}

        first_input = sorted((task_root / "private" / "hidden_inputs").glob("*.json"))[0]
        model_id = str(_read_json(first_input)["model_id"])
        source_reference = task_root / "private" / "reference" / model_id
        artifact_root = root / "oversized_artifacts"
        model_root = artifact_root / model_id
        model_root.mkdir(parents=True)
        for filename in ("hamiltonian.npz", "self_energies.npz", "spectra.npz"):
            shutil.copyfile(source_reference / filename, model_root / filename)
        (model_root / "diagnostics.json").write_bytes(b" " * (64 * 1024 + 1))
        oversized, _run = _run_evaluator(
            task_root,
            logs,
            "security_oversized_probe.json",
            artifacts_only=artifact_root,
            expected_codes={1},
        )
        oversized_failures = "\n".join(
            case_failure
            for case in oversized.get("cases", [])
            for case_failure in case.get("hard_gates", {}).get("failures", [])
        )
        if "diagnostics.json exceeds" not in oversized_failures:
            raise VerificationFailure("oversized artifact probe was not rejected by its size gate")
        probe_results["oversized_artifact"] = {
            "rejected": True,
            "failure": next(
                line for line in oversized_failures.splitlines() if "diagnostics.json exceeds" in line
            ),
        }

        symlink_result: dict[str, Any]
        symlink_root = root / "symlink_artifacts"
        symlink_model = symlink_root / model_id
        symlink_model.mkdir(parents=True)
        for filename in ("hamiltonian.npz", "self_energies.npz", "spectra.npz"):
            shutil.copyfile(source_reference / filename, symlink_model / filename)
        try:
            os.symlink(source_reference / "diagnostics.json", symlink_model / "diagnostics.json")
        except (OSError, NotImplementedError) as exc:
            symlink_result = {
                "supported_by_host": False,
                "static_policy_present": "_is_link_like" in (
                    task_root / "private" / "grader" / "evaluate.py"
                ).read_text(encoding="utf-8"),
                "reason": f"{type(exc).__name__}: {exc}",
            }
            if not symlink_result["static_policy_present"]:
                raise VerificationFailure("symlink probe unavailable and evaluator lacks link policy")
        else:
            symlink, _run = _run_evaluator(
                task_root,
                logs,
                "security_symlink_probe.json",
                artifacts_only=symlink_root,
                expected_codes={1},
            )
            failures = "\n".join(
                failure
                for case in symlink.get("cases", [])
                for failure in case.get("hard_gates", {}).get("failures", [])
            )
            if "not a regular file" not in failures:
                raise VerificationFailure("symlink artifact probe was not rejected")
            symlink_result = {"supported_by_host": True, "rejected": True, "failure": failures}
        probe_results["symlink_artifact"] = symlink_result
    return probe_results


def _environment_gate() -> dict[str, Any]:
    if sys.version_info < (3, 11):
        raise VerificationFailure("verification requires Python 3.11 or newer")
    try:
        numpy_parts = np.__version__.split(".")
        numpy_major = int(numpy_parts[0])
        numpy_minor = int(numpy_parts[1])
    except (ValueError, IndexError) as exc:
        raise VerificationFailure(f"cannot interpret NumPy version {np.__version__!r}") from exc
    if numpy_major not in {1, 2} or (numpy_major == 1 and numpy_minor < 26):
        raise VerificationFailure(f"NumPy version is outside the declared family: {np.__version__}")
    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "numpy": np.__version__,
        "platform": sys.platform,
        "network_used": False,
        "shell_used": False,
    }


def _run_gate(name: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        details = operation()
    except Exception as exc:
        return {
            "name": name,
            "passed": False,
            "elapsed_seconds": time.perf_counter() - started,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
    return {
        "name": name,
        "passed": True,
        "elapsed_seconds": time.perf_counter() - started,
        "details": details,
    }


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task-root",
        type=Path,
        default=default_root,
        help="Override the task root; defaults to the parent of scripts/.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    try:
        task_root = arguments.task_root.resolve(strict=True)
    except OSError as exc:
        sys.stderr.write(f"invalid task root: {exc}\n")
        return 2
    logs = task_root / "author" / "verification_logs"
    logs.mkdir(parents=True, exist_ok=True)

    operations: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("environment", _environment_gate),
        ("syntax_and_solver_static_audit", lambda: _syntax_and_source_gate(task_root)),
        ("participant_package_and_leakage", lambda: _package_gate(task_root)),
        ("deterministic_privileged_oracle", lambda: _oracle_gate(task_root, logs)),
        (
            "privileged_oracle_artifact_evaluation",
            lambda: _oracle_artifact_evaluator_gate(task_root, logs),
        ),
        ("metamorphic_and_scientific_invariants", lambda: _manifest_gate(task_root)),
        ("public_clean_room_solvers", lambda: _public_clean_room_gate(task_root, logs)),
        ("hidden_evaluator_and_repeat", lambda: _hidden_evaluator_gate(task_root, logs)),
        ("ordinary_mutant_source_audit", lambda: _mutant_source_gate(task_root)),
        ("mutant_evaluator_rejection", lambda: _mutant_evaluator_gate(task_root, logs)),
        ("evaluator_security_and_size_probes", lambda: _security_probe_gate(task_root, logs)),
    ]

    gate_results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for name, operation in operations:
        print(f"[verify] {name} ...", flush=True)
        result = _run_gate(name, operation)
        gate_results.append(result)
        print(f"[verify] {name}: {'PASS' if result['passed'] else 'FAIL'}", flush=True)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "task_root": str(task_root),
        "passed": all(result["passed"] for result in gate_results),
        "elapsed_seconds": time.perf_counter() - started,
        "gates": gate_results,
    }
    _write_json(logs / "verification_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
