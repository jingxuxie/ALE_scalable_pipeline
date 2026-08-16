#!/usr/bin/env python3
"""Private evaluator command-line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core import grade_submission


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", type=Path)
    arguments = parser.parse_args()
    result = grade_submission(arguments.submission.absolute())
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
