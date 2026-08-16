#!/usr/bin/env python3
"""Scientific metamorphic checks for the disclosed Hamiltonian workflow."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path

import numpy as np


def load_solver(task_root: Path):
    path = task_root / "author" / "reference_solver" / "solve.py"
    spec = importlib.util.spec_from_file_location("metamorphic_dense_solver", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load dense solver")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def max_observable_difference(left: dict[str, float], right: dict[str, float]) -> float:
    return max(abs(left[key] - right[key]) for key in left)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("participant", type=Path)
    args = parser.parse_args()
    task_root = Path(__file__).resolve().parents[1]
    solver = load_solver(task_root)
    loaded = solver.load_inputs(args.participant.resolve())
    config = loaded["config"]
    sites = loaded["sites"]
    bonds = loaded["bonds"]
    onsite = loaded["onsite"]
    realization = loaded["realizations"][4]
    order = int(config["basis_order"])
    center = float(realization["center"])
    half_width = float(realization["half_width"])
    bessel = solver.load_bessel(args.participant.resolve())
    psi0 = solver.initial_state(config, sites, "none")
    hamiltonian = solver.build_hamiltonian(
        config, sites, bonds, onsite, realization, "none"
    )
    baseline_basis = solver.make_basis(
        hamiltonian, psi0, center, half_width, order, "none"
    )
    probe_time = 1.73
    baseline_state = solver.contract(
        baseline_basis, center, half_width, probe_time, bessel, "none"
    )
    baseline_observables = solver.observables(baseline_state, sites)
    results: dict[str, dict[str, float | str]] = {}

    phase = np.exp(0.731j)
    phase_basis = solver.make_basis(
        hamiltonian, phase * psi0, center, half_width, order, "none"
    )
    phase_error = float(np.max(np.abs(phase_basis - phase * baseline_basis)))
    phase_state = solver.contract(phase_basis, center, half_width, probe_time, bessel, "none")
    phase_observable_error = max_observable_difference(
        baseline_observables, solver.observables(phase_state, sites)
    )
    if phase_error > 3.0e-13 or phase_observable_error > 3.0e-13:
        raise AssertionError("global-phase covariance failed")
    results["global_phase"] = {
        "basis_covariance_max_abs": phase_error,
        "observable_invariance_max_abs": phase_observable_error,
        "status": "pass",
    }

    shift = 0.317
    shifted_basis = solver.make_basis(
        hamiltonian + shift * np.eye(hamiltonian.shape[0]),
        psi0,
        center + shift,
        half_width,
        order,
        "none",
    )
    shift_basis_error = float(np.max(np.abs(shifted_basis - baseline_basis)))
    shifted_state = solver.contract(
        shifted_basis, center + shift, half_width, probe_time, bessel, "none"
    )
    shift_observable_error = max_observable_difference(
        baseline_observables, solver.observables(shifted_state, sites)
    )
    if shift_basis_error > 3.0e-13 or shift_observable_error > 3.0e-13:
        raise AssertionError("uniform-energy-shift invariance failed")
    results["uniform_energy_shift"] = {
        "basis_invariance_max_abs": shift_basis_error,
        "observable_invariance_max_abs": shift_observable_error,
        "status": "pass",
    }

    scale = 1.37
    scaled_basis = solver.make_basis(
        scale * hamiltonian,
        psi0,
        scale * center,
        scale * half_width,
        order,
        "none",
    )
    scale_basis_error = float(np.max(np.abs(scaled_basis - baseline_basis)))
    scaled_state = solver.contract(
        scaled_basis,
        scale * center,
        scale * half_width,
        probe_time / scale,
        bessel,
        "none",
    )
    scale_observable_error = max_observable_difference(
        baseline_observables, solver.observables(scaled_state, sites)
    )
    if scale_basis_error > 3.0e-13 or scale_observable_error > 3.0e-13:
        raise AssertionError("Hamiltonian-scaling/time reciprocity failed")
    results["hamiltonian_scaling_time"] = {
        "basis_invariance_max_abs": scale_basis_error,
        "observable_invariance_max_abs": scale_observable_error,
        "status": "pass",
    }

    translated_sites = copy.deepcopy(sites)
    dx_shift, dy_shift = 2.3, -1.4
    for site in translated_sites:
        site["x"] = str(float(site["x"]) + dx_shift)
        site["y"] = str(float(site["y"]) + dy_shift)
    translated_config = copy.deepcopy(config)
    translated_config["initial_state"]["x0"] += dx_shift
    translated_config["initial_state"]["y0"] += dy_shift
    translated_h = solver.build_hamiltonian(
        translated_config, translated_sites, bonds, onsite, realization, "none"
    )
    translated_psi = solver.initial_state(translated_config, translated_sites, "none")
    expected_phase = np.exp(
        1.0j
        * (
            float(config["initial_state"]["kx"]) * dx_shift
            + float(config["initial_state"]["ky"]) * dy_shift
        )
    )
    translation_h_error = float(np.max(np.abs(translated_h - hamiltonian)))
    translation_packet_error = float(np.max(np.abs(translated_psi - expected_phase * psi0)))
    translated_basis = solver.make_basis(
        translated_h, translated_psi, center, half_width, order, "none"
    )
    translated_state = solver.contract(
        translated_basis, center, half_width, probe_time, bessel, "none"
    )
    translated_observables = solver.observables(translated_state, translated_sites)
    expected = dict(baseline_observables)
    expected["mean_x"] += dx_shift
    expected["mean_y"] += dy_shift
    expected["second_x"] += 2.0 * dx_shift * baseline_observables["mean_x"] + dx_shift**2
    expected["second_y"] += 2.0 * dy_shift * baseline_observables["mean_y"] + dy_shift**2
    expected["second_xy"] += (
        dx_shift * baseline_observables["mean_y"]
        + dy_shift * baseline_observables["mean_x"]
        + dx_shift * dy_shift
    )
    translation_moment_error = max_observable_difference(expected, translated_observables)
    if (
        translation_h_error > 1.0e-14
        or translation_packet_error > 3.0e-15
        or translation_moment_error > 1.0e-12
    ):
        raise AssertionError("coordinate-translation relation failed")
    results["coordinate_translation"] = {
        "hamiltonian_invariance_max_abs": translation_h_error,
        "packet_phase_covariance_max_abs": translation_packet_error,
        "moment_relation_max_abs": translation_moment_error,
        "status": "pass",
    }

    zero_config = copy.deepcopy(config)
    zero_config["soc_lambda"] = 0.0
    zero_config["initial_state"]["theta"] = 0.0
    zero_state = solver.initial_state(zero_config, sites, "none")
    zero_h = solver.build_hamiltonian(zero_config, sites, bonds, onsite, realization, "none")
    zero_eigenvalues = np.linalg.eigvalsh(zero_h)
    zero_center = float(0.5 * (zero_eigenvalues[0] + zero_eigenvalues[-1]))
    zero_half_width = float((zero_eigenvalues[-1] - zero_eigenvalues[0]) / (2.0 * 0.94))
    zero_basis = solver.make_basis(
        zero_h, zero_state, zero_center, zero_half_width, order, "none"
    )
    norm_error = 0.0
    polarization_error = 0.0
    transverse_error = 0.0
    for time in (0.0, 0.37, 1.17, 2.23):
        state = solver.contract(zero_basis, zero_center, zero_half_width, time, bessel, "none")
        observed = solver.observables(state, sites)
        norm_error = max(norm_error, abs(observed["norm"] - 1.0))
        polarization_error = max(polarization_error, abs(observed["sz"] - observed["norm"]))
        transverse_error = max(transverse_error, abs(observed["sx"]), abs(observed["sy"]))
    if norm_error > 3.0e-12 or polarization_error > 3.0e-13 or transverse_error > 3.0e-13:
        raise AssertionError("norm/zero-SOC invariant failed")
    results["norm_and_zero_soc"] = {
        "norm_max_abs_error": norm_error,
        "up_polarization_max_abs_error": polarization_error,
        "transverse_spin_max_abs": transverse_error,
        "status": "pass",
    }

    hermiticity_error = float(np.max(np.abs(hamiltonian - hamiltonian.conj().T)))
    if hermiticity_error > 1.0e-14:
        raise AssertionError("Hermiticity invariant failed")
    results["hermiticity"] = {
        "max_abs_error": hermiticity_error,
        "status": "pass",
    }
    print(json.dumps(results, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
