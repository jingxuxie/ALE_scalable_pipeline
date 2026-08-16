# Public tooling

`validate_submission.py` checks only the one-file inventory, file safety, size,
UTF-8 decoding, and Python syntax.  It deliberately contains no reference
results, thresholds, hidden cases, or scientific implementation.

From the task root:

```text
python participant/software/validate_submission.py output
python output/solution.py --experiment participant/input/retired_experiment --output public_result.json
```
