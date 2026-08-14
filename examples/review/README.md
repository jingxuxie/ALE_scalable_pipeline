# Concrete examples for review

This folder contains four complete, browsable task instances. Each example is
split into two parts:

- `participant/` contains the task description and inputs visible to the
  evaluated agent.
- `reviewer_only/` exposes the grading data that would normally be hidden: the
  grader, a correct answer, and a deliberately incorrect answer.

Do not give `reviewer_only/` to a participant. It is included here so task
authors and reviewers can inspect the full evaluation design.

These exact instances are public review fixtures, not secret benchmark
instances. Permanently retire instance `000` from scoring. A live benchmark
needs an unpublished seed or private source assets and private evaluator
artifacts; merely generating instance `001` from the committed seed and code
does not make it secret.

The included correct submissions are oracle references that test the positive
grader path. They do not demonstrate that an independent solver recovered the
answer from only the public inputs.

| Example | What it demonstrates |
| --- | --- |
| [Generic affine recovery](generic-affine/README.md) | A compact task produced by the declarative generic compiler. |
| [HNN coupled identification](hnn-coupled-identification/README.md) | Recovers a nonlinear three-degree-of-freedom Hamiltonian from noisy derivatives. |
| [HNN variable-N gravity](hnn-variable-nbody/README.md) | Computes energies and canonical dynamics for changing body counts and close encounters. |
| [HNN canonical recovery](hnn-canonical-recovery/README.md) | Recovers hidden canonical coordinates and a nonlinear Hamiltonian jointly. |

From the repository root, verify all four examples with:

```powershell
python examples/review/run_checks.py
```

The command must show that each correct submission passes and each incorrect
submission fails. `review_manifest.json` in each example records the exact
source build and SHA-256 digest of every copied task artifact.

To share all examples as one file after cloning the repository:

```powershell
git archive --format=zip --output paper2ale-review-examples.zip HEAD examples/review
```
