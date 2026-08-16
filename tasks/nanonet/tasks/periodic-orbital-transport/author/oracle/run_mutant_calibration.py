#!/usr/bin/env python3
"""Run all standalone mutants through the private evaluator deterministically."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence


TASK_ROOT = Path(__file__).resolve().parents[2]
EVALUATOR = TASK_ROOT / "private" / "grader" / "evaluate.py"
MUTANT_ROOT = TASK_ROOT / "private" / "mutants"
INPUT_ROOT = TASK_ROOT / "private" / "hidden_inputs"
REFERENCE_ROOT = TASK_ROOT / "private" / "reference"
DEFAULT_OUTPUT = TASK_ROOT / "author" / "verification_logs" / "mutant_results.json"
SCHEMA_VERSION = "periodic-orbital-transport-mutant-results/v1"


def _run_one(mutant: Path, temporary_root: Path) -> dict[str, Any]:
    report_path = temporary_root / f"{mutant.stem}.json"
    command = [
        sys.executable,
        str(EVALUATOR),
        "--submission",
        str(mutant),
        "--inputs",
        str(INPUT_ROOT),
        "--references",
        str(REFERENCE_ROOT),
        "--json-out",
        str(report_path),
    ]
    completed = subprocess.run(
        command,
        cwd=TASK_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=31 * 60,
        check=False,
    )
    if completed.returncode == 2:
        raise RuntimeError(
            f"evaluator error for {mutant.name}: {completed.stdout}{completed.stderr}"
        )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(
            f"unexpected evaluator exit {completed.returncode} for {mutant.name}: "
            f"{completed.stdout}{completed.stderr}"
        )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read evaluator report for {mutant.name}: {exc}") from exc
    if report.get("evaluator_error") is not None:
        raise RuntimeError(
            f"evaluator error for {mutant.name}: {report['evaluator_error']}"
        )
    if bool(report.get("passed")) != (completed.returncode == 0):
        raise RuntimeError(f"exit/result mismatch for {mutant.name}")
    return report


def _render() -> str:
    mutants = sorted(MUTANT_ROOT.glob("*.py"), key=lambda path: path.name)
    if not mutants:
        raise RuntimeError(f"no mutants found in {MUTANT_ROOT}")
    with tempfile.TemporaryDirectory(prefix="periodic-mutant-calibration-") as temporary:
        temporary_root = Path(temporary)
        results = [
            {"mutant": mutant.name, "evaluation": _run_one(mutant, temporary_root)}
            for mutant in mutants
        ]
    document = {
        "schema_version": SCHEMA_VERSION,
        "mutant_count": len(results),
        "all_rejected": all(not item["evaluation"]["passed"] for item in results),
        "results": results,
    }
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


def run(*, output: Path, check: bool) -> None:
    rendered = _render()
    if check:
        try:
            observed = output.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"cannot read mutant result summary: {exc}") from exc
        if observed != rendered:
            raise SystemExit("mutant result summary is stale")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="rerun and compare")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    run(output=options.output, check=options.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
