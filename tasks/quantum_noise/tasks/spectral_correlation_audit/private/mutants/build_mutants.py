#!/usr/bin/env python3
"""Construct schema-valid scientific mutant analyzers from a valid baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"mutation anchor count is {source.count(old)}, expected one: {old[:60]}")
    return source.replace(old, new, 1)


def mutate(source: str, mutant_id: str) -> str:
    if mutant_id == "ignore-target-mask":
        return replace_once(source, "error = target ^ observed", "error = observed")
    if mutant_id == "normalized-forward-transform":
        return replace_once(source, "    return out\n\n\ndef project_simplex", "    return out / out.size\n\n\ndef project_simplex")
    if mutant_id == "ordinal-length-fit":
        return replace_once(
            source,
            "fit_lengths = lengths.astype(np.float64)",
            "fit_lengths = np.arange(lengths.size, dtype=np.float64)",
        )
    if mutant_id == "unit-nuisance-amplitude":
        return replace_once(
            source,
            "    amplitudes[0] = 1.0\n    eigenvalues[0] = 1.0",
            "    amplitudes[:] = 1.0\n    fit_rmse[:] = np.sqrt(np.mean((amplitudes[None, :] * eigenvalues[None, :] ** fit_lengths[:, None] - spectra) ** 2, axis=0))\n    amplitudes[0] = 1.0\n    eigenvalues[0] = 1.0",
        )
    if mutant_id == "unnormalized-inverse":
        return replace_once(
            source,
            "raw_distribution = fwht(eigenvalues) / state_count",
            "raw_distribution = fwht(eigenvalues)",
        )
    if mutant_id == "independent-bit-collapse":
        return replace_once(
            source,
            "    distribution = project_simplex(raw_distribution)\n    local_configuration = manifest[\"local_model\"]",
            "    distribution = project_simplex(raw_distribution)\n    independence_states = np.arange(state_count, dtype=np.int64)\n    independence_rates = [float(np.dot(distribution, (independence_states >> unit) & 1)) for unit in range(bit_count)]\n    independence_product = np.ones(state_count, dtype=np.float64)\n    for unit, rate in enumerate(independence_rates):\n        independence_product *= np.where((independence_states >> unit) & 1, rate, 1.0 - rate)\n    distribution = independence_product / independence_product.sum()\n    local_configuration = manifest[\"local_model\"]",
        )
    if mutant_id == "omit-clique-separators":
        return replace_once(
            source,
            "            denominator *= probabilities[subset_index(mask, separator)]",
            "            denominator *= 1.0",
        )
    if mutant_id == "mi-reported-as-cmi":
        return replace_once(
            source,
            '"conditional_mutual_information": max(0.0, conditional_information),',
            '"conditional_mutual_information": mutual_information,',
        )
    if mutant_id == "covariance-as-correlation":
        return replace_once(
            source,
            "pearson = covariance / math.sqrt(variance_i * variance_j) if variance_i > 0 and variance_j > 0 else 0.0",
            "pearson = covariance",
        )
    if mutant_id == "ascending-cmi-ranking":
        return replace_once(
            source,
            '-float(record["conditional_mutual_information"]),',
            'float(record["conditional_mutual_information"]),',
        )
    if mutant_id == "js-divergence-not-distance":
        return replace_once(
            source,
            "return math.sqrt(max(0.0, js_divergence)), 0.5 * float(np.sum(np.abs(left - right)))",
            "return js_divergence, 0.5 * float(np.sum(np.abs(left - right)))",
        )
    if mutant_id == "uniform-stale-analysis":
        return replace_once(
            source,
            "probabilities = corrected_counts / totals[:, None]",
            "probabilities = np.full(corrected_counts.shape, 1.0 / state_count, dtype=np.float64)",
        )
    if mutant_id == "reversed-unit-significance":
        changed = source.replace("states >> unit_i", "states >> (bit_count - 1 - unit_i)")
        changed = changed.replace("states >> unit_j", "states >> (bit_count - 1 - unit_j)")
        if changed == source:
            raise ValueError("bit-significance mutation anchor missing")
        return changed
    if mutant_id == "chain-topology-assumption":
        return replace_once(
            source,
            '    cliques = [[int(unit) for unit in clique] for clique in local_configuration["cliques"]]\n    tree_edges = [[int(endpoint) for endpoint in edge] for edge in local_configuration["tree_edges"]]',
            '    cliques = [list(range(start, start + 3)) for start in range(bit_count - 2)]\n    tree_edges = [[index, index + 1] for index in range(len(cliques) - 1)]',
        )
    raise KeyError(mutant_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output_root", type=Path)
    arguments = parser.parse_args()
    baseline = arguments.baseline.resolve()
    source_path = baseline / "analyze.py" if baseline.is_dir() else baseline
    source = source_path.read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    output_root = arguments.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    for record in manifest["mutants"]:
        destination = output_root / record["mutant_id"]
        destination.mkdir()
        (destination / "analyze.py").write_text(mutate(source, record["mutant_id"]), encoding="utf-8")
    (output_root / "mutant_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
