# Paper-Blind Specification Review

## Scope attestation

This verdict was derived only from the non-hidden public files under
`participant/`, with an isolated blind rereview after the final contract edits.
No paper, pre-existing author material, private files, official implementation,
hidden files, Git history, or external reference results were inspected or used
as evidence.

## Verdict

**PASS.** There are no blocking or nonblocking specification/package defects for
a capable solver using the Python standard library and public NumPy. The task is
self-contained, its scientific conventions and output schemas are implementable,
and no solution or expected-answer leak was found.

## Findings

- **Blockers:** None.
- **Nonblockers:** None.

## Passing checks

- The visible inventory contains `TASK.md` plus exactly the five files in the
  provided-files table (`participant/TASK.md:20-28`). No `__pycache__`, `.pyc`,
  result, reference, or other unintended non-hidden artifact is present.
- Basis order, neighbor enumeration, cutoff tolerance, directional hopping
  signs, `H0`/`H1` orientation, Bloch phase, device construction, left/right
  lead orientation, contact self-energies, observables, and the `C == 1` rule
  are explicit (`participant/TASK.md:95-244`).
- Filenames, exact NPZ keys, dtypes, shapes, axis order, raw-input hash, and
  diagnostic residuals are fully specified (`participant/TASK.md:246-338`).
- The public domain caps `N <= 32`, `C <= 10`, and `P,K <= 64`, bounds numeric
  scales and `eta`, and discloses input, source, console, artifact, memory, CPU,
  and time limits (`participant/TASK.md:77-93`, `364-380`). These bounds make
  the mandatory dense arrays and linear algebra feasible.
- `schema.json` matches the prose bounds and clearly delegates cross-field
  semantic rules to `TASK.md`. The optional helper matches the 64 MiB input
  limit when loading and hashing and accepts integral JSON numbers such as
  `4.0` consistently with the schema.
- Both shipped JSON fixtures parse, satisfy the current schema, and pass smoke
  checks for dimensions, unique IDs, species references, nonzero lattice
  vector, canonical hopping keys, and enumerated-neighbor coverage.
- The task discloses combined absolute/relative comparison against independent
  double-precision implementations (`participant/TASK.md:360-362`); evaluator
  thresholds do not alter any scientific or serialization convention.
- `software/solution.py` remains a TODO entry-point stub and `io_utils.py`
  contains generic parsing/serialization utilities only. No reference outputs,
  evaluator data, paper identity, or hidden scientific implementation appear in
  the participant-visible package.
