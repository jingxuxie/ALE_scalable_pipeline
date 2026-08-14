# Recover an affine transformation from examples

## Goal

Infer one affine rule from worked numeric examples, then apply that same
rule to every unlabeled query. This is a small system-identification
problem, not a request to memorize rows. The hidden rule has the form

```text
y = W x + b
```

where each input `x` has `3` numbers and each output `y`
has `2` numbers. Recover the matrix `W` and intercept
`b` well enough to predict held-out inputs. A neural network is neither
required nor especially useful; least squares with an intercept is a
suitable starting point.

## Input

Read the variant's `input.json`. In a compiled bundle it is stored at
`input/instances/<NNN>/input.json`; the ALE runtime supplies the exact
variant path. The file contains:

- `public_examples`: `8` rows with `id`, `input`, and
  possibly noisy `output` values;
- `queries`: `154` rows with `id` and `input`, but no output;
- `output_contract`: the required destination and JSON shape;
- `context` values that are explicit decoys and must not affect the rule.

Use the example inputs and outputs to fit all coefficients jointly.
Preserve every query ID exactly and compute one prediction vector for
each query.

## Required output

Write `submission.json` with exactly one top-level key:

```json
{
  "predictions": [
    {"id": "q00000", "values": [0.0, 0.0]}
  ]
}
```

Each `values` array must contain exactly `2` finite
numbers. Include every query ID exactly once; do not include example
IDs, extra keys, comments, code, commands, or serialized objects. The
maximum file size is `131072` bytes.

## Evaluation

The private evaluator applies the exact affine rule to all public query
inputs and compares your values with those references. Required numeric
thresholds are `rmse` <= `0.06`, `maximum_error` <= `0.15`. Passing metrics must contribute at least
`90%` of the declared metric weight. The grader also
enforces strict JSON, the byte limit, exact vector shapes, finite
numbers, and complete unique query IDs.

## Common mistakes

- fitting a linear rule without an intercept column;
- using the unrelated `context` fields as predictors;
- predicting the examples instead of the query rows;
- rounding coefficients or predictions too early;
- omitting IDs, changing their spelling, or adding extra JSON fields.
