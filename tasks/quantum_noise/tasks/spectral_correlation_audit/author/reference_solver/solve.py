#!/usr/bin/env python3
"""Construct a submission using only the participant projection as data."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--participant", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    arguments = parser.parse_args()
    participant = arguments.participant.resolve()
    submission = arguments.submission.resolve()
    manifest = json.loads((participant / "input" / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "spectral-correlation-audit-input/v1":
        raise ValueError("unexpected public input schema")
    submission.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__).with_name("analyze.py"), submission / "analyze.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
