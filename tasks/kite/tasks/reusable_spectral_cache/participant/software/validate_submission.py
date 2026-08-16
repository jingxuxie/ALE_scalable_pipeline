#!/usr/bin/env python3
"""Public structural validator; it contains no scientific reference values."""

from __future__ import annotations

import argparse
import csv
import json
import math
import stat
import zipfile
from pathlib import Path

import numpy as np


NAMES = {"moments.npz", "public_response.csv", "diagnostics.json"}
KEYS = {
    "schema_version",
    "system_ids",
    "dimensions",
    "moment_count",
    "probe_count",
    "tau_real",
    "tau_imag",
}
HEADER = [
    "query_id",
    "system_id",
    "prefix",
    "kind",
    "energy",
    "eta",
    "value_real",
    "value_imag",
]


def finite(value: str) -> bool:
    try:
        return math.isfinite(float(value))
    except ValueError:
        return False


def validate(participant: Path, submission: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads((participant / "input" / "manifest.json").read_text(encoding="utf-8"))
    if not submission.is_dir() or submission.is_symlink():
        return ["submission must be a real directory"]
    if {entry.name for entry in submission.iterdir()} != NAMES:
        errors.append("output directory must contain exactly the three required files")
        return errors
    for name in NAMES:
        info = (submission / name).lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            errors.append(f"{name} is not a regular file")
    try:
        if not zipfile.is_zipfile(submission / "moments.npz"):
            raise ValueError("not an NPZ archive")
        with np.load(submission / "moments.npz", allow_pickle=False) as archive:
            if set(archive.files) != KEYS:
                errors.append("moments.npz key set is wrong")
            else:
                expected = (len(manifest["systems"]), manifest["probe_count"], manifest["moment_count"])
                for key in ("tau_real", "tau_imag"):
                    array = archive[key]
                    if array.shape != expected or array.dtype != np.dtype("float64"):
                        errors.append(f"{key} must have shape {expected} and dtype float64")
                    elif not np.all(np.isfinite(array)):
                        errors.append(f"{key} contains a non-finite value")
    except Exception as exc:
        errors.append(f"moments.npz cannot be loaded safely: {exc}")

    with (participant / "input" / manifest["public_queries_file"]).open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        expected_queries = list(csv.DictReader(handle))
    try:
        with (submission / "public_response.csv").open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        if reader.fieldnames != HEADER or len(rows) != len(expected_queries):
            errors.append("public_response.csv header or row count is wrong")
        else:
            for row, expected in zip(rows, expected_queries):
                if any(row[key] != expected[key] for key in HEADER[:4]):
                    errors.append("public response identity metadata differs from input")
                    break
                if any(not finite(row[key]) for key in HEADER[4:]):
                    errors.append("public response contains a non-finite numeric value")
                    break
    except Exception as exc:
        errors.append(f"public_response.csv cannot be parsed: {exc}")

    try:
        diagnostics = json.loads(
            (submission / "diagnostics.json").read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
        top = {"schema_version", "moment_count", "probe_count", "public_query_count", "systems"}
        item_keys = {
            "system_id",
            "dimension",
            "tau0_max_abs_error",
            "max_abs_imaginary_moment",
            "max_abs_moment",
            "scaled_gershgorin_radius",
        }
        if set(diagnostics) != top or diagnostics.get("schema_version") != "spectral-diagnostics/v1":
            errors.append("diagnostics.json top-level schema is wrong")
        elif len(diagnostics.get("systems", [])) != len(manifest["systems"]):
            errors.append("diagnostics systems length is wrong")
        elif any(set(item) != item_keys for item in diagnostics["systems"]):
            errors.append("diagnostics system record schema is wrong")
    except Exception as exc:
        errors.append(f"diagnostics.json cannot be parsed: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--participant", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    args = parser.parse_args()
    errors = validate(args.participant.absolute(), args.submission.absolute())
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
