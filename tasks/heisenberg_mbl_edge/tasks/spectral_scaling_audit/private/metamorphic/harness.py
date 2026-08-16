#!/usr/bin/env python3
"""Deterministic metamorphic checks for spectral-scaling analyzers.

This module is private evaluator infrastructure.  It deliberately uses only the
Python standard library and NumPy so that ``scripts/verify.py`` can import it in
the same runtime as the participant and reference analyzers.

The case transformations preserve the five-file public input contract.  The
output comparator normalizes transformed coordinates before comparing results.
For transformations that permute realization-to-bootstrap-index assignments,
point estimates remain strict while finite-replicate uncertainty is checked by
interval behavior rather than accidental equality of pseudorandom draws.
"""

from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


CASE_FILES = (
    "manifest.json",
    "packets.csv",
    "eigenvalues.npz",
    "queries.csv",
    "analysis_grid.json",
)

OUTPUT_FILES = (
    "realization_stats.csv",
    "packet_stats.csv",
    "transition.csv",
    "stability.csv",
    "predictions.csv",
    "claims.json",
)

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

QUERY_COLUMNS = ("query_id", "target", "size", "control")

CSV_SCHEMAS: dict[str, dict[str, Any]] = {
    "realization_stats.csv": {
        "columns": (
            "case_id",
            "target",
            "size",
            "control",
            "realization_id",
            "n_ratios",
            "mean_r",
        ),
        "key": ("case_id", "target", "size", "control", "realization_id"),
        "float": ("target", "control", "mean_r"),
        "int": ("size", "n_ratios"),
    },
    "packet_stats.csv": {
        "columns": (
            "case_id",
            "target",
            "size",
            "control",
            "n_realizations",
            "n_ratios",
            "mean_r",
            "se_r",
        ),
        "key": ("case_id", "target", "size", "control"),
        "float": ("target", "control", "mean_r", "se_r"),
        "int": ("size", "n_realizations", "n_ratios"),
    },
    "transition.csv": {
        "columns": (
            "case_id",
            "target",
            "h_c",
            "nu",
            "h_c_lo",
            "h_c_hi",
            "nu_lo",
            "nu_hi",
            "fit_score",
            "stable",
        ),
        "key": ("case_id", "target"),
        "float": (
            "target",
            "h_c",
            "nu",
            "h_c_lo",
            "h_c_hi",
            "nu_lo",
            "nu_hi",
            "fit_score",
        ),
        "int": ("stable",),
    },
    "stability.csv": {
        "columns": (
            "case_id",
            "target",
            "min_size",
            "halfwidth",
            "h_c",
            "nu",
            "validation_rmse",
            "n_groups",
            "fit_ok",
        ),
        "key": ("case_id", "target", "min_size", "halfwidth"),
        "float": ("target", "halfwidth", "h_c", "nu", "validation_rmse"),
        "int": ("min_size", "n_groups", "fit_ok"),
    },
    "predictions.csv": {
        "columns": ("query_id", "mean_r", "se_r"),
        "key": ("query_id",),
        "float": ("mean_r", "se_r"),
        "int": (),
    },
}

CLAIM_FIELDS = (
    "schema_version",
    "case_id",
    "case_token",
    "finite_size_crossover",
    "phase_direction",
    "n_realizations",
    "n_groups",
    "n_targets",
    "low_control_mean_r",
    "high_control_mean_r",
)

UNCERTAINTY_FIELDS = {
    ("transition.csv", "h_c_lo"),
    ("transition.csv", "h_c_hi"),
    ("transition.csv", "nu_lo"),
    ("transition.csv", "nu_hi"),
    ("predictions.csv", "se_r"),
}

ENERGY_AFFINE_SCALE_MINIMUM = 0.5
ENERGY_AFFINE_SCALE_MAXIMUM = 2.0
ENERGY_AFFINE_MAGNITUDE_LIMIT = 1e100
ENERGY_AFFINE_SHIFT_SPAN_FRACTION_LIMIT = 0.005
ENERGY_AFFINE_KEEP_BOUNDARY_SPAN_FRACTION = 1e-8
ENERGY_AFFINE_SELECTED_GAP_SPAN_FRACTION = 1e-9
ENERGY_AFFINE_ULP_MULTIPLIER = 2**20
ENERGY_AFFINE_RATIO_PERTURBATION_LIMIT = 1e-10


def _number(value: float) -> str:
    """Render a finite float without discarding transform information."""

    value = float(value)
    if not math.isfinite(value):
        raise ValueError("transformed values must be finite")
    return format(value, ".17g")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no CSV header")
        fieldnames = list(reader.fieldnames)
        rows = [dict(row) for row in reader]
    return fieldnames, rows


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row[name] for name in fieldnames})


def _prepare_empty(path: Path) -> Path:
    path = Path(path)
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"destination is not a directory: {path}")
        if any(path.iterdir()):
            raise ValueError(f"destination must be empty: {path}")
    else:
        path.mkdir(parents=True)
    return path


def _validate_inventory(case_dir: Path) -> None:
    actual = {item.name for item in case_dir.iterdir() if item.is_file()}
    missing = set(CASE_FILES) - actual
    if missing:
        raise ValueError(f"case is missing required files: {sorted(missing)}")


def _load_case(case_dir: Path) -> dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    _validate_inventory(case_dir)
    manifest = _read_json(case_dir / "manifest.json")
    grid = _read_json(case_dir / "analysis_grid.json")
    packet_header, packets = _read_csv(case_dir / "packets.csv")
    query_header, queries = _read_csv(case_dir / "queries.csv")
    if tuple(packet_header) != PACKET_COLUMNS:
        raise ValueError(f"unexpected packets.csv columns: {packet_header}")
    if tuple(query_header) != QUERY_COLUMNS:
        raise ValueError(f"unexpected queries.csv columns: {query_header}")
    with np.load(case_dir / "eigenvalues.npz", allow_pickle=False) as archive:
        if set(archive.files) != {"schema_version", "energies"}:
            raise ValueError("eigenvalues.npz has unexpected members")
        schema_version = str(np.asarray(archive["schema_version"]).item())
        energies = np.asarray(archive["energies"], dtype=np.float64).copy()
    if schema_version != "spectral-scaling-eigenvalues/v1":
        raise ValueError(f"unexpected eigenvalue schema: {schema_version}")
    if energies.ndim != 1 or not np.all(np.isfinite(energies)):
        raise ValueError("energies must be a finite one-dimensional array")

    chunks: list[np.ndarray] = []
    occupied = np.zeros(energies.size, dtype=np.uint8)
    for row in packets:
        offset = int(row["eigen_offset"])
        count = int(row["eigen_count"])
        if offset < 0 or count <= 0 or offset + count > energies.size:
            raise ValueError(f"invalid packet range for {row['packet_id']}")
        if np.any(occupied[offset : offset + count]):
            raise ValueError("packet ranges overlap")
        occupied[offset : offset + count] = 1
        chunks.append(energies[offset : offset + count].copy())
    if not np.all(occupied):
        raise ValueError("unreferenced or missing eigenvalues in packet ranges")
    packet_ids = [row["packet_id"] for row in packets]
    if len(set(packet_ids)) != len(packet_ids):
        raise ValueError("packet_id values must be unique")
    return {
        "manifest": manifest,
        "grid": grid,
        "packets": packets,
        "queries": queries,
        "chunks": chunks,
    }


def _write_case(destination: Path, case: Mapping[str, Any]) -> None:
    destination = _prepare_empty(Path(destination))
    rows: list[dict[str, Any]] = [dict(row) for row in case["packets"]]
    chunks = [np.asarray(chunk, dtype=np.float64) for chunk in case["chunks"]]
    if len(rows) != len(chunks):
        raise ValueError("packet/chunk cardinality mismatch")
    flattened: list[np.ndarray] = []
    offset = 0
    for row, chunk in zip(rows, chunks):
        if chunk.ndim != 1 or chunk.size <= 0 or not np.all(np.isfinite(chunk)):
            raise ValueError(f"invalid eigenvalue chunk for {row['packet_id']}")
        row["eigen_offset"] = str(offset)
        row["eigen_count"] = str(int(chunk.size))
        flattened.append(chunk)
        offset += int(chunk.size)
    energies = np.concatenate(flattened) if flattened else np.empty(0, dtype=np.float64)
    _write_json(destination / "manifest.json", case["manifest"])
    _write_json(destination / "analysis_grid.json", case["grid"])
    _write_csv(destination / "packets.csv", PACKET_COLUMNS, rows)
    _write_csv(destination / "queries.csv", QUERY_COLUMNS, case["queries"])
    np.savez(
        destination / "eigenvalues.npz",
        schema_version=np.asarray("spectral-scaling-eigenvalues/v1"),
        energies=energies,
    )


def transform_row_and_packet_permutation(
    source: Path,
    destination: Path,
    *,
    seed: int = 7331,
) -> dict[str, Any]:
    """Permute packet rows/blocks and raw eigenvalue order within every block."""

    case = _load_case(Path(source))
    rng = np.random.default_rng(seed)
    order = np.asarray(rng.permutation(len(case["packets"])), dtype=np.int64)
    case["packets"] = [case["packets"][int(index)] for index in order]
    case["chunks"] = [
        case["chunks"][int(index)][rng.permutation(case["chunks"][int(index)].size)]
        for index in order
    ]
    _write_case(Path(destination), case)
    return {"kind": "row_packet_permutation", "seed": int(seed)}


def transform_realization_id_permutation(
    source: Path,
    destination: Path,
    *,
    seed: int = 4219,
) -> dict[str, Any]:
    """Apply a deterministic derangement of all realization identifier labels."""

    case = _load_case(Path(source))
    identifiers = sorted({row["realization_id"] for row in case["packets"]})
    if len(identifiers) < 2:
        raise ValueError("at least two realization identifiers are required")
    shuffled = list(identifiers)
    np.random.default_rng(seed).shuffle(shuffled)
    mapping = {
        shuffled[index]: shuffled[(index + 1) % len(shuffled)]
        for index in range(len(shuffled))
    }
    for row in case["packets"]:
        row["realization_id"] = mapping[row["realization_id"]]
    _write_case(Path(destination), case)
    return {
        "kind": "realization_id_permutation",
        "seed": int(seed),
        "inverse_realization_ids": {new: old for old, new in mapping.items()},
        "bootstrap_relabel": True,
    }


def transform_positive_affine_energy(
    source: Path,
    destination: Path,
    *,
    scale: float = 1.625,
    offset: float = -4.75,
) -> dict[str, Any]:
    """Apply a well-conditioned positive affine map to every energy field.

    The public statistic is affine invariant in exact arithmetic, but a map can
    still be a bad metamorphic test if floating-point rounding changes a nearest
    level tie, the retained set, or an adjacent-gap ratio.  Preflight therefore
    reproduces the public stable-selection rule on both the source values and
    the exact values that will be written, and rejects ill-conditioned maps
    before creating ``destination``.
    """

    scale = float(scale)
    offset = float(offset)
    if (
        not math.isfinite(scale)
        or not ENERGY_AFFINE_SCALE_MINIMUM <= scale <= ENERGY_AFFINE_SCALE_MAXIMUM
        or not math.isfinite(offset)
    ):
        raise ValueError(
            "energy affine map requires finite parameters and "
            f"{ENERGY_AFFINE_SCALE_MINIMUM} <= scale <= "
            f"{ENERGY_AFFINE_SCALE_MAXIMUM}"
        )
    case = _load_case(Path(source))

    transformed_rows = [dict(row) for row in case["packets"]]
    transformed_chunks: list[np.ndarray] = []
    with np.errstate(over="ignore", invalid="ignore"):
        for chunk in case["chunks"]:
            transformed_chunks.append(scale * chunk + offset)
    for row in transformed_rows:
        for column in ("e_min", "e_max", "shift_energy"):
            row[column] = _number(scale * float(row[column]) + offset)

    def packet_metrics(row: Mapping[str, Any], levels: np.ndarray) -> dict[str, Any]:
        levels = np.asarray(levels, dtype=np.float64)
        e_min = float(row["e_min"])
        e_max = float(row["e_max"])
        shift_energy = float(row["shift_energy"])
        target = float(row["target"])
        keep_count = int(row["keep_count"])
        maximum_magnitude = max(
            float(np.max(np.abs(levels))),
            abs(e_min),
            abs(e_max),
            abs(shift_energy),
        )
        if not (
            np.all(np.isfinite(levels))
            and all(
                math.isfinite(value)
                for value in (
                    e_min,
                    e_max,
                    shift_energy,
                    maximum_magnitude,
                )
            )
        ):
            raise ValueError(f"non-finite energy value for packet {row['packet_id']}")
        if maximum_magnitude > ENERGY_AFFINE_MAGNITUDE_LIMIT:
            raise ValueError(
                f"energy magnitude limit exceeded for packet {row['packet_id']}: "
                f"{maximum_magnitude:.12g} > {ENERGY_AFFINE_MAGNITUDE_LIMIT:.12g}"
            )

        target_energy = e_max + target * (e_min - e_max)
        declared_span = e_max - e_min
        if (
            not math.isfinite(target_energy)
            or not math.isfinite(declared_span)
            or declared_span <= 0.0
        ):
            raise ValueError(f"invalid declared energy span for packet {row['packet_id']}")
        spectrum_span = float(np.ptp(levels))
        span_scale = max(spectrum_span, declared_span)
        shift_span_fraction = abs(shift_energy - target_energy) / declared_span
        magnitude_scale = max(
            1.0,
            float(np.max(np.abs(levels))),
            abs(e_min),
            abs(e_max),
            abs(target_energy),
        )
        maximum_magnitude = max(maximum_magnitude, abs(target_energy))
        if not all(
            math.isfinite(value)
            for value in (
                target_energy,
                declared_span,
                spectrum_span,
                span_scale,
                magnitude_scale,
                maximum_magnitude,
                shift_span_fraction,
            )
        ) or span_scale <= 0.0:
            raise ValueError(f"invalid energy conditioning scale for packet {row['packet_id']}")
        if maximum_magnitude > ENERGY_AFFINE_MAGNITUDE_LIMIT:
            raise ValueError(
                f"energy magnitude limit exceeded for packet {row['packet_id']}: "
                f"{maximum_magnitude:.12g} > {ENERGY_AFFINE_MAGNITUDE_LIMIT:.12g}"
            )
        ulp_scale = math.ulp(magnitude_scale)

        distances = np.abs(levels - target_energy)
        distance_order = np.argsort(distances, kind="stable")
        ordered_distances = distances[distance_order]
        boundary_margin: float | None = None
        boundary_requirement: float | None = None
        if keep_count < levels.size:
            boundary_margin = float(
                ordered_distances[keep_count] - ordered_distances[keep_count - 1]
            )
            boundary_requirement = max(
                ENERGY_AFFINE_KEEP_BOUNDARY_SPAN_FRACTION * span_scale,
                ENERGY_AFFINE_ULP_MULTIPLIER * ulp_scale,
            )

        nearest_indices = np.asarray(distance_order[:keep_count], dtype=np.int64)
        energy_order = np.argsort(levels[nearest_indices], kind="stable")
        sorted_indices = nearest_indices[energy_order]
        selected_levels = levels[sorted_indices]
        gaps = np.diff(selected_levels)
        selected_gap_margin = float(np.min(gaps))
        selected_gap_requirement = max(
            ENERGY_AFFINE_SELECTED_GAP_SPAN_FRACTION * span_scale,
            ENERGY_AFFINE_ULP_MULTIPLIER * ulp_scale,
        )
        ratios = np.minimum(gaps[:-1], gaps[1:]) / np.maximum(gaps[:-1], gaps[1:])
        return {
            "maximum_magnitude": maximum_magnitude,
            "span_scale": span_scale,
            "magnitude_scale": magnitude_scale,
            "ulp_scale": ulp_scale,
            "shift_span_fraction": shift_span_fraction,
            "keep_boundary_margin": boundary_margin,
            "keep_boundary_requirement": boundary_requirement,
            "keep_boundary_margin_over_span": (
                None if boundary_margin is None else boundary_margin / span_scale
            ),
            "keep_boundary_margin_in_ulps": (
                None if boundary_margin is None else boundary_margin / ulp_scale
            ),
            "keep_boundary_requirement_ratio": (
                None if boundary_margin is None else boundary_margin / boundary_requirement
            ),
            "selected_adjacent_gap_margin": selected_gap_margin,
            "selected_adjacent_gap_requirement": selected_gap_requirement,
            "selected_adjacent_gap_margin_over_span": selected_gap_margin / span_scale,
            "selected_adjacent_gap_margin_in_ulps": selected_gap_margin / ulp_scale,
            "selected_adjacent_gap_requirement_ratio": (
                selected_gap_margin / selected_gap_requirement
            ),
            "nearest_indices": nearest_indices,
            "sorted_indices": sorted_indices,
            "ratios": ratios,
        }

    baseline_metrics: list[dict[str, Any]] = []
    transformed_metrics: list[dict[str, Any]] = []
    maximum_ratio_perturbation = 0.0
    exact_nearest_prefix_preserved = True
    exact_sorted_indices_preserved = True
    for baseline_row, baseline_chunk, transformed_row, transformed_chunk in zip(
        case["packets"],
        case["chunks"],
        transformed_rows,
        transformed_chunks,
    ):
        baseline = packet_metrics(baseline_row, baseline_chunk)
        transformed = packet_metrics(transformed_row, transformed_chunk)
        baseline_metrics.append(baseline)
        transformed_metrics.append(transformed)
        exact_nearest_prefix_preserved = exact_nearest_prefix_preserved and np.array_equal(
            baseline["nearest_indices"], transformed["nearest_indices"]
        )
        exact_sorted_indices_preserved = exact_sorted_indices_preserved and np.array_equal(
            baseline["sorted_indices"], transformed["sorted_indices"]
        )
        if baseline["ratios"].shape != transformed["ratios"].shape:
            maximum_ratio_perturbation = math.inf
        elif baseline["ratios"].size:
            maximum_ratio_perturbation = max(
                maximum_ratio_perturbation,
                float(np.max(np.abs(baseline["ratios"] - transformed["ratios"]))),
            )

    def minimum(name: str, metrics: Sequence[Mapping[str, Any]]) -> float | None:
        values = [float(item[name]) for item in metrics if item[name] is not None]
        return min(values) if values else None

    for coordinate, metrics in (
        ("baseline", baseline_metrics),
        ("transformed", transformed_metrics),
    ):
        for row, item in zip(case["packets"], metrics):
            boundary_margin = item["keep_boundary_margin"]
            boundary_requirement = item["keep_boundary_requirement"]
            if boundary_margin is not None and boundary_margin < boundary_requirement:
                raise ValueError(
                    f"{coordinate} keep-boundary margin for packet {row['packet_id']} "
                    f"is {boundary_margin:.12g}, below {boundary_requirement:.12g}"
                )
            if item["selected_adjacent_gap_margin"] < item["selected_adjacent_gap_requirement"]:
                raise ValueError(
                    f"{coordinate} selected adjacent-gap margin for packet "
                    f"{row['packet_id']} is {item['selected_adjacent_gap_margin']:.12g}, "
                    f"below {item['selected_adjacent_gap_requirement']:.12g}"
                )
            if item["shift_span_fraction"] > ENERGY_AFFINE_SHIFT_SPAN_FRACTION_LIMIT:
                raise ValueError(
                    f"{coordinate} shift-to-target span fraction for packet "
                    f"{row['packet_id']} is {item['shift_span_fraction']:.12g}, "
                    f"above {ENERGY_AFFINE_SHIFT_SPAN_FRACTION_LIMIT:.12g}"
                )

    exact_index_sequences_preserved = (
        exact_nearest_prefix_preserved and exact_sorted_indices_preserved
    )
    conditioning = {
        "packet_count": len(baseline_metrics),
        "packets_with_keep_boundary": sum(
            item["keep_boundary_margin"] is not None
            for item in baseline_metrics
        ),
        "scale": scale,
        "offset": offset,
        "scale_minimum": ENERGY_AFFINE_SCALE_MINIMUM,
        "scale_maximum": ENERGY_AFFINE_SCALE_MAXIMUM,
        "magnitude_limit": ENERGY_AFFINE_MAGNITUDE_LIMIT,
        "maximum_allowed_shift_span_fraction": ENERGY_AFFINE_SHIFT_SPAN_FRACTION_LIMIT,
        "minimum_required_keep_boundary_span_fraction": (
            ENERGY_AFFINE_KEEP_BOUNDARY_SPAN_FRACTION
        ),
        "minimum_required_selected_adjacent_gap_span_fraction": (
            ENERGY_AFFINE_SELECTED_GAP_SPAN_FRACTION
        ),
        "minimum_required_ulp_multiplier": ENERGY_AFFINE_ULP_MULTIPLIER,
        "maximum_allowed_retained_adjacent_gap_ratio_perturbation": (
            ENERGY_AFFINE_RATIO_PERTURBATION_LIMIT
        ),
        "baseline_max_magnitude": max(
            float(item["maximum_magnitude"]) for item in baseline_metrics
        ),
        "transformed_max_magnitude": max(
            float(item["maximum_magnitude"]) for item in transformed_metrics
        ),
        "baseline_max_shift_span_fraction": max(
            float(item["shift_span_fraction"]) for item in baseline_metrics
        ),
        "transformed_max_shift_span_fraction": max(
            float(item["shift_span_fraction"]) for item in transformed_metrics
        ),
        "baseline_min_keep_boundary_margin_over_span": minimum(
            "keep_boundary_margin_over_span", baseline_metrics
        ),
        "transformed_min_keep_boundary_margin_over_span": minimum(
            "keep_boundary_margin_over_span", transformed_metrics
        ),
        "baseline_min_keep_boundary_margin_in_ulps": minimum(
            "keep_boundary_margin_in_ulps", baseline_metrics
        ),
        "transformed_min_keep_boundary_margin_in_ulps": minimum(
            "keep_boundary_margin_in_ulps", transformed_metrics
        ),
        "baseline_min_keep_boundary_requirement_ratio": minimum(
            "keep_boundary_requirement_ratio", baseline_metrics
        ),
        "transformed_min_keep_boundary_requirement_ratio": minimum(
            "keep_boundary_requirement_ratio", transformed_metrics
        ),
        "baseline_min_selected_adjacent_gap_margin_over_span": minimum(
            "selected_adjacent_gap_margin_over_span", baseline_metrics
        ),
        "transformed_min_selected_adjacent_gap_margin_over_span": minimum(
            "selected_adjacent_gap_margin_over_span", transformed_metrics
        ),
        "baseline_min_selected_adjacent_gap_margin_in_ulps": minimum(
            "selected_adjacent_gap_margin_in_ulps", baseline_metrics
        ),
        "transformed_min_selected_adjacent_gap_margin_in_ulps": minimum(
            "selected_adjacent_gap_margin_in_ulps", transformed_metrics
        ),
        "baseline_min_selected_adjacent_gap_requirement_ratio": minimum(
            "selected_adjacent_gap_requirement_ratio", baseline_metrics
        ),
        "transformed_min_selected_adjacent_gap_requirement_ratio": minimum(
            "selected_adjacent_gap_requirement_ratio", transformed_metrics
        ),
        "exact_stable_selected_prefix_preserved": exact_nearest_prefix_preserved,
        "exact_energy_sorted_selected_index_sequence_preserved": (
            exact_sorted_indices_preserved
        ),
        "exact_selected_index_sequence_preserved": exact_index_sequences_preserved,
        "max_retained_adjacent_gap_ratio_perturbation": maximum_ratio_perturbation,
    }

    if not exact_index_sequences_preserved:
        raise ValueError("energy affine map does not preserve exact selected index sequences")
    if maximum_ratio_perturbation > ENERGY_AFFINE_RATIO_PERTURBATION_LIMIT:
        raise ValueError(
            "energy affine map changes a retained adjacent-gap ratio by "
            f"{maximum_ratio_perturbation:.12g}, exceeding "
            f"{ENERGY_AFFINE_RATIO_PERTURBATION_LIMIT:.12g}"
        )

    case["packets"] = transformed_rows
    case["chunks"] = transformed_chunks
    _write_case(Path(destination), case)
    return {
        "kind": "positive_affine_energy",
        "scale": scale,
        "offset": offset,
        "conditioning": conditioning,
    }


def transform_affine_control(
    source: Path,
    destination: Path,
    *,
    scale: float = 1.35,
    offset: float = -0.42,
) -> dict[str, Any]:
    """Apply h -> scale * h + offset and scale every analysis window."""

    scale = float(scale)
    offset = float(offset)
    if not math.isfinite(scale) or scale <= 0.0 or not math.isfinite(offset):
        raise ValueError("control scale must be positive and affine parameters finite")
    case = _load_case(Path(source))
    for row in case["packets"]:
        row["control"] = _number(scale * float(row["control"]) + offset)
    for row in case["queries"]:
        row["control"] = _number(scale * float(row["control"]) + offset)

    summary = case["manifest"].get("grid_summary", {})
    if "control_min" in summary:
        summary["control_min"] = scale * float(summary["control_min"]) + offset
    if "control_max" in summary:
        summary["control_max"] = scale * float(summary["control_max"]) + offset
    for key in ("halfwidths",):
        if key in case["grid"]:
            case["grid"][key] = [scale * float(value) for value in case["grid"][key]]
    if "primary_halfwidth" in case["grid"]:
        case["grid"]["primary_halfwidth"] = scale * float(case["grid"]["primary_halfwidth"])
    _write_case(Path(destination), case)
    return {"kind": "affine_control", "scale": scale, "offset": offset}


def transform_target_mirror(source: Path, destination: Path) -> dict[str, Any]:
    """Reflect target coordinates and spectra around their respective midpoints.

    With the public convention ``E_t = e_max + t * (e_min - e_max)``, the map
    ``t -> 1-t`` is covariant under ``E -> -E`` with extrema swapped.  This
    preserves the selected levels and all gap-ratio evidence while reversing
    the labels of the target-dependent crossover curve.
    """

    case = _load_case(Path(source))
    for row in case["packets"]:
        old_min = float(row["e_min"])
        old_max = float(row["e_max"])
        row["target"] = _number(1.0 - float(row["target"]))
        row["e_min"] = _number(-old_max)
        row["e_max"] = _number(-old_min)
        row["shift_energy"] = _number(-float(row["shift_energy"]))
    for row in case["queries"]:
        row["target"] = _number(1.0 - float(row["target"]))
    summary = case["manifest"].get("grid_summary", {})
    if "targets" in summary:
        summary["targets"] = sorted(1.0 - float(value) for value in summary["targets"])
    case["chunks"] = [-chunk for chunk in case["chunks"]]
    _write_case(Path(destination), case)
    return {"kind": "target_mirror", "bootstrap_relabel": True}


def split_case_into_shards(
    source: Path,
    shard_root: Path,
    *,
    shard_count: int = 4,
    seed: int = 9157,
) -> dict[str, Any]:
    """Split packet rows and eigenvalue blocks into deterministic private shards.

    A shard root is an intermediate representation, not a participant case.  It
    contains the three common files, ``shard_index.json``, and shard directories
    holding contract-shaped ``packets.csv``/``eigenvalues.npz`` pairs.
    """

    case = _load_case(Path(source))
    shard_count = int(shard_count)
    if shard_count < 2 or shard_count > len(case["packets"]):
        raise ValueError("shard_count must be between 2 and the packet count")
    shard_root = _prepare_empty(Path(shard_root))
    _write_json(shard_root / "manifest.json", case["manifest"])
    _write_json(shard_root / "analysis_grid.json", case["grid"])
    _write_csv(shard_root / "queries.csv", QUERY_COLUMNS, case["queries"])

    order = np.asarray(np.random.default_rng(seed).permutation(len(case["packets"])), dtype=np.int64)
    shard_names: list[str] = []
    shard_packet_ids: dict[str, list[str]] = {}
    for shard_number in range(shard_count):
        indices = order[shard_number::shard_count]
        name = f"shard_{shard_number:03d}"
        shard_names.append(name)
        shard_path = shard_root / name
        shard_path.mkdir()
        rows = [case["packets"][int(index)] for index in indices]
        chunks = [case["chunks"][int(index)] for index in indices]
        offset = 0
        rendered_rows: list[dict[str, Any]] = []
        for row, chunk in zip(rows, chunks):
            rendered = dict(row)
            rendered["eigen_offset"] = str(offset)
            rendered["eigen_count"] = str(int(chunk.size))
            offset += int(chunk.size)
            rendered_rows.append(rendered)
        energies = np.concatenate(chunks)
        _write_csv(shard_path / "packets.csv", PACKET_COLUMNS, rendered_rows)
        np.savez(
            shard_path / "eigenvalues.npz",
            schema_version=np.asarray("spectral-scaling-eigenvalues/v1"),
            energies=energies,
        )
        shard_packet_ids[name] = [row["packet_id"] for row in rows]

    index = {
        "schema_version": "spectral-scaling-shards/v1",
        "seed": int(seed),
        "packet_count": len(case["packets"]),
        "eigenvalue_count": int(sum(chunk.size for chunk in case["chunks"])),
        "shards": shard_names,
        "packet_ids": shard_packet_ids,
    }
    _write_json(shard_root / "shard_index.json", index)
    return {
        "kind": "shard_split",
        "seed": int(seed),
        "shard_count": shard_count,
        "packet_count": len(case["packets"]),
    }


def rejoin_shards(
    shard_root: Path,
    destination: Path,
    *,
    reverse_shard_order: bool = True,
) -> dict[str, Any]:
    """Rejoin private shards into one valid case, rewriting all flat offsets."""

    shard_root = Path(shard_root).resolve()
    index = _read_json(shard_root / "shard_index.json")
    if index.get("schema_version") != "spectral-scaling-shards/v1":
        raise ValueError("unexpected shard index schema")
    names = list(index.get("shards", []))
    if not names or len(set(names)) != len(names):
        raise ValueError("shard list is empty or contains duplicates")
    if reverse_shard_order:
        names.reverse()
    packets: list[dict[str, str]] = []
    chunks: list[np.ndarray] = []
    for name in names:
        if Path(name).name != name:
            raise ValueError(f"unsafe shard name: {name}")
        shard_path = shard_root / name
        header, shard_rows = _read_csv(shard_path / "packets.csv")
        if tuple(header) != PACKET_COLUMNS:
            raise ValueError(f"unexpected packet columns in {name}")
        with np.load(shard_path / "eigenvalues.npz", allow_pickle=False) as archive:
            if set(archive.files) != {"schema_version", "energies"}:
                raise ValueError(f"unexpected archive members in {name}")
            energies = np.asarray(archive["energies"], dtype=np.float64)
        expected_offset = 0
        for row in shard_rows:
            offset = int(row["eigen_offset"])
            count = int(row["eigen_count"])
            if offset != expected_offset or count <= 0 or offset + count > energies.size:
                raise ValueError(f"noncontiguous packet ranges in {name}")
            expected_offset += count
            packets.append(dict(row))
            chunks.append(energies[offset : offset + count].copy())
        if expected_offset != energies.size:
            raise ValueError(f"unreferenced eigenvalues in {name}")

    if len(packets) != int(index["packet_count"]):
        raise ValueError("rejoined packet count differs from shard index")
    if sum(chunk.size for chunk in chunks) != int(index["eigenvalue_count"]):
        raise ValueError("rejoined eigenvalue count differs from shard index")
    identifiers = [row["packet_id"] for row in packets]
    expected_ids = {
        packet_id
        for values in index.get("packet_ids", {}).values()
        for packet_id in values
    }
    if len(set(identifiers)) != len(identifiers) or set(identifiers) != expected_ids:
        raise ValueError("rejoined packet identifiers do not match shard index")

    case = {
        "manifest": _read_json(shard_root / "manifest.json"),
        "grid": _read_json(shard_root / "analysis_grid.json"),
        "queries": _read_csv(shard_root / "queries.csv")[1],
        "packets": packets,
        "chunks": chunks,
    }
    _write_case(Path(destination), case)
    return {
        "kind": "shard_rejoin",
        "reverse_shard_order": bool(reverse_shard_order),
        "shard_count": len(names),
    }


def assert_packet_equivalent(left: Path, right: Path) -> dict[str, int]:
    """Assert packet-metadata and per-packet eigenvalue equality, ignoring offsets."""

    left_case = _load_case(Path(left))
    right_case = _load_case(Path(right))
    left_by_id = {
        row["packet_id"]: (row, chunk)
        for row, chunk in zip(left_case["packets"], left_case["chunks"])
    }
    right_by_id = {
        row["packet_id"]: (row, chunk)
        for row, chunk in zip(right_case["packets"], right_case["chunks"])
    }
    if set(left_by_id) != set(right_by_id):
        raise AssertionError("packet identifiers differ after shard round-trip")
    metadata_columns = [name for name in PACKET_COLUMNS if name != "eigen_offset"]
    eigenvalue_count = 0
    for packet_id in sorted(left_by_id):
        left_row, left_chunk = left_by_id[packet_id]
        right_row, right_chunk = right_by_id[packet_id]
        if any(left_row[name] != right_row[name] for name in metadata_columns):
            raise AssertionError(f"packet metadata changed for {packet_id}")
        if not np.array_equal(left_chunk, right_chunk):
            raise AssertionError(f"packet eigenvalues changed for {packet_id}")
        eigenvalue_count += int(left_chunk.size)
    return {"packet_count": len(left_by_id), "eigenvalue_count": eigenvalue_count}


def run_analyzer(
    analyzer: Path,
    case_dir: Path,
    output_dir: Path,
    *,
    python_executable: Path | str = sys.executable,
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Run an analyzer on a transformed case and enforce output inventory."""

    analyzer = Path(analyzer).resolve()
    case_dir = Path(case_dir).resolve()
    output_dir = _prepare_empty(Path(output_dir)).resolve()
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    completed = subprocess.run(
        [
            str(python_executable),
            "-B",
            str(analyzer),
            "--input",
            str(case_dir),
            "--output",
            str(output_dir),
        ],
        cwd=str(analyzer.parent),
        env=environment,
        capture_output=True,
        text=True,
        timeout=float(timeout_seconds),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"analyzer failed on {case_dir.name} with exit {completed.returncode}: "
            f"{completed.stderr[-2000:]}"
        )
    actual = {item.name for item in output_dir.iterdir() if item.is_file()}
    if actual != set(OUTPUT_FILES):
        raise RuntimeError(
            f"analyzer output inventory mismatch: expected {list(OUTPUT_FILES)}, got {sorted(actual)}"
        )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-2000:],
    }


def _normalize_float(file_name: str, column: str, value: float, relation: Mapping[str, Any]) -> float:
    value = float(value)
    kind = relation.get("kind", "identity")
    if column == "target" and kind == "target_mirror":
        value = 1.0 - value
    if kind == "affine_control":
        scale = float(relation["scale"])
        offset = float(relation["offset"])
        if column == "control" or column in {"h_c", "h_c_lo", "h_c_hi"}:
            value = (value - offset) / scale
        elif column == "halfwidth":
            value = value / scale
    if not math.isfinite(value):
        raise ValueError(f"non-finite output value in {file_name}:{column}")
    return value


def _parse_rows(
    path: Path,
    file_name: str,
    relation: Mapping[str, Any],
) -> tuple[dict[tuple[Any, ...], dict[str, Any]], list[str]]:
    schema = CSV_SCHEMAS[file_name]
    header, raw_rows = _read_csv(path)
    if tuple(header) != tuple(schema["columns"]):
        raise ValueError(f"{file_name} has unexpected columns {header}")
    inverse_ids = relation.get("inverse_realization_ids", {})
    parsed_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    for raw in raw_rows:
        parsed: dict[str, Any] = {}
        for column in schema["columns"]:
            if column in schema["float"]:
                parsed[column] = _normalize_float(file_name, column, float(raw[column]), relation)
            elif column in schema["int"]:
                parsed[column] = int(raw[column])
            elif column == "realization_id" and inverse_ids:
                if raw[column] not in inverse_ids:
                    raise ValueError(f"unknown transformed realization id {raw[column]}")
                parsed[column] = inverse_ids[raw[column]]
            else:
                parsed[column] = raw[column]
        key: list[Any] = []
        for column in schema["key"]:
            atom = parsed[column]
            if isinstance(atom, float):
                atom = round(atom, 8)
            key.append(atom)
        tuple_key = tuple(key)
        if tuple_key in parsed_rows:
            raise ValueError(f"duplicate normalized key in {file_name}: {tuple_key}")
        parsed_rows[tuple_key] = parsed
    return parsed_rows, header


def _float_close(left: float, right: float, atol: float, rtol: float) -> tuple[bool, float, float]:
    error = abs(float(left) - float(right))
    allowance = float(atol) + float(rtol) * max(abs(float(left)), abs(float(right)))
    return error <= allowance, error, allowance


def _relaxed_uncertainty_ok(
    file_name: str,
    baseline_row: Mapping[str, Any],
    transformed_row: Mapping[str, Any],
) -> tuple[bool, str]:
    if file_name == "predictions.csv":
        baseline = float(baseline_row["se_r"])
        transformed = float(transformed_row["se_r"])
        if baseline < 0.0 or transformed < 0.0:
            return False, "negative predictive uncertainty"
        ratio = transformed / max(baseline, 1e-12)
        okay = 0.35 <= ratio <= 2.85 and abs(transformed - baseline) <= 0.06
        return okay, f"predictive se ratio={ratio:.6g}"

    checks: list[tuple[str, float, float, float]] = []
    for center, low, high in (
        ("h_c", "h_c_lo", "h_c_hi"),
        ("nu", "nu_lo", "nu_hi"),
    ):
        base_center = float(baseline_row[center])
        other_center = float(transformed_row[center])
        base_low = float(baseline_row[low])
        base_high = float(baseline_row[high])
        other_low = float(transformed_row[low])
        other_high = float(transformed_row[high])
        if not (base_low <= base_center <= base_high and other_low <= other_center <= other_high):
            return False, f"{center} interval does not contain its point estimate"
        base_width = base_high - base_low
        other_width = other_high - other_low
        ratio = other_width / max(base_width, 1e-12)
        checks.append((center, base_width, other_width, ratio))
        if not (0.12 <= ratio <= 8.0):
            return False, f"{center} interval-width ratio={ratio:.6g}"
    return True, "; ".join(f"{name} width ratio={ratio:.6g}" for name, _, _, ratio in checks)


def compare_output_directories(
    baseline_dir: Path,
    transformed_dir: Path,
    relation: Mapping[str, Any] | None = None,
    *,
    atol: float = 5e-9,
    rtol: float = 5e-8,
    max_messages: int = 30,
) -> dict[str, Any]:
    """Compare analyzer outputs after undoing a declared input transformation."""

    relation = dict(relation or {"kind": "identity"})
    baseline_dir = Path(baseline_dir)
    transformed_dir = Path(transformed_dir)
    messages: list[str] = []
    max_abs_error = 0.0
    max_error_ratio = 0.0
    comparisons = 0
    relaxed_checks = 0

    def problem(message: str) -> None:
        if len(messages) < max_messages:
            messages.append(message)

    for file_name, schema in CSV_SCHEMAS.items():
        try:
            baseline_rows, _ = _parse_rows(baseline_dir / file_name, file_name, {"kind": "identity"})
            transformed_rows, _ = _parse_rows(transformed_dir / file_name, file_name, relation)
        except (OSError, ValueError) as exc:
            problem(str(exc))
            continue
        if set(baseline_rows) != set(transformed_rows):
            missing = sorted(set(baseline_rows) - set(transformed_rows), key=str)[:3]
            extra = sorted(set(transformed_rows) - set(baseline_rows), key=str)[:3]
            problem(f"{file_name}: normalized keys differ; missing={missing}, extra={extra}")
            continue
        for key in sorted(baseline_rows, key=str):
            baseline = baseline_rows[key]
            transformed = transformed_rows[key]
            if relation.get("bootstrap_relabel") and file_name in {"transition.csv", "predictions.csv"}:
                okay, detail = _relaxed_uncertainty_ok(file_name, baseline, transformed)
                relaxed_checks += 1
                if not okay:
                    problem(f"{file_name} {key}: {detail}")
            for column in schema["columns"]:
                if relation.get("bootstrap_relabel") and (file_name, column) in UNCERTAINTY_FIELDS:
                    continue
                left = baseline[column]
                right = transformed[column]
                comparisons += 1
                if isinstance(left, float):
                    okay, error, allowance = _float_close(left, right, atol, rtol)
                    max_abs_error = max(max_abs_error, error)
                    if allowance > 0.0:
                        max_error_ratio = max(max_error_ratio, error / allowance)
                    if not okay:
                        problem(
                            f"{file_name} {key} {column}: baseline={left:.12g}, "
                            f"transformed={right:.12g}, error={error:.3g}, allowed={allowance:.3g}"
                        )
                elif left != right:
                    problem(f"{file_name} {key} {column}: {left!r} != {right!r}")

    try:
        baseline_claims = _read_json(baseline_dir / "claims.json")
        transformed_claims = _read_json(transformed_dir / "claims.json")
        if tuple(sorted(baseline_claims)) != tuple(sorted(CLAIM_FIELDS)):
            problem("baseline claims.json fields do not match the contract")
        if tuple(sorted(transformed_claims)) != tuple(sorted(CLAIM_FIELDS)):
            problem("transformed claims.json fields do not match the contract")
        for field in CLAIM_FIELDS:
            if field not in baseline_claims or field not in transformed_claims:
                continue
            left = baseline_claims[field]
            right = transformed_claims[field]
            comparisons += 1
            if isinstance(left, (int, float)) and not isinstance(left, bool):
                okay, error, allowance = _float_close(float(left), float(right), atol, rtol)
                max_abs_error = max(max_abs_error, error)
                if allowance > 0.0:
                    max_error_ratio = max(max_error_ratio, error / allowance)
                if not okay:
                    problem(f"claims.json {field}: {left!r} != {right!r}")
            elif left != right:
                problem(f"claims.json {field}: {left!r} != {right!r}")
    except (OSError, ValueError) as exc:
        problem(str(exc))

    return {
        "passed": not messages,
        "relation": relation.get("kind", "identity"),
        "conditioning": relation.get("conditioning"),
        "comparisons": comparisons,
        "relaxed_uncertainty_checks": relaxed_checks,
        "atol": float(atol),
        "rtol": float(rtol),
        "max_abs_error": max_abs_error,
        "max_error_to_tolerance_ratio": max_error_ratio,
        "messages": messages,
    }


def run_metamorphic_suite(
    analyzer: Path,
    case_dir: Path,
    work_root: Path,
    *,
    python_executable: Path | str = sys.executable,
    timeout_seconds: float = 180.0,
    atol: float = 5e-9,
    rtol: float = 5e-8,
) -> dict[str, Any]:
    """Generate every required transform, run the analyzer, and compare outputs."""

    work_root = _prepare_empty(Path(work_root)).resolve()
    cases_root = work_root / "cases"
    outputs_root = work_root / "outputs"
    shards_root = work_root / "shards"
    cases_root.mkdir()
    outputs_root.mkdir()

    baseline_output = outputs_root / "baseline"
    run_analyzer(
        analyzer,
        case_dir,
        baseline_output,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    )

    transforms: list[tuple[str, dict[str, Any]]] = []
    row_packet_case = cases_root / "row_packet_permutation"
    transforms.append(
        (
            "row_packet_permutation",
            transform_row_and_packet_permutation(case_dir, row_packet_case),
        )
    )
    realization_case = cases_root / "realization_id_permutation"
    transforms.append(
        (
            "realization_id_permutation",
            transform_realization_id_permutation(case_dir, realization_case),
        )
    )
    energy_case = cases_root / "positive_affine_energy"
    transforms.append(
        (
            "positive_affine_energy",
            transform_positive_affine_energy(case_dir, energy_case),
        )
    )
    control_case = cases_root / "affine_control"
    transforms.append(("affine_control", transform_affine_control(case_dir, control_case)))
    mirror_case = cases_root / "target_mirror"
    transforms.append(("target_mirror", transform_target_mirror(case_dir, mirror_case)))

    split_case_into_shards(case_dir, shards_root)
    joined_case = cases_root / "shard_rejoin"
    shard_relation = rejoin_shards(shards_root, joined_case)
    shard_integrity = assert_packet_equivalent(case_dir, joined_case)
    transforms.append(("shard_rejoin", shard_relation))

    results: dict[str, Any] = {}
    for name, relation in transforms:
        output_dir = outputs_root / name
        run_analyzer(
            analyzer,
            cases_root / name,
            output_dir,
            python_executable=python_executable,
            timeout_seconds=timeout_seconds,
        )
        results[name] = compare_output_directories(
            baseline_output,
            output_dir,
            relation,
            atol=atol,
            rtol=rtol,
        )
    results["shard_rejoin"]["integrity"] = shard_integrity
    passed = all(result["passed"] for result in results.values())
    return {
        "schema_version": "spectral-scaling-metamorphic-report/v1",
        "passed": passed,
        "case": str(Path(case_dir).resolve()),
        "analyzer": str(Path(analyzer).resolve()),
        "tests": results,
    }
