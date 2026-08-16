#!/usr/bin/env python3
"""Deterministic small-system Heisenberg exact-diagonalization realism fixture.

This module is intentionally independent of the synthetic crossover generator.
It constructs the random-field spin-1/2 Heisenberg Hamiltonian in the fixed
zero-magnetization sector, diagonalizes it exactly, and emits complete raw
spectra using the participant packet representation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np


TASK_ROOT = Path(__file__).resolve().parents[2]
CASE_ID = "heisenberg_ed_fixed_sector"
SCHEMA_VERSION = "spectral-ed-realism/v1"
SEED = 14_110_660
SIZES = (8, 10)
CONTROLS = (0.75, 8.0)
TARGETS = (0.25, 0.50, 0.75)
REALIZATIONS = 12
PACKET_COLUMNS = (
    "packet_id",
    "realization_id",
    "size",
    "control",
    "target",
    "e_min",
    "e_max",
    "shift_energy",
    "keep_count",
    "eigen_offset",
    "eigen_count",
)


def _basis(size: int) -> tuple[list[int], dict[int, int]]:
    """Return the computational basis with exactly ``size / 2`` up spins."""

    if size % 2:
        raise ValueError("the zero-magnetization sector requires an even size")
    states = [state for state in range(1 << size) if state.bit_count() == size // 2]
    return states, {state: index for index, state in enumerate(states)}


def _hamiltonian(
    size: int,
    states: list[int],
    state_index: dict[int, int],
    fields: np.ndarray,
) -> np.ndarray:
    """Build H = sum_i S_i.S_(i+1) - sum_i fields_i S_i^z, periodically."""

    if fields.shape != (size,) or not np.all(np.isfinite(fields)):
        raise ValueError("invalid field vector")
    dimension = len(states)
    matrix = np.zeros((dimension, dimension), dtype=np.float64)
    for column, state in enumerate(states):
        diagonal = 0.0
        for site in range(size):
            neighbor = (site + 1) % size
            spin = 0.5 if (state >> site) & 1 else -0.5
            neighbor_spin = 0.5 if (state >> neighbor) & 1 else -0.5
            diagonal += spin * neighbor_spin - float(fields[site]) * spin
            if spin != neighbor_spin:
                flipped = state ^ (1 << site) ^ (1 << neighbor)
                matrix[state_index[flipped], column] += 0.5
        matrix[column, column] += diagonal
    if not np.array_equal(matrix, matrix.T):
        raise AssertionError("constructed Hamiltonian is not exactly symmetric")
    return matrix


def _packet_ratio(spectrum: np.ndarray, target: float, keep_count: int) -> float:
    """Compute mean adjacent-gap ratio after normalized-energy window selection."""

    e_min = float(np.min(spectrum))
    e_max = float(np.max(spectrum))
    target_energy = e_max + float(target) * (e_min - e_max)
    nearest = np.argsort(np.abs(spectrum - target_energy), kind="stable")[:keep_count]
    selected = np.sort(spectrum[nearest], kind="stable")
    gaps = np.diff(selected)
    if gaps.size < 3 or np.any(gaps <= 0.0) or not np.all(np.isfinite(gaps)):
        raise AssertionError("ED spectrum does not define valid adjacent-gap ratios")
    ratios = np.minimum(gaps[:-1], gaps[1:]) / np.maximum(gaps[:-1], gaps[1:])
    if not np.all((ratios >= 0.0) & (ratios <= 1.0)):
        raise AssertionError("adjacent-gap ratio escaped its mathematical bounds")
    return float(np.mean(ratios))


def _format_cell(value: object) -> object:
    if isinstance(value, float):
        return format(value, ".17g")
    return value


def _json_write(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def generate_ed_realism(output_root: Path) -> Path:
    """Generate the private exact-diagonalization realism fixture.

    Parameters
    ----------
    output_root:
        Task-package root. Files are written below
        ``private/realism/heisenberg_ed_fixed_sector``.

    Returns
    -------
    Path
        The generated case directory.
    """

    output_root = Path(output_root).resolve()
    case_dir = output_root / "private" / "realism" / CASE_ID
    case_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(SEED)
    rows: list[dict[str, object]] = []
    flat_energies: list[float] = []
    observed: dict[tuple[int, float, float], list[float]] = {}
    dimensions: dict[str, int] = {}
    spectrum_hashes: list[str] = []
    unique_spectrum_count = 0

    for size in SIZES:
        states, state_index = _basis(size)
        dimension = len(states)
        expected_dimension = math.comb(size, size // 2)
        if dimension != expected_dimension:
            raise AssertionError("fixed-sector basis has the wrong dimension")
        dimensions[str(size)] = dimension
        keep_count = 31 if size == 8 else 61

        # A realization is one deterministic direction in field space. Scaling
        # the same direction at weak and strong control reduces irrelevant Monte
        # Carlo noise without changing either marginal uniform distribution.
        unit_fields = rng.uniform(-1.0, 1.0, size=(REALIZATIONS, size))
        for realization in range(REALIZATIONS):
            for control in CONTROLS:
                fields = float(control) * unit_fields[realization]
                spectrum = np.linalg.eigvalsh(_hamiltonian(size, states, state_index, fields))
                if spectrum.shape != (dimension,) or not np.all(np.isfinite(spectrum)):
                    raise AssertionError("exact diagonalization returned an invalid spectrum")
                spectrum_hashes.append(hashlib.sha256(spectrum.tobytes(order="C")).hexdigest())
                unique_spectrum_count += 1
                e_min = float(spectrum[0])
                e_max = float(spectrum[-1])

                for target in TARGETS:
                    packet_index = len(rows)
                    # Store a complete spectrum in non-sorted order so that the
                    # fixture exercises participant-side sorting as well as the
                    # normalized target-energy convention.
                    shuffled = spectrum[rng.permutation(dimension)]
                    offset = len(flat_energies)
                    flat_energies.extend(float(value) for value in shuffled)
                    ratio = _packet_ratio(spectrum, target, keep_count)
                    observed.setdefault((size, float(control), float(target)), []).append(ratio)
                    target_energy = e_max + float(target) * (e_min - e_max)
                    rows.append(
                        {
                            "packet_id": f"ed{packet_index:04d}",
                            "realization_id": f"l{size:02d}_r{realization:03d}",
                            "size": size,
                            "control": float(control),
                            "target": float(target),
                            "e_min": e_min,
                            "e_max": e_max,
                            "shift_energy": target_energy,
                            "keep_count": keep_count,
                            "eigen_offset": offset,
                            "eigen_count": dimension,
                        }
                    )

    ratio_values = np.asarray([value for values in observed.values() for value in values])
    if ratio_values.size == 0 or not np.all((ratio_values >= 0.0) & (ratio_values <= 1.0)):
        raise AssertionError("bounded adjacent-gap-ratio gate failed")

    group_summaries: list[dict[str, float | int]] = []
    differences: list[float] = []
    weak_control, strong_control = CONTROLS
    for size in SIZES:
        for target in TARGETS:
            weak_values = np.asarray(observed[(size, weak_control, target)], dtype=np.float64)
            strong_values = np.asarray(observed[(size, strong_control, target)], dtype=np.float64)
            weak_mean = float(np.mean(weak_values))
            strong_mean = float(np.mean(strong_values))
            difference = weak_mean - strong_mean
            differences.append(difference)
            group_summaries.append(
                {
                    "size": size,
                    "target": float(target),
                    "weak_control": float(weak_control),
                    "strong_control": float(strong_control),
                    "weak_mean_r": weak_mean,
                    "strong_mean_r": strong_mean,
                    "weak_minus_strong": difference,
                    "weak_sem": float(np.std(weak_values, ddof=1) / math.sqrt(weak_values.size)),
                    "strong_sem": float(np.std(strong_values, ddof=1) / math.sqrt(strong_values.size)),
                    "realizations": REALIZATIONS,
                }
            )

    global_weak = float(
        np.mean([value for (size, control, target), values in observed.items() if control == weak_control for value in values])
    )
    global_strong = float(
        np.mean([value for (size, control, target), values in observed.items() if control == strong_control for value in values])
    )
    # The global margin is the robust physical gate. Every target/size group is
    # also required to order correctly, allowing modest finite-sample variation.
    if global_weak <= global_strong + 0.055:
        raise AssertionError(
            f"weak/strong global separation too small: {global_weak - global_strong:.6f}"
        )
    if min(differences) <= 0.010:
        raise AssertionError(f"a weak/strong group is not resolved: {min(differences):.6f}")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "case_id": CASE_ID,
        "derivation_type": "small_exact_diagonalization",
        "description": "complete spectra of a periodic random-field Heisenberg chain in the fixed zero-magnetization sector",
        "files": {"packets": "packets.csv", "eigenvalues": "eigenvalues.npz"},
        "packet_columns": list(PACKET_COLUMNS),
        "target_energy": "e_max + target * (e_min - e_max)",
        "independent_sampling_unit": "realization_id within (target,size,control)",
        "model": {
            "hamiltonian": "sum_i S_i dot S_(i+1) - sum_i field_i S_i^z",
            "exchange_coupling": 1.0,
            "boundary": "periodic",
            "field_distribution": "independent uniform[-control,+control] before paired control scaling",
            "sector": "sum_i S_i^z = 0",
            "basis": "computational bitstrings with size/2 up spins",
        },
        "generation": {
            "seed": SEED,
            "sizes": list(SIZES),
            "sector_dimensions": dimensions,
            "controls": list(CONTROLS),
            "targets": list(TARGETS),
            "realizations_per_size": REALIZATIONS,
            "diagonalization": "numpy.linalg.eigvalsh on a real symmetric dense matrix",
            "spectrum_scope": "complete fixed-sector spectrum per realization and control",
            "packet_spectra_are_shuffled": True,
        },
        "adjacent_gap_ratio": "mean(min(delta_n,delta_(n+1))/max(delta_n,delta_(n+1))) after nearest-target selection",
    }
    _json_write(case_dir / "manifest.json", manifest)

    with (case_dir / "packets.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PACKET_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _format_cell(row[key]) for key in PACKET_COLUMNS})

    np.savez_compressed(
        case_dir / "eigenvalues.npz",
        schema_version=np.asarray("spectral-scaling-eigenvalues/v1"),
        energies=np.asarray(flat_energies, dtype=np.float64),
    )

    truth_summary = {
        "schema_version": "spectral-ed-realism-truth-summary/v1",
        "case_id": CASE_ID,
        "derivation_type": "small_exact_diagonalization",
        "packet_count": len(rows),
        "unique_spectrum_count": unique_spectrum_count,
        "raw_eigenvalue_count": len(flat_energies),
        "sector_dimensions": dimensions,
        "group_summaries": group_summaries,
        "aggregate": {
            "weak_mean_r": global_weak,
            "strong_mean_r": global_strong,
            "weak_minus_strong": global_weak - global_strong,
            "minimum_group_weak_minus_strong": min(differences),
            "observed_ratio_minimum": float(np.min(ratio_values)),
            "observed_ratio_maximum": float(np.max(ratio_values)),
        },
        "invariants": {
            "fixed_sector_dimensions_match_binomial": True,
            "hamiltonians_are_real_symmetric": True,
            "spectra_are_finite": True,
            "bounded_adjacent_gap_ratios": True,
            "weak_field_mean_exceeds_strong_field_mean": True,
            "every_size_target_group_orders_weak_above_strong": True,
            "normalized_target_selection_used": True,
            "complete_raw_sector_spectra_stored": True,
        },
        "spectrum_digest": hashlib.sha256("".join(spectrum_hashes).encode("ascii")).hexdigest(),
    }
    _json_write(case_dir / "truth_summary.json", truth_summary)
    return case_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=TASK_ROOT,
        help="task-package root (default: inferred finite-size spectral audit root)",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    case_dir = generate_ed_realism(args.output_root)
    runtime_seconds = time.perf_counter() - started
    summary = json.loads((case_dir / "truth_summary.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "case_dir": str(case_dir),
                "packet_count": summary["packet_count"],
                "weak_minus_strong": summary["aggregate"]["weak_minus_strong"],
                "minimum_group_margin": summary["aggregate"]["minimum_group_weak_minus_strong"],
                "runtime_seconds": runtime_seconds,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
