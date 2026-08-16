#!/usr/bin/env python3
"""Guarded behavioral evaluator for submitted solution.py programs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from core import (
    MAX_RESULT_BYTES,
    SubmissionError,
    load_json_strict,
    score_result,
    validate_result,
    validate_submission,
)


def failed(message: str) -> dict[str, Any]:
    return {
        "hard_gates": {"passed": False, "failures": [message]},
        "metrics": {},
        "total_score": 0.0,
        "passed": False,
    }


def clean_environment(stage_root: Path) -> dict[str, str]:
    allowed = {
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "LANG",
        "LC_ALL",
    }
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in allowed
    }
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": "0",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "TEMP": str(stage_root),
            "TMP": str(stage_root),
            "TMPDIR": str(stage_root),
        }
    )
    return environment


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(file_digest(path)))
    return digest.hexdigest()


def terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5.0,
                    shell=False,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                process.kill()
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except OSError:
                process.kill()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass


def tail(path: Path, limit: int = 800) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read(limit).decode("utf-8", errors="replace").replace("\n", " ")
    except OSError:
        return ""


def execute_solution(
    solution: Path,
    experiment_dir: Path,
    task_root: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    runner = task_root / "private" / "grader" / "sandbox_runner.py"
    with tempfile.TemporaryDirectory(prefix="sector-audit-run-") as temporary:
        root = Path(temporary)
        source_dir = root / "source"
        copied_experiment = root / "input"
        output_dir = root / "output"
        source_dir.mkdir()
        output_dir.mkdir()
        copied_solution = source_dir / "solution.py"
        copied_runner = root / "guard.py"
        output = output_dir / "result.json"
        shutil.copy2(solution, copied_solution)
        shutil.copytree(experiment_dir, copied_experiment)
        shutil.copy2(runner, copied_runner)
        source_before = file_digest(copied_solution)
        input_before = tree_digest(copied_experiment)
        stdout_path = root / "stdout.bin"
        stderr_path = root / "stderr.bin"
        console_limit = 1_000_000
        deadline = time.monotonic() + timeout_seconds
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(copied_runner),
                    str(copied_solution),
                    str(copied_experiment),
                    str(output),
                    str(root),
                ],
                cwd=root,
                env=clean_environment(root),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                shell=False,
                start_new_session=(os.name != "nt"),
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
            )
            while process.poll() is None:
                if time.monotonic() > deadline:
                    terminate(process)
                    raise SubmissionError("solution exceeded the per-experiment time limit")
                stdout_size = stdout_path.stat().st_size
                stderr_size = stderr_path.stat().st_size
                if stdout_size + stderr_size > console_limit:
                    terminate(process)
                    raise SubmissionError("solution emitted excessive console output")
                try:
                    result_size = output.stat().st_size
                except OSError:
                    result_size = 0
                if result_size > MAX_RESULT_BYTES:
                    terminate(process)
                    raise SubmissionError("result exceeded the size limit during execution")
                time.sleep(0.02)
            returncode = process.wait()
        # A fast child can exit between polling iterations. Handles are closed
        # here, so this mandatory post-exit check observes fully flushed files.
        if stdout_path.stat().st_size + stderr_path.stat().st_size > console_limit:
            raise SubmissionError("solution emitted excessive console output")
        if returncode != 0:
            detail = tail(stderr_path, 800)
            raise SubmissionError(f"solution failed under the evaluation guard: {detail}")
        if file_digest(copied_solution) != source_before or tree_digest(copied_experiment) != input_before:
            raise SubmissionError("solution modified staged source or input")
        if [path.name for path in output_dir.iterdir()] != ["result.json"]:
            raise SubmissionError("solution must create exactly output/result.json")
        return load_json_strict(output, MAX_RESULT_BYTES)


def grade(submission: Path, participant: Path, timeout_seconds: float = 300.0) -> dict[str, Any]:
    try:
        solution = validate_submission(submission)
        if not (participant / "TASK.md").is_file():
            raise SubmissionError("participant package is incomplete")
        task_root = Path(__file__).resolve().parents[2]
        hidden_root = task_root / "private" / "hidden_inputs"
        experiment_dirs = sorted(path for path in hidden_root.iterdir() if path.is_dir())
        if not experiment_dirs:
            raise RuntimeError("private hidden suite is empty")
        per_experiment: list[tuple[str, dict[str, Any]]] = []
        for experiment_dir in experiment_dirs:
            experiment_data = load_json_strict(experiment_dir / "experiment.json", 2_000_000)
            experiment_id = experiment_data.get("experiment_id")
            if not isinstance(experiment_id, str):
                raise RuntimeError("hidden experiment is malformed")
            reference = load_json_strict(
                task_root / "private" / "reference" / f"{experiment_id}.json",
                MAX_RESULT_BYTES,
            )
            actual = execute_solution(solution, experiment_dir, task_root, timeout_seconds)
            parsed = validate_result(actual, reference)
            per_experiment.append((experiment_id, score_result(parsed, reference)))
    except SubmissionError as exc:
        return failed(str(exc))
    except Exception as exc:
        return failed(f"evaluator failed safely: {type(exc).__name__}: {exc}")

    metric_names = (
        "spectral_packet",
        "entanglement_participation",
        "magnetization",
        "realization_aggregation",
        "evidence_consistency",
    )
    metrics: dict[str, Any] = {}
    scores: dict[str, float] = {}
    for name in metric_names:
        case_scores = [float(item[name]["score"]) for _experiment, item in per_experiment]
        score = sum(case_scores) / len(case_scores)
        error = sum(item[name]["normalized_rmse"] for _experiment, item in per_experiment) / len(per_experiment)
        scores[name] = float(score)
        metrics[name] = {
            "score": float(score),
            "mean_normalized_rmse": float(error),
            "minimum_experiment_score": min(case_scores),
            "experiment_count": len(per_experiment),
        }
        if name == "spectral_packet":
            metrics[name]["mean_index_fraction"] = float(
                sum(item[name]["index_fraction"] for _experiment, item in per_experiment)
                / len(per_experiment)
            )
    weights = {
        "spectral_packet": 0.25,
        "entanglement_participation": 0.30,
        "magnetization": 0.15,
        "realization_aggregation": 0.20,
        "evidence_consistency": 0.10,
    }
    total = float(sum(weights[name] * scores[name] for name in metric_names))
    mandatory = all(
        item["spectral_packet"]["score"] >= 0.92
        and item["entanglement_participation"]["score"] >= 0.92
        and item["magnetization"]["score"] >= 0.92
        and item["realization_aggregation"]["score"] >= 0.92
        and item["evidence_consistency"]["score"] == 1.0
        for _experiment, item in per_experiment
    )
    return {
        "hard_gates": {"passed": True, "failures": []},
        "metrics": metrics,
        "total_score": total,
        "passed": bool(total >= 0.95 and mandatory),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--participant", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = grade(args.submission.resolve(), args.participant.resolve())
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
