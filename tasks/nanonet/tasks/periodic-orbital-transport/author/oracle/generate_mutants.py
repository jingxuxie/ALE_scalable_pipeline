#!/usr/bin/env python3
"""Generate deterministic standalone mutants from the clean-room solver."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


TASK_ROOT = Path(__file__).resolve().parents[2]
CLEAN_SOLVER = TASK_ROOT / "author" / "reference_solver" / "solve.py"
MUTANT_ROOT = TASK_ROOT / "private" / "mutants"


@dataclass(frozen=True)
class Mutation:
    description: str
    old: str
    new: str
    replacements: int = 1


MUTATIONS = {
    "mutant_advanced_branch.py": Mutation(
        "select the advanced rather than retarded surface branch",
        '        z = complex(energy, instance["eta"])',
        '        z = complex(energy, -instance["eta"])',
    ),
    "mutant_caroli_no_dagger.py": Mutation(
        "transpose G_1N without complex conjugation in Caroli transmission",
        "@ green_first_last.conj().T",
        "@ green_first_last.T",
    ),
    "mutant_dos_factor.py": Mutation(
        "apply an erroneous factor-of-two spin degeneracy to DOS",
        "/ math.pi",
        "* 2.0 / math.pi",
        replacements=2,
    ),
    "mutant_eta_real_shift.py": Mutation(
        "incorrectly add eta to the real energy as well",
        '        z = complex(energy, instance["eta"])',
        '        z = complex(energy + instance["eta"], instance["eta"])',
    ),
    "mutant_nan.py": Mutation(
        "inject one NaN into an otherwise complete submission",
        "        result = solve_instance(instance)\n"
        "        write_outputs(arguments.output, result)",
        "        result = solve_instance(instance)\n"
        '        result["spectra"]["transmission"][0] = np.nan\n'
        "        write_outputs(arguments.output, result)",
    ),
    "mutant_omit_periodic.py": Mutation(
        "omit every forward inter-cell hopping contribution",
        "            if block is not None:\n"
        "                h1[site_slices[row_index], site_slices[column_index]] += block",
        "            if block is not None:\n"
        "                pass",
    ),
    "mutant_partial.py": Mutation(
        "emit only the otherwise-correct Hamiltonian artifact",
        "        result = solve_instance(instance)\n"
        "        write_outputs(arguments.output, result)",
        "        result = solve_instance(instance)\n"
        "        output_path = Path(arguments.output)\n"
        "        output_path.mkdir(parents=True, exist_ok=True)\n"
        '        np.savez(output_path / "hamiltonian.npz", **result["hamiltonian"])',
    ),
    "mutant_stale_public.py": Mutation(
        "reuse pristine-device settings for every input",
        "        instance = load_instance(arguments.input)\n"
        "        result = solve_instance(instance)",
        "        instance = load_instance(arguments.input)\n"
        '        instance["device"]["site_potential"].fill(0.0)\n'
        '        instance["device"]["bond_scale"].fill(1.0)\n'
        '        instance["device"]["contact_scale_left"] = 1.0\n'
        '        instance["device"]["contact_scale_right"] = 1.0\n'
        "        result = solve_instance(instance)",
    ),
    "mutant_wrong_sp_sign.py": Mutation(
        "use the wrong sign for p(row)-to-s(column) hopping",
        '            elif column_orbital == "s":\n'
        '                value = -direction[P_AXIS[row_orbital]] * parameters["sp_sigma"]',
        '            elif column_orbital == "s":\n'
        '                value = direction[P_AXIS[row_orbital]] * parameters["sp_sigma"]',
    ),
}


def _render(clean_source: str, mutation: Mutation) -> str:
    actual = clean_source.count(mutation.old)
    if actual != mutation.replacements:
        raise RuntimeError(
            f"mutation source mismatch for {mutation.description!r}: "
            f"expected {mutation.replacements}, found {actual}"
        )
    mutated = clean_source.replace(mutation.old, mutation.new)
    lines = mutated.splitlines(keepends=True)
    marker = (
        f"# MUTANT: {mutation.description}.\n"
        "# Generated deterministically; do not repair this author-only negative control.\n"
    )
    if lines and lines[0].startswith("#!"):
        return lines[0] + marker + "".join(lines[1:])
    return marker + mutated


def generate(*, check: bool) -> None:
    clean_source = CLEAN_SOLVER.read_text(encoding="utf-8")
    MUTANT_ROOT.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for name, mutation in sorted(MUTATIONS.items()):
        destination = MUTANT_ROOT / name
        expected = _render(clean_source, mutation)
        if check:
            try:
                observed = destination.read_text(encoding="utf-8")
            except OSError as exc:
                failures.append(f"{name}: cannot read: {exc}")
                continue
            if observed != expected:
                failures.append(f"{name}: stale or modified")
        else:
            destination.write_text(expected, encoding="utf-8", newline="\n")
    if failures:
        raise SystemExit("mutant verification failed:\n" + "\n".join(failures))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify without writing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    generate(check=options.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
