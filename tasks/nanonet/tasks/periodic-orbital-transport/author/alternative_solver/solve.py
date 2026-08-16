#!/usr/bin/env python3
"""Independent dense solver for the periodic orbital transport task.

This implementation intentionally uses a damped Dyson fixed-point iteration for
the two lead surfaces.  It shares no implementation code with the privileged
oracle or the participant reference solution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SCHEMA_VERSION = "periodic-orbital-transport-output/v1"
SURFACE_TOL = 5.0e-12
SURFACE_MAX_ITER = 30000
CUTOFF_EPS = 1.0e-12
_CANONICAL_ORBITALS = ("s", "px", "py", "pz")
_ORBITAL_INDEX = {name: index for index, name in enumerate(_CANONICAL_ORBITALS)}


def dagger(matrix: np.ndarray) -> np.ndarray:
    return matrix.conj().T


def frobenius(matrix: np.ndarray) -> float:
    return float(np.linalg.norm(matrix, ord="fro"))


def _as_grid(value: Any, name: str) -> np.ndarray:
    """Accept the public explicit-array form plus common linspace spellings."""
    if isinstance(value, dict):
        if "values" in value:
            value = value["values"]
        else:
            count = value.get("count", value.get("num", value.get("points")))
            if count is None or "start" not in value or "stop" not in value:
                raise ValueError(f"{name} must contain values or start/stop/count")
            value = np.linspace(
                float(value["start"]), float(value["stop"]), int(count), dtype=np.float64
            )
    result = np.asarray(value, dtype=np.float64)
    if result.ndim != 1 or result.size == 0 or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a nonempty finite one-dimensional grid")
    return result


def _species_pair_key(first: str, second: str) -> str:
    return "|".join(sorted((first, second)))


def _canonical_hopping_block(
    row_orbitals: tuple[str, ...],
    column_orbitals: tuple[str, ...],
    direction: np.ndarray,
    parameters: dict[str, Any],
) -> np.ndarray:
    """Construct an s/p hopping via scalar, vector, and projector blocks."""
    v_ss = float(parameters["ss_sigma"])
    v_sp = float(parameters["sp_sigma"])
    v_pp_sigma = float(parameters["pp_sigma"])
    v_pp_pi = float(parameters["pp_pi"])

    full = np.empty((4, 4), dtype=np.float64)
    full[0, 0] = v_ss
    full[0, 1:] = v_sp * direction
    full[1:, 0] = -v_sp * direction
    projector = np.outer(direction, direction)
    full[1:, 1:] = v_pp_pi * np.eye(3) + (v_pp_sigma - v_pp_pi) * projector

    rows = [_ORBITAL_INDEX[orbital] for orbital in row_orbitals]
    columns = [_ORBITAL_INDEX[orbital] for orbital in column_orbitals]
    return full[np.ix_(rows, columns)]


def assemble_periodic_blocks(
    data: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[slice]]:
    species = data["species"]
    sites = data["sites"]
    hoppings = data["hoppings"]
    cutoff = float(data["neighbor_cutoff"])
    lattice = np.asarray(data["lattice_vector"], dtype=np.float64)
    if lattice.shape != (3,) or not np.all(np.isfinite(lattice)):
        raise ValueError("lattice_vector must contain three finite numbers")
    if not math.isfinite(cutoff) or cutoff <= 0.0:
        raise ValueError("neighbor_cutoff must be positive and finite")
    if not sites:
        raise ValueError("sites must not be empty")

    site_orbitals: list[tuple[str, ...]] = []
    positions: list[np.ndarray] = []
    site_species: list[str] = []
    site_slices: list[slice] = []
    basis_site: list[int] = []
    cursor = 0

    for site_index, site in enumerate(sites):
        species_name = str(site["species"])
        if species_name not in species:
            raise ValueError(f"unknown species at site {site_index}: {species_name}")
        orbitals = tuple(species[species_name]["orbitals"])
        if orbitals not in (("s",), _CANONICAL_ORBITALS):
            raise ValueError(
                f"species {species_name} orbitals must be ['s'] or ['s','px','py','pz']"
            )
        position = np.asarray(site["position"], dtype=np.float64)
        if position.shape != (3,) or not np.all(np.isfinite(position)):
            raise ValueError(f"site {site_index} has an invalid position")

        site_species.append(species_name)
        site_orbitals.append(orbitals)
        positions.append(position)
        site_slices.append(slice(cursor, cursor + len(orbitals)))
        basis_site.extend([site_index] * len(orbitals))
        cursor += len(orbitals)

    h0 = np.zeros((cursor, cursor), dtype=np.complex128)
    h1 = np.zeros_like(h0)

    for site_index, (species_name, orbitals, block_slice) in enumerate(
        zip(site_species, site_orbitals, site_slices)
    ):
        onsite = species[species_name]["onsite"]
        values = np.asarray([float(onsite[orbital]) for orbital in orbitals])
        if not np.all(np.isfinite(values)):
            raise ValueError(f"species {species_name} has non-finite onsite data")
        h0[block_slice, block_slice] += np.diag(values)

    def hopping(row_site: int, column_site: int, displacement: np.ndarray) -> np.ndarray:
        distance = float(np.linalg.norm(displacement))
        if distance == 0.0:
            raise ValueError("coincident interacting sites are not permitted")
        pair_key = _species_pair_key(site_species[row_site], site_species[column_site])
        try:
            parameters = hoppings[pair_key]
        except KeyError as exc:
            raise ValueError(f"missing hopping parameters for {pair_key}") from exc
        return _canonical_hopping_block(
            site_orbitals[row_site],
            site_orbitals[column_site],
            displacement / distance,
            parameters,
        )

    # Same-cell pairs are visited once and explicitly completed by transpose.
    for row_site in range(len(sites)):
        for column_site in range(row_site + 1, len(sites)):
            displacement = positions[column_site] - positions[row_site]
            distance = float(np.linalg.norm(displacement))
            if 0.0 < distance <= cutoff + CUTOFF_EPS:
                block = hopping(row_site, column_site, displacement)
                row_slice = site_slices[row_site]
                column_slice = site_slices[column_site]
                h0[row_slice, column_slice] += block
                h0[column_slice, row_slice] += block.T

    # Every ordered cell-0 to cell-1 pair contributes to the forward block.
    for row_site in range(len(sites)):
        for column_site in range(len(sites)):
            displacement = positions[column_site] + lattice - positions[row_site]
            distance = float(np.linalg.norm(displacement))
            if 0.0 < distance <= cutoff + CUTOFF_EPS:
                block = hopping(row_site, column_site, displacement)
                h1[site_slices[row_site], site_slices[column_site]] += block

    if not np.all(np.isfinite(h0)) or not np.all(np.isfinite(h1)):
        raise ValueError("Hamiltonian assembly produced a non-finite value")
    return h0, h1, np.asarray(basis_site, dtype=np.int64), site_slices


def build_device(
    h0: np.ndarray,
    h1: np.ndarray,
    site_slices: list[slice],
    device: dict[str, Any],
) -> np.ndarray:
    cells = int(device["cells"])
    if cells < 1 or cells != device["cells"]:
        raise ValueError("device.cells must be a positive integer")
    potentials = np.asarray(device["site_potential"], dtype=np.float64)
    if potentials.shape != (cells, len(site_slices)) or not np.all(np.isfinite(potentials)):
        raise ValueError("device.site_potential has the wrong shape or non-finite entries")
    bond_scale = np.asarray(device["bond_scale"], dtype=np.float64)
    if bond_scale.shape != (max(cells - 1, 0),) or not np.all(np.isfinite(bond_scale)):
        raise ValueError("device.bond_scale must have cells-1 finite entries")

    cell_size = h0.shape[0]
    hd = np.zeros((cells * cell_size, cells * cell_size), dtype=np.complex128)
    for cell in range(cells):
        cell_slice = slice(cell * cell_size, (cell + 1) * cell_size)
        hd[cell_slice, cell_slice] = h0
        for site_index, orbital_slice in enumerate(site_slices):
            shifted = slice(
                cell * cell_size + orbital_slice.start,
                cell * cell_size + orbital_slice.stop,
            )
            hd[shifted, shifted] += potentials[cell, site_index] * np.eye(
                orbital_slice.stop - orbital_slice.start
            )
        if cell + 1 < cells:
            next_slice = slice((cell + 1) * cell_size, (cell + 2) * cell_size)
            coupling = bond_scale[cell] * h1
            hd[cell_slice, next_slice] = coupling
            hd[next_slice, cell_slice] = dagger(coupling)
    return hd


def surface_equation_residual(
    g_surface: np.ndarray, h0: np.ndarray, outward: np.ndarray, z: complex
) -> float:
    identity = np.eye(h0.shape[0], dtype=np.complex128)
    effective = z * identity - h0 - outward @ g_surface @ dagger(outward)
    numerator = frobenius(effective @ g_surface - identity)
    denominator = max(frobenius(identity), frobenius(effective) * frobenius(g_surface))
    return numerator / denominator


def _fixed_point_surface(
    h0: np.ndarray,
    outward: np.ndarray,
    z: complex,
    initial: np.ndarray | None,
) -> tuple[np.ndarray, float, int]:
    """Solve g=(zI-H0-B g B^H)^-1 by guarded damped Picard steps."""
    size = h0.shape[0]
    identity = np.eye(size, dtype=np.complex128)
    scale = max(
        abs(z),
        frobenius(h0),
        frobenius(outward),
        np.finfo(np.float64).tiny,
    )
    scaled_z = z / scale
    scaled_h0 = h0 / scale
    scaled_outward = outward / scale
    bare = scaled_z * identity - scaled_h0
    try:
        current = (
            np.linalg.solve(bare, identity)
            if initial is None
            else scale * initial.copy()
        )
    except np.linalg.LinAlgError as exc:
        raise RuntimeError(f"singular bare lead resolvent at z={z!r}") from exc

    residual = surface_equation_residual(
        current, scaled_h0, scaled_outward, scaled_z
    )
    if not math.isfinite(residual):
        raise RuntimeError(f"non-finite initial surface residual at z={z!r}")
    relaxation = 0.5

    for iteration in range(1, SURFACE_MAX_ITER + 1):
        effective = (
            scaled_z * identity
            - scaled_h0
            - scaled_outward @ current @ dagger(scaled_outward)
        )
        try:
            fixed_value = np.linalg.solve(effective, identity)
        except np.linalg.LinAlgError as exc:
            raise RuntimeError(f"singular Dyson fixed-point matrix at z={z!r}") from exc
        if not np.all(np.isfinite(fixed_value)):
            raise RuntimeError(f"non-finite Dyson iterate at z={z!r}")

        # Backtrack only when a step substantially worsens the nonlinear equation.
        trial_relaxation = relaxation
        accepted: np.ndarray | None = None
        accepted_residual = math.inf
        for _ in range(9):
            trial = current + trial_relaxation * (fixed_value - current)
            trial_residual = surface_equation_residual(
                trial, scaled_h0, scaled_outward, scaled_z
            )
            if math.isfinite(trial_residual) and (
                trial_residual <= 1.25 * residual or trial_relaxation <= 1.0 / 256.0
            ):
                accepted = trial
                accepted_residual = trial_residual
                break
            trial_relaxation *= 0.5
        if accepted is None or not math.isfinite(accepted_residual):
            raise RuntimeError(f"Dyson fixed-point line search failed at z={z!r}")

        step = frobenius(accepted - current) / max(1.0, frobenius(accepted))
        previous_residual = residual
        current = accepted
        residual = accepted_residual

        if residual <= SURFACE_TOL and step <= 2.0e-11:
            # Recompute the reported residual using the final, unmodified iterate.
            physical_green = current / scale
            residual = surface_equation_residual(physical_green, h0, outward, z)
            if residual <= 5.0e-11:
                return physical_green, residual, iteration

        if residual < 0.70 * previous_residual:
            relaxation = min(0.55, trial_relaxation * 1.08)
        elif residual > 0.98 * previous_residual:
            relaxation = max(1.0 / 256.0, trial_relaxation * 0.90)
        else:
            relaxation = trial_relaxation

    raise RuntimeError(
        f"Dyson fixed-point iteration did not converge at z={z!r}; residual={residual:.3e}"
    )


def hermiticity_residual(matrix: np.ndarray) -> float:
    return frobenius(matrix - dagger(matrix)) / max(1.0, frobenius(matrix))


def solve_model(data: dict[str, Any]) -> dict[str, np.ndarray | float | int]:
    h0, h1, basis_site, site_slices = assemble_periodic_blocks(data)
    phases = _as_grid(data["phase_grid"], "phase_grid")
    energies = _as_grid(data["energy_grid"], "energy_grid")
    eta = float(data["eta"])
    if not math.isfinite(eta) or eta <= 0.0:
        raise ValueError("eta must be positive and finite")

    bands = np.empty((phases.size, h0.shape[0]), dtype=np.float64)
    max_hermiticity = hermiticity_residual(h0)
    for phase_index, phase in enumerate(phases):
        bloch = h0 + np.exp(1j * phase) * h1 + np.exp(-1j * phase) * dagger(h1)
        bands[phase_index] = np.linalg.eigvalsh(bloch).real

    device = data["device"]
    cells = int(device["cells"])
    hd = build_device(h0, h1, site_slices, device)
    max_hermiticity = max(max_hermiticity, hermiticity_residual(hd))
    contact_left = float(device["contact_scale_left"]) * dagger(h1)
    contact_right = float(device["contact_scale_right"]) * h1
    outward_left = dagger(h1)
    outward_right = h1

    n_energy = energies.size
    cell_size = h0.shape[0]
    sigma_left = np.empty((n_energy, cell_size, cell_size), dtype=np.complex128)
    sigma_right = np.empty_like(sigma_left)
    surface_residual_left = np.empty(n_energy, dtype=np.float64)
    surface_residual_right = np.empty(n_energy, dtype=np.float64)
    previous_left: np.ndarray | None = None
    previous_right: np.ndarray | None = None

    for energy_index, energy in enumerate(energies):
        z = complex(float(energy), eta)
        g_left, residual_left, _ = _fixed_point_surface(
            h0, outward_left, z, previous_left
        )
        g_right, residual_right, _ = _fixed_point_surface(
            h0, outward_right, z, previous_right
        )
        previous_left = g_left
        previous_right = g_right
        sigma_left[energy_index] = contact_left @ g_left @ dagger(contact_left)
        sigma_right[energy_index] = contact_right @ g_right @ dagger(contact_right)
        surface_residual_left[energy_index] = residual_left
        surface_residual_right[energy_index] = residual_right

    dos_total = np.empty(n_energy, dtype=np.float64)
    ldos_cells = np.empty((n_energy, cells), dtype=np.float64)
    transmission = np.empty(n_energy, dtype=np.float64)
    device_identity = np.eye(hd.shape[0], dtype=np.complex128)
    first = slice(0, cell_size)
    last = slice((cells - 1) * cell_size, cells * cell_size)

    for energy_index, energy in enumerate(energies):
        embedded = hd.copy()
        embedded[first, first] += sigma_left[energy_index]
        embedded[last, last] += sigma_right[energy_index]
        z = complex(float(energy), eta)
        try:
            green = np.linalg.solve(z * device_identity - embedded, device_identity)
        except np.linalg.LinAlgError as exc:
            raise RuntimeError(f"singular device resolvent at energy {energy!r}") from exc

        dos_total[energy_index] = -float(np.imag(np.trace(green))) / math.pi
        for cell in range(cells):
            block = slice(cell * cell_size, (cell + 1) * cell_size)
            ldos_cells[energy_index, cell] = -float(np.imag(np.trace(green[block, block]))) / math.pi

        gamma_left = 1j * (sigma_left[energy_index] - dagger(sigma_left[energy_index]))
        gamma_right = 1j * (sigma_right[energy_index] - dagger(sigma_right[energy_index]))
        green_first_last = green[first, last]
        caroli = gamma_left @ green_first_last @ gamma_right @ dagger(green_first_last)
        transmission[energy_index] = float(np.real(np.trace(caroli)))

    max_surface_residual = float(
        max(np.max(surface_residual_left), np.max(surface_residual_right))
    )
    return {
        "h0": np.asarray(h0, dtype=np.complex128),
        "h1": np.asarray(h1, dtype=np.complex128),
        "basis_site": np.asarray(basis_site, dtype=np.int64),
        "phases": np.asarray(phases, dtype=np.float64),
        "bands": np.asarray(bands, dtype=np.float64),
        "energies": np.asarray(energies, dtype=np.float64),
        "sigma_left": np.asarray(sigma_left, dtype=np.complex128),
        "sigma_right": np.asarray(sigma_right, dtype=np.complex128),
        "dos_total": np.asarray(dos_total, dtype=np.float64),
        "ldos_cells": np.asarray(ldos_cells, dtype=np.float64),
        "transmission": np.asarray(transmission, dtype=np.float64),
        "basis_size": int(h0.shape[0]),
        "device_cells": cells,
        "max_surface_residual": max_surface_residual,
        "max_hermiticity_residual": float(max_hermiticity),
    }


def write_outputs(
    output_directory: Path,
    result: dict[str, np.ndarray | float | int],
    model_id: str,
    input_sha256: str,
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_directory / "hamiltonian.npz",
        h0=result["h0"],
        h1=result["h1"],
        basis_site=result["basis_site"],
    )
    np.savez_compressed(
        output_directory / "self_energies.npz",
        energies=result["energies"],
        sigma_left=result["sigma_left"],
        sigma_right=result["sigma_right"],
    )
    np.savez_compressed(
        output_directory / "spectra.npz",
        phases=result["phases"],
        bands=result["bands"],
        energies=result["energies"],
        dos_total=result["dos_total"],
        ldos_cells=result["ldos_cells"],
        transmission=result["transmission"],
    )
    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "model_id": model_id,
        "input_sha256": input_sha256,
        "basis_size": result["basis_size"],
        "device_cells": result["device_cells"],
        "max_surface_residual": result["max_surface_residual"],
        "max_hermiticity_residual": result["max_hermiticity_residual"],
    }
    (output_directory / "diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def parse_arguments(arguments: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="public input JSON")
    parser.add_argument("--output", required=True, type=Path, help="output directory")
    return parser.parse_args(arguments)


def main(arguments: Iterable[str] | None = None) -> int:
    options = parse_arguments(arguments)
    raw_input = options.input.read_bytes()
    input_sha256 = hashlib.sha256(raw_input).hexdigest()
    data = json.loads(raw_input.decode("utf-8"))
    result = solve_model(data)
    write_outputs(options.output, result, str(data["model_id"]), input_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
