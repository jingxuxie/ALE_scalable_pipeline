#!/usr/bin/env python3
"""Trusted deterministic generator for retired and hidden spectral cases."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from ed_realism import generate_ed_realism


TASK_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_ANALYZER = TASK_ROOT / "author" / "reference_solver" / "analyze.py"

UINT64_MAX = 2**64 - 1
MAX_ABSOLUTE_CONTROL = 1e6
MAX_ABSOLUTE_NUMERIC = 1e100
MAX_CASE_INPUT_BYTES = 256 * 1024 * 1024
AFFINE_ENERGY_SCALE = 1.625
AFFINE_ENERGY_OFFSET = -4.75
MIN_KEEP_BOUNDARY_SPAN_FRACTION = 1e-8
MIN_SELECTED_GAP_SPAN_FRACTION = 1e-9
MIN_FLOAT64_ULPS = 2**20
MAX_RATIO_PERTURBATION = 1e-10

CASES = [
    {
        "case_id": "retired_cedar",
        "token": "retired-7f14b9c2",
        "seed": 813271,
        "public": True,
        "center": 2.75,
        "curvature": 1.05,
        "asymmetry": 0.34,
        "nu": 0.94,
        "nu_tilt": 0.10,
        "correction": 0.25,
        "sizes": [8, 12, 18, 26],
        "controls": [1.30, 1.65, 2.00, 2.35, 2.70, 3.05, 3.40, 3.75, 4.10],
        "targets": [0.22, 0.50, 0.78],
        "realizations": 28,
    },
    {
        "case_id": "case_amber",
        "token": "hidden-amber-31d86a0f",
        "seed": 197933,
        "public": False,
        "center": 3.18,
        "curvature": 1.34,
        "asymmetry": -1.20,
        "nu": 0.78,
        "nu_tilt": -0.08,
        "correction": 0.30,
        "sizes": [7, 11, 17, 25],
        "controls": [1.45, 1.85, 2.25, 2.65, 3.05, 3.45, 3.85, 4.25, 4.65],
        "targets": [0.18, 0.50, 0.82],
        "realizations": 29,
    },
    {
        "case_id": "case_indigo",
        "token": "hidden-indigo-4a8f125e",
        "seed": 440987,
        "public": False,
        "center": 2.42,
        "curvature": 0.72,
        "asymmetry": 1.40,
        "nu": 1.23,
        "nu_tilt": 0.16,
        "correction": -0.24,
        "sizes": [9, 14, 21, 30],
        "controls": [0.85, 1.25, 1.65, 2.05, 2.45, 2.85, 3.25, 3.65, 4.05],
        "targets": [0.24, 0.47, 0.76],
        "realizations": 27,
        "unbalanced": True,
    },
    {
        "case_id": "case_sable",
        "token": "hidden-sable-cbe20973",
        "seed": 631921,
        "public": False,
        "center": 3.62,
        "curvature": 1.58,
        "asymmetry": 0.90,
        "nu": 0.66,
        "nu_tilt": 0.05,
        "correction": 0.32,
        "sizes": [8, 13, 20, 29],
        "controls": [1.70, 2.15, 2.60, 3.05, 3.50, 3.95, 4.40, 4.85, 5.30],
        "targets": [0.20, 0.52, 0.84],
        "realizations": 30,
        "missing_edges": True,
    },
    {
        "case_id": "case_verdant",
        "token": "hidden-verdant-08e5d91a",
        "seed": 902117,
        "public": False,
        "center": 2.93,
        "curvature": 0.96,
        "asymmetry": -1.10,
        "nu": 1.08,
        "nu_tilt": -0.18,
        "correction": 0.18,
        "sizes": [6, 10, 18, 28],
        "controls": [1.05, 1.50, 1.95, 2.40, 2.85, 3.30, 3.75, 4.20, 4.65],
        "targets": [0.16, 0.49, 0.80],
        "realizations": 26,
        "unbalanced": True,
    },
]


def critical(config: dict, target: float) -> float:
    values = [
        float(config[name])
        for name in ("center", "curvature", "asymmetry")
    ]
    target = float(target)
    if (
        not math.isfinite(target)
        or not 0.0 <= target <= 1.0
        or not all(math.isfinite(value) for value in values)
    ):
        raise AssertionError("critical-curve inputs must be finite")
    centered = target - 0.5
    result = float(
        values[0]
        - values[1] * centered * centered
        + values[2] * centered
        + 0.35 * centered**3
    )
    if not math.isfinite(result):
        raise AssertionError("critical-curve calculation must remain finite")
    return result


def exponent(config: dict, target: float) -> float:
    nu = float(config["nu"])
    tilt = float(config["nu_tilt"])
    target = float(target)
    if not all(math.isfinite(value) for value in (nu, tilt, target)):
        raise AssertionError("exponent inputs must be finite")
    result = float(nu * (1.0 + tilt * (target - 0.5)))
    if not math.isfinite(result) or not 0.35 <= result <= 3.5:
        raise AssertionError("generated scaling exponent must remain in the fit envelope")
    return result


def logistic(value: np.ndarray | float) -> np.ndarray | float:
    if not np.all(np.isfinite(value)):
        raise AssertionError("logistic input must be finite before clipping")
    result = 1.0 / (1.0 + np.exp(-np.clip(value, -40.0, 40.0)))
    if not np.all(np.isfinite(result)):
        raise AssertionError("logistic output must be finite")
    return result


def expected_ratio(shape: float) -> float:
    shape = float(shape)
    if not math.isfinite(shape) or shape <= 0.0:
        raise AssertionError("gamma shape must be positive and finite")
    nodes, weights = np.polynomial.legendre.leggauss(160)
    points = 0.25 * (nodes + 1.0)
    integral_weights = 0.25 * weights
    log_beta = 2.0 * math.lgamma(shape) - math.lgamma(2.0 * shape)
    log_density = (shape - 1.0) * (np.log(points) + np.log1p(-points)) - log_beta
    ratio = points / (1.0 - points)
    result = float(2.0 * np.sum(integral_weights * np.exp(log_density) * ratio))
    if not math.isfinite(result):
        raise AssertionError("expected gap ratio integration must remain finite")
    return result


def mean_ratio(config: dict, target: float, size: float, control: float) -> float:
    target = float(target)
    size = float(size)
    control = float(control)
    correction = float(config["correction"])
    if (
        not all(math.isfinite(value) for value in (target, size, control, correction))
        or not 0.0 <= target <= 1.0
        or not 1.0 <= size <= 1_000_000.0
        or abs(control) > MAX_ABSOLUTE_CONTROL
    ):
        raise AssertionError("mean-ratio coordinates must be finite with positive size")
    size_correction = size**0.72
    if not math.isfinite(size_correction) or size_correction <= 0.0:
        raise AssertionError("finite-size correction overflowed")
    hc = critical(config, target) + correction / size_correction
    nu = exponent(config, target)
    size_scale = size ** (1.0 / nu)
    base = (control - hc) * size_scale / 4.6
    if not all(math.isfinite(value) for value in (hc, size_scale, base)):
        raise AssertionError("mean-ratio scaling coordinate overflowed")
    nodes, weights = np.polynomial.hermite.hermgauss(18)
    values = []
    for node in nodes:
        localized = float(logistic(base + math.sqrt(2.0) * 0.22 * float(node)))
        shape = 1.0 + 1.44 * (1.0 - localized)
        values.append(expected_ratio(shape))
    result = float(np.dot(weights, np.asarray(values)) / math.sqrt(math.pi))
    if not math.isfinite(result):
        raise AssertionError("mean gap-ratio integral must remain finite")
    return result


def canonical(value: float) -> float:
    """Return the public ten-decimal numeric key."""

    return round(float(value), 10)


def affine_energy_conditioning(packet_rows: list[dict], flat_energies: list[float]) -> dict:
    """Audit packet selection before and after the default affine-energy map.

    These checks make the affine-energy metamorphic test a scientific
    invariance check rather than a selection-boundary or float64 accident.
    The returned extrema are written to hidden truth summaries; the same
    assertions are nevertheless applied to the retired public case.
    """

    energies = np.asarray(flat_energies, dtype=np.float64)
    minimum_keep_boundary = math.inf
    minimum_keep_boundary_over_span = math.inf
    minimum_keep_boundary_ulps = math.inf
    minimum_selected_gap = math.inf
    minimum_selected_gap_over_span = math.inf
    minimum_selected_gap_ulps = math.inf
    minimum_absolute_shift_offset = math.inf
    maximum_absolute_shift_offset = 0.0
    maximum_shift_offset_over_span = 0.0
    maximum_ratio_perturbation = 0.0
    maximum_absolute_energy_coordinate = 0.0
    selected_index_prefix_exactly_preserved = True

    for packet_index, row in enumerate(packet_rows):
        offset = int(row["eigen_offset"])
        count = int(row["eigen_count"])
        keep = int(row["keep_count"])
        chunk = np.asarray(energies[offset : offset + count], dtype=np.float64)
        target = float(row["target"])
        target_energy = float(row["e_max"]) + target * (
            float(row["e_min"]) - float(row["e_max"])
        )
        shift_offset = abs(float(row["shift_energy"]) - target_energy)
        distances = np.abs(chunk - target_energy)
        distance_order = np.argsort(distances, kind="stable")
        ordered_distances = distances[distance_order]
        boundary_margin = (
            float(ordered_distances[keep] - ordered_distances[keep - 1])
            if keep < count
            else None
        )
        selected_indices = distance_order[:keep]
        selected = np.sort(chunk[selected_indices])
        gaps = np.diff(selected)
        ratios = np.minimum(gaps[:-1], gaps[1:]) / np.maximum(gaps[:-1], gaps[1:])
        span = max(float(np.ptp(chunk)), float(row["e_max"]) - float(row["e_min"]))
        magnitude = max(
            1.0,
            float(np.max(np.abs(chunk))),
            abs(float(row["e_min"])),
            abs(float(row["e_max"])),
            abs(target_energy),
        )
        ulp = math.ulp(magnitude)

        transformed_chunk = AFFINE_ENERGY_SCALE * chunk + AFFINE_ENERGY_OFFSET
        transformed_e_min = AFFINE_ENERGY_SCALE * float(row["e_min"]) + AFFINE_ENERGY_OFFSET
        transformed_e_max = AFFINE_ENERGY_SCALE * float(row["e_max"]) + AFFINE_ENERGY_OFFSET
        transformed_shift = AFFINE_ENERGY_SCALE * float(row["shift_energy"]) + AFFINE_ENERGY_OFFSET
        transformed_target_energy = transformed_e_max + target * (
            transformed_e_min - transformed_e_max
        )
        transformed_distances = np.abs(transformed_chunk - transformed_target_energy)
        transformed_order = np.argsort(transformed_distances, kind="stable")
        transformed_ordered_distances = transformed_distances[transformed_order]
        transformed_boundary_margin = (
            float(
                transformed_ordered_distances[keep]
                - transformed_ordered_distances[keep - 1]
            )
            if keep < count
            else None
        )
        transformed_indices = transformed_order[:keep]
        transformed_selected = np.sort(transformed_chunk[transformed_indices])
        transformed_gaps = np.diff(transformed_selected)
        transformed_ratios = np.minimum(
            transformed_gaps[:-1], transformed_gaps[1:]
        ) / np.maximum(transformed_gaps[:-1], transformed_gaps[1:])
        transformed_span = max(
            float(np.ptp(transformed_chunk)), transformed_e_max - transformed_e_min
        )
        transformed_shift_offset = abs(transformed_shift - transformed_target_energy)
        transformed_magnitude = max(
            1.0,
            float(np.max(np.abs(transformed_chunk))),
            abs(transformed_e_min),
            abs(transformed_e_max),
            abs(transformed_target_energy),
        )
        transformed_ulp = math.ulp(transformed_magnitude)

        if not np.array_equal(selected_indices, transformed_indices):
            selected_index_prefix_exactly_preserved = False
        if ratios.shape != transformed_ratios.shape:
            raise AssertionError(
                f"affine-energy ratio shape changed for packet {packet_index}"
            )
        ratio_perturbation = float(np.max(np.abs(ratios - transformed_ratios)))
        if boundary_margin is not None and transformed_boundary_margin is not None:
            minimum_keep_boundary = min(
                minimum_keep_boundary, boundary_margin, transformed_boundary_margin
            )
            minimum_keep_boundary_over_span = min(
                minimum_keep_boundary_over_span,
                boundary_margin / span,
                transformed_boundary_margin / transformed_span,
            )
            minimum_keep_boundary_ulps = min(
                minimum_keep_boundary_ulps,
                boundary_margin / ulp,
                transformed_boundary_margin / transformed_ulp,
            )
        minimum_selected_gap = min(
            minimum_selected_gap,
            float(np.min(gaps)),
            float(np.min(transformed_gaps)),
        )
        minimum_selected_gap_over_span = min(
            minimum_selected_gap_over_span,
            float(np.min(gaps)) / span,
            float(np.min(transformed_gaps)) / transformed_span,
        )
        minimum_selected_gap_ulps = min(
            minimum_selected_gap_ulps,
            float(np.min(gaps)) / ulp,
            float(np.min(transformed_gaps)) / transformed_ulp,
        )
        minimum_absolute_shift_offset = min(
            minimum_absolute_shift_offset, shift_offset, transformed_shift_offset
        )
        maximum_absolute_shift_offset = max(
            maximum_absolute_shift_offset, shift_offset, transformed_shift_offset
        )
        maximum_shift_offset_over_span = max(
            maximum_shift_offset_over_span,
            shift_offset / span,
            transformed_shift_offset / transformed_span,
        )
        maximum_ratio_perturbation = max(
            maximum_ratio_perturbation, ratio_perturbation
        )
        maximum_absolute_energy_coordinate = max(
            maximum_absolute_energy_coordinate,
            abs(float(row["e_min"])),
            abs(float(row["e_max"])),
            abs(float(row["shift_energy"])),
            abs(target_energy),
            float(np.max(np.abs(chunk))),
            abs(transformed_e_min),
            abs(transformed_e_max),
            abs(transformed_shift),
            abs(transformed_target_energy),
            float(np.max(np.abs(transformed_chunk))),
        )

    metrics = {
        "affine_energy_scale": AFFINE_ENERGY_SCALE,
        "affine_energy_offset": AFFINE_ENERGY_OFFSET,
        "minimum_keep_boundary_margin": float(minimum_keep_boundary),
        "minimum_keep_boundary_margin_over_span": float(minimum_keep_boundary_over_span),
        "minimum_keep_boundary_margin_ulps": float(minimum_keep_boundary_ulps),
        "minimum_selected_gap": float(minimum_selected_gap),
        "minimum_selected_gap_over_span": float(minimum_selected_gap_over_span),
        "minimum_selected_gap_ulps": float(minimum_selected_gap_ulps),
        "selected_index_prefix_exactly_preserved": bool(selected_index_prefix_exactly_preserved),
        "minimum_absolute_shift_offset": float(minimum_absolute_shift_offset),
        "maximum_absolute_shift_offset": float(maximum_absolute_shift_offset),
        "maximum_shift_offset_over_span": float(maximum_shift_offset_over_span),
        "maximum_ratio_perturbation": float(maximum_ratio_perturbation),
        "maximum_absolute_energy_coordinate": float(maximum_absolute_energy_coordinate),
    }
    if (
        not all(math.isfinite(float(value)) for key, value in metrics.items() if key != "selected_index_prefix_exactly_preserved")
        or metrics["minimum_keep_boundary_margin_over_span"] < MIN_KEEP_BOUNDARY_SPAN_FRACTION
        or metrics["minimum_keep_boundary_margin_ulps"] < MIN_FLOAT64_ULPS
        or metrics["minimum_selected_gap_over_span"] < MIN_SELECTED_GAP_SPAN_FRACTION
        or metrics["minimum_selected_gap_ulps"] < MIN_FLOAT64_ULPS
        or not metrics["selected_index_prefix_exactly_preserved"]
        or metrics["minimum_absolute_shift_offset"] <= 0.0
        or metrics["maximum_shift_offset_over_span"] > 0.005
        or metrics["maximum_ratio_perturbation"] > MAX_RATIO_PERTURBATION
        or metrics["maximum_absolute_energy_coordinate"] > MAX_ABSOLUTE_NUMERIC
    ):
        raise AssertionError(
            f"affine-energy conditioning invariants failed: {metrics}"
        )
    return metrics


def validate_generated_contract(
    manifest: dict,
    grid: dict,
    packet_rows: list[dict],
    flat_energies: list[float],
    query_rows: list[dict],
) -> None:
    """Enforce the participant-visible v1 input envelope at generation time."""

    energies = np.asarray(flat_energies, dtype=np.float64)
    if (
        not 1 <= len(packet_rows) <= 6_000
        or not 1 <= energies.size <= 5_000_000
        or energies.ndim != 1
        or not np.all(np.isfinite(energies))
        or np.any(np.abs(energies) > MAX_ABSOLUTE_NUMERIC)
        or not 1 <= len(query_rows) <= 512
    ):
        raise AssertionError("case violates published packet/eigenvalue/query bounds")

    packet_ids: set[str] = set()
    group_realizations: dict[tuple[float, int, float], set[str]] = {}
    controls_by_curve: dict[tuple[float, int], set[float]] = {}
    sizes_by_target: dict[float, set[int]] = {}
    expected_offset = 0
    for packet_index, row in enumerate(packet_rows):
        packet_id = str(row["packet_id"])
        realization_id = str(row["realization_id"])
        size = int(row["size"])
        control = float(row["control"])
        target = float(row["target"])
        e_min = float(row["e_min"])
        e_max = float(row["e_max"])
        shift_energy = float(row["shift_energy"])
        keep = int(row["keep_count"])
        offset = int(row["eigen_offset"])
        count = int(row["eigen_count"])
        numeric = (control, target, e_min, e_max, shift_energy)
        if (
            not packet_id
            or packet_id in packet_ids
            or len(packet_id.encode("utf-8")) > 48
            or not realization_id
            or len(realization_id.encode("utf-8")) > 48
            or not all(math.isfinite(value) for value in numeric)
            or not 1 <= size <= 1_000_000
            or abs(control) > MAX_ABSOLUTE_CONTROL
            or not 0.0 <= target <= 1.0
            or not e_min < e_max
            or any(abs(value) > MAX_ABSOLUTE_NUMERIC for value in numeric)
            or offset != expected_offset
            or not 5 <= keep <= count <= 4_096
            or offset + count > energies.size
        ):
            raise AssertionError(f"packet {packet_index} violates the published row contract")
        chunk = np.asarray(energies[offset : offset + count], dtype=np.float64)
        target_energy = e_max + target * (e_min - e_max)
        if (
            not math.isfinite(target_energy)
            or float(np.min(chunk)) < e_min
            or float(np.max(chunk)) > e_max
            or not 0.0 < abs(shift_energy - target_energy) <= 0.005 * (e_max - e_min)
        ):
            raise AssertionError(
                f"packet {packet_index} violates spectral containment or shift bounds"
            )
        packet_ids.add(packet_id)
        expected_offset += count
        group_key = (canonical(target), size, canonical(control))
        realizations = group_realizations.setdefault(group_key, set())
        if realization_id in realizations:
            raise AssertionError(f"packet {packet_index} duplicates a group-realization key")
        realizations.add(realization_id)
        controls_by_curve.setdefault(group_key[:2], set()).add(group_key[2])
        sizes_by_target.setdefault(group_key[0], set()).add(size)

    if expected_offset != energies.size:
        raise AssertionError("packet slices do not exhaust the generated eigenvalue array")
    observed_targets = set(sizes_by_target)
    observed_sizes = {size for values in sizes_by_target.values() for size in values}
    if (
        not 1 <= len(observed_targets) <= 8
        or not 3 <= len(observed_sizes) <= 8
        or any(not 3 <= len(values) <= 8 for values in sizes_by_target.values())
        or any(not 5 <= len(values) <= 21 for values in controls_by_curve.values())
        or any(not 2 <= len(values) <= 128 for values in group_realizations.values())
    ):
        raise AssertionError("case violates published target/size/control/realization bounds")

    query_ids: set[str] = set()
    for query_index, row in enumerate(query_rows):
        query_id = str(row["query_id"])
        target = float(row["target"])
        size = float(row["size"])
        control = float(row["control"])
        if (
            not query_id
            or query_id in query_ids
            or len(query_id.encode("utf-8")) > 48
            or not all(math.isfinite(value) for value in (target, size, control))
            or canonical(target) not in observed_targets
            or not 1.0 <= size <= 1_000_000.0
            or abs(control) > MAX_ABSOLUTE_CONTROL
        ):
            raise AssertionError(f"query {query_index} violates the published query contract")
        query_ids.add(query_id)

    seed = int(manifest["bootstrap_seed"])
    halfwidths = [float(value) for value in grid["halfwidths"]]
    if (
        not 0 <= seed <= UINT64_MAX
        or seed + 1009 * (len(observed_targets) - 1) > UINT64_MAX
        or any(
            not math.isfinite(value) or not 0.4 <= value <= MAX_ABSOLUTE_CONTROL
            for value in halfwidths
        )
    ):
        raise AssertionError("bootstrap seed or halfwidth exceeds the published bounds")


def manifest_for(config: dict, grid: dict) -> dict:
    return {
        "schema_version": "spectral-scaling-input/v1",
        "case_id": config["case_id"],
        "case_token": config["token"],
        "derivation_type": "grounded_extension",
        "description": "finite-size crossover spectra with realization-clustered packets",
        "bootstrap_seed": int(config["seed"] + 5011),
        "files": {
            "packets": "packets.csv",
            "eigenvalues": "eigenvalues.npz",
            "queries": "queries.csv",
            "analysis_grid": "analysis_grid.json",
        },
        "packet_columns": [
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
        ],
        "query_columns": ["query_id", "target", "size", "control"],
        "target_energy": "e_max + target * (e_min - e_max)",
        "independent_sampling_unit": "realization_id within (target,size,control)",
        "scaling_coordinate": "(control - h_c) * size**(1/nu)",
        "expected_output_files": [
            "realization_stats.csv",
            "packet_stats.csv",
            "transition.csv",
            "stability.csv",
            "predictions.csv",
            "claims.json",
        ],
        "resource_contract": {
            "python": "3.11+",
            "numpy": "2.3.5",
            "network": "disabled",
            "wall_time_seconds": 180,
            "output_bytes": 4000000,
        },
        "grid_summary": {
            "targets": [float(value) for value in config["targets"]],
            "sizes": [int(value) for value in config["sizes"]],
            "control_min": float(min(config["controls"])),
            "control_max": float(max(config["controls"])),
            "stability_variant_count": len(grid["min_sizes"]) * len(grid["halfwidths"]),
        },
    }


def write_case(config: dict, input_dir: Path, truth_dir: Path | None) -> None:
    rng = np.random.default_rng(int(config["seed"]))
    sizes = [int(value) for value in config["sizes"]]
    controls = [float(value) for value in config["controls"]]
    targets = [float(value) for value in config["targets"]]
    if (
        not 1 <= len(targets) <= 8
        or len({canonical(value) for value in targets}) != len(targets)
        or any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in targets)
        or not 3 <= len(sizes) <= 8
        or len(set(sizes)) != len(sizes)
        or any(not 1 <= value <= 1_000_000 for value in sizes)
        or not 5 <= len(controls) <= 21
        or len({canonical(value) for value in controls}) != len(controls)
        or any(
            not math.isfinite(value) or abs(value) > MAX_ABSOLUTE_CONTROL
            for value in controls
        )
        or not 2 <= int(config["realizations"]) <= 128
    ):
        raise AssertionError("case configuration violates published coordinate/cardinality bounds")
    spacing = float(np.median(np.diff(np.asarray(controls))))
    if not math.isfinite(spacing) or spacing <= 0.0:
        raise AssertionError("control grid must be finite and strictly ordered")
    grid = {
        "schema_version": "spectral-scaling-analysis-grid/v1",
        "min_sizes": [sizes[0], sizes[1]],
        "halfwidths": [round(1.75 * spacing, 6), round(2.25 * spacing, 6), round(2.75 * spacing, 6)],
        "primary_min_size": sizes[1],
        "primary_halfwidth": round(2.25 * spacing, 6),
        "bootstrap_replicates": 20,
        "interval_level": 0.68,
    }
    if (
        not 1 <= len(grid["min_sizes"]) <= 8
        or not 1 <= len(grid["halfwidths"]) <= 8
        or not 2 <= len(grid["min_sizes"]) * len(grid["halfwidths"]) <= 24
        or not 8 <= int(grid["bootstrap_replicates"]) <= 64
        or any(
            not math.isfinite(float(value))
            or not 0.4 <= float(value) <= MAX_ABSOLUTE_CONTROL
            for value in grid["halfwidths"]
        )
        or len({canonical(value) for value in grid["halfwidths"]}) != len(grid["halfwidths"])
    ):
        raise AssertionError("analysis-grid closure invariants failed")
    manifest = manifest_for(config, grid)
    resource = manifest["resource_contract"]
    if (
        any(not 1 <= int(value) <= 1_000_000 for value in sizes)
        or any(not 1 <= int(value) <= 1_000_000 for value in grid["min_sizes"])
        or int(manifest["bootstrap_seed"]) < 0
        or int(manifest["bootstrap_seed"]) > UINT64_MAX
        or int(manifest["bootstrap_seed"]) + 1009 * (len(targets) - 1) > UINT64_MAX
        or any(not value or len(str(value).encode("utf-8")) > 48 for value in (manifest["case_id"], manifest["case_token"]))
        or int(resource["wall_time_seconds"]) != 180
        or not 1 <= int(resource["output_bytes"]) <= 4_000_000
    ):
        raise AssertionError("manifest resource/cardinality closure invariants failed")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (input_dir / "analysis_grid.json").write_text(
        json.dumps(grid, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    combinations = []
    for target in targets:
        for size_index, size in enumerate(sizes):
            for control_index, control in enumerate(controls):
                if config.get("missing_edges") and ((size_index == 0 and control_index == 0) or (size_index == 3 and control_index == 8)):
                    continue
                count = int(config["realizations"])
                if config.get("unbalanced"):
                    count += ((size_index * 3 + control_index * 2 + int(round(target * 10))) % 7) - 3
                for realization in range(count):
                    combinations.append((target, size, control, realization))
    rng.shuffle(combinations)
    if len(combinations) > 6_000:
        raise AssertionError("case exceeds the 6,000-packet public bound")
    packet_rows = []
    flat_energies: list[float] = []
    raw_count = 45
    for packet_index, (target, size, control, realization) in enumerate(combinations):
        size_correction = float(size) ** 0.72
        if not math.isfinite(size_correction) or size_correction <= 0.0:
            raise AssertionError("packet finite-size correction overflowed")
        correction = float(config["correction"])
        if not math.isfinite(correction):
            raise AssertionError("packet correction strength must be finite")
        true_hc = critical(config, target) + correction / size_correction
        true_nu = exponent(config, target)
        size_scale = float(size) ** (1.0 / true_nu)
        x = (control - true_hc) * size_scale / 4.6
        random_shift = float(rng.normal(0.0, 0.22))
        if not all(
            math.isfinite(value)
            for value in (true_hc, true_nu, size_scale, x, random_shift)
        ):
            raise AssertionError("packet scaling coordinate overflowed before clipping")
        localized = float(logistic(x + random_shift))
        # Real acquisitions need not retain identical level counts.  Correlate
        # the requested count mildly with the realization's crossover state so
        # pooling level ratios (instead of equal-weight realization means) is a
        # detectable pseudoreplication error rather than an accidental alias.
        keep_count = int(np.clip(round(26.0 + 14.0 * localized), 25, 41))
        shape = 1.0 + 1.44 * (1.0 - localized)
        gaps = rng.gamma(shape, 1.0 / shape, size=raw_count - 1)
        if not np.all(np.isfinite(gaps)) or np.any(gaps <= 0.0):
            raise AssertionError("generated gamma gaps must be positive and finite")
        ordered = np.concatenate(([0.0], np.cumsum(gaps)))
        ordered -= float(np.median(ordered))
        tentative_e_min = -60.0 + float(rng.normal(0.0, 0.35))
        tentative_e_max = 60.0 + float(rng.normal(0.0, 0.35))
        if not 0.0 < target < 1.0:
            raise AssertionError("symmetric packet construction requires interior targets")
        target_energy = tentative_e_max + target * (
            tentative_e_min - tentative_e_max
        )
        level_scale = float(rng.uniform(0.72, 1.34))
        centered_levels = level_scale * ordered
        baseline_width = tentative_e_max - tentative_e_min
        lower_extent = -float(np.min(centered_levels))
        upper_extent = float(np.max(centered_levels))
        spectral_width = max(
            baseline_width,
            (lower_extent + 1.0) / (1.0 - target),
            (upper_extent + 1.0) / target,
        )
        e_min = target_energy - (1.0 - target) * spectral_width
        e_max = target_energy + target * spectral_width
        target_energy = e_max + target * (e_min - e_max)
        ordered = target_energy + centered_levels
        if (
            not all(
                math.isfinite(value)
                for value in (e_min, e_max, target_energy, spectral_width)
            )
            or not np.all(np.isfinite(ordered))
            or float(np.min(ordered)) < e_min
            or float(np.max(ordered)) > e_max
        ):
            raise AssertionError("generated float64 packet is not contained in its spectral extrema")
        shuffled = ordered[rng.permutation(raw_count)]
        offset = len(flat_energies)
        flat_energies.extend(float(value) for value in shuffled)
        shift_sign = -1.0 if float(rng.random()) < 0.5 else 1.0
        shift_energy = target_energy + 0.45 * shift_sign
        if (
            not math.isfinite(shift_energy)
            or not 0.0 < abs(shift_energy - target_energy) <= 0.005 * (e_max - e_min)
        ):
            raise AssertionError(
                "shift diagnostic must be finite, nonzero, and within 0.5% of the spectral span"
            )
        packet_rows.append(
            {
                "packet_id": f"p{packet_index:06d}",
                "realization_id": f"r{realization:04d}",
                "size": size,
                "control": control,
                "target": target,
                "e_min": e_min,
                "e_max": e_max,
                "shift_energy": shift_energy,
                "keep_count": keep_count,
                "eigen_offset": offset,
                "eigen_count": raw_count,
            }
        )

    if not 1 <= len(flat_energies) <= 5_000_000:
        raise AssertionError("case exceeds the 5,000,000-eigenvalue public bound")
    if any(
        not math.isfinite(float(value)) or abs(float(value)) > MAX_ABSOLUTE_NUMERIC
        for value in flat_energies
    ) or any(
        not math.isfinite(float(row[key]))
        or abs(float(row[key])) > (
            MAX_ABSOLUTE_CONTROL if key == "control" else MAX_ABSOLUTE_NUMERIC
        )
        for row in packet_rows
        for key in ("control", "e_min", "e_max", "shift_energy")
    ):
        raise AssertionError("generated packet coordinate exceeds the public magnitude bound")
    if any(
        len(str(row["packet_id"]).encode("utf-8")) > 48
        or len(str(row["realization_id"]).encode("utf-8")) > 48
        for row in packet_rows
    ):
        raise AssertionError("generated packet identifier exceeds the 48-byte public bound")
    columns = manifest["packet_columns"]
    with (input_dir / "packets.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in packet_rows:
            writer.writerow(
                {
                    key: format(float(value), ".17g") if isinstance(value, float) else value
                    for key, value in row.items()
                }
            )
    np.savez_compressed(
        input_dir / "eigenvalues.npz",
        schema_version=np.asarray("spectral-scaling-eigenvalues/v1"),
        energies=np.asarray(flat_energies, dtype=np.float64),
    )

    query_rows = []
    query_truth = []
    query_index = 0
    query_sizes = [0.5 * (sizes[0] + sizes[1]), 0.5 * (sizes[2] + sizes[3]), sizes[-1] + 2]
    for target in targets:
        hc = critical(config, target)
        for size in query_sizes:
            for delta in (-0.32, 0.0, 0.32):
                control = hc + delta
                query_rows.append(
                    {"query_id": f"q{query_index:04d}", "target": target, "size": size, "control": control}
                )
                query_truth.append(mean_ratio(config, target, size, control))
                query_index += 1
    if not query_rows:
        raise AssertionError("each case must include at least one held-out query")
    if len(query_rows) > 512 or any(len(str(row["query_id"]).encode("utf-8")) > 48 for row in query_rows):
        raise AssertionError("case exceeds the public query bound")
    if any(
        not math.isfinite(float(row["size"]))
        or not 1.0 <= float(row["size"]) <= 1_000_000.0
        for row in query_rows
    ):
        raise AssertionError("generated query size exceeds the public bound")
    if any(
        not math.isfinite(float(row["target"]))
        or not math.isfinite(float(row["control"]))
        or abs(float(row["control"])) > MAX_ABSOLUTE_CONTROL
        for row in query_rows
    ):
        raise AssertionError("generated query control exceeds the public magnitude bound")
    validate_generated_contract(manifest, grid, packet_rows, flat_energies, query_rows)
    conditioning = affine_energy_conditioning(packet_rows, flat_energies)
    with (input_dir / "queries.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["query_id", "target", "size", "control"], lineterminator="\n")
        writer.writeheader()
        for row in query_rows:
            writer.writerow(
                {
                    key: format(float(value), ".17g") if isinstance(value, float) else value
                    for key, value in row.items()
                }
            )

    physical_case_files = [input_dir / "manifest.json"] + [
        input_dir / manifest["files"][role]
        for role in ("packets", "eigenvalues", "queries", "analysis_grid")
    ]
    if len({path.resolve() for path in physical_case_files}) != 5 or not all(
        path.is_file() for path in physical_case_files
    ):
        raise AssertionError("case must consist of five distinct physical input files")
    physical_case_input_bytes = sum(path.stat().st_size for path in physical_case_files)
    if physical_case_input_bytes > MAX_CASE_INPUT_BYTES:
        raise AssertionError("physical five-file case input exceeds 256 MiB")

    group_count = len({
        (round(float(row["target"]), 10), int(row["size"]), round(float(row["control"]), 10))
        for row in packet_rows
    })
    stability_cells = len(grid["min_sizes"]) * len(grid["halfwidths"])
    required_rows = (
        len(packet_rows)
        + group_count
        + len(targets)
        + len(targets) * stability_cells
        + len(query_rows)
    )
    if int(resource["output_bytes"]) < 512 * required_rows + 8192:
        raise AssertionError("declared output byte cap is insufficient for mandatory rows")

    true_hc = np.asarray([critical(config, target) for target in targets], dtype=np.float64)
    true_nu = np.asarray([exponent(config, target) for target in targets], dtype=np.float64)
    weak = np.asarray([mean_ratio(config, target, sizes[-1], controls[0]) for target in targets])
    strong = np.asarray([mean_ratio(config, target, sizes[-1], controls[-1]) for target in targets])
    if not np.all((weak > strong + 0.045) & (weak < 0.59) & (strong > 0.34)):
        raise AssertionError(f"crossover invariants failed for {config['case_id']}")
    minimum_curve_span = 0.15 if config.get("public") else 0.45
    if float(np.ptp(true_hc)) < minimum_curve_span or not np.all(
        (true_hc > min(controls)) & (true_hc < max(controls))
    ):
        raise AssertionError("critical curve is not a resolved in-range edge")
    for target, hc in zip(targets, true_hc):
        weak_side = np.asarray(
            [mean_ratio(config, target, size, float(hc) - 0.35) for size in sizes],
            dtype=np.float64,
        )
        strong_side = np.asarray(
            [mean_ratio(config, target, size, float(hc) + 0.35) for size in sizes],
            dtype=np.float64,
        )
        crossing = np.asarray(
            [mean_ratio(config, target, size, float(hc)) for size in sizes],
            dtype=np.float64,
        )
        if weak_side[-1] <= weak_side[0] + 0.007:
            raise AssertionError("weak-side size ordering does not resolve a crossing")
        if strong_side[-1] >= strong_side[0] - 0.020:
            raise AssertionError("strong-side size ordering does not resolve a crossing")
        if float(np.ptp(crossing)) >= 0.025:
            raise AssertionError("finite-size crossing fan is too broad")

    if truth_dir is not None:
        truth_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            truth_dir / "truth.npz",
            schema_version=np.asarray("spectral-scaling-truth/v1"),
            targets=np.asarray(targets, dtype=np.float64),
            h_c=true_hc,
            nu=true_nu,
            query_ids=np.asarray([row["query_id"] for row in query_rows]),
            query_mean_r=np.asarray(query_truth, dtype=np.float64),
            weak_limit_mean_r=weak,
            strong_limit_mean_r=strong,
            correction_strength=np.asarray(float(config["correction"]), dtype=np.float64),
        )
        summary = {
            "schema_version": "spectral-scaling-truth-summary/v1",
            "case_id": config["case_id"],
            "derivation_type": "grounded_extension",
            "generator_family": "clustered-gamma-gap finite-size crossover",
            "invariants": {
                "bounded_gap_ratio": True,
                "weak_control_mean_exceeds_strong_control_mean": True,
                "common_size_crossing": True,
                "affine_energy_invariance": True,
                "realization_cluster_is_sampling_unit": True,
            },
            "critical_curve_span": float(np.ptp(true_hc)),
            "weak_minus_strong_minimum": float(np.min(weak - strong)),
            "physical_case_input_bytes": int(physical_case_input_bytes),
            "numeric_conditioning": conditioning,
        }
        (truth_dir / "truth_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def run_reference_gate(input_dir: Path, output_dir: Path, case_id: str) -> None:
    """Require the complete trusted workflow to accept one generated case."""

    process = subprocess.run(
        [
            sys.executable,
            "-B",
            str(REFERENCE_ANALYZER),
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
        ],
        cwd=TASK_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"reference workflow rejected {case_id}: {detail}")
    manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    actual_output_bytes = sum(
        path.stat().st_size for path in output_dir.iterdir() if path.is_file()
    )
    if actual_output_bytes > int(manifest["resource_contract"]["output_bytes"]):
        raise RuntimeError(f"oracle output for {case_id} exceeds the declared byte cap")


def generate(output_root: Path) -> None:
    public_root = output_root / "participant" / "input"
    hidden_root = output_root / "private" / "hidden_inputs"
    reference_root = output_root / "private" / "reference"
    suite_cases = []
    for config in CASES:
        if config["public"]:
            write_case(config, public_root, None)
            with tempfile.TemporaryDirectory(
                prefix=f"spectral-reference-gate-{config['case_id']}-"
            ) as temporary_root:
                run_reference_gate(
                    public_root,
                    Path(temporary_root) / "oracle_output",
                    str(config["case_id"]),
                )
        else:
            case_input = hidden_root / config["case_id"]
            case_reference = reference_root / config["case_id"]
            write_case(config, case_input, case_reference)
            oracle_output = case_reference / "oracle_output"
            run_reference_gate(case_input, oracle_output, str(config["case_id"]))
            suite_cases.append(
                {
                    "case_id": config["case_id"],
                    "input": f"../hidden_inputs/{config['case_id']}",
                    "truth": f"{config['case_id']}/truth.npz",
                    "oracle_output": f"{config['case_id']}/oracle_output",
                    "class": "distribution_shift" if config["case_id"] in {"case_indigo", "case_verdant"} else "ordinary",
                    "derivation_type": "grounded_extension",
                }
            )
    realism_path = generate_ed_realism(output_root)
    canonical = reference_root / "canonical_submission" / "output"
    canonical.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REFERENCE_ANALYZER, canonical / "analyze.py")
    reference_root.mkdir(parents=True, exist_ok=True)
    (reference_root / "suite.json").write_text(
        json.dumps(
            {
                "schema_version": "spectral-scaling-hidden-suite/v1",
                "cases": suite_cases,
                "realism_cases": [
                    {
                        "case_id": "heisenberg_ed_fixed_sector",
                        "path": realism_path.relative_to(output_root).as_posix(),
                        "role": "generator-invariant realism fixture; not a scored scaling case",
                    }
                ],
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=TASK_ROOT)
    arguments = parser.parse_args()
    generate(arguments.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
