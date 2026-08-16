#!/usr/bin/env python3
"""Generate retired public and private hidden experiment manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA = "sector-audit-experiment/v1"
ROOT_ENTROPY = 0x5ECA_70A1_2026


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def query(query_id: str, epsilon: float, packet_size: int, start: int, size: int) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "epsilon": epsilon,
        "packet_size": packet_size,
        "subsystem_start": start,
        "subsystem_size": size,
    }


def make_experiment(
    experiment_id: str,
    rng: np.random.Generator,
    length: int,
    n_up: int,
    realization_count: int,
    weak_amplitude: float,
    strong_amplitude: float,
    query_specs: list[tuple[str, float, int, int]],
    exchange: float = 1.0,
    packet_cycle: tuple[int, ...] = (5, 7, 9, 6, 8),
    condition_ids: tuple[str, str] = ("weak", "strong"),
    record_prefixes: tuple[str, str] = ("weak", "strong"),
    comparison_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if len(packet_cycle) < len(query_specs) or len(set(packet_cycle)) < 2:
        raise ValueError("packet cycle must support query-varying packet sizes")
    if len(condition_ids) != 2 or len(record_prefixes) != 2:
        raise ValueError("exactly two condition IDs and record prefixes are required")
    if comparison_ids is None:
        comparison_ids = tuple(
            f"weak-vs-strong-{query_id}"
            for query_id, _epsilon, _start, _size in query_specs
        )
    if len(comparison_ids) != len(query_specs):
        raise ValueError("one comparison ID is required per query")
    records: list[dict[str, Any]] = []
    regimes = (
        (condition_ids[0], record_prefixes[0], weak_amplitude),
        (condition_ids[1], record_prefixes[1], strong_amplitude),
    )
    for condition_id, record_prefix, amplitude in regimes:
        for realization in range(realization_count):
            # Amplitudes are dimensionless h/J values. Scaling both J and h
            # preserves the intended finite-regime signature while ensuring
            # that hidden nonunit exchange values are behaviorally exercised.
            fields = rng.uniform(-amplitude * exchange, amplitude * exchange, size=length)
            records.append(
                {
                    "record_id": f"{record_prefix}-r{realization:02d}",
                    "condition_id": condition_id,
                    "L": length,
                    "n_up": n_up,
                    "exchange": exchange,
                    "fields": [float(value) for value in fields],
                    "queries": [
                        query(
                            query_id,
                            epsilon,
                            packet_cycle[(realization + query_index) % len(packet_cycle)],
                            start,
                            size,
                        )
                        for query_index, (query_id, epsilon, start, size) in enumerate(query_specs)
                    ],
                }
            )
    # Static review instances deliberately vary record order too. Canonical
    # participant outputs must therefore follow the disclosed identifier sort,
    # not assume weak records precede strong records.
    records = [records[int(index)] for index in rng.permutation(len(records))]
    comparisons = [
        {
            "comparison_id": comparison_id,
            "weak_condition": condition_ids[0],
            "strong_condition": condition_ids[1],
            "query_id": query_id,
        }
        for comparison_id, (query_id, _epsilon, _start, _size) in zip(
            comparison_ids, query_specs
        )
    ]
    return {
        "schema_version": SCHEMA,
        "experiment_id": experiment_id,
        "records": records,
        "comparisons": comparisons,
    }


def generate(task_root: Path) -> list[Path]:
    streams = np.random.SeedSequence(ROOT_ENTROPY).spawn(4)
    definitions = [
        (
            task_root / "participant" / "input" / "retired_experiment" / "experiment.json",
            make_experiment(
                "retired-demo-01",
                np.random.default_rng(streams[0]),
                length=8,
                n_up=4,
                realization_count=5,
                weak_amplitude=0.9,
                strong_amplitude=6.5,
                query_specs=[("center", 0.50, 0, 4), ("offset", 0.68, 2, 3)],
            ),
        ),
        (
            task_root / "private" / "hidden_inputs" / "hidden_alpha" / "experiment.json",
            make_experiment(
                "hidden-alpha-01",
                np.random.default_rng(streams[1]),
                length=9,
                n_up=4,
                realization_count=5,
                weak_amplitude=0.85,
                strong_amplitude=7.0,
                query_specs=[("q-a31", 0.44, 7, 4), ("q-a74", 0.27, 1, 5)],
                condition_ids=("c-a17", "c-a92"),
                record_prefixes=("ra17", "ra92"),
                comparison_ids=("cmp-a08", "cmp-a63"),
            ),
        ),
        (
            task_root / "private" / "hidden_inputs" / "hidden_beta" / "experiment.json",
            make_experiment(
                "hidden-beta-01",
                np.random.default_rng(streams[2]),
                length=10,
                n_up=5,
                realization_count=4,
                weak_amplitude=1.05,
                strong_amplitude=6.8,
                query_specs=[("q-b19", 0.53, 3, 5), ("q-b67", 0.72, 8, 4)],
                exchange=1.35,
                condition_ids=("c-b24", "c-b81"),
                record_prefixes=("rb24", "rb81"),
                comparison_ids=("cmp-b14", "cmp-b76"),
            ),
        ),
        (
            task_root / "private" / "hidden_inputs" / "hidden_gamma" / "experiment.json",
            make_experiment(
                "hidden-gamma-01",
                np.random.default_rng(streams[3]),
                length=12,
                n_up=5,
                realization_count=5,
                weak_amplitude=0.78,
                strong_amplitude=7.2,
                query_specs=[
                    ("q-g13", 0.48, 4, 6),
                    ("q-g58", 0.78, 10, 5),
                    ("q-g91", 0.24, 1, 4),
                ],
                exchange=0.8,
                packet_cycle=(2, 15, 9, 6, 8),
                condition_ids=("c-g13", "c-g86"),
                record_prefixes=("rg13", "rg86"),
                comparison_ids=("cmp-g05", "cmp-g47", "cmp-g88"),
            ),
        ),
    ]
    outputs: list[Path] = []
    for path, experiment in definitions:
        write_json(path, experiment)
        outputs.append(path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    args = parser.parse_args()
    outputs = generate(args.task_root.resolve())
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
