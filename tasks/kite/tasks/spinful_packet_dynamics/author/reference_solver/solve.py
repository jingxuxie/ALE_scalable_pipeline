#!/usr/bin/env python3
"""Public-input-only dense reference solution for the spinful packet task."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path
from typing import Callable

import numpy as np


TRAJECTORY_COLUMNS = [
    "realization_id",
    "disorder_model",
    "time",
    "norm",
    "sx",
    "sy",
    "sz",
    "mean_x",
    "mean_y",
    "second_x",
    "second_y",
    "second_xy",
]
OBSERVABLES = TRAJECTORY_COLUMNS[3:]
ENSEMBLE_COLUMNS = ["disorder_model", "time", "count"] + [
    f"{name}_{suffix}" for name in OBSERVABLES for suffix in ("mean", "std")
]
MUTATIONS = {
    "none",
    "wrong_soc_sign",
    "conjugate_peierls_phase",
    "swap_soc_axes",
    "omit_ising_disorder",
    "swap_initial_spin",
    "unnormalized_packet",
    "first_order_recurrence",
    "real_bessel_coefficients",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_bessel(public_root: Path) -> Callable[[float, int], np.ndarray]:
    helper = public_root / "software" / "bessel.py"
    spec = importlib.util.spec_from_file_location("public_bessel_helper", helper)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load public Bessel helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bessel_j_sequence


def load_inputs(public_root: Path) -> dict[str, object]:
    input_root = public_root / "input"
    config = json.loads((input_root / "config.json").read_text(encoding="utf-8"))
    sites = read_csv(input_root / "sites.csv")
    bonds = read_csv(input_root / "bonds.csv")
    realizations = read_csv(input_root / "realizations.csv")
    onsite_rows = read_csv(input_root / "onsite.csv")
    times = [float(row["time"]) for row in read_csv(input_root / "times.csv")]
    onsite = {
        (row["realization_id"], row["site_id"]): (float(row["u"]), float(row["m_z"]))
        for row in onsite_rows
    }
    return {
        "config": config,
        "sites": sites,
        "bonds": bonds,
        "realizations": realizations,
        "onsite": onsite,
        "times": times,
    }


def initial_state(config: dict[str, object], sites: list[dict[str, str]], mutation: str) -> np.ndarray:
    state = config["initial_state"]
    x0, y0 = float(state["x0"]), float(state["y0"])
    sigma = float(state["sigma"])
    kx, ky = float(state["kx"]), float(state["ky"])
    theta, alpha = float(state["theta"]), float(state["alpha"])
    spinor = np.array(
        [np.cos(theta / 2.0), np.exp(1.0j * alpha) * np.sin(theta / 2.0)],
        dtype=np.complex128,
    )
    if mutation == "swap_initial_spin":
        spinor = spinor[::-1].copy()
    packet = np.empty((len(sites), 2), dtype=np.complex128)
    for index, site in enumerate(sites):
        x, y = float(site["x"]), float(site["y"])
        envelope = np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (4.0 * sigma**2))
        plane_wave = np.exp(1.0j * (kx * x + ky * y))
        packet[index] = envelope * plane_wave * spinor
    if mutation != "unnormalized_packet":
        packet /= np.linalg.norm(packet)
    return packet.reshape(-1)


def build_hamiltonian(
    config: dict[str, object],
    sites: list[dict[str, str]],
    bonds: list[dict[str, str]],
    onsite: dict[tuple[str, str], tuple[float, float]],
    realization: dict[str, str],
    mutation: str,
) -> np.ndarray:
    n_sites = len(sites)
    hamiltonian = np.zeros((2 * n_sites, 2 * n_sites), dtype=np.complex128)
    site_index = {row["site_id"]: index for index, row in enumerate(sites)}
    coordinates = {
        row["site_id"]: (float(row["x"]), float(row["y"])) for row in sites
    }
    realization_id = realization["realization_id"]
    for site in sites:
        index = site_index[site["site_id"]]
        scalar, ising = onsite[(realization_id, site["site_id"])]
        if mutation == "omit_ising_disorder" and realization["disorder_model"] == "scalar_ising":
            paired_id = realization_id.replace("scalar_ising_", "scalar_", 1)
            ising = onsite[(paired_id, site["site_id"])][1]
        hamiltonian[2 * index, 2 * index] = scalar + ising
        hamiltonian[2 * index + 1, 2 * index + 1] = scalar - ising

    hopping = float(config["hopping_t"])
    soc = float(config["soc_lambda"])
    if mutation == "wrong_soc_sign":
        soc = -soc
    identity = np.eye(2, dtype=np.complex128)
    sigma_x = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.complex128)
    sigma_y = np.array([[0.0, -1.0j], [1.0j, 0.0]], dtype=np.complex128)
    for bond in bonds:
        source, target = bond["source_id"], bond["target_id"]
        i, j = site_index[source], site_index[target]
        xi, yi = coordinates[source]
        xj, yj = coordinates[target]
        dx, dy = xj - xi, yj - yi
        if mutation == "swap_soc_axes":
            dx, dy = dy, dx
        phi = float(bond["phi"])
        if mutation == "conjugate_peierls_phase":
            phi = -phi
        block = np.exp(1.0j * phi) * (
            -hopping * identity + 1.0j * soc * (dy * sigma_x - dx * sigma_y)
        )
        hamiltonian[2 * i : 2 * i + 2, 2 * j : 2 * j + 2] = block
        hamiltonian[2 * j : 2 * j + 2, 2 * i : 2 * i + 2] = block.conj().T
    return hamiltonian


def make_basis(
    hamiltonian: np.ndarray,
    psi0: np.ndarray,
    center: float,
    half_width: float,
    order: int,
    mutation: str,
) -> np.ndarray:
    scaled = (hamiltonian - center * np.eye(hamiltonian.shape[0])) / half_width
    vectors = np.empty((order, hamiltonian.shape[0]), dtype=np.complex128)
    vectors[0] = psi0
    vectors[1] = scaled @ psi0
    for n in range(2, order):
        if mutation == "first_order_recurrence":
            vectors[n] = scaled @ vectors[n - 1]
        else:
            vectors[n] = 2.0 * (scaled @ vectors[n - 1]) - vectors[n - 2]
    return vectors


def contract(
    basis: np.ndarray,
    center: float,
    half_width: float,
    time: float,
    bessel: Callable[[float, int], np.ndarray],
    mutation: str,
) -> np.ndarray:
    order = basis.shape[0]
    functions = bessel(half_width * time, order)
    coefficients = np.empty(order, dtype=np.complex128)
    coefficients[0] = functions[0]
    if mutation == "real_bessel_coefficients":
        coefficients[1:] = 2.0 * functions[1:]
    else:
        coefficients[1:] = 2.0 * (-1.0j) ** np.arange(1, order) * functions[1:]
    return np.exp(-1.0j * center * time) * np.einsum("n,nd->d", coefficients, basis)


def observables(state: np.ndarray, sites: list[dict[str, str]]) -> dict[str, float]:
    spinors = state.reshape(len(sites), 2)
    alpha, beta = spinors[:, 0], spinors[:, 1]
    probability = np.abs(alpha) ** 2 + np.abs(beta) ** 2
    norm = float(probability.sum())
    x = np.array([float(row["x"]) for row in sites], dtype=np.float64)
    y = np.array([float(row["y"]) for row in sites], dtype=np.float64)
    overlap = np.conj(alpha) * beta
    return {
        "norm": norm,
        "sx": float(2.0 * np.real(overlap).sum()),
        "sy": float(2.0 * np.imag(overlap).sum()),
        "sz": float((np.abs(alpha) ** 2 - np.abs(beta) ** 2).sum()),
        "mean_x": float(np.dot(x, probability) / norm),
        "mean_y": float(np.dot(y, probability) / norm),
        "second_x": float(np.dot(x * x, probability) / norm),
        "second_y": float(np.dot(y * y, probability) / norm),
        "second_xy": float(np.dot(x * y, probability) / norm),
    }


def trajectory_rows(
    all_basis: np.ndarray,
    realizations: list[dict[str, str]],
    sites: list[dict[str, str]],
    times: list[float],
    bessel: Callable[[float, int], np.ndarray],
    mutation: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for realization_index, realization in enumerate(realizations):
        center = float(realization["center"])
        half_width = float(realization["half_width"])
        for time in times:
            state = contract(
                all_basis[realization_index], center, half_width, time, bessel, mutation
            )
            row: dict[str, object] = {
                "realization_id": realization["realization_id"],
                "disorder_model": realization["disorder_model"],
                "time": format(time, ".17g"),
            }
            row.update({key: format(value, ".17g") for key, value in observables(state, sites).items()})
            rows.append(row)
    return rows


def aggregate(rows: list[dict[str, object]], times: list[float]) -> list[dict[str, object]]:
    models: list[str] = []
    for row in rows:
        model = str(row["disorder_model"])
        if model not in models:
            models.append(model)
    answer: list[dict[str, object]] = []
    for model in models:
        for time in times:
            members = [
                row
                for row in rows
                if row["disorder_model"] == model and abs(float(row["time"]) - time) < 1.0e-13
            ]
            aggregate_row: dict[str, object] = {
                "disorder_model": model,
                "time": format(time, ".17g"),
                "count": len(members),
            }
            for name in OBSERVABLES:
                values = np.array([float(row[name]) for row in members], dtype=np.float64)
                aggregate_row[f"{name}_mean"] = format(float(values.mean()), ".17g")
                aggregate_row[f"{name}_std"] = format(float(values.std(ddof=0)), ".17g")
            answer.append(aggregate_row)
    return answer


def make_analysis(
    config: dict[str, object],
    realizations: list[dict[str, str]],
    times: list[float],
    trajectory: list[dict[str, object]],
    bounds: list[dict[str, object]],
) -> dict[str, object]:
    contrasts: list[dict[str, float]] = []
    for time in times:
        by_model: dict[str, list[dict[str, object]]] = {}
        for model in ("scalar", "scalar_ising"):
            by_model[model] = [
                row
                for row in trajectory
                if row["disorder_model"] == model and abs(float(row["time"]) - time) < 1.0e-13
            ]
        sz = {
            model: float(np.mean([float(row["sz"]) for row in members]))
            for model, members in by_model.items()
        }
        spread = {
            model: float(
                np.mean(
                    [
                        float(row["second_x"])
                        - float(row["mean_x"]) ** 2
                        + float(row["second_y"])
                        - float(row["mean_y"]) ** 2
                        for row in members
                    ]
                )
            )
            for model, members in by_model.items()
        }
        contrasts.append(
            {
                "time": time,
                "scalar_sz_mean": sz["scalar"],
                "scalar_ising_sz_mean": sz["scalar_ising"],
                "delta_sz": sz["scalar_ising"] - sz["scalar"],
                "scalar_spread_mean": spread["scalar"],
                "scalar_ising_spread_mean": spread["scalar_ising"],
                "delta_spread": spread["scalar_ising"] - spread["scalar"],
            }
        )
    final = contrasts[-1]
    abs_scalar = abs(final["scalar_sz_mean"])
    abs_ising = abs(final["scalar_ising_sz_mean"])
    if abs(abs_scalar - abs_ising) <= 1.0e-14:
        smaller_abs_sz = "tie"
    else:
        smaller_abs_sz = "scalar" if abs_scalar < abs_ising else "scalar_ising"
    scalar_spread = final["scalar_spread_mean"]
    ising_spread = final["scalar_ising_spread_mean"]
    if abs(scalar_spread - ising_spread) <= 1.0e-14:
        spreading = "tie"
    else:
        spreading = "scalar" if scalar_spread > ising_spread else "scalar_ising"
    return {
        "schema_version": "spinful-packet-analysis/v1",
        "instance_id": config["instance_id"],
        "basis_order": int(config["basis_order"]),
        "bounds": bounds,
        "contrasts": contrasts,
        "conclusion": {
            "comparison_time": times[-1],
            "smaller_final_abs_sz_model": smaller_abs_sz,
            "greater_spreading_model": spreading,
        },
    }


def solve(public_root: Path, output_root: Path, mutation: str = "none") -> None:
    if mutation not in MUTATIONS:
        raise ValueError(f"unknown mutation {mutation!r}")
    loaded = load_inputs(public_root)
    config = loaded["config"]
    sites = loaded["sites"]
    bonds = loaded["bonds"]
    realizations = loaded["realizations"]
    onsite = loaded["onsite"]
    times = loaded["times"]
    bessel = load_bessel(public_root)
    order = int(config["basis_order"])
    psi0 = initial_state(config, sites, mutation)
    basis_blocks: list[np.ndarray] = []
    bounds: list[dict[str, object]] = []
    for realization in realizations:
        hamiltonian = build_hamiltonian(
            config, sites, bonds, onsite, realization, mutation
        )
        hermiticity_error = float(np.max(np.abs(hamiltonian - hamiltonian.conj().T)))
        if hermiticity_error > 1.0e-12:
            raise RuntimeError("constructed Hamiltonian is not Hermitian")
        eigenvalues = np.linalg.eigvalsh(hamiltonian)
        center = float(realization["center"])
        half_width = float(realization["half_width"])
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
        basis_blocks.append(
            make_basis(hamiltonian, psi0, center, half_width, order, mutation)
        )
    basis_flat = np.stack(basis_blocks, axis=0)
    basis = basis_flat.reshape(len(realizations), order, len(sites), 2)

    output_root.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_root / "basis.npz",
        basis=basis,
        realization_ids=np.asarray(
            [row["realization_id"] for row in realizations], dtype=np.str_
        ),
        site_ids=np.asarray([row["site_id"] for row in sites], dtype=np.str_),
        orders=np.arange(order, dtype=np.int64),
        instance_id=np.asarray(config["instance_id"], dtype=np.str_),
    )
    trajectories = trajectory_rows(
        basis_flat, realizations, sites, times, bessel, mutation
    )
    ensembles = aggregate(trajectories, times)
    analysis = make_analysis(config, realizations, times, trajectories, bounds)
    write_csv(output_root / "trajectories.csv", TRAJECTORY_COLUMNS, trajectories)
    write_csv(output_root / "ensemble.csv", ENSEMBLE_COLUMNS, ensembles)
    (output_root / "analysis.json").write_text(
        json.dumps(analysis, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("participant", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mutation", choices=sorted(MUTATIONS), default="none")
    arguments = parser.parse_args()
    solve(arguments.participant.resolve(), arguments.output.resolve(), arguments.mutation)


if __name__ == "__main__":
    main()
