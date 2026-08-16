#!/usr/bin/env python3
"""Cross-platform release verification for the scalable local-noise task."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import numpy as np


sys.dont_write_bytecode = True
TASK_ROOT = Path(__file__).resolve().parents[1]
PARTICIPANT = TASK_ROOT / "participant"
CORE_PATH = TASK_ROOT / "private" / "grader" / "core.py"
GRADER_PATH = TASK_ROOT / "private" / "grader" / "grade.py"
GENERATOR_PATH = TASK_ROOT / "private" / "generator" / "generate.py"
ORACLE_PATH = TASK_ROOT / "author" / "oracle" / "generate.py"
REFERENCE_PATH = TASK_ROOT / "author" / "reference_solver" / "solve.py"
ALTERNATIVE_PATH = TASK_ROOT / "author" / "alternative_solver" / "solve.py"
MUTANT_BUILDER = TASK_ROOT / "private" / "mutants" / "build_mutants.py"
VALIDATOR = PARTICIPANT / "software" / "validate_submission.py"
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".py", ".txt", ".yaml", ".yml"}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(CORE_PATH.parent))
CORE = load_module("verify_local_core", CORE_PATH)
GRADE = load_module("verify_local_grade", GRADER_PATH)
GENERATOR = load_module("verify_local_generator", GENERATOR_PATH)


def clean_environment(hash_seed: str = "0") -> dict[str, str]:
    environment = dict(os.environ)
    for key in list(environment):
        if key.upper() in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}:
            environment.pop(key, None)
    environment.update(
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
    return environment


def run_process(command: list[str], cwd: Path, timeout: float = 180.0, hash_seed: str = "0") -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=clean_environment(hash_seed),
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def tree_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts
    }


def task_build_id(snapshot: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, file_hash in sorted(snapshot.items()):
        if relative in {"author/task_spec.yaml", "author/verification_report.md"}:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def tree_digest(root: Path) -> str:
    lines = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        lines.append(f"{path.relative_to(root).as_posix()}\0{sha256(path)}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def copy_task_for_generation(parent: Path, name: str, excluded_roots: tuple[Path, ...] = ()) -> Path:
    target = parent / name

    excluded = {path.as_posix() for path in excluded_roots}

    def ignore(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).resolve().relative_to(TASK_ROOT.resolve())
        return {
            name
            for name in names
            if name == "__pycache__"
            or name.endswith(".pyc")
            or (relative / name).as_posix() in excluded
        }

    shutil.copytree(
        TASK_ROOT,
        target,
        ignore=ignore,
    )
    return target


def parse_json_process(process: dict[str, Any], label: str) -> dict[str, Any]:
    if process["returncode"] != 0:
        raise AssertionError(f"{label} failed rc={process['returncode']}: {process['stderr'][-500:]}")
    try:
        result = json.loads(process["stdout"])
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{label} did not emit one JSON document: {exc}") from exc
    return result


class Checks:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def run(self, check_id: str, function: Callable[[], Any]) -> Any:
        started = time.perf_counter()
        try:
            details = function()
            self.records.append(
                {
                    "check_id": check_id,
                    "required": True,
                    "status": "pass",
                    "runtime_seconds": time.perf_counter() - started,
                    "details": details,
                }
            )
            return details
        except Exception as exc:
            self.records.append(
                {
                    "check_id": check_id,
                    "required": True,
                    "status": "fail",
                    "runtime_seconds": time.perf_counter() - started,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(limit=8),
                }
            )
            return None


def preflight() -> dict[str, Any]:
    required = [
        PARTICIPANT / "TASK.md", PARTICIPANT / "input" / "manifest.json", VALIDATOR,
        TASK_ROOT / "author" / "task_spec.yaml", TASK_ROOT / "author" / "spec_review.md",
        TASK_ROOT / "author" / "verification_report.md", TASK_ROOT / "private" / "evaluation_spec.yaml",
        CORE_PATH, GRADER_PATH, GENERATOR_PATH, ORACLE_PATH, REFERENCE_PATH, ALTERNATIVE_PATH,
        MUTANT_BUILDER,
    ]
    missing = [str(path.relative_to(TASK_ROOT)) for path in required if not path.is_file()]
    if missing:
        raise AssertionError(f"missing required files: {missing}")
    text_files = [
        path
        for path in TASK_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and "__pycache__" not in path.parts
    ]
    invalid_text = []
    for path in text_files:
        payload = path.read_bytes()
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError:
            invalid_text.append(f"{path.relative_to(TASK_ROOT).as_posix()}:not-utf8")
        if b"\r" in payload:
            invalid_text.append(f"{path.relative_to(TASK_ROOT).as_posix()}:contains-CR")
    if invalid_text:
        raise AssertionError(f"task text files must be deterministic UTF-8/LF: {invalid_text[:10]}")
    for path in TASK_ROOT.rglob("*.py"):
        if "__pycache__" not in path.parts:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
    task_spec = (TASK_ROOT / "author" / "task_spec.yaml").read_text(encoding="utf-8")
    evaluation_spec = (TASK_ROOT / "private" / "evaluation_spec.yaml").read_text(encoding="utf-8")
    for token in (
        "schema_version: paper2ale.codex-task-spec/v1", "target_claim_leaf_id:",
        "task_mode: masked_workflow_completion", "specification_closure:",
        "provisional_label: structurally_hard_candidate", "path_base: task_root",
    ):
        if token not in task_spec:
            raise AssertionError(f"task spec missing {token}")
    provenance_paths = [
        "../../authoring/source_manifest.yaml",
        "../../authoring/evidence_map.yaml",
        "../../authoring/workflow_graph.yaml",
        "../../authoring/task_candidates.yaml",
    ]
    unresolved = [path for path in provenance_paths if not (TASK_ROOT / path).resolve().is_file()]
    if unresolved:
        raise AssertionError(f"task-root-relative provenance paths do not resolve: {unresolved}")
    for path in provenance_paths:
        if task_spec.count(path) != 1:
            raise AssertionError(f"task spec provenance path missing or duplicated: {path}")
    if "schema_version: paper2ale.codex-evaluation-spec/v1" not in evaluation_spec:
        raise AssertionError("evaluation spec schema missing")
    build_id = task_build_id(tree_snapshot(TASK_ROOT))
    if f"exact_task_build_id: {build_id}" not in task_spec:
        raise AssertionError(f"task spec exact build identity is stale; expected {build_id}")
    return {
        "required_file_count": len(required),
        "python_file_count": len(list(TASK_ROOT.rglob("*.py"))),
        "lf_utf8_text_file_count": len(text_files),
        "exact_task_build_id": build_id,
    }


def participant_audit() -> dict[str, Any]:
    forbidden = [
        "1907.13022", "arxiv.org", "efficient learning of quantum noise",
        "juqst", "flammia", "wallman", "harper", "rharper",
        "efficientlearningdataset", "query_ibmq",
    ]
    hits = []
    for path in PARTICIPANT.rglob("*"):
        relative = path.relative_to(PARTICIPANT).as_posix().lower()
        if any(token in relative for token in forbidden):
            hits.append(relative)
        if path.is_file():
            if path.is_symlink():
                raise AssertionError(f"participant package contains link: {relative}")
            if path.suffix.lower() in {".md", ".json", ".jsonl", ".py", ".txt", ".yaml", ".yml"}:
                text = path.read_text(encoding="utf-8", errors="strict").lower()
                for token in forbidden:
                    if token in text:
                        hits.append(f"{relative}:{token}")
    if hits:
        raise AssertionError(f"source identifiers leaked into participant package: {hits}")
    public_instance = CORE.load_instance(PARTICIPANT / "input")
    if public_instance["variable_count"] < 40:
        raise AssertionError("public n is too small to behaviorally prohibit global enumeration")
    dense_bytes = (1 << public_instance["variable_count"]) * 8
    if dense_bytes < 100_000_000_000:
        raise AssertionError("global table would not clearly violate resource contract")
    public_digest = tree_digest(PARTICIPANT)
    task_spec = (TASK_ROOT / "author" / "task_spec.yaml").read_text(encoding="utf-8")
    if f"participant-tree-sha256-{public_digest}" not in task_spec:
        raise AssertionError("task spec public build identity is stale")
    return {
        "participant_file_count": sum(path.is_file() for path in PARTICIPANT.rglob("*")),
        "forbidden_identifier_hits": 0,
        "public_variable_count": public_instance["variable_count"],
        "dense_float64_table_bytes": dense_bytes,
        "participant_tree_sha256": public_digest,
    }


def oracle_checks() -> dict[str, Any]:
    fixture_roots = [Path("participant/input"), Path("private/hidden_inputs"), Path("private/reference")]
    checked_snapshots = [tree_snapshot(TASK_ROOT / relative) for relative in fixture_roots]
    with tempfile.TemporaryDirectory(prefix="local-noise-oracle-generation-") as temporary:
        generation_root = Path(temporary)
        generated_tasks = [
            copy_task_for_generation(generation_root, "first-task", tuple(fixture_roots)),
            copy_task_for_generation(generation_root, "second-task", tuple(fixture_roots)),
        ]
        processes = []
        documents = []
        snapshots = []
        for index, (generated_task, hash_seed) in enumerate(zip(generated_tasks, ("17", "991"))):
            command = [sys.executable, "-B", str(generated_task / "author" / "oracle" / "generate.py")]
            cwd = generated_task / "scripts" if index == 0 else generation_root
            process = run_process(command, cwd, timeout=120.0, hash_seed=hash_seed)
            processes.append(process)
            documents.append(parse_json_process(process, f"oracle isolated run {index + 1}"))
            snapshots.append([tree_snapshot(generated_task / relative) for relative in fixture_roots])
        if documents[0] != documents[1] or snapshots[0] != snapshots[1]:
            raise AssertionError("isolated oracle generations are not byte-deterministic")
        if snapshots[0] != checked_snapshots:
            raise AssertionError("checked-in oracle/input fixtures differ from isolated regeneration")

        generated_task = generated_tasks[0]
        suite = CORE.load_json(generated_task / "private" / "hidden_inputs" / "suite_manifest.json")
        semantic_markers = {"ordinary", "anomaly", "ood", "chain", "branch", "fork", "sparse", "width"}
        leaked_ids = [
            case["instance_id"]
            for case in suite["cases"]
            if any(marker in case["instance_id"].lower() for marker in semantic_markers)
        ]
        if leaked_ids or any("category" in case or "topology" in case for case in suite["cases"]):
            raise AssertionError(f"hidden input metadata leaks case class through identifiers or fields: {leaked_ids}")
        cases = []
        for case in suite["cases"]:
            case_id = case["instance_id"]
            instance = CORE.load_instance(generated_task / "private" / "hidden_inputs" / "cases" / case_id)
            if "category" in instance or "topology" in instance:
                raise AssertionError("participant-visible hidden manifest contains private case class")
            outputs = CORE.load_submission_outputs(
                generated_task / "private" / "reference" / "oracle_outputs" / case_id, instance
            )
            truth = CORE.load_json(generated_task / "private" / "reference" / "truth" / f"{case_id}.json")
            cases.append(GRADE.score_case(instance, outputs, truth))
        aggregate = GRADE.aggregate(cases)
        if not aggregate["passed"] or abs(aggregate["total_score"] - 1.0) > 1.0e-15:
            raise AssertionError(f"oracle artifacts did not receive perfect score: {aggregate}")
        return {
            "generation_seconds": [process["runtime_seconds"] for process in processes],
            "hidden_case_count": len(cases),
            "oracle_score": aggregate["total_score"],
            "categories": sorted({case["category"] for case in cases}),
            "opaque_hidden_instance_ids": True,
            "isolated_regeneration_matches_checked_fixtures": True,
        }


def copy_solver_submission(source: Path, target: Path) -> None:
    target.mkdir(parents=True)
    shutil.copyfile(source, target / "solution.py")


def run_public_clean_room(source: Path, root: Path, hash_seed: str) -> tuple[Path, float]:
    submission = root / "submission"
    input_dir = root / "participant" / "input"
    output_dir = root / "output"
    copy_solver_submission(source, submission)
    shutil.copytree(PARTICIPANT, root / "participant")
    output_dir.mkdir()
    started = time.perf_counter()
    GRADE.execute_case(submission / "solution.py", input_dir, output_dir, hash_seed)
    runtime = time.perf_counter() - started
    instance = CORE.load_instance(input_dir)
    CORE.load_submission_outputs(output_dir, instance)
    validator = run_process(
        [sys.executable, "-B", str(VALIDATOR), "--input", str(input_dir), "--output", str(output_dir)],
        root,
        timeout=60.0,
    )
    result = parse_json_process(validator, "public validator")
    if not result.get("passed"):
        raise AssertionError(f"public validator rejected solver output: {result}")
    return output_dir, runtime


def grade_solver(source: Path, root: Path, hash_seed: str) -> tuple[dict[str, Any], float, str]:
    submission = root / "submission"
    copy_solver_submission(source, submission)
    process = run_process(
        [sys.executable, "-B", str(GRADER_PATH), "--submission", str(submission)],
        root,
        timeout=180.0,
        hash_seed=hash_seed,
    )
    result = parse_json_process(process, f"grader for {source.name}")
    return result, process["runtime_seconds"], process["stdout"]


def reference_checks() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="local-noise-reference-") as temporary:
        root = Path(temporary)
        output_a, public_a = run_public_clean_room(REFERENCE_PATH, root / "run-a", "101")
        output_b, public_b = run_public_clean_room(REFERENCE_PATH, root / "run-b", "997")
        if tree_snapshot(output_a) != tree_snapshot(output_b):
            raise AssertionError("reference solver public artifacts are nondeterministic")
        grade_a, runtime_a, stdout_a = grade_solver(REFERENCE_PATH, root / "grade-a", "37")
        grade_b, runtime_b, stdout_b = grade_solver(REFERENCE_PATH, root / "grade-b", "811")
        if grade_a != grade_b or stdout_a != stdout_b:
            raise AssertionError("private evaluator or clean-room reference result is nondeterministic")
        if not grade_a["passed"]:
            raise AssertionError(f"reference solver did not pass: {grade_a}")
        return {
            "public_runtime_seconds": [public_a, public_b],
            "grader_runtime_seconds": [runtime_a, runtime_b],
            "score": grade_a["total_score"],
            "metrics": grade_a["metrics"],
            "hidden_case_count": len(grade_a["case_results"]),
            "output_inventory": sorted(path.name for path in output_a.iterdir()),
        }


def alternative_checks() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="local-noise-alternative-") as temporary:
        root = Path(temporary)
        alternative_output, public_runtime = run_public_clean_room(ALTERNATIVE_PATH, root / "public", "313")
        reference_output, _ = run_public_clean_room(REFERENCE_PATH, root / "reference", "317")
        if (alternative_output / "model.json").read_bytes() == (reference_output / "model.json").read_bytes():
            raise AssertionError("alternative estimator is byte-identical to direct conditional estimator")
        result, grader_runtime, _ = grade_solver(ALTERNATIVE_PATH, root / "grade", "331")
        if not result["passed"]:
            raise AssertionError(f"alternative solver did not pass: {result}")
        return {
            "algorithm": "context-shrunk empirical-Bayes conditionals",
            "public_runtime_seconds": public_runtime,
            "grader_runtime_seconds": grader_runtime,
            "score": result["total_score"],
            "metrics": result["metrics"],
        }


def mutant_checks() -> dict[str, Any]:
    results = []
    with tempfile.TemporaryDirectory(prefix="local-noise-mutants-") as temporary:
        root = Path(temporary)
        generated_task = copy_task_for_generation(root, "generated-task")
        generated_builder = generated_task / "private" / "mutants" / "build_mutants.py"
        build = run_process(
            [sys.executable, "-B", str(generated_builder)], generated_task / "scripts", timeout=60.0
        )
        manifest = parse_json_process(build, "isolated mutant builder")
        generated_cases = generated_task / "private" / "mutants" / "cases"
        checked_cases = TASK_ROOT / "private" / "mutants" / "cases"
        if tree_snapshot(generated_cases) != tree_snapshot(checked_cases):
            raise AssertionError("checked-in mutant cases differ from isolated regeneration")
        for index, mutant in enumerate(manifest["mutants"]):
            source_dir = generated_task / "private" / "mutants" / mutant["path"]
            result, runtime, _ = grade_solver(source_dir / "solution.py", root / f"m-{index:02d}", str(401 + index))
            if result["passed"]:
                raise AssertionError(f"required mutant passed: {mutant['mutant_id']} score={result['total_score']}")
            if mutant["mutant_id"] == "single_topology_failure":
                if not result["hard_gates"]["passed"] or not result.get("case_floor_failures"):
                    raise AssertionError("single-topology mutant was not rejected by a per-case floor")
            if mutant["mutant_id"] == "validation_contamination":
                failures = result["hard_gates"].get("failures", [])
                if result["hard_gates"]["passed"] or not any("validation isolation" in item for item in failures):
                    raise AssertionError("validation-contamination mutant was not rejected by isolation enforcement")
            if mutant["mutant_id"] == "hash_nondeterminism":
                failures = result["hard_gates"].get("failures", [])
                if result["hard_gates"]["passed"] or not any("determinism" in item for item in failures):
                    raise AssertionError("hash-nondeterminism mutant was not rejected by repeated-input enforcement")
            results.append(
                {
                    "mutant_id": mutant["mutant_id"],
                    "category": mutant["category"],
                    "hard_gate_passed": result["hard_gates"]["passed"],
                    "score": result["total_score"],
                    "runtime_seconds": runtime,
                }
            )
    if len({item["category"] for item in results}) < 10:
        raise AssertionError("mutants do not span enough distinct scientific categories")
    return {
        "mutant_count": len(results),
        "all_rejected": True,
        "isolated_regeneration_matches_checked_fixtures": True,
        "results": results,
    }


def expect_parser_rejection(path: Path, instance: dict[str, Any], label: str) -> str:
    try:
        CORE.load_submission_outputs(path, instance)
    except CORE.SubmissionError as exc:
        return str(exc)
    raise AssertionError(f"parser accepted malformed output: {label}")


def robustness_checks() -> dict[str, Any]:
    instance = CORE.load_instance(PARTICIPANT / "input")
    oracle = TASK_ROOT / "private" / "reference" / "oracle_submission"
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="local-noise-robustness-") as temporary:
        root = Path(temporary)
        malformed = root / "malformed"
        shutil.copytree(oracle, malformed)
        (malformed / "model.json").write_text("{not json\n", encoding="utf-8")
        results["malformed"] = expect_parser_rejection(malformed, instance, "malformed")

        partial = root / "partial"
        shutil.copytree(oracle, partial)
        (partial / "audit.json").unlink()
        results["partial"] = expect_parser_rejection(partial, instance, "partial")

        nonfinite = root / "nonfinite"
        shutil.copytree(oracle, nonfinite)
        model_text = (nonfinite / "model.json").read_text(encoding="utf-8")
        model_text = model_text.replace('"probabilities": [', '"probabilities": [NaN,', 1)
        (nonfinite / "model.json").write_text(model_text, encoding="utf-8")
        results["nan"] = expect_parser_rejection(nonfinite, instance, "nan")

        oversized = root / "oversized"
        shutil.copytree(oracle, oversized)
        (oversized / "diagnostics.json").write_text("x" * 70_000, encoding="utf-8")
        results["oversized"] = expect_parser_rejection(oversized, instance, "oversized")

        stale = root / "stale"
        shutil.copytree(oracle, stale)
        stale_model = CORE.load_json(stale / "model.json")
        stale_model["instance_id"] = "stale"
        CORE.dump_json(stale / "model.json", stale_model)
        results["stale"] = expect_parser_rejection(stale, instance, "stale")

        link_status = "unsupported"
        linked = root / "linked"
        shutil.copytree(oracle, linked)
        target = root / "external-diagnostics.json"
        shutil.copyfile(linked / "diagnostics.json", target)
        (linked / "diagnostics.json").unlink()
        try:
            os.symlink(target, linked / "diagnostics.json")
            results["symlink"] = expect_parser_rejection(linked, instance, "symlink")
            link_status = "rejected"
        except (OSError, NotImplementedError):
            shutil.copyfile(target, linked / "diagnostics.json")

        hardlinked = root / "hardlinked"
        shutil.copytree(oracle, hardlinked)
        hard_target = root / "hard-target.json"
        shutil.copyfile(hardlinked / "diagnostics.json", hard_target)
        (hardlinked / "diagnostics.json").unlink()
        try:
            os.link(hard_target, hardlinked / "diagnostics.json")
            results["hardlink"] = expect_parser_rejection(hardlinked, instance, "hardlink")
            hardlink_status = "rejected"
        except (OSError, NotImplementedError):
            hardlink_status = "unsupported"

        source_cases = {
            "missing_source": {},
            "extra_source": {"solution.py": "pass\n", "extra.txt": "x\n"},
            "syntax_error": {"solution.py": "this is not python !!!\n"},
            "oversized_source": {"solution.py": "#" * 513_000},
        }
        source_results = {}
        for name, files in source_cases.items():
            directory = root / name
            directory.mkdir()
            for filename, content in files.items():
                (directory / filename).write_text(content, encoding="utf-8")
            result = GRADE.grade(directory)
            if result["hard_gates"]["passed"] or result["passed"] or result["total_score"] != 0.0:
                raise AssertionError(f"source robustness case passed: {name}")
            source_results[name] = result["hard_gates"]["failures"]

        root_link_status = "unsupported"
        root_link_target = root / "root-link-target"
        root_link_target.mkdir()
        (root_link_target / "solution.py").write_text("pass\n", encoding="utf-8")
        root_link = root / "root-link-submission"
        try:
            os.symlink(root_link_target, root_link, target_is_directory=True)
            try:
                GRADE.validate_source(root_link)
            except CORE.SubmissionError:
                pass
            else:
                raise AssertionError("private grader accepted a symlinked submission root")
            public_link_check = run_process(
                [sys.executable, "-B", str(VALIDATOR), "--submission", str(root_link)],
                root,
                timeout=60.0,
            )
            public_link_result = json.loads(public_link_check["stdout"])
            if public_link_check["returncode"] == 0 or public_link_result.get("passed"):
                raise AssertionError("public validator accepted a symlinked submission root")
            root_link_status = "rejected-by-private-and-public-validators"
        except (OSError, NotImplementedError):
            root_link_status = "unsupported"

        integrity_root = root / "integrity-snapshot-probe"
        integrity_source = integrity_root / "source"
        integrity_input = integrity_root / "input"
        integrity_case = integrity_root / "case"
        integrity_output = integrity_case / "output"
        integrity_source.mkdir(parents=True)
        integrity_input.mkdir()
        integrity_output.mkdir(parents=True)
        (integrity_source / "solution.py").write_text("pass\n", encoding="utf-8")
        (integrity_input / "manifest.json").write_text("{}\n", encoding="utf-8")
        (integrity_case / "protected.txt").write_text("before\n", encoding="utf-8")
        source_before = GRADE.protected_tree_snapshot(integrity_source)
        input_before = GRADE.protected_tree_snapshot(integrity_input)
        case_before = GRADE.protected_tree_snapshot(integrity_case, excluded=integrity_output)
        (integrity_source / "solution.py").write_text("changed\n", encoding="utf-8")
        (integrity_input / "manifest.json").write_text("changed\n", encoding="utf-8")
        (integrity_case / "protected.txt").write_text("changed\n", encoding="utf-8")
        if (
            source_before == GRADE.protected_tree_snapshot(integrity_source)
            or input_before == GRADE.protected_tree_snapshot(integrity_input)
            or case_before == GRADE.protected_tree_snapshot(integrity_case, excluded=integrity_output)
        ):
            raise AssertionError("protected-state snapshot failed to detect a mutation")

        probe_root = root / "security-probe"
        submission = probe_root / "submission"
        input_copy = probe_root / "input"
        output = probe_root / "output"
        submission.mkdir(parents=True)
        output.mkdir()
        shutil.copytree(PARTICIPANT / "input", input_copy)
        denied = probe_root / "denied-secret.txt"
        denied.write_text("secret", encoding="utf-8")
        denied_directory = probe_root / "denied-directory"
        denied_directory.mkdir()
        input_manifest_before = (input_copy / "manifest.json").read_bytes()
        probe_source = r'''import argparse, ctypes, os, socket, subprocess, sys
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("--input"); p.add_argument("--output"); a=p.parse_args()
denied = Path(a.input).parent / "denied-secret.txt"
denied_directory = Path(a.input).parent / "denied-directory"
outside = Path(a.output).parent
output = Path(a.output)
def must_deny(label, action):
    try: action()
    except PermissionError: return
    raise SystemExit("audit policy allowed " + label)
must_deny("outside read", lambda: denied.read_text())
must_deny("network", lambda: socket.socket())
must_deny("subprocess", lambda: subprocess.run([sys.executable, "-c", "pass"]))
must_deny("exec", lambda: os.execv(sys.executable, [sys.executable, "-c", "pass"]))
must_deny("ctypes", lambda: ctypes.CDLL("codex-security-probe-nonexistent-library"))
must_deny("outside write", lambda: (outside / "escape.txt").write_text("bad"))
must_deny("os.open write flags", lambda: os.close(os.open(Path(a.input) / "manifest.json", os.O_WRONLY | os.O_TRUNC)))
def replacement_path_helper(value): return str(Path(a.input))
must_deny("path helper code mutation", lambda: setattr(os.path.realpath, "__code__", replacement_path_helper.__code__))
saved_path_helpers = (
    os.path.realpath, os.path.abspath, os.path.commonpath, os.path.isabs,
    os.path.normpath, os.path.normcase, os.fsdecode, os.fspath, os.PathLike,
)
saved_open_flags = (os.O_WRONLY, os.O_RDWR, os.O_CREAT, os.O_TRUNC, os.O_APPEND)
try:
    os.path.realpath = lambda value: str(Path(a.input))
    os.path.abspath = lambda value: str(Path(a.input))
    os.path.commonpath = lambda values: str(Path(a.input))
    os.path.isabs = lambda value: True
    os.path.normpath = lambda value: str(Path(a.input))
    os.path.normcase = lambda value: str(Path(a.input))
    os.fsdecode = lambda value: str(Path(a.input))
    os.fspath = lambda value: str(Path(a.input))
    os.PathLike = str
    os.O_WRONLY = os.O_RDWR = os.O_CREAT = os.O_TRUNC = os.O_APPEND = 0
    must_deny("monkeypatched path read", lambda: denied.read_text())
    must_deny(
        "monkeypatched flag write",
        lambda: os.close(os.open(Path(a.input) / "manifest.json", saved_open_flags[0] | saved_open_flags[3])),
    )
finally:
    (
        os.path.realpath, os.path.abspath, os.path.commonpath, os.path.isabs,
        os.path.normpath, os.path.normcase, os.fsdecode, os.fspath, os.PathLike,
    ) = saved_path_helpers
    (os.O_WRONLY, os.O_RDWR, os.O_CREAT, os.O_TRUNC, os.O_APPEND) = saved_open_flags
must_deny("remove", lambda: os.remove(denied))
must_deny("unlink", lambda: os.unlink(denied))
must_deny("rename", lambda: os.rename(denied, output / "renamed.txt"))
must_deny("replace", lambda: os.replace(denied, output / "replaced.txt"))
must_deny("hard link", lambda: os.link(denied, output / "hard-link.txt"))
must_deny("symbolic link", lambda: os.symlink(denied, output / "symbolic-link.txt"))
must_deny("mkdir", lambda: os.mkdir(outside / "outside-directory"))
must_deny("rmdir", lambda: os.rmdir(denied_directory))
must_deny("truncate", lambda: os.truncate(denied, 0))
must_deny("chdir", lambda: os.chdir(output))
must_deny("default listdir", lambda: os.listdir())
must_deny("default scandir", lambda: os.scandir())
manifest_fd = os.open(Path(a.input) / "manifest.json", os.O_RDONLY)
try:
    must_deny("descriptor open", lambda: open(manifest_fd, "rb"))
finally:
    os.close(manifest_fd)
if os.open in os.supports_dir_fd and os.mkdir in os.supports_dir_fd:
    input_fd = os.open(a.input, os.O_RDONLY)
    try:
        must_deny("os.open dir_fd", lambda: os.close(os.open("manifest.json", os.O_WRONLY | os.O_TRUNC, dir_fd=input_fd)))
        must_deny("mkdir dir_fd", lambda: os.mkdir("dir-fd-created", dir_fd=input_fd))
        must_deny("descriptor listdir", lambda: os.listdir(input_fd))
    finally:
        os.close(input_fd)
scratch = output / "scratch.txt"
renamed = output / "scratch-renamed.txt"
scratch.write_text("abc")
os.replace(scratch, renamed)
os.truncate(renamed, 2)
os.remove(renamed)
inside_directory = output / "inside-directory"
os.mkdir(inside_directory)
os.rmdir(inside_directory)
(Path(a.output)/"probe.txt").write_text("all denied")
'''
        (submission / "solution.py").write_text(probe_source, encoding="utf-8")
        GRADE.execute_case(submission / "solution.py", input_copy, output, "59")
        escaped_paths = [
            probe_root / "escape.txt", probe_root / "outside-directory",
            output / "renamed.txt", output / "replaced.txt", output / "hard-link.txt",
            output / "symbolic-link.txt",
        ]
        if (
            (output / "probe.txt").read_text(encoding="utf-8") != "all denied"
            or denied.read_text(encoding="utf-8") != "secret"
            or not denied_directory.is_dir()
            or (input_copy / "manifest.json").read_bytes() != input_manifest_before
            or (input_copy / "dir-fd-created").exists()
            or any(path.exists() or path.is_symlink() for path in escaped_paths)
        ):
            raise AssertionError("security audit guard self-test failed")

        binary_probe = root / "binary-stdout-probe"
        binary_submission = binary_probe / "submission"
        binary_input = binary_probe / "input"
        binary_output = binary_probe / "output"
        binary_submission.mkdir(parents=True)
        binary_output.mkdir()
        shutil.copytree(PARTICIPANT / "input", binary_input)
        (binary_submission / "solution.py").write_text(
            "import sys\nsys.stdout.buffer.write(b'x' * 65537)\n",
            encoding="utf-8",
        )
        try:
            GRADE.execute_case(binary_submission / "solution.py", binary_input, binary_output, "61")
        except GRADE.core.SubmissionError:
            binary_stdout_status = "rejected"
        else:
            raise AssertionError("binary stdout bypassed the 65536-byte cap")
        results["security_probe"] = [
            "outside read/write", "os.open write flags", "immutable audit dependencies",
            "dir_fd mutation when supported",
            "network", "subprocess", "exec", "ctypes",
            "remove/unlink", "rename/replace", "link/symlink", "mkdir/rmdir", "truncate",
            "descriptor access", "chdir", "inside-output mutation allowed",
        ]
        results["source_cases"] = source_results
        results["symlink_status"] = link_status
        results["hardlink_status"] = hardlink_status
        results["submission_root_symlink_status"] = root_link_status
        results["post_run_integrity_snapshots"] = ["source tree", "input tree", "case root excluding output"]
        results["binary_stdout_cap"] = binary_stdout_status
    return results


def explicit_joint_probability(instance: dict[str, Any], model: dict[str, Any], assignment: dict[str, int]) -> float:
    value = 1.0
    for clique in instance["cliques"]:
        factor = model["_factor_by_id"][clique["clique_id"]]["_array"]
        index = CORE.assignment_index(clique["variables"], assignment)
        value *= float(factor[index])
    return value


def metamorphic_checks() -> dict[str, Any]:
    instance = CORE.load_instance(PARTICIPANT / "input")
    truth_doc = CORE.load_json(TASK_ROOT / "private" / "reference" / "public_truth.json")
    model = CORE.validate_model(truth_doc["true_model"], instance)
    observed: dict[str, Any] = {}
    rng = np.random.default_rng(83_017)

    partition_errors = []
    for _ in range(12):
        variables = list(rng.choice(instance["variable_ids"], size=5, replace=False))
        evidence = {variable: int(rng.integers(0, 2)) for variable in variables[:4]}
        split = variables[4]
        whole = CORE.evidence_probability(instance, model, evidence)
        parts = sum(CORE.evidence_probability(instance, model, {**evidence, split: bit}) for bit in (0, 1))
        partition_errors.append(abs(whole - parts))
    if max(partition_errors) > 5.0e-13:
        raise AssertionError("evidence partition relation failed")
    observed["evidence_partition_max_error"] = max(partition_errors)

    parity_errors = []
    explicit_errors = []
    for _ in range(10):
        variables = list(rng.choice(instance["variable_ids"], size=4, replace=False))
        even = CORE.parity_probability(instance, model, variables, 0)
        odd = CORE.parity_probability(instance, model, variables, 1)
        parity_errors.append(abs(even + odd - 1.0))
        explicit = 0.0
        for index in range(1 << len(variables)):
            if index.bit_count() % 2 == 0:
                evidence = {variable: (index >> position) & 1 for position, variable in enumerate(variables)}
                explicit += CORE.evidence_probability(instance, model, evidence)
        explicit_errors.append(abs(even - explicit))
    if max(parity_errors) > 3.0e-15 or max(explicit_errors) > 8.0e-13:
        raise AssertionError("signed parity message relation failed")
    observed["parity_complement_max_error"] = max(parity_errors)
    observed["signed_vs_explicit_parity_max_error"] = max(explicit_errors)

    marginals = CORE.clique_marginals(instance, model)
    marginal_errors = []
    for clique in instance["cliques"]:
        table = marginals[clique["clique_id"]]
        for index in range(table.size):
            evidence = {variable: (index >> position) & 1 for position, variable in enumerate(clique["variables"])}
            marginal_errors.append(abs(float(table[index]) - CORE.evidence_probability(instance, model, evidence)))
    if max(marginal_errors) > 7.0e-13:
        raise AssertionError("two-pass clique beliefs disagree with direct evidence DP")
    observed["two_pass_marginal_max_error"] = max(marginal_errors)

    with tempfile.TemporaryDirectory(prefix="local-noise-metamorphic-") as temporary:
        root = Path(temporary)
        reordered_input = root / "reordered"
        shutil.copytree(PARTICIPANT / "input", reordered_input)
        manifest = CORE.load_json(reordered_input / "manifest.json")
        manifest["cliques"] = list(reversed(manifest["cliques"]))
        CORE.dump_json(reordered_input / "manifest.json", manifest)
        counts = CORE.load_json(reordered_input / "clique_counts.json")
        counts["tables"] = list(reversed(counts["tables"]))
        CORE.dump_json(reordered_input / "clique_counts.json", counts)
        reordered_instance = CORE.load_instance(reordered_input)
        factor_by_id = {factor["clique_id"]: factor for factor in truth_doc["true_model"]["factors"]}
        reordered_model_doc = {
            "schema_version": "rooted-junction-model/v1",
            "instance_id": truth_doc["true_model"]["instance_id"],
            "root_clique_id": truth_doc["true_model"]["root_clique_id"],
            "factors": [factor_by_id[clique["clique_id"]] for clique in manifest["cliques"]],
        }
        reordered_model = CORE.validate_model(reordered_model_doc, reordered_instance)
        order_errors = []
        for query in instance["_queries"]:
            order_errors.append(
                abs(
                    CORE.evidence_probability(instance, model, query["assignment"])
                    - CORE.evidence_probability(reordered_instance, reordered_model, query["assignment"])
                )
            )
        if max(order_errors) > 2.0e-15:
            raise AssertionError("clique/count record reordering changed probabilities")
        observed["record_order_max_error"] = max(order_errors)

        base = root / "validation-base"
        shifted = root / "validation-shifted"
        shutil.copytree(PARTICIPANT / "input", base)
        shutil.copytree(PARTICIPANT / "input", shifted)
        rows = CORE.load_jsonl(shifted / "validation.jsonl")
        for row in rows:
            row["successes"] = row["shots"] - row["successes"]
        CORE.dump_jsonl(shifted / "validation.jsonl", rows)
        output_base = root / "out-base"
        output_shifted = root / "out-shifted"
        solve_base = run_process([sys.executable, "-B", str(REFERENCE_PATH), "--input", str(base), "--output", str(output_base)], root, 60.0)
        solve_shifted = run_process([sys.executable, "-B", str(REFERENCE_PATH), "--input", str(shifted), "--output", str(output_shifted)], root, 60.0)
        if solve_base["returncode"] != 0 or solve_shifted["returncode"] != 0:
            raise AssertionError("validation isolation solver run failed")
        if (output_base / "model.json").read_bytes() != (output_shifted / "model.json").read_bytes():
            raise AssertionError("validation data contaminated fitted model")
        if (output_base / "query_results.jsonl").read_bytes() != (output_shifted / "query_results.jsonl").read_bytes():
            raise AssertionError("validation data contaminated query predictions")
        if (output_base / "audit.json").read_bytes() == (output_shifted / "audit.json").read_bytes():
            raise AssertionError("validation change did not affect audit")
        observed["validation_isolation"] = "model and queries identical; audit changed"

        small_config = {
            "instance_id": "metamorphic_small", "seed": 991_117, "n": 8, "max_scope": 4,
            "shots": 3000, "topology": "branch", "query_count": 5,
            "validation_count": 5, "anomaly_count": 0, "category": "metamorphic",
        }
        public, truth, _ = GENERATOR.generate_instance(small_config)
        small_input = root / "small"
        GENERATOR.write_instance(small_input, public)
        small_instance = CORE.load_instance(small_input)
        small_model = CORE.validate_model(truth["true_model"], small_instance)
        all_variables = small_instance["variable_ids"]
        dense = np.zeros(1 << len(all_variables), dtype=np.float64)
        for index in range(dense.size):
            assignment = {variable: (index >> position) & 1 for position, variable in enumerate(all_variables)}
            dense[index] = explicit_joint_probability(small_instance, small_model, assignment)
        if abs(float(np.sum(dense)) - 1.0) > 7.0e-14:
            raise AssertionError("small explicit joint is not normalized")
        brute_errors = []
        for query in small_instance["_queries"]:
            expected = 0.0
            for index, value in enumerate(dense):
                if all(((index >> all_variables.index(variable)) & 1) == bit for variable, bit in query["assignment"].items()):
                    expected += float(value)
            actual = CORE.evidence_probability(small_instance, small_model, query["assignment"])
            brute_errors.append(abs(actual - expected))
        if max(brute_errors) > 7.0e-14:
            raise AssertionError("DP disagrees with small explicit enumeration")
        observed["small_dp_vs_bruteforce_max_error"] = max(brute_errors)

    return observed


def main() -> int:
    task_tree_before = tree_snapshot(TASK_ROOT)
    exact_task_build_id = task_build_id(task_tree_before)
    checks = Checks()
    started = time.perf_counter()
    checks.run("preflight-and-schema", preflight)
    checks.run("participant-paper-blindness-and-resource-scale", participant_audit)
    checks.run("oracle-generation-truth-and-determinism", oracle_checks)
    checks.run("clean-room-reference-solver-and-evaluator-determinism", reference_checks)
    checks.run("independent-alternative-solver", alternative_checks)
    checks.run("scientific-mutants", mutant_checks)
    checks.run("malformed-security-leakage-and-size-controls", robustness_checks)
    checks.run("metamorphic-and-invariant-tests", metamorphic_checks)
    def task_tree_idempotence() -> dict[str, Any]:
        task_tree_after = tree_snapshot(TASK_ROOT)
        changed = sorted(
            path
            for path in set(task_tree_before) | set(task_tree_after)
            if task_tree_before.get(path) != task_tree_after.get(path)
        )
        if changed:
            raise AssertionError(f"verification modified the task tree: {changed[:10]}")
        return {"unchanged_file_count": len(task_tree_after)}

    checks.run("task-tree-read-only-idempotence", task_tree_idempotence)
    failures = [record["check_id"] for record in checks.records if record["status"] != "pass"]
    payload = {
        "schema_version": "local-noise-verification/v1",
        "task_id": "local-junction-noise-model-v1",
        "exact_task_build_id": exact_task_build_id,
        "status": "pass" if not failures else "fail",
        "release_decision": "needs_agent_calibration" if not failures else "rejected_verification_failure",
        "provisional_difficulty": "structurally_hard_candidate",
        "checks": checks.records,
        "required_failures": failures,
        "total_runtime_seconds": time.perf_counter() - started,
    }
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
