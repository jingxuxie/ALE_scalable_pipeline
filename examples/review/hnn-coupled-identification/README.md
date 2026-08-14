# HNN coupled-identification review example

This is instance `000` of `hnn-hard-coupled-identification`.

## Start here

Read the full [participant task description](participant/description.md). It
defines the Hamiltonian, derives the canonical vector field, explains every
input and output field, gives a practical fitting strategy, and states the
hidden evaluation criteria.

## Participant materials

The public [data](participant/data.json) contain 240 noisy training and 80
validation state/derivative pairs for a three-degree-of-freedom periodic
system. The participant must recover:

- a symmetric positive-definite 3-by-3 inverse-mass matrix;
- three onsite potential coefficients;
- three pair-coupling coefficients in a symmetric zero-diagonal matrix.

`participant/starter/fit_model.py` provides the required JSON structure but
does not solve the regression problem. The task card records the runtime and
resource contract.

## Public reviewer reference

The public `reviewer_only/` directory exposes material that would normally be
private: the exact grader, 144 hidden wider-angle states, 8 rollout initial
conditions with 126 time points, the true parameters, a correct submission,
and a deliberately incorrect model that removes every pair coupling.

The grader requires hidden field MSE at most `0.006` and rollout MSE at most
`0.035`. It also rejects invalid shapes, unsafe coefficients, non-positive
kinetic matrices, and malformed JSON contracts.

Run the positive and negative checks from the repository root:

```powershell
python examples/review/run_checks.py
```

This public fixture is for review only. Give a simulated participant only the
`participant/` directory. A real evaluation requires an unpublished seed and
private evaluator artifacts, not another predictable instance from this build.
