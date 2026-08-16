"""Starter entry point for the periodic orbital transport task."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Hamiltonian, self-energy, spectra, and diagnostic artifacts."
    )
    parser.add_argument("--input", required=True, help="Path to one input JSON instance.")
    parser.add_argument("--output", required=True, help="Directory for generated artifacts.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    raise SystemExit(
        "TODO: implement the workflow in this file, place the completed entry point "
        "at output/solution.py, and write the required artifacts to --output."
    )


if __name__ == "__main__":
    raise SystemExit(main())
