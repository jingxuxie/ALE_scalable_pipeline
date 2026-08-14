# Identify a coupled nonlinear Hamiltonian

## Goal

Recover the coefficients of a three-degree-of-freedom Hamiltonian from
noisy observations of states and their time derivatives. You are fitting a
specified physical model, not predicting the supplied rows one by one.

A state has coordinate order
`[q0, q1, q2, p0, p1, p2]`, where `q` contains three periodic positions and
`p` contains their canonical momenta. The Hamiltonian is

```text
H(q,p) = 0.5 p^T A p
         + sum_i a_i (1 - cos(q_i))
         + sum_{i<j} c_ij (1 - cos(q_i - q_j)).
```

The unknowns are a symmetric positive-definite 3-by-3 inverse-mass matrix
`A`, three onsite coefficients `a`, and a symmetric 3-by-3 coupling matrix
`C` with a zero diagonal. Hamilton's equations give

```text
dq/dt   = A p
dp_i/dt = -a_i sin(q_i) - sum_{j != i} c_ij sin(q_i - q_j).
```

## Input

Read the variant's `data.json`. In a compiled bundle it is stored at
`input/instances/<NNN>/data.json`; the ALE runtime supplies the exact path.
It contains `240` training and `80` validation
samples. In each split:

- `states[k]` is one six-number state in the coordinate order above;
- `derivatives[k]` is the corresponding noisy
  `[dq0/dt, dq1/dt, dq2/dt, dp0/dt, dp1/dt, dp2/dt]` label;
- `model_basis` and `artifact_contract` restate the model and output path.

A useful approach is to fit `A` from the linear relation between `p` and
`dq/dt`, then fit `a` and the three pair couplings from the sine features in
`dp/dt`. Use both data splits to check that every coefficient, including
off-diagonal kinetic and pair-coupling terms, has been recovered.

## Required output

Write `model.json` with exactly this structure:

```json
{
  "format": "coupled-periodic-hamiltonian-v1",
  "dof": 3,
  "inverse_mass": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
  "onsite": [1.0, 1.0, 1.0],
  "couplings": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
}
```

`inverse_mass` must be symmetric positive definite. `couplings` must be
symmetric with a zero diagonal. Every number must be finite and have
absolute value at most 10. The JSON file must not exceed 1,000,000 bytes.
Do not submit trajectories, Python code, or a serialized model object.

Complete `software/fit_model.py` or use your own fitting program, then
create the JSON file at the output path stated in `artifact_contract`.

## Evaluation

The private grader reconstructs the vector field from your coefficients.
It measures mean-squared field error on `144` wider-angle hidden
states and trajectory error on `8` nonlinear rollouts with
`126` time points. Field MSE must be at most
`0.006` and rollout MSE at most
`0.035`. The score weights are 45% hidden field,
45% rollout, and 10% artifact validity; a failed required check rejects the
submission.

## Common mistakes

- fitting six unrelated derivative predictors instead of the stated basis;
- dropping the off-diagonal entries of `A` or all pair couplings;
- using the wrong sign for `dp/dt`;
- returning asymmetric matrices or a non-positive kinetic matrix;
- fitting only the local rows without checking nonlinear rollouts.
