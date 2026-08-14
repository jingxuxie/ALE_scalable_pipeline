"""Starter for safe coupled-periodic parameter identification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fit(instance: dict) -> dict:
    # TODO: use train and validation derivatives to estimate every basis coefficient.
    dof = int(instance["artifact_contract"]["dof"])
    return {
        "format": "coupled-periodic-hamiltonian-v1",
        "dof": dof,
        "inverse_mass": [[1.0 if i == j else 0.0 for j in range(dof)] for i in range(dof)],
        "onsite": [1.0] * dof,
        "couplings": [[0.0] * dof for _ in range(dof)],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = fit(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(model, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
