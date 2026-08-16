#!/usr/bin/env python3
"""Operator-only alternative implementation for evaluator validation.

Hamiltonian action is accumulated directly from site and bond records; no dense
Hamiltonian is used by the recurrence.  The clean reference instead assembles
the full block matrix.  Shared code is limited to public-input parsing, output
schema serialization, and the disclosed contraction/observable definitions.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import numpy as np


def load_schema_module(task_root: Path):
    path = task_root / "author" / "reference_solver" / "solve.py"
    spec = importlib.util.spec_from_file_location("packet_schema_support", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load schema support")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def operator_data(loaded: dict[str, object], realization: dict[str, str]) -> dict[str, object]:
    config = loaded["config"]
    sites = loaded["sites"]
    indices = {site["site_id"]: index for index, site in enumerate(sites)}
    coordinates = {
        site["site_id"]: (float(site["x"]), float(site["y"])) for site in sites
    }
    rid = realization["realization_id"]
    diagonal = np.asarray(
        [loaded["onsite"][(rid, site["site_id"])] for site in sites], dtype=np.float64
    )
    edges: list[tuple[int, int, np.ndarray]] = []
    hopping = float(config["hopping_t"])
    soc = float(config["soc_lambda"])
    for bond in loaded["bonds"]:
        source, target = bond["source_id"], bond["target_id"]
        i, j = indices[source], indices[target]
        xi, yi = coordinates[source]
        xj, yj = coordinates[target]
        dx, dy = xj - xi, yj - yi
        phase = np.exp(1.0j * float(bond["phi"]))
        block = phase * np.array(
            [
                [-hopping, -soc * dx + 1.0j * soc * dy],
                [soc * dx + 1.0j * soc * dy, -hopping],
            ],
            dtype=np.complex128,
        )
        edges.append((i, j, block))
    return {"diagonal": diagonal, "edges": edges, "n_sites": len(sites)}


def apply_h(data: dict[str, object], vector: np.ndarray) -> np.ndarray:
    n_sites = int(data["n_sites"])
    state = np.asarray(vector, dtype=np.complex128).reshape(n_sites, 2)
    scalar = data["diagonal"][:, 0]
    ising = data["diagonal"][:, 1]
    result = np.empty_like(state)
    result[:, 0] = (scalar + ising) * state[:, 0]
    result[:, 1] = (scalar - ising) * state[:, 1]
    for i, j, block in data["edges"]:
        result[i] += block @ state[j]
        result[j] += block.conj().T @ state[i]
    return result.reshape(-1)


def basis_from_action(
    data: dict[str, object], psi0: np.ndarray, center: float, half_width: float, order: int
) -> np.ndarray:
    def scaled(vector: np.ndarray) -> np.ndarray:
        return (apply_h(data, vector) - center * vector) / half_width

    basis = np.empty((order, psi0.size), dtype=np.complex128)
    basis[0] = psi0
    basis[1] = scaled(psi0)
    for n in range(2, order):
        basis[n] = 2.0 * scaled(basis[n - 1]) - basis[n - 2]
    return basis


def dense_for_bounds(data: dict[str, object]) -> np.ndarray:
    dimension = 2 * int(data["n_sites"])
    identity = np.eye(dimension, dtype=np.complex128)
    return np.column_stack([apply_h(data, identity[:, column]) for column in range(dimension)])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("participant", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    public_root = arguments.participant.resolve()
    task_root = Path(__file__).resolve().parents[2]
    schema = load_schema_module(task_root)
    loaded = schema.load_inputs(public_root)
    config = loaded["config"]
    sites = loaded["sites"]
    realizations = loaded["realizations"]
    times = loaded["times"]
    order = int(config["basis_order"])
    psi0 = schema.initial_state(config, sites, "none")
    basis_blocks: list[np.ndarray] = []
    bounds: list[dict[str, object]] = []
    for realization in realizations:
        data = operator_data(loaded, realization)
        center = float(realization["center"])
        half_width = float(realization["half_width"])
        basis_blocks.append(basis_from_action(data, psi0, center, half_width, order))
        eigenvalues = np.linalg.eigvalsh(dense_for_bounds(data))
        radius = float(np.max(np.abs((eigenvalues[[0, -1]] - center) / half_width)))
        bounds.append(
            {
                "realization_id": realization["realization_id"],
                "eigenvalue_min": float(eigenvalues[0]),
                "eigenvalue_max": float(eigenvalues[-1]),
                "scaled_radius": radius,
                "within_declared_interval": bool(radius <= 1.0 + 2.0e-12),
            }
        )
    flat_basis = np.stack(basis_blocks)
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output / "basis.npz",
        basis=flat_basis.reshape(len(realizations), order, len(sites), 2),
        realization_ids=np.asarray([row["realization_id"] for row in realizations], dtype=np.str_),
        site_ids=np.asarray([row["site_id"] for row in sites], dtype=np.str_),
        orders=np.arange(order, dtype=np.int64),
        instance_id=np.asarray(config["instance_id"], dtype=np.str_),
    )
    bessel = schema.load_bessel(public_root)
    rows = schema.trajectory_rows(flat_basis, realizations, sites, times, bessel, "none")
    aggregate_rows = schema.aggregate(rows, times)
    report = schema.make_analysis(config, realizations, times, rows, bounds)
    schema.write_csv(output / "trajectories.csv", schema.TRAJECTORY_COLUMNS, rows)
    schema.write_csv(output / "ensemble.csv", schema.ENSEMBLE_COLUMNS, aggregate_rows)
    (output / "analysis.json").write_text(
        schema.json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
