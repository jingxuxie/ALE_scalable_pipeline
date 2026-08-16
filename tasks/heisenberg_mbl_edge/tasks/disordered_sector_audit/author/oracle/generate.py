#!/usr/bin/env python3
"""Privileged oracle and deterministic reference generator."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def generate(task_root: Path, check: bool) -> dict[str, Any]:
    trusted = task_root / "private" / "trusted"
    instance_module = load_module("sector_instance_generator", trusted / "generate_instances.py")
    core = load_module("sector_oracle_core", trusted / "oracle_core.py")
    experiment_paths = instance_module.generate(task_root)
    reference_root = task_root / "private" / "reference"
    reference_root.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    for experiment_path in experiment_paths:
        experiment_dir = experiment_path.parent
        experiment = core.load_experiment(experiment_dir)
        result = core.solve_experiment(experiment)
        reference_path = reference_root / f"{experiment['experiment_id']}.json"
        core.dump_json(reference_path, result)
        effects = {
            row["claim_id"]: float(row["effect"])
            for row in result["conclusions"]
        }
        if check:
            nonpositive = [claim_id for claim_id, effect in effects.items() if not effect > 0.0]
            if nonpositive:
                raise RuntimeError(
                    f"generated finite ensemble does not preserve target signatures: {nonpositive}"
                )
            if not all(row["positive_effect"] for row in result["conclusions"]):
                raise RuntimeError("oracle conclusion flag contradicts positive effects")
        summaries.append(
            {
                "experiment_id": experiment["experiment_id"],
                "input_sha256": sha256(experiment_path),
                "reference_sha256": sha256(reference_path),
                "record_count": len(experiment["records"]),
                "state_row_count": len(result["state_rows"]),
                "effects": effects,
            }
        )
    summary = {
        "schema_version": "sector-audit-oracle-summary/v1",
        "experiments": summaries,
    }
    summary_path = reference_root / "oracle_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    summary = generate(args.task_root.resolve(), args.check)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
