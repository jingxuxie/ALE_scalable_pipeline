#!/usr/bin/env python3
"""Cross-platform release verification for the reusable spectral cache task."""

from __future__ import annotations

import csv
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
import zipfile
from pathlib import Path
from typing import Any, Callable

import numpy as np


sys.dont_write_bytecode = True
TASK_ROOT = Path(__file__).resolve().parents[1]
PARTICIPANT = TASK_ROOT / "participant"
GRADER = TASK_ROOT / "private" / "grader" / "grade.py"
ORACLE = TASK_ROOT / "author" / "oracle" / "generate.py"
REFERENCE_SOLVER = TASK_ROOT / "author" / "reference_solver" / "solve.py"
ALTERNATIVE_SOLVER = TASK_ROOT / "author" / "alternative_solver" / "solve.py"
MUTANT_BUILDER = TASK_ROOT / "private" / "mutants" / "build_mutants.py"
ORACLE_SUBMISSION = TASK_ROOT / "private" / "reference" / "oracle_submission"
OUTPUT_NAMES = {"moments.npz", "public_response.csv", "diagnostics.json"}


AUDIT_WRAPPER = r'''import json, os, runpy, socket, sys
import numpy

solver = os.path.abspath(sys.argv[1])
participant = os.path.abspath(sys.argv[2])
output = os.path.abspath(sys.argv[3])
denied = [os.path.normcase(os.path.abspath(item)) for item in json.loads(sys.argv[4])]

def under(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except (ValueError, OSError):
        return False

def audit(event, args):
    if event in {"socket.__new__", "socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
        raise PermissionError("clean-room audit denied " + event)
    if event in {"open", "os.listdir", "os.scandir"} and args:
        raw = args[0]
        if isinstance(raw, (str, bytes, os.PathLike)):
            path = os.path.normcase(os.path.abspath(os.fsdecode(raw)))
            if any(under(path, root) for root in denied):
                raise PermissionError("clean-room audit denied source path")

sys.addaudithook(audit)
sys.argv = [solver, "--participant", participant, "--output", output]
runpy.run_path(solver, run_name="__main__")
'''


AUDIT_PROBE = r'''import argparse, socket
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--participant")
parser.add_argument("--output")
args = parser.parse_args()
denied_file = Path(args.participant).parent / "denied_target.txt"
read_denied = False
network_denied = False
try:
    denied_file.read_bytes()
except PermissionError:
    read_denied = True
try:
    socket.socket()
except PermissionError:
    network_denied = True
if not (read_denied and network_denied):
    raise SystemExit("audit guard self-test failed")
print("audit guard denied source read and socket")
'''


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CORE = load_module("verify_spectral_core", TASK_ROOT / "private" / "grader" / "core.py")
ORACLE_MODULE = load_module("verify_spectral_oracle", ORACLE)


def clean_environment(hash_seed: str = "0") -> dict[str, str]:
    environment = dict(os.environ)
    for name in list(environment):
        if name.upper() in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}:
            environment.pop(name, None)
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


def run_process(
    command: list[str],
    cwd: Path,
    timeout: float = 180.0,
    hash_seed: str = "0",
) -> dict[str, Any]:
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
        shell=False,
        timeout=timeout,
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


def build_identity() -> str:
    digest = hashlib.sha256()
    included: list[Path] = []
    for subtree in (PARTICIPANT, TASK_ROOT / "private"):
        included.extend(path for path in subtree.rglob("*") if path.is_file())
    included.extend(
        [
            ORACLE,
            REFERENCE_SOLVER,
            ALTERNATIVE_SOLVER,
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


def tree_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def finite_tree(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and finite_tree(item) for key, item in value.items())
    if isinstance(value, list):
        return all(finite_tree(item) for item in value)
    return value is None or isinstance(value, (str, int, bool))


def parse_grade(process: dict[str, Any]) -> dict[str, Any]:
    if process["returncode"] != 0:
        raise AssertionError(
            f"grader process failed rc={process['returncode']}: {process['stderr'][-500:]}"
        )
    try:
        result = json.loads(process["stdout"])
    except json.JSONDecodeError as exc:
        raise AssertionError(f"grader did not emit one JSON document: {exc}") from exc
    if not finite_tree(result):
        raise AssertionError("grader emitted non-finite or unsupported values")
    if set(result) != {"hard_gates", "metrics", "total_score", "passed"}:
        raise AssertionError("grader result top-level schema mismatch")
    if not (0.0 <= float(result["total_score"]) <= 1.0) or type(result["passed"]) is not bool:
        raise AssertionError("grader score contract is malformed")
    return result


def grade_twice(submission: Path, participant: Path = PARTICIPANT) -> tuple[dict[str, Any], dict[str, Any]]:
    before_submission = tree_snapshot(submission) if submission.is_dir() and not submission.is_symlink() else {}
    before_participant = tree_snapshot(participant)
    command = [
        sys.executable,
        "-B",
        str(GRADER),
        "--participant",
        str(participant),
        "--submission",
        str(submission),
    ]
    first = run_process(command, Path(tempfile.gettempdir()), hash_seed="17")
    second = run_process(command, TASK_ROOT / "scripts", hash_seed="991")
    first_result = parse_grade(first)
    second_result = parse_grade(second)
    if first["returncode"] != second["returncode"]:
        raise AssertionError("grader process status is nondeterministic")
    if first["stdout"] != second["stdout"] or first["stderr"] != second["stderr"]:
        raise AssertionError("grader byte output is nondeterministic")
    if first_result != second_result:
        raise AssertionError("grader parsed result is nondeterministic")
    if before_participant != tree_snapshot(participant):
        raise AssertionError("grader mutated participant inputs")
    if before_submission and before_submission != tree_snapshot(submission):
        raise AssertionError("grader mutated the submission")
    return first_result, {"first_seconds": first["runtime_seconds"], "second_seconds": second["runtime_seconds"]}


def compare_submissions(left: Path, right: Path) -> None:
    if {path.name for path in left.iterdir()} != OUTPUT_NAMES:
        raise AssertionError("left solver output inventory mismatch")
    if {path.name for path in right.iterdir()} != OUTPUT_NAMES:
        raise AssertionError("right solver output inventory mismatch")
    with np.load(left / "moments.npz", allow_pickle=False) as first, np.load(
        right / "moments.npz", allow_pickle=False
    ) as second:
        if first.files != second.files:
            raise AssertionError("repeated solver NPZ keys differ")
        for key in first.files:
            if not np.array_equal(first[key], second[key]):
                raise AssertionError(f"repeated solver array differs: {key}")
    for name in ("public_response.csv", "diagnostics.json"):
        if (left / name).read_bytes() != (right / name).read_bytes():
            raise AssertionError(f"repeated solver text differs: {name}")


class Checks:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def run(self, check_id: str, function: Callable[[], Any], required: bool = True) -> Any:
        started = time.perf_counter()
        try:
            details = function()
            record = {
                "check_id": check_id,
                "required": required,
                "status": "pass",
                "runtime_seconds": time.perf_counter() - started,
                "details": details,
            }
            self.records.append(record)
            return details
        except Exception as exc:
            self.records.append(
                {
                    "check_id": check_id,
                    "required": required,
                    "status": "fail",
                    "runtime_seconds": time.perf_counter() - started,
                    "details": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(limit=6),
                }
            )
            return None


def preflight() -> dict[str, Any]:
    required = [
        PARTICIPANT / "TASK.md",
        PARTICIPANT / "input" / "manifest.json",
        PARTICIPANT / "input" / "public_queries.csv",
        PARTICIPANT / "software" / "validate_submission.py",
        TASK_ROOT / "private" / "evaluation_spec.yaml",
        TASK_ROOT / "private" / "hidden_inputs" / "queries.csv",
        TASK_ROOT / "private" / "reference" / "hidden_response.csv",
        ORACLE_SUBMISSION / "moments.npz",
        ORACLE_SUBMISSION / "public_response.csv",
        ORACLE_SUBMISSION / "diagnostics.json",
        GRADER,
        TASK_ROOT / "private" / "grader" / "core.py",
        MUTANT_BUILDER,
        TASK_ROOT / "author" / "task_spec.yaml",
        TASK_ROOT / "author" / "spec_review.md",
        TASK_ROOT / "author" / "verification_report.md",
        ORACLE,
        REFERENCE_SOLVER,
        ALTERNATIVE_SOLVER,
        Path(__file__).resolve(),
    ]
    missing = [str(path.relative_to(TASK_ROOT)) for path in required if not path.is_file()]
    if missing:
        raise AssertionError(f"missing package files: {missing}")
    task_spec = (TASK_ROOT / "author" / "task_spec.yaml").read_text(encoding="utf-8")
    evaluation_spec = (TASK_ROOT / "private" / "evaluation_spec.yaml").read_text(encoding="utf-8")
    if "task_id: reusable-chebyshev-spectral-cache-v1" not in task_spec:
        raise AssertionError("task spec ID missing")
    if "task_id: reusable-chebyshev-spectral-cache-v1" not in evaluation_spec:
        raise AssertionError("evaluation spec ID mismatch")
    if "status: pass" not in task_spec or "material_ambiguities: []" not in task_spec:
        raise AssertionError("paper-blind review is not closed")
    if "Status: PASS" not in (TASK_ROOT / "author" / "spec_review.md").read_text(encoding="utf-8"):
        raise AssertionError("paper-blind review record is not PASS")
    caches = [
        path.relative_to(TASK_ROOT).as_posix()
        for path in TASK_ROOT.rglob("*")
        if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
    ]
    if caches:
        raise AssertionError(f"generated Python caches contaminate package: {caches}")
    temporary = [path.name for path in TASK_ROOT.iterdir() if path.name.startswith(".tmp_")]
    if temporary:
        raise AssertionError(f"temporary verification directories remain: {temporary}")
    return {"required_file_count": len(required), "python": sys.version.split()[0], "numpy": np.__version__}


def participant_audit() -> dict[str, Any]:
    forbidden_patterns = [
        "1910.05194",
        "quantum-kite",
        "arxiv.org",
        "zenodo.org",
        "high-performance accurate modelling",
        "tools/src/dos.cpp",
        "eq. 2.17",
        "authoring/sources",
    ]
    files = [path for path in PARTICIPANT.rglob("*") if path.is_file()]
    seen_casefold: set[str] = set()
    total_bytes = 0
    for path in PARTICIPANT.rglob("*"):
        relative = path.relative_to(PARTICIPANT).as_posix()
        folded = relative.casefold()
        if folded in seen_casefold:
            raise AssertionError(f"case-fold path collision: {relative}")
        seen_casefold.add(folded)
        info = path.lstat()
        reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(info.st_mode) or reparse:
            raise AssertionError(f"participant contains link/reparse point: {relative}")
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise AssertionError(f"participant contains special file: {relative}")
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink > 1:
                raise AssertionError(f"participant contains hard-linked file: {relative}")
            total_bytes += info.st_size
    for path in files:
        if path.suffix.lower() not in {".md", ".json", ".csv", ".py"}:
            raise AssertionError(f"unexpected participant file type: {path.name}")
        text = path.read_text(encoding="utf-8").casefold()
        for token in forbidden_patterns:
            if token.casefold() in text:
                raise AssertionError(f"source identifier leaked in {path.name}: {token}")
        if "kite" in path.name.casefold():
            raise AssertionError(f"source acronym leaked in participant path: {path.name}")
    participant_hashes = {sha256(path) for path in files}
    protected_files = [
        path
        for base in (TASK_ROOT / "private" / "reference", TASK_ROOT / "author")
        for path in base.rglob("*")
        if path.is_file() and path.suffix not in {".pyc"}
    ]
    collisions = [path.relative_to(TASK_ROOT).as_posix() for path in protected_files if sha256(path) in participant_hashes]
    if collisions:
        raise AssertionError(f"participant duplicates protected artifact bytes: {collisions}")
    manifest = CORE.load_manifest(PARTICIPANT)
    for system in manifest["systems"]:
        for label, relative in (
            ("onsite", system["onsite_file"]),
            ("edges", system["edges_file"]),
            ("probes", system["probes_file"]),
        ):
            if sha256(PARTICIPANT / "input" / relative) != system["file_sha256"][label]:
                raise AssertionError(f"public input hash mismatch: {system['system_id']}:{label}")
    return {"file_count": len(files), "total_bytes": total_bytes, "source_identifier_leaks": 0}


def oracle_checks() -> dict[str, Any]:
    command = [sys.executable, "-B", str(ORACLE), "--task-root", str(TASK_ROOT), "--check"]
    before = tree_snapshot(TASK_ROOT)
    first = run_process(command, Path(tempfile.gettempdir()), timeout=240.0, hash_seed="101")
    second = run_process(command, TASK_ROOT / "scripts", timeout=240.0, hash_seed="303")
    if first["returncode"] or second["returncode"]:
        raise AssertionError(f"oracle check failed: {first['stderr']} {second['stderr']}")
    first_json, second_json = json.loads(first["stdout"]), json.loads(second["stdout"])
    if first_json != second_json or first_json.get("status") != "pass":
        raise AssertionError("oracle generation is nondeterministic")
    if before != tree_snapshot(TASK_ROOT):
        raise AssertionError("read-only oracle check mutated the package")
    return {
        "runs": 2,
        "runtime_seconds": [first["runtime_seconds"], second["runtime_seconds"]],
        "scaled_max_abs_eigenvalue": [
            item["scaled_max_abs_eigenvalue"] for item in first_json["summary"]["system_details"]
        ],
    }


def audit_guard_selftest() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="spectral-audit-selftest-") as temporary:
        root = Path(temporary)
        room = root / "room"
        denied = root / "denied"
        room.mkdir()
        denied.mkdir()
        (denied / "denied_target.txt").write_text("secret", encoding="utf-8")
        wrapper = room / "wrapper.py"
        probe = room / "probe.py"
        wrapper.write_text(AUDIT_WRAPPER, encoding="utf-8")
        probe.write_text(AUDIT_PROBE, encoding="utf-8")
        participant_link = denied / "participant"
        participant_link.mkdir()
        command = [
            sys.executable,
            "-B",
            "-I",
            str(wrapper),
            str(probe),
            str(participant_link),
            str(room / "output"),
            json.dumps([str(denied)]),
        ]
        result = run_process(command, room)
        if result["returncode"] != 0 or "denied source read and socket" not in result["stdout"]:
            raise AssertionError(f"audit guard self-test failed: {result}")
        return {"source_read_denied": True, "socket_denied": True}


def clean_room_runs() -> dict[str, Any]:
    solver_source = REFERENCE_SOLVER.read_text(encoding="utf-8").casefold()
    for token in ("private", "authoring", "1910.05194", "quantum-kite", "socket", "requests"):
        if token in solver_source:
            raise AssertionError(f"reference solver contains prohibited dependency token: {token}")
    with tempfile.TemporaryDirectory(prefix="spectral-clean-room-") as temporary:
        root = Path(temporary)
        outputs: list[Path] = []
        runtimes: list[float] = []
        grade_results: list[dict[str, Any]] = []
        for run_index in range(2):
            room = root / f"run_{run_index}"
            participant = room / "participant"
            solver_dir = room / "solver"
            output = room / "output"
            shutil.copytree(PARTICIPANT, participant)
            solver_dir.mkdir(parents=True)
            shutil.copy2(REFERENCE_SOLVER, solver_dir / "solve.py")
            wrapper = room / "audit_wrapper.py"
            wrapper.write_text(AUDIT_WRAPPER, encoding="utf-8")
            before = tree_snapshot(participant)
            command = [
                sys.executable,
                "-B",
                "-I",
                str(wrapper),
                str(solver_dir / "solve.py"),
                str(participant),
                str(output),
                json.dumps([str(TASK_ROOT), str(TASK_ROOT.parent.parent / "authoring")]),
            ]
            process = run_process(command, room, timeout=180.0, hash_seed=str(701 + run_index))
            if process["returncode"] != 0:
                raise AssertionError(f"clean-room solver failed: {process['stderr'][-1000:]}")
            if before != tree_snapshot(participant):
                raise AssertionError("clean-room solver mutated public inputs")
            if not output.is_dir() or {entry.name for entry in output.iterdir()} != OUTPUT_NAMES:
                raise AssertionError("clean-room output inventory mismatch")
            result, grade_runtime = grade_twice(output, participant)
            if not result["passed"] or not result["hard_gates"]["passed"]:
                raise AssertionError(f"clean-room solution failed evaluator: {result}")
            outputs.append(output)
            runtimes.append(process["runtime_seconds"])
            grade_results.append({"result": result, "runtime": grade_runtime})
        compare_submissions(outputs[0], outputs[1])
        return {
            "runs": 2,
            "solver_runtime_seconds": runtimes,
            "scores": [item["result"]["total_score"] for item in grade_results],
            "metrics": grade_results[0]["result"]["metrics"],
            "hidden_access_audit": "audit hook denied source task paths, sockets, and subprocesses",
        }


def oracle_grade() -> dict[str, Any]:
    result, runtimes = grade_twice(ORACLE_SUBMISSION)
    if not result["passed"] or result["total_score"] != 1.0:
        raise AssertionError(f"oracle submission did not receive a perfect score: {result}")
    return {"score": result["total_score"], "metrics": result["metrics"], "grader_runtime": runtimes}


def alternative_run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="spectral-alternative-") as temporary:
        output = Path(temporary) / "output"
        command = [
            sys.executable,
            "-B",
            str(ALTERNATIVE_SOLVER),
            "--participant",
            str(PARTICIPANT),
            "--output",
            str(output),
        ]
        process = run_process(command, Path(temporary), timeout=180.0, hash_seed="1231")
        if process["returncode"] != 0:
            raise AssertionError(f"alternative solver failed: {process['stderr']}")
        result, grade_runtime = grade_twice(output)
        if not result["passed"]:
            raise AssertionError(f"alternative solver failed evaluator: {result}")
        return {
            "solver_runtime_seconds": process["runtime_seconds"],
            "score": result["total_score"],
            "metrics": result["metrics"],
            "grader_runtime": grade_runtime,
        }


def mutant_runs() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="spectral-mutants-") as temporary:
        output_root = Path(temporary) / "cases"
        command = [
            sys.executable,
            "-B",
            str(MUTANT_BUILDER),
            "--task-root",
            str(TASK_ROOT),
            "--output-root",
            str(output_root),
        ]
        build = run_process(command, Path(temporary), timeout=180.0, hash_seed="1777")
        if build["returncode"] != 0:
            raise AssertionError(f"mutant builder failed: {build['stderr']}")
        manifest = json.loads((output_root / "mutant_manifest.json").read_text(encoding="utf-8"))
        expected_ids = [item["mutant_id"] for item in manifest["mutants"]]
        if len(expected_ids) < 6:
            raise AssertionError("mutant suite is too small")
        results: dict[str, Any] = {}
        for mutant_id in expected_ids:
            result, _ = grade_twice(output_root / mutant_id)
            if not result["hard_gates"]["passed"]:
                raise AssertionError(f"scientific mutant failed structurally instead of behaviorally: {mutant_id}")
            if result["passed"]:
                raise AssertionError(f"scientific mutant passed: {mutant_id} -> {result}")
            results[mutant_id] = {
                "score": result["total_score"],
                "metric_scores": {
                    key: value["score"] for key, value in result["metrics"].items()
                },
            }
        return {
            "count": len(results),
            "build_runtime_seconds": build["runtime_seconds"],
            "results": results,
        }


def save_npz_arrays(path: Path, arrays: dict[str, np.ndarray], compressed: bool = False) -> None:
    writer = np.savez_compressed if compressed else np.savez
    writer(path, **arrays)


def base_arrays() -> dict[str, np.ndarray]:
    with np.load(ORACLE_SUBMISSION / "moments.npz", allow_pickle=False) as archive:
        return {key: np.array(archive[key], copy=True) for key in archive.files}


def robustness_runs() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="spectral-robustness-") as temporary:
        root = Path(temporary)
        cases: dict[str, Path] = {}

        def fresh(name: str) -> Path:
            target = root / name
            shutil.copytree(ORACLE_SUBMISSION, target)
            cases[name] = target
            return target

        missing = fresh("missing_artifact")
        (missing / "diagnostics.json").unlink()

        corrupt = fresh("corrupt_npz")
        (corrupt / "moments.npz").write_bytes(b"not an npz")

        object_case = fresh("object_array_npz")
        arrays = base_arrays()
        arrays["tau_real"] = arrays["tau_real"].astype(object)
        save_npz_arrays(object_case / "moments.npz", arrays)

        wrong_shape = fresh("wrong_shape")
        arrays = base_arrays()
        arrays["tau_real"] = np.transpose(arrays["tau_real"], (0, 2, 1))
        save_npz_arrays(wrong_shape / "moments.npz", arrays)

        nan_case = fresh("nan_moment")
        arrays = base_arrays()
        arrays["tau_real"][0, 0, 17] = np.nan
        save_npz_arrays(nan_case / "moments.npz", arrays)

        oversize = fresh("oversized_artifact")
        with (oversize / "moments.npz").open("ab") as handle:
            handle.write(b"x" * 2_000_001)

        bomb = fresh("expanded_npz_bomb")
        arrays = base_arrays()
        arrays["tau_real"] = np.zeros(600_000, dtype=np.float64)
        save_npz_arrays(bomb / "moments.npz", arrays, compressed=True)

        partial = fresh("partial_csv")
        lines = (partial / "public_response.csv").read_text(encoding="utf-8").splitlines()
        (partial / "public_response.csv").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

        duplicate_json = fresh("duplicate_json_key")
        (duplicate_json / "diagnostics.json").write_text(
            '{"schema_version":"spectral-diagnostics/v1","schema_version":"duplicate"}\n',
            encoding="utf-8",
        )

        nonfinite_json = fresh("nonfinite_json")
        diagnostics = json.loads((nonfinite_json / "diagnostics.json").read_text(encoding="utf-8"))
        text = json.dumps(diagnostics).replace('"tau0_max_abs_error": 0.0', '"tau0_max_abs_error": NaN', 1)
        if "NaN" not in text:
            text = text.replace('"tau0_max_abs_error": 0', '"tau0_max_abs_error": NaN', 1)
        (nonfinite_json / "diagnostics.json").write_text(text, encoding="utf-8")

        extra = fresh("extra_file")
        (extra / "unexpected.txt").write_text("unexpected", encoding="utf-8")

        stale = fresh("stale_ids")
        arrays = base_arrays()
        arrays["system_ids"] = arrays["system_ids"][[1, 0, 2]]
        save_npz_arrays(stale / "moments.npz", arrays)

        directory_artifact = fresh("directory_artifact")
        (directory_artifact / "diagnostics.json").unlink()
        (directory_artifact / "diagnostics.json").mkdir()

        hardlink = fresh("hardlink_artifact")
        (hardlink / "diagnostics.json").unlink()
        hardlink_source = root / "hardlink_source.json"
        shutil.copy2(ORACLE_SUBMISSION / "diagnostics.json", hardlink_source)
        os.link(hardlink_source, hardlink / "diagnostics.json")

        symlink_status: dict[str, str] = {}
        try:
            leaf_link = fresh("symlink_artifact")
            (leaf_link / "moments.npz").unlink()
            os.symlink(ORACLE_SUBMISSION / "moments.npz", leaf_link / "moments.npz")
            symlink_status["leaf"] = "created_and_tested"
        except (OSError, NotImplementedError) as error:
            cases.pop("symlink_artifact", None)
            symlink_status["leaf"] = f"platform_unavailable: {error}"

        root_target = root / "symlink_root_target"
        shutil.copytree(ORACLE_SUBMISSION, root_target)
        root_link = root / "symlink_root"
        try:
            os.symlink(root_target, root_link, target_is_directory=True)
            cases["symlink_root"] = root_link
            symlink_status["submission_root"] = "created_and_tested"
        except (OSError, NotImplementedError) as error:
            symlink_status["submission_root"] = f"platform_unavailable: {error}"

        results: dict[str, Any] = {}
        for name, case in cases.items():
            result, _ = grade_twice(case)
            if result["passed"] or result["total_score"] != 0.0 or result["hard_gates"]["passed"]:
                raise AssertionError(f"robustness case did not fail a hard gate: {name}: {result}")
            results[name] = result["hard_gates"]["failures"]

        positive = root / "near_tolerance_positive"
        shutil.copytree(ORACLE_SUBMISSION, positive)
        manifest = CORE.load_manifest(PARTICIPANT)
        moments = CORE.load_moments(positive / "moments.npz", manifest)
        tau = moments["tau"]
        tolerance = np.maximum(2.0e-11, 4.0e-10 * np.abs(tau))
        signs = np.asarray([1.0, -1.0, 1.0, -1.0])[None, :, None]
        perturbed = tau + 0.20 * tolerance * signs
        CORE.write_moments(positive / "moments.npz", manifest, perturbed)
        queries = CORE.load_queries(PARTICIPANT / "input" / manifest["public_queries_file"])
        CORE.write_response(
            positive / "public_response.csv",
            queries,
            CORE.response_values(perturbed, manifest, queries),
        )
        CORE.write_diagnostics(
            positive / "diagnostics.json",
            CORE.compute_diagnostics(PARTICIPANT, manifest, perturbed, len(queries)),
        )
        positive_result, _ = grade_twice(positive)
        if not positive_result["passed"] or positive_result["total_score"] != 1.0:
            raise AssertionError(f"near-tolerance non-byte-equal control failed: {positive_result}")
        if np.array_equal(tau, perturbed):
            raise AssertionError("near-tolerance control was accidentally byte-identical")

        bytes_case = root / "valid_byte_identifiers"
        shutil.copytree(ORACLE_SUBMISSION, bytes_case)
        arrays = base_arrays()
        arrays["schema_version"] = np.asarray(b"spectral-moments/v1")
        arrays["system_ids"] = arrays["system_ids"].astype("S")
        save_npz_arrays(bytes_case / "moments.npz", arrays)
        bytes_result, _ = grade_twice(bytes_case)
        if not bytes_result["passed"]:
            raise AssertionError(f"publicly allowed byte identifiers were rejected: {bytes_result}")

        compressed = root / "valid_high_compression"
        shutil.copytree(ORACLE_SUBMISSION, compressed)
        arrays = base_arrays()
        arrays["tau_imag"] = np.zeros_like(arrays["tau_imag"])
        save_npz_arrays(compressed / "moments.npz", arrays, compressed=True)
        compressed_tau = arrays["tau_real"] + 1j * arrays["tau_imag"]
        queries = CORE.load_queries(PARTICIPANT / "input" / manifest["public_queries_file"])
        CORE.write_response(
            compressed / "public_response.csv",
            queries,
            CORE.response_values(compressed_tau, manifest, queries),
        )
        CORE.write_diagnostics(
            compressed / "diagnostics.json",
            CORE.compute_diagnostics(PARTICIPANT, manifest, compressed_tau, len(queries)),
        )
        with zipfile.ZipFile(compressed / "moments.npz") as archive:
            ratios = [
                member.file_size / member.compress_size
                for member in archive.infolist()
                if member.compress_size
            ]
        if max(ratios) <= 200.0:
            raise AssertionError("high-compression positive control did not exercise the old limit")
        compressed_result, _ = grade_twice(compressed)
        if not compressed_result["passed"]:
            raise AssertionError(f"valid compressed NPZ was rejected: {compressed_result}")
        return {
            "hard_gate_case_count": len(results),
            "hard_gate_results": results,
            "near_tolerance_control_score": positive_result["total_score"],
            "byte_identifier_control_score": bytes_result["total_score"],
            "high_compression_control": {
                "max_member_ratio": max(ratios),
                "score": compressed_result["total_score"],
            },
            "symlink_tests": symlink_status,
        }


def dense_moments(hamiltonian: np.ndarray, probes: np.ndarray, lower: float, upper: float, count: int):
    n = hamiltonian.shape[0]
    a = 0.5 * (upper - lower)
    b = 0.5 * (upper + lower)
    scaled = (hamiltonian - b * np.eye(n)) / a
    vectors = probes.T.copy()
    previous = vectors.copy()
    tau = np.empty((probes.shape[0], count), dtype=np.complex128)
    tau[:, 0] = np.einsum("pn,np->p", probes.conjugate(), previous) / n
    if count == 1:
        return tau
    current = scaled @ vectors
    tau[:, 1] = np.einsum("pn,np->p", probes.conjugate(), current) / n
    for order in range(2, count):
        following = 2.0 * (scaled @ current) - previous
        tau[:, order] = np.einsum("pn,np->p", probes.conjugate(), following) / n
        previous, current = current, following
    return tau


def independent_contract(
    tau: np.ndarray, prefix: int, energy: float, eta: float, lower: float, upper: float, sigma: int = 1
):
    a = 0.5 * (upper - lower)
    b = 0.5 * (upper + lower)
    z = complex((energy - b) / a, sigma * eta / a)
    candidate = complex(np.sqrt(z * z - 1.0 + 0.0j))
    root = candidate if abs(z - candidate) < abs(z + candidate) else -candidate
    q = 1.0 / (z + root)
    power = q
    total = tau[0]
    for order in range(1, prefix):
        total += 2.0 * power * tau[order]
        power *= q
    return total / (a * root), root, q


def metamorphic_tests() -> dict[str, Any]:
    manifest = CORE.load_manifest(PARTICIPANT)
    system = manifest["systems"][0]
    onsite, edges, probes = CORE.load_system(PARTICIPANT, system)
    hamiltonian = CORE.dense_hamiltonian(onsite, edges)
    lower = float(system["spectral_lower"])
    upper = float(system["spectral_upper"])
    a = 0.5 * (upper - lower)
    b = 0.5 * (upper + lower)
    tau = dense_moments(hamiltonian, probes, lower, upper, int(manifest["moment_count"]))
    tau_mean = np.mean(tau, axis=0)
    observed: dict[str, Any] = {}

    if np.max(np.abs(tau[:, 0] - 1.0)) > 2.0e-14:
        raise AssertionError("tau0 invariant failed")
    if np.max(np.abs(tau.imag)) > 2.0e-13 or np.max(np.abs(tau)) > 1.0 + 2.0e-12:
        raise AssertionError("Hermitian moment bound failed")
    observed["moment_invariants"] = {
        "max_tau0_error": float(np.max(np.abs(tau[:, 0] - 1.0))),
        "max_imaginary": float(np.max(np.abs(tau.imag))),
        "max_absolute": float(np.max(np.abs(tau))),
    }

    rng = np.random.default_rng(88_101)
    permutation = rng.permutation(hamiltonian.shape[0])
    permuted_h = hamiltonian[np.ix_(permutation, permutation)]
    permuted_probes = probes[:, permutation]
    permutation_tau = dense_moments(permuted_h, permuted_probes, lower, upper, 64)
    permutation_error = float(np.max(np.abs(permutation_tau - tau[:, :64])))
    if permutation_error > 2.0e-13:
        raise AssertionError("basis permutation invariance failed")
    observed["basis_permutation_max_error"] = permutation_error

    phase = np.exp(0.713j)
    phase_tau = dense_moments(hamiltonian, probes * phase, lower, upper, 32)
    phase_error = float(np.max(np.abs(phase_tau - tau[:, :32])))
    if phase_error > 2.0e-13:
        raise AssertionError("global probe phase invariance failed")
    observed["global_probe_phase_max_error"] = phase_error

    alpha, beta = 1.73, -0.41
    transformed_h = alpha * hamiltonian + beta * np.eye(hamiltonian.shape[0])
    transformed_lower, transformed_upper = alpha * lower + beta, alpha * upper + beta
    transformed_tau = dense_moments(transformed_h, probes, transformed_lower, transformed_upper, 64)
    affine_tau_error = float(np.max(np.abs(transformed_tau - tau[:, :64])))
    energy, eta = b + 0.23 * a, 0.071 * a
    response, _, _ = independent_contract(tau_mean, 64, energy, eta, lower, upper, 1)
    transformed_response, _, _ = independent_contract(
        np.mean(transformed_tau, axis=0),
        64,
        alpha * energy + beta,
        alpha * eta,
        transformed_lower,
        transformed_upper,
        1,
    )
    affine_response_error = abs(transformed_response - response / alpha)
    if affine_tau_error > 3.0e-13 or affine_response_error > 3.0e-13:
        raise AssertionError("positive affine covariance failed")
    observed["affine_covariance"] = {
        "moment_max_error": affine_tau_error,
        "response_abs_error": float(affine_response_error),
    }

    retarded, _, _ = independent_contract(tau_mean.real, 128, energy, eta, lower, upper, 1)
    advanced, _, _ = independent_contract(tau_mean.real, 128, energy, eta, lower, upper, -1)
    conjugacy_error = abs(advanced - retarded.conjugate())
    density = -retarded.imag / math.pi
    density_identity_error = abs(density - ((advanced - retarded) / (2j * math.pi)).real)
    if conjugacy_error > 2.0e-13 or density_identity_error > 2.0e-14 or density < 0.0:
        raise AssertionError("retarded/advanced or DOS identity failed")
    observed["causality"] = {
        "conjugacy_error": float(conjugacy_error),
        "density_identity_error": float(density_identity_error),
        "density": float(density),
    }

    prefix = 57
    suffix_mutated = tau_mean.copy()
    suffix_mutated[prefix:] += rng.normal(size=suffix_mutated.size - prefix)
    prefix_value, _, _ = independent_contract(tau_mean, prefix, energy, eta, lower, upper, 1)
    suffix_value, _, _ = independent_contract(suffix_mutated, prefix, energy, eta, lower, upper, 1)
    suffix_error = abs(prefix_value - suffix_value)
    if suffix_error != 0.0:
        raise AssertionError("prefix/suffix independence failed")
    observed["prefix_suffix_independence_error"] = float(suffix_error)

    direct_prefix = 73
    finite, root, q = independent_contract(tau_mean, direct_prefix, energy, eta, lower, upper, 1)
    z_physical = complex(energy, eta)
    direct_values = []
    matrix = z_physical * np.eye(hamiltonian.shape[0]) - hamiltonian
    for probe in probes:
        direct_values.append(np.vdot(probe, np.linalg.solve(matrix, probe)) / hamiltonian.shape[0])
    direct = complex(np.mean(direct_values))
    tail_bound = 2.0 * abs(q) ** direct_prefix / (a * abs(root) * (1.0 - abs(q)))
    direct_error = abs(finite - direct)
    if direct_error > tail_bound * (1.0 + 2.0e-11) + 2.0e-13:
        raise AssertionError("finite contraction exceeds analytic tail bound")
    observed["direct_resolvent"] = {
        "absolute_error": float(direct_error),
        "tail_bound": float(tail_bound),
    }

    energies = np.linspace(b - 20.0 * a, b + 20.0 * a, 1601)
    densities = np.empty(energies.size)
    integration_eta = 0.10 * a
    for index, grid_energy in enumerate(energies):
        value, _, _ = independent_contract(
            tau_mean, int(manifest["moment_count"]), float(grid_energy), integration_eta, lower, upper, 1
        )
        densities[index] = -value.imag / math.pi
    mass = float(np.trapezoid(densities, energies))
    if abs(mass - tau_mean[0].real) > 0.012:
        raise AssertionError(f"integrated broadened DOS mass failed: {mass}")

    eigenvalues, eigenvectors = np.linalg.eigh(hamiltonian)
    weights = np.mean(np.abs(eigenvectors.conjugate().T @ probes.T) ** 2, axis=1) / hamiltonian.shape[0]
    grid = np.linspace(b - 0.70 * a, b + 0.70 * a, 61)
    convergence_eta = 0.06 * a
    short_errors = []
    long_errors = []
    for grid_energy in grid:
        exact = np.sum(weights / (grid_energy + 1j * convergence_eta - eigenvalues))
        short, _, _ = independent_contract(tau_mean, 32, grid_energy, convergence_eta, lower, upper, 1)
        long, _, _ = independent_contract(tau_mean, 192, grid_energy, convergence_eta, lower, upper, 1)
        short_errors.append(abs(short - exact) ** 2)
        long_errors.append(abs(long - exact) ** 2)
    short_l2 = float(math.sqrt(sum(short_errors) / len(short_errors)))
    long_l2 = float(math.sqrt(sum(long_errors) / len(long_errors)))
    if not long_l2 < short_l2:
        raise AssertionError("global prefix convergence failed")
    observed["dos_normalization_and_global_convergence"] = {
        "integrated_mass": mass,
        "expected_mass": float(tau_mean[0].real),
        "short_prefix_l2": short_l2,
        "long_prefix_l2": long_l2,
    }
    return observed


def metamorphic_determinism() -> dict[str, Any]:
    first = metamorphic_tests()
    second = metamorphic_tests()
    if first != second:
        raise AssertionError("metamorphic test output is nondeterministic")
    return first


def main() -> int:
    checks = Checks()
    started = time.perf_counter()
    checks.run("preflight", preflight)
    checks.run("participant-leakage-and-input-audit", participant_audit)
    checks.run("oracle-generation-and-determinism", oracle_checks)
    checks.run("oracle-grading", oracle_grade)
    checks.run("clean-room-audit-guard-selftest", audit_guard_selftest)
    checks.run("clean-room-reference-and-determinism", clean_room_runs)
    checks.run("alternative-valid-implementation", alternative_run)
    checks.run("scientific-mutants", mutant_runs)
    checks.run("parser-security-and-tolerance-controls", robustness_runs)
    checks.run("metamorphic-oracle-and-determinism", metamorphic_determinism)
    required_failures = [
        record["check_id"]
        for record in checks.records
        if record["required"] and record["status"] != "pass"
    ]
    payload = {
        "schema_version": "spectral-task-verification/v1",
        "task_id": "reusable-chebyshev-spectral-cache-v1",
        "status": "pass" if not required_failures else "fail",
        "release_decision": "needs_agent_calibration" if not required_failures else "rejected_verification_failure",
        "provisional_difficulty": "structurally_hard_candidate",
        "build_identity": build_identity(),
        "checks": checks.records,
        "required_failures": required_failures,
        "total_runtime_seconds": time.perf_counter() - started,
    }
    results_path = TASK_ROOT / "author" / "verification_results.json"
    results_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0 if not required_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
