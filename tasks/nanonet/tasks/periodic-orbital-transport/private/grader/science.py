"""Trusted numerical reference for the periodic orbital transport task.

This module intentionally depends only on the Python standard library and
NumPy.  It does not import participant code or the source project from which
the benchmark was derived.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np


INPUT_SCHEMA_VERSION = "periodic-orbital-device/v1"
OUTPUT_SCHEMA_VERSION = "periodic-orbital-transport-output/v1"

ORBITAL_SETS = (("s",), ("s", "px", "py", "pz"))
P_COMPONENT = {"px": 0, "py": 1, "pz": 2}
HOPPING_FIELDS = ("ss_sigma", "sp_sigma", "pp_sigma", "pp_pi")

DEFAULT_DECIMATION_TOL = 1.0e-14
DEFAULT_SURFACE_RESIDUAL_TOL = 5.0e-11
DEFAULT_MAX_SURFACE_ITERATIONS = 256
MAX_SURFACE_HOMOTOPY_STEPS = 512
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_NPZ_BYTES = 1024 * 1024 * 1024

_INPUT_KEYS = {
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
}
_DEVICE_KEYS = {
    "cells",
    "site_potential",
    "bond_scale",
    "contact_scale_left",
    "contact_scale_right",
}
_DIAGNOSTIC_KEYS = {
    "schema_version",
    "model_id",
    "input_sha256",
    "basis_size",
    "device_cells",
    "max_surface_residual",
    "max_hermiticity_residual",
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}\Z")


class ScienceError(ValueError):
    """Raised when an instance or numerical reference calculation is invalid."""


def _fail(path: str, message: str) -> None:
    raise ScienceError(f"{path}: {message}")


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be a JSON object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], path: str, optional: set[str] | None = None
) -> None:
    optional = optional or set()
    keys = set(value)
    missing = expected - keys
    extra = keys - expected - optional
    if missing:
        _fail(path, f"missing keys {sorted(missing)!r}")
    if extra:
        _fail(path, f"unexpected keys {sorted(extra)!r}")


def _finite_real(value: Any, path: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        _fail(path, "must be a real number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ScienceError(f"{path}: must be representable as a finite float") from exc
    if not math.isfinite(result):
        _fail(path, "must be finite")
    return result


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        _fail(path, "must be an integer")
    result = int(value)
    if result < 1:
        _fail(path, "must be at least 1")
    return result


def _real_vector(value: Any, length: int | None, path: str, *, nonempty: bool = False) -> np.ndarray:
    if not isinstance(value, list):
        _fail(path, "must be a JSON array")
    if length is not None and len(value) != length:
        _fail(path, f"must have length {length}")
    if nonempty and not value:
        _fail(path, "must not be empty")
    return np.asarray([_finite_real(item, f"{path}[{index}]") for index, item in enumerate(value)], dtype=np.float64)


def _nonempty_string(value: Any, path: str, *, forbid_pipe: bool = False) -> str:
    if not isinstance(value, str) or not value:
        _fail(path, "must be a nonempty string")
    if forbid_pipe and "|" in value:
        _fail(path, "must not contain '|'")
    return value


def _pair_key(species_a: str, species_b: str) -> str:
    first, second = sorted((species_a, species_b))
    return f"{first}|{second}"


def _site_orbitals(instance: Mapping[str, Any]) -> tuple[list[tuple[str, ...]], np.ndarray, list[slice]]:
    orbitals: list[tuple[str, ...]] = []
    basis_site: list[int] = []
    slices: list[slice] = []
    cursor = 0
    for site_index, site in enumerate(instance["sites"]):
        site_orbitals = tuple(instance["species"][site["species"]]["orbitals"])
        orbitals.append(site_orbitals)
        slices.append(slice(cursor, cursor + len(site_orbitals)))
        basis_site.extend([site_index] * len(site_orbitals))
        cursor += len(site_orbitals)
    return orbitals, np.asarray(basis_site, dtype=np.int64), slices


def _iter_geometric_pairs(instance: Mapping[str, Any]):
    """Yield (i, j, offset, displacement, distance) in the specified order."""

    sites = instance["sites"]
    positions = [np.asarray(site["position"], dtype=np.float64) for site in sites]
    lattice = np.asarray(instance["lattice_vector"], dtype=np.float64)
    cutoff = float(instance["neighbor_cutoff"]) + 1.0e-12

    for i in range(len(sites)):
        for j in range(i + 1, len(sites)):
            displacement = positions[j] - positions[i]
            distance = float(np.linalg.norm(displacement))
            if distance != 0.0 and distance <= cutoff:
                yield i, j, 0, displacement, distance

    for i in range(len(sites)):
        for j in range(len(sites)):
            displacement = positions[j] + lattice - positions[i]
            distance = float(np.linalg.norm(displacement))
            if distance != 0.0 and distance <= cutoff:
                yield i, j, 1, displacement, distance


def validate_instance(instance: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate an instance strictly and return the original mapping.

    ``_input_sha256`` is the sole permitted internal key.  ``load_instance``
    adds it only after validating the JSON document, so it cannot weaken the
    public input schema.
    """

    instance = _require_mapping(instance, "instance")
    _require_exact_keys(instance, _INPUT_KEYS, "instance", {"_input_sha256"})

    if instance["schema_version"] != INPUT_SCHEMA_VERSION:
        _fail("schema_version", f"must equal {INPUT_SCHEMA_VERSION!r}")
    model_id = _nonempty_string(instance["model_id"], "model_id")
    if len(model_id) > 128:
        _fail("model_id", "must contain at most 128 characters")

    lattice = _real_vector(instance["lattice_vector"], 3, "lattice_vector")
    if float(np.linalg.norm(lattice)) == 0.0:
        _fail("lattice_vector", "must be nonzero")
    cutoff = _finite_real(instance["neighbor_cutoff"], "neighbor_cutoff")
    if cutoff <= 0.0:
        _fail("neighbor_cutoff", "must be positive")

    species = _require_mapping(instance["species"], "species")
    if not species:
        _fail("species", "must not be empty")
    for name, spec in species.items():
        _nonempty_string(name, "species key", forbid_pipe=True)
        if _NAME_RE.fullmatch(name) is None:
            _fail("species key", "must match [A-Za-z][A-Za-z0-9_-]{0,31}")
        spec = _require_mapping(spec, f"species.{name}")
        _require_exact_keys(spec, {"orbitals", "onsite"}, f"species.{name}")
        if not isinstance(spec["orbitals"], list):
            _fail(f"species.{name}.orbitals", "must be a JSON array")
        orbitals = tuple(spec["orbitals"])
        if orbitals not in ORBITAL_SETS:
            _fail(
                f"species.{name}.orbitals",
                "must be exactly ['s'] or ['s', 'px', 'py', 'pz']",
            )
        onsite = _require_mapping(spec["onsite"], f"species.{name}.onsite")
        _require_exact_keys(onsite, set(orbitals), f"species.{name}.onsite")
        for orbital in orbitals:
            _finite_real(onsite[orbital], f"species.{name}.onsite.{orbital}")

    sites = instance["sites"]
    if not isinstance(sites, list) or not sites:
        _fail("sites", "must be a nonempty JSON array")
    site_ids: set[str] = set()
    for index, site in enumerate(sites):
        path = f"sites[{index}]"
        site = _require_mapping(site, path)
        _require_exact_keys(site, {"id", "species", "position"}, path)
        site_id = _nonempty_string(site["id"], f"{path}.id")
        if len(site_id) > 128:
            _fail(f"{path}.id", "must contain at most 128 characters")
        if site_id in site_ids:
            _fail(f"{path}.id", "must be unique")
        site_ids.add(site_id)
        species_name = _nonempty_string(site["species"], f"{path}.species", forbid_pipe=True)
        if species_name not in species:
            _fail(f"{path}.species", "does not name a declared species")
        _real_vector(site["position"], 3, f"{path}.position")

    hoppings = _require_mapping(instance["hoppings"], "hoppings")
    if not hoppings:
        _fail("hoppings", "must not be empty")
    for key, hopping in hoppings.items():
        _nonempty_string(key, "hoppings key")
        parts = key.split("|")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            _fail(f"hoppings.{key}", "key must have canonical form 'A|B'")
        if parts[0] not in species or parts[1] not in species:
            _fail(f"hoppings.{key}", "key names an undeclared species")
        if key != _pair_key(parts[0], parts[1]):
            _fail(f"hoppings.{key}", "species names must be in alphabetic order")
        hopping = _require_mapping(hopping, f"hoppings.{key}")
        _require_exact_keys(hopping, set(HOPPING_FIELDS), f"hoppings.{key}")
        for field in HOPPING_FIELDS:
            _finite_real(hopping[field], f"hoppings.{key}.{field}")

    _real_vector(instance["phase_grid"], None, "phase_grid", nonempty=True)
    _real_vector(instance["energy_grid"], None, "energy_grid", nonempty=True)
    eta = _finite_real(instance["eta"], "eta")
    if eta <= 0.0:
        _fail("eta", "must be positive")

    device = _require_mapping(instance["device"], "device")
    _require_exact_keys(device, _DEVICE_KEYS, "device")
    cells = _positive_int(device["cells"], "device.cells")
    potentials = device["site_potential"]
    if not isinstance(potentials, list) or len(potentials) != cells:
        _fail("device.site_potential", f"must have shape ({cells}, {len(sites)})")
    for cell, row in enumerate(potentials):
        _real_vector(row, len(sites), f"device.site_potential[{cell}]")
    _real_vector(device["bond_scale"], cells - 1, "device.bond_scale")
    _finite_real(device["contact_scale_left"], "device.contact_scale_left")
    _finite_real(device["contact_scale_right"], "device.contact_scale_right")
    if float(device["contact_scale_left"]) <= 0.0:
        _fail("device.contact_scale_left", "must be positive")
    if float(device["contact_scale_right"]) <= 0.0:
        _fail("device.contact_scale_right", "must be positive")

    internal_hash = instance.get("_input_sha256")
    if internal_hash is not None and (
        not isinstance(internal_hash, str) or _SHA256_RE.fullmatch(internal_hash) is None
    ):
        _fail("_input_sha256", "must be a lowercase hexadecimal SHA-256 digest")

    required_hoppings: set[str] = set()
    for i, j, _offset, _displacement, _distance in _iter_geometric_pairs(instance):
        required_hoppings.add(_pair_key(sites[i]["species"], sites[j]["species"]))
    missing_hoppings = required_hoppings - set(hoppings)
    if missing_hoppings:
        _fail("hoppings", f"missing geometrically used pairs {sorted(missing_hoppings)!r}")

    return instance


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScienceError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ScienceError(f"non-finite JSON constant {value!r} is not permitted")


def load_instance(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load and validate a UTF-8 JSON instance, retaining its raw-byte digest."""

    input_path = Path(path)
    if input_path.is_symlink() or not input_path.is_file():
        raise ScienceError(f"instance path is not a regular file: {input_path}")
    if input_path.stat().st_size > MAX_JSON_BYTES:
        raise ScienceError(f"instance exceeds {MAX_JSON_BYTES} bytes: {input_path}")
    raw = input_path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScienceError(f"instance is not valid UTF-8: {exc}") from exc
    try:
        instance = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ScienceError) as exc:
        raise ScienceError(f"invalid instance JSON: {exc}") from exc
    instance = _require_mapping(instance, "instance")
    if "_input_sha256" in instance:
        raise ScienceError("input JSON contains reserved key '_input_sha256'")
    validate_instance(instance)
    instance["_input_sha256"] = hashlib.sha256(raw).hexdigest()
    return instance


def _sk_block(
    row_orbitals: tuple[str, ...],
    column_orbitals: tuple[str, ...],
    direction: np.ndarray,
    hopping: Mapping[str, Any],
) -> np.ndarray:
    """Construct one real Slater-Koster block using the public sign convention."""

    v_ss = float(hopping["ss_sigma"])
    v_sp = float(hopping["sp_sigma"])
    v_pp_sigma = float(hopping["pp_sigma"])
    v_pp_pi = float(hopping["pp_pi"])
    block = np.empty((len(row_orbitals), len(column_orbitals)), dtype=np.float64)

    for row, orbital_row in enumerate(row_orbitals):
        for column, orbital_column in enumerate(column_orbitals):
            if orbital_row == "s" and orbital_column == "s":
                value = v_ss
            elif orbital_row == "s":
                value = direction[P_COMPONENT[orbital_column]] * v_sp
            elif orbital_column == "s":
                value = -direction[P_COMPONENT[orbital_row]] * v_sp
            else:
                component_row = P_COMPONENT[orbital_row]
                component_column = P_COMPONENT[orbital_column]
                product = direction[component_row] * direction[component_column]
                delta = 1.0 if component_row == component_column else 0.0
                value = product * v_pp_sigma + (delta - product) * v_pp_pi
            block[row, column] = value
    return block


def assemble_blocks(instance: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Assemble ``H0``, forward ``H1``, and the zero-based basis-to-site map."""

    validate_instance(instance)
    site_orbitals, basis_site, slices = _site_orbitals(instance)
    basis_size = int(basis_site.size)
    h0 = np.zeros((basis_size, basis_size), dtype=np.float64)
    h1 = np.zeros((basis_size, basis_size), dtype=np.float64)

    for site_index, site in enumerate(instance["sites"]):
        onsite = instance["species"][site["species"]]["onsite"]
        site_slice = slices[site_index]
        h0[site_slice, site_slice] = np.diag(
            [float(onsite[orbital]) for orbital in site_orbitals[site_index]]
        )

    for i, j, offset, displacement, distance in _iter_geometric_pairs(instance):
        species_i = instance["sites"][i]["species"]
        species_j = instance["sites"][j]["species"]
        hopping = instance["hoppings"][_pair_key(species_i, species_j)]
        block = _sk_block(
            site_orbitals[i],
            site_orbitals[j],
            displacement / distance,
            hopping,
        )
        if offset == 0:
            h0[slices[i], slices[j]] += block
            h0[slices[j], slices[i]] += block.T
        else:
            h1[slices[i], slices[j]] += block

    return (
        np.asarray(h0, dtype=np.complex128),
        np.asarray(h1, dtype=np.complex128),
        basis_site,
    )


def _bloch_matrix(h0: np.ndarray, h1: np.ndarray, phase: float) -> np.ndarray:
    forward_phase = np.exp(1.0j * phase)
    return h0 + h1 * forward_phase + h1.conj().T * np.conjugate(forward_phase)


def bands(
    instance: Mapping[str, Any],
    h0: np.ndarray | None = None,
    h1: np.ndarray | None = None,
) -> np.ndarray:
    """Return ascending Bloch eigenvalues with shape ``(phases, basis)``."""

    validate_instance(instance)
    if h0 is None or h1 is None:
        assembled_h0, assembled_h1, _basis_site = assemble_blocks(instance)
        h0 = assembled_h0 if h0 is None else h0
        h1 = assembled_h1 if h1 is None else h1
    h0 = _square_complex_matrix(h0, "h0")
    h1 = _square_complex_matrix(h1, "h1", size=h0.shape[0])

    result = np.empty((len(instance["phase_grid"]), h0.shape[0]), dtype=np.float64)
    for index, phase_value in enumerate(instance["phase_grid"]):
        h_phase = _bloch_matrix(h0, h1, float(phase_value))
        result[index] = np.linalg.eigvalsh(h_phase)
    return result


def _square_complex_matrix(value: Any, path: str, *, size: int | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=np.complex128)
    if array.ndim != 2 or array.shape[0] != array.shape[1]:
        _fail(path, "must be a square matrix")
    if size is not None and array.shape != (size, size):
        _fail(path, f"must have shape ({size}, {size})")
    if not np.all(np.isfinite(array)):
        _fail(path, "contains a non-finite value")
    return array


def _hermiticity_residual(matrix: np.ndarray) -> float:
    numerator = float(np.linalg.norm(matrix - matrix.conj().T, ord="fro"))
    denominator = max(1.0, float(np.linalg.norm(matrix, ord="fro")))
    return numerator / denominator


def _surface_equation_residual(
    g_surface: np.ndarray, z: complex, h0: np.ndarray, outward_coupling: np.ndarray
) -> float:
    identity = np.eye(h0.shape[0], dtype=np.complex128)
    effective = z * identity - h0 - outward_coupling @ g_surface @ outward_coupling.conj().T
    numerator = float(np.linalg.norm(effective @ g_surface - identity, ord="fro"))
    denominator = max(
        float(np.linalg.norm(identity, ord="fro")),
        float(np.linalg.norm(effective, ord="fro"))
        * float(np.linalg.norm(g_surface, ord="fro")),
    )
    return numerator / denominator


def _refine_surface_newton(
    initial_g: np.ndarray,
    z: complex,
    h0: np.ndarray,
    outward_coupling: np.ndarray,
    residual_tol: float,
    *,
    max_steps: int = 64,
    force_step: bool = False,
) -> tuple[np.ndarray, float, int]:
    """Refine a causal decimation result by Newton's method.

    Lopez-Sancho can lose digits through cancellation when ``eta`` is tiny and
    an early bulk resolvent is nearly singular.  Once decimation has selected
    the retarded branch, Newton refinement of the same nonlinear surface
    equation recovers those digits.  The Jacobian is only formed for modest
    lead blocks; benchmark instances are deliberately in that regime.
    """

    size = h0.shape[0]
    if size > 24:
        return initial_g, _surface_equation_residual(initial_g, z, h0, outward_coupling), 0

    identity = np.eye(size, dtype=np.complex128)
    g_surface = initial_g.copy()
    residual = _surface_equation_residual(g_surface, z, h0, outward_coupling)
    if residual <= residual_tol and not force_step:
        return g_surface, residual, 0
    for step in range(1, max_steps + 1):
        effective = z * identity - h0 - outward_coupling @ g_surface @ outward_coupling.conj().T
        equation = effective @ g_surface - identity
        equation_norm = float(np.linalg.norm(equation, ord="fro"))
        right_factor = outward_coupling.conj().T @ g_surface
        jacobian = np.kron(identity, effective) - np.kron(
            right_factor.T, outward_coupling
        )
        try:
            delta_vector = np.linalg.solve(
                jacobian, -equation.reshape(size * size, order="F")
            )
        except np.linalg.LinAlgError:
            break
        delta = delta_vector.reshape((size, size), order="F")
        if not np.all(np.isfinite(delta)):
            break

        accepted = False
        damping = 1.0
        for _line_search in range(12):
            candidate = g_surface + damping * delta
            if np.all(np.isfinite(candidate)):
                imaginary_part = (candidate - candidate.conj().T) / (2.0j)
                causality_limit = _surface_causality_limit(candidate)
                causal = float(np.max(np.linalg.eigvalsh(imaginary_part))) <= causality_limit
                candidate_residual = _surface_equation_residual(
                    candidate, z, h0, outward_coupling
                )
                candidate_effective = (
                    z * identity
                    - h0
                    - outward_coupling @ candidate @ outward_coupling.conj().T
                )
                candidate_equation_norm = float(
                    np.linalg.norm(candidate_effective @ candidate - identity, ord="fro")
                )
                raw_equation_improved = candidate_equation_norm < equation_norm * (
                    1.0 - 1.0e-12
                )
                plateau_progress = residual >= 0.9 and raw_equation_improved
                continuation_progress = force_step and raw_equation_improved
                if causal and (
                    candidate_residual < residual
                    or plateau_progress
                    or continuation_progress
                ):
                    g_surface = candidate
                    residual = candidate_residual
                    accepted = True
                    break
            damping *= 0.5
        if not accepted or residual <= residual_tol:
            return g_surface, residual, step
    return g_surface, residual, max_steps


def _surface_causality_violation(g_surface: np.ndarray) -> float:
    imaginary_part = (g_surface - g_surface.conj().T) / (2.0j)
    return max(0.0, float(np.max(np.linalg.eigvalsh(imaginary_part))))


def _surface_causality_limit(g_surface: np.ndarray) -> float:
    return 1.0e-8 * max(
        np.finfo(np.float64).tiny,
        float(np.linalg.norm(g_surface, ord="fro")),
    )


def _surface_tangent_predictor(
    g_surface: np.ndarray,
    current_z: complex,
    next_z: complex,
    h0: np.ndarray,
    outward_coupling: np.ndarray,
    previous_green: np.ndarray | None = None,
    previous_z: complex | None = None,
) -> np.ndarray:
    """Select a causal continuation predictor by equation defect."""

    size = h0.shape[0]
    identity = np.eye(size, dtype=np.complex128)
    effective = current_z * identity - h0 - outward_coupling @ g_surface @ outward_coupling.conj().T
    right_factor = outward_coupling.conj().T @ g_surface
    jacobian = np.kron(identity, effective) - np.kron(
        right_factor.T, outward_coupling
    )
    source = -(next_z - current_z) * g_surface
    candidates = [g_surface]
    try:
        tangent = np.linalg.solve(
            jacobian, source.reshape(size * size, order="F")
        ).reshape((size, size), order="F")
    except np.linalg.LinAlgError:
        pass
    else:
        candidates.append(g_surface + tangent)

    # This candidate captures isolated surface-pole residues.  It is never
    # accepted merely by assumption: the nonlinear equation defect below is
    # compared against the general tangent and secant predictors.
    scaled_candidate: np.ndarray | None = None
    if next_z.imag > 0.0:
        scaled_candidate = g_surface * (current_z.imag / next_z.imag)
        candidates.append(scaled_candidate)
    if previous_green is not None and previous_z is not None and current_z != previous_z:
        secant_weight = (next_z - current_z) / (current_z - previous_z)
        candidates.append(g_surface + secant_weight * (g_surface - previous_green))

    best = g_surface
    best_defect = math.inf
    prepared_scaled: np.ndarray | None = None
    for raw_candidate in candidates:
        if not np.all(np.isfinite(raw_candidate)):
            continue
        candidate = raw_candidate
        violation = _surface_causality_violation(candidate)
        limit = _surface_causality_limit(candidate)
        if violation > 10.0 * limit:
            continue
        if violation > limit:
            hermitian_part = (candidate + candidate.conj().T) / 2.0
            imaginary_part = (candidate - candidate.conj().T) / (2.0j)
            values, vectors = np.linalg.eigh(imaginary_part)
            causal_imaginary = (vectors * np.minimum(values, 0.0)) @ vectors.conj().T
            candidate = hermitian_part + 1.0j * causal_imaginary
        if raw_candidate is scaled_candidate:
            prepared_scaled = candidate
        candidate_effective = (
            next_z * identity
            - h0
            - outward_coupling @ candidate @ outward_coupling.conj().T
        )
        defect = float(np.linalg.norm(candidate_effective @ candidate - identity, ord="fro"))
        if math.isfinite(defect) and defect < best_defect:
            best = candidate
            best_defect = defect
    pole_indicator = current_z.imag * float(np.linalg.norm(g_surface, ord="fro"))
    if prepared_scaled is not None and pole_indicator >= 1.0e-4:
        return prepared_scaled
    return best


def _recover_causal_surface(
    h0: np.ndarray,
    outward_coupling: np.ndarray,
    energy: float,
    eta: float,
    residual_tol: float,
) -> tuple[np.ndarray, float, int, int]:
    """Track the retarded solution from a large-eta causal anchor."""

    size = h0.shape[0]
    if size > 24:
        raise ScienceError("causal homotopy is limited to lead blocks of size at most 24")
    identity = np.eye(size, dtype=np.complex128)
    homotopy_residual_tol = residual_tol
    problem_scale = max(
        abs(energy),
        eta,
        float(np.max(np.abs(h0))),
        float(np.max(np.abs(outward_coupling))),
        np.finfo(np.float64).tiny,
    )

    anchor_green: np.ndarray | None = None
    anchor_eta = max(8.0 * problem_scale, 2.0 * eta)
    anchor_residual = math.inf
    anchor_newton_steps = 0
    for _anchor_attempt in range(6):
        anchor_z = complex(energy, anchor_eta)
        try:
            bare_green = np.linalg.solve(anchor_z * identity - h0, identity)
        except np.linalg.LinAlgError:
            anchor_eta *= 4.0
            continue
        candidate, candidate_residual, candidate_steps = _refine_surface_newton(
            bare_green,
            anchor_z,
            h0,
            outward_coupling,
            homotopy_residual_tol,
            force_step=True,
        )
        causal = _surface_causality_violation(candidate) <= _surface_causality_limit(
            candidate
        )
        if candidate_residual <= homotopy_residual_tol and causal:
            anchor_green = candidate
            anchor_residual = candidate_residual
            anchor_newton_steps = candidate_steps
            break
        anchor_eta *= 4.0
    if anchor_green is None:
        raise ScienceError("could not establish a causal large-broadening surface anchor")

    current_green = anchor_green
    current_eta = anchor_eta
    residual = anchor_residual
    total_newton_steps = anchor_newton_steps
    homotopy_steps = 0
    step_fraction = 0.1
    previous_green: np.ndarray | None = None
    previous_z: complex | None = None
    while current_eta > eta:
        if homotopy_steps >= MAX_SURFACE_HOMOTOPY_STEPS:
            raise ScienceError(
                f"causal surface homotopy exceeded {MAX_SURFACE_HOMOTOPY_STEPS} steps"
            )
        next_eta = max(eta, current_eta * (1.0 - step_fraction))
        current_z = complex(energy, current_eta)
        next_z = complex(energy, next_eta)
        predicted_green = _surface_tangent_predictor(
            current_green,
            current_z,
            next_z,
            h0,
            outward_coupling,
            previous_green,
            previous_z,
        )
        candidate, candidate_residual, candidate_steps = _refine_surface_newton(
            predicted_green,
            next_z,
            h0,
            outward_coupling,
            homotopy_residual_tol,
            force_step=True,
        )
        causal = _surface_causality_violation(candidate) <= _surface_causality_limit(
            candidate
        )
        if candidate_residual > homotopy_residual_tol or not causal:
            step_fraction *= 0.5
            if step_fraction < 1.0e-5:
                violation = _surface_causality_violation(candidate)
                raise ScienceError(
                    "causal surface homotopy failed at "
                    f"eta={next_eta:.3e} (residual={candidate_residual:.3e}, "
                    f"causality_violation={violation:.3e})"
                )
            continue
        previous_green = current_green
        previous_z = current_z
        current_green = candidate
        current_eta = next_eta
        residual = candidate_residual
        total_newton_steps += candidate_steps
        homotopy_steps += 1
        step_fraction = min(0.1, step_fraction * 1.25)

    return current_green, residual, total_newton_steps, homotopy_steps


def surface_gf(
    h0: Any,
    outward_coupling: Any,
    energy: float,
    eta: float,
    *,
    decimation_tol: float = DEFAULT_DECIMATION_TOL,
    residual_tol: float = DEFAULT_SURFACE_RESIDUAL_TOL,
    max_iter: int = DEFAULT_MAX_SURFACE_ITERATIONS,
    return_info: bool = False,
):
    """Compute a retarded semi-infinite surface Green function.

    The returned matrix satisfies

    ``g = inv(z I - H0 - B g B^H)``, where ``z = energy + i*eta``.

    The Lopez-Sancho updates are simultaneous and never invert the coupling,
    so singular and zero coupling blocks are supported.
    """

    h0_array = _square_complex_matrix(h0, "h0")
    coupling = _square_complex_matrix(
        outward_coupling, "outward_coupling", size=h0_array.shape[0]
    )
    energy_value = _finite_real(energy, "energy")
    eta_value = _finite_real(eta, "eta")
    if eta_value <= 0.0:
        _fail("eta", "must be positive")
    decimation_tol = _finite_real(decimation_tol, "decimation_tol")
    residual_tol = _finite_real(residual_tol, "residual_tol")
    if decimation_tol <= 0.0 or residual_tol <= 0.0:
        raise ScienceError("surface tolerances must be positive")
    max_iter = _positive_int(max_iter, "max_iter")

    z = complex(energy_value, eta_value)
    scale = max(
        abs(z),
        float(np.max(np.abs(h0_array))),
        float(np.max(np.abs(coupling))),
        np.finfo(np.float64).tiny,
    )
    z_scaled = z / scale
    h0_scaled = h0_array / scale
    alpha = coupling / scale
    beta = coupling.conj().T / scale
    epsilon_surface = h0_scaled.copy()
    epsilon_bulk = h0_scaled.copy()
    identity = np.eye(h0_array.shape[0], dtype=np.complex128)

    last_residual = math.inf
    last_decimation_error = math.inf
    last_g: np.ndarray | None = None
    decimation_failure: str | None = None

    for iteration in range(1, max_iter + 1):
        bulk_operator = z_scaled * identity - epsilon_bulk
        try:
            solved_alpha = np.linalg.solve(bulk_operator, alpha)
            solved_beta = np.linalg.solve(bulk_operator, beta)
        except np.linalg.LinAlgError:
            decimation_failure = f"bulk solve failed at iteration {iteration}"
            break

        surface_delta = alpha @ solved_beta
        bulk_delta = surface_delta + beta @ solved_alpha
        epsilon_surface_new = epsilon_surface + surface_delta
        epsilon_bulk_new = epsilon_bulk + bulk_delta
        alpha_new = alpha @ solved_alpha
        beta_new = beta @ solved_beta

        arrays = (
            epsilon_surface_new,
            epsilon_bulk_new,
            alpha_new,
            beta_new,
        )
        if not all(np.all(np.isfinite(array)) for array in arrays):
            decimation_failure = f"decimation became non-finite at iteration {iteration}"
            break

        try:
            g_scaled = np.linalg.solve(z_scaled * identity - epsilon_surface_new, identity)
        except np.linalg.LinAlgError:
            decimation_failure = f"surface solve failed at iteration {iteration}"
            break
        last_g = g_scaled / scale
        if not np.all(np.isfinite(last_g)):
            decimation_failure = f"surface result became non-finite at iteration {iteration}"
            break

        last_residual = _surface_equation_residual(last_g, z, h0_array, coupling)
        coupling_scale = max(
            1.0,
            float(np.linalg.norm(epsilon_surface_new, ord="fro")),
            float(np.linalg.norm(epsilon_bulk_new, ord="fro")),
            abs(z_scaled),
        )
        last_decimation_error = max(
            float(np.linalg.norm(surface_delta, ord="fro")),
            float(np.linalg.norm(bulk_delta, ord="fro")),
            float(np.linalg.norm(alpha_new, ord="fro")),
            float(np.linalg.norm(beta_new, ord="fro")),
        ) / coupling_scale

        epsilon_surface = epsilon_surface_new
        epsilon_bulk = epsilon_bulk_new
        alpha = alpha_new
        beta = beta_new

        newton_steps = 0
        if last_decimation_error <= decimation_tol and last_residual > residual_tol:
            last_g, last_residual, newton_steps = _refine_surface_newton(
                last_g, z, h0_array, coupling, residual_tol
            )

        if last_decimation_error <= decimation_tol and last_residual <= residual_tol:
            causality_violation = _surface_causality_violation(last_g)
            homotopy_steps = 0
            small_relative_broadening = eta_value / scale <= 1.0e-8
            if (
                causality_violation > _surface_causality_limit(last_g)
                or small_relative_broadening
            ):
                (
                    recovered_scaled,
                    last_residual,
                    recovery_newton_steps,
                    homotopy_steps,
                ) = _recover_causal_surface(
                    h0_scaled,
                    coupling / scale,
                    energy_value / scale,
                    eta_value / scale,
                    residual_tol,
                )
                last_g = recovered_scaled / scale
                newton_steps += recovery_newton_steps
                causality_violation = _surface_causality_violation(last_g)
            info = {
                "iterations": iteration,
                "newton_steps": newton_steps,
                "homotopy_steps": homotopy_steps,
                "residual": last_residual,
                "decimation_error": last_decimation_error,
                "causality_violation": causality_violation,
            }
            return (last_g, info) if return_info else last_g

    try:
        recovered_scaled, recovered_residual, recovery_newton_steps, homotopy_steps = (
            _recover_causal_surface(
                h0_scaled,
                coupling / scale,
                energy_value / scale,
                eta_value / scale,
                residual_tol,
            )
        )
    except ScienceError as recovery_error:
        failure_detail = (
            f"; decimation failure: {decimation_failure}"
            if decimation_failure is not None
            else ""
        )
        raise ScienceError(
            "surface decimation did not converge after "
            f"{max_iter} iterations (residual={last_residual:.3e}, "
            f"decimation_error={last_decimation_error:.3e}){failure_detail}; "
            f"causal recovery also failed: {recovery_error}"
        ) from recovery_error
    recovered = recovered_scaled / scale
    info = {
        "iterations": max_iter,
        "newton_steps": recovery_newton_steps,
        "homotopy_steps": homotopy_steps,
        "residual": recovered_residual,
        "decimation_error": last_decimation_error,
        "causality_violation": _surface_causality_violation(recovered),
    }
    return (recovered, info) if return_info else recovered


def _device_hamiltonian(
    instance: Mapping[str, Any], h0: np.ndarray, h1: np.ndarray, basis_site: np.ndarray
) -> np.ndarray:
    cells = int(instance["device"]["cells"])
    basis_size = h0.shape[0]
    h_device = np.zeros((cells * basis_size, cells * basis_size), dtype=np.complex128)

    potentials = np.asarray(instance["device"]["site_potential"], dtype=np.float64)
    for cell in range(cells):
        block_slice = slice(cell * basis_size, (cell + 1) * basis_size)
        block = h0.copy()
        block[np.diag_indices(basis_size)] += potentials[cell, basis_site]
        h_device[block_slice, block_slice] = block

    for cell, scale_value in enumerate(instance["device"]["bond_scale"]):
        left_slice = slice(cell * basis_size, (cell + 1) * basis_size)
        right_slice = slice((cell + 1) * basis_size, (cell + 2) * basis_size)
        coupling = float(scale_value) * h1
        h_device[left_slice, right_slice] = coupling
        h_device[right_slice, left_slice] = coupling.conj().T
    return h_device


def _canonical_instance_hash(instance: Mapping[str, Any]) -> str:
    stored = instance.get("_input_sha256")
    if isinstance(stored, str) and _SHA256_RE.fullmatch(stored):
        return stored
    raise ScienceError(
        "raw input SHA-256 is unavailable; call load_instance(path) before solve_instance"
    )


def solve_instance(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Compute all trusted reference arrays and output diagnostics.

    The mapping must be the unmodified object returned by ``load_instance``;
    that is what binds ``input_sha256`` to the raw public input bytes.
    """

    validate_instance(instance)
    input_digest = _canonical_instance_hash(instance)
    h0, h1, basis_site = assemble_blocks(instance)
    phases = np.asarray(instance["phase_grid"], dtype=np.float64)
    energies = np.asarray(instance["energy_grid"], dtype=np.float64)
    eta = float(instance["eta"])
    basis_size = h0.shape[0]
    cells = int(instance["device"]["cells"])

    band_values = np.empty((len(phases), basis_size), dtype=np.float64)
    for phase_index, phase in enumerate(phases):
        h_phase = _bloch_matrix(h0, h1, float(phase))
        band_values[phase_index] = np.linalg.eigvalsh(h_phase)

    h_device = _device_hamiltonian(instance, h0, h1, basis_site)
    hermiticity_residuals = [
        _hermiticity_residual(h0),
        _hermiticity_residual(h_device),
    ]

    sigma_left = np.empty((len(energies), basis_size, basis_size), dtype=np.complex128)
    sigma_right = np.empty_like(sigma_left)
    dos_total = np.empty(len(energies), dtype=np.float64)
    ldos_cells = np.empty((len(energies), cells), dtype=np.float64)
    transmission = np.empty(len(energies), dtype=np.float64)
    surface_residual_left = np.empty(len(energies), dtype=np.float64)
    surface_residual_right = np.empty(len(energies), dtype=np.float64)
    surface_iterations_left = np.empty(len(energies), dtype=np.int64)
    surface_iterations_right = np.empty(len(energies), dtype=np.int64)

    outward_left = h1.conj().T
    outward_right = h1
    contact_left = float(instance["device"]["contact_scale_left"]) * h1.conj().T
    contact_right = float(instance["device"]["contact_scale_right"]) * h1
    device_identity = np.eye(h_device.shape[0], dtype=np.complex128)

    for energy_index, energy in enumerate(energies):
        g_left, left_info = surface_gf(
            h0, outward_left, float(energy), eta, return_info=True
        )
        g_right, right_info = surface_gf(
            h0, outward_right, float(energy), eta, return_info=True
        )
        current_sigma_left = contact_left @ g_left @ contact_left.conj().T
        current_sigma_right = contact_right @ g_right @ contact_right.conj().T
        sigma_left[energy_index] = current_sigma_left
        sigma_right[energy_index] = current_sigma_right
        surface_residual_left[energy_index] = float(left_info["residual"])
        surface_residual_right[energy_index] = float(right_info["residual"])
        surface_iterations_left[energy_index] = int(left_info["iterations"])
        surface_iterations_right[energy_index] = int(right_info["iterations"])

        z = complex(float(energy), eta)
        inverse_green = z * device_identity - h_device
        inverse_green[:basis_size, :basis_size] -= current_sigma_left
        inverse_green[-basis_size:, -basis_size:] -= current_sigma_right
        try:
            green = np.linalg.solve(inverse_green, device_identity)
        except np.linalg.LinAlgError as exc:
            raise ScienceError(f"device Green function solve failed at energy index {energy_index}") from exc
        if not np.all(np.isfinite(green)):
            raise ScienceError(f"device Green function is non-finite at energy index {energy_index}")

        dos_total[energy_index] = -float(np.imag(np.trace(green))) / math.pi
        for cell in range(cells):
            cell_slice = slice(cell * basis_size, (cell + 1) * basis_size)
            ldos_cells[energy_index, cell] = (
                -float(np.imag(np.trace(green[cell_slice, cell_slice]))) / math.pi
            )

        gamma_left = 1.0j * (current_sigma_left - current_sigma_left.conj().T)
        gamma_right = 1.0j * (current_sigma_right - current_sigma_right.conj().T)
        green_first_last = green[:basis_size, -basis_size:]
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

    result: dict[str, Any] = {
        "h0": h0,
        "h1": h1,
        "basis_site": basis_site,
        "energies": energies,
        "sigma_left": sigma_left,
        "sigma_right": sigma_right,
        "phases": phases,
        "bands": band_values,
        "dos_total": dos_total,
        "ldos_cells": ldos_cells,
        "transmission": transmission,
        "diagnostics": {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "model_id": instance["model_id"],
            "input_sha256": input_digest,
            "basis_size": basis_size,
            "device_cells": cells,
            "max_surface_residual": float(
                max(np.max(surface_residual_left), np.max(surface_residual_right))
            ),
            "max_hermiticity_residual": float(max(hermiticity_residuals)),
        },
        "_surface_residual_left": surface_residual_left,
        "_surface_residual_right": surface_residual_right,
        "_surface_iterations_left": surface_iterations_left,
        "_surface_iterations_right": surface_iterations_right,
        "_device_hamiltonian": h_device,
    }
    _validate_reference_result(result)
    return result


def _finite_array(
    value: Any,
    name: str,
    *,
    ndim: int | None = None,
    dtype: Any | None = None,
    c_contiguous: bool = False,
) -> np.ndarray:
    array = np.asarray(value)
    if ndim is not None and array.ndim != ndim:
        _fail(name, f"must have rank {ndim}")
    if array.dtype.kind not in "biufc":
        _fail(name, "must be a numeric array")
    if dtype is not None and array.dtype != np.dtype(dtype):
        _fail(name, f"must have dtype {np.dtype(dtype)}, got {array.dtype}")
    if c_contiguous and not array.flags.c_contiguous:
        _fail(name, "must be C-contiguous")
    if not np.all(np.isfinite(array)):
        _fail(name, "contains a non-finite value")
    return array


def _validate_diagnostics(diagnostics: Any) -> dict[str, Any]:
    diagnostics = _require_mapping(diagnostics, "diagnostics")
    _require_exact_keys(diagnostics, _DIAGNOSTIC_KEYS, "diagnostics")
    if diagnostics["schema_version"] != OUTPUT_SCHEMA_VERSION:
        _fail("diagnostics.schema_version", f"must equal {OUTPUT_SCHEMA_VERSION!r}")
    _nonempty_string(diagnostics["model_id"], "diagnostics.model_id")
    digest = diagnostics["input_sha256"]
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        _fail("diagnostics.input_sha256", "must be 64 lowercase hexadecimal characters")
    _positive_int(diagnostics["basis_size"], "diagnostics.basis_size")
    _positive_int(diagnostics["device_cells"], "diagnostics.device_cells")
    for key in ("max_surface_residual", "max_hermiticity_residual"):
        value = _finite_real(diagnostics[key], f"diagnostics.{key}")
        if value < 0.0:
            _fail(f"diagnostics.{key}", "must be nonnegative")
    return dict(diagnostics)


def _validate_reference_result(result: Mapping[str, Any]) -> None:
    required = {
        "h0",
        "h1",
        "basis_site",
        "energies",
        "sigma_left",
        "sigma_right",
        "phases",
        "bands",
        "dos_total",
        "ldos_cells",
        "transmission",
        "diagnostics",
    }
    missing = required - set(result)
    if missing:
        _fail("result", f"missing keys {sorted(missing)!r}")

    h0 = _finite_array(
        result["h0"], "h0", ndim=2, dtype=np.complex128, c_contiguous=True
    )
    h1 = _finite_array(
        result["h1"], "h1", ndim=2, dtype=np.complex128, c_contiguous=True
    )
    if h0.shape[0] == 0 or h0.shape[0] != h0.shape[1] or h1.shape != h0.shape:
        _fail("h0/h1", "must be equally shaped, nonempty square matrices")
    basis_size = h0.shape[0]
    basis_site = _finite_array(
        result["basis_site"],
        "basis_site",
        ndim=1,
        dtype=np.int64,
        c_contiguous=True,
    )
    if basis_site.shape != (basis_size,):
        _fail("basis_site", f"must be an integer array with shape ({basis_size},)")
    if np.any(basis_site < 0) or np.any(np.diff(basis_site) < 0):
        _fail("basis_site", "must be nonnegative and nondecreasing")

    energies = _finite_array(
        result["energies"], "energies", ndim=1, dtype=np.float64, c_contiguous=True
    )
    phases = _finite_array(
        result["phases"], "phases", ndim=1, dtype=np.float64, c_contiguous=True
    )
    if energies.size == 0 or phases.size == 0:
        _fail("energies/phases", "must be nonempty")
    energy_count = energies.size
    phase_count = phases.size
    sigma_shape = (energy_count, basis_size, basis_size)
    for key in ("sigma_left", "sigma_right"):
        value = _finite_array(
            result[key], key, ndim=3, dtype=np.complex128, c_contiguous=True
        )
        if value.shape != sigma_shape:
            _fail(key, f"must have shape {sigma_shape}")
    if _finite_array(
        result["bands"], "bands", ndim=2, dtype=np.float64, c_contiguous=True
    ).shape != (phase_count, basis_size):
        _fail("bands", f"must have shape ({phase_count}, {basis_size})")
    if _finite_array(
        result["dos_total"],
        "dos_total",
        ndim=1,
        dtype=np.float64,
        c_contiguous=True,
    ).shape != (energy_count,):
        _fail("dos_total", f"must have shape ({energy_count},)")
    if _finite_array(
        result["transmission"],
        "transmission",
        ndim=1,
        dtype=np.float64,
        c_contiguous=True,
    ).shape != (energy_count,):
        _fail("transmission", f"must have shape ({energy_count},)")
    ldos = _finite_array(
        result["ldos_cells"],
        "ldos_cells",
        ndim=2,
        dtype=np.float64,
        c_contiguous=True,
    )
    if ldos.shape[0] != energy_count or ldos.shape[1] == 0:
        _fail("ldos_cells", f"must have shape ({energy_count}, L) with L >= 1")

    diagnostics = _validate_diagnostics(result["diagnostics"])
    if diagnostics["basis_size"] != basis_size:
        _fail("diagnostics.basis_size", "does not match Hamiltonian arrays")
    if diagnostics["device_cells"] != ldos.shape[1]:
        _fail("diagnostics.device_cells", "does not match ldos_cells")


def write_outputs(output_dir: str | os.PathLike[str], result: Mapping[str, Any]) -> None:
    """Write the exact participant artifact contract from a solved result."""

    _validate_reference_result(result)
    destination = Path(output_dir)
    if destination.is_symlink():
        raise ScienceError(f"output directory must not be a symlink: {destination}")
    if destination.exists() and not destination.is_dir():
        raise ScienceError(f"output path is not a directory: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    np.savez_compressed(
        destination / "hamiltonian.npz",
        h0=np.ascontiguousarray(result["h0"], dtype=np.complex128),
        h1=np.ascontiguousarray(result["h1"], dtype=np.complex128),
        basis_site=np.ascontiguousarray(result["basis_site"], dtype=np.int64),
    )
    np.savez_compressed(
        destination / "self_energies.npz",
        energies=np.ascontiguousarray(result["energies"], dtype=np.float64),
        sigma_left=np.ascontiguousarray(result["sigma_left"], dtype=np.complex128),
        sigma_right=np.ascontiguousarray(result["sigma_right"], dtype=np.complex128),
    )
    np.savez_compressed(
        destination / "spectra.npz",
        phases=np.ascontiguousarray(result["phases"], dtype=np.float64),
        bands=np.ascontiguousarray(result["bands"], dtype=np.float64),
        energies=np.ascontiguousarray(result["energies"], dtype=np.float64),
        dos_total=np.ascontiguousarray(result["dos_total"], dtype=np.float64),
        ldos_cells=np.ascontiguousarray(result["ldos_cells"], dtype=np.float64),
        transmission=np.ascontiguousarray(result["transmission"], dtype=np.float64),
    )
    diagnostics_text = json.dumps(
        dict(result["diagnostics"]),
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    (destination / "diagnostics.json").write_text(diagnostics_text, encoding="utf-8", newline="\n")


def _preflight_npz(path: Path, expected_keys: set[str]) -> int:
    if path.is_symlink() or not path.is_file():
        raise ScienceError(f"required output is not a regular file: {path}")
    if path.stat().st_size > MAX_NPZ_BYTES:
        raise ScienceError(f"output exceeds {MAX_NPZ_BYTES} bytes: {path}")
    expected_members = {f"{key}.npy" for key in expected_keys}
    try:
        with zipfile.ZipFile(path, mode="r") as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                _fail(path.name, "contains duplicate physical ZIP members")
            if set(names) != expected_members or len(names) != len(expected_members):
                _fail(
                    path.name,
                    f"members must be exactly {sorted(expected_members)!r}, got {sorted(names)!r}",
                )
            if any(member.is_dir() or member.flag_bits & 0x1 for member in members):
                _fail(path.name, "must not contain directories or encrypted members")
            uncompressed_size = sum(member.file_size for member in members)
    except (OSError, ValueError, zipfile.BadZipFile, ScienceError) as exc:
        if isinstance(exc, ScienceError):
            raise
        raise ScienceError(f"invalid NPZ container {path.name}: {exc}") from exc
    if uncompressed_size > MAX_NPZ_BYTES:
        raise ScienceError(
            f"uncompressed arrays in {path.name} exceed {MAX_NPZ_BYTES} bytes"
        )
    return uncompressed_size


def _load_npz_exact(path: Path, expected_keys: set[str]) -> dict[str, np.ndarray]:
    _preflight_npz(path, expected_keys)
    archive: Any = None
    try:
        archive = np.load(path, allow_pickle=False)
        if not hasattr(archive, "files") or not hasattr(archive, "close"):
            _fail(path.name, "is not an NPZ archive")
        files = list(archive.files)
        if len(files) != len(set(files)) or set(files) != expected_keys:
            _fail(
                path.name,
                f"keys must be exactly {sorted(expected_keys)!r}, got {sorted(files)!r}",
            )
        return {key: np.array(archive[key], copy=True) for key in files}
    except (OSError, TypeError, AttributeError, ValueError, ScienceError) as exc:
        if isinstance(exc, ScienceError):
            raise
        raise ScienceError(f"could not read {path.name}: {exc}") from exc
    finally:
        if archive is not None and hasattr(archive, "close"):
            archive.close()


def read_outputs(
    output_dir: str | os.PathLike[str],
    instance: Mapping[str, Any] | str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Read participant outputs and enforce their structural/finite contract."""

    source = Path(output_dir)
    if source.is_symlink() or not source.is_dir():
        raise ScienceError(f"output path is not a regular directory: {source}")
    diagnostics_path = source / "diagnostics.json"
    if diagnostics_path.is_symlink() or not diagnostics_path.is_file():
        raise ScienceError(f"required output is not a regular file: {diagnostics_path}")
    if diagnostics_path.stat().st_size > MAX_JSON_BYTES:
        raise ScienceError(f"diagnostics exceeds {MAX_JSON_BYTES} bytes: {diagnostics_path}")
    npz_specs = (
        (source / "hamiltonian.npz", {"h0", "h1", "basis_site"}),
        (
            source / "self_energies.npz",
            {"energies", "sigma_left", "sigma_right"},
        ),
        (
            source / "spectra.npz",
            {"phases", "bands", "energies", "dos_total", "ldos_cells", "transmission"},
        ),
    )
    uncompressed_total = sum(_preflight_npz(path, keys) for path, keys in npz_specs)
    if uncompressed_total > MAX_NPZ_BYTES:
        raise ScienceError(
            f"uncompressed required arrays exceed {MAX_NPZ_BYTES} bytes in total"
        )
    compressed_total = diagnostics_path.stat().st_size + sum(
        path.stat().st_size for path, _keys in npz_specs
    )
    if compressed_total > MAX_NPZ_BYTES:
        raise ScienceError(f"required output artifacts exceed {MAX_NPZ_BYTES} bytes")
    hamiltonian = _load_npz_exact(*npz_specs[0])
    self_energies = _load_npz_exact(*npz_specs[1])
    spectra = _load_npz_exact(*npz_specs[2])
    try:
        diagnostics = json.loads(
            diagnostics_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ScienceError) as exc:
        raise ScienceError(f"could not read diagnostics.json: {exc}") from exc

    spectra_energies = _finite_array(
        spectra["energies"],
        "spectra.energies",
        ndim=1,
        dtype=np.float64,
        c_contiguous=True,
    )
    if not np.array_equal(self_energies["energies"], spectra_energies):
        _fail("energies", "self_energies.npz and spectra.npz must agree exactly")
    result = {
        **hamiltonian,
        "energies": self_energies["energies"],
        "sigma_left": self_energies["sigma_left"],
        "sigma_right": self_energies["sigma_right"],
        "phases": spectra["phases"],
        "bands": spectra["bands"],
        "dos_total": spectra["dos_total"],
        "ldos_cells": spectra["ldos_cells"],
        "transmission": spectra["transmission"],
        "diagnostics": diagnostics,
    }
    _validate_reference_result(result)

    if instance is not None:
        expected_instance = load_instance(instance) if isinstance(instance, (str, os.PathLike)) else instance
        validate_instance(expected_instance)
        _h0, _h1, expected_basis_site = assemble_blocks(expected_instance)
        expected_basis_size = expected_basis_site.size
        expected_cells = int(expected_instance["device"]["cells"])
        expected_energy_count = len(expected_instance["energy_grid"])
        expected_phase_count = len(expected_instance["phase_grid"])
        if result["h0"].shape != (expected_basis_size, expected_basis_size):
            _fail("h0", "shape does not match the instance basis")
        if result["energies"].shape != (expected_energy_count,):
            _fail("energies", "shape does not match the instance energy grid")
        if result["phases"].shape != (expected_phase_count,):
            _fail("phases", "shape does not match the instance phase grid")
        if result["ldos_cells"].shape != (expected_energy_count, expected_cells):
            _fail("ldos_cells", "shape does not match the instance device")
        if result["diagnostics"]["model_id"] != expected_instance["model_id"]:
            _fail("diagnostics.model_id", "does not match the input instance")
        if result["diagnostics"]["input_sha256"] != _canonical_instance_hash(expected_instance):
            _fail("diagnostics.input_sha256", "does not match the input instance")
        if not np.array_equal(result["basis_site"], expected_basis_site):
            _fail("basis_site", "values do not match the instance basis order")
        if not np.array_equal(
            result["energies"], np.asarray(expected_instance["energy_grid"], dtype=np.float64)
        ):
            _fail("energies", "values/order do not match the instance energy_grid")
        if not np.array_equal(
            result["phases"], np.asarray(expected_instance["phase_grid"], dtype=np.float64)
        ):
            _fail("phases", "values/order do not match the instance phase_grid")

    return result


def reference_arrays(
    instance: Mapping[str, Any] | str | os.PathLike[str],
) -> dict[str, Any]:
    """Return the trusted result for a path or a mapping from ``load_instance``."""

    loaded = load_instance(instance) if isinstance(instance, (str, os.PathLike)) else instance
    return solve_instance(loaded)


__all__ = [
    "DEFAULT_DECIMATION_TOL",
    "DEFAULT_MAX_SURFACE_ITERATIONS",
    "DEFAULT_SURFACE_RESIDUAL_TOL",
    "INPUT_SCHEMA_VERSION",
    "OUTPUT_SCHEMA_VERSION",
    "ScienceError",
    "assemble_blocks",
    "bands",
    "load_instance",
    "read_outputs",
    "reference_arrays",
    "solve_instance",
    "surface_gf",
    "validate_instance",
    "write_outputs",
]
