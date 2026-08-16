#!/usr/bin/env python3
"""Public structural validator; it contains no scientific references."""

from __future__ import annotations

import argparse
import ast
import os
import stat
from pathlib import Path


MAX_BYTES = 200_000


def validate(directory: Path) -> None:
    directory = Path(os.path.abspath(directory))
    info = directory.lstat()
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISDIR(info.st_mode):
        raise ValueError("submission must be a real directory")
    entries = list(directory.iterdir())
    if [entry.name for entry in entries] != ["solution.py"]:
        raise ValueError("submission must contain exactly solution.py")
    solution = entries[0]
    file_info = solution.lstat()
    reparse = bool(getattr(file_info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(file_info.st_mode) or reparse or not stat.S_ISREG(file_info.st_mode):
        raise ValueError("solution.py must be a regular file")
    if file_info.st_nlink > 1:
        raise ValueError("hard-linked solution.py is not accepted")
    if not 1 <= file_info.st_size <= MAX_BYTES:
        raise ValueError("solution.py violates the size limit")
    source = solution.read_text(encoding="utf-8")
    ast.parse(source, filename="solution.py")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", type=Path)
    args = parser.parse_args()
    try:
        validate(args.submission)
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        print(f"INVALID: {exc}")
        return 1
    print("VALID STRUCTURE: scientific correctness is not checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
