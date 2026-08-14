# Recover hidden canonical coordinates and nonlinear energy

## Goal

The four measured coordinates `x = [x0, x1, x2, x3]` are an unknown linear
mixture of two canonical position-momentum pairs. Recover a linear map from
observed to canonical coordinates and a scalar Hamiltonian that together
reproduce the observed dynamics.

Let `z = [q0, q1, p0, p1] = B x`, where the unknown invertible 4-by-4 matrix
`B` is `canonical_from_observed`. In canonical coordinates, use

```text
H(q,p) = 0.5 p^T D p + 0.5 q^T K q
         + a q0^4/4 + b q1^4/4 + c q0^2 q1^2/2.
```

`D` and `K` are symmetric positive-definite 2-by-2 matrices. The quartic
vector is `[a, b, c]`. Hamilton's equations are
`dz/dt = [dH/dp, -dH/dq]`; therefore the derivative predicted in observed
coordinates is `dx/dt = inverse(B) dz/dt`.

## Input

Read the variant's `observations.json`. In a compiled bundle it is stored at
`input/instances/<NNN>/observations.json`; the ALE runtime supplies the exact
path. The file contains:

- `360` training observed states and noisy observed derivatives;
- `100` validation states and derivatives covering a wider
  range;
- the coordinate order, Hamiltonian basis, unknown parameter types, and
  required output path.

Each state and derivative is a four-number row. The true canonical states,
the mixing matrix, and the Hamiltonian coefficients are not provided.

This is a joint system-identification problem. One possible strategy is to
optimize `B`, `D`, `K`, and `[a,b,c]` together against derivative error,
using the validation split to reject solutions that only fit the local
training region. Different parameter factorizations are acceptable when
they induce the same observed-space vector field. A neural network is not
required; any numerical optimization method may be used.

## Required output

Write `recovery.json` with exactly these keys and shapes:

```json
{
  "format": "latent-canonical-hamiltonian-v1",
  "canonical_from_observed": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
  "kinetic": [[1.0, 0.0], [0.0, 1.0]],
  "stiffness": [[1.0, 0.0], [0.0, 1.0]],
  "quartic": [0.0, 0.0, 0.0]
}
```

`canonical_from_observed` must be invertible with condition number at most
100. `kinetic` (`D`) and `stiffness` (`K`) must be symmetric positive
definite. Every coefficient must be finite and have absolute value at most
20. The JSON file must not exceed 1,000,000 bytes. Do not submit predictions,
code, or a serialized model.

Complete `software/recover.py` or use your own fitting program, then write
the bounded JSON artifact at the path stated in `artifact_contract`.

## Evaluation

The grader does not compare raw coefficients, because equivalent latent
factorizations can describe the same dynamics. Instead, it constructs your
induced observed-space vector field, measures field MSE on `176`
hidden higher-energy states, and integrates `9` hidden
trajectories with `141` time points. Field MSE must be at most
`0.008` and rollout MSE at most
`0.045`. The score weights are 45% hidden field,
45% rollout, and 10% artifact validity; a failed required check rejects the
submission.

## Common mistakes

- assuming the observed coordinates `x` are already canonical;
- returning `inverse(B)` when the contract asks for `B`;
- computing `dz/dt` but forgetting to transform it back to `dx/dt`;
- omitting the mixed-quartic gradient terms or using the wrong sign;
- minimizing only local derivative error while hidden rollouts diverge.
