"""Trusted task-family registry.

Task families are executable compiler plugins: they own deterministic instance
generation and trusted evaluator construction.  Keeping registration here
lets the CLI/extraction layer discover capabilities without hard-coding them
in the compiler pipeline.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..packaging import BuildFile
from .hnn import build_task_files as build_hnn_task_files
from .hnn_hard import build_task_files as build_hnn_hard_task_files


TaskBuilder = Callable[..., Sequence[BuildFile]]


@dataclass(frozen=True, slots=True)
class TaskFamily:
    """One trusted, deterministic task-family compiler plugin."""

    name: str
    builder: TaskBuilder
    supported_difficulty_levels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("task family name must be nonempty")
        if not callable(self.builder):
            raise TypeError("task family builder must be callable")
        if len(set(self.supported_difficulty_levels)) != len(
            self.supported_difficulty_levels
        ):
            raise ValueError("supported difficulty levels must be unique")


_FAMILY_SPECS: dict[str, TaskFamily] = {}
# Backwards-compatible public builder map.  Register through
# ``register_task_family`` so specs and builders cannot drift.
TASK_FAMILIES: dict[str, TaskBuilder] = {}


def register_task_family(
    name: str,
    builder: TaskBuilder,
    *,
    supported_difficulty_levels: Sequence[str] = (),
    replace: bool = False,
) -> TaskFamily:
    """Register trusted family code explicitly.

    Registration is intentionally process-local.  Importing a paper or model
    response never loads executable plugins; an operator must install/import
    trusted family code first.
    """

    normalized = name.strip() if isinstance(name, str) else ""
    if not normalized:
        raise ValueError("task family name must be a nonempty string")
    if normalized in _FAMILY_SPECS and not replace:
        raise ValueError(f"task family {normalized!r} is already registered")
    levels = tuple(str(level).strip() for level in supported_difficulty_levels)
    if any(not level for level in levels):
        raise ValueError("supported difficulty levels must be nonempty strings")
    spec = TaskFamily(normalized, builder, levels)
    _FAMILY_SPECS[normalized] = spec
    TASK_FAMILIES[normalized] = builder
    return spec


def task_family(name: str) -> TaskFamily:
    """Return a registered family or fail with an actionable error."""

    try:
        return _FAMILY_SPECS[name]
    except KeyError as error:
        available = ", ".join(sorted(_FAMILY_SPECS)) or "none"
        raise ValueError(
            f"unsupported task family {name!r}; registered families: {available}. "
            "Install or register a trusted deterministic family before compiling."
        ) from error


def registered_task_families() -> Mapping[str, TaskFamily]:
    """Return a defensive snapshot of available trusted family plugins."""

    return dict(sorted(_FAMILY_SPECS.items()))


register_task_family("hnn", build_hnn_task_files)
register_task_family(
    "hnn_hard",
    build_hnn_hard_task_files,
    supported_difficulty_levels=("medium", "hard", "frontier"),
)


__all__ = [
    "TASK_FAMILIES",
    "TaskBuilder",
    "TaskFamily",
    "build_hnn_task_files",
    "build_hnn_hard_task_files",
    "register_task_family",
    "registered_task_families",
    "task_family",
]
