#!/usr/bin/env python3
"""Materialize schema-valid scientific mutant submissions.

Each generated submission is a byte-for-byte copy of the clean reference
analyzer except for its dormant ``MUTATION_MODE`` selector.  The static
``manifest.json`` is the source of truth for the mutation suite.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
TASK_ROOT = HERE.parent.parent
DEFAULT_SOURCE = TASK_ROOT / "author" / "reference_solver" / "analyze.py"
DEFAULT_CASES = HERE / "cases"
MODE_MARKER = 'MUTATION_MODE = "correct"'
NO_STABILITY_ANCHOR = 'if MUTATION_MODE == "no_stability":'
LARGEST_SIZE_ANCHOR = (
    'base = fit_scaling(rows, max(int(row["size"]) for row in rows) - 1, primary_halfwidth)'
)
LARGEST_SIZE_REWRITE = """largest_size = max(int(row[\"size\"]) for row in rows)
            largest_rows = [row for row in rows if int(row[\"size\"]) == largest_size]
            largest_controls = [float(row[\"control\"]) for row in largest_rows]
            single_size_hc = 0.5 * (min(largest_controls) + max(largest_controls))
            base = fixed_fit(rows, single_size_hc, 1.0, primary_min, primary_halfwidth)"""


def load_manifest() -> dict:
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "spectral-scaling-audit-mutants/v1":
        raise ValueError("unexpected mutant manifest schema")
    mutants = manifest.get("mutants")
    if not isinstance(mutants, list) or len(mutants) < 14:
        raise ValueError("at least fourteen scientific mutants are required")
    identifiers = [record.get("mutant_id") for record in mutants]
    modes = [record.get("mode") for record in mutants]
    if len(set(identifiers)) != len(identifiers) or len(set(modes)) != len(modes):
        raise ValueError("mutant identifiers and modes must be unique")
    if len({record.get("category") for record in mutants}) < 5:
        raise ValueError("mutant suite must span at least five categories")
    for record in mutants:
        required = {
            "mutant_id",
            "mode",
            "category",
            "description",
            "expected_result",
            "expected_fail_rationale",
            "expected_component",
            "schema_valid",
            "path",
        }
        if set(record) != required:
            missing = sorted(required - set(record))
            extra = sorted(set(record) - required)
            raise ValueError(
                f"invalid record keys for {record.get('mutant_id')!r}: "
                f"missing={missing}, extra={extra}"
            )
        mutant_id = record["mutant_id"]
        expected_path = f"cases/{mutant_id}/output/analyze.py"
        if record["path"] != expected_path:
            raise ValueError(f"unexpected path for {mutant_id}: {record['path']}")
        if record["expected_result"] != "reject" or record["schema_valid"] is not True:
            raise ValueError(f"mutant {mutant_id} must be a schema-valid expected rejection")
        for field in ("mutant_id", "mode", "category"):
            value = record[field]
            if not isinstance(value, str) or not value or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value
            ):
                raise ValueError(f"invalid {field} for mutant {mutant_id!r}")
        for field in ("description", "expected_fail_rationale", "expected_component"):
            if not isinstance(record[field], str) or not record[field].strip():
                raise ValueError(f"missing {field} for mutant {mutant_id!r}")
    return manifest


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(source_path: Path, cases_root: Path) -> Path:
    manifest = load_manifest()
    source_path = source_path.resolve()
    source = source_path.read_text(encoding="utf-8")
    if source.count(MODE_MARKER) != 1:
        raise ValueError("reference analyzer mutation marker is missing or ambiguous")

    cases_root = cases_root.resolve()
    cases_root.mkdir(parents=True, exist_ok=True)
    generated_records = []
    for record in manifest["mutants"]:
        mode = record["mode"]
        branch_anchor = f'MUTATION_MODE == "{mode}"'
        if branch_anchor not in source:
            raise ValueError(f"reference analyzer has no dormant branch for mode {mode!r}")
        mutated = source.replace(MODE_MARKER, f'MUTATION_MODE = "{mode}"', 1)
        # Removing L from the design coordinate makes a few deliberately narrow
        # stability windows rank deficient.  Reuse the already-valid primary
        # no-size fit in those cells so this remains a complete scientific
        # mutant instead of being misclassified as an execution-failure probe.
        if mode == "no_size_scaling":
            if mutated.count(NO_STABILITY_ANCHOR) != 1:
                raise ValueError("stability fallback anchor is missing or ambiguous")
            mutated = mutated.replace(
                NO_STABILITY_ANCHOR,
                'if MUTATION_MODE in ("no_stability", "no_size_scaling"):',
                1,
            )
        # The dormant largest-size branch deliberately violates the clean
        # three-size support gate and would otherwise terminate. Replace only
        # that branch's estimator by a complete single-size shortcut: take the
        # midpoint of the largest-size control sweep, fix nu=1, and use the
        # ordinary fixed-fit/output path for every remaining artifact.
        if mode == "largest_size_only":
            if mutated.count(LARGEST_SIZE_ANCHOR) != 1:
                raise ValueError("largest-size mutation anchor is missing or ambiguous")
            mutated = mutated.replace(LARGEST_SIZE_ANCHOR, LARGEST_SIZE_REWRITE, 1)
            if mutated.count(NO_STABILITY_ANCHOR) != 1:
                raise ValueError("largest-size stability fallback anchor is missing or ambiguous")
            mutated = mutated.replace(
                NO_STABILITY_ANCHOR,
                'if MUTATION_MODE in ("no_stability", "largest_size_only"):',
                1,
            )
        ast.parse(mutated, filename=f"{record['mutant_id']}/output/analyze.py")
        destination = cases_root / record["mutant_id"] / "output" / "analyze.py"
        destination.parent.mkdir(parents=True, exist_ok=True)
        encoded = mutated.encode("utf-8")
        destination.write_bytes(encoded)
        generated_records.append(
            {
                **record,
                # Keep the package-relative logical path stable even when the
                # verifier materializes cases under an arbitrary temp root.
                "path": record["path"],
                "sha256": sha256(encoded),
            }
        )

    generated = {
        "schema_version": "spectral-scaling-audit-generated-mutants/v1",
        "source": source_path.relative_to(TASK_ROOT).as_posix(),
        "source_sha256": sha256(source.encode("utf-8")),
        "mutant_count": len(generated_records),
        "category_count": len({record["category"] for record in generated_records}),
        "mutants": generated_records,
    }
    generated_path = cases_root / "mutant_manifest.json"
    generated_path.write_text(
        json.dumps(generated, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return generated_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="clean analyzer containing the dormant MUTATION_MODE branches",
    )
    parser.add_argument(
        "--cases-root",
        type=Path,
        default=DEFAULT_CASES,
        help="destination for cases/<mutant_id>/output/analyze.py",
    )
    arguments = parser.parse_args()
    generated_path = build(arguments.source, arguments.cases_root)
    print(generated_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
