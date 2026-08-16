#!/usr/bin/env python3
"""Clean-room solver using sparse matrix-vector Chebyshev recurrences."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


RESPONSE_COLUMNS = [
    "query_id",
    "system_id",
    "prefix",
    "kind",
    "energy",
    "eta",
    "value_real",
    "value_imag",
]


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_system(participant: Path, system: dict, probe_count: int):
    n = int(system["dimension"])
    onsite = np.empty(n, dtype=np.float64)
    for row in csv_rows(participant / "input" / system["onsite_file"]):
        onsite[int(row["index"])] = float(row["value"])
    edge_rows = csv_rows(participant / "input" / system["edges_file"])
    edge_i = np.asarray([int(row["i"]) for row in edge_rows], dtype=np.int64)
    edge_j = np.asarray([int(row["j"]) for row in edge_rows], dtype=np.int64)
    edge_v = np.asarray(
        [complex(float(row["value_real"]), float(row["value_imag"])) for row in edge_rows],
        dtype=np.complex128,
    )
    probes = np.empty((probe_count, n), dtype=np.complex128)
    for row in csv_rows(participant / "input" / system["probes_file"]):
        probes[int(row["probe_id"]), int(row["index"])] = complex(
            float(row["value_real"]), float(row["value_imag"])
        )
    return onsite, edge_i, edge_j, edge_v, probes


def scaled_matvec(
    vector: np.ndarray,
    onsite: np.ndarray,
    edge_i: np.ndarray,
    edge_j: np.ndarray,
    edge_v: np.ndarray,
    a: float,
    b: float,
) -> np.ndarray:
    result = ((onsite - b) / a).astype(np.complex128) * vector
    np.add.at(result, edge_i, (edge_v / a) * vector[edge_j])
    np.add.at(result, edge_j, (edge_v.conjugate() / a) * vector[edge_i])
    return result


def sparse_moments(participant: Path, manifest: dict) -> np.ndarray:
    systems = manifest["systems"]
    probe_count = int(manifest["probe_count"])
    moment_count = int(manifest["moment_count"])
    tau = np.empty((len(systems), probe_count, moment_count), dtype=np.complex128)
    for system_index, system in enumerate(systems):
        onsite, edge_i, edge_j, edge_v, probes = read_system(participant, system, probe_count)
        n = int(system["dimension"])
        lower = float(system["spectral_lower"])
        upper = float(system["spectral_upper"])
        a = 0.5 * (upper - lower)
        b = 0.5 * (upper + lower)
        for probe_index, probe in enumerate(probes):
            previous = probe.copy()
            tau[system_index, probe_index, 0] = np.vdot(probe, previous) / n
            if moment_count == 1:
                continue
            current = scaled_matvec(probe, onsite, edge_i, edge_j, edge_v, a, b)
            tau[system_index, probe_index, 1] = np.vdot(probe, current) / n
            for order in range(2, moment_count):
                following = (
                    2.0 * scaled_matvec(current, onsite, edge_i, edge_j, edge_v, a, b)
                    - previous
                )
                tau[system_index, probe_index, order] = np.vdot(probe, following) / n
                previous, current = current, following
    return tau


def decaying_root(z: complex) -> tuple[complex, complex]:
    candidate = complex(np.sqrt(z * z - 1.0 + 0.0j))
    root = candidate if abs(z - candidate) <= abs(z + candidate) else -candidate
    q = 1.0 / (z + root)
    return root, q


def contract(tau_mean: np.ndarray, query: dict, system: dict) -> complex:
    prefix = int(query["prefix"])
    a = 0.5 * (float(system["spectral_upper"]) - float(system["spectral_lower"]))
    b = 0.5 * (float(system["spectral_upper"]) + float(system["spectral_lower"]))
    sigma = -1.0 if query["kind"] == "GA" else 1.0
    z = complex((float(query["energy"]) - b) / a, sigma * float(query["eta"]) / a)
    root, q = decaying_root(z)
    total = tau_mean[0]
    power = q
    for order in range(1, prefix):
        total += 2.0 * power * tau_mean[order]
        power *= q
    value = total / (a * root)
    if query["kind"] == "DOS":
        return complex(-value.imag / math.pi, 0.0)
    return complex(value)


def read_queries(path: Path) -> list[dict]:
    result = []
    for row in csv_rows(path):
        result.append(
            {
                "query_id": row["query_id"],
                "system_id": row["system_id"],
                "prefix": int(row["prefix"]),
                "kind": row["kind"],
                "energy": float(row["energy"]),
                "eta": float(row["eta"]),
            }
        )
    return result


def gershgorin(participant: Path, system: dict) -> float:
    n = int(system["dimension"])
    onsite = np.empty(n, dtype=np.float64)
    for row in csv_rows(participant / "input" / system["onsite_file"]):
        onsite[int(row["index"])] = float(row["value"])
    lower = float(system["spectral_lower"])
    upper = float(system["spectral_upper"])
    a = 0.5 * (upper - lower)
    b = 0.5 * (upper + lower)
    radius = np.abs((onsite - b) / a)
    for row in csv_rows(participant / "input" / system["edges_file"]):
        value = abs(complex(float(row["value_real"]), float(row["value_imag"]))) / a
        radius[int(row["i"])] += value
        radius[int(row["j"])] += value
    return float(np.max(radius))


def write_outputs(participant: Path, output: Path, manifest: dict, tau: np.ndarray) -> None:
    output.mkdir(parents=True, exist_ok=True)
    np.savez(
        output / "moments.npz",
        schema_version=np.asarray("spectral-moments/v1"),
        system_ids=np.asarray([item["system_id"] for item in manifest["systems"]]),
        dimensions=np.asarray([item["dimension"] for item in manifest["systems"]], dtype=np.int64),
        moment_count=np.asarray(int(manifest["moment_count"]), dtype=np.int64),
        probe_count=np.asarray(int(manifest["probe_count"]), dtype=np.int64),
        tau_real=np.asarray(tau.real, dtype=np.float64),
        tau_imag=np.asarray(tau.imag, dtype=np.float64),
    )
    queries = read_queries(participant / "input" / manifest["public_queries_file"])
    system_map = {item["system_id"]: item for item in manifest["systems"]}
    system_index = {item["system_id"]: index for index, item in enumerate(manifest["systems"])}
    values = []
    for query in queries:
        index = system_index[query["system_id"]]
        values.append(contract(np.mean(tau[index], axis=0), query, system_map[query["system_id"]]))
    with (output / "public_response.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(RESPONSE_COLUMNS)
        for query, value in zip(queries, values):
            writer.writerow(
                [
                    query["query_id"],
                    query["system_id"],
                    query["prefix"],
                    query["kind"],
                    format(query["energy"], ".17g"),
                    format(query["eta"], ".17g"),
                    format(value.real, ".17g"),
                    format(value.imag, ".17g"),
                ]
            )
    diagnostics = {
        "schema_version": "spectral-diagnostics/v1",
        "moment_count": int(manifest["moment_count"]),
        "probe_count": int(manifest["probe_count"]),
        "public_query_count": len(queries),
        "systems": [],
    }
    for index, system in enumerate(manifest["systems"]):
        values_for_system = tau[index]
        diagnostics["systems"].append(
            {
                "system_id": system["system_id"],
                "dimension": int(system["dimension"]),
                "tau0_max_abs_error": float(np.max(np.abs(values_for_system[:, 0] - 1.0))),
                "max_abs_imaginary_moment": float(np.max(np.abs(values_for_system.imag))),
                "max_abs_moment": float(np.max(np.abs(values_for_system))),
                "scaled_gershgorin_radius": gershgorin(participant, system),
            }
        )
    (output / "diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--participant", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    participant = args.participant.resolve()
    manifest = json.loads((participant / "input" / "manifest.json").read_text(encoding="utf-8"))
    tau = sparse_moments(participant, manifest)
    write_outputs(participant, args.output.resolve(), manifest, tau)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
