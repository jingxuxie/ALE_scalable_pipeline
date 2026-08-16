#!/usr/bin/env python3
"""Generate the deterministic public lattice and private contraction times."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


TASK_ROOT = Path(__file__).resolve().parents[1]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
        handle.write("\n")


def _block(dx: float, dy: float, phi: float, hopping: float, soc: float) -> np.ndarray:
    identity = np.eye(2, dtype=np.complex128)
    sigma_x = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.complex128)
    sigma_y = np.array([[0.0, -1.0j], [1.0j, 0.0]], dtype=np.complex128)
    return np.exp(1.0j * phi) * (
        -hopping * identity + 1.0j * soc * (dy * sigma_x - dx * sigma_y)
    )


def _hamiltonian(
    sites: list[dict[str, object]],
    bonds: list[dict[str, object]],
    onsite: dict[str, tuple[float, float]],
    hopping: float,
    soc: float,
) -> np.ndarray:
    n_sites = len(sites)
    index = {str(site["site_id"]): i for i, site in enumerate(sites)}
    coordinates = {
        str(site["site_id"]): (float(site["x"]), float(site["y"])) for site in sites
    }
    matrix = np.zeros((2 * n_sites, 2 * n_sites), dtype=np.complex128)
    for site_id, i in index.items():
        scalar, ising = onsite[site_id]
        matrix[2 * i, 2 * i] = scalar + ising
        matrix[2 * i + 1, 2 * i + 1] = scalar - ising
    for bond in bonds:
        source = str(bond["source_id"])
        target = str(bond["target_id"])
        i, j = index[source], index[target]
        xi, yi = coordinates[source]
        xj, yj = coordinates[target]
        hij = _block(xj - xi, yj - yi, float(bond["phi"]), hopping, soc)
        matrix[2 * i : 2 * i + 2, 2 * j : 2 * j + 2] = hij
        matrix[2 * j : 2 * j + 2, 2 * i : 2 * i + 2] = hij.conj().T
    return matrix


def main(task_root: Path = TASK_ROOT) -> None:
    public_input = task_root / "participant" / "input"
    hidden_input = task_root / "private" / "hidden_inputs"
    public_input.mkdir(parents=True, exist_ok=True)
    hidden_input.mkdir(parents=True, exist_ok=True)

    nx, ny = 9, 8
    hopping = 1.0
    soc = 0.28
    flux_phase = 0.047
    base_mz = 0.12
    scalar_width = 0.82
    ising_width = 0.46
    rho_limit = 0.975
    basis_order = 52

    sites: list[dict[str, object]] = []
    for y in range(ny):
        for x in range(nx):
            sites.append({"site_id": f"s{y * nx + x:03d}", "x": x, "y": y})

    bonds: list[dict[str, object]] = []
    bond_number = 0
    for y in range(ny):
        for x in range(nx):
            source = f"s{y * nx + x:03d}"
            if x + 1 < nx:
                bonds.append(
                    {
                        "bond_id": f"b{bond_number:03d}",
                        "source_id": source,
                        "target_id": f"s{y * nx + x + 1:03d}",
                        "phi": -flux_phase * (y - (ny - 1) / 2.0),
                    }
                )
                bond_number += 1
            if y + 1 < ny:
                bonds.append(
                    {
                        "bond_id": f"b{bond_number:03d}",
                        "source_id": source,
                        "target_id": f"s{(y + 1) * nx + x:03d}",
                        "phi": 0.0,
                    }
                )
                bond_number += 1

    realization_rows: list[dict[str, object]] = []
    onsite_rows: list[dict[str, object]] = []
    realization_payload: list[dict[str, object]] = []
    paired_scalar_fields: list[np.ndarray] = []
    scalar_seeds = [42117, 42119, 42131]
    ising_seeds = [61301, 61303, 61307]
    for seed in scalar_seeds:
        paired_scalar_fields.append(
            np.random.default_rng(seed).uniform(-scalar_width / 2.0, scalar_width / 2.0, len(sites))
        )

    realization_definitions: list[tuple[str, str, np.ndarray, np.ndarray]] = []
    for pair_index, scalar_field in enumerate(paired_scalar_fields):
        realization_definitions.append(
            (
                f"scalar_{pair_index}",
                "scalar",
                scalar_field,
                np.full(len(sites), base_mz, dtype=np.float64),
            )
        )
    for pair_index, scalar_field in enumerate(paired_scalar_fields):
        ising_field = base_mz + np.random.default_rng(ising_seeds[pair_index]).uniform(
            -ising_width / 2.0, ising_width / 2.0, len(sites)
        )
        realization_definitions.append(
            (f"scalar_ising_{pair_index}", "scalar_ising", scalar_field, ising_field)
        )

    asymmetric_padding = [
        (0.21, 0.15),
        (0.17, 0.25),
        (0.24, 0.18),
        (0.19, 0.27),
        (0.23, 0.16),
        (0.18, 0.22),
    ]
    for realization_index, (realization_id, model, scalar_field, ising_field) in enumerate(
        realization_definitions
    ):
        onsite = {
            str(site["site_id"]): (float(scalar_field[i]), float(ising_field[i]))
            for i, site in enumerate(sites)
        }
        hamiltonian = _hamiltonian(sites, bonds, onsite, hopping, soc)
        eigenvalues = np.linalg.eigvalsh(hamiltonian)
        energy_min = float(eigenvalues[0])
        energy_max = float(eigenvalues[-1])
        lower_padding, upper_padding = asymmetric_padding[realization_index]
        declared_lower = energy_min - lower_padding
        declared_upper = energy_max + upper_padding
        raw_center = 0.5 * (declared_lower + declared_upper)
        raw_half_width = 0.5 * (declared_upper - declared_lower)
        # Canonicalize the LAPACK-derived values before both publication and
        # content hashing.  Nine decimals are far finer than the public
        # tolerances and the 0.15--0.27 spectral padding, while remaining stable
        # across supported eigvalsh implementations.
        center_text = format(raw_center, ".9f")
        half_width_text = format(raw_half_width, ".9f")
        center = float(center_text)
        half_width = float(half_width_text)
        realization_rows.append(
            {
                "realization_id": realization_id,
                "disorder_model": model,
                "center": center_text,
                "half_width": half_width_text,
            }
        )
        for site_index, site in enumerate(sites):
            onsite_rows.append(
                {
                    "realization_id": realization_id,
                    "site_id": site["site_id"],
                    "u": format(float(scalar_field[site_index]), ".17g"),
                    "m_z": format(float(ising_field[site_index]), ".17g"),
                }
            )
        realization_payload.append(
            {
                "realization_id": realization_id,
                "disorder_model": model,
                "center": center,
                "half_width": half_width,
                "u": scalar_field.tolist(),
                "m_z": ising_field.tolist(),
            }
        )

    public_times = [0.0, 0.22, 0.55, 0.95, 1.40, 1.95, 2.50]
    hidden_times = [0.11, 0.37, 0.78, 1.17, 1.73, 2.23]
    initial_state = {
        "x0": 3.15,
        "y0": 3.55,
        "sigma": 1.22,
        "kx": 0.71,
        "ky": -0.33,
        "theta": 1.08,
        "alpha": 0.41,
    }
    canonical_payload = {
        "sites": sites,
        "bonds": bonds,
        "realizations": realization_payload,
        "hopping": hopping,
        "soc": soc,
        "initial_state": initial_state,
        "basis_order": basis_order,
        "public_times": public_times,
    }
    canonical_bytes = json.dumps(
        canonical_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")
    instance_id = "spd-" + hashlib.sha256(canonical_bytes).hexdigest()[:24]

    _write_csv(public_input / "sites.csv", ["site_id", "x", "y"], sites)
    _write_csv(
        public_input / "bonds.csv",
        ["bond_id", "source_id", "target_id", "phi"],
        bonds,
    )
    _write_csv(
        public_input / "realizations.csv",
        ["realization_id", "disorder_model", "center", "half_width"],
        realization_rows,
    )
    _write_csv(
        public_input / "onsite.csv",
        ["realization_id", "site_id", "u", "m_z"],
        onsite_rows,
    )
    _write_csv(
        public_input / "times.csv",
        ["time"],
        [{"time": format(value, ".17g")} for value in public_times],
    )

    config = {
        "schema_version": "spinful-packet-instance/v1",
        "instance_id": instance_id,
        "boundary": "open",
        "site_order": "sites.csv row order",
        "spin_order": ["up", "down"],
        "hopping_t": hopping,
        "soc_lambda": soc,
        "basis_order": basis_order,
        "rho_limit": rho_limit,
        "time_interval": [0.0, 2.5],
        "initial_state": initial_state,
    }
    _write_json(public_input / "config.json", config)
    _write_json(
        hidden_input / "private_times.json",
        {
            "schema_version": "spinful-packet-private-times/v1",
            "instance_id": instance_id,
            "times": hidden_times,
        },
    )
    print(f"generated {instance_id}: {len(sites)} sites, {len(bonds)} bonds, 6 realizations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, default=TASK_ROOT)
    arguments = parser.parse_args()
    main(arguments.task_root.resolve())
