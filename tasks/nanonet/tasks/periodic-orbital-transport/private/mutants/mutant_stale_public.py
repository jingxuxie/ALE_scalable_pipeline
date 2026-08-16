#!/usr/bin/env python3
# MUTANT: reuse pristine-device settings for every input.
# Generated deterministically; do not repair this author-only negative control.
"""Clean-room solver for the periodic orbital transport task.

This program intentionally depends only on the Python standard library and
NumPy.  At runtime it reads the public JSON instance supplied with ``--input``
and does not import any project, author, or private-evaluator modules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


INPUT_SCHEMA = "periodic-orbital-device/v1"
OUTPUT_SCHEMA = "periodic-orbital-transport-output/v1"
ORBITAL_SETS = (("s",), ("s", "px", "py", "pz"))
HOPPING_PARAMETERS = ("ss_sigma", "sp_sigma", "pp_sigma", "pp_pi")
P_AXIS = {"px": 0, "py": 1, "pz": 2}
NEIGHBOR_EPSILON = 1.0e-12
DECIMATION_TOLERANCE = 1.0e-14
SURFACE_RESIDUAL_TOLERANCE = 5.0e-11
MAX_SURFACE_ITERATIONS = 256
MAX_INPUT_BYTES = 64 * 1024 * 1024
ROOT_FIELDS = (
    "schema_version",
    "model_id",
    "lattice_vector",
    "neighbor_cutoff",
    "species",
    "sites",
    "hoppings",
    "phase_grid",
    "energy_grid",
    "eta",
    "device",
)
DEVICE_FIELDS = (
    "cells",
    "site_potential",
    "bond_scale",
    "contact_scale_left",
    "contact_scale_right",
)
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a JSON object")
    return value


def _require_sequence(value: Any, where: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be a JSON array")
    return value


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where} must be a nonempty string")
    return value


def _finite_float(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a finite JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{where} must be finite")
    return result


def _positive_integer(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{where} must be a positive integer")
    return value


def _number_vector(value: Any, length: int, where: str) -> np.ndarray:
    items = _require_sequence(value, where)
    if len(items) != length:
        raise ValueError(f"{where} must contain exactly {length} numbers")
    return np.asarray(
        [_finite_float(item, f"{where}[{index}]") for index, item in enumerate(items)],
        dtype=np.float64,
    )


def _number_grid(value: Any, where: str) -> np.ndarray:
    items = _require_sequence(value, where)
    if not items:
        raise ValueError(f"{where} must not be empty")
    return np.asarray(
        [_finite_float(item, f"{where}[{index}]") for index, item in enumerate(items)],
        dtype=np.float64,
    )


def _required(obj: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in obj:
        raise ValueError(f"missing required field {where}.{key}")
    return obj[key]


def _require_exact_keys(
    obj: Mapping[str, Any], expected: Sequence[str], where: str
) -> None:
    wanted = set(expected)
    actual = set(obj)
    if actual != wanted:
        raise ValueError(
            f"{where} keys mismatch: missing={sorted(wanted - actual)}, "
            f"extra={sorted(actual - wanted)}"
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant {token!r} is not allowed")


def _canonical_pair(first: str, second: str) -> str:
    left, right = sorted((first, second))
    return f"{left}|{right}"


def load_instance(path: str | Path) -> dict[str, Any]:
    """Read and strictly validate a public instance JSON file."""

    input_path = Path(path)
    if input_path.is_symlink() or not input_path.is_file():
        raise ValueError(f"input must be a regular, non-symlink file: {input_path}")
    if input_path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    raw = input_path.read_bytes()
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"input is not valid UTF-8 JSON: {exc}") from exc
    root = _require_mapping(document, "input")
    _require_exact_keys(root, ROOT_FIELDS, "input")

    schema_version = _require_string(
        _required(root, "schema_version", "input"), "input.schema_version"
    )
    if schema_version != INPUT_SCHEMA:
        raise ValueError(
            f"input.schema_version must be {INPUT_SCHEMA!r}, got {schema_version!r}"
        )
    model_id = _require_string(_required(root, "model_id", "input"), "input.model_id")
    if len(model_id) > 128:
        raise ValueError("input.model_id must contain at most 128 characters")

    lattice_vector = _number_vector(
        _required(root, "lattice_vector", "input"), 3, "input.lattice_vector"
    )
    if np.linalg.norm(lattice_vector) == 0.0:
        raise ValueError("input.lattice_vector must be nonzero")
    neighbor_cutoff = _finite_float(
        _required(root, "neighbor_cutoff", "input"), "input.neighbor_cutoff"
    )
    if neighbor_cutoff <= 0.0:
        raise ValueError("input.neighbor_cutoff must be positive")

    species_document = _require_mapping(
        _required(root, "species", "input"), "input.species"
    )
    if not species_document:
        raise ValueError("input.species must not be empty")
    species: dict[str, dict[str, Any]] = {}
    for species_name, unvalidated in species_document.items():
        _require_string(species_name, "input.species key")
        if NAME_PATTERN.fullmatch(species_name) is None:
            raise ValueError(f"invalid species name {species_name!r}")
        entry = _require_mapping(unvalidated, f"input.species[{species_name!r}]")
        _require_exact_keys(
            entry, ("orbitals", "onsite"), f"input.species[{species_name!r}]"
        )
        orbitals_document = _require_sequence(
            _required(entry, "orbitals", f"input.species[{species_name!r}]"),
            f"input.species[{species_name!r}].orbitals",
        )
        orbitals = tuple(orbitals_document)
        if orbitals not in ORBITAL_SETS:
            raise ValueError(
                f"input.species[{species_name!r}].orbitals must be exactly "
                "['s'] or ['s', 'px', 'py', 'pz']"
            )
        onsite_document = _require_mapping(
            _required(entry, "onsite", f"input.species[{species_name!r}]"),
            f"input.species[{species_name!r}].onsite",
        )
        if set(onsite_document) != set(orbitals):
            raise ValueError(
                f"input.species[{species_name!r}].onsite keys must exactly match orbitals"
            )
        onsite = np.asarray(
            [
                _finite_float(
                    onsite_document[orbital],
                    f"input.species[{species_name!r}].onsite[{orbital!r}]",
                )
                for orbital in orbitals
            ],
            dtype=np.float64,
        )
        species[species_name] = {"orbitals": orbitals, "onsite": onsite}

    sites_document = _require_sequence(_required(root, "sites", "input"), "input.sites")
    if not sites_document:
        raise ValueError("input.sites must not be empty")
    sites: list[dict[str, Any]] = []
    site_ids: set[str] = set()
    for index, unvalidated in enumerate(sites_document):
        where = f"input.sites[{index}]"
        entry = _require_mapping(unvalidated, where)
        _require_exact_keys(entry, ("id", "species", "position"), where)
        site_id = _require_string(_required(entry, "id", where), f"{where}.id")
        if len(site_id) > 128:
            raise ValueError(f"{where}.id must contain at most 128 characters")
        if site_id in site_ids:
            raise ValueError(f"duplicate site id {site_id!r}")
        site_ids.add(site_id)
        species_name = _require_string(
            _required(entry, "species", where), f"{where}.species"
        )
        if NAME_PATTERN.fullmatch(species_name) is None:
            raise ValueError(f"{where}.species has invalid syntax")
        if species_name not in species:
            raise ValueError(f"{where}.species names undefined species {species_name!r}")
        position = _number_vector(_required(entry, "position", where), 3, f"{where}.position")
        sites.append({"id": site_id, "species": species_name, "position": position})

    hoppings_document = _require_mapping(
        _required(root, "hoppings", "input"), "input.hoppings"
    )
    if not hoppings_document:
        raise ValueError("input.hoppings must not be empty")
    hoppings: dict[str, dict[str, float]] = {}
    for pair_name, unvalidated in hoppings_document.items():
        _require_string(pair_name, "input.hoppings key")
        pieces = pair_name.split("|")
        if len(pieces) != 2 or not pieces[0] or not pieces[1]:
            raise ValueError(f"invalid hopping pair key {pair_name!r}")
        if pieces != sorted(pieces) or any(piece not in species for piece in pieces):
            raise ValueError(
                f"hopping key {pair_name!r} must be an alphabetically ordered defined species pair"
            )
        entry = _require_mapping(unvalidated, f"input.hoppings[{pair_name!r}]")
        if set(entry) != set(HOPPING_PARAMETERS):
            raise ValueError(
                f"input.hoppings[{pair_name!r}] must contain exactly "
                f"{list(HOPPING_PARAMETERS)!r}"
            )
        hoppings[pair_name] = {
            name: _finite_float(entry[name], f"input.hoppings[{pair_name!r}][{name!r}]")
            for name in HOPPING_PARAMETERS
        }

    phases = _number_grid(_required(root, "phase_grid", "input"), "input.phase_grid")
    energies = _number_grid(_required(root, "energy_grid", "input"), "input.energy_grid")
    eta = _finite_float(_required(root, "eta", "input"), "input.eta")
    if eta <= 0.0:
        raise ValueError("input.eta must be positive")

    device_document = _require_mapping(
        _required(root, "device", "input"), "input.device"
    )
    _require_exact_keys(device_document, DEVICE_FIELDS, "input.device")
    cells = _positive_integer(
        _required(device_document, "cells", "input.device"), "input.device.cells"
    )
    potential_document = _require_sequence(
        _required(device_document, "site_potential", "input.device"),
        "input.device.site_potential",
    )
    if len(potential_document) != cells:
        raise ValueError("input.device.site_potential must have one row per device cell")
    site_potential = np.empty((cells, len(sites)), dtype=np.float64)
    for cell, row in enumerate(potential_document):
        site_potential[cell] = _number_vector(
            row, len(sites), f"input.device.site_potential[{cell}]"
        )

    bond_document = _require_sequence(
        _required(device_document, "bond_scale", "input.device"),
        "input.device.bond_scale",
    )
    if len(bond_document) != cells - 1:
        raise ValueError("input.device.bond_scale must contain device.cells - 1 numbers")
    bond_scale = np.asarray(
        [
            _finite_float(value, f"input.device.bond_scale[{index}]")
            for index, value in enumerate(bond_document)
        ],
        dtype=np.float64,
    )
    contact_scale_left = _finite_float(
        _required(device_document, "contact_scale_left", "input.device"),
        "input.device.contact_scale_left",
    )
    contact_scale_right = _finite_float(
        _required(device_document, "contact_scale_right", "input.device"),
        "input.device.contact_scale_right",
    )
    if contact_scale_left <= 0.0 or contact_scale_right <= 0.0:
        raise ValueError("input.device contact scales must be strictly positive")

    return {
        "schema_version": schema_version,
        "model_id": model_id,
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "lattice_vector": lattice_vector,
        "neighbor_cutoff": neighbor_cutoff,
        "species": species,
        "sites": sites,
        "hoppings": hoppings,
        "phases": phases,
        "energies": energies,
        "eta": eta,
        "device": {
            "cells": cells,
            "site_potential": site_potential,
            "bond_scale": bond_scale,
            "contact_scale_left": contact_scale_left,
            "contact_scale_right": contact_scale_right,
        },
    }


def _slater_koster_block(
    row_orbitals: tuple[str, ...],
    column_orbitals: tuple[str, ...],
    direction: np.ndarray,
    parameters: Mapping[str, float],
) -> np.ndarray:
    block = np.empty((len(row_orbitals), len(column_orbitals)), dtype=np.float64)
    for row, row_orbital in enumerate(row_orbitals):
        for column, column_orbital in enumerate(column_orbitals):
            if row_orbital == "s" and column_orbital == "s":
                value = parameters["ss_sigma"]
            elif row_orbital == "s":
                value = direction[P_AXIS[column_orbital]] * parameters["sp_sigma"]
            elif column_orbital == "s":
                value = -direction[P_AXIS[row_orbital]] * parameters["sp_sigma"]
            else:
                row_axis = P_AXIS[row_orbital]
                column_axis = P_AXIS[column_orbital]
                product = direction[row_axis] * direction[column_axis]
                delta = 1.0 if row_axis == column_axis else 0.0
                value = (
                    product * parameters["pp_sigma"]
                    + (delta - product) * parameters["pp_pi"]
                )
            block[row, column] = value
    return block


def _assemble_hamiltonians(
    instance: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    species = instance["species"]
    sites = instance["sites"]
    hoppings = instance["hoppings"]

    basis_site_values: list[int] = []
    site_slices: list[slice] = []
    cursor = 0
    for site_index, site in enumerate(sites):
        width = len(species[site["species"]]["orbitals"])
        site_slices.append(slice(cursor, cursor + width))
        basis_site_values.extend([site_index] * width)
        cursor += width
    basis_site = np.asarray(basis_site_values, dtype=np.int64)
    h0 = np.zeros((cursor, cursor), dtype=np.complex128)
    h1 = np.zeros((cursor, cursor), dtype=np.complex128)

    for site_index, site in enumerate(sites):
        onsite = species[site["species"]]["onsite"]
        h0[site_slices[site_index], site_slices[site_index]] += np.diag(onsite)

    cutoff = instance["neighbor_cutoff"] + NEIGHBOR_EPSILON

    def coupling(row_index: int, column_index: int, displacement: np.ndarray) -> np.ndarray | None:
        distance = float(np.linalg.norm(displacement))
        if distance == 0.0 or distance > cutoff:
            return None
        row_species = sites[row_index]["species"]
        column_species = sites[column_index]["species"]
        pair_name = _canonical_pair(row_species, column_species)
        if pair_name not in hoppings:
            raise ValueError(
                f"missing hopping parameters for interacting species pair {pair_name!r}"
            )
        return _slater_koster_block(
            species[row_species]["orbitals"],
            species[column_species]["orbitals"],
            displacement / distance,
            hoppings[pair_name],
        )

    for row_index in range(len(sites)):
        for column_index in range(row_index + 1, len(sites)):
            displacement = sites[column_index]["position"] - sites[row_index]["position"]
            block = coupling(row_index, column_index, displacement)
            if block is None:
                continue
            row_slice = site_slices[row_index]
            column_slice = site_slices[column_index]
            h0[row_slice, column_slice] += block
            h0[column_slice, row_slice] += block.T

    lattice_vector = instance["lattice_vector"]
    for row_index in range(len(sites)):
        for column_index in range(len(sites)):
            displacement = (
                sites[column_index]["position"] + lattice_vector - sites[row_index]["position"]
            )
            block = coupling(row_index, column_index, displacement)
            if block is not None:
                h1[site_slices[row_index], site_slices[column_index]] += block

    return h0, h1, basis_site


def _relative_hermiticity_residual(matrix: np.ndarray) -> float:
    numerator = float(np.linalg.norm(matrix - matrix.conj().T, ord="fro"))
    denominator = max(1.0, float(np.linalg.norm(matrix, ord="fro")))
    return numerator / denominator


def _all_finite(*arrays: np.ndarray) -> bool:
    return all(np.all(np.isfinite(array)) for array in arrays)


def _surface_residual(
    z: complex, h0: np.ndarray, coupling: np.ndarray, green: np.ndarray
) -> float:
    identity = np.eye(h0.shape[0], dtype=np.complex128)
    effective_system = z * identity - h0 - coupling @ green @ coupling.conj().T
    numerator = float(np.linalg.norm(effective_system @ green - identity, ord="fro"))
    denominator = max(
        float(np.linalg.norm(identity, ord="fro")),
        float(np.linalg.norm(effective_system, ord="fro"))
        * float(np.linalg.norm(green, ord="fro")),
    )
    return numerator / denominator


def _surface_green(
    z: complex, h0: np.ndarray, coupling: np.ndarray
) -> tuple[np.ndarray, int, float]:
    """Solve g=[zI-H0-B g B^H]^-1 by Lopez-Sancho decimation."""

    size = h0.shape[0]
    identity = np.eye(size, dtype=np.complex128)

    # Work in dimensionless units.  This avoids convergence decisions that
    # change merely because an otherwise identical instance uses another
    # energy scale.
    scale = max(
        abs(z),
        float(np.linalg.norm(h0, ord="fro")),
        float(np.linalg.norm(coupling, ord="fro")),
        np.finfo(np.float64).tiny,
    )
    z_scaled = z / scale
    h_scaled = h0 / scale
    original_coupling = coupling / scale

    surface_onsite = h_scaled.copy()
    bulk_onsite = h_scaled.copy()
    alpha = original_coupling.copy()
    beta = original_coupling.conj().T.copy()
    last_residual = math.inf

    for iteration in range(1, MAX_SURFACE_ITERATIONS + 1):
        system = z_scaled * identity - bulk_onsite
        try:
            inverse_alpha = np.linalg.solve(system, alpha)
            inverse_beta = np.linalg.solve(system, beta)
        except np.linalg.LinAlgError as exc:
            raise RuntimeError(
                f"surface decimation encountered a singular bulk system at iteration {iteration}"
            ) from exc

        surface_update = alpha @ inverse_beta
        bulk_update = surface_update + beta @ inverse_alpha
        new_surface_onsite = surface_onsite + surface_update
        new_bulk_onsite = bulk_onsite + bulk_update
        new_alpha = alpha @ inverse_alpha
        new_beta = beta @ inverse_beta

        try:
            green_scaled = np.linalg.solve(
                z_scaled * identity - new_surface_onsite, identity
            )
        except np.linalg.LinAlgError as exc:
            raise RuntimeError(
                f"surface decimation encountered a singular surface system at iteration {iteration}"
            ) from exc

        effective_system = (
            z_scaled * identity
            - h_scaled
            - original_coupling @ green_scaled @ original_coupling.conj().T
        )
        residual_numerator = float(
            np.linalg.norm(effective_system @ green_scaled - identity, ord="fro")
        )
        residual_denominator = max(
            float(np.linalg.norm(identity, ord="fro")),
            float(np.linalg.norm(effective_system, ord="fro"))
            * float(np.linalg.norm(green_scaled, ord="fro")),
        )
        last_residual = residual_numerator / residual_denominator

        energy_scale = max(
            abs(z_scaled),
            float(np.linalg.norm(h_scaled, ord="fro")),
            float(np.linalg.norm(original_coupling, ord="fro")),
            float(np.linalg.norm(new_surface_onsite, ord="fro")),
            float(np.linalg.norm(new_bulk_onsite, ord="fro")),
            np.finfo(np.float64).tiny,
        )
        decimation_error = max(
            float(np.linalg.norm(surface_update, ord="fro")),
            float(np.linalg.norm(bulk_update, ord="fro")),
            float(np.linalg.norm(new_alpha, ord="fro")),
            float(np.linalg.norm(new_beta, ord="fro")),
        ) / energy_scale

        if not _all_finite(
            new_surface_onsite,
            new_bulk_onsite,
            new_alpha,
            new_beta,
            green_scaled,
            np.asarray([last_residual, decimation_error]),
        ):
            raise RuntimeError(
                f"surface decimation produced a non-finite value at iteration {iteration}"
            )

        # All recurrence updates are simultaneous and use the old values.
        surface_onsite = new_surface_onsite
        bulk_onsite = new_bulk_onsite
        alpha = new_alpha
        beta = new_beta

        if (
            decimation_error <= DECIMATION_TOLERANCE
            and last_residual <= SURFACE_RESIDUAL_TOLERANCE
        ):
            green = green_scaled / scale
            return green, iteration, _surface_residual(z, h0, coupling, green)

    raise RuntimeError(
        "surface decimation did not converge in "
        f"{MAX_SURFACE_ITERATIONS} iterations (residual={last_residual:.3e})"
    )


def _device_hamiltonian(
    h0: np.ndarray,
    h1: np.ndarray,
    basis_site: np.ndarray,
    device: Mapping[str, Any],
) -> np.ndarray:
    basis_size = h0.shape[0]
    cells = device["cells"]
    result = np.zeros((basis_size * cells, basis_size * cells), dtype=np.complex128)
    for cell in range(cells):
        block = h0.copy()
        block[np.diag_indices(basis_size)] += device["site_potential"][cell, basis_site]
        cell_slice = slice(cell * basis_size, (cell + 1) * basis_size)
        result[cell_slice, cell_slice] = block
    for cell, scale in enumerate(device["bond_scale"]):
        left = slice(cell * basis_size, (cell + 1) * basis_size)
        right = slice((cell + 1) * basis_size, (cell + 2) * basis_size)
        coupling = scale * h1
        result[left, right] = coupling
        result[right, left] = coupling.conj().T
    return result


def solve_instance(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Compute all arrays in the participant output contract."""

    h0, h1, basis_site = _assemble_hamiltonians(instance)
    basis_size = h0.shape[0]
    phases = instance["phases"].copy()
    energies = instance["energies"].copy()
    bands = np.empty((len(phases), basis_size), dtype=np.float64)
    h0_hermiticity = _relative_hermiticity_residual(h0)
    for index, phase in enumerate(phases):
        bloch = (
            h0
            + h1 * np.exp(1.0j * phase)
            + h1.conj().T * np.exp(-1.0j * phase)
        )
        bands[index] = np.linalg.eigvalsh(bloch)

    device = instance["device"]
    cells = device["cells"]
    h_device = _device_hamiltonian(h0, h1, basis_site, device)
    max_hermiticity = max(
        h0_hermiticity, _relative_hermiticity_residual(h_device)
    )
    device_size = basis_size * cells
    identity_device = np.eye(device_size, dtype=np.complex128)

    sigma_left = np.empty(
        (len(energies), basis_size, basis_size), dtype=np.complex128
    )
    sigma_right = np.empty_like(sigma_left)
    dos_total = np.empty(len(energies), dtype=np.float64)
    ldos_cells = np.empty((len(energies), cells), dtype=np.float64)
    transmission = np.empty(len(energies), dtype=np.float64)

    lead_coupling_left = h1.T
    lead_coupling_right = h1
    contact_left = device["contact_scale_left"] * h1.T
    contact_right = device["contact_scale_right"] * h1
    max_surface_residual = 0.0

    for energy_index, energy in enumerate(energies):
        z = complex(energy, instance["eta"])
        try:
            green_left, _, residual_left = _surface_green(
                z, h0, lead_coupling_left
            )
            green_right, _, residual_right = _surface_green(
                z, h0, lead_coupling_right
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"surface Green function failed at energy_grid[{energy_index}]={energy}: {exc}"
            ) from exc

        left = contact_left @ green_left @ contact_left.conj().T
        right = contact_right @ green_right @ contact_right.conj().T
        sigma_left[energy_index] = left
        sigma_right[energy_index] = right
        max_surface_residual = max(
            max_surface_residual, residual_left, residual_right
        )

        resolvent = z * identity_device - h_device
        resolvent[:basis_size, :basis_size] -= left
        resolvent[-basis_size:, -basis_size:] -= right
        try:
            green_device = np.linalg.solve(resolvent, identity_device)
        except np.linalg.LinAlgError as exc:
            raise RuntimeError(
                f"device Green function is singular at energy_grid[{energy_index}]={energy}"
            ) from exc

        dos_total[energy_index] = -float(np.imag(np.trace(green_device))) / math.pi
        for cell in range(cells):
            cell_slice = slice(cell * basis_size, (cell + 1) * basis_size)
            ldos_cells[energy_index, cell] = (
                -float(np.imag(np.trace(green_device[cell_slice, cell_slice])))
                / math.pi
            )

        gamma_left = 1.0j * (left - left.conj().T)
        gamma_right = 1.0j * (right - right.conj().T)
        green_first_last = green_device[:basis_size, -basis_size:]
        transmission[energy_index] = float(
            np.real(
                np.trace(
                    gamma_left
                    @ green_first_last
                    @ gamma_right
                    @ green_first_last.conj().T
                )
            )
        )

    arrays = (
        h0,
        h1,
        basis_site,
        phases,
        bands,
        energies,
        sigma_left,
        sigma_right,
        dos_total,
        ldos_cells,
        transmission,
    )
    if not _all_finite(*arrays):
        raise RuntimeError("solver produced a non-finite output")

    return {
        "hamiltonian": {"h0": h0, "h1": h1, "basis_site": basis_site},
        "self_energies": {
            "energies": energies,
            "sigma_left": sigma_left,
            "sigma_right": sigma_right,
        },
        "spectra": {
            "phases": phases,
            "bands": bands,
            "energies": energies,
            "dos_total": dos_total,
            "ldos_cells": ldos_cells,
            "transmission": transmission,
        },
        "diagnostics": {
            "schema_version": OUTPUT_SCHEMA,
            "model_id": instance["model_id"],
            "input_sha256": instance["input_sha256"],
            "basis_size": int(basis_size),
            "device_cells": int(cells),
            "max_surface_residual": float(max_surface_residual),
            "max_hermiticity_residual": float(max_hermiticity),
        },
    }


def reference_arrays(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility name for verification code that needs reference arrays."""

    return solve_instance(instance)


def write_outputs(output_dir: str | Path, result: Mapping[str, Any]) -> None:
    """Write exactly the four required artifacts and their disclosed keys."""

    output_path = Path(output_dir)
    if output_path.is_symlink():
        raise ValueError(f"output path must not be a symlink: {output_path}")
    if output_path.exists() and not output_path.is_dir():
        raise ValueError(f"output path exists and is not a directory: {output_path}")
    output_path.mkdir(parents=True, exist_ok=True)

    hamiltonian = {
        key: np.ascontiguousarray(value) for key, value in result["hamiltonian"].items()
    }
    self_energies = {
        key: np.ascontiguousarray(value) for key, value in result["self_energies"].items()
    }
    spectra = {
        key: np.ascontiguousarray(value) for key, value in result["spectra"].items()
    }
    np.savez(output_path / "hamiltonian.npz", **hamiltonian)
    np.savez(output_path / "self_energies.npz", **self_energies)
    np.savez(output_path / "spectra.npz", **spectra)
    with (output_path / "diagnostics.json").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        json.dump(result["diagnostics"], stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Solve one periodic orbital transport JSON instance."
    )
    parser.add_argument("--input", required=True, help="path to the public input JSON")
    parser.add_argument("--output", required=True, help="directory for required artifacts")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    try:
        instance = load_instance(arguments.input)
        instance["device"]["site_potential"].fill(0.0)
        instance["device"]["bond_scale"].fill(1.0)
        instance["device"]["contact_scale_left"] = 1.0
        instance["device"]["contact_scale_right"] = 1.0
        result = solve_instance(instance)
        write_outputs(arguments.output, result)
    except (OSError, ValueError, RuntimeError, np.linalg.LinAlgError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
