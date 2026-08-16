#!/usr/bin/env python3
"""Public-input reference analyzer for a finite-size spectral crossover task.

The file is deliberately self-contained.  During private evaluation an analyzer
is given only one case directory and an empty output directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


MUTATION_MODE = "wrong_l_exponent"
OUTPUT_FILES = {
    "realization_stats.csv",
    "packet_stats.csv",
    "transition.csv",
    "stability.csv",
    "predictions.csv",
    "claims.json",
}
MAX_ABS_CONTROL = 1_000_000.0
MAX_ABS_DESIGN_COORDINATE = 2.1e36
MAX_ABS_COEFFICIENT = 1_000_000.0
MAX_ABS_RAW_PREDICTION = 20_000_000.0
MAX_ABS_QUERY_Z = 2.0
MAX_BOOTSTRAP_SEED = 18_446_744_073_709_544_552
MIN_NU = 0.2
MAX_NU = 4.0
MAX_WEIGHTED_DESIGN_CONDITION = 1.0e12
MAX_WEIGHTED_RESIDUAL_SUM = 1.0e35


def strict_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            rendered = {}
            for key in fieldnames:
                value = row[key]
                if isinstance(value, (float, np.floating)):
                    rendered[key] = format(float(value), ".17g")
                else:
                    rendered[key] = value
            writer.writerow(rendered)


def float_key(value: float) -> float:
    return round(float(value), 10)


def packet_statistics(input_dir: Path, manifest: dict) -> tuple[list[dict], list[dict], dict]:
    packet_rows = read_csv(input_dir / manifest["files"]["packets"])
    with np.load(input_dir / manifest["files"]["eigenvalues"], allow_pickle=False) as archive:
        if set(archive.files) != {"energies", "schema_version"}:
            raise ValueError("eigenvalue archive has unexpected keys")
        energies = np.asarray(archive["energies"], dtype=np.float64)
    if energies.ndim != 1 or not np.all(np.isfinite(energies)):
        raise ValueError("energies must be a finite one-dimensional array")

    realization_rows: list[dict] = []
    ratio_blocks: dict[tuple, np.ndarray] = {}
    expected_offset = 0
    for row in packet_rows:
        offset = int(row["eigen_offset"])
        count = int(row["eigen_count"])
        keep = int(row["keep_count"])
        if offset != expected_offset or count < keep or keep < 5 or offset + count > energies.size:
            raise ValueError("packet offsets/counts are inconsistent")
        expected_offset += count
        chunk = np.asarray(energies[offset : offset + count], dtype=np.float64)
        target = float(row["target"])
        if MUTATION_MODE == "target_mirror":
            target = 1.0 - target
        if MUTATION_MODE == "use_shift_energy":
            target_energy = float(row["shift_energy"])
        else:
            target_energy = float(row["e_max"]) + target * (float(row["e_min"]) - float(row["e_max"]))
        nearest = np.argsort(np.abs(chunk - target_energy), kind="stable")[:keep]
        if MUTATION_MODE == "unsorted":
            selected = chunk[np.sort(nearest)]
            gaps = np.abs(np.diff(selected))
        else:
            selected = np.sort(chunk[nearest])
            gaps = np.diff(selected)
        if gaps.size < 3 or not np.all(np.isfinite(gaps)) or np.any(gaps <= 0.0):
            raise ValueError("selected spectrum is not strictly ordered")
        if MUTATION_MODE == "raw_ratio":
            ratios = np.minimum(gaps[:-1] / gaps[1:], 1.0)
        else:
            ratios = np.minimum(gaps[:-1], gaps[1:]) / np.maximum(gaps[:-1], gaps[1:])
        size = int(row["size"])
        raw_control = float(row["control"])
        if not math.isfinite(raw_control) or abs(raw_control) > MAX_ABS_CONTROL:
            raise ValueError("control lies outside the supported finite range")
        control = float_key(raw_control)
        target_key = float_key(float(row["target"]))
        realization_id = row["realization_id"]
        key = (target_key, size, control, realization_id)
        ratio_blocks[key] = ratios
        realization_rows.append(
            {
                "case_id": manifest["case_id"],
                "target": target_key,
                "size": size,
                "control": control,
                "realization_id": realization_id,
                "n_ratios": int(ratios.size),
                "mean_r": float(np.mean(ratios)),
            }
        )
    if expected_offset != energies.size:
        raise ValueError("unreferenced energies remain in the archive")

    groups: dict[tuple, list[dict]] = {}
    for row in realization_rows:
        key = (row["target"], row["size"], row["control"])
        groups.setdefault(key, []).append(row)
    packet_stats: list[dict] = []
    for key in sorted(groups):
        rows = groups[key]
        means = np.asarray([float(row["mean_r"]) for row in rows], dtype=np.float64)
        all_ratios = np.concatenate(
            [ratio_blocks[(key[0], key[1], key[2], row["realization_id"])] for row in rows]
        )
        if MUTATION_MODE == "pool_gaps":
            mean_r = float(np.mean(all_ratios))
            se_r = float(np.std(all_ratios, ddof=1) / math.sqrt(all_ratios.size))
        else:
            mean_r = float(np.mean(means))
            if MUTATION_MODE == "gap_sem":
                se_r = float(np.std(all_ratios, ddof=1) / math.sqrt(all_ratios.size))
            else:
                se_r = float(np.std(means, ddof=1) / math.sqrt(means.size))
        packet_stats.append(
            {
                "case_id": manifest["case_id"],
                "target": key[0],
                "size": key[1],
                "control": key[2],
                "n_realizations": len(rows),
                "n_ratios": int(all_ratios.size),
                "mean_r": mean_r,
                "se_r": se_r,
            }
        )
    realization_rows.sort(key=lambda row: (row["target"], row["size"], row["control"], row["realization_id"]))
    return realization_rows, packet_stats, ratio_blocks


def design_coordinate(control: np.ndarray, size: np.ndarray, hc: float, nu: float) -> np.ndarray:
    controls = np.asarray(control, dtype=np.float64)
    sizes = np.asarray(size, dtype=np.float64)
    hc_value = float(hc)
    nu_value = float(nu)
    if controls.shape != sizes.shape or controls.size == 0:
        raise ValueError("control and size arrays must be nonempty and aligned")
    if (
        not np.all(np.isfinite(controls))
        or np.any(np.abs(controls) > MAX_ABS_CONTROL)
        or not math.isfinite(hc_value)
        or abs(hc_value) > MAX_ABS_CONTROL
    ):
        raise ValueError("control coordinates lie outside the supported finite range")
    if not math.isfinite(nu_value) or not MIN_NU <= nu_value <= MAX_NU:
        raise ValueError("nu must be finite and lie in [0.2, 4.0]")
    if not np.all(np.isfinite(sizes)) or np.any(sizes <= 0.0):
        raise ValueError("sizes must be finite and positive")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore", under="ignore"):
        if MUTATION_MODE == "no_size_scaling":
            coordinate = controls - hc_value
        elif MUTATION_MODE == "wrong_l_exponent":
            coordinate = (controls - hc_value) / np.power(sizes, 1.0 / nu_value)
        else:
            coordinate = (controls - hc_value) * np.power(sizes, 1.0 / nu_value)
    coordinate = np.asarray(coordinate, dtype=np.float64)
    if (
        not np.all(np.isfinite(coordinate))
        or np.any(np.abs(coordinate) > MAX_ABS_DESIGN_COORDINATE)
    ):
        raise ValueError("finite-size design coordinate is outside the supported range")
    return coordinate


def preliminary_center(rows: list[dict]) -> float:
    """Locate the finite-size crossover before the nonlinear scaling search.

    The search window must not move with the trial critical point: allowing that
    would compare different observations at different parameter values and can
    reward a quiet tail instead of a size crossing.  We use the median control
    at which each size curve crosses its own robust plateau midpoint.
    """
    centers: list[float] = []
    for size in sorted({int(row["size"]) for row in rows}):
        curve = sorted(
            [row for row in rows if int(row["size"]) == size],
            key=lambda row: float(row["control"]),
        )
        controls = np.asarray([float(row["control"]) for row in curve], dtype=np.float64)
        values = np.asarray([float(row["mean_r"]) for row in curve], dtype=np.float64)
        flank = max(2, min(3, values.size // 3))
        midpoint = 0.5 * (float(np.median(values[:flank])) + float(np.median(values[-flank:])))
        candidates: list[float] = []
        for index in range(values.size - 1):
            left = float(values[index] - midpoint)
            right = float(values[index + 1] - midpoint)
            if left == 0.0:
                candidates.append(float(controls[index]))
            elif (
                ((left < 0.0 < right) or (left > 0.0 > right) or right == 0.0)
                and values[index + 1] != values[index]
            ):
                fraction = (midpoint - values[index]) / (values[index + 1] - values[index])
                candidates.append(float(controls[index] + fraction * (controls[index + 1] - controls[index])))
        if candidates:
            middle_control = float(np.median(controls))
            centers.append(min(candidates, key=lambda value: abs(value - middle_control)))
    if centers:
        return float(np.median(np.asarray(centers, dtype=np.float64)))
    return float(np.median(np.asarray([float(row["control"]) for row in rows], dtype=np.float64)))


def coefficients_for(
    rows: list[dict],
    hc: float,
    nu: float,
    min_size: int,
    halfwidth: float,
    selection_center: float | None = None,
) -> dict | None:
    window_center = float(hc if selection_center is None else selection_center)
    selected = [
        row for row in rows
        if int(row["size"]) >= min_size
        and abs(float(row["control"]) - window_center) <= halfwidth * (1.0 + 1e-12)
    ]
    if len(selected) < 8 or len({int(row["size"]) for row in selected}) < 3:
        return None
    control = np.asarray([float(row["control"]) for row in selected], dtype=np.float64)
    size = np.asarray([float(row["size"]) for row in selected], dtype=np.float64)
    observed = np.asarray([float(row["mean_r"]) for row in selected], dtype=np.float64)
    se = np.asarray([max(float(row["se_r"]), 0.0025) for row in selected], dtype=np.float64)
    if not np.all(np.isfinite(observed)) or not np.all(np.isfinite(se)) or np.any(se <= 0.0):
        return None
    x = design_coordinate(control, size, hc, nu)
    scale = max(float(np.max(np.abs(x))), 1.0)
    if not math.isfinite(scale) or scale <= 0.0:
        return None
    z = x / scale
    if not np.all(np.isfinite(z)):
        return None
    with np.errstate(over="ignore", invalid="ignore"):
        matrix = np.column_stack([np.ones(z.size), z, z * z, z * z * z])
    if not np.all(np.isfinite(matrix)):
        return None
    if MUTATION_MODE == "wrong_group_weight":
        weights = np.sqrt(np.asarray([float(row["n_ratios"]) for row in selected], dtype=np.float64))
        weights /= float(np.max(weights))
    else:
        weights = 1.0 / se
    if not np.all(np.isfinite(weights)) or np.any(weights <= 0.0):
        return None
    weighted_matrix = matrix * weights[:, None]
    weighted_observed = observed * weights
    if not np.all(np.isfinite(weighted_matrix)) or not np.all(np.isfinite(weighted_observed)):
        return None
    try:
        condition = float(np.linalg.cond(weighted_matrix))
    except np.linalg.LinAlgError:
        return None
    if not math.isfinite(condition) or condition > MAX_WEIGHTED_DESIGN_CONDITION:
        return None
    try:
        coefficients, _, rank, _ = np.linalg.lstsq(weighted_matrix, weighted_observed, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if (
        rank < 4
        or not np.all(np.isfinite(coefficients))
        or np.any(np.abs(coefficients) > MAX_ABS_COEFFICIENT)
    ):
        return None
    with np.errstate(over="ignore", invalid="ignore"):
        prediction = matrix @ coefficients
    if (
        not np.all(np.isfinite(prediction))
        or np.any(np.abs(prediction) > MAX_ABS_RAW_PREDICTION)
    ):
        return None
    residual = prediction - observed
    with np.errstate(over="ignore", invalid="ignore"):
        weighted_residual_sum = float(np.sum((residual * weights) ** 2))
        weight_square_sum = float(np.sum(weights**2))
    if (
        not math.isfinite(weighted_residual_sum)
        or weighted_residual_sum > MAX_WEIGHTED_RESIDUAL_SUM
        or not math.isfinite(weight_square_sum)
        or weight_square_sum <= 0.0
    ):
        return None
    rmse = float(math.sqrt(weighted_residual_sum / weight_square_sum))
    if not math.isfinite(rmse):
        return None
    return {
        "hc": float(hc),
        "nu": float(nu),
        "coefficients": coefficients,
        "x_scale": scale,
        "rmse": rmse,
        "n_groups": len(selected),
    }


def fit_scaling(
    rows: list[dict],
    min_size: int,
    halfwidth: float,
    center: tuple[float, float] | None = None,
    local: bool = False,
) -> dict:
    controls = np.asarray([float(row["control"]) for row in rows], dtype=np.float64)
    low = float(np.min(controls))
    high = float(np.max(controls))
    span = high - low
    # Keep the observation set fixed even during local refinement and bootstrap.
    # The supplied ``center`` seeds parameter bounds; it must not move the data
    # window or a noisy local optimum could lose all supporting groups.
    selection_center = preliminary_center(rows)
    if center is None:
        hc_values = np.linspace(low + 0.08 * span, high - 0.08 * span, 29)
        nu_values = np.exp(np.linspace(math.log(0.35), math.log(2.6), 23))
    else:
        hc0, nu0 = center
        hc_radius = (0.22 if local else 0.35) * max(halfwidth, 0.4)
        hc_values = np.linspace(max(low, hc0 - hc_radius), min(high, hc0 + hc_radius), 11)
        nu_values = np.exp(np.linspace(math.log(max(0.25, 0.65 * nu0)), math.log(min(3.5, 1.45 * nu0)), 11))
    best = None
    for hc in hc_values:
        for nu in nu_values:
            candidate = coefficients_for(
                rows, float(hc), float(nu), min_size, halfwidth, selection_center
            )
            if candidate is not None and (best is None or candidate["rmse"] < best["rmse"]):
                best = candidate
    if best is None:
        raise ValueError("finite-size fit has insufficient support")
    for _ in range(2):
        hc_radius = max(span / 80.0, halfwidth / 18.0)
        nu_radius = max(0.04, best["nu"] * 0.14)
        hcs = np.linspace(max(low, best["hc"] - hc_radius), min(high, best["hc"] + hc_radius), 11)
        nus = np.linspace(max(0.2, best["nu"] - nu_radius), min(4.0, best["nu"] + nu_radius), 11)
        for hc in hcs:
            for nu in nus:
                candidate = coefficients_for(
                    rows, float(hc), float(nu), min_size, halfwidth, selection_center
                )
                if candidate is not None and candidate["rmse"] < best["rmse"]:
                    best = candidate
    return best


def fixed_fit(rows: list[dict], hc: float, nu: float, min_size: int, halfwidth: float) -> dict:
    candidate = coefficients_for(rows, hc, nu, min_size, halfwidth)
    if candidate is None:
        wide = max(halfwidth, max(float(row["control"]) for row in rows) - min(float(row["control"]) for row in rows))
        candidate = coefficients_for(rows, hc, nu, min_size, wide)
    if candidate is None:
        raise ValueError("fixed mutant fit failed")
    return candidate


def bootstrap_intervals(
    target_rows: list[dict],
    realization_rows: list[dict],
    base: dict,
    min_size: int,
    halfwidth: float,
    replicates: int,
    seed: int,
) -> tuple[float, float, float, float]:
    grouped: dict[tuple, list[float]] = {}
    target = float_key(float(target_rows[0]["target"]))
    for row in realization_rows:
        if float_key(float(row["target"])) == target:
            key = (int(row["size"]), float_key(float(row["control"])))
            grouped.setdefault(key, []).append(float(row["mean_r"]))
    rng = np.random.default_rng(seed)
    hc_samples: list[float] = []
    nu_samples: list[float] = []
    template = {(int(row["size"]), float_key(float(row["control"]))): row for row in target_rows}
    for _ in range(replicates):
        sampled_rows = []
        for key, values in grouped.items():
            array = np.asarray(values, dtype=np.float64)
            sample = array[rng.integers(0, array.size, size=array.size)]
            source = template[key]
            sampled_rows.append(
                {
                    **source,
                    "mean_r": float(np.mean(sample)),
                    "se_r": float(np.std(sample, ddof=1) / math.sqrt(sample.size)),
                }
            )
        try:
            fitted = fit_scaling(sampled_rows, min_size, halfwidth, (base["hc"], base["nu"]), local=True)
        except ValueError:
            continue
        hc_samples.append(float(fitted["hc"]))
        nu_samples.append(float(fitted["nu"]))
    if len(hc_samples) < max(8, replicates // 2):
        raise ValueError("too many bootstrap fits failed")
    return (
        float(np.quantile(hc_samples, 0.16)),
        float(np.quantile(hc_samples, 0.84)),
        float(np.quantile(nu_samples, 0.16)),
        float(np.quantile(nu_samples, 0.84)),
    )


def predict(fit: dict, size: float, control: float) -> float:
    x = float(design_coordinate(np.asarray([control]), np.asarray([size]), fit["hc"], fit["nu"])[0])
    scale = float(fit["x_scale"])
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("fit has an invalid design-coordinate scale")
    z = x / scale
    if not math.isfinite(z) or abs(z) > MAX_ABS_QUERY_Z:
        raise ValueError("query lies outside the supported scaled-coordinate range")
    with np.errstate(over="ignore", invalid="ignore"):
        basis = np.asarray([1.0, z, z * z, z * z * z], dtype=np.float64)
    if not np.all(np.isfinite(basis)):
        raise ValueError("query produced a nonfinite cubic basis")
    coefficients = np.asarray(fit["coefficients"], dtype=np.float64)
    if (
        coefficients.shape != (4,)
        or not np.all(np.isfinite(coefficients))
        or np.any(np.abs(coefficients) > MAX_ABS_COEFFICIENT)
    ):
        raise ValueError("fit has invalid cubic coefficients")
    with np.errstate(over="ignore", invalid="ignore"):
        raw_prediction = float(np.dot(basis, coefficients))
    if not math.isfinite(raw_prediction) or abs(raw_prediction) > MAX_ABS_RAW_PREDICTION:
        raise ValueError("query produced an invalid raw prediction")
    return float(np.clip(raw_prediction, 0.0, 1.0))


def analyze(input_dir: Path, output_dir: Path) -> None:
    manifest = strict_json(input_dir / "manifest.json")
    bootstrap_seed_value = manifest.get("bootstrap_seed")
    if (
        isinstance(bootstrap_seed_value, bool)
        or not isinstance(bootstrap_seed_value, int)
        or bootstrap_seed_value < 0
        or bootstrap_seed_value > MAX_BOOTSTRAP_SEED
    ):
        raise ValueError(
            "bootstrap_seed must be an integer in [0, 18446744073709544552]"
        )
    bootstrap_seed = int(bootstrap_seed_value)
    grid = strict_json(input_dir / manifest["files"]["analysis_grid"])
    queries = read_csv(input_dir / manifest["files"]["queries"])
    realization_rows, packet_rows, _ = packet_statistics(input_dir, manifest)
    min_sizes = [int(value) for value in grid["min_sizes"]]
    halfwidths = [float_key(float(value)) for value in grid["halfwidths"]]
    primary_min = int(grid["primary_min_size"])
    primary_halfwidth = float_key(float(grid["primary_halfwidth"]))
    targets = sorted({float_key(float(row["target"])) for row in packet_rows})
    transition_rows: list[dict] = []
    stability_rows: list[dict] = []
    fits: dict[float, dict] = {}
    common_hc = float(np.median([float(row["control"]) for row in packet_rows]))

    for target_index, target in enumerate(targets):
        rows = [row for row in packet_rows if float_key(float(row["target"])) == target]
        base = fit_scaling(rows, primary_min, primary_halfwidth)
        if MUTATION_MODE == "constant_edge":
            base = fixed_fit(rows, common_hc, base["nu"], primary_min, primary_halfwidth)
        elif MUTATION_MODE == "hardcoded_public":
            base = fixed_fit(rows, 2.75, 0.95, primary_min, max(primary_halfwidth, 2.0))
        elif MUTATION_MODE == "largest_size_only":
            base = fit_scaling(rows, max(int(row["size"]) for row in rows) - 1, primary_halfwidth)
        if MUTATION_MODE == "no_size_scaling":
            base["nu"] = 1.0
        fits[target] = base
        target_stability = []
        for min_size in min_sizes:
            for halfwidth in halfwidths:
                if MUTATION_MODE == "no_stability":
                    fitted = base
                else:
                    fitted = fit_scaling(rows, min_size, halfwidth, (base["hc"], base["nu"]))
                target_stability.append(fitted)
                stability_rows.append(
                    {
                        "case_id": manifest["case_id"],
                        "target": target,
                        "min_size": min_size,
                        "halfwidth": halfwidth,
                        "h_c": fitted["hc"],
                        "nu": fitted["nu"],
                        "validation_rmse": fitted["rmse"],
                        "n_groups": fitted["n_groups"],
                        "fit_ok": 1,
                    }
                )
        boot = bootstrap_intervals(
            rows,
            realization_rows,
            base,
            primary_min,
            primary_halfwidth,
            int(grid["bootstrap_replicates"]),
            bootstrap_seed + 1009 * target_index,
        )
        hc_spread = float(np.std([fit["hc"] for fit in target_stability], ddof=1))
        nu_spread = float(np.std([fit["nu"] for fit in target_stability], ddof=1))
        hc_half = math.sqrt(max(base["hc"] - boot[0], boot[1] - base["hc"], 0.0) ** 2 + hc_spread**2)
        nu_half = math.sqrt(max(base["nu"] - boot[2], boot[3] - base["nu"], 0.0) ** 2 + nu_spread**2)
        if MUTATION_MODE == "skip_bootstrap":
            hc_half = 1e-6
            nu_half = 1e-6
        transition_rows.append(
            {
                "case_id": manifest["case_id"],
                "target": target,
                "h_c": base["hc"],
                "nu": base["nu"],
                "h_c_lo": base["hc"] - hc_half,
                "h_c_hi": base["hc"] + hc_half,
                "nu_lo": max(0.01, base["nu"] - nu_half),
                "nu_hi": base["nu"] + nu_half,
                "fit_score": 1.0 / (1.0 + base["rmse"] / 0.02),
                "stable": int(hc_spread <= 0.5 * primary_halfwidth and nu_spread <= 0.9),
            }
        )

    prediction_rows = []
    transition_by_target = {float_key(float(row["target"])): row for row in transition_rows}
    for row in queries:
        target = float_key(float(row["target"]))
        fitted = fits[target]
        prediction = predict(fitted, float(row["size"]), float(row["control"]))
        interval = transition_by_target[target]
        width = 0.008 + 0.025 * min(1.0, abs(float(row["control"]) - fitted["hc"]) / max(primary_halfwidth, 0.1))
        width += 0.015 * min(
            1.0,
            (float(interval["h_c_hi"]) - float(interval["h_c_lo"]))
            / max(primary_halfwidth, 0.1),
        )
        prediction_rows.append({"query_id": row["query_id"], "mean_r": prediction, "se_r": width})

    low_rows = [row for row in packet_rows if float(row["control"]) == min(float(item["control"]) for item in packet_rows)]
    high_rows = [row for row in packet_rows if float(row["control"]) == max(float(item["control"]) for item in packet_rows)]
    claims = {
        "schema_version": "spectral-scaling-claims/v1",
        "case_id": manifest["case_id"],
        "case_token": manifest["case_token"],
        "finite_size_crossover": True,
        "phase_direction": "mean_r_decreases_with_control",
        "n_realizations": len(realization_rows),
        "n_groups": len(packet_rows),
        "n_targets": len(targets),
        "low_control_mean_r": float(np.mean([float(row["mean_r"]) for row in low_rows])),
        "high_control_mean_r": float(np.mean([float(row["mean_r"]) for row in high_rows])),
    }
    if MUTATION_MODE == "stale":
        claims["case_token"] = "retired-public-token"
    if MUTATION_MODE == "fabricated_claims":
        claims["n_groups"] += 17
        claims["phase_direction"] = "mean_r_increases_with_control"

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "realization_stats.csv",
        ["case_id", "target", "size", "control", "realization_id", "n_ratios", "mean_r"],
        realization_rows,
    )
    write_csv(
        output_dir / "packet_stats.csv",
        ["case_id", "target", "size", "control", "n_realizations", "n_ratios", "mean_r", "se_r"],
        packet_rows,
    )
    write_csv(
        output_dir / "transition.csv",
        ["case_id", "target", "h_c", "nu", "h_c_lo", "h_c_hi", "nu_lo", "nu_hi", "fit_score", "stable"],
        transition_rows,
    )
    write_csv(
        output_dir / "stability.csv",
        ["case_id", "target", "min_size", "halfwidth", "h_c", "nu", "validation_rmse", "n_groups", "fit_ok"],
        stability_rows,
    )
    write_csv(output_dir / "predictions.csv", ["query_id", "mean_r", "se_r"], prediction_rows)
    (output_dir / "claims.json").write_text(
        json.dumps(claims, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    analyze(arguments.input.resolve(), arguments.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
