#!/usr/bin/env python3
"""Generate deterministic public and private assets for this task.

The generator deliberately imports the privileged numerical implementation by
resolved file path.  It never imports participant code or NanoNET itself.
Measured wall-clock timings are printed to stdout; the generated manifest only
contains deterministic workload metadata so repeated runs are byte-stable.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np


TASK_ROOT = Path(__file__).resolve().parents[2]
INPUT_SCHEMA_VERSION = "periodic-orbital-device/v1"
MANIFEST_SCHEMA_VERSION = "periodic-orbital-assets-manifest/v1"
REFERENCE_FILES = (
    "hamiltonian.npz",
    "self_energies.npz",
    "spectra.npz",
    "diagnostics.json",
)

# Each case, including each member of a metamorphic pair, has a distinct
# literal seed.  Transform seeds control only their documented transform.
SEED_PUBLIC_ANALYTIC = 101_003
SEED_PUBLIC_ROTATED = 101_021
SEED_HIDDEN_ROTATION = 201_007
SEED_HIDDEN_PERMUTATION = 201_029
SEED_HIDDEN_CUTOFF = 201_061
SEED_HIDDEN_HETEROGENEOUS = 201_089
SEED_HIDDEN_WEAK_CONTACT = 201_107
SEED_HIDDEN_STRONG_DEFECT = 201_133
SEED_HIDDEN_ENERGY_BASE = 201_161
SEED_HIDDEN_ENERGY_SHIFT = 201_193
SEED_HIDDEN_SITE_BASE = 201_217
SEED_HIDDEN_SITE_PERMUTATION = 201_239

ALL_LITERAL_SEEDS = (
    SEED_PUBLIC_ANALYTIC,
    SEED_PUBLIC_ROTATED,
    SEED_HIDDEN_ROTATION,
    SEED_HIDDEN_PERMUTATION,
    SEED_HIDDEN_CUTOFF,
    SEED_HIDDEN_HETEROGENEOUS,
    SEED_HIDDEN_WEAK_CONTACT,
    SEED_HIDDEN_STRONG_DEFECT,
    SEED_HIDDEN_ENERGY_BASE,
    SEED_HIDDEN_ENERGY_SHIFT,
    SEED_HIDDEN_SITE_BASE,
    SEED_HIDDEN_SITE_PERMUTATION,
)


@dataclass(frozen=True)
class Case:
    instance: dict[str, Any]
    visibility: str
    family: str
    seed: int
    seed_label: str


def _load_science(task_root: Path):
    task_root = task_root.resolve(strict=True)
    science_path = (task_root / "private" / "grader" / "science.py").resolve(strict=True)
    try:
        science_path.relative_to(task_root)
    except ValueError as exc:
        raise RuntimeError(f"trusted science module escapes task root: {science_path}") from exc
    spec = importlib.util.spec_from_file_location(
        "periodic_orbital_transport_private_science", science_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import trusted science module: {science_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _round(value: float, digits: int = 12) -> float:
    return round(float(value), digits)


def _rounded_vector(values: np.ndarray | Sequence[float], digits: int = 12) -> list[float]:
    return [_round(value, digits) for value in values]


def _write_json(path: Path, document: Any) -> str:
    payload = (
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _fixed_rotation() -> np.ndarray:
    """Return a non-axis-aligned proper rotation with rational entries."""

    rotation_z = np.asarray(
        [[3.0 / 5.0, -4.0 / 5.0, 0.0], [4.0 / 5.0, 3.0 / 5.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    rotation_y = np.asarray(
        [[5.0 / 13.0, 0.0, 12.0 / 13.0], [0.0, 1.0, 0.0], [-12.0 / 13.0, 0.0, 5.0 / 13.0]],
        dtype=np.float64,
    )
    return rotation_z @ rotation_y


def _random_rotation(rng: np.random.Generator) -> np.ndarray:
    axis = rng.normal(size=3)
    axis /= np.linalg.norm(axis)
    angle = float(rng.uniform(0.47, 1.31))
    x, y, z = axis
    cross = np.asarray([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return (
        math.cos(angle) * np.eye(3)
        + math.sin(angle) * cross
        + (1.0 - math.cos(angle)) * np.outer(axis, axis)
    )


def _rotate_geometry(
    lattice: Sequence[float], positions: Sequence[Sequence[float]], rotation: np.ndarray
) -> tuple[list[float], list[list[float]]]:
    rotated_lattice = _rounded_vector(rotation @ np.asarray(lattice, dtype=np.float64))
    rotated_positions = [
        _rounded_vector(rotation @ np.asarray(position, dtype=np.float64))
        for position in positions
    ]
    return rotated_lattice, rotated_positions


def _species_s(onsite: float) -> dict[str, Any]:
    return {"orbitals": ["s"], "onsite": {"s": _round(onsite)}}


def _species_sp(onsite: Sequence[float]) -> dict[str, Any]:
    if len(onsite) != 4:
        raise ValueError("s/p species onsite data must have four values")
    return {
        "orbitals": ["s", "px", "py", "pz"],
        "onsite": {
            "s": _round(onsite[0]),
            "px": _round(onsite[1]),
            "py": _round(onsite[2]),
            "pz": _round(onsite[3]),
        },
    }


def _hoppings(
    species_names: Sequence[str], rng: np.random.Generator, *, scale: float = 1.0
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    ordered = sorted(species_names)
    for first_index, first in enumerate(ordered):
        for second_index in range(first_index, len(ordered)):
            second = ordered[second_index]
            pair_factor = 1.0 + 0.035 * (first_index + second_index)
            result[f"{first}|{second}"] = {
                "ss_sigma": _round(
                    scale * pair_factor * (-0.82 + rng.uniform(-0.11, 0.11))
                ),
                "sp_sigma": _round(
                    scale * pair_factor * (0.67 + rng.uniform(-0.09, 0.09))
                ),
                "pp_sigma": _round(
                    scale * pair_factor * (0.93 + rng.uniform(-0.12, 0.12))
                ),
                "pp_pi": _round(
                    scale * pair_factor * (-0.29 + rng.uniform(-0.06, 0.06))
                ),
            }
    return result


def _phase_grid(
    rng: np.random.Generator, count: int, *, ordered: bool = False
) -> list[float]:
    if count < 7:
        raise ValueError("phase grid is too short for the intended fixtures")
    phases = np.linspace(-math.pi, math.pi, count, dtype=np.float64)
    if not ordered:
        phases[1:-1] += rng.uniform(-0.13, 0.13, count - 2)
        phases[count // 2] = 0.0
        phases[-2] = phases[2]
        phases = phases[rng.permutation(count)]
    return _rounded_vector(phases)


def _energy_grid(
    rng: np.random.Generator,
    count: int,
    lower: float,
    upper: float,
    *,
    ordered: bool = False,
) -> list[float]:
    if count < 9:
        raise ValueError("energy grid is too short for the intended fixtures")
    energies = np.linspace(lower, upper, count, dtype=np.float64)
    if not ordered:
        spacing = (upper - lower) / (count - 1)
        energies[1:-1] += rng.uniform(-0.19 * spacing, 0.19 * spacing, count - 2)
        energies[-2] = energies[3]
        energies = energies[rng.permutation(count)]
    return _rounded_vector(energies)


def _device(
    rng: np.random.Generator,
    cells: int,
    site_count: int,
    *,
    potential_scale: float = 0.18,
    contact_left: float | None = None,
    contact_right: float | None = None,
) -> dict[str, Any]:
    potentials = rng.normal(0.0, potential_scale, size=(cells, site_count))
    cell_profile = np.linspace(-0.55, 0.55, cells, dtype=np.float64)[:, None]
    site_profile = np.linspace(-0.08, 0.08, site_count, dtype=np.float64)[None, :]
    potentials += cell_profile * site_profile
    bonds = rng.uniform(0.78, 1.24, cells - 1)
    left = float(rng.uniform(0.72, 1.16)) if contact_left is None else contact_left
    right = float(rng.uniform(0.72, 1.16)) if contact_right is None else contact_right
    return {
        "cells": cells,
        "site_potential": [
            _rounded_vector(row) for row in np.asarray(potentials, dtype=np.float64)
        ],
        "bond_scale": _rounded_vector(bonds),
        "contact_scale_left": _round(left),
        "contact_scale_right": _round(right),
    }


def _instance(
    *,
    model_id: str,
    lattice: Sequence[float],
    cutoff: float,
    species: dict[str, dict[str, Any]],
    site_records: Sequence[tuple[str, str, Sequence[float]]],
    hoppings: dict[str, dict[str, float]],
    phases: Sequence[float],
    energies: Sequence[float],
    eta: float,
    device: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "model_id": model_id,
        "lattice_vector": _rounded_vector(lattice, 15),
        "neighbor_cutoff": _round(cutoff, 15),
        "species": species,
        "sites": [
            {
                "id": site_id,
                "species": species_name,
                "position": _rounded_vector(position, 15),
            }
            for site_id, species_name, position in site_records
        ],
        "hoppings": hoppings,
        "phase_grid": [_round(value, 12) for value in phases],
        "energy_grid": [_round(value, 12) for value in energies],
        "eta": _round(eta, 12),
        "device": device,
    }


def _public_analytic() -> Case:
    rng = np.random.default_rng(SEED_PUBLIC_ANALYTIC)
    species = {"A": _species_s(-0.38), "B": _species_s(0.54)}
    hoppings = {
        "A|A": {"ss_sigma": -0.57, "sp_sigma": 0.41, "pp_sigma": 0.72, "pp_pi": -0.19},
        "A|B": {"ss_sigma": -1.04, "sp_sigma": 0.63, "pp_sigma": 0.88, "pp_pi": -0.27},
        "B|B": {"ss_sigma": -0.46, "sp_sigma": 0.52, "pp_sigma": 0.77, "pp_pi": -0.23},
    }
    instance = _instance(
        model_id="public_scalar_diatomic",
        lattice=[2.55, 0.0, 0.0],
        cutoff=2.60,
        species=species,
        site_records=[("left_A", "A", [0.0, 0.0, 0.0]), ("right_B", "B", [1.18, 0.0, 0.0])],
        hoppings=hoppings,
        phases=_phase_grid(rng, 13, ordered=True),
        energies=_energy_grid(rng, 21, -3.9, 3.9, ordered=True),
        eta=0.08,
        device=_device(rng, 4, 2, potential_scale=0.11, contact_left=0.91, contact_right=1.08),
    )
    return Case(
        instance,
        "public",
        "analytic_scalar_diatomic",
        SEED_PUBLIC_ANALYTIC,
        "public-analytic-scalar-diatomic-101003",
    )


def _public_rotated() -> Case:
    rng = np.random.default_rng(SEED_PUBLIC_ROTATED)
    species = {
        "P": _species_sp([-0.31, 0.48, 0.73, 1.02]),
        "Q": _species_sp([0.22, 0.62, 0.91, 1.17]),
        "S": _species_s(-0.67),
    }
    lattice, positions = _rotate_geometry(
        [2.42, 0.11, -0.07],
        [[1.48, 0.27, -0.13], [0.0, 0.0, 0.0], [0.73, -0.19, 0.23]],
        _fixed_rotation(),
    )
    instance = _instance(
        model_id="public_rotated_multispecies",
        lattice=lattice,
        cutoff=float(np.linalg.norm(lattice)) + 0.17,
        species=species,
        site_records=[("site_q", "Q", positions[0]), ("site_p", "P", positions[1]), ("site_s", "S", positions[2])],
        hoppings=_hoppings(species, rng, scale=1.03),
        phases=_phase_grid(rng, 17),
        energies=_energy_grid(rng, 25, -5.1, 5.4),
        eta=0.07,
        device=_device(rng, 5, 3, potential_scale=0.17),
    )
    return Case(
        instance,
        "public",
        "rotated_permuted_multispecies_s_sp",
        SEED_PUBLIC_ROTATED,
        "public-rotated-permuted-multispecies-101021",
    )


def _hidden_rotation() -> Case:
    rng = np.random.default_rng(SEED_HIDDEN_ROTATION)
    species = {
        "L": _species_sp([-0.44, 0.39, 0.78, 1.11]),
        "R": _species_sp([0.17, 0.55, 0.89, 1.24]),
    }
    lattice, positions = _rotate_geometry(
        [2.31, 0.18, 0.12],
        [[0.0, 0.0, 0.0], [1.02, 0.31, -0.18]],
        _random_rotation(rng),
    )
    instance = _instance(
        model_id="hidden_ordinary_rotation",
        lattice=lattice,
        cutoff=float(np.linalg.norm(lattice)) + 0.14,
        species=species,
        site_records=[("rot_left", "L", positions[0]), ("rot_right", "R", positions[1])],
        hoppings=_hoppings(species, rng, scale=0.94),
        phases=_phase_grid(rng, 19),
        energies=_energy_grid(rng, 27, -5.0, 5.2),
        eta=0.06,
        device=_device(rng, 5, 2, potential_scale=0.16),
    )
    return Case(
        instance,
        "hidden",
        "ordinary_rotation",
        SEED_HIDDEN_ROTATION,
        "hidden-ordinary-rotation-201007",
    )


def _hidden_permutation() -> Case:
    rng = np.random.default_rng(SEED_HIDDEN_PERMUTATION)
    species = {
        "M": _species_sp([-0.53, 0.31, 0.66, 0.95]),
        "N": _species_s(0.28),
        "O": _species_s(-0.14),
    }
    natural_sites = [
        ("middle_id", "M", [0.0, 0.0, 0.0]),
        ("first_id", "N", [0.72, 0.26, -0.17]),
        ("last_id", "O", [1.51, -0.22, 0.19]),
    ]
    permutation = rng.permutation(len(natural_sites)).tolist()
    if permutation == list(range(len(natural_sites))):
        permutation = [2, 0, 1]
    sites = [natural_sites[index] for index in permutation]
    lattice = [2.39, -0.16, 0.21]
    instance = _instance(
        model_id="hidden_ordinary_permutation",
        lattice=lattice,
        cutoff=float(np.linalg.norm(lattice)) + 0.16,
        species=species,
        site_records=sites,
        hoppings=_hoppings(species, rng, scale=1.08),
        phases=_phase_grid(rng, 15),
        energies=_energy_grid(rng, 23, -4.7, 4.9),
        eta=0.09,
        device=_device(rng, 6, 3, potential_scale=0.21),
    )
    return Case(
        instance,
        "hidden",
        "ordinary_site_permutation",
        SEED_HIDDEN_PERMUTATION,
        "hidden-ordinary-permutation-201029",
    )


def _hidden_cutoff_edge() -> Case:
    rng = np.random.default_rng(SEED_HIDDEN_CUTOFF)
    species = {"Edge": _species_s(0.13)}
    instance = _instance(
        model_id="hidden_cutoff_edge",
        lattice=[2.3, 0.0, 0.0],
        cutoff=2.3,
        species=species,
        site_records=[
            ("origin", "Edge", [0.0, 0.0, 0.0]),
            ("inside_epsilon", "Edge", [0.0, 2.3000000000005, 0.0]),
            ("outside_epsilon", "Edge", [0.0, -2.3000000000015, 0.0]),
        ],
        hoppings=_hoppings(species, rng, scale=0.87),
        phases=_phase_grid(rng, 11),
        energies=_energy_grid(rng, 19, -3.2, 3.4),
        eta=0.12,
        device=_device(rng, 5, 3, potential_scale=0.13),
    )
    return Case(
        instance,
        "hidden",
        "neighbor_cutoff_epsilon_edge",
        SEED_HIDDEN_CUTOFF,
        "hidden-cutoff-edge-201061",
    )


def _hidden_heterogeneous() -> Case:
    rng = np.random.default_rng(SEED_HIDDEN_HETEROGENEOUS)
    species = {
        "Core": _species_sp([-0.61, 0.34, 0.69, 1.08]),
        "Dot": _species_s(0.43),
        "Shell": _species_sp([0.08, 0.51, 0.82, 1.21]),
    }
    lattice, positions = _rotate_geometry(
        [2.58, 0.09, 0.14],
        [[0.0, 0.0, 0.0], [0.57, 0.24, -0.16], [1.24, -0.18, 0.27], [1.91, 0.16, -0.11]],
        _fixed_rotation().T,
    )
    instance = _instance(
        model_id="hidden_heterogeneous_s_sp",
        lattice=lattice,
        cutoff=float(np.linalg.norm(lattice)) + 0.15,
        species=species,
        site_records=[
            ("core", "Core", positions[0]),
            ("dot_a", "Dot", positions[1]),
            ("shell", "Shell", positions[2]),
            ("dot_b", "Dot", positions[3]),
        ],
        hoppings=_hoppings(species, rng, scale=0.98),
        phases=_phase_grid(rng, 23),
        energies=_energy_grid(rng, 29, -5.4, 5.6),
        eta=0.08,
        device=_device(rng, 6, 4, potential_scale=0.19),
    )
    return Case(
        instance,
        "hidden",
        "heterogeneous_s_sp_basis",
        SEED_HIDDEN_HETEROGENEOUS,
        "hidden-heterogeneous-s-sp-201089",
    )


def _hidden_weak_contact() -> Case:
    rng = np.random.default_rng(SEED_HIDDEN_WEAK_CONTACT)
    species = {"Lead": _species_sp([-0.26, 0.42, 0.77, 1.05])}
    lattice = [2.43, -0.13, 0.17]
    instance = _instance(
        model_id="hidden_weak_contact",
        lattice=lattice,
        cutoff=float(np.linalg.norm(lattice)) + 0.18,
        species=species,
        site_records=[
            ("lead_a", "Lead", [0.0, 0.0, 0.0]),
            ("lead_b", "Lead", [1.09, 0.29, -0.21]),
        ],
        hoppings=_hoppings(species, rng, scale=1.01),
        phases=_phase_grid(rng, 21),
        energies=_energy_grid(rng, 31, -4.9, 5.1),
        eta=0.05,
        device=_device(
            rng,
            7,
            2,
            potential_scale=0.12,
            contact_left=0.14,
            contact_right=0.19,
        ),
    )
    return Case(
        instance,
        "hidden",
        "weak_asymmetric_contacts",
        SEED_HIDDEN_WEAK_CONTACT,
        "hidden-weak-contact-201107",
    )


def _hidden_strong_defect() -> Case:
    rng = np.random.default_rng(SEED_HIDDEN_STRONG_DEFECT)
    species = {
        "A": _species_sp([-0.49, 0.36, 0.71, 1.09]),
        "B": _species_s(0.37),
        "C": _species_sp([0.12, 0.59, 0.88, 1.26]),
    }
    lattice = [2.51, 0.18, -0.09]
    device = _device(rng, 7, 3, potential_scale=0.22, contact_left=1.21, contact_right=0.87)
    device["site_potential"][3][1] = 3.75
    device["site_potential"][4][0] = -1.85
    device["bond_scale"][2] = 0.34
    device["bond_scale"][3] = 1.47
    instance = _instance(
        model_id="hidden_strong_defect",
        lattice=lattice,
        cutoff=float(np.linalg.norm(lattice)) + 0.13,
        species=species,
        site_records=[
            ("defect_left", "A", [0.0, 0.0, 0.0]),
            ("defect_center", "B", [0.82, -0.24, 0.19]),
            ("defect_right", "C", [1.62, 0.22, -0.16]),
        ],
        hoppings=_hoppings(species, rng, scale=1.06),
        phases=_phase_grid(rng, 19),
        energies=_energy_grid(rng, 31, -6.0, 6.2),
        eta=0.11,
        device=device,
    )
    return Case(
        instance,
        "hidden",
        "strong_local_defect_and_bond_contrast",
        SEED_HIDDEN_STRONG_DEFECT,
        "hidden-strong-defect-201133",
    )


def _hidden_energy_pair() -> tuple[Case, Case, dict[str, Any]]:
    rng = np.random.default_rng(SEED_HIDDEN_ENERGY_BASE)
    species = {
        "Mix": _species_sp([-0.57, 0.28, 0.63, 0.98]),
        "Solo": _species_s(0.24),
    }
    lattice = [2.36, 0.15, 0.20]
    base = _instance(
        model_id="hidden_energy_shift_base",
        lattice=lattice,
        cutoff=float(np.linalg.norm(lattice)) + 0.16,
        species=species,
        site_records=[("mix", "Mix", [0.0, 0.0, 0.0]), ("solo", "Solo", [1.04, -0.27, 0.16])],
        hoppings=_hoppings(species, rng, scale=0.96),
        phases=_phase_grid(rng, 19),
        energies=_energy_grid(rng, 25, -4.8, 5.0),
        eta=0.07,
        device=_device(rng, 5, 2, potential_scale=0.18),
    )
    transform_rng = np.random.default_rng(SEED_HIDDEN_ENERGY_SHIFT)
    delta = _round(transform_rng.uniform(1.15, 1.55), 9)
    shifted = copy.deepcopy(base)
    shifted["model_id"] = "hidden_energy_shift_shifted"
    for species_record in shifted["species"].values():
        for orbital in species_record["onsite"]:
            species_record["onsite"][orbital] = _round(
                species_record["onsite"][orbital] + delta
            )
    shifted["energy_grid"] = [_round(energy + delta) for energy in base["energy_grid"]]
    base_case = Case(
        base,
        "hidden",
        "energy_shift_metamorphic_base",
        SEED_HIDDEN_ENERGY_BASE,
        "hidden-energy-shift-base-201161",
    )
    shifted_case = Case(
        shifted,
        "hidden",
        "energy_shift_metamorphic_shifted",
        SEED_HIDDEN_ENERGY_SHIFT,
        "hidden-energy-shift-transform-201193",
    )
    relation = {
        "id": "global_energy_shift",
        "base_model_id": base["model_id"],
        "transformed_model_id": shifted["model_id"],
        "energy_shift": delta,
        "expected": {
            "bands": "transformed equals base plus energy_shift",
            "h0": "transformed equals base plus energy_shift times identity",
            "h1": "unchanged",
            "self_energies_and_transport_observables": "unchanged at correspondingly shifted energy grid",
        },
    }
    return base_case, shifted_case, relation


def _hidden_site_permutation_pair() -> tuple[Case, Case, dict[str, Any]]:
    rng = np.random.default_rng(SEED_HIDDEN_SITE_BASE)
    species = {
        "X": _species_sp([-0.63, 0.24, 0.58, 0.91]),
        "Y": _species_sp([0.06, 0.47, 0.83, 1.19]),
    }
    lattice = [2.64, -0.14, 0.19]
    base = _instance(
        model_id="hidden_site_permutation_base",
        lattice=lattice,
        cutoff=float(np.linalg.norm(lattice)) + 0.17,
        species=species,
        site_records=[
            ("site_x0", "X", [0.0, 0.0, 0.0]),
            ("site_y1", "Y", [0.83, 0.26, -0.18]),
            ("site_x2", "X", [1.71, -0.23, 0.16]),
        ],
        hoppings=_hoppings(species, rng, scale=1.02),
        phases=_phase_grid(rng, 21),
        energies=_energy_grid(rng, 27, -5.8, 5.9),
        eta=0.09,
        device=_device(rng, 4, 3, potential_scale=0.20),
    )
    transform_rng = np.random.default_rng(SEED_HIDDEN_SITE_PERMUTATION)
    permutation = transform_rng.permutation(len(base["sites"])).tolist()
    if permutation == list(range(len(base["sites"]))):
        permutation = [2, 0, 1]
    permuted = copy.deepcopy(base)
    permuted["model_id"] = "hidden_site_permutation_permuted"
    permuted["sites"] = [copy.deepcopy(base["sites"][index]) for index in permutation]
    permuted["device"]["site_potential"] = [
        [row[index] for index in permutation] for row in base["device"]["site_potential"]
    ]
    base_case = Case(
        base,
        "hidden",
        "site_permutation_metamorphic_base",
        SEED_HIDDEN_SITE_BASE,
        "hidden-site-permutation-base-201217",
    )
    permuted_case = Case(
        permuted,
        "hidden",
        "site_permutation_metamorphic_permuted",
        SEED_HIDDEN_SITE_PERMUTATION,
        "hidden-site-permutation-transform-201239",
    )
    relation = {
        "id": "site_list_permutation",
        "base_model_id": base["model_id"],
        "transformed_model_id": permuted["model_id"],
        "new_site_order_as_old_indices": permutation,
        "expected": {
            "hamiltonians_and_self_energies": "related by the induced site-major orbital permutation",
            "bands_dos_ldos_cells_and_transmission": "unchanged because all reported spectral traces are basis-invariant",
        },
    }
    return base_case, permuted_case, relation


def _build_cases() -> tuple[list[Case], list[dict[str, Any]]]:
    if len(ALL_LITERAL_SEEDS) != len(set(ALL_LITERAL_SEEDS)):
        raise RuntimeError("case seeds must be pairwise disjoint")
    energy_base, energy_shifted, energy_relation = _hidden_energy_pair()
    site_base, site_permuted, site_relation = _hidden_site_permutation_pair()
    cases = [
        _public_analytic(),
        _public_rotated(),
        _hidden_rotation(),
        _hidden_permutation(),
        _hidden_cutoff_edge(),
        _hidden_heterogeneous(),
        _hidden_weak_contact(),
        _hidden_strong_defect(),
        energy_base,
        energy_shifted,
        site_base,
        site_permuted,
    ]
    model_ids = [case.instance["model_id"] for case in cases]
    if len(model_ids) != len(set(model_ids)):
        raise RuntimeError("model IDs must be unique")
    seed_labels = [case.seed_label for case in cases]
    if len(seed_labels) != len(set(seed_labels)):
        raise RuntimeError("seed labels must be unique")
    if {case.seed for case in cases} != set(ALL_LITERAL_SEEDS):
        raise RuntimeError("case inventory must use every literal seed exactly once")
    if any(case.visibility not in {"public", "hidden"} for case in cases):
        raise RuntimeError("case visibility must be public or hidden")
    if sum(case.visibility == "public" for case in cases) != 2:
        raise RuntimeError("exactly two public fixtures are required")
    if sum(case.visibility == "hidden" for case in cases) < 7:
        raise RuntimeError("at least seven hidden fixtures are required")
    return cases, [energy_relation, site_relation]


def _check_limits(case: Case) -> None:
    instance = case.instance
    basis_size = sum(
        len(instance["species"][site["species"]]["orbitals"])
        for site in instance["sites"]
    )
    cells = int(instance["device"]["cells"])
    phase_count = len(instance["phase_grid"])
    energy_count = len(instance["energy_grid"])
    eta = float(instance["eta"])
    if basis_size > 12:
        raise RuntimeError(f"{instance['model_id']}: basis size {basis_size} exceeds 12")
    if cells > 7:
        raise RuntimeError(f"{instance['model_id']}: cell count {cells} exceeds 7")
    if phase_count > 25:
        raise RuntimeError(f"{instance['model_id']}: phase count {phase_count} exceeds 25")
    if energy_count > 31:
        raise RuntimeError(f"{instance['model_id']}: energy count {energy_count} exceeds 31")
    if not 0.04 <= eta <= 0.12:
        raise RuntimeError(f"{instance['model_id']}: eta {eta} is outside [0.04, 0.12]")


def _relative_reference_dir(case: Case) -> Path:
    model_id = str(case.instance["model_id"])
    if case.visibility == "public":
        return Path("author") / "oracle" / "public_reference" / model_id
    return Path("private") / "reference" / model_id


def _relative_input_path(case: Case) -> Path:
    model_id = str(case.instance["model_id"])
    if case.visibility == "public":
        return Path("participant") / "input" / f"{model_id}.json"
    return Path("private") / "hidden_inputs" / f"{model_id}.json"


def _runtime_workload(instance: dict[str, Any], basis_size: int) -> dict[str, int]:
    cells = int(instance["device"]["cells"])
    phase_count = len(instance["phase_grid"])
    energy_count = len(instance["energy_grid"])
    device_dimension = basis_size * cells
    return {
        "basis_size": basis_size,
        "device_cells": cells,
        "device_dimension": device_dimension,
        "phase_points": phase_count,
        "energy_points": energy_count,
        "lead_surface_solves": 2 * energy_count,
        "device_linear_solves": energy_count,
        "nominal_dense_cubic_work_units": (
            phase_count * basis_size**3
            + 2 * energy_count * basis_size**3
            + energy_count * device_dimension**3
        ),
    }


def _max_abs_residual(actual: Any, expected: Any) -> float:
    difference = np.asarray(actual) - np.asarray(expected)
    return float(np.max(np.abs(difference))) if difference.size else 0.0


def _metamorphic_oracle_checks(
    results: dict[str, dict[str, Any]],
    loaded_instances: dict[str, dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    checks: dict[str, dict[str, float]] = {}

    energy_relation = next(relation for relation in relations if relation["id"] == "global_energy_shift")
    energy_base = results[energy_relation["base_model_id"]]
    energy_shifted = results[energy_relation["transformed_model_id"]]
    delta = float(energy_relation["energy_shift"])
    identity = np.eye(energy_base["h0"].shape[0], dtype=np.complex128)
    energy_checks = {
        "h0_shift_residual": _max_abs_residual(
            energy_shifted["h0"], energy_base["h0"] + delta * identity
        ),
        "h1_residual": _max_abs_residual(energy_shifted["h1"], energy_base["h1"]),
        "energy_grid_shift_residual": _max_abs_residual(
            energy_shifted["energies"], energy_base["energies"] + delta
        ),
        "phase_grid_residual": _max_abs_residual(
            energy_shifted["phases"], energy_base["phases"]
        ),
        "band_shift_residual": _max_abs_residual(
            energy_shifted["bands"], energy_base["bands"] + delta
        ),
        "sigma_left_residual": _max_abs_residual(
            energy_shifted["sigma_left"], energy_base["sigma_left"]
        ),
        "sigma_right_residual": _max_abs_residual(
            energy_shifted["sigma_right"], energy_base["sigma_right"]
        ),
        "dos_total_residual": _max_abs_residual(
            energy_shifted["dos_total"], energy_base["dos_total"]
        ),
        "ldos_cells_residual": _max_abs_residual(
            energy_shifted["ldos_cells"], energy_base["ldos_cells"]
        ),
        "transmission_residual": _max_abs_residual(
            energy_shifted["transmission"], energy_base["transmission"]
        ),
    }
    if max(energy_checks.values()) > 2.0e-9:
        raise RuntimeError(f"global energy-shift metamorphic check failed: {energy_checks}")
    checks["global_energy_shift"] = energy_checks

    site_relation = next(relation for relation in relations if relation["id"] == "site_list_permutation")
    site_base_id = str(site_relation["base_model_id"])
    site_permuted_id = str(site_relation["transformed_model_id"])
    site_base = results[site_base_id]
    site_permuted = results[site_permuted_id]
    base_instance = loaded_instances[site_base_id]
    site_slices: list[np.ndarray] = []
    cursor = 0
    for site in base_instance["sites"]:
        width = len(base_instance["species"][site["species"]]["orbitals"])
        site_slices.append(np.arange(cursor, cursor + width, dtype=np.int64))
        cursor += width
    basis_permutation = np.concatenate(
        [site_slices[index] for index in site_relation["new_site_order_as_old_indices"]]
    )

    def permute_matrix(matrix: np.ndarray) -> np.ndarray:
        return matrix[np.ix_(basis_permutation, basis_permutation)]

    def permute_matrix_stack(stack: np.ndarray) -> np.ndarray:
        return stack[:, basis_permutation, :][:, :, basis_permutation]

    site_checks = {
        "h0_permutation_residual": _max_abs_residual(
            site_permuted["h0"], permute_matrix(site_base["h0"])
        ),
        "h1_permutation_residual": _max_abs_residual(
            site_permuted["h1"], permute_matrix(site_base["h1"])
        ),
        "sigma_left_permutation_residual": _max_abs_residual(
            site_permuted["sigma_left"], permute_matrix_stack(site_base["sigma_left"])
        ),
        "sigma_right_permutation_residual": _max_abs_residual(
            site_permuted["sigma_right"], permute_matrix_stack(site_base["sigma_right"])
        ),
        "bands_residual": _max_abs_residual(site_permuted["bands"], site_base["bands"]),
        "dos_total_residual": _max_abs_residual(
            site_permuted["dos_total"], site_base["dos_total"]
        ),
        "ldos_cells_residual": _max_abs_residual(
            site_permuted["ldos_cells"], site_base["ldos_cells"]
        ),
        "transmission_residual": _max_abs_residual(
            site_permuted["transmission"], site_base["transmission"]
        ),
    }
    if max(site_checks.values()) > 2.0e-9:
        raise RuntimeError(f"site-permutation metamorphic check failed: {site_checks}")
    checks["site_list_permutation"] = site_checks
    return checks


def generate(task_root: Path, output_root: Path) -> tuple[dict[str, Any], dict[str, float]]:
    science = _load_science(task_root)
    cases, metamorphic_pairs = _build_cases()
    output_root = output_root.resolve()
    case_records: list[dict[str, Any]] = []
    measured_seconds: dict[str, float] = {}
    generated_files: list[str] = []
    results_by_model: dict[str, dict[str, Any]] = {}
    loaded_by_model: dict[str, dict[str, Any]] = {}

    for case in cases:
        _check_limits(case)
        input_relative = _relative_input_path(case)
        input_path = output_root / input_relative
        written_digest = _write_json(input_path, case.instance)
        loaded = science.load_instance(input_path)
        if loaded["_input_sha256"] != written_digest:
            raise RuntimeError(f"input digest mismatch for {case.instance['model_id']}")

        h0, h1, basis_site = science.assemble_blocks(loaded)
        singular_values = np.linalg.svd(h1, compute_uv=False)
        rank_threshold = max(1.0, float(singular_values[0])) * 1.0e-10
        h1_rank = int(np.count_nonzero(singular_values > rank_threshold))
        minimum_rank = max(1, math.ceil(0.75 * h1.shape[0]))
        h1_norm = float(np.linalg.norm(h1, ord="fro"))
        if h1_norm <= 0.1 or h1_rank < minimum_rank:
            raise RuntimeError(
                f"{case.instance['model_id']}: H1 is not meaningful/full-rank-ish "
                f"(norm={h1_norm:.6g}, rank={h1_rank}/{h1.shape[0]})"
            )

        started = time.perf_counter()
        result = science.solve_instance(loaded)
        model_id = str(case.instance["model_id"])
        measured_seconds[model_id] = time.perf_counter() - started
        results_by_model[model_id] = result
        loaded_by_model[model_id] = loaded
        reference_relative = _relative_reference_dir(case)
        reference_path = output_root / reference_relative
        science.write_outputs(reference_path, result)

        generated_files.append(input_relative.as_posix())
        generated_files.extend(
            (reference_relative / filename).as_posix() for filename in REFERENCE_FILES
        )
        case_records.append(
            {
                "model_id": case.instance["model_id"],
                "visibility": case.visibility,
                "family": case.family,
                "seed": case.seed,
                "seed_label": case.seed_label,
                "input": input_relative.as_posix(),
                "input_sha256": written_digest,
                "reference": reference_relative.as_posix(),
                "runtime": _runtime_workload(case.instance, int(basis_site.size)),
                "oracle_checks": {
                    "h1_frobenius_norm": h1_norm,
                    "h1_numerical_rank": h1_rank,
                    "h1_rank_fraction": h1_rank / int(basis_site.size),
                    "max_hermiticity_residual": float(
                        result["diagnostics"]["max_hermiticity_residual"]
                    ),
                    "max_surface_residual": float(
                        result["diagnostics"]["max_surface_residual"]
                    ),
                },
            }
        )

    metamorphic_checks = _metamorphic_oracle_checks(
        results_by_model, loaded_by_model, metamorphic_pairs
    )
    for relation in metamorphic_pairs:
        relation["oracle_checks"] = metamorphic_checks[str(relation["id"])]

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generator": "author/oracle/generate_assets.py",
        "determinism": {
            "json": "UTF-8, LF terminated, sorted keys, two-space indentation",
            "seed_policy": "all public, hidden, and transform seeds are distinct literals",
            "wall_clock_timings": "printed by the CLI only and excluded from generated files",
        },
        "limits": {
            "maximum_basis_size": 12,
            "maximum_device_cells": 7,
            "maximum_phase_points": 25,
            "maximum_energy_points": 31,
            "minimum_eta": 0.04,
            "maximum_eta": 0.12,
            "minimum_h1_rank_fraction": 0.75,
        },
        "cases": case_records,
        "metamorphic_pairs": metamorphic_pairs,
        "generated_files": sorted(generated_files),
    }
    _write_json(output_root / "author" / "oracle" / "manifest.json", manifest)
    return manifest, measured_seconds


def _compare_npz(expected: Path, actual: Path, relative: str) -> None:
    with np.load(expected, allow_pickle=False) as left, np.load(actual, allow_pickle=False) as right:
        if left.files != right.files:
            raise RuntimeError(f"NPZ keys differ for {relative}: {left.files!r} != {right.files!r}")
        for key in left.files:
            if not np.array_equal(left[key], right[key]):
                raise RuntimeError(f"NPZ array differs for {relative}:{key}")


def compare_generated(expected_root: Path, actual_root: Path) -> None:
    manifest_relative = Path("author") / "oracle" / "manifest.json"
    actual_manifest = json.loads((actual_root / manifest_relative).read_text(encoding="utf-8"))
    relative_paths = [manifest_relative.as_posix(), *actual_manifest["generated_files"]]
    for relative in relative_paths:
        expected = expected_root / relative
        actual = actual_root / relative
        if not expected.is_file():
            raise RuntimeError(f"checked-in generated file is missing: {relative}")
        if not actual.is_file():
            raise RuntimeError(f"regenerated file is missing: {relative}")
        if expected.suffix == ".npz":
            _compare_npz(expected, actual, relative)
        elif expected.read_bytes() != actual.read_bytes():
            raise RuntimeError(f"generated text differs for {relative}")


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic periodic-orbital transport task assets."
    )
    parser.add_argument(
        "--task-root",
        type=Path,
        default=TASK_ROOT,
        help="task root containing private/grader/science.py",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="alternate output root; defaults to --task-root",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in a temporary directory and compare with checked-in assets",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    task_root = arguments.task_root.resolve(strict=True)
    if arguments.check and arguments.output_root is not None:
        raise SystemExit("--check and --output-root are mutually exclusive")

    if arguments.check:
        with tempfile.TemporaryDirectory(prefix="periodic-orbital-assets-") as temporary:
            manifest, timings = generate(task_root, Path(temporary))
            compare_generated(task_root, Path(temporary))
    else:
        output_root = arguments.output_root.resolve() if arguments.output_root else task_root
        manifest, timings = generate(task_root, output_root)

    print(
        json.dumps(
            {
                "status": "pass",
                "case_count": len(manifest["cases"]),
                "public_case_count": sum(
                    case["visibility"] == "public" for case in manifest["cases"]
                ),
                "hidden_case_count": sum(
                    case["visibility"] == "hidden" for case in manifest["cases"]
                ),
                "measured_oracle_seconds": timings,
                "measured_total_oracle_seconds": sum(timings.values()),
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
