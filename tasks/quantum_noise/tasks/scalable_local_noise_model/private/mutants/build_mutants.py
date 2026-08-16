#!/usr/bin/env python3
"""Build realistic scientific mutant submissions from the clean-room solver."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path


TASK_ROOT = Path(__file__).resolve().parents[2]
REFERENCE = TASK_ROOT / "author" / "reference_solver" / "solve.py"
CASES = TASK_ROOT / "private" / "mutants" / "cases"

MUTANTS = [
    ("wrong_endian", "coordinate-convention", "Treat the first local scope variable as the most-significant rather than least-significant bit."),
    ("ignore_context", "omitted-interaction", "Discard separator context and fit only pooled new-variable marginals."),
    ("uniform_root", "omitted-marginal", "Replace the learned root marginal by a uniform table."),
    ("no_smoothing", "omitted-normalization-guard", "Remove the disclosed half-count smoothing on sparse hidden cases."),
    ("query_product", "cross-clique-independence", "Answer multi-variable queries as products of singleton probabilities."),
    ("ascending_audit", "wrong-ranking-direction", "Rank the smallest standardized residual as most anomalous."),
    ("single_topology_failure", "concealed-topology-failure", "Over-shrink factors only for a disclosed three-way-junction layout."),
    ("validation_contamination", "validation-leakage", "Tilt fitted root probabilities using held-out validation outcomes."),
    ("hash_nondeterminism", "nondeterministic-output", "Perturb root factors using Python's randomized string hash."),
    ("stale_identity", "stale-cache", "Return artifacts labeled with a fixed public-like instance identity."),
    ("truncate_tree", "partial-model", "Omit the final clique factor and emit incomplete sidecars."),
]


def build() -> dict:
    source = REFERENCE.read_text(encoding="utf-8")
    marker = 'MUTATION = "none"'
    if source.count(marker) != 1:
        raise RuntimeError("reference mutation marker changed")
    if CASES.exists():
        if TASK_ROOT.resolve() not in CASES.resolve().parents:
            raise RuntimeError("refusing to reset mutant cases outside the task root")
        def writable_retry(function, target, _exc_info):
            os.chmod(target, stat.S_IWRITE)
            function(target)
        shutil.rmtree(CASES, onerror=writable_retry)
    CASES.mkdir(parents=True)
    records = []
    for mutant_id, category, description in MUTANTS:
        target = CASES / mutant_id
        target.mkdir()
        mutated = source.replace(marker, f'MUTATION = "{mutant_id}"')
        (target / "solution.py").write_bytes(mutated.encode("utf-8"))
        records.append(
            {
                "mutant_id": mutant_id,
                "category": category,
                "description": description,
                "path": f"cases/{mutant_id}",
                "expected": "fail",
            }
        )
    manifest = {"schema_version": "local-noise-mutants/v1", "mutants": records}
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (CASES / "manifest.json").write_bytes(payload.encode("utf-8"))
    return manifest


def main() -> int:
    print(json.dumps(build(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
