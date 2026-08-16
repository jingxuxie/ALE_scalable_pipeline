#!/usr/bin/env python3
"""Cross-platform local verification for spectral-correlation-audit-v1."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

import numpy as np


sys.dont_write_bytecode = True
TASK_ROOT = Path(__file__).resolve().parents[1]
PAPER_ROOT = TASK_ROOT.parents[1]
PARTICIPANT = TASK_ROOT / "participant"
PRIVATE = TASK_ROOT / "private"
AUTHOR = TASK_ROOT / "author"
GRADER_DIR = PRIVATE / "grader"
sys.path.insert(0, str(GRADER_DIR))

from core import (  # noqa: E402
    GateFailure,
    aggregate_components,
    character_matrix,
    dependence_values,
    divergence_metrics,
    expected_pipeline,
    grade_submission,
    marginal,
    inspect_output,
    parse_output,
    reconstruct_local,
    run_analyzer,
    score_case,
    strict_json,
)


GENERATOR = AUTHOR / "oracle" / "generate.py"
REFERENCE_SOLVER = AUTHOR / "reference_solver"
ALTERNATIVE_SOLVER = AUTHOR / "alternative_solver"
CANONICAL_SUBMISSION = PRIVATE / "reference" / "canonical_submission"
MUTANT_BUILDER = PRIVATE / "mutants" / "build_mutants.py"
MUTANT_MANIFEST = PRIVATE / "mutants" / "manifest.json"
PUBLIC_VALIDATOR = PARTICIPANT / "software" / "validate_submission.py"


class Checks:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def run(self, check_id: str, function: Callable[[], Any], required: bool = True) -> None:
        started = time.perf_counter()
        try:
            details = function()
            self.records.append(
                {
                    "check_id": check_id,
                    "required": required,
                    "status": "pass",
                    "runtime_seconds": time.perf_counter() - started,
                    "details": details,
                }
            )
        except Exception as error:  # verification must report every gate
            self.records.append(
                {
                    "check_id": check_id,
                    "required": required,
                    "status": "fail",
                    "runtime_seconds": time.perf_counter() - started,
                    "error": f"{type(error).__name__}: {error}",
                }
            )


def command(arguments: list[str], cwd: Path, timeout: int = 120) -> dict[str, Any]:
    started = time.perf_counter()
    process = subprocess.run(
        arguments,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    result = {
        "returncode": process.returncode,
        "stdout": process.stdout.decode("utf-8", errors="replace"),
        "stderr": process.stderr.decode("utf-8", errors="replace"),
        "runtime_seconds": time.perf_counter() - started,
    }
    if process.returncode != 0:
        raise AssertionError(
            f"command failed ({process.returncode}): {' '.join(arguments)}\n{result['stderr'][-1200:]}"
        )
    return result


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def task_snapshot() -> dict[str, str]:
    return {
        path.relative_to(TASK_ROOT).as_posix(): file_digest(path)
        for path in sorted(TASK_ROOT.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def build_id(snapshot: dict[str, str]) -> str:
    hasher = hashlib.sha256()
    for path, digest in sorted(snapshot.items()):
        if path in {"author/verification_report.md", "author/task_spec.yaml"}:
            continue
        hasher.update(path.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(digest.encode("ascii"))
        hasher.update(b"\n")
    return "sha256:" + hasher.hexdigest()


def preflight() -> dict[str, Any]:
    required = [
        PARTICIPANT / "TASK.md",
        PARTICIPANT / "input" / "manifest.json",
        PARTICIPANT / "input" / "raw_counts.csv",
        PUBLIC_VALIDATOR,
        PRIVATE / "evaluation_spec.yaml",
        GRADER_DIR / "core.py",
        GRADER_DIR / "grade.py",
        GRADER_DIR / "guarded_runner.py",
        PRIVATE / "reference" / "suite.json",
        CANONICAL_SUBMISSION / "analyze.py",
        MUTANT_BUILDER,
        MUTANT_MANIFEST,
        AUTHOR / "task_spec.yaml",
        AUTHOR / "paper_blind_review.md",
        AUTHOR / "verification_report.md",
        GENERATOR,
        REFERENCE_SOLVER / "analyze.py",
        REFERENCE_SOLVER / "solve.py",
        ALTERNATIVE_SOLVER / "solve.py",
        PAPER_ROOT / "authoring" / "source_manifest.yaml",
        PAPER_ROOT / "authoring" / "evidence_map.yaml",
        PAPER_ROOT / "authoring" / "workflow_graph.yaml",
        PAPER_ROOT / "authoring" / "task_candidates.yaml",
        PAPER_ROOT / "authoring" / "session_report.md",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise AssertionError(f"required files missing: {missing}")
    python_files = sorted(TASK_ROOT.rglob("*.py"))
    for path in python_files:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    task_spec = (AUTHOR / "task_spec.yaml").read_text(encoding="utf-8")
    for identifier in (
        "claim-leaf-long-range-correlations-and-local-model-mismatch",
        "op-xor-correct-and-aggregate-counts",
        "op-rank-nonlocal-interactions",
        "structurally_hard_candidate",
    ):
        if identifier not in task_spec:
            raise AssertionError(f"task spec missing identifier {identifier}")
    for field in ("task_mode: audit", "path_base: task_root", "decision: needs_agent_calibration"):
        if field not in task_spec:
            raise AssertionError(f"task spec missing canonical field {field}")
    evaluation_spec = (PRIVATE / "evaluation_spec.yaml").read_text(encoding="utf-8")
    if "adversarial_attribute_cases:" not in evaluation_spec or "overlaps_primary_classes: true" not in evaluation_spec:
        raise AssertionError("private suite class accounting is ambiguous")
    if "\n  adversarial_cases:" in evaluation_spec:
        raise AssertionError("overlapping adversarial attributes are incorrectly declared as extra cases")
    blind_review = (AUTHOR / "paper_blind_review.md").read_text(encoding="utf-8").lower()
    if "- final status: pass" not in blind_review:
        raise AssertionError("paper-blind review has not reached final pass")
    return {"required_file_count": len(required), "python_file_count": len(python_files)}


def participant_audit() -> dict[str, Any]:
    expected = {
        "TASK.md",
        "input/manifest.json",
        "input/raw_counts.csv",
        "software/README.md",
        "software/validate_submission.py",
    }
    actual = {
        path.relative_to(PARTICIPANT).as_posix()
        for path in PARTICIPANT.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise AssertionError(f"participant inventory mismatch: {sorted(actual)}")
    forbidden = [
        "1907.13022",
        "efficient learning of quantum noise",
        "juqst",
        "melbourne",
        "rharper",
        "private/reference",
        "private/hidden",
    ]
    for path in PARTICIPANT.rglob("*"):
        if path.is_symlink():
            raise AssertionError(f"participant link forbidden: {path}")
        if path.is_file() and path.suffix.lower() in {".md", ".json", ".py", ".csv"}:
            lowered = path.read_text(encoding="utf-8").lower()
            for phrase in forbidden:
                if phrase in lowered:
                    raise AssertionError(f"participant leakage in {path}: {phrase}")
    manifest = strict_json(PARTICIPANT / "input" / "manifest.json")
    if manifest["schema_version"] != "spectral-correlation-audit-input/v1":
        raise AssertionError("public manifest schema mismatch")
    targets: set[int] = set()
    rows = 0
    with (PARTICIPANT / "input" / "raw_counts.csv").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows += 1
            targets.add(int(row["target_mask"]))
    if rows < 1000 or len(targets) < 16 or max(targets) < (1 << (manifest["bit_count"] - 1)):
        raise AssertionError("public raw counts do not exercise randomized high-bit targets")
    hasher = hashlib.sha256()
    for relative in sorted(actual):
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(file_digest(PARTICIPANT / relative).encode("ascii"))
        hasher.update(b"\n")
    return {
        "inventory": sorted(actual),
        "raw_rows": rows,
        "distinct_targets": len(targets),
        "participant_projection_id": "sha256:" + hasher.hexdigest(),
    }


def generated_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for relative_root in (Path("participant/input"), Path("private/hidden_inputs"), Path("private/reference")):
        directory = root / relative_root
        for path in directory.rglob("*"):
            if path.is_file():
                result[path.relative_to(root).as_posix()] = path
    return result


def physical_thinning_matrix(bit_count: int) -> np.ndarray:
    size = 1 << bit_count
    matrix = np.zeros((size, size), dtype=np.float64)
    for support_mask in range(size):
        observed_mask = support_mask
        while True:
            matrix[observed_mask, support_mask] = (2.0 / 3.0) ** observed_mask.bit_count() * (
                1.0 / 3.0
            ) ** (support_mask.bit_count() - observed_mask.bit_count())
            if observed_mask == 0:
                break
            observed_mask = (observed_mask - 1) & support_mask
    return matrix


def compare_generated(left: Path, right: Path) -> None:
    left_files = generated_files(left)
    right_files = generated_files(right)
    if set(left_files) != set(right_files):
        raise AssertionError("generated file inventory mismatch")
    for name in sorted(left_files):
        if name.endswith(".npz"):
            with np.load(left_files[name], allow_pickle=False) as first, np.load(right_files[name], allow_pickle=False) as second:
                if set(first.files) != set(second.files):
                    raise AssertionError(f"NPZ key mismatch: {name}")
                for key in first.files:
                    if not np.array_equal(first[key], second[key]):
                        raise AssertionError(f"NPZ value mismatch: {name}:{key}")
        elif left_files[name].read_bytes() != right_files[name].read_bytes():
            raise AssertionError(f"generated bytes mismatch: {name}")


def oracle_generation() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="spectral-oracle-regeneration-") as temporary:
        root = Path(temporary)
        first = root / "first"
        second = root / "second"
        command([sys.executable, "-B", str(GENERATOR), "--output-root", str(first)], TASK_ROOT)
        command([sys.executable, "-B", str(GENERATOR), "--output-root", str(second)], TASK_ROOT)
        compare_generated(first, second)
        compare_generated(first, TASK_ROOT)
        files = generated_files(first)
        suite = strict_json(first / "private" / "reference" / "suite.json")
        topology_degrees = {}
        for case in suite["cases"]:
            manifest = strict_json(first / "private" / "hidden_inputs" / case["case_id"] / "manifest.json")
            clique_count = len(manifest["local_model"]["cliques"])
            degrees = [0] * clique_count
            for left, right in manifest["local_model"]["tree_edges"]:
                degrees[int(left)] += 1
                degrees[int(right)] += 1
            topology_degrees[case["case_id"]] = max(degrees, default=0)
        if not any(degree >= 3 for degree in topology_degrees.values()) or not any(
            degree <= 2 for degree in topology_degrees.values()
        ):
            raise AssertionError(f"hidden suite lacks both chain and branched clique trees: {topology_degrees}")
    return {
        "generated_file_count": len(files),
        "regenerations": 2,
        "package_match": True,
        "hidden_topology_max_degrees": topology_degrees,
    }


def canonical_grade(result: dict[str, Any]) -> str:
    return json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)


def grade_twice(submission: Path) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    first = grade_submission(submission)
    second = grade_submission(submission)
    if canonical_grade(first) != canonical_grade(second):
        raise AssertionError("private evaluator is nondeterministic")
    return first, time.perf_counter() - started


def privileged_truth_oracle() -> dict[str, Any]:
    suite = strict_json(PRIVATE / "reference" / "suite.json")
    per_case_components = []
    case_records = []
    maximum_truth_error = 0.0
    maximum_physicality_roundtrip_error = 0.0
    minimum_pauli_support_probability = 1.0
    for case in suite["cases"]:
        case_id = case["case_id"]
        input_dir = PRIVATE / "hidden_inputs" / case_id
        manifest = strict_json(input_dir / "manifest.json")
        counts, probabilities, spectra = expected_pipeline(input_dir, manifest)
        with np.load(PRIVATE / "reference" / case_id / "truth.npz", allow_pickle=False) as archive:
            if str(np.asarray(archive["schema_version"]).item()) != "spectral-correlation-audit-truth/v1":
                raise AssertionError(f"privileged truth schema mismatch for {case_id}")
            distribution = np.asarray(archive["distribution"], dtype=np.float64)
            pauli_support = np.asarray(archive["pauli_support_distribution"], dtype=np.float64)
            spam = np.asarray(archive["spam_distribution"], dtype=np.float64)
            eigenvalues = np.asarray(archive["eigenvalues"], dtype=np.float64)
            amplitudes = np.asarray(archive["amplitudes"], dtype=np.float64)
        transform = character_matrix(int(manifest["bit_count"]))
        thinning = physical_thinning_matrix(int(manifest["bit_count"]))
        recovered_support = np.linalg.solve(thinning, distribution)
        physicality_error = max(
            float(np.max(np.abs(thinning @ pauli_support - distribution))),
            float(np.max(np.abs(recovered_support - pauli_support))),
        )
        maximum_physicality_roundtrip_error = max(maximum_physicality_roundtrip_error, physicality_error)
        minimum_pauli_support_probability = min(minimum_pauli_support_probability, float(pauli_support.min()))
        if float(recovered_support.min()) < -1e-12 or physicality_error > 2e-12:
            raise AssertionError(f"privileged Pauli-support physicality failure for {case_id}")
        transform_errors = [
            float(np.max(np.abs(transform @ distribution - eigenvalues))),
            float(np.max(np.abs(transform @ spam - amplitudes))),
            abs(float(distribution.sum()) - 1.0),
            abs(float(spam.sum()) - 1.0),
        ]
        for length in manifest["sequence_lengths"]:
            model_spectrum = amplitudes * eigenvalues ** int(length)
            model_distribution = (transform @ model_spectrum) / transform.shape[0]
            if float(model_distribution.min()) < -1e-12:
                raise AssertionError(f"privileged convolution law is non-probabilistic for {case_id}")
            transform_errors.extend(
                [
                    abs(float(model_distribution.sum()) - 1.0),
                    float(np.max(np.abs(transform @ model_distribution - model_spectrum))),
                ]
            )
        maximum_truth_error = max(maximum_truth_error, *transform_errors)
        if maximum_truth_error > 2e-12:
            raise AssertionError(f"privileged generator truth inconsistency: {maximum_truth_error}")

        lengths = np.asarray(manifest["sequence_lengths"], dtype=np.float64)
        fitted = amplitudes[None, :] * eigenvalues[None, :] ** lengths[:, None]
        decays = np.column_stack(
            [amplitudes, eigenvalues, np.sqrt(np.mean((fitted - spectra) ** 2, axis=0))]
        )
        raw_distribution = (transform @ eigenvalues) / transform.shape[0]
        local_distribution = reconstruct_local(distribution, manifest)
        pairs, dependence = dependence_values(distribution, int(manifest["bit_count"]), manifest)
        js_distance, total_variation = divergence_metrics(distribution, local_distribution)
        eligible = [index for index, row in enumerate(dependence) if int(row[3]) == 0]
        eligible.sort(key=lambda index: (-float(dependence[index, 1]), pairs[index]))
        top_k = int(manifest["local_model"]["top_k_nonlocal"])
        ranking = [
            {
                "rank": rank,
                "unit_i": pairs[index][0],
                "unit_j": pairs[index][1],
                "conditional_mutual_information": float(dependence[index, 1]),
            }
            for rank, index in enumerate(eligible[:top_k], start=1)
        ]
        parsed = {
            "counts": counts,
            "aggregated_probabilities": probabilities,
            "spectra": spectra,
            "decays": decays,
            "raw_distribution": raw_distribution,
            "distribution": distribution,
            "local_distribution": local_distribution,
            "pairs": pairs,
            "dependence": dependence,
            "summary": {
                "simplex_adjustment_l2": float(np.linalg.norm(distribution - raw_distribution)),
                "jensen_shannon_distance": js_distance,
                "total_variation_distance": total_variation,
                "nonlocal_ranking": ranking,
            },
        }
        components, diagnostics, mandatory_failures = score_case(
            parsed,
            input_dir,
            PRIVATE / "reference" / case_id / "truth.npz",
            manifest,
        )
        if set(mandatory_failures) - {"bounded-decay-global-minimum"}:
            raise AssertionError(
                f"privileged truth has unexpected contract exceptions for {case_id}: {mandatory_failures}"
            )
        if any(value < 1.0 - 1e-10 for value in components.values()):
            raise AssertionError(f"privileged truth does not saturate evaluator for {case_id}: {components}")
        per_case_components.append(components)
        case_records.append(
            {
                "case_id": case_id,
                "components": components,
                "diagnostics": diagnostics,
                "truth_record_contract_exceptions": mandatory_failures,
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
    if score < 1.0 - 1e-10:
        raise AssertionError(f"privileged truth oracle does not saturate evaluator: {score}")
    return {
        "score": score,
        "components": components,
        "case_count": len(case_records),
        "maximum_truth_consistency_error": maximum_truth_error,
        "maximum_physicality_roundtrip_error": maximum_physicality_roundtrip_error,
        "minimum_pauli_support_probability": minimum_pauli_support_probability,
        "truth_record_contract_exceptions": sorted(
            {
                failure
                for record in case_records
                for failure in record["truth_record_contract_exceptions"]
            }
        ),
    }


def canonical_reference_grading() -> dict[str, Any]:
    result, runtime = grade_twice(CANONICAL_SUBMISSION)
    if not result["passed"] or result["hard_gate_failures"]:
        raise AssertionError(f"canonical reference submission failed: {result}")
    return {"score": result["score"], "components": result["components"], "two_run_seconds": runtime}


def clean_room_reference() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="spectral-clean-room-") as temporary:
        root = Path(temporary)
        participant = root / "participant"
        solver = root / "reference_solver"
        submission = root / "submission"
        shutil.copytree(PARTICIPANT, participant)
        shutil.copytree(REFERENCE_SOLVER, solver)
        before = {path.relative_to(participant).as_posix(): file_digest(path) for path in participant.rglob("*") if path.is_file()}
        source_text = (solver / "solve.py").read_text(encoding="utf-8").lower()
        if any(token in source_text for token in ("private/", "hidden_inputs", "http://", "https://")):
            raise AssertionError("reference solver contains a forbidden dependency marker")
        solve = command(
            [sys.executable, "-I", "-B", str(solver / "solve.py"), "--participant", str(participant), "--submission", str(submission)],
            root,
        )
        after = {path.relative_to(participant).as_posix(): file_digest(path) for path in participant.rglob("*") if path.is_file()}
        if before != after:
            raise AssertionError("clean-room solver mutated participant assets")
        public_check = command([sys.executable, "-I", "-B", str(participant / "software" / "validate_submission.py"), str(submission)], root)
        result, grade_runtime = grade_twice(submission)
        if not result["passed"] or result["hard_gate_failures"]:
            raise AssertionError(f"clean-room reference failed: {result}")
        inventory = sorted(path.relative_to(submission).as_posix() for path in submission.rglob("*") if path.is_file())
    return {
        "score": result["score"],
        "components": result["components"],
        "solver_runtime_seconds": solve["runtime_seconds"],
        "public_validator_runtime_seconds": public_check["runtime_seconds"],
        "two_grade_seconds": grade_runtime,
        "submission_inventory": inventory,
        "hidden_access_audit": "only participant and solver copies existed during construction",
    }


def alternative_valid() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="spectral-alternative-") as temporary:
        root = Path(temporary)
        participant = root / "participant"
        author = root / "author"
        submission = root / "submission"
        shutil.copytree(PARTICIPANT, participant)
        shutil.copytree(REFERENCE_SOLVER, author / "reference_solver")
        shutil.copytree(ALTERNATIVE_SOLVER, author / "alternative_solver")
        solve = command(
            [sys.executable, "-I", "-B", str(author / "alternative_solver" / "solve.py"), "--participant", str(participant), "--submission", str(submission)],
            root,
        )
        result, grade_runtime = grade_twice(submission)
        if not result["passed"] or result["hard_gate_failures"]:
            raise AssertionError(f"alternative valid solver failed: {result}")
    return {
        "score": result["score"],
        "components": result["components"],
        "solver_runtime_seconds": solve["runtime_seconds"],
        "two_grade_seconds": grade_runtime,
        "independence": "multi-start damped Gauss-Newton fit and bisection simplex projection",
    }


def scientific_mutants() -> dict[str, Any]:
    manifest = strict_json(MUTANT_MANIFEST)
    with tempfile.TemporaryDirectory(prefix="spectral-mutants-") as temporary:
        output = Path(temporary) / "cases"
        command([sys.executable, "-B", str(MUTANT_BUILDER), str(CANONICAL_SUBMISSION), str(output)], TASK_ROOT)
        records = []
        for mutant in manifest["mutants"]:
            mutant_id = mutant["mutant_id"]
            result = grade_submission(output / mutant_id)
            if result["passed"]:
                raise AssertionError(f"scientific mutant passed: {mutant_id}: {result}")
            if mutant_id == "ascending-cmi-ranking":
                if result["hard_gate_failures"] != ["ranking is not the global top-k from dependence.csv"]:
                    raise AssertionError(f"ranking-contract mutant failed unexpectedly: {result}")
            elif result["hard_gate_failures"] or not result.get("mandatory_failures"):
                raise AssertionError(f"scientific mutant did not reach a mandatory scientific rejection: {mutant_id}: {result}")
            records.append(
                {
                    "mutant_id": mutant_id,
                    "category": mutant["category"],
                    "score": result["score"],
                    "components": result["components"],
                    "hard_gate_failures": result["hard_gate_failures"],
                    "mandatory_failures": result.get("mandatory_failures", []),
                }
            )
    return {
        "count": len(records),
        "scientific_mandatory_reject_count": 13,
        "hard_linked_ranking_reject_count": 1,
        "results": records,
    }


def mutation_source(base: str, old: str, new: str) -> str:
    if base.count(old) != 1:
        raise AssertionError(f"robustness anchor count {base.count(old)} for {old[:50]}")
    return base.replace(old, new, 1)


def robustness_checks() -> dict[str, Any]:
    base = (CANONICAL_SUBMISSION / "analyze.py").read_text(encoding="utf-8")

    def pathlib_probe(body: str) -> str:
        source = mutation_source(
            base,
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport pathlib\n",
        )
        return mutation_source(
            source,
            "def main() -> int:\n    parser = argparse.ArgumentParser()",
            "def main() -> int:\n" + body + "\n    parser = argparse.ArgumentParser()",
        )

    denied_probe = Path(tempfile.gettempdir()).resolve() / "spectral-audit-denied-probe.txt"
    mutable_policy_read = pathlib_probe(
        "    _fake = str(Path(pathlib.sys.argv[pathlib.sys.argv.index('--input') + 1]) / 'manifest.json')\n"
        "    pathlib.Path.resolve = lambda self, *args, **kwargs: Path(_fake)\n"
        "    pathlib.os.fspath = lambda value: _fake\n"
        "    pathlib.os.path.abspath = lambda value: _fake\n"
        "    pathlib.os.path.realpath = lambda value: _fake\n"
        "    pathlib.os.path.commonpath = lambda values: _fake\n"
        "    pathlib.os.PathLike = str\n"
        "    pathlib.os.O_WRONLY = pathlib.os.O_RDWR = pathlib.os.O_CREAT = 0\n"
        f"    open(r'{(PRIVATE / 'reference' / 'suite.json').resolve()}', 'r', encoding='utf-8').read()"
    )
    mutable_policy_write = pathlib_probe(
        "    _fake = str(Path(pathlib.sys.argv[pathlib.sys.argv.index('--output') + 1]) / 'inside.txt')\n"
        "    pathlib.Path.resolve = lambda self, *args, **kwargs: Path(_fake)\n"
        "    pathlib.os.fspath = lambda value: _fake\n"
        "    pathlib.os.path.abspath = lambda value: _fake\n"
        "    pathlib.os.path.realpath = lambda value: _fake\n"
        "    pathlib.os.path.commonpath = lambda values: _fake\n"
        "    pathlib.os.PathLike = str\n"
        "    pathlib.os.O_WRONLY = pathlib.os.O_RDWR = pathlib.os.O_CREAT = pathlib.os.O_TRUNC = 0\n"
        f"    open(r'{denied_probe}', 'w', encoding='utf-8').write('modified')"
    )
    low_level_exec = pathlib_probe(
        "    pathlib.os.execv(pathlib.sys.executable, [pathlib.sys.executable, '-c', 'raise SystemExit(0)'])"
    )
    relative_low_level_open = pathlib_probe(
        "    pathlib.os.close(pathlib.os.open('manifest.json', pathlib.os.O_WRONLY | pathlib.os.O_TRUNC))"
    )
    ctypes_probe = pathlib_probe(
        "    np.ctypeslib.ctypes.CDLL('spectral-audit-nonexistent-library')"
    )
    parent_traversal_probe = pathlib_probe(
        "    _input = Path(pathlib.sys.argv[pathlib.sys.argv.index('--input') + 1])\n"
        "    (_input / '..' / 'runner.stderr').read_text(encoding='utf-8')"
    )
    ftruncate_probe = pathlib_probe(
        "    _output = Path(pathlib.sys.argv[pathlib.sys.argv.index('--output') + 1])\n"
        "    _output.mkdir(parents=True)\n"
        "    _scratch = _output / 'fd-scratch.txt'\n"
        "    _scratch.write_text('abc', encoding='utf-8')\n"
        "    _fd = pathlib.os.open(_scratch, pathlib.os.O_RDWR)\n"
        "    try:\n"
        "        pathlib.os.ftruncate(_fd, 0)\n"
        "    finally:\n"
        "        pathlib.os.close(_fd)"
    )
    input_mutation_probe = pathlib_probe(
        "    _input = Path(pathlib.sys.argv[pathlib.sys.argv.index('--input') + 1])\n"
        "    (_input / 'manifest.json').write_text('modified', encoding='utf-8')"
    )
    case_root_mutation_probe = pathlib_probe(
        "    _output = Path(pathlib.sys.argv[pathlib.sys.argv.index('--output') + 1])\n"
        "    (_output.parent / 'escape.txt').write_text('modified', encoding='utf-8')"
    )
    aliased_eval_probe = pathlib_probe(
        "    _runner = eval\n"
        "    _runner('40 + 2')"
    )
    aliased_import_probe = pathlib_probe(
        "    _loader = __import__\n"
        "    _loader('socket')"
    )
    cases: dict[str, str] = {
        "malformed-source": "def broken(:\n",
        "forbidden-network-import": mutation_source(
            base,
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport socket\n",
        ),
        "oversized-source": base + "\n#" + ("x" * 160000),
        "forbidden-link-capability": mutation_source(
            base,
            "def main() -> int:\n    parser = argparse.ArgumentParser()",
            'def main() -> int:\n    Path("forbidden-link").symlink_to("target")\n    parser = argparse.ArgumentParser()',
        ),
        "private-path-read": mutation_source(
            base,
            "from __future__ import annotations\n",
            f'from __future__ import annotations\n\nPath_forbidden_probe = None\n',
        ),
        "partial-artifacts": mutation_source(base, 'output_dir / "summary.json"', 'output_dir / "wrong-summary.json"'),
        "nan-artifact": mutation_source(base, 'f"{distribution[mask]:.17g}",', '"nan",'),
        "inf-artifact": mutation_source(base, 'f"{local_distribution[mask]:.17g}",', '"inf",'),
        "extra-artifact": mutation_source(
            base,
            "    output_dir.mkdir(parents=True, exist_ok=True)\n",
            '    output_dir.mkdir(parents=True, exist_ok=True)\n    (output_dir / "extra.txt").write_text("extra", encoding="utf-8")\n',
        ),
        "duplicate-json-key": mutation_source(
            base,
            "json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)",
            "'{\"schema_version\":\"spectral-correlation-audit-result/v1\",\"schema_version\":\"duplicate\"}'",
        ),
        "oversized-runtime-output": mutation_source(
            base,
            'json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\\n",',
            'json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\\n" + (" " * 9000000),',
        ),
        "fabricated-ranking-value": mutation_source(
            base,
            '"conditional_mutual_information": float(record["conditional_mutual_information"]),',
            '"conditional_mutual_information": float(record["conditional_mutual_information"]) + 0.01,',
        ),
        "integer-overflow": mutation_source(
            base,
            "int(corrected_counts[index, mask]),",
            "(1 << 100),",
        ),
        "zero-mass-heldout-prediction": mutation_source(
            base,
            "amplitudes[0] = 1.0",
            "amplitudes[:] = 0.0",
        ),
        "oversized-csv-field": mutation_source(
            base,
            'f"{probabilities[index, mask]:.17g}"',
            'f"{probabilities[index, mask]:.17g}" if (index or mask) else ("1" * 200000)',
        ),
        "mutable-audit-policy-read": mutable_policy_read,
        "mutable-audit-policy-write": mutable_policy_write,
        "low-level-exec": low_level_exec,
        "relative-low-level-open": relative_low_level_open,
        "ctypes-capability": ctypes_probe,
        "parent-traversal-read": parent_traversal_probe,
        "ftruncate-capability": ftruncate_probe,
        "input-mutation": input_mutation_probe,
        "case-root-mutation": case_root_mutation_probe,
        "oversized-console-output": pathlib_probe("    print('x' * 50000)"),
        "aliased-dynamic-eval": aliased_eval_probe,
        "aliased-dynamic-import": aliased_import_probe,
    }
    # The private-read case must execute a prohibited read after pathlib is imported.
    cases["private-path-read"] = mutation_source(
        base,
        "def main() -> int:\n    parser = argparse.ArgumentParser()",
        f'def main() -> int:\n    Path(r"{(PRIVATE / "reference" / "suite.json").resolve()}").read_text(encoding="utf-8")\n    parser = argparse.ArgumentParser()',
    )
    expected_failure_fragments = {
        "mutable-audit-policy-read": "audit denied filesystem access: open",
        "mutable-audit-policy-write": "audit denied filesystem access: open",
        "low-level-exec": "audit denied capability: os.exec",
        "relative-low-level-open": "audit denied relative os.open access",
        "ctypes-capability": "audit denied capability: ctypes.",
        "parent-traversal-read": "audit denied filesystem access: open",
        "ftruncate-capability": "audit denied filesystem access: os.truncate",
        "truncate-outside-output": "audit denied filesystem access: os.truncate",
        "input-mutation": "audit denied filesystem access: open",
        "case-root-mutation": "audit denied filesystem access: open",
        "oversized-console-output": "analyzer exceeded the console output limit",
        "aliased-dynamic-eval": "audit denied capability: compile",
        "aliased-dynamic-import": "audit denied import: socket",
    }
    protected_files = [
        CANONICAL_SUBMISSION / "analyze.py",
        PARTICIPANT / "input" / "manifest.json",
        PARTICIPANT / "input" / "raw_counts.csv",
    ]
    protected_before = {path: file_digest(path) for path in protected_files}
    hard_results = []
    with tempfile.TemporaryDirectory(prefix="spectral-robustness-") as temporary:
        root = Path(temporary)
        denied_probe = root / "denied-probe.txt"
        denied_probe.write_text("unchanged", encoding="utf-8")
        cases["mutable-audit-policy-write"] = pathlib_probe(
            "    _fake = str(Path(pathlib.sys.argv[pathlib.sys.argv.index('--output') + 1]) / 'inside.txt')\n"
            "    pathlib.Path.resolve = lambda self, *args, **kwargs: Path(_fake)\n"
            "    pathlib.os.fspath = lambda value: _fake\n"
            "    pathlib.os.path.abspath = lambda value: _fake\n"
            "    pathlib.os.path.realpath = lambda value: _fake\n"
            "    pathlib.os.path.commonpath = lambda values: _fake\n"
            "    pathlib.os.PathLike = str\n"
            "    pathlib.os.O_WRONLY = pathlib.os.O_RDWR = pathlib.os.O_CREAT = pathlib.os.O_TRUNC = 0\n"
            f"    open(r'{denied_probe}', 'w', encoding='utf-8').write('modified')"
        )
        cases["truncate-outside-output"] = pathlib_probe(
            f"    pathlib.os.truncate(r'{denied_probe}', 0)"
        )
        for case_id, source in cases.items():
            submission = root / case_id
            submission.mkdir()
            (submission / "analyze.py").write_text(source, encoding="utf-8")
            result = grade_submission(submission)
            if not result["hard_gate_failures"] or result["passed"] or result["score"] != 0.0:
                raise AssertionError(f"robustness case did not hard-fail: {case_id}: {result}")
            failure = result["hard_gate_failures"][0]
            expected_fragment = expected_failure_fragments.get(case_id)
            if expected_fragment is not None and expected_fragment not in failure:
                raise AssertionError(f"security probe {case_id} failed for the wrong reason: {failure}")
            hard_results.append({"case_id": case_id, "failure": failure})
        if denied_probe.read_text(encoding="utf-8") != "unchanged":
            raise AssertionError("mutable audit-policy probe escaped its isolated case root")

        public_limit_probes = {}
        for case_id, expected_fragment in {
            "oversized-console-output": "console output exceeds limit",
            "oversized-runtime-output": "runtime artifacts exceed size limit",
        }.items():
            public_process = subprocess.run(
                [sys.executable, "-I", "-B", str(PUBLIC_VALIDATOR), str(root / case_id)],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            combined = (public_process.stdout + public_process.stderr).decode("utf-8", errors="replace")
            if public_process.returncode == 0 or expected_fragment not in combined:
                raise AssertionError(f"public live-limit probe failed: {case_id}: {combined[-800:]}")
            public_limit_probes[case_id] = "rejected"

        dir_fd_status = "unavailable-on-platform"
        if os.open in getattr(os, "supports_dir_fd", set()):
            dir_fd_source = pathlib_probe(
                "    _input = Path(pathlib.sys.argv[pathlib.sys.argv.index('--input') + 1])\n"
                "    _fd = pathlib.os.open(_input, pathlib.os.O_RDONLY)\n"
                "    try:\n"
                "        pathlib.os.close(pathlib.os.open('manifest.json', pathlib.os.O_WRONLY | pathlib.os.O_TRUNC, dir_fd=_fd))\n"
                "    finally:\n"
                "        pathlib.os.close(_fd)"
            )
            submission = root / "dir-fd-write"
            submission.mkdir()
            (submission / "analyze.py").write_text(dir_fd_source, encoding="utf-8")
            result = grade_submission(submission)
            failure = result["hard_gate_failures"][0] if result["hard_gate_failures"] else ""
            if result["passed"] or "audit denied relative os.open access" not in failure:
                raise AssertionError(f"dir_fd write probe was not denied by policy: {result}")
            dir_fd_status = "denied"

        fabricated = root / "fabricated-summary"
        fabricated.mkdir()
        fabricated_source = mutation_source(
            base,
            '"jensen_shannon_distance": js_distance,',
            '"jensen_shannon_distance": 0.0,',
        )
        (fabricated / "analyze.py").write_text(fabricated_source, encoding="utf-8")
        fabricated_result = grade_submission(fabricated)
        if fabricated_result["hard_gate_failures"] or fabricated_result["passed"]:
            raise AssertionError(f"fabricated summary was not rejected scientifically: {fabricated_result}")

        ordinary_state_source = mutation_source(
            base,
            "\n\n\ndef main() -> int:",
            "\n\nclass _State:\n"
            "    def __init__(self) -> None:\n"
            "        self.value = 1\n\n\n"
            "def main() -> int:",
        )
        ordinary_state_source = mutation_source(
            ordinary_state_source,
            "def main() -> int:\n    parser = argparse.ArgumentParser()",
            "def main() -> int:\n    _state = _State()\n    _state.value = 2\n    parser = argparse.ArgumentParser()",
        )
        inside_mutation_source = mutation_source(
            base,
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport pathlib\n",
        )
        inside_mutation_source = mutation_source(
            inside_mutation_source,
            "    analyze(arguments.input.resolve(), arguments.output.resolve())\n    return 0",
            "    analyze(arguments.input.resolve(), arguments.output.resolve())\n"
            "    _scratch = arguments.output / 'scratch.tmp'\n"
            "    _renamed = arguments.output / 'scratch-renamed.tmp'\n"
            "    _scratch.write_text('abcd', encoding='utf-8')\n"
            "    _scratch.replace(_renamed)\n"
            "    pathlib.os.truncate(_renamed, 2)\n"
            "    _renamed.unlink()\n"
            "    return 0",
        )
        valid_variants = {
            "strict-output-mkdir": mutation_source(
                base,
                "output_dir.mkdir(parents=True, exist_ok=True)",
                "output_dir.mkdir(parents=True, exist_ok=False)",
            ),
            "benign-string-method": mutation_source(
                base,
                "def main() -> int:\n    parser = argparse.ArgumentParser()",
                'def main() -> int:\n    _benign = "audit".replace("audit", "audit")\n    parser = argparse.ArgumentParser()',
            ),
            "ordinary-instance-state": ordinary_state_source,
            "ordinary-setattr-and-dunder": mutation_source(
                ordinary_state_source,
                "    _state.value = 2\n    parser = argparse.ArgumentParser()",
                "    _state.value = 2\n"
                "    setattr(_state, 'value', _state.__class__.__name__.__len__())\n"
                "    parser = argparse.ArgumentParser()",
            ),
            "inside-output-mutations": inside_mutation_source,
        }
        valid_variant_scores = {}
        for case_id, source in valid_variants.items():
            submission = root / case_id
            submission.mkdir()
            (submission / "analyze.py").write_text(source, encoding="utf-8")
            public_process = subprocess.run(
                [sys.executable, "-I", "-B", str(PUBLIC_VALIDATOR), str(submission)],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if public_process.returncode != 0:
                raise AssertionError(
                    f"public validator rejected valid policy variant {case_id}: "
                    + public_process.stderr.decode("utf-8", errors="replace")[-800:]
                )
            result = grade_submission(submission)
            if not result["passed"] or result["hard_gate_failures"] or result.get("mandatory_failures"):
                raise AssertionError(f"valid policy variant failed: {case_id}: {result}")
            valid_variant_scores[case_id] = result["score"]

        bom_submission = root / "utf8-bom-source"
        bom_submission.mkdir()
        (bom_submission / "analyze.py").write_bytes(b"\xef\xbb\xbf" + base.encode("utf-8"))
        public_process = subprocess.run(
            [sys.executable, "-I", "-B", str(PUBLIC_VALIDATOR), str(bom_submission)],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if public_process.returncode != 0:
            raise AssertionError(
                "public validator rejected valid UTF-8 BOM source: "
                + public_process.stderr.decode("utf-8", errors="replace")[-800:]
            )
        bom_result = grade_submission(bom_submission)
        if not bom_result["passed"] or bom_result["hard_gate_failures"] or bom_result.get("mandatory_failures"):
            raise AssertionError(f"private evaluator rejected valid UTF-8 BOM source: {bom_result}")
        valid_variant_scores["utf8-bom-source"] = bom_result["score"]

        contract_mutants = {
            "zero-raw-inverse": mutation_source(base, 'f"{raw_distribution[mask]:.17g}",', '"0",'),
            "shift-nonzero-amplitudes": mutation_source(
                base,
                "amplitudes[0] = 1.0",
                "amplitudes[1:] = np.clip(amplitudes[1:] + 0.05, 0.0, 1.0)\n    amplitudes[0] = 1.0",
            ),
            "corrupt-selected-counts": mutation_source(
                base,
                "int(corrected_counts[index, mask]),",
                "int(corrected_counts[index, mask]) + (1 if (index * state_count + mask) % 67 == 0 else 0),",
            ),
        }
        contract_results = {}
        for case_id, source in contract_mutants.items():
            submission = root / case_id
            submission.mkdir()
            (submission / "analyze.py").write_text(source, encoding="utf-8")
            result = grade_submission(submission)
            if result["passed"]:
                raise AssertionError(f"contract-bypass mutant passed: {case_id}: {result}")
            contract_results[case_id] = {
                "score": result["score"],
                "hard_gate_failures": result["hard_gate_failures"],
                "mandatory_failures": result.get("mandatory_failures", []),
            }

        symlink_root_status = "unavailable-on-platform"
        real_submission = root / "real-symlink-target"
        shutil.copytree(CANONICAL_SUBMISSION, real_submission)
        linked_submission = root / "linked-submission-root"
        try:
            linked_submission.symlink_to(real_submission, target_is_directory=True)
        except OSError:
            pass
        else:
            linked_result = grade_submission(linked_submission)
            if not linked_result["hard_gate_failures"] or linked_result["passed"]:
                raise AssertionError(f"private evaluator accepted a linked submission root: {linked_result}")
            public_process = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(PARTICIPANT / "software" / "validate_submission.py"),
                    str(linked_submission),
                ],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if public_process.returncode == 0:
                raise AssertionError("public validator accepted a linked submission root")
            symlink_root_status = "rejected-by-public-and-private"
        source_hardlink_status = "unavailable-on-platform"
        hardlink_target = root / "hardlink-source-target.py"
        hardlink_target.write_text(base, encoding="utf-8")
        hardlink_submission = root / "hardlink-submission"
        hardlink_submission.mkdir()
        try:
            os.link(hardlink_target, hardlink_submission / "analyze.py")
        except OSError:
            pass
        else:
            private_result = grade_submission(hardlink_submission)
            if not private_result["hard_gate_failures"] or private_result["passed"]:
                raise AssertionError(f"private evaluator accepted a hardlinked source: {private_result}")
            public_process = subprocess.run(
                [sys.executable, "-I", "-B", str(PUBLIC_VALIDATOR), str(hardlink_submission)],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if public_process.returncode == 0:
                raise AssertionError("public validator accepted a hardlinked source")
            source_hardlink_status = "rejected-by-public-and-private"

        runtime_hardlink_status = "unavailable-on-platform"
        output, output_temporary = run_analyzer(CANONICAL_SUBMISSION, PARTICIPANT / "input")
        try:
            anchor = Path(output_temporary.name) / "summary-hardlink-anchor.json"
            try:
                os.link(output / "summary.json", anchor)
            except OSError:
                pass
            else:
                try:
                    inspect_output(output)
                except GateFailure:
                    runtime_hardlink_status = "rejected-by-private-parser"
                else:
                    raise AssertionError("private parser accepted a hardlinked runtime artifact")
        finally:
            output_temporary.cleanup()

        public_hardlink_source = mutation_source(
            base,
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport pathlib\n",
        )
        public_hardlink_source = mutation_source(
            public_hardlink_source,
            "\n\n\ndef main() -> int:",
            "\n    pathlib.os.link(output_dir / 'summary.json', output_dir.parent / 'summary-hardlink-anchor.json')\n\n\ndef main() -> int:",
        )
        public_hardlink_submission = root / "runtime-hardlink-public"
        public_hardlink_submission.mkdir()
        (public_hardlink_submission / "analyze.py").write_text(public_hardlink_source, encoding="utf-8")
        public_process = subprocess.run(
            [sys.executable, "-I", "-B", str(PUBLIC_VALIDATOR), str(public_hardlink_submission)],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if public_process.returncode == 0:
            raise AssertionError("public validator accepted a hardlinked runtime artifact")
        if runtime_hardlink_status == "rejected-by-private-parser":
            runtime_hardlink_status = "rejected-by-public-and-private"
    protected_after = {path: file_digest(path) for path in protected_files}
    if protected_before != protected_after:
        raise AssertionError("security probes mutated protected source or input files")
    return {
        "hard_failure_count": len(hard_results),
        "hard_failures": hard_results,
        "fabricated_summary_score": fabricated_result["score"],
        "fabricated_summary_passed": fabricated_result["passed"],
        "valid_policy_variant_scores": valid_variant_scores,
        "contract_bypass_mutants": contract_results,
        "submission_root_symlink": symlink_root_status,
        "source_hardlink": source_hardlink_status,
        "runtime_hardlink": runtime_hardlink_status,
        "dir_fd_write": dir_fd_status,
        "public_live_limit_probes": public_limit_probes,
        "protected_source_and_input_unchanged": True,
        "stale_public_behavior": "covered by uniform-stale-analysis scientific mutant",
    }


def run_parsed(submission: Path, input_dir: Path) -> dict[str, Any]:
    manifest = strict_json(input_dir / "manifest.json")
    output, temporary = run_analyzer(submission, input_dir)
    try:
        return parse_output(output, manifest)
    finally:
        temporary.cleanup()


def write_derived_input(destination: Path, manifest: dict, rows: list[list[str]]) -> None:
    destination.mkdir(parents=True)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with (destination / "raw_counts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["length", "sequence_id", "target_mask", "observed_mask", "count"])
        writer.writerows(rows)


def semantic_difference(left: dict[str, Any], right: dict[str, Any], include_counts: bool = True) -> float:
    names = [
        "aggregated_probabilities",
        "spectra",
        "decays",
        "raw_distribution",
        "distribution",
        "local_distribution",
        "dependence",
    ]
    differences = [float(np.max(np.abs(left[name] - right[name]))) for name in names]
    if include_counts:
        differences.append(float(np.max(np.abs(left["counts"] - right["counts"]))))
    left_summary = left["summary"]
    right_summary = right["summary"]
    for field in ("simplex_adjustment_l2", "jensen_shannon_distance", "total_variation_distance"):
        differences.append(abs(float(left_summary[field]) - float(right_summary[field])))
    left_rank = left_summary["nonlocal_ranking"]
    right_rank = right_summary["nonlocal_ranking"]
    if [(row["unit_i"], row["unit_j"]) for row in left_rank] != [(row["unit_i"], row["unit_j"]) for row in right_rank]:
        return float("inf")
    differences.extend(
        abs(float(left_row["conditional_mutual_information"]) - float(right_row["conditional_mutual_information"]))
        for left_row, right_row in zip(left_rank, right_rank)
    )
    return max(differences)


def metamorphic_checks() -> dict[str, Any]:
    manifest = strict_json(PARTICIPANT / "input" / "manifest.json")
    with (PARTICIPANT / "input" / "raw_counts.csv").open("r", encoding="utf-8", newline="") as handle:
        source_rows = [row for row in csv.reader(handle)][1:]
    base = run_parsed(CANONICAL_SUBMISSION, PARTICIPANT / "input")
    with tempfile.TemporaryDirectory(prefix="spectral-metamorphic-") as temporary:
        root = Path(temporary)
        common_mask = (1 << int(manifest["bit_count"])) - 1
        xor_rows = [
            [row[0], row[1], str(int(row[2]) ^ common_mask), str(int(row[3]) ^ common_mask), row[4]]
            for row in source_rows
        ]
        write_derived_input(root / "xor", manifest, xor_rows)
        xor_result = run_parsed(CANONICAL_SUBMISSION, root / "xor")
        xor_difference = semantic_difference(base, xor_result)
        if xor_difference > 2e-12:
            raise AssertionError(f"common XOR invariance failed: {xor_difference}")

        split_rows: list[list[str]] = []
        for row in source_rows:
            count = int(row[4])
            if count > 1:
                split_rows.append(row[:4] + [str(count // 2)])
                split_rows.append(row[:4] + [str(count - count // 2)])
            else:
                split_rows.append(row)
        split_rows.reverse()
        write_derived_input(root / "split", manifest, split_rows)
        split_result = run_parsed(CANONICAL_SUBMISSION, root / "split")
        split_difference = semantic_difference(base, split_result)
        if split_difference > 2e-12:
            raise AssertionError(f"row split/order invariance failed: {split_difference}")

        scale_rows = [row[:4] + [str(3 * int(row[4]))] for row in source_rows]
        write_derived_input(root / "scaled", manifest, scale_rows)
        scaled_result = run_parsed(CANONICAL_SUBMISSION, root / "scaled")
        if not np.array_equal(scaled_result["counts"], 3 * base["counts"]):
            raise AssertionError("uniform count scaling did not scale corrected counts")
        scale_difference = semantic_difference(base, scaled_result, include_counts=False)
        if scale_difference > 2e-12:
            raise AssertionError(f"uniform count-scale invariance failed: {scale_difference}")

    bit_count = int(manifest["bit_count"])
    transform = character_matrix(bit_count)
    probe = np.linspace(-0.7, 0.9, 1 << bit_count)
    involution_error = float(np.max(np.abs(transform @ (transform @ probe) - (1 << bit_count) * probe)))
    if involution_error > 2e-12:
        raise AssertionError(f"transform involution failed: {involution_error}")
    thinning = physical_thinning_matrix(bit_count)
    support_probe = np.exp(np.linspace(-1.0, 1.0, 1 << bit_count))
    support_probe /= support_probe.sum()
    observed_probe = thinning @ support_probe
    recovered_probe = np.linalg.solve(thinning, observed_probe)
    physical_roundtrip_error = float(np.max(np.abs(recovered_probe - support_probe)))
    if physical_roundtrip_error > 2e-12 or float(recovered_probe.min()) < -1e-12:
        raise AssertionError(f"physical thinning round-trip failed: {physical_roundtrip_error}")
    reconstructed = reconstruct_local(base["distribution"], manifest)
    marginal_error = max(
        float(np.max(np.abs(marginal(base["distribution"], clique) - marginal(reconstructed, clique))))
        for clique in manifest["local_model"]["cliques"]
    )
    if marginal_error > 2e-10:
        raise AssertionError(f"junction-tree clique marginals changed: {marginal_error}")
    _, local_dependence = dependence_values(reconstructed, bit_count, manifest)
    nonlocal_cmi = float(np.max(local_dependence[local_dependence[:, 3] == 0, 1]))
    if nonlocal_cmi > 2e-10:
        raise AssertionError(f"junction-tree nonlocal all-rest CMI is nonzero: {nonlocal_cmi}")
    return {
        "common_target_xor_max_difference": xor_difference,
        "row_split_order_max_difference": split_difference,
        "uniform_scale_max_semantic_difference": scale_difference,
        "transform_involution_max_error": involution_error,
        "physical_thinning_roundtrip_max_error": physical_roundtrip_error,
        "clique_marginal_max_error": marginal_error,
        "local_nonco_clique_cmi_max": nonlocal_cmi,
    }


def metamorphic_determinism() -> dict[str, Any]:
    first = metamorphic_checks()
    second = metamorphic_checks()
    if json.dumps(first, sort_keys=True) != json.dumps(second, sort_keys=True):
        raise AssertionError("metamorphic results are nondeterministic")
    return first


def main() -> int:
    started = time.perf_counter()
    before = task_snapshot()
    checks = Checks()
    checks.run("preflight-and-authoring-cross-reference", preflight)
    checks.run("participant-leakage-and-input-audit", participant_audit)
    checks.run("oracle-regeneration-and-package-match", oracle_generation)
    checks.run("privileged-truth-oracle-and-evaluator-self-consistency", privileged_truth_oracle)
    checks.run("canonical-reference-grading-and-determinism", canonical_reference_grading)
    checks.run("clean-room-reference-and-determinism", clean_room_reference)
    checks.run("alternative-valid-implementation", alternative_valid)
    checks.run("schema-valid-scientific-mutants", scientific_mutants)
    checks.run("parser-security-and-malformed-cases", robustness_checks)
    checks.run("metamorphic-and-invariant-determinism", metamorphic_determinism)
    after = task_snapshot()
    unchanged = before == after
    checks.records.append(
        {
            "check_id": "verification-does-not-mutate-package",
            "required": True,
            "status": "pass" if unchanged else "fail",
            "runtime_seconds": 0.0,
            **({"details": {"file_count": len(after)}} if unchanged else {"error": "task tree changed during verification"}),
        }
    )
    required_failures = [record["check_id"] for record in checks.records if record["required"] and record["status"] != "pass"]
    payload = {
        "schema_version": "spectral-correlation-audit-verification/v1",
        "task_id": "spectral-correlation-audit-v1",
        "exact_task_build_id": build_id(after),
        "status": "pass" if not required_failures else "fail",
        "release_decision": "needs_agent_calibration" if not required_failures else "rejected_verification_failure",
        "provisional_difficulty": "structurally_hard_candidate",
        "frontier_agent_calibration": "not_run",
        "checks": checks.records,
        "required_failures": required_failures,
        "total_runtime_seconds": time.perf_counter() - started,
    }
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0 if not required_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
