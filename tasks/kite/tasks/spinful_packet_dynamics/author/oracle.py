#!/usr/bin/env python3
"""Privileged independent oracle using spectral Chebyshev evaluation.

Unlike the clean-room solver, this implementation diagonalizes each scaled
Hamiltonian and evaluates ``T_n`` as ``cos(n arccos(E))``.  Bessel functions
come from an independent Gauss-Legendre integral rather than the public helper.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, header: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_public(public_root: Path) -> dict[str, object]:
    inputs = public_root / "input"
    config = json.loads((inputs / "config.json").read_text(encoding="utf-8"))
    sites = read_csv(inputs / "sites.csv")
    bonds = read_csv(inputs / "bonds.csv")
    realizations = read_csv(inputs / "realizations.csv")
    onsite = {
        (row["realization_id"], row["site_id"]): (float(row["u"]), float(row["m_z"]))
        for row in read_csv(inputs / "onsite.csv")
    }
    times = [float(row["time"]) for row in read_csv(inputs / "times.csv")]
    return {
        "config": config,
        "sites": sites,
        "bonds": bonds,
        "realizations": realizations,
        "onsite": onsite,
        "times": times,
    }


def packet(config: dict[str, object], sites: list[dict[str, str]]) -> np.ndarray:
    initial = config["initial_state"]
    coordinates = np.asarray(
        [[float(site["x"]), float(site["y"])] for site in sites], dtype=np.float64
    )
    displacement = coordinates - np.array([initial["x0"], initial["y0"]])
    envelope = np.exp(-np.sum(displacement * displacement, axis=1) / (4.0 * initial["sigma"] ** 2))
    plane = np.exp(
        1.0j * (initial["kx"] * coordinates[:, 0] + initial["ky"] * coordinates[:, 1])
    )
    spin = np.array(
        [
            np.cos(initial["theta"] / 2.0),
            np.cos(0.0) * np.exp(1.0j * initial["alpha"]) * np.sin(initial["theta"] / 2.0),
        ],
        dtype=np.complex128,
    )
    state = (envelope * plane)[:, None] * spin[None, :]
    return (state / np.sqrt(np.vdot(state, state).real)).reshape(-1)


def matrix_for(
    loaded: dict[str, object], realization: dict[str, str]
) -> np.ndarray:
    config = loaded["config"]
    sites = loaded["sites"]
    bonds = loaded["bonds"]
    onsite = loaded["onsite"]
    n_sites = len(sites)
    indices = {site["site_id"]: index for index, site in enumerate(sites)}
    xy = {site["site_id"]: (float(site["x"]), float(site["y"])) for site in sites}
    result = np.zeros((2 * n_sites, 2 * n_sites), dtype=np.complex128)
    rid = realization["realization_id"]
    for site in sites:
        index = indices[site["site_id"]]
        scalar, ising = onsite[(rid, site["site_id"])]
        result[2 * index : 2 * index + 2, 2 * index : 2 * index + 2] = np.diag(
            [scalar + ising, scalar - ising]
        )
    hopping = float(config["hopping_t"])
    soc = float(config["soc_lambda"])
    for bond in bonds:
        i, j = indices[bond["source_id"]], indices[bond["target_id"]]
        xi, yi = xy[bond["source_id"]]
        xj, yj = xy[bond["target_id"]]
        dx, dy = xj - xi, yj - yi
        phase = np.exp(1.0j * float(bond["phi"]))
        block = phase * np.array(
            [
                [-hopping, -soc * dx + 1.0j * soc * dy],
                [soc * dx + 1.0j * soc * dy, -hopping],
            ],
            dtype=np.complex128,
        )
        result[2 * i : 2 * i + 2, 2 * j : 2 * j + 2] = block
        result[2 * j : 2 * j + 2, 2 * i : 2 * i + 2] = block.conj().T
    return result


def spectral_basis(
    matrix: np.ndarray, state: np.ndarray, center: float, half_width: float, order: int
) -> tuple[np.ndarray, np.ndarray]:
    energies, eigenvectors = np.linalg.eigh(matrix)
    scaled_energies = (energies - center) / half_width
    if np.max(np.abs(scaled_energies)) >= 1.0:
        raise RuntimeError("oracle found an invalid rescaling interval")
    angles = np.arccos(scaled_energies)
    amplitudes = eigenvectors.conj().T @ state
    basis = np.empty((order, matrix.shape[0]), dtype=np.complex128)
    for n in range(order):
        basis[n] = eigenvectors @ (np.cos(n * angles) * amplitudes)
    return basis, energies


_QUAD_NODES, _QUAD_WEIGHTS = np.polynomial.legendre.leggauss(320)
_QUAD_THETA = 0.5 * np.pi * (_QUAD_NODES + 1.0)


def integral_bessel(argument: float, order: int) -> np.ndarray:
    n = np.arange(order, dtype=np.float64)[:, None]
    integrand = np.cos(n * _QUAD_THETA[None, :] - argument * np.sin(_QUAD_THETA)[None, :])
    return 0.5 * (integrand @ _QUAD_WEIGHTS)


def contract(basis: np.ndarray, center: float, half_width: float, time: float) -> np.ndarray:
    values = integral_bessel(half_width * time, basis.shape[0])
    coefficient = values.astype(np.complex128)
    coefficient[1:] *= 2.0 * (-1.0j) ** np.arange(1, basis.shape[0])
    return np.exp(-1.0j * center * time) * (coefficient @ basis)


def measure(state: np.ndarray, sites: list[dict[str, str]]) -> dict[str, float]:
    spin = state.reshape(len(sites), 2)
    up, down = spin[:, 0], spin[:, 1]
    density = up.real**2 + up.imag**2 + down.real**2 + down.imag**2
    norm = density.sum()
    x = np.fromiter((float(site["x"]) for site in sites), dtype=np.float64)
    y = np.fromiter((float(site["y"]) for site in sites), dtype=np.float64)
    cross = np.conj(up) * down
    return {
        "norm": float(norm),
        "sx": float(2.0 * np.real(cross).sum()),
        "sy": float(2.0 * np.imag(cross).sum()),
        "sz": float(np.sum(np.abs(up) ** 2 - np.abs(down) ** 2)),
        "mean_x": float(np.sum(x * density) / norm),
        "mean_y": float(np.sum(y * density) / norm),
        "second_x": float(np.sum(x**2 * density) / norm),
        "second_y": float(np.sum(y**2 * density) / norm),
        "second_xy": float(np.sum(x * y * density) / norm),
    }


def trajectories(
    bases: np.ndarray,
    realizations: list[dict[str, str]],
    sites: list[dict[str, str]],
    times: list[float],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, realization in enumerate(realizations):
        for time in times:
            state = contract(
                bases[index], float(realization["center"]), float(realization["half_width"]), time
            )
            row: dict[str, object] = {
                "realization_id": realization["realization_id"],
                "disorder_model": realization["disorder_model"],
                "time": format(time, ".17g"),
            }
            row.update({name: format(value, ".17g") for name, value in measure(state, sites).items()})
            rows.append(row)
    return rows


def ensembles(
    rows: list[dict[str, object]], times: list[float]
) -> list[dict[str, object]]:
    answer: list[dict[str, object]] = []
    for model in ("scalar", "scalar_ising"):
        for time in times:
            subset = [
                row
                for row in rows
                if row["disorder_model"] == model and abs(float(row["time"]) - time) < 1e-13
            ]
            record: dict[str, object] = {
                "disorder_model": model,
                "time": format(time, ".17g"),
                "count": len(subset),
            }
            for observable in OBSERVABLES:
                values = np.asarray([float(row[observable]) for row in subset])
                record[f"{observable}_mean"] = format(float(np.mean(values)), ".17g")
                record[f"{observable}_std"] = format(float(np.sqrt(np.mean((values - values.mean()) ** 2))), ".17g")
            answer.append(record)
    return answer


def analysis(
    config: dict[str, object],
    realizations: list[dict[str, str]],
    times: list[float],
    rows: list[dict[str, object]],
    bounds: list[dict[str, object]],
) -> dict[str, object]:
    contrasts: list[dict[str, float]] = []
    for time in times:
        model_values: dict[str, tuple[float, float]] = {}
        for model in ("scalar", "scalar_ising"):
            subset = [
                row
                for row in rows
                if row["disorder_model"] == model and abs(float(row["time"]) - time) < 1e-13
            ]
            sz = float(np.mean([float(row["sz"]) for row in subset]))
            spread = float(
                np.mean(
                    [
                        float(row["second_x"]) - float(row["mean_x"]) ** 2
                        + float(row["second_y"]) - float(row["mean_y"]) ** 2
                        for row in subset
                    ]
                )
            )
            model_values[model] = (sz, spread)
        scalar, ising = model_values["scalar"], model_values["scalar_ising"]
        contrasts.append(
            {
                "time": time,
                "scalar_sz_mean": scalar[0],
                "scalar_ising_sz_mean": ising[0],
                "delta_sz": ising[0] - scalar[0],
                "scalar_spread_mean": scalar[1],
                "scalar_ising_spread_mean": ising[1],
                "delta_spread": ising[1] - scalar[1],
            }
        )
    final = contrasts[-1]
    if abs(abs(final["scalar_sz_mean"]) - abs(final["scalar_ising_sz_mean"])) <= 1e-14:
        smaller_abs_sz = "tie"
    elif abs(final["scalar_sz_mean"]) < abs(final["scalar_ising_sz_mean"]):
        smaller_abs_sz = "scalar"
    else:
        smaller_abs_sz = "scalar_ising"
    if abs(final["scalar_spread_mean"] - final["scalar_ising_spread_mean"]) <= 1e-14:
        spreading = "tie"
    elif final["scalar_spread_mean"] > final["scalar_ising_spread_mean"]:
        spreading = "scalar"
    else:
        spreading = "scalar_ising"
    return {
        "schema_version": "spinful-packet-analysis/v1",
        "instance_id": config["instance_id"],
        "basis_order": config["basis_order"],
        "bounds": bounds,
        "contrasts": contrasts,
        "conclusion": {
            "comparison_time": times[-1],
            "smaller_final_abs_sz_model": smaller_abs_sz,
            "greater_spreading_model": spreading,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("participant", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("hidden_times", type=Path)
    parser.add_argument("hidden_output", type=Path)
    args = parser.parse_args()
    loaded = load_public(args.participant.resolve())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = loaded["config"]
    sites = loaded["sites"]
    realizations = loaded["realizations"]
    state = packet(config, sites)
    basis_blocks: list[np.ndarray] = []
    bounds: list[dict[str, object]] = []
    for realization in realizations:
        matrix = matrix_for(loaded, realization)
        basis, energies = spectral_basis(
            matrix,
            state,
            float(realization["center"]),
            float(realization["half_width"]),
            int(config["basis_order"]),
        )
        radius = float(
            max(
                abs((energies[0] - float(realization["center"])) / float(realization["half_width"])),
                abs((energies[-1] - float(realization["center"])) / float(realization["half_width"])),
            )
        )
        if radius > float(config["rho_limit"]) + 2.0e-12:
            raise RuntimeError("oracle spectrum exceeds the public rho_limit")
        basis_blocks.append(basis)
        bounds.append(
            {
                "realization_id": realization["realization_id"],
                "eigenvalue_min": float(energies[0]),
                "eigenvalue_max": float(energies[-1]),
                "scaled_radius": radius,
                "within_declared_interval": bool(radius <= 1.0 + 2e-12),
            }
        )
    bases = np.stack(basis_blocks)
    shaped = bases.reshape(len(realizations), int(config["basis_order"]), len(sites), 2)
    np.savez_compressed(
        output / "basis.npz",
        basis=shaped,
        realization_ids=np.asarray([row["realization_id"] for row in realizations], dtype=np.str_),
        site_ids=np.asarray([row["site_id"] for row in sites], dtype=np.str_),
        orders=np.arange(int(config["basis_order"]), dtype=np.int64),
        instance_id=np.asarray(config["instance_id"], dtype=np.str_),
    )
    public_rows = trajectories(bases, realizations, sites, loaded["times"])
    ensemble_rows = ensembles(public_rows, loaded["times"])
    report = analysis(config, realizations, loaded["times"], public_rows, bounds)
    write_csv(output / "trajectories.csv", TRAJECTORY_COLUMNS, public_rows)
    write_csv(output / "ensemble.csv", ENSEMBLE_COLUMNS, ensemble_rows)
    with (output / "analysis.json").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        handle.write("\n")
    private_times = json.loads(args.hidden_times.read_text(encoding="utf-8"))["times"]
    hidden_rows = trajectories(bases, realizations, sites, [float(value) for value in private_times])
    hidden_output = args.hidden_output.resolve()
    hidden_output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(hidden_output, TRAJECTORY_COLUMNS, hidden_rows)
    print(f"oracle wrote {output} for {config['instance_id']}")


if __name__ == "__main__":
    main()
