# Hard HNN canonical-recovery review example

This is instance `000` of `hnn-hard-canonical-recovery`, grounded in the
Hamiltonian Neural Networks workflow.

## Participant materials

The [task description](participant/description.md) asks the participant to
recover both a latent canonical coordinate transform and a coupled quartic
Hamiltonian. The public [observations](participant/observations.json) contain
noisy training states and derivatives. `participant/starter/` provides a
runnable output template and its dependency declaration.

The participant must submit a bounded JSON artifact. The task does not accept
participant code inside the evaluator.

Concretely, the input contains 360 noisy training state/derivative pairs and
100 validation pairs in four mixed observed coordinates. The submitted model
must contain a 4-by-4 canonicalizing transform, two 2-by-2 positive-definite
quadratic matrices, and three quartic coefficients.

## Public reviewer reference

The public `reviewer_only/` directory exposes material that would normally be
private:

- `reference/grader.py`: the exact private NumPy grader;
- `reference/instances/000/truth.json`: hidden higher-energy states, rollout
  cases, true parameters, and thresholds;
- `examples/correct_submission.json`: a known-correct recovered model;
- `examples/incorrect_submission.json`: a model that incorrectly assumes the
  observed coordinates are already canonical.

The grader compares the induced vector field and integrated trajectories, not
just raw coefficient equality. It evaluates 176 hidden higher-energy states
and 9 hidden rollouts with 141 time points each. Field MSE must be at most
`0.008`, and rollout MSE must be at most `0.045`. Run both positive and
negative checks with:

```powershell
python examples/review/run_checks.py
```

Only `participant/` belongs in a participant-facing package. Because the
answers are public here, do not reuse this exact instance in an evaluation;
use an unpublished seed and keep the new evaluator artifacts private.
