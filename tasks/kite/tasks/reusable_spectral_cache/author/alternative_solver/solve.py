#!/usr/bin/env python3
"""Independent valid solver using a dense Hermitian spectral decomposition."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np


def load_io_module():
    path = Path(__file__).resolve().parents[1] / "reference_solver" / "solve.py"
    spec = importlib.util.spec_from_file_location("spectral_reference_io", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load shared artifact writer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def spectral_moments(participant: Path, manifest: dict, io_module) -> np.ndarray:
    systems = manifest["systems"]
    probe_count = int(manifest["probe_count"])
    moment_count = int(manifest["moment_count"])
    tau = np.zeros((len(systems), probe_count, moment_count), dtype=np.complex128)
    for system_index, system in enumerate(systems):
        onsite, edge_i, edge_j, edge_v, probes = io_module.read_system(
            participant, system, probe_count
        )
        n = int(system["dimension"])
        hamiltonian = np.diag(onsite.astype(np.complex128))
        hamiltonian[edge_i, edge_j] = edge_v
        hamiltonian[edge_j, edge_i] = edge_v.conjugate()
        eigenvalues, eigenvectors = np.linalg.eigh(hamiltonian)
        lower = float(system["spectral_lower"])
        upper = float(system["spectral_upper"])
        a = 0.5 * (upper - lower)
        b = 0.5 * (upper + lower)
        x = (eigenvalues - b) / a
        polynomial_previous = np.ones(n, dtype=np.float64)
        polynomial_current = x.copy()
        for probe_index, probe in enumerate(probes):
            spectral_weights = np.abs(eigenvectors.conjugate().T @ probe) ** 2
            tau[system_index, probe_index, 0] = np.dot(spectral_weights, polynomial_previous) / n
            if moment_count > 1:
                tau[system_index, probe_index, 1] = np.dot(spectral_weights, polynomial_current) / n
            previous = polynomial_previous.copy()
            current = polynomial_current.copy()
            for order in range(2, moment_count):
                following = 2.0 * x * current - previous
                tau[system_index, probe_index, order] = np.dot(spectral_weights, following) / n
                previous, current = current, following
    return tau


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--participant", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    participant = args.participant.resolve()
    manifest = json.loads((participant / "input" / "manifest.json").read_text(encoding="utf-8"))
    io_module = load_io_module()
    tau = spectral_moments(participant, manifest, io_module)
    io_module.write_outputs(participant, args.output.resolve(), manifest, tau)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
