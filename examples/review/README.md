# Concrete examples for review

This folder contains two complete, browsable task instances. Each example is
split into two parts:

- `participant/` contains the task description and inputs visible to the
  evaluated agent.
- `reviewer_only/` contains the hidden grading data, grader, a correct answer,
  and a deliberately incorrect answer.

Do not give `reviewer_only/` to a participant. It is included here so task
authors and reviewers can inspect the full evaluation design.

These exact instances are public review fixtures, not secret benchmark
instances. Generate different, private instances before using a task to score
agents.

| Example | What it demonstrates |
| --- | --- |
| [Generic affine recovery](generic-affine/README.md) | A compact task produced by the declarative generic compiler. |
| [Hard HNN canonical recovery](hnn-canonical-recovery/README.md) | A paper-grounded scientific task with noisy observations, starter code, hidden physical tests, and a private grader. |

From the repository root, verify both examples with:

```powershell
python examples/review/run_checks.py
```

The command must show that each correct submission passes and each incorrect
submission fails. `review_manifest.json` in each example records the exact
source build and SHA-256 digest of every copied task artifact.

To share both examples as one file after cloning the repository:

```powershell
git archive --format=zip --output paper2ale-review-examples.zip HEAD examples/review
```
