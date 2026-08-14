# HNN variable-N gravity review example

This is instance `000` of `hnn-hard-variable-nbody`.

## Start here

Read the full [participant task description](participant/description.md). It
defines the softened gravitational Hamiltonian, derives the energy and field
formulas, explains the body and JSON layouts, and lists the grading checks.

## Participant materials

The public [problems](participant/problems.json) provide the gravitational and
softening constants, two worked examples, and 10 unlabeled queries containing
3 to 6 bodies. Queries include close encounters and a permuted version of
another system. Each body row is `[q_x, q_y, p_x, p_y]`.

The participant must return one scalar energy and one four-component canonical
field row per body for every query. `participant/starter/solve_queries.py`
provides the exact output structure.

## Public reviewer reference

The evaluator does not need a stored answer table: its grader independently
recomputes every answer from the public problems. The public `reviewer_only/`
directory exposes the evaluator layout that would normally be private, its
`1e-9` absolute and relative tolerance policy, a correct output, and an
incorrect output that reverses every gravitational force.

The public input is duplicated under `reviewer_only/input/` because the exact
generated grader reads it from the evaluator bundle. The two copies have the
same SHA-256 digest.

Run the positive and negative checks from the repository root:

```powershell
python examples/review/run_checks.py
```

This public fixture is for review only. Give a simulated participant only the
`participant/` directory. A real evaluation requires an unpublished seed and
private evaluator artifacts, not another predictable instance from this build.
