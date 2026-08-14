# Generic affine-recovery review example

This is instance `000` of `generic-hard-affine-recovery`.

## Participant materials

The full [task description](participant/description.md) states the affine
equation, explains every input section, gives the exact output JSON shape,
lists the scoring thresholds, and suggests a least-squares approach. The
complete public [input](participant/input.json) contains the worked examples,
query rows, and machine-readable output contract. The
[task card](participant/task_card.json) records the runtime and resource
contract.

The hidden answer is not present anywhere under `participant/`.

Concretely, this hard instance provides 8 worked examples of a three-input,
two-output affine map and asks for 154 predictions. Unrelated context fields
are included as decoys. The participant must return every query ID with the
correct two-number output and no extra JSON fields.

## Evaluation reference

The public `reviewer_only/` directory contains:

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

This directory is for review, so it intentionally exposes answers that would
normally be private. The golden output is an evaluator oracle, not evidence
that an independent solver inferred the rule. Only `participant/` belongs in a
participant-facing package. Instance `000` is permanently retired from live
evaluation; a real benchmark also needs unpublished seeds and reference data.
