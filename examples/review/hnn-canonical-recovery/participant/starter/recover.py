"""Starter for latent canonical-coordinate and Hamiltonian recovery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def recover(instance: dict) -> dict:
    # TODO: infer a canonicalizer and all quadratic/quartic coefficients.
    return {
        "format": "latent-canonical-hamiltonian-v1",
        "canonical_from_observed": [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)],
        "kinetic": [[1.0, 0.0], [0.0, 1.0]],
        "stiffness": [[1.0, 0.0], [0.0, 1.0]],
        "quartic": [0.0, 0.0, 0.0],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = recover(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
