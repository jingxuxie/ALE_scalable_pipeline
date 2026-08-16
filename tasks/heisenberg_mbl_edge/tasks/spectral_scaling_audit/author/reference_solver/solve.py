#!/usr/bin/env python3
"""Construct the clean-room reference submission."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--participant", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    participant = arguments.participant.resolve()
    if not (participant / "TASK.md").is_file() or not (participant / "input" / "manifest.json").is_file():
        raise ValueError("participant package is incomplete")
    destination = arguments.output.resolve() / "output"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("analyze.py"), destination / "analyze.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
