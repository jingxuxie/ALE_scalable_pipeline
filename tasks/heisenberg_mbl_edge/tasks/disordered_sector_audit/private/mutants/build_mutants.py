#!/usr/bin/env python3
"""Materialize complete schema-valid scientific mutant programs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


MUTANTS = {
    "pauli_scale": "operator normalization",
    "unit_exchange": "input-parameter handling",
    "open_boundary": "Hamiltonian topology",
    "wrong_energy_normalization": "energy convention",
    "one_sided_packet": "packet selection",
    "shannon_entanglement": "observable substitution",
    "log2_entanglement": "logarithm convention",
    "s2_ipr": "participation definition",
    "mz_second_moment": "magnetization moment",
    "naive_aggregation": "realization weighting",
    "sem_over_states": "cluster uncertainty",
    "stale_evidence": "fabricated evidence",
}

EXPECTED_METRICS = {
    "pauli_scale": "spectral_packet",
    "unit_exchange": "spectral_packet",
    "open_boundary": "spectral_packet",
    "wrong_energy_normalization": "spectral_packet",
    "one_sided_packet": "spectral_packet",
    "shannon_entanglement": "entanglement_participation",
    "log2_entanglement": "entanglement_participation",
    "s2_ipr": "entanglement_participation",
    "mz_second_moment": "magnetization",
    "naive_aggregation": "realization_aggregation",
    "sem_over_states": "realization_aggregation",
    "stale_evidence": "evidence_consistency",
}


def build(task_root: Path) -> Path:
    source_path = task_root / "author" / "reference_solver" / "solution.py"
    source = source_path.read_text(encoding="utf-8")
    marker = 'MUTATION = "none"'
    if source.count(marker) != 1:
        raise RuntimeError("reference mutation marker missing or ambiguous")
    cases_root = task_root / "private" / "mutants" / "cases"
    cases_root.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    for mutant_id, category in MUTANTS.items():
        directory = cases_root / mutant_id
        directory.mkdir(parents=True, exist_ok=True)
        mutated = source.replace(marker, f'MUTATION = "{mutant_id}"')
        (directory / "solution.py").write_text(mutated, encoding="utf-8")
        manifest.append(
            {
                "mutant_id": mutant_id,
                "category": category,
                "path": f"cases/{mutant_id}/solution.py",
                "expected": "reject",
                "expected_metric": EXPECTED_METRICS[mutant_id],
            }
        )
    manifest_path = cases_root / "mutant_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"schema_version": "sector-audit-mutants/v1", "mutants": manifest},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.task_root.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
