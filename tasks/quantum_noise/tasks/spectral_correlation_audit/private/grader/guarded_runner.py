#!/usr/bin/env python3
"""Run one analyzer with a restrictive Python audit hook.

This is a local verification guard, not a replacement for an ALE OS sandbox.
"""

from __future__ import annotations

import argparse
import collections
import csv
import itertools
import json
import math
import os
from pathlib import Path
import pkgutil
import runpy
import sys
import types
import typing

import numpy as np
import numpy.ctypeslib  # preload the allowlisted NumPy facade before the hook


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("analyzer", type=Path)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    arguments = parser.parse_args()
    analyzer = arguments.analyzer.resolve()
    input_dir = arguments.input_dir.resolve()
    output_dir = arguments.output_dir.resolve()

    # Warm lazy imports before installing the hook.
    np.linalg.norm(np.ones(2, dtype=np.float64))
    np.bincount(np.asarray([0, 1], dtype=np.int64))
    # Freeze every policy dependency before participant code executes. The
    # allowlisted pathlib module exposes its shared os module, so the hook must
    # not consult mutable module attributes after installation.
    frozen_getcwd = os.getcwd
    frozen_lstat = os.lstat
    frozen_readlink = os.readlink
    frozen_fullpath = getattr(os.path, "_getfullpathname", None)
    frozen_finalpath = getattr(os.path, "_getfinalpathname", None)
    filesystem_encoding = sys.getfilesystemencoding()
    windows_paths = os.name == "nt"
    frozen_type = type
    frozen_getattr = getattr
    frozen_len = len
    frozen_any = any
    str_type = str
    bytes_type = bytes
    int_type = int
    denied_error = PermissionError
    file_not_found_error = FileNotFoundError
    os_error = OSError
    path_errors = (TypeError, ValueError, OSError)
    write_flag_mask = int(os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
    reserved_windows_names = frozenset(
        {"CON", "PRN", "AUX", "NUL"}
        | {f"COM{index}" for index in range(1, 10)}
        | {f"LPT{index}" for index in range(1, 10)}
    )
    code_type = types.CodeType
    allowed_import_roots = frozenset(
        {"__future__", "argparse", "collections", "csv", "itertools", "json", "math", "numpy", "pathlib", "typing"}
    )

    def decoded_path(raw: object) -> str | None:
        if frozen_type(raw) not in {str_type, bytes_type}:
            return None
        if frozen_type(raw) is bytes_type:
            return raw.decode(filesystem_encoding, errors="surrogateescape")
        return raw

    def lexical_posix(raw: str, base: str) -> str:
        combined = raw if raw.startswith("/") else base.rstrip("/") + "/" + raw
        parts: list[str] = []
        for part in combined.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        return "/" + "/".join(parts)

    def resolve_posix(raw: str) -> str | None:
        path = lexical_posix(raw, frozen_getcwd())
        links = 0
        while True:
            components = [part for part in path.split("/") if part]
            current = "/"
            restarted = False
            for index, part in enumerate(components):
                candidate = current.rstrip("/") + "/" + part
                try:
                    info = frozen_lstat(candidate)
                except file_not_found_error:
                    suffix = "/".join(components[index + 1 :])
                    return candidate + (("/" + suffix) if suffix else "")
                except os_error:
                    return None
                if info.st_mode & 0o170000 == 0o120000:
                    links += 1
                    if links > 40:
                        return None
                    try:
                        target = frozen_readlink(candidate)
                    except os_error:
                        return None
                    suffix = "/".join(components[index + 1 :])
                    if target.startswith("/"):
                        replacement = target
                    else:
                        replacement = current.rstrip("/") + "/" + target
                    if suffix:
                        replacement += "/" + suffix
                    path = lexical_posix(replacement, "/")
                    restarted = True
                    break
                current = candidate
            if not restarted:
                return current

    def resolve_windows(raw: str) -> str | None:
        if frozen_fullpath is None:
            return None
        try:
            full = frozen_fullpath(raw).replace("/", "\\")
        except path_errors:
            return None
        if frozen_finalpath is None:
            return full
        candidate = full
        tail: list[str] = []
        while True:
            try:
                resolved = frozen_finalpath(candidate).replace("/", "\\")
                break
            except os_error:
                stripped = candidate.rstrip("\\")
                split_at = stripped.rfind("\\")
                if split_at < 0:
                    return None
                name = stripped[split_at + 1 :]
                parent = stripped[:split_at]
                if parent.endswith(":"):
                    parent += "\\"
                if not name or parent == candidate:
                    return None
                tail.append(name)
                candidate = parent
        for name in reversed(tail):
            resolved = resolved.rstrip("\\") + "\\" + name
        return resolved

    def normalized_path(raw: object) -> str | None:
        text = decoded_path(raw)
        if text is None:
            return None
        return resolve_windows(text) if windows_paths else resolve_posix(text)

    def under(path: str, root: str) -> bool:
        separator = "\\" if windows_paths else "/"
        path_key = path.lower() if windows_paths else path
        root_key = root.lower() if windows_paths else root
        root_key = root_key.rstrip(separator)
        return path_key == root_key or path_key.startswith(root_key + separator)

    def safe_write_path(path: str, root: str) -> bool:
        if not under(path, root):
            return False
        if not windows_paths:
            return True
        relative = path[frozen_len(root.rstrip("\\")) :].lstrip("\\")
        for component in (part for part in relative.split("\\") if part):
            if ":" in component or component.endswith((" ", ".")):
                return False
            stem = component.split(".", 1)[0].rstrip(" .").upper()
            if stem in reserved_windows_names:
                return False
        return True

    def raw_is_absolute(raw: object) -> bool:
        text = decoded_path(raw)
        if text is None:
            return False
        if not windows_paths:
            return text.startswith("/")
        text = text.replace("/", "\\")
        return text.startswith("\\") or (frozen_len(text) >= 3 and text[1:3] == ":\\")

    read_roots = (
        normalized_path(str_type(input_dir)),
        normalized_path(str_type(analyzer.parent)),
        normalized_path(str_type(sys.base_prefix)),
    )
    write_roots = (normalized_path(str_type(output_dir)),)
    if frozen_any(root is None for root in read_roots + write_roots):
        raise RuntimeError("failed to initialize audit roots")
    analyzer_path = normalized_path(str_type(analyzer))
    analyzer_compile_remaining = 1
    analyzer_exec_remaining = 1

    def require_allowed_path(
        raw: object,
        roots: tuple[str | None, ...],
        event: str,
        writing: bool = False,
    ) -> None:
        path = normalized_path(raw)
        allowed = frozen_any(
            root is not None and (safe_write_path(path, root) if writing else under(path, root))
            for root in roots
        ) if path is not None else False
        if not allowed:
            raise denied_error(f"audit denied filesystem access: {event}")

    def nondefault_dir_fd(args: tuple[object, ...], index: int) -> bool:
        return frozen_len(args) > index and args[index] not in {None, -1}

    single_path_mutations = {
        "os.remove": 1,
        "os.unlink": 1,
        "os.rmdir": 1,
        "os.mkdir": 2,
        "os.truncate": None,
    }
    denied_exact = {
        "os.system",
        "os.startfile",
        "os.startfile/2",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.spawn",
        "os.kill",
        "os.killpg",
        "os.fchdir",
        "os.fchmod",
        "os.fchown",
        "os.ftruncate",
        "os.chmod",
        "os.chown",
        "os.lchown",
        "os.utime",
        "os.mknod",
        "os.mkfifo",
        "os.setxattr",
        "os.removexattr",
        "os.putenv",
        "os.unsetenv",
        "os.add_dll_directory",
        "os.symlink",
        "os.link",
        "sys._getframe",
        "sys.settrace",
        "sys.setprofile",
        "sys.addaudithook",
        "sys._current_frames",
        "sys._current_exceptions",
        "gc.get_objects",
        "gc.get_referrers",
        "gc.get_referents",
        "code.__new__",
        "function.__new__",
        "pickle.find_class",
    }

    def audit(event: str, args: tuple[object, ...]) -> None:
        nonlocal analyzer_compile_remaining, analyzer_exec_remaining
        if event == "compile":
            filename = args[1] if frozen_len(args) > 1 else None
            if (
                analyzer_compile_remaining == 1
                and frozen_type(filename) in {str_type, bytes_type}
                and normalized_path(filename) == analyzer_path
            ):
                analyzer_compile_remaining = 0
                return
            raise denied_error("audit denied capability: compile")
        if event == "exec":
            code = args[0] if args else None
            filename = frozen_getattr(code, "co_filename", None) if frozen_type(code) is code_type else None
            if (
                analyzer_exec_remaining == 1
                and frozen_type(filename) is str_type
                and normalized_path(filename) == analyzer_path
            ):
                analyzer_exec_remaining = 0
                return
            raise denied_error("audit denied capability: exec")
        if event == "import" and args:
            module_name = args[0]
            top_level = module_name.split(".", 1)[0] if frozen_type(module_name) is str_type else ""
            if top_level not in allowed_import_roots:
                raise denied_error(f"audit denied import: {top_level}")
        if (
            event.startswith("socket.")
            or event.startswith("subprocess.")
            or event.startswith("ctypes.")
            or event.startswith("winreg.")
            or event.startswith("_winapi.")
            or event.startswith("_posixsubprocess.")
            or event.startswith("fcntl.")
            or event.startswith("msvcrt.")
            or event.startswith("_thread.")
            or event.startswith("sys.monitoring.")
            or event.startswith("cpython.run_")
            or event.startswith("os.exec")
            or event in denied_exact
        ):
            raise denied_error(f"audit denied capability: {event}")
        if event == "open" and args:
            raw_path = args[0]
            if frozen_type(raw_path) is int_type:
                raise denied_error("audit denied integer file descriptor access")
            mode = args[1] if frozen_len(args) > 1 else "r"
            flags = args[2] if frozen_len(args) > 2 else 0
            writing = frozen_type(mode) is str_type and frozen_any(marker in mode for marker in "wax+")
            writing = writing or (frozen_type(flags) is int_type and (flags & write_flag_mask) != 0)
            if mode is None and not raw_is_absolute(raw_path):
                raise denied_error("audit denied relative os.open access")
            roots = write_roots if writing else read_roots + write_roots
            require_allowed_path(raw_path, roots, event, writing=writing)
        elif event in {"os.listdir", "os.scandir"}:
            if not args:
                raise denied_error(f"audit denied directory access: {event}")
            require_allowed_path(args[0], read_roots + write_roots, event)
        elif event in single_path_mutations:
            if not args:
                raise denied_error(f"audit denied filesystem mutation: {event}")
            dir_fd_index = single_path_mutations[event]
            if dir_fd_index is not None and nondefault_dir_fd(args, dir_fd_index):
                raise denied_error(f"audit denied dir_fd mutation: {event}")
            require_allowed_path(args[0], write_roots, event, writing=True)
        elif event in {"os.rename", "os.replace"}:
            if frozen_len(args) < 2 or nondefault_dir_fd(args, 2) or nondefault_dir_fd(args, 3):
                raise denied_error(f"audit denied dir_fd mutation: {event}")
            require_allowed_path(args[0], write_roots, event, writing=True)
            require_allowed_path(args[1], write_roots, event, writing=True)
        elif event == "os.chdir":
            raise denied_error("audit denied directory change")

    sys.addaudithook(audit)
    sys.argv = [str(analyzer), "--input", str(input_dir), "--output", str(output_dir)]
    runpy.run_path(str(analyzer), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
