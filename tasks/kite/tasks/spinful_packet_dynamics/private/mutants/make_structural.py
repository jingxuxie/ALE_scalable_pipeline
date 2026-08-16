#!/usr/bin/env python3
"""Build structural/adversarial submissions from a known-correct artifact set."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import numpy as np


KINDS = {
    "malformed",
    "malformed_json",
    "partial",
    "nan",
    "huge_finite",
    "oversized",
    "stale",
    "fabricated",
    "wrong_conclusions",
    "wrong_numeric_type",
    "wrong_category_type",
    "hardcoded_public",
    "unexpected_executable",
}
ARTIFACTS = ["basis.npz", "trajectories.csv", "ensemble.csv", "analysis.json"]


def copy_reference(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in ARTIFACTS:
        shutil.copy2(source / name, destination / name)


def rewrite_basis(path: Path, mutate) -> None:
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: np.array(archive[name], copy=True) for name in archive.files}
    mutate(arrays)
    np.savez_compressed(path, **arrays)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=sorted(KINDS))
    parser.add_argument("reference", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    copy_reference(args.reference.resolve(), args.destination.resolve())
    destination = args.destination.resolve()

    if args.kind == "malformed":
        (destination / "basis.npz").write_bytes(b"this is not an NPZ archive\n")
    elif args.kind == "malformed_json":
        (destination / "analysis.json").write_text(
            "[" * 5000 + "]" * 5000, encoding="utf-8"
        )
    elif args.kind == "partial":
        (destination / "ensemble.csv").unlink()
    elif args.kind == "nan":
        path = destination / "trajectories.csv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = list(reader.fieldnames or [])
            rows = list(reader)
        rows[0]["norm"] = "NaN"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    elif args.kind == "huge_finite":
        path = destination / "trajectories.csv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = list(reader.fieldnames or [])
            rows = list(reader)
        rows[0]["norm"] = "1e308"
        rows[0]["mean_x"] = "1e308"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    elif args.kind == "oversized":
        (destination / "basis.npz").write_bytes(b"0" * (20 * 1024 * 1024 + 1))
    elif args.kind == "stale":
        def stale(arrays: dict[str, np.ndarray]) -> None:
            arrays["instance_id"] = np.asarray("spd-stale-cached-instance", dtype=np.str_)

        rewrite_basis(destination / "basis.npz", stale)
        analysis = json.loads((destination / "analysis.json").read_text(encoding="utf-8"))
        analysis["instance_id"] = "spd-stale-cached-instance"
        (destination / "analysis.json").write_text(
            json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    elif args.kind == "fabricated":
        analysis = json.loads((destination / "analysis.json").read_text(encoding="utf-8"))
        for record in analysis["contrasts"]:
            record["delta_sz"] = 0.75
            record["delta_spread"] = -4.0
        analysis["conclusion"]["smaller_final_abs_sz_model"] = "scalar_ising"
        analysis["conclusion"]["greater_spreading_model"] = "scalar"
        (destination / "analysis.json").write_text(
            json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    elif args.kind == "wrong_conclusions":
        analysis = json.loads((destination / "analysis.json").read_text(encoding="utf-8"))
        current_spin = analysis["conclusion"]["smaller_final_abs_sz_model"]
        current_spread = analysis["conclusion"]["greater_spreading_model"]
        analysis["conclusion"]["smaller_final_abs_sz_model"] = (
            "scalar_ising" if current_spin != "scalar_ising" else "scalar"
        )
        analysis["conclusion"]["greater_spreading_model"] = (
            "scalar" if current_spread != "scalar" else "scalar_ising"
        )
        (destination / "analysis.json").write_text(
            json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    elif args.kind == "wrong_numeric_type":
        analysis = json.loads((destination / "analysis.json").read_text(encoding="utf-8"))
        analysis["bounds"][0]["eigenvalue_min"] = "not-a-number"
        (destination / "analysis.json").write_text(
            json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    elif args.kind == "wrong_category_type":
        analysis = json.loads((destination / "analysis.json").read_text(encoding="utf-8"))
        analysis["conclusion"]["smaller_final_abs_sz_model"] = []
        (destination / "analysis.json").write_text(
            json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    elif args.kind == "hardcoded_public":
        def public_only(arrays: dict[str, np.ndarray]) -> None:
            arrays["basis"][:, 1:, :, :] = 0.0

        rewrite_basis(destination / "basis.npz", public_only)
    elif args.kind == "unexpected_executable":
        (destination / "run_me.py").write_text(
            "raise RuntimeError('submission code must never be executed')\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
