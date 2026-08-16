#!/usr/bin/env python3
"""Independent public-input solver for the spectral scaling audit.

This implementation deliberately uses a different inference route from the
privileged oracle.  It estimates the crossing from monotone size curves,
estimates the exponent by leave-one-size-out non-parametric collapse, and only
then constructs a universal response by isotonic regression.  Complete
realizations, rather than individual gap ratios, are resampled for intervals.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


REALIZATION_FIELDS = [
    "case_id", "target", "size", "control", "realization_id", "n_ratios", "mean_r"
]
PACKET_FIELDS = [
    "case_id", "target", "size", "control", "n_realizations", "n_ratios", "mean_r", "se_r"
]
TRANSITION_FIELDS = [
    "case_id", "target", "h_c", "nu", "h_c_lo", "h_c_hi", "nu_lo", "nu_hi",
    "fit_score", "stable"
]
STABILITY_FIELDS = [
    "case_id", "target", "min_size", "halfwidth", "h_c", "nu",
    "validation_rmse", "n_groups", "fit_ok"
]
PREDICTION_FIELDS = ["query_id", "mean_r", "se_r"]
MAX_STANDARDIZED_QUERY = 2.0
MAX_CUBIC_CONDITION = 1e12
MAX_CUBIC_COEFFICIENT = 1e6
MAX_SCALING_COORDINATE = 2.1e36
MAX_RAW_CUBIC_PREDICTION = 2e7
MAX_WEIGHTED_SQUARED_RESIDUAL = 1e35
UINT64_MAX = 2**64 - 1


def rounded(value: float) -> float:
    return round(float(value), 10)


def read_json(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return result


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            rendered = {}
            for field in fields:
                value = row[field]
                if isinstance(value, (float, np.floating)):
                    rendered[field] = format(float(value), ".17g")
                else:
                    rendered[field] = value
            writer.writerow(rendered)


def packet_statistics(input_dir: Path, manifest: dict) -> tuple[list[dict], list[dict]]:
    packets = read_csv(input_dir / manifest["files"]["packets"])
    with np.load(input_dir / manifest["files"]["eigenvalues"], allow_pickle=False) as archive:
        if set(archive.files) != {"schema_version", "energies"}:
            raise ValueError("unexpected eigenvalue archive inventory")
        energies = np.asarray(archive["energies"], dtype=np.float64)
    if energies.ndim != 1 or not np.all(np.isfinite(energies)):
        raise ValueError("energies must be one-dimensional and finite")

    realization_rows: list[dict] = []
    ratio_blocks: dict[tuple, np.ndarray] = {}
    expected_offset = 0
    for packet in packets:
        offset = int(packet["eigen_offset"])
        count = int(packet["eigen_count"])
        keep = int(packet["keep_count"])
        if offset != expected_offset or keep < 5 or count < keep or offset + count > energies.size:
            raise ValueError("inconsistent packet slice")
        expected_offset += count
        chunk = energies[offset : offset + count]
        target = float(packet["target"])
        target_energy = float(packet["e_max"]) + target * (
            float(packet["e_min"]) - float(packet["e_max"])
        )
        nearest = np.argsort(np.abs(chunk - target_energy), kind="stable")[:keep]
        selected = np.sort(chunk[nearest])
        gaps = np.diff(selected)
        if gaps.size < 3 or np.any(gaps <= 0.0) or not np.all(np.isfinite(gaps)):
            raise ValueError("selected levels do not form a finite strict spectrum")
        ratios = np.minimum(gaps[:-1], gaps[1:]) / np.maximum(gaps[:-1], gaps[1:])
        key = (
            rounded(target), int(packet["size"]), rounded(float(packet["control"])),
            packet["realization_id"],
        )
        if key in ratio_blocks:
            raise ValueError("duplicate realization key")
        ratio_blocks[key] = ratios
        realization_rows.append(
            {
                "case_id": manifest["case_id"],
                "target": key[0],
                "size": key[1],
                "control": key[2],
                "realization_id": key[3],
                "n_ratios": int(ratios.size),
                "mean_r": float(np.mean(ratios)),
            }
        )
    if expected_offset != energies.size:
        raise ValueError("the flat eigenvalue array is not covered exactly")

    grouped_rows: list[dict] = []
    grouped: dict[tuple, list[dict]] = {}
    for row in realization_rows:
        grouped.setdefault((row["target"], row["size"], row["control"]), []).append(row)
    for key in sorted(grouped):
        members = grouped[key]
        means = np.asarray([float(row["mean_r"]) for row in members], dtype=np.float64)
        n_ratios = int(sum(int(row["n_ratios"]) for row in members))
        grouped_rows.append(
            {
                "case_id": manifest["case_id"],
                "target": key[0],
                "size": key[1],
                "control": key[2],
                "n_realizations": len(members),
                "n_ratios": n_ratios,
                "mean_r": float(np.mean(means)),
                "se_r": float(np.std(means, ddof=1) / math.sqrt(means.size)),
            }
        )
    realization_rows.sort(
        key=lambda row: (row["target"], row["size"], row["control"], row["realization_id"])
    )
    return realization_rows, grouped_rows


def isotonic_decreasing(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Weighted pool-adjacent-violators regression in descending order."""
    y = np.asarray(values, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    if y.size == 0 or y.size != w.size:
        raise ValueError("invalid isotonic arrays")
    starts: list[int] = []
    ends: list[int] = []
    sums: list[float] = []
    totals: list[float] = []
    for index in range(y.size):
        starts.append(index)
        ends.append(index + 1)
        sums.append(float(y[index] * w[index]))
        totals.append(float(w[index]))
        while len(sums) >= 2 and sums[-2] / totals[-2] < sums[-1] / totals[-1]:
            starts[-2] = starts[-2]
            ends[-2] = ends[-1]
            sums[-2] += sums[-1]
            totals[-2] += totals[-1]
            starts.pop()
            ends.pop()
            sums.pop()
            totals.pop()
    fitted = np.empty_like(y)
    for start, end, total_y, total_w in zip(starts, ends, sums, totals):
        fitted[start:end] = total_y / total_w
    return fitted


def weighted_median(values: list[float], weights: list[float]) -> float:
    array = np.asarray(values, dtype=np.float64)
    weight = np.asarray(weights, dtype=np.float64)
    order = np.argsort(array, kind="stable")
    array = array[order]
    weight = weight[order]
    cumulative = np.cumsum(weight)
    return float(array[int(np.searchsorted(cumulative, 0.5 * cumulative[-1], side="left"))])


def curve(rows: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ordered = sorted(rows, key=lambda row: float(row["control"]))
    controls = np.asarray([float(row["control"]) for row in ordered], dtype=np.float64)
    means = np.asarray([float(row["mean_r"]) for row in ordered], dtype=np.float64)
    sem = np.asarray([max(float(row["se_r"]), 0.004) for row in ordered], dtype=np.float64)
    if controls.size < 3 or np.any(np.diff(controls) <= 0.0):
        raise ValueError("each size must have at least three ordered controls")
    weights = 1.0 / np.square(sem)
    return controls, isotonic_decreasing(means, weights), sem


def inverse_curve(controls: np.ndarray, values: np.ndarray, level: float) -> float:
    descending = np.minimum.accumulate(values)
    # Repeated plateaus are harmless after a deterministic microscopic tilt.
    tilted = descending - np.arange(descending.size, dtype=np.float64) * 1e-12
    return float(np.interp(level, tilted[::-1], controls[::-1]))


def crossing_structure(rows: list[dict], min_size: int, control_scale: float) -> dict:
    control_scale = float(control_scale)
    if not math.isfinite(control_scale) or control_scale <= 0.0:
        raise ValueError("crossing objective requires a positive finite control scale")
    by_size: dict[int, list[dict]] = {}
    for row in rows:
        size = int(row["size"])
        if size >= min_size:
            by_size.setdefault(size, []).append(row)
    sizes = sorted(by_size)
    if len(sizes) < 3:
        raise ValueError("at least three retained sizes are required")
    curves = {size: curve(by_size[size]) for size in sizes}

    low_level = float(np.median([curves[size][1][0] for size in sizes]))
    high_level = float(np.median([curves[size][1][-1] for size in sizes]))
    middle_level = 0.5 * (low_level + high_level)
    midpoints = [inverse_curve(curves[size][0], curves[size][1], middle_level) for size in sizes]
    provisional = float(np.median(np.asarray(midpoints)))

    roots: list[float] = []
    root_weights: list[float] = []
    root_levels: list[float] = []
    for left_index, left_size in enumerate(sizes):
        left_h, left_y, _ = curves[left_size]
        for right_size in sizes[left_index + 1 :]:
            right_h, right_y, _ = curves[right_size]
            lower = max(float(left_h[0]), float(right_h[0]))
            upper = min(float(left_h[-1]), float(right_h[-1]))
            if not lower < upper:
                continue
            grid = np.linspace(lower, upper, 501)
            yl = np.interp(grid, left_h, left_y)
            yr = np.interp(grid, right_h, right_y)
            difference = yl - yr
            candidates: list[float] = []
            for index in range(grid.size - 1):
                first = float(difference[index])
                second = float(difference[index + 1])
                if first == 0.0:
                    candidates.append(float(grid[index]))
                elif first * second < 0.0:
                    fraction = abs(first) / (abs(first) + abs(second))
                    candidates.append(float(grid[index] + fraction * (grid[index + 1] - grid[index])))
            if not candidates:
                local = np.abs(difference)
                allowed = np.abs(grid - provisional) <= 0.45 * (upper - lower)
                if np.any(allowed):
                    masked = np.where(allowed, local, np.inf)
                    if float(np.min(masked)) <= 0.020:
                        candidates.append(float(grid[int(np.argmin(masked))]))
            if candidates:
                chosen = min(candidates, key=lambda value: abs(value - provisional))
                level = 0.5 * (
                    float(np.interp(chosen, left_h, left_y))
                    + float(np.interp(chosen, right_h, right_y))
                )
                central_low = high_level + 0.10 * (low_level - high_level)
                central_high = low_level - 0.10 * (low_level - high_level)
                if central_low <= level <= central_high:
                    roots.append(chosen)
                    root_weights.append(abs(math.log(float(right_size) / float(left_size))) + 0.05)
                    root_levels.append(level)

    if roots:
        crossing = weighted_median(roots, root_weights)
        crossing_level = weighted_median(root_levels, root_weights)
    else:
        lower = max(float(curves[size][0][0]) for size in sizes)
        upper = min(float(curves[size][0][-1]) for size in sizes)
        grid = np.linspace(lower, upper, 501)
        predictions = np.vstack(
            [np.interp(grid, curves[size][0], curves[size][1]) for size in sizes]
        )
        middle = np.mean(predictions, axis=0)
        central = (middle >= high_level + 0.10 * (low_level - high_level)) & (
            middle <= low_level - 0.10 * (low_level - high_level)
        )
        variance = np.var(predictions, axis=0)
        crossing = float(grid[int(np.argmin(np.where(central, variance, np.inf)))])
        crossing_level = float(np.mean([np.interp(crossing, curves[size][0], curves[size][1]) for size in sizes]))

    common_low = max(float(curves[size][1][-1]) for size in sizes)
    common_high = min(float(curves[size][1][0]) for size in sizes)
    span = max(common_high - common_low, 0.02)
    level_low = common_low + 0.18 * span
    level_high = common_high - 0.18 * span
    center = min(max(crossing_level, level_low), level_high)
    levels = np.linspace(max(level_low, center - 0.045), min(level_high, center + 0.045), 15)
    if levels.size == 0 or levels[0] > levels[-1]:
        levels = np.asarray([center])

    best = None
    log_sizes = np.log(np.asarray(sizes, dtype=np.float64))
    for level in levels:
        centers = np.asarray(
            [inverse_curve(curves[size][0], curves[size][1], float(level)) for size in sizes],
            dtype=np.float64,
        )
        for correction_power in np.linspace(0.45, 1.25, 9):
            decay = np.power(np.asarray(sizes, dtype=np.float64), -float(correction_power))
            matrix = np.column_stack([np.ones(decay.size), decay])
            coefficients, _, _, _ = np.linalg.lstsq(matrix, centers, rcond=None)
            if not np.all(np.isfinite(coefficients)):
                raise ValueError("crossing extrapolation produced non-finite coefficients")
            intercept = float(coefficients[0])
            residual = centers - matrix @ coefficients
            if not np.all(np.isfinite(residual)):
                raise ValueError("crossing extrapolation produced non-finite residuals")
            center_rmse = float(math.sqrt(np.mean(np.square(residual))))

            slopes: list[float] = []
            valid_sizes: list[float] = []
            for size, center_h in zip(sizes, centers):
                controls, _, _ = curves[size]
                raw_rows = sorted(by_size[size], key=lambda row: float(row["control"]))
                raw_y = np.asarray([float(row["mean_r"]) for row in raw_rows], dtype=np.float64)
                raw_se = np.asarray([max(float(row["se_r"]), 0.004) for row in raw_rows])
                nearest = np.argsort(np.abs(controls - center_h), kind="stable")[: min(4, controls.size)]
                local_h = controls[nearest] - center_h
                order = np.argsort(local_h)
                local_h = local_h[order]
                local_y = raw_y[nearest][order]
                local_w = 1.0 / raw_se[nearest][order]
                degree = min(2, local_h.size - 1)
                design = np.column_stack([np.power(local_h, power) for power in range(degree + 1)])
                weighted_design = design * local_w[:, None]
                weighted_y = local_y * local_w
                if not np.all(np.isfinite(weighted_design)) or not np.all(np.isfinite(weighted_y)):
                    raise ValueError("local slope polynomial contains non-finite values")
                coef, _, _, _ = np.linalg.lstsq(weighted_design, weighted_y, rcond=None)
                if not np.all(np.isfinite(coef)):
                    raise ValueError("local slope polynomial produced non-finite coefficients")
                slope = -float(coef[1]) if coef.size > 1 else 0.0
                if math.isfinite(slope) and slope > 1e-4:
                    slopes.append(slope)
                    valid_sizes.append(float(size))
            if len(slopes) >= 3:
                log_sizes_for_fit = np.log(np.asarray(valid_sizes, dtype=np.float64))
                log_slopes_for_fit = np.log(np.asarray(slopes, dtype=np.float64))
                if not np.all(np.isfinite(log_sizes_for_fit)) or not np.all(np.isfinite(log_slopes_for_fit)):
                    raise ValueError("slope polynomial received non-finite logarithms")
                slope_coef = np.polyfit(log_sizes_for_fit, log_slopes_for_fit, 1)
                if not np.all(np.isfinite(slope_coef)):
                    raise ValueError("slope polynomial produced non-finite coefficients")
                exponent_power = float(slope_coef[0])
                predicted_log = np.polyval(slope_coef, log_sizes_for_fit)
                if not np.all(np.isfinite(predicted_log)):
                    raise ValueError("slope polynomial produced non-finite predictions")
                slope_rmse = float(math.sqrt(np.mean(np.square(log_slopes_for_fit - predicted_log))))
            else:
                exponent_power = 1.0
                slope_rmse = 0.8
            intercept_distance = abs(intercept - crossing)
            objective = (
                center_rmse / (0.018 * control_scale)
                + 0.65 * intercept_distance / (0.14 * control_scale)
                + 0.30 * slope_rmse
                + 0.025 * abs(float(correction_power) - 0.9)
            )
            candidate = {
                "objective": objective,
                "level": float(level),
                "centers": centers,
                "correction_power": float(correction_power),
                "intercept": intercept,
                "correction_amplitude": float(coefficients[1]),
                "slope_power": exponent_power,
                "slope_rmse": slope_rmse,
            }
            if best is None or candidate["objective"] < best["objective"]:
                best = candidate
    if best is None:
        raise ValueError("could not infer crossing structure")

    # Pair crossings are less sensitive than a four-point extrapolated intercept;
    # retain a small contribution from the latter to remove leading drift.
    best["h_c"] = 0.72 * crossing + 0.28 * best["intercept"]
    decay = np.power(np.asarray(sizes, dtype=np.float64), -best["correction_power"])
    best["correction_amplitude"] = float(
        np.dot(decay, best["centers"] - best["h_c"]) / max(np.dot(decay, decay), 1e-12)
    )
    best["sizes"] = sizes
    best["crossing"] = crossing
    best["curves"] = curves
    return best


def scaled_x(rows: list[dict], hc: float, nu: float, amplitude: float, correction_power: float) -> np.ndarray:
    control = np.asarray([float(row["control"]) for row in rows], dtype=np.float64)
    size = np.asarray([float(row["size"]) for row in rows], dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        effective_center = hc + amplitude * np.power(size, -correction_power)
        coordinate = (control - effective_center) * np.power(size, 1.0 / nu)
    if (
        not np.all(np.isfinite(coordinate))
        or (coordinate.size and float(np.max(np.abs(coordinate))) > MAX_SCALING_COORDINATE)
    ):
        raise ValueError("raw scaling coordinate exceeds the float64 safety bound")
    return coordinate


def response_curve(x: np.ndarray, y: np.ndarray, sem: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if (
        not np.all(np.isfinite(x))
        or (x.size and float(np.max(np.abs(x))) > MAX_SCALING_COORDINATE)
    ):
        raise ValueError("response curve received an invalid raw scaling coordinate")
    order = np.argsort(x, kind="stable")
    ordered_x = np.asarray(x[order], dtype=np.float64)
    ordered_y = np.asarray(y[order], dtype=np.float64)
    ordered_w = 1.0 / np.square(np.maximum(np.asarray(sem[order]), 0.004))
    fitted = isotonic_decreasing(ordered_y, ordered_w)
    # Exact duplicate coordinates are collapsed so interpolation is unambiguous.
    unique_x: list[float] = []
    unique_y: list[float] = []
    unique_w: list[float] = []
    for value_x, value_y, value_w in zip(ordered_x, fitted, ordered_w):
        if unique_x and abs(value_x - unique_x[-1]) <= 1e-12:
            total = unique_w[-1] + float(value_w)
            unique_y[-1] = (unique_y[-1] * unique_w[-1] + float(value_y) * float(value_w)) / total
            unique_w[-1] = total
        else:
            unique_x.append(float(value_x))
            unique_y.append(float(value_y))
            unique_w.append(float(value_w))
    return np.asarray(unique_x), np.asarray(unique_y)


def collapse_cv(rows: list[dict], hc: float, nu: float, amplitude: float, correction_power: float) -> float:
    sizes = sorted({int(row["size"]) for row in rows})
    if len(sizes) < 3:
        return math.inf
    errors: list[float] = []
    weights: list[float] = []
    for held_size in sizes:
        training = [row for row in rows if int(row["size"]) != held_size]
        held = [row for row in rows if int(row["size"]) == held_size]
        train_x = scaled_x(training, hc, nu, amplitude, correction_power)
        train_y = np.asarray([float(row["mean_r"]) for row in training], dtype=np.float64)
        train_se = np.asarray([float(row["se_r"]) for row in training], dtype=np.float64)
        response_x, response_y = response_curve(train_x, train_y, train_se)
        held_x = scaled_x(held, hc, nu, amplitude, correction_power)
        prediction = np.interp(held_x, response_x, response_y)
        observed = np.asarray([float(row["mean_r"]) for row in held], dtype=np.float64)
        sem = np.asarray([max(float(row["se_r"]), 0.006) for row in held], dtype=np.float64)
        errors.extend((prediction - observed).tolist())
        weights.extend((1.0 / np.square(sem)).tolist())
    error = np.asarray(errors, dtype=np.float64)
    weight = np.asarray(weights, dtype=np.float64)
    return float(math.sqrt(np.dot(weight, np.square(error)) / np.sum(weight)))


def reference_window_center(rows: list[dict]) -> float:
    """Apply the public fixed-window convention before the independent fit."""
    per_size: list[float] = []
    for size in sorted({int(row["size"]) for row in rows}):
        curve = sorted(
            (row for row in rows if int(row["size"]) == size),
            key=lambda row: float(row["control"]),
        )
        controls = np.asarray([float(row["control"]) for row in curve], dtype=np.float64)
        means = np.asarray([float(row["mean_r"]) for row in curve], dtype=np.float64)
        flank = max(2, min(3, means.size // 3))
        level = 0.5 * (float(np.median(means[:flank])) + float(np.median(means[-flank:])))
        crossings: list[float] = []
        for index in range(means.size - 1):
            left = float(means[index] - level)
            right = float(means[index + 1] - level)
            if left == 0.0:
                crossings.append(float(controls[index]))
            elif (
                ((left < 0.0 < right) or (left > 0.0 > right) or right == 0.0)
                and means[index + 1] != means[index]
            ):
                fraction = (level - means[index]) / (means[index + 1] - means[index])
                crossings.append(float(controls[index] + fraction * (controls[index + 1] - controls[index])))
        if crossings:
            middle = float(np.median(controls))
            per_size.append(min(crossings, key=lambda value: abs(value - middle)))
    if per_size:
        return float(np.median(np.asarray(per_size, dtype=np.float64)))
    return float(np.median(np.asarray([float(row["control"]) for row in rows], dtype=np.float64)))


def public_cubic_diagnostic(rows: list[dict], hc: float, nu: float) -> float:
    """Report the contract's common residual diagnostic for any estimator."""
    if not math.isfinite(hc) or not math.isfinite(nu) or nu <= 0.0:
        raise ValueError("public cubic diagnostic received invalid h_c/nu")
    control = np.asarray([float(row["control"]) for row in rows], dtype=np.float64)
    size = np.asarray([float(row["size"]) for row in rows], dtype=np.float64)
    observed = np.asarray([float(row["mean_r"]) for row in rows], dtype=np.float64)
    sem = np.asarray([max(float(row["se_r"]), 0.0025) for row in rows], dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        x = (control - float(hc)) * np.power(size, 1.0 / float(nu))
    if not np.all(np.isfinite(x)) or float(np.max(np.abs(x))) > MAX_SCALING_COORDINATE:
        raise ValueError("public cubic diagnostic scaling coordinate exceeds the float64 safety bound")
    scale = max(float(np.max(np.abs(x))), 1.0)
    z = x / scale
    if not np.all(np.isfinite(z)) or np.any(np.abs(z) > 1.0 + 4.0 * np.finfo(np.float64).eps):
        raise ValueError("public cubic diagnostic standardized coordinates are invalid")
    matrix = np.column_stack([np.ones(z.size), z, z * z, z * z * z])
    weights = 1.0 / sem
    weighted_matrix = matrix * weights[:, None]
    weighted_observed = observed * weights
    condition = float(np.linalg.cond(weighted_matrix))
    if (
        not np.all(np.isfinite(matrix))
        or not np.all(np.isfinite(weighted_matrix))
        or not np.all(np.isfinite(weighted_observed))
        or not math.isfinite(condition)
        or condition > MAX_CUBIC_CONDITION
    ):
        raise ValueError("public cubic diagnostic exceeds the conditioning bound")
    coefficients, _, rank, _ = np.linalg.lstsq(
        weighted_matrix, weighted_observed, rcond=None
    )
    if (
        rank < 4
        or not np.all(np.isfinite(coefficients))
        or float(np.max(np.abs(coefficients))) > MAX_CUBIC_COEFFICIENT
    ):
        raise ValueError("public cubic diagnostic is rank deficient")
    raw_prediction = matrix @ coefficients
    if (
        not np.all(np.isfinite(raw_prediction))
        or float(np.max(np.abs(raw_prediction))) > MAX_RAW_CUBIC_PREDICTION
    ):
        raise ValueError("public cubic diagnostic produced an unsafe raw prediction")
    with np.errstate(over="ignore", invalid="ignore"):
        residual = raw_prediction - observed
        weighted_residual = residual * weights
        squared_residual = np.square(weighted_residual)
        squared_weight = np.square(weights)
        numerator = float(np.sum(squared_residual))
        denominator = float(np.sum(squared_weight))
    if (
        not np.all(np.isfinite(residual))
        or not np.all(np.isfinite(weighted_residual))
        or not np.all(np.isfinite(squared_residual))
        or not np.all(np.isfinite(squared_weight))
        or not math.isfinite(numerator)
        or numerator > MAX_WEIGHTED_SQUARED_RESIDUAL
        or not math.isfinite(denominator)
        or denominator <= 0.0
    ):
        raise ValueError("public cubic diagnostic residual reduction exceeds the float64 safety bound")
    rmse = float(math.sqrt(numerator / denominator))
    if not math.isfinite(rmse):
        raise ValueError("public cubic diagnostic produced a non-finite RMSE")
    return rmse


def fit_scaling(rows: list[dict], min_size: int, halfwidth: float, fast: bool = False) -> dict:
    retained = [row for row in rows if int(row["size"]) >= min_size]
    # The fast path is used only for bootstrap replicates.  Its crossing
    # penalties must be dimensionless so uncertainty intervals commute with a
    # positive affine change of the control coordinate.  Full point/stability
    # fits retain the independently calibrated objective.
    crossing_scale = halfwidth if fast else 1.0
    structure = crossing_structure(retained, min_size, crossing_scale)
    hc = float(structure["h_c"])
    correction_power = float(structure["correction_power"])
    amplitude = float(structure["correction_amplitude"])
    window_center = reference_window_center(rows)
    selected = [
        row
        for row in retained
        if abs(float(row["control"]) - window_center) <= halfwidth * (1.0 + 1e-12)
    ]
    if len(selected) < 8 or len({int(row["size"]) for row in selected}) < 3:
        raise ValueError("fixed public stability window has insufficient support")

    slope_power = float(structure["slope_power"])
    slope_nu = 1.0 / slope_power if 0.35 <= slope_power <= 2.5 else 1.0
    count = 15 if fast else 31
    broad = np.exp(np.linspace(math.log(0.42), math.log(2.25), count))
    local = np.exp(
        np.linspace(math.log(max(0.38, 0.58 * slope_nu)), math.log(min(2.5, 1.65 * slope_nu)), count)
    )
    candidates = np.unique(np.concatenate([broad, local]))
    best_nu = 1.0
    best_objective = math.inf
    best_rmse = math.inf
    for nu in candidates:
        rmse = collapse_cv(selected, hc, float(nu), amplitude, correction_power)
        regularization = 0.0015 * abs(math.log(float(nu) / max(slope_nu, 0.25)))
        objective = rmse + regularization
        if objective < best_objective:
            best_objective = objective
            best_rmse = rmse
            best_nu = float(nu)
    for _ in range(2 if not fast else 1):
        refinement = np.exp(
            np.linspace(math.log(max(0.30, 0.82 * best_nu)), math.log(min(3.0, 1.22 * best_nu)), 13)
        )
        for nu in refinement:
            rmse = collapse_cv(selected, hc, float(nu), amplitude, correction_power)
            regularization = 0.0015 * abs(math.log(float(nu) / max(slope_nu, 0.25)))
            objective = rmse + regularization
            if objective < best_objective:
                best_objective = objective
                best_rmse = rmse
                best_nu = float(nu)

    if not math.isfinite(best_nu) or not 0.2 <= best_nu <= 4.0:
        raise ValueError("fitted point exponent lies outside the public domain")
    x = scaled_x(selected, hc, best_nu, amplitude, correction_power)
    observed = np.asarray([float(row["mean_r"]) for row in selected], dtype=np.float64)
    sem = np.asarray([float(row["se_r"]) for row in selected], dtype=np.float64)
    response_x, response_y = response_curve(x, observed, sem)
    x_scale = max(float(np.max(np.abs(x))), 1.0)
    fitted_at_data = np.interp(x, response_x, response_y)
    if not np.all(np.isfinite(fitted_at_data)):
        raise ValueError("response interpolation produced non-finite fitted values")
    fit_rmse = float(math.sqrt(np.mean(np.square(fitted_at_data - observed))))
    diagnostic_rmse = public_cubic_diagnostic(selected, hc, best_nu)
    return {
        "h_c": hc,
        "nu": best_nu,
        "correction_power": correction_power,
        "correction_amplitude": amplitude,
        "response_x": response_x,
        "response_y": response_y,
        "x_scale": x_scale,
        "validation_rmse": diagnostic_rmse,
        "collapse_cv_rmse": best_rmse,
        "fit_rmse": fit_rmse,
        "n_groups": len(selected),
    }


def predict(model: dict, size: float, control: float) -> float:
    if not math.isfinite(size) or not math.isfinite(control) or size <= 0.0:
        raise ValueError("prediction received an invalid size/control")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        numeric_size = np.float64(size)
        effective = model["h_c"] + model["correction_amplitude"] * np.power(
            numeric_size, -model["correction_power"]
        )
        x = float((control - effective) * np.power(numeric_size, 1.0 / model["nu"]))
    if not math.isfinite(x) or abs(x) > MAX_SCALING_COORDINATE:
        raise ValueError("prediction raw scaling coordinate exceeds the float64 safety bound")
    x_scale = float(model["x_scale"])
    if not math.isfinite(x_scale) or x_scale <= 0.0:
        raise ValueError("prediction scaling normalization is invalid")
    z = x / x_scale
    if not math.isfinite(z) or abs(z) > MAX_STANDARDIZED_QUERY:
        raise ValueError("prediction standardized coordinate exceeds the extrapolation bound")
    value = float(np.interp(x, model["response_x"], model["response_y"]))
    if not math.isfinite(value):
        raise ValueError("prediction produced a non-finite raw response")
    return float(np.clip(value, 0.0, 1.0))


def bootstrap_fits(
    target_rows: list[dict],
    realization_rows: list[dict],
    min_size: int,
    halfwidth: float,
    replicates: int,
    seed: int,
) -> tuple[list[float], list[float]]:
    target = rounded(float(target_rows[0]["target"]))
    blocks: dict[tuple, list[float]] = {}
    for row in realization_rows:
        if rounded(float(row["target"])) == target:
            key = (int(row["size"]), rounded(float(row["control"])))
            blocks.setdefault(key, []).append(float(row["mean_r"]))
    templates = {
        (int(row["size"]), rounded(float(row["control"]))): row for row in target_rows
    }
    rng = np.random.default_rng(seed)
    hc_values: list[float] = []
    nu_values: list[float] = []
    for _ in range(replicates):
        sampled_rows: list[dict] = []
        for key in sorted(blocks):
            values = np.asarray(blocks[key], dtype=np.float64)
            sampled = values[rng.integers(0, values.size, size=values.size)]
            source = templates[key]
            sampled_rows.append(
                {
                    **source,
                    "mean_r": float(np.mean(sampled)),
                    "se_r": float(np.std(sampled, ddof=1) / math.sqrt(sampled.size)),
                }
            )
        try:
            model = fit_scaling(sampled_rows, min_size, halfwidth, fast=True)
        except ValueError:
            continue
        hc_values.append(float(model["h_c"]))
        nu_values.append(float(model["nu"]))
    return hc_values, nu_values


def analyze(input_dir: Path, output_dir: Path) -> None:
    manifest = read_json(input_dir / "manifest.json")
    raw_bootstrap_seed = manifest.get("bootstrap_seed")
    if type(raw_bootstrap_seed) is not int or not 0 <= raw_bootstrap_seed <= UINT64_MAX:
        raise ValueError("manifest bootstrap_seed must be an unsigned 64-bit integer")
    bootstrap_seed = int(raw_bootstrap_seed)
    grid = read_json(input_dir / manifest["files"]["analysis_grid"])
    queries = read_csv(input_dir / manifest["files"]["queries"])
    realization_rows, grouped_rows = packet_statistics(input_dir, manifest)
    targets = sorted({rounded(float(row["target"])) for row in grouped_rows})
    min_sizes = [int(value) for value in grid["min_sizes"]]
    halfwidths = [rounded(float(value)) for value in grid["halfwidths"]]
    primary_min = int(grid["primary_min_size"])
    primary_halfwidth = rounded(float(grid["primary_halfwidth"]))

    models: dict[float, dict] = {}
    transition_rows: list[dict] = []
    stability_rows: list[dict] = []
    transition_by_target: dict[float, dict] = {}
    for target_index, target in enumerate(targets):
        target_rows = [row for row in grouped_rows if rounded(float(row["target"])) == target]
        variants: dict[tuple[int, float], dict] = {}
        for min_size in min_sizes:
            for halfwidth in halfwidths:
                model = fit_scaling(target_rows, min_size, halfwidth)
                variants[(min_size, rounded(halfwidth))] = model
                stability_rows.append(
                    {
                        "case_id": manifest["case_id"],
                        "target": target,
                        "min_size": min_size,
                        "halfwidth": halfwidth,
                        "h_c": model["h_c"],
                        "nu": model["nu"],
                        "validation_rmse": model["validation_rmse"],
                        "n_groups": model["n_groups"],
                        "fit_ok": 1,
                    }
                )
        base_key = (primary_min, rounded(primary_halfwidth))
        base = variants.get(base_key)
        if base is None:
            base = fit_scaling(target_rows, primary_min, primary_halfwidth)
        models[target] = base

        target_bootstrap_seed = bootstrap_seed + 1301 * target_index
        boot_hc, boot_nu = bootstrap_fits(
            target_rows,
            realization_rows,
            primary_min,
            primary_halfwidth,
            int(grid["bootstrap_replicates"]),
            target_bootstrap_seed,
        )
        variant_hc = np.asarray([model["h_c"] for model in variants.values()], dtype=np.float64)
        variant_nu = np.asarray([model["nu"] for model in variants.values()], dtype=np.float64)
        hc_spread = float(np.std(variant_hc, ddof=1)) if variant_hc.size > 1 else 0.0
        nu_spread = float(np.std(variant_nu, ddof=1)) if variant_nu.size > 1 else 0.0
        if len(boot_hc) >= max(8, int(grid["bootstrap_replicates"]) // 2):
            hc_low, hc_high = [float(value) for value in np.quantile(np.asarray(boot_hc), [0.16, 0.84])]
            nu_low, nu_high = [float(value) for value in np.quantile(np.asarray(boot_nu), [0.16, 0.84])]
            hc_stat = max(
                base["h_c"] - hc_low,
                hc_high - base["h_c"],
                0.03 * primary_halfwidth,
            )
            nu_stat = max(base["nu"] - nu_low, nu_high - base["nu"], 0.06)
        else:
            hc_stat = 0.12 * primary_halfwidth
            nu_stat = 0.25
        hc_half = math.sqrt(hc_stat * hc_stat + hc_spread * hc_spread)
        nu_half = math.sqrt(nu_stat * nu_stat + nu_spread * nu_spread)
        transition = {
            "case_id": manifest["case_id"],
            "target": target,
            "h_c": base["h_c"],
            "nu": base["nu"],
            "h_c_lo": base["h_c"] - hc_half,
            "h_c_hi": base["h_c"] + hc_half,
            "nu_lo": max(0.02, base["nu"] - nu_half),
            "nu_hi": base["nu"] + nu_half,
            "fit_score": 1.0 / (1.0 + base["validation_rmse"] / 0.02),
            "stable": int(hc_spread <= 0.5 * primary_halfwidth and nu_spread <= 0.90),
        }
        transition_rows.append(transition)
        transition_by_target[target] = transition

    prediction_rows: list[dict] = []
    for query in queries:
        target = rounded(float(query["target"]))
        model = models[target]
        value = predict(model, float(query["size"]), float(query["control"]))
        transition = transition_by_target[target]
        distance = abs(float(query["control"]) - model["h_c"]) / max(primary_halfwidth, 0.1)
        transition_width = float(transition["h_c_hi"] - transition["h_c_lo"])
        uncertainty = (
            0.009
            + min(0.022, 0.80 * float(model["validation_rmse"]))
            + 0.011 * min(1.0, distance)
            + 0.010 * min(1.0, transition_width / max(primary_halfwidth, 0.1))
        )
        prediction_rows.append(
            {"query_id": query["query_id"], "mean_r": value, "se_r": min(0.08, uncertainty)}
        )

    minimum_control = min(float(row["control"]) for row in grouped_rows)
    maximum_control = max(float(row["control"]) for row in grouped_rows)
    low_rows = [row for row in grouped_rows if float(row["control"]) == minimum_control]
    high_rows = [row for row in grouped_rows if float(row["control"]) == maximum_control]
    claims = {
        "schema_version": "spectral-scaling-claims/v1",
        "case_id": manifest["case_id"],
        "case_token": manifest["case_token"],
        "finite_size_crossover": True,
        "phase_direction": "mean_r_decreases_with_control",
        "n_realizations": len(realization_rows),
        "n_groups": len(grouped_rows),
        "n_targets": len(targets),
        "low_control_mean_r": float(np.mean([float(row["mean_r"]) for row in low_rows])),
        "high_control_mean_r": float(np.mean([float(row["mean_r"]) for row in high_rows])),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "realization_stats.csv", REALIZATION_FIELDS, realization_rows)
    write_csv(output_dir / "packet_stats.csv", PACKET_FIELDS, grouped_rows)
    write_csv(output_dir / "transition.csv", TRANSITION_FIELDS, transition_rows)
    write_csv(output_dir / "stability.csv", STABILITY_FIELDS, stability_rows)
    write_csv(output_dir / "predictions.csv", PREDICTION_FIELDS, prediction_rows)
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
