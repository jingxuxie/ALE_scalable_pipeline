#!/usr/bin/env python3
"""Command-line entry point for the private metamorphic harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import warnings

from harness import run_metamorphic_suite


REPORT_SCHEMA = "spectral-scaling-metamorphic-report/v1"
FATAL_REPORT = {
    "schema_version": REPORT_SCHEMA,
    "passed": False,
    "fatal_error": "metamorphic_suite_exception",
}


def _render_report(report: object) -> str:
    return json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyzer", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--atol", type=float, default=5e-9)
    parser.add_argument("--rtol", type=float, default=5e-8)
    arguments = parser.parse_args()

    try:
        # NumPy and stdlib warnings include source filenames and line numbers on
        # stderr.  Convert every parent-process warning to an exception inside
        # the same redaction boundary so malformed private cases cannot leak
        # evaluator paths before the fatal envelope is emitted.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            if arguments.work is None:
                with tempfile.TemporaryDirectory(prefix="spectral-metamorphic-") as temporary:
                    report = run_metamorphic_suite(
                        arguments.analyzer,
                        arguments.case,
                        Path(temporary),
                        python_executable=arguments.python,
                        timeout_seconds=arguments.timeout,
                        atol=arguments.atol,
                        rtol=arguments.rtol,
                    )
            else:
                report = run_metamorphic_suite(
                    arguments.analyzer,
                    arguments.case,
                    arguments.work,
                    python_executable=arguments.python,
                    timeout_seconds=arguments.timeout,
                    atol=arguments.atol,
                    rtol=arguments.rtol,
                )
        rendered = _render_report(report)
        exit_code = 0 if report["passed"] is True else 1
    except Exception:
        # Exception text can contain hidden paths, analyzer stderr, packet IDs,
        # or other private evaluator state.  The CLI boundary intentionally
        # converts every suite/preflight failure to one stable, minimal report.
        report = dict(FATAL_REPORT)
        rendered = _render_report(report)
        exit_code = 1

    if arguments.report is not None:
        try:
            arguments.report.parent.mkdir(parents=True, exist_ok=True)
            arguments.report.write_text(rendered, encoding="utf-8")
        except Exception:
            # Preserve the no-traceback/no-private-leakage boundary even when
            # the optional report destination itself is unavailable.
            rendered = _render_report(FATAL_REPORT)
            exit_code = 1
    sys.stdout.write(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
