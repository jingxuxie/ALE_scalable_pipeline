"""Run the positive and negative checks for the concrete review examples."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
CASES = (
    (
        "generic-affine",
        ROOT / "generic-affine" / "reviewer_only" / "reference" / "grader.py",
        ROOT / "generic-affine" / "reviewer_only" / "examples" / "correct_submission.json",
        ROOT / "generic-affine" / "reviewer_only" / "examples" / "incorrect_submission.json",
    ),
    (
        "hnn-coupled-identification",
        ROOT / "hnn-coupled-identification" / "reviewer_only" / "reference" / "grader.py",
        ROOT / "hnn-coupled-identification" / "reviewer_only" / "examples" / "correct_submission.json",
        ROOT / "hnn-coupled-identification" / "reviewer_only" / "examples" / "incorrect_submission.json",
    ),
    (
        "hnn-variable-nbody",
        ROOT / "hnn-variable-nbody" / "reviewer_only" / "reference" / "grader.py",
        ROOT / "hnn-variable-nbody" / "reviewer_only" / "examples" / "correct_submission.json",
        ROOT / "hnn-variable-nbody" / "reviewer_only" / "examples" / "incorrect_submission.json",
    ),
    (
        "hnn-canonical-recovery",
        ROOT / "hnn-canonical-recovery" / "reviewer_only" / "reference" / "grader.py",
        ROOT / "hnn-canonical-recovery" / "reviewer_only" / "examples" / "correct_submission.json",
        ROOT / "hnn-canonical-recovery" / "reviewer_only" / "examples" / "incorrect_submission.json",
    ),
)


def grade(grader: Path, submission: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    process = subprocess.run(
        [sys.executable, str(grader), "--submission", str(submission), "--instance", "000"],
        capture_output=True,
        check=False,
        encoding="utf-8",
        timeout=30,
    )
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"grader {grader} did not return JSON; stderr={process.stderr!r}"
        ) from error
    return process, result


def main() -> int:
    failures: list[str] = []
    for name, grader, correct, incorrect in CASES:
        correct_process, correct_result = grade(grader, correct)
        incorrect_process, incorrect_result = grade(grader, incorrect)
        correct_metrics = correct_result.get("metrics")
        incorrect_metrics = incorrect_result.get("metrics")
        correct_ok = (
            correct_process.returncode == 0
            and correct_result.get("passed") is True
            and isinstance(correct_metrics, (dict, list))
            and bool(correct_metrics)
        )
        incorrect_ok = (
            incorrect_process.returncode != 0
            and incorrect_result.get("passed") is False
            and isinstance(incorrect_metrics, (dict, list))
            and bool(incorrect_metrics)
        )
        print(
            f"{name}: correct={'PASS' if correct_ok else 'FAIL'} "
            f"incorrect={'REJECTED' if incorrect_ok else 'ACCEPTED'}"
        )
        if not correct_ok:
            failures.append(f"{name}: known-correct submission did not pass")
        if not incorrect_ok:
            failures.append(f"{name}: deliberately incorrect submission was not rejected")
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
