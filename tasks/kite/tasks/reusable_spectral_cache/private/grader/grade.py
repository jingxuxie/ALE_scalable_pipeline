#!/usr/bin/env python3
"""Private, artifact-only evaluator for the reusable spectral cache task."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

from core import (
    SubmissionError,
    compare_diagnostics,
    compute_diagnostics,
    load_diagnostics,
    load_manifest,
    load_moments,
    load_queries,
    load_response,
    normalized_rmse,
    quality_score,
    response_values,
    validate_output_directory,
)


MOMENT_ABSOLUTE_TOLERANCE = 2.0e-11
MOMENT_RELATIVE_TOLERANCE = 4.0e-10
RESPONSE_ABSOLUTE_TOLERANCE = 4.0e-10
RESPONSE_RELATIVE_TOLERANCE = 4.0e-9


def failed_result(message: str) -> dict:
    return {
        "hard_gates": {"passed": False, "failures": [message]},
        "metrics": {},
        "total_score": 0.0,
        "passed": False,
    }


def grade(submission_dir: Path, participant_dir: Path) -> dict:
    try:
        validate_output_directory(submission_dir)
        manifest = load_manifest(participant_dir)
        public_queries = load_queries(participant_dir / "input" / manifest["public_queries_file"])
        moments = load_moments(submission_dir / "moments.npz", manifest)
        response = load_response(submission_dir / "public_response.csv", public_queries)
        diagnostics = load_diagnostics(submission_dir / "diagnostics.json", manifest)

        task_root = Path(__file__).resolve().parents[2]
        reference_dir = task_root / "private" / "reference"
        reference_moments = load_moments(reference_dir / "oracle_submission" / "moments.npz", manifest)
        hidden_queries = load_queries(task_root / "private" / "hidden_inputs" / "queries.csv")
        hidden_reference_rows = load_response(
            reference_dir / "hidden_response.csv",
            hidden_queries,
        )
    except SubmissionError as exc:
        return failed_result(str(exc))
    except Exception as exc:  # Defensive boundary: submissions must never produce a traceback.
        return failed_result(f"safe parser rejected artifact: {type(exc).__name__}: {exc}")

    tau = moments["tau"]
    reference_tau = reference_moments["tau"]
    moment_error = normalized_rmse(
        tau,
        reference_tau,
        MOMENT_ABSOLUTE_TOLERANCE,
        MOMENT_RELATIVE_TOLERANCE,
    )
    moment_score = quality_score(moment_error, excellent=1.0, minimum=35.0)

    try:
        hidden_actual = response_values(tau, manifest, hidden_queries)
        hidden_expected = np.asarray([row["value"] for row in hidden_reference_rows], dtype=np.complex128)
        hidden_error = normalized_rmse(
            hidden_actual,
            hidden_expected,
            RESPONSE_ABSOLUTE_TOLERANCE,
            RESPONSE_RELATIVE_TOLERANCE,
        )
        hidden_score = quality_score(hidden_error, excellent=1.0, minimum=35.0)

        public_actual = np.asarray([row["value"] for row in response], dtype=np.complex128)
        public_expected = response_values(tau, manifest, public_queries)
        public_error = normalized_rmse(
            public_actual,
            public_expected,
            RESPONSE_ABSOLUTE_TOLERANCE,
            RESPONSE_RELATIVE_TOLERANCE,
        )
        public_score = quality_score(public_error, excellent=1.0, minimum=35.0)

        expected_diagnostics = compute_diagnostics(
            participant_dir,
            manifest,
            tau,
            len(public_queries),
        )
        diagnostics_score, diagnostics_failures = compare_diagnostics(diagnostics, expected_diagnostics)
    except SubmissionError as exc:
        return failed_result(str(exc))
    except Exception as exc:
        return failed_result(f"numeric evaluation failed safely: {type(exc).__name__}: {exc}")

    weights = {
        "raw_moment_accuracy": 0.50,
        "hidden_contraction_accuracy": 0.35,
        "public_response_consistency": 0.10,
        "diagnostics_consistency": 0.05,
    }
    scores = {
        "raw_moment_accuracy": moment_score,
        "hidden_contraction_accuracy": hidden_score,
        "public_response_consistency": public_score,
        "diagnostics_consistency": diagnostics_score,
    }
    total = float(sum(weights[key] * scores[key] for key in weights))
    mandatory = (
        moment_score >= 0.93
        and hidden_score >= 0.93
        and public_score >= 0.93
        and diagnostics_score == 1.0
    )
    passed = bool(total >= 0.95 and mandatory)
    return {
        "hard_gates": {"passed": True, "failures": []},
        "metrics": {
            "raw_moment_accuracy": {
                "score": moment_score,
                "normalized_rmse": moment_error,
            },
            "hidden_contraction_accuracy": {
                "score": hidden_score,
                "normalized_rmse": hidden_error,
                "query_count": len(hidden_queries),
            },
            "public_response_consistency": {
                "score": public_score,
                "normalized_rmse": public_error,
                "query_count": len(public_queries),
            },
            "diagnostics_consistency": {
                "score": diagnostics_score,
                "failed_fields": diagnostics_failures,
            },
        },
        "total_score": total,
        "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--participant", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    submission = Path(os.path.abspath(args.submission))
    participant = Path(os.path.abspath(args.participant))
    result = grade(submission, participant)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
