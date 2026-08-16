#!/usr/bin/env python3
"""Run a trusted validation script with audited file/network/process access."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import numpy as np


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: isolated_runner.py ROOT SCRIPT [ARG ...]")
    root = Path(sys.argv[1]).resolve(strict=True)
    script = Path(sys.argv[2]).resolve(strict=True)
    if not is_within(script, root):
        raise SystemExit("script must be inside the isolated root")
    runtime_roots = {
        Path(sys.prefix).resolve(),
        Path(sys.base_prefix).resolve(),
        Path(np.__file__).resolve().parent,
    }
    allowed_roots = {root, *runtime_roots}

    def audit(event: str, arguments: tuple[object, ...]) -> None:
        if event == "open" and arguments:
            target = arguments[0]
            if isinstance(target, (str, bytes, os.PathLike)):
                candidate = Path(os.fsdecode(target))
                if not candidate.is_absolute():
                    candidate = Path.cwd() / candidate
                resolved = candidate.resolve(strict=False)
                if not any(is_within(resolved, allowed) for allowed in allowed_roots):
                    raise PermissionError(f"isolated runner denied file access: {resolved}")
        if event.startswith("socket."):
            raise PermissionError(f"isolated runner denied network event: {event}")
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn"}:
            raise PermissionError(f"isolated runner denied process event: {event}")

    sys.addaudithook(audit)
    sys.argv = [str(script), *sys.argv[3:]]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
