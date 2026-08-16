#!/usr/bin/env python3
"""Defense-in-depth audit wrapper for one staged participant execution.

The parent process supplies only a copied solution, a copied public experiment,
an initially empty output directory, and this wrapper. This hook narrows normal
Python I/O and blocks common process/network/link escapes. Production scoring
must still place the staged tree in an OS sandbox: Python audit hooks are not a
complete security boundary against deliberately hostile Python code.
"""

from __future__ import annotations

import os
import runpy
import sys

import numpy  # Load the sole third-party dependency before installing the hook.


def install_guard(stage_root: str, output_file: str) -> None:
    normcase = os.path.normcase
    realpath = os.path.realpath
    abspath = os.path.abspath
    commonpath = os.path.commonpath
    dirname = os.path.dirname
    fsdecode = os.fsdecode
    is_instance = isinstance
    any_value = any
    bool_value = bool
    length_of = len
    integer_type = int
    string_type = str
    bytes_type = bytes
    pathlike_type = os.PathLike
    permission_error = PermissionError
    os_error = OSError
    value_error = ValueError

    stage = normcase(realpath(abspath(stage_root)))
    output = normcase(realpath(abspath(output_file)))
    runtime_roots = tuple(
        dict.fromkeys(
            normcase(realpath(abspath(path)))
            for path in (sys.base_prefix, sys.prefix, sys.exec_prefix)
            if path
        )
    )
    readable_roots = (stage, *runtime_roots)
    write_bits = int(
        os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    )
    denied_exact = frozenset(
        {
            "socket.__new__",
            "socket.bind",
            "socket.connect",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "subprocess.Popen",
            "os.system",
            "os.link",
            "os.symlink",
            "os.rename",
            "os.remove",
            "os.rmdir",
            "os.truncate",
            "os.chmod",
            "os.chown",
            "os.utime",
            "os.chdir",
            "os.fchdir",
            "os.chroot",
            "ctypes.dlopen",
            "ctypes.dlsym",
            "ctypes.call_function",
            "sys._getframe",
            "sys.settrace",
            "sys.setprofile",
        }
    )
    denied_prefixes = (
        "os.exec",
        "os.spawn",
        "os.posix_spawn",
        "os.fork",
        "os.startfile",
    )

    def inside(path: str, root: str) -> bool:
        try:
            return commonpath((path, root)) == root
        except (os_error, value_error):
            return False

    def normalize(raw: object) -> str | None:
        if is_instance(raw, integer_type):
            return None
        if not is_instance(raw, (string_type, bytes_type, pathlike_type)):
            return None
        return normcase(realpath(abspath(fsdecode(raw))))

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event in denied_exact or event.startswith(denied_prefixes):
            raise permission_error("evaluation guard denied " + event)
        if event == "open" and args:
            path = normalize(args[0])
            if path is None:
                return
            mode = args[1] if length_of(args) > 1 else "r"
            flags = args[2] if length_of(args) > 2 else 0
            writing = bool_value(
                (is_instance(mode, string_type) and any_value(token in mode for token in "wax+"))
                or (is_instance(flags, integer_type) and flags & write_bits)
            )
            if writing:
                if path != output:
                    raise permission_error("evaluation guard denied write outside result file")
            elif not any_value(inside(path, root) for root in readable_roots):
                raise permission_error("evaluation guard denied read outside staged/runtime roots")
        elif event in {"os.listdir", "os.scandir"} and args:
            path = normalize(args[0])
            if path is not None and not any_value(inside(path, root) for root in readable_roots):
                raise permission_error("evaluation guard denied directory access outside staged/runtime roots")
        elif event == "os.mkdir" and args:
            path = normalize(args[0])
            if path != normcase(realpath(dirname(output))):
                raise permission_error("evaluation guard denied directory creation")

    # The registered hook retains immutable closure state. It is not backed by
    # a mutable module-global denylist that untrusted frames can simply clear.
    sys.addaudithook(audit)


def main(arguments: tuple[str, ...]) -> int:
    if len(arguments) != 5:
        raise SystemExit("usage: guard.py SOLUTION EXPERIMENT OUTPUT STAGE_ROOT")
    solution = os.path.realpath(os.path.abspath(arguments[1]))
    experiment = os.path.realpath(os.path.abspath(arguments[2]))
    output = os.path.realpath(os.path.abspath(arguments[3]))
    stage = os.path.realpath(os.path.abspath(arguments[4]))
    install_guard(stage, output)
    sys.argv = [solution, "--experiment", experiment, "--output", output]
    runpy.run_path(solution, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(tuple(sys.argv)))
