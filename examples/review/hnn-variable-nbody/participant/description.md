# Compute softened gravitational Hamiltonian dynamics

## Goal

For every unlabeled N-body query, compute both the scalar Hamiltonian and
the full canonical time derivative of every body. This is a numerical
physics task: all constants and states needed for the calculation are in
the input.

Each body has mass `m_i` and one state row
`[q_x, q_y, p_x, p_y]`. With the supplied gravitational constant `G` and
softening length `epsilon`, use

```text
H = sum_i ||p_i||^2 / (2 m_i)
    - G sum_{i<j} m_i m_j
        / sqrt(||q_i - q_j||^2 + epsilon^2).
```

Hamilton's equations define the required field row for body `i`:

```text
dq_i/dt = p_i / m_i
dp_i/dt = -G m_i sum_{j != i} m_j (q_i - q_j)
          / (||q_i - q_j||^2 + epsilon^2)^(3/2).
```

Each pair contributes once to the energy and equal-and-opposite momentum
derivatives to the two bodies.

## Input

Read the variant's `problems.json`. In a compiled bundle it is stored at
`input/instances/<NNN>/problems.json`; the ALE runtime supplies the exact
path. The file contains:

- `constants` supplies `gravitational_constant` and `softening`;
- `state_layout` defines the four values in each body row;
- `labeled_examples` contains 2 fully worked problems for checking signs,
  shapes, and conventions;
- `queries` contains `10` problems with between 3 and
  `6` bodies. A query has `query_id`, `masses`, and `state` but
  no answer.

Body counts vary by query. Some positions form softened close encounters,
and one query is a permutation of another. Always preserve the body order
used by that query.

## Required output

Write `results.json` in this form:

```json
{
  "format": "nbody-query-results-v1",
  "instance_id": "000",
  "results": [
    {
      "query_id": "query-00",
      "hamiltonian": 0.0,
      "field": [
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0]
      ]
    }
  ]
}
```

Return exactly one result for every public query ID. Each `field` must have
one four-number row per body in the same order as the input. Replace `000`
with the input's `instance_id`. All numbers must be finite. Do not add extra
keys or submit executable objects. The JSON file must not exceed 4,000,000
bytes.

Complete `software/solve_queries.py` or use your own implementation. A
direct double loop over unordered body pairs is sufficient and helps apply
equal-and-opposite forces consistently.

## Evaluation

The grader independently recomputes every answer from `problems.json` and
checks energies and all field components with absolute and relative
tolerance `1e-09`. It also checks query coverage, unique IDs,
array shapes and finite values. The query set deliberately includes variable
body counts, close encounters, and a permuted counterpart; each of those
results is recomputed and checked independently. The score weights are 25%
energy, 55% canonical field, and 20% composition and permutation behavior.
Every query must pass.

## Common mistakes

- treating momentum as velocity and forgetting division by mass;
- reversing the attractive-force sign;
- omitting `epsilon^2` or using the wrong power in the force denominator;
- double-counting pair potential energy or not applying opposite forces;
- assuming a fixed body count, reordering bodies, or rounding too early.
