from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


def strict_json(data):
    def reject(value):
        raise ValueError("non-finite JSON constant " + value)
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key " + repr(key))
            result[key] = value
        return result
    return json.loads(
        data.decode("utf-8"),
        parse_constant=reject,
        object_pairs_hook=unique_object,
    )


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def numeric_values(submitted, expected):
    if not isinstance(submitted, dict) or set(submitted) != {"predictions"}:
        raise ValueError("submission must contain only predictions")
    actual_rows = submitted["predictions"]
    expected_rows = expected["predictions"]
    if not isinstance(actual_rows, list) or len(actual_rows) != len(expected_rows):
        raise ValueError("prediction count mismatch")
    actual_by_id = {}
    for row in actual_rows:
        if not isinstance(row, dict) or set(row) != {"id", "values"} or not isinstance(row["id"], str):
            raise ValueError("invalid prediction row")
        if row["id"] in actual_by_id:
            raise ValueError("duplicate query ID")
        actual_by_id[row["id"]] = row["values"]
    expected_ids = [row["id"] for row in expected_rows]
    if set(actual_by_id) != set(expected_ids):
        raise ValueError("query ID mismatch")
    actual, target = [], []
    for row in expected_rows:
        values = actual_by_id[row["id"]]
        if not isinstance(values, list) or len(values) != len(row["values"]):
            raise ValueError("prediction shape mismatch")
        if not all(finite_number(value) for value in values):
            raise ValueError("predictions must be finite numbers")
        actual.extend(float(value) for value in values)
        target.extend(float(value) for value in row["values"])
    return actual, target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True)
    parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    evaluation = strict_json((root / "instances" / args.instance / "evaluation.json").read_bytes())
    submission = Path(args.submission)
    if submission.is_dir():
        submission = submission / evaluation["filename"]
    errors = []
    gate_results = {gate: True for gate in evaluation["gates"]}
    try:
        if submission.is_symlink() or not submission.is_file():
            raise ValueError("submission file is missing or is a symbolic link")
        size = submission.stat().st_size
        if size > evaluation["max_submission_bytes"]:
            gate_results["max_bytes"] = False
            raise ValueError("submission exceeds byte limit")
        submitted = strict_json(submission.read_bytes())
    except Exception as error:
        submitted = None
        gate_results = {gate: False for gate in evaluation["gates"]}
        errors.append(type(error).__name__ + ": " + str(error))

    metric_results = []
    if submitted is not None:
        primitive = evaluation["output_primitive"]
        expected = evaluation["expected"]
        try:
            if primitive == "numeric_predictions_json":
                actual, target = numeric_values(submitted, expected)
                differences = [left - right for left, right in zip(actual, target)]
                values = {
                    "numeric_rmse": math.sqrt(sum(value * value for value in differences) / len(differences)),
                    "numeric_max_abs": max(abs(value) for value in differences),
                }
            elif primitive == "table_rows_json":
                if not isinstance(submitted, dict) or set(submitted) != {"rows"} or not isinstance(submitted["rows"], list):
                    raise ValueError("submission must contain only a rows array")
                values = {"table_exact": 1.0 if submitted == expected else 0.0}
            elif primitive == "json_object":
                if not isinstance(submitted, dict) or set(submitted) != {"result"} or not isinstance(submitted["result"], dict):
                    raise ValueError("submission must contain only a result object")
                values = {"json_exact": 1.0 if submitted == expected else 0.0}
            else:
                raise ValueError("untrusted output primitive")
            for metric in evaluation["metrics"]:
                value = values[metric["primitive"]]
                passed = value <= metric["threshold"] if metric["direction"] == "lower_is_better" else value >= metric["threshold"]
                if metric["direction"] == "lower_is_better":
                    metric_score = 1.0 if passed else max(0.0, metric["threshold"] / value) if value > 0 else 1.0
                else:
                    metric_score = min(1.0, max(0.0, value))
                metric_results.append({"id": metric["id"], "primitive": metric["primitive"], "value": value, "threshold": metric["threshold"], "weight": metric["weight"], "score": metric_score, "passed": passed})
        except Exception as error:
            for gate in gate_results:
                if gate not in {"strict_json", "max_bytes"}:
                    gate_results[gate] = False
            errors.append(type(error).__name__ + ": " + str(error))

    total_weight = sum(metric["weight"] for metric in evaluation["metrics"])
    passed_weight = sum(metric["weight"] for metric in metric_results if metric["passed"])
    fraction = passed_weight / total_weight if total_weight else 0.0
    hard_gates_passed = all(gate_results.values())
    passed = hard_gates_passed and fraction >= evaluation["required_pass_fraction"]
    metric_scores = {metric["id"]: 0.0 for metric in evaluation["metrics"]}
    metric_scores.update({metric["id"]: metric["score"] for metric in metric_results})
    weighted_score = sum(metric["weight"] * metric["score"] for metric in metric_results) / total_weight if total_weight else 0.0
    score = weighted_score if hard_gates_passed else 0.0
    result = {
        "passed": passed,
        "hard_gates_passed": hard_gates_passed,
        "score": score,
        "instance": args.instance,
        "metric_pass_fraction": fraction,
        "metric_scores": metric_scores,
        "metrics": metric_results,
        "gates": gate_results,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
