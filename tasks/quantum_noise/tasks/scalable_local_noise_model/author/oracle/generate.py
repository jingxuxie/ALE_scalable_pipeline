#!/usr/bin/env python3
"""Privileged oracle: regenerate instances and exact latent-model artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path


TASK_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TASK_ROOT / "private" / "grader"))
sys.path.insert(0, str(TASK_ROOT / "private" / "generator"))
import core  # noqa: E402
import generate  # noqa: E402


def clean_model(model: dict) -> dict:
    result = {key: value for key, value in model.items() if not key.startswith("_")}
    result["factors"] = [
        {key: value for key, value in factor.items() if not key.startswith("_")}
        for factor in result["factors"]
    ]
    return result


def reset_directory(path: Path) -> None:
    resolved = path.resolve()
    if TASK_ROOT.resolve() not in resolved.parents:
        raise RuntimeError("refusing to reset a directory outside the task root")
    if path.exists():
        def writable_retry(function, target, _exc_info):
            os.chmod(target, stat.S_IWRITE)
            function(target)
        shutil.rmtree(path, onerror=writable_retry)
    path.mkdir(parents=True)


def generate_oracle(task_root: Path) -> dict:
    suite = generate.generate_all(task_root)
    reference_root = task_root / "private" / "reference"
    public_output = reference_root / "oracle_submission"
    reset_directory(public_output)
    public_instance = core.load_instance(task_root / "participant" / "input")
    public_truth = core.load_json(reference_root / "public_truth.json")
    core.write_outputs(public_output, public_instance, clean_model(public_truth["true_model"]))

    hidden_output_root = reference_root / "oracle_outputs"
    reset_directory(hidden_output_root)
    cases = []
    for case in suite["cases"]:
        case_id = case["instance_id"]
        instance = core.load_instance(task_root / "private" / "hidden_inputs" / "cases" / case_id)
        truth = core.load_json(reference_root / "truth" / f"{case_id}.json")
        core.write_outputs(hidden_output_root / case_id, instance, clean_model(truth["true_model"]))
        cases.append(
            {
                "instance_id": case_id,
                "category": truth["category"],
                "anomaly_count": len(truth["anomaly_ids"]),
                "private_query_count": len(truth["private_queries"]),
            }
        )
    summary = {
        "schema_version": "local-noise-oracle-summary/v1",
        "public_instance_id": public_instance["instance_id"],
        "hidden_cases": cases,
        "truth_definition": "latent normalized rooted junction-tree factors; validation shifts are private independent audit interventions",
    }
    core.dump_json(reference_root / "oracle_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, default=TASK_ROOT)
    args = parser.parse_args()
    summary = generate_oracle(args.task_root.resolve())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
