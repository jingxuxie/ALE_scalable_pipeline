# Generic affine-recovery review example

This is instance `000` of `generic-hard-affine-recovery`.

## Participant materials

The [task description](participant/description.md) asks the participant to
infer a numeric transformation from worked examples. The complete public
[input](participant/input.json) contains those examples, the query rows, and
the required JSON output format. The [task card](participant/task_card.json)
records the runtime and resource contract.

The hidden answer is not present anywhere under `participant/`.

Concretely, this hard instance provides 8 worked examples of a three-input,
two-output affine map and asks for 154 predictions. Unrelated context fields
are included as decoys. The participant must return every query ID with the
correct two-number output and no extra JSON fields.

## Evaluation reference

The `reviewer_only/` directory contains:

- `reference/grader.py`: the exact private grader;
- `reference/instances/000/evaluation.json`: expected query outputs, metrics,
  thresholds, and hard checks;
- `examples/correct_submission.json`: a known-correct output;
- `examples/incorrect_submission.json`: a plausible but wrong output that the
  grader must reject.

The grader recomputes root-mean-square and maximum absolute error for all 154
hidden answers. It also rejects duplicate or missing query IDs, wrong shapes,
non-finite numbers, extra JSON structure, and oversized files.

Run the shared check from the repository root:

```powershell
python examples/review/run_checks.py
```

This directory is for review, so it intentionally contains private answers.
Only `participant/` belongs in a participant-facing package. Because the
answers are public here, do not reuse this exact instance in an evaluation.
